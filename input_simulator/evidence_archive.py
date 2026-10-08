"""Bounded original observation segments, not run verdicts or attestations."""

import base64
import binascii
from collections import Counter
from contextlib import contextmanager, ExitStack
from dataclasses import asdict, dataclass, fields
import hashlib
import os
from pathlib import Path
import platform
import re

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, check_json_domain, loads
from icd_runtime.wire import Header
from .dispatch import DispatchRecord, UDPDispatcher
from .evidence import EvidenceInbox, EvidenceRecord
from .session import SourceExchange, SourceSession


MAX_BYTES = 256 * 1024 * 1024
DEFAULT_BYTES = 64 * 1024 * 1024
RECORD_TYPES = {'SOURCE': SourceExchange, 'DISPATCH': DispatchRecord, 'INBOX': EvidenceRecord}
NATIVE_STREAMS = frozenset(('SOURCE', 'DISPATCH', 'INBOX', 'CAN', 'L2'))
SCENARIO_STREAMS = NATIVE_STREAMS | {'PLAN', 'NATIVE_ACTION', 'SCENARIO'}
ASSERTION_STREAMS = SCENARIO_STREAMS | {'STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE'}
TARGET_STREAMS = SCENARIO_STREAMS | {'TARGET_AUTHORIZATION','MODEL_EPOCH'}
FULL_RUNTIME_STREAMS = ASSERTION_STREAMS | {'TARGET_AUTHORIZATION','MODEL_EPOCH'}
FORMAT_STREAMS = {'HIL_OBSERVATION_SEGMENT_1': frozenset(RECORD_TYPES),
                  'HIL_OBSERVATION_SEGMENT_2': NATIVE_STREAMS,
                  'HIL_OBSERVATION_SEGMENT_3': SCENARIO_STREAMS,
                  'HIL_OBSERVATION_SEGMENT_4': ASSERTION_STREAMS,
                  'HIL_OBSERVATION_SEGMENT_5': TARGET_STREAMS,
                  'HIL_OBSERVATION_SEGMENT_6': FULL_RUNTIME_STREAMS}
BYTE_FIELDS = {'request_json', 'reply_json', 'wire_data'}
TIME_FIELDS = {'started_ns', 'completed_ns', 'at_ns', 'received_ns'}
MANIFEST_KEYS = frozenset(('format', 'status', 'run_id', 'baseline_sha256', 'component_hashes',
                          'channel', 'session_id', 'session_state', 'pending_count', 'dropped_feedback',
                          'runtime', 'records_sha256', 'records_size_bytes', 'record_count', 'stream_counts',
                          'execution_ready', 'qualification_status', 'evidence_complete', 'raw_capture_scope'))


def _limits(max_records, max_bytes):
    if (type(max_records) is not int or not 1 <= max_records <= 100000 or
            type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES):
        raise ICDError('CAPACITY', 'bounded integral archive count/byte limits required')


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _uint(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ICDError('RESOURCE', 'archive integer has wrong type/range')
    return value


def _text(value, maximum=128):
    check_json_domain(value)
    if type(value) is not str or not 1 <= len(value) <= maximum:
        raise ICDError('RESOURCE', 'archive string has wrong type/range')
    return value


def _encode_record(stream, record):
    if stream in ('TARGET_AUTHORIZATION','MODEL_EPOCH'):
        from ._target_evidence import encode_target_record
        return encode_target_record(stream,record)
    if stream in ('STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE'):
        from ._assertion_evidence import encode_assertion_record
        return encode_assertion_record(stream,record)
    if stream in ('PLAN', 'NATIVE_ACTION', 'SCENARIO'):
        from ._scenario_evidence import encode_scenario_record
        return encode_scenario_record(stream, record)
    if stream in ('CAN', 'L2'):
        from ._native_evidence import encode_native_record
        return encode_native_record(stream, record)
    if type(record) is not RECORD_TYPES[stream]:
        raise ICDError('STATE', 'original typed observation record required')
    row = {}
    for field in fields(record):
        name, value = field.name, getattr(record, field.name)
        if value is not None:
            if name in BYTE_FIELDS:
                if type(value) is not bytes:
                    raise ICDError('STATE', 'original immutable record bytes required')
                value = base64.b64encode(value).decode('ascii')
            elif name in TIME_FIELDS:
                value = str(_uint(value, 2**64-1))
            elif name == 'header':
                if type(value) is not Header:
                    raise ICDError('STATE', 'original Header required')
                value = asdict(value)
            elif name == 'peer':
                value = list(value)
        row[name] = value
    result = {'stream': stream, 'record': row}
    _decode_record(result)
    return canonicalize(result) + b'\n'


def _decode_record(row):
    if type(row) is dict and row.get('stream') in ('TARGET_AUTHORIZATION','MODEL_EPOCH'):
        from ._target_evidence import decode_target_record
        return decode_target_record(row)
    if type(row) is dict and row.get('stream') in ('STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE'):
        from ._assertion_evidence import decode_assertion_record
        return decode_assertion_record(row)
    if type(row) is dict and row.get('stream') in ('PLAN', 'NATIVE_ACTION', 'SCENARIO'):
        from ._scenario_evidence import decode_scenario_record
        return decode_scenario_record(row)
    if type(row) is dict and row.get('stream') in ('CAN', 'L2'):
        from ._native_evidence import decode_native_record
        return decode_native_record(row)
    if type(row) is not dict or set(row) != {'stream', 'record'} or row['stream'] not in RECORD_TYPES:
        raise ICDError('RESOURCE', 'closed original observation stream required')
    stream, value = row['stream'], row['record']
    cls = RECORD_TYPES[stream]
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ICDError('RESOURCE', 'closed original observation fields required')
    decoded = {}
    for name, item in value.items():
        if name in BYTE_FIELDS:
            if item is not None:
                if type(item) is not str:
                    raise ICDError('RESOURCE', 'original bytes must be explicit base64')
                try:
                    raw = base64.b64decode(item, validate=True)
                except (binascii.Error, ValueError) as error:
                    raise ICDError('RESOURCE', 'invalid observation base64') from error
                if base64.b64encode(raw).decode('ascii') != item:
                    raise ICDError('RESOURCE', 'noncanonical observation base64')
                if name.endswith('_json'):
                    loads(raw)
                item = raw
        elif name in TIME_FIELDS:
            if item is not None:
                if type(item) is not str or re.fullmatch(r'0|[1-9][0-9]{0,19}', item) is None:
                    raise ICDError('RESOURCE', 'original uint64 time must be decimal string')
                item = _uint(int(item), 2**64-1)
            elif name in ('started_ns', 'received_ns'):
                raise ICDError('RESOURCE', 'original receive/start time required')
        elif name == 'header':
            if type(item) is not dict or set(item) != {f.name for f in fields(Header)}:
                raise ICDError('RESOURCE', 'complete original Header required')
            for key, number in item.items():
                _uint(number, 65535 if key == 'valid_for_ms' else 2**32-1)
            item = Header(**item)
        elif name == 'kind':
            kinds = ('DATAGRAM', 'EVIDENCE') if stream == 'INBOX' else (
                'SUBMITTED', 'TX', 'RX', 'COMPLETE', 'FAILED', 'TIMEOUT', 'CANCEL')
            if type(item) is not str or item not in kinds:
                raise ICDError('RESOURCE', 'unknown original observation kind')
        elif name == 'peer':
            if type(item) is not list or len(item) != 2:
                raise ICDError('RESOURCE', 'original IPv4 UDP peer pair required')
            _text(item[0])
            _uint(item[1], 65535)
            item = tuple(item)
        elif name == 'channel':
            if type(item) is not str or item not in tuple(f'ETH_{i}' for i in range(4)):
                raise ICDError('RESOURCE', 'original standard UDP channel required')
        elif name == 'correlation_matched':
            if type(item) is not bool:
                raise ICDError('RESOURCE', 'explicit observation correlation boolean required')
        elif name == 'error':
            if item is not None:
                _text(item)
        elif name == 'attempt':
            _uint(item, 2**32-1)
        elif name == 'fragment_index':
            if item is not None:
                _uint(item, 65535)
        decoded[name] = item
    if stream == 'SOURCE' and decoded['request_json'] is None:
        raise ICDError('RESOURCE', 'source exchange must retain original request')
    if stream == 'INBOX':
        if decoded['kind'] == 'DATAGRAM' and (decoded['wire_data'] is None or decoded['reply_json'] is not None):
            raise ICDError('RESOURCE', 'datagram must retain original wire bytes')
        if decoded['kind'] == 'EVIDENCE' and (decoded['reply_json'] is None or decoded['wire_data'] is not None):
            raise ICDError('RESOURCE', 'logical observation must retain original reply')
        if decoded['correlation_matched'] and (decoded['request_json'] is None or decoded['error'] is not None):
            raise ICDError('RESOURCE', 'matched claim requires original request without correlation error')
    return cls(**decoded)


def _validate(archive, *, contract=None, max_records=100000, max_bytes=DEFAULT_BYTES):
    _limits(max_records, max_bytes)
    if type(archive.records_jsonl) is not bytes or type(archive.manifest_json) is not bytes:
        raise ICDError('RESOURCE', 'immutable archive bytes required')
    if len(archive.records_jsonl) + len(archive.manifest_json) > max_bytes:
        raise ICDError('CAPACITY', 'archive exceeds complete byte bound')
    try:
        manifest = loads(archive.manifest_json)
        if type(manifest) is not dict or set(manifest) != MANIFEST_KEYS:
            raise ICDError('RESOURCE', 'closed archive manifest required')
        if (type(manifest['format']) is not str or manifest['format'] not in FORMAT_STREAMS or
                manifest['status'] != 'OBSERVATIONS_SAVED_NOT_RUN_VERDICT' or
                manifest['execution_ready'] is not False or manifest['evidence_complete'] is not False or
                manifest['qualification_status'] != 'NOT_EVALUATED' or
                manifest['raw_capture_scope'] != 'ONLY_ORIGINAL_RETAINED_RECORDS_NOT_WHOLE_RUN'):
            raise ICDError('RESOURCE', 'archive cannot claim execution or complete qualified evidence')
        streams = FORMAT_STREAMS[manifest['format']]
        _text(manifest['run_id'])
        if (type(manifest['baseline_sha256']) is not str or
                re.fullmatch('[0-9a-f]{64}', manifest['baseline_sha256']) is None or
                type(manifest['component_hashes']) is not dict or len(manifest['component_hashes']) != 4 or
                any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None
                    for v in manifest['component_hashes'].values())):
            raise ICDError('RESOURCE', 'actual baseline component hashes required')
        if contract is not None and (not isinstance(contract, Contract) or
                manifest['baseline_sha256'] != contract.baseline_sha256 or
                manifest['component_hashes'] != contract.component_hashes):
            raise ICDError('RESOURCE', 'archive differs from the actual frozen baseline')
        if (manifest['channel'] not in tuple(f'ETH_{i}' for i in range(4)) or
                manifest['session_state'] not in ('NEW', 'LIVE', 'ABANDONED', 'CLOSED')):
            raise ICDError('RESOURCE', 'original source state/channel required')
        if manifest['session_id'] is not None:
            _uint(manifest['session_id'], 2**32-1)
        _uint(manifest['pending_count'], 64)
        _uint(manifest['dropped_feedback'], 2**64-1)
        if (type(manifest['runtime']) is not dict or set(manifest['runtime']) != {'python', 'implementation', 'platform'}):
            raise ICDError('RESOURCE', 'closed observed host metadata required')
        for item in manifest['runtime'].values():
            _text(item, 1024)
        if (manifest['records_sha256'] != _digest(archive.records_jsonl) or
                type(manifest['records_size_bytes']) is not int or
                manifest['records_size_bytes'] != len(archive.records_jsonl)):
            raise ICDError('RESOURCE', 'original observation file hash/size differs')
        _uint(manifest['record_count'], 100000)
        if manifest['record_count'] > max_records:
            raise ICDError('CAPACITY', 'archive record count exceeds bound')
        if (type(manifest['stream_counts']) is not dict or set(manifest['stream_counts']) != streams or
                any(type(n) is not int or not 0 <= n <= max_records for n in manifest['stream_counts'].values())):
            raise ICDError('RESOURCE', 'closed original stream counts required')
        if not archive.records_jsonl.endswith(b'\n'):
            raise ICDError('RESOURCE', 'complete JSONL record terminator required')
        rows, counts = [], Counter()
        for line in archive.records_jsonl.splitlines():
            if len(rows) >= max_records:
                raise ICDError('CAPACITY', 'archive actual records exceed bound')
            row = loads(line)
            if type(row) is not dict or type(row.get('stream')) is not str or row['stream'] not in streams:
                raise ICDError('RESOURCE', 'row stream not allowed by original archive format')
            record = _decode_record(row)
            if contract is not None and row['stream'] in ('TARGET_AUTHORIZATION','MODEL_EPOCH'):
                from ._target_evidence import validate_target_record
                validate_target_record(record,contract)
            if contract is not None and row['stream'] in ('STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE'):
                from ._assertion_evidence import validate_assertion_record
                validate_assertion_record(record,contract)
            if canonicalize(row) != line:
                raise ICDError('RESOURCE', 'archive row encoding is not canonical')
            rows.append(record)
            counts[row['stream']] += 1
        if (len(rows) != manifest['record_count'] or
                {k:counts[k] for k in streams} != manifest['stream_counts'] or
                canonicalize(manifest) != archive.manifest_json):
            raise ICDError('RESOURCE', 'archive counts/manifest encoding differ')
        return manifest, tuple(rows)
    except ICDError as error:
        if error.code == 'CAPACITY':
            raise
        raise ICDError('RESOURCE', 'archive contents invalid or incomplete') from error
    except (TypeError, ValueError, KeyError) as error:
        raise ICDError('RESOURCE', 'archive closed structure invalid') from error


def _read_bounded(path, maximum):
    if path.is_symlink() or not path.is_file():
        raise OSError('regular original archive file required')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ICDError('CAPACITY', 'archive file exceeds remaining byte bound')
    return raw


@dataclass(frozen=True, slots=True)
class ObservationArchive:
    records_jsonl: bytes
    manifest_json: bytes

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    @property
    def manifest(self):
        return _validate(self, max_bytes=MAX_BYTES)[0]

    @property
    def records(self):
        return _validate(self, max_bytes=MAX_BYTES)[1]

    def write_new_directory(self, path):
        _validate(self, max_bytes=MAX_BYTES)
        try:
            target = Path(path)
            target.mkdir(parents=False, exist_ok=False)
            for name, raw in (('records.jsonl', self.records_jsonl), ('manifest.pending.json', self.manifest_json)):
                destination = target / name
                with destination.open('xb') as stream:
                    if stream.write(raw) != len(raw):
                        raise OSError('incomplete observation write')
                    stream.flush()
                    os.fsync(stream.fileno())
                if _read_bounded(destination, len(raw)) != raw:
                    raise OSError('observation readback differs')
            manifest = target / 'manifest.json'
            os.link(target / 'manifest.pending.json', manifest)
            return manifest
        except (OSError, TypeError, ValueError, ICDError) as error:
            raise ICDError('RESOURCE', 'exclusive observation persistence failed; owned incomplete directory retained') from error


def prepare_evidence_archive(dispatcher, *, run_id, inbox=None, max_records=100000, max_bytes=DEFAULT_BYTES):
    return _prepare_evidence_snapshot(dispatcher,run_id=run_id,inbox=inbox,
                                      max_records=max_records,max_bytes=max_bytes)[0]


def prepare_native_evidence_archive(dispatcher, *, run_id, coordinator=None, inbox=None,
                                    max_records=100000, max_bytes=DEFAULT_BYTES):
    return _prepare_native_evidence_snapshot(dispatcher, run_id=run_id, coordinator=coordinator,
        inbox=inbox, max_records=max_records, max_bytes=max_bytes)[0]


@contextmanager
def _native_owners(dispatcher, coordinator, inbox):
    from .native_tools import NativeToolCoordinator
    from .can_signal import CANSignalSender
    from .scapy_source import ScapySource
    if type(dispatcher) is not UDPDispatcher:
        raise ICDError('STATE', 'actual original native dispatcher required')
    session, transport = dispatcher.session, dispatcher.transport
    if (type(session) is not SourceSession or dispatcher._observation_owners != (
            session, transport, dispatcher.contract)):
        raise ICDError('STATE', 'native snapshot requires original dispatcher provenance')
    if coordinator is not None and (type(coordinator) is not NativeToolCoordinator
            or coordinator.dispatcher is not dispatcher or coordinator.session is not session
            or coordinator._observation_owners[:3] != (dispatcher, session, transport)):
        raise ICDError('STATE', 'actual same-session native coordinator required')
    with ExitStack() as stack:
        if coordinator is not None:
            stack.enter_context(coordinator._operation(closed_ok=True))
        stack.enter_context(dispatcher._operation(closed_ok=True))
        senders = () if coordinator is None else coordinator.senders
        if coordinator is not None and (senders is not coordinator._observation_owners[3]
                or type(senders) is not tuple or not 1 <= len(senders) <= 4
                or any(type(s) is not CANSignalSender for s in senders)
                or any(s is not pinned[0] or s.builder is not pinned[1]
                       or s.binding is not pinned[2] or s.book is not pinned[3]
                       for s, pinned in zip(senders, coordinator._observation_owners[4]))):
            raise ICDError('STATE', 'native snapshot cannot replace original sender/builder/binding')
        builders = set()
        for sender in senders:
            if not sender._lock.acquire(blocking=False):
                raise ICDError('STATE', 'native sender snapshot requires its serialized owner')
            stack.callback(sender._lock.release)
            if id(sender.builder) not in builders:
                if not sender.builder._lock.acquire(blocking=False):
                    raise ICDError('STATE', 'native builder snapshot requires its serialized owner')
                stack.callback(sender.builder._lock.release)
                builders.add(id(sender.builder))
        stack.enter_context(session._operation(owner=dispatcher, closed_ok=True))
        if (dispatcher.session is not session or dispatcher.transport is not transport
                or session.transport is not transport or session._dispatcher not in (None, dispatcher)
                or transport._session_owner is not session):
            raise ICDError('STATE', 'native snapshot cannot adopt replaced source owners')
        if coordinator is None:
            if session._native_tool_coordinator is not None or type(transport) is not ScapySource:
                raise ICDError('STATE', 'explicit current native coordinator or actual Scapy source required')
        elif (coordinator.senders is not senders or
              session._native_tool_coordinator is not coordinator and not (
                  coordinator._closed and session._native_tool_coordinator is None) or
              any(s.session is not session or s.builder.session is not session
                  or s.book is not s.builder.book or s.contract is not session.contract for s in senders)):
            raise ICDError('STATE', 'native snapshot no longer owns the original senders')
        selected = dispatcher._evidence_inbox if inbox is None else inbox
        if selected is not None and (type(selected) is not EvidenceInbox or
                selected._owner is not dispatcher or selected.session is not session):
            raise ICDError('STATE', 'original same-owner evidence inbox required')
        if type(transport) is ScapySource:
            if not transport._l2_lock.acquire(blocking=False):
                raise ICDError('STATE', 'Scapy snapshot cannot overlap original TX/close')
            stack.callback(transport._l2_lock.release)
        yield session, transport, senders, selected


def _native_streams(dispatcher, owners):
    from .scapy_source import ScapySource
    session, transport, senders, inbox = owners
    return {'SOURCE': session.records, 'DISPATCH': dispatcher.records,
            'INBOX': () if inbox is None else inbox.records,
            'CAN': tuple(row for sender in senders for row in sender.records),
            'L2': transport.l2_records if type(transport) is ScapySource else ()}


def _prepare_native_evidence_snapshot(dispatcher, *, run_id, coordinator=None, inbox=None,
                                       max_records=100000, max_bytes=DEFAULT_BYTES):
    _limits(max_records, max_bytes)
    try:
        _text(run_id)
    except ICDError as error:
        raise ICDError('SCHEMA', 'explicit valid run identity required') from error
    with _native_owners(dispatcher, coordinator, inbox) as owners:
        streams = _native_streams(dispatcher, owners)
        archive = _build_archive(dispatcher, streams, run_id=run_id, native=True,
                                 max_records=max_records, max_bytes=max_bytes)
        return archive, streams, tuple(sender.records for sender in owners[2])


def _build_archive(dispatcher, streams, *, run_id, native=False, scenario=False, assertions=False, targets=False, max_records, max_bytes):
    count = sum(len(rows) for rows in streams.values())
    if not 1 <= count <= max_records:
        raise ICDError('CAPACITY', 'bounded nonempty observation snapshot required')
    encoded, total = [], 0
    for stream, records in streams.items():
        for record in records:
            line = _encode_record(stream, record)
            total += len(line)
            if total > max_bytes:
                raise ICDError('CAPACITY', 'observation snapshot byte bound exceeded')
            encoded.append(line)
    raw, session = b''.join(encoded), dispatcher.session
    manifest = {
        'format': ('HIL_OBSERVATION_SEGMENT_6' if assertions else 'HIL_OBSERVATION_SEGMENT_5') if targets else 'HIL_OBSERVATION_SEGMENT_4' if assertions else 'HIL_OBSERVATION_SEGMENT_3' if scenario else 'HIL_OBSERVATION_SEGMENT_2' if native else 'HIL_OBSERVATION_SEGMENT_1',
        'status':'OBSERVATIONS_SAVED_NOT_RUN_VERDICT',
        'run_id':run_id, 'baseline_sha256':dispatcher.contract.baseline_sha256,
        'component_hashes':dict(dispatcher.contract.component_hashes), 'channel':dispatcher.transport.channel,
        'session_id':session.session_id, 'session_state':session._state,
        'pending_count':dispatcher.pending_count, 'dropped_feedback':dispatcher.transport.dropped_feedback,
        'runtime':{'python':platform.python_version(), 'implementation':platform.python_implementation(),
                   'platform':platform.platform()},
        'records_sha256':_digest(raw), 'records_size_bytes':len(raw), 'record_count':count,
        'stream_counts':{stream:len(records) for stream, records in streams.items()},
        'execution_ready':False, 'qualification_status':'NOT_EVALUATED', 'evidence_complete':False,
        'raw_capture_scope':'ONLY_ORIGINAL_RETAINED_RECORDS_NOT_WHOLE_RUN'}
    archive = ObservationArchive(raw, canonicalize(manifest))
    _validate(archive, contract=dispatcher.contract, max_records=max_records, max_bytes=max_bytes)
    return archive


def _prepare_evidence_snapshot(dispatcher, *, run_id, inbox=None, max_records=100000, max_bytes=DEFAULT_BYTES):
    _limits(max_records, max_bytes)
    try:
        _text(run_id)
    except ICDError as error:
        raise ICDError('SCHEMA', 'explicit valid run identity required') from error
    if not isinstance(dispatcher, UDPDispatcher):
        raise ICDError('STATE', 'actual original dispatcher required')
    with dispatcher._operation(closed_ok=True):
        session = dispatcher.session
        if not session._lock.acquire(blocking=False):
            raise ICDError('STATE', 'source observation snapshot requires its serialized owner')
        try:
            if session._dispatcher not in (None, dispatcher):
                raise ICDError('STATE', 'source is owned by another dispatcher')
            selected = dispatcher._evidence_inbox if inbox is None else inbox
            if selected is not None and (type(selected) is not EvidenceInbox or
                    selected._owner is not dispatcher or selected.session is not session):
                raise ICDError('STATE', 'original same-owner evidence inbox required')
            streams = {'SOURCE':session.records, 'DISPATCH':dispatcher.records,
                       'INBOX':() if selected is None else selected.records}
            archive = _build_archive(dispatcher, streams, run_id=run_id,
                                     max_records=max_records, max_bytes=max_bytes)
            return archive, streams
        finally:
            session._lock.release()


def read_evidence_archive(path, contract, *, max_records=100000, max_bytes=DEFAULT_BYTES):
    _limits(max_records, max_bytes)
    if not isinstance(contract, Contract) or not contract.component_hashes:
        raise ICDError('RESOURCE', 'actual frozen contract required for readback')
    try:
        target = Path(path)
        if target.is_symlink() or not target.is_dir():
            raise OSError('original archive directory required')
        names = set()
        with os.scandir(target) as entries:
            for entry in entries:
                if entry.name not in ('records.jsonl', 'manifest.json', 'manifest.pending.json') or len(names) >= 3:
                    raise OSError('archive has extra files')
                names.add(entry.name)
        if names not in ({'records.jsonl', 'manifest.json'}, {'records.jsonl', 'manifest.json', 'manifest.pending.json'}):
            raise OSError('archive directory incomplete or has extra files')
        manifest = _read_bounded(target / 'manifest.json', max_bytes)
        records = _read_bounded(target / 'records.jsonl', max_bytes-len(manifest))
        if 'manifest.pending.json' in names:
            if _read_bounded(target / 'manifest.pending.json', len(manifest)) != manifest:
                raise OSError('pending manifest differs from published original')
        archive = ObservationArchive(records, manifest)
        _validate(archive, contract=contract, max_records=max_records, max_bytes=max_bytes)
        return archive
    except ICDError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise ICDError('RESOURCE', 'original observation archive readback failed') from error
