"""Single bounded original observation writer; never a qualified run verdict."""

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .dispatch import UDPDispatcher
from .evidence import EvidenceInbox
from .evidence_archive import (MAX_BYTES, DEFAULT_BYTES, _digest, _read_bounded, _text, _uint,
                               _prepare_evidence_snapshot, read_evidence_archive,
                               _native_owners, _native_streams, _prepare_native_evidence_snapshot, _build_archive)


STREAMS = ('SOURCE', 'DISPATCH', 'INBOX')
NATIVE_STREAMS = STREAMS + ('CAN', 'L2')
SCENARIO_STREAMS = NATIVE_STREAMS + ('PLAN', 'NATIVE_ACTION', 'SCENARIO')
ASSERTION_STREAMS = SCENARIO_STREAMS + ('STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE')
TARGET_STREAMS = SCENARIO_STREAMS + ('TARGET_AUTHORIZATION','MODEL_EPOCH')
FULL_RUNTIME_STREAMS = ASSERTION_STREAMS + ('TARGET_AUTHORIZATION','MODEL_EPOCH')
FORMAT_STREAMS = {f'HIL_OBSERVATION_SEGMENT_{i}': streams
                  for i, streams in enumerate((STREAMS, NATIVE_STREAMS, SCENARIO_STREAMS,
                                               ASSERTION_STREAMS,TARGET_STREAMS,FULL_RUNTIME_STREAMS), 1)}
DESCRIPTOR_BYTES = 16384
LINK_KEYS = frozenset(('format', 'index', 'segment', 'run_id', 'baseline_sha256', 'previous_sha256',
                       'archive_manifest_sha256', 'archive_records_sha256', 'stream_start_counts',
                       'stream_end_counts', 'dropped_feedback_before', 'dropped_feedback_after',
                       'execution_ready', 'qualification_status', 'evidence_complete'))
CLOSE_KEYS = frozenset(('format', 'run_id', 'baseline_sha256', 'committed_segments',
                        'tip_sha256', 'stream_counts', 'persisted_segment_bytes', 'unpersisted_counts',
                        'worker_stopped', 'error', 'execution_ready', 'qualification_status', 'evidence_complete'))


@contextmanager
def _owners(dispatcher):
    with dispatcher._operation(closed_ok=True):
        session = dispatcher.session
        if not session._lock.acquire(blocking=False):
            raise ICDError('STATE', 'serialized source record owner required')
        try:
            if session._dispatcher not in (None, dispatcher):
                raise ICDError('STATE', 'source records have another dispatcher owner')
            yield
        finally:
            session._lock.release()


def _streams(dispatcher, inbox):
    return {'SOURCE':dispatcher.session.records, 'DISPATCH':dispatcher.records,
            'INBOX':() if inbox is None else inbox.records}


def _limits(max_segments, max_records, max_bytes, max_total_bytes):
    if (type(max_segments) is not int or not 1 <= max_segments <= 100000 or
            type(max_records) is not int or not 1 <= max_records <= 100000 or
            type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES or
            type(max_total_bytes) is not int or not 1 <= max_total_bytes <= 1024**3):
        raise ICDError('CAPACITY', 'strict bounded recorder limits required')


def _link(raw, archive, *, index, run_id, previous, counts, dropped_before):
    try:
        value, manifest = loads(raw), archive.manifest
        profile = manifest['format'].rsplit('_', 1)[1]
        streams = FORMAT_STREAMS[manifest['format']]
        if (type(value) is not dict or set(value) != LINK_KEYS or
                value['format'] != f'HIL_OBSERVATION_CHAIN_LINK_{profile}' or
                type(value['index']) is not int or value['index'] != index or
                value['segment'] != f'segment-{index:06d}' or value['run_id'] != run_id or
                value['baseline_sha256'] != manifest['baseline_sha256'] or
                value['previous_sha256'] != previous or
                value['archive_manifest_sha256'] != _digest(archive.manifest_json) or
                value['archive_records_sha256'] != _digest(archive.records_jsonl) or
                value['execution_ready'] is not False or value['evidence_complete'] is not False or
                value['qualification_status'] != 'NOT_EVALUATED'):
            raise ICDError('RESOURCE', 'observation chain identity/hash/qualification differs')
        for name in ('stream_start_counts', 'stream_end_counts'):
            if type(value[name]) is not dict or set(value[name]) != set(streams):
                raise ICDError('RESOURCE', 'closed observation stream counts required')
            for count in value[name].values():
                _uint(count, 10**10)
        end = {k:counts[k]+manifest['stream_counts'][k] for k in streams}
        if value['stream_start_counts'] != counts or value['stream_end_counts'] != end:
            raise ICDError('RESOURCE', 'observation chain stream continuity differs')
        before = _uint(value['dropped_feedback_before'], 2**53-1)
        after = _uint(value['dropped_feedback_after'], 2**53-1)
        if before != dropped_before or after < before or after != manifest['dropped_feedback']:
            raise ICDError('RESOURCE', 'observed drop counters differ or reverse')
        if canonicalize(value) != raw:
            raise ICDError('RESOURCE', 'observation link encoding differs')
        return value
    except ICDError as error:
        raise ICDError('RESOURCE', 'invalid or incomplete original observation chain link') from error
    except (TypeError, KeyError, ValueError) as error:
        raise ICDError('RESOURCE', 'closed observation chain structure required') from error


@dataclass(frozen=True, slots=True)
class RecorderCloseout:
    committed_segments: int
    counts: tuple
    worker_stopped: bool
    error: str | None
    streams: tuple = STREAMS

    @property
    def unpersisted_counts(self):
        return dict(zip(self.streams, self.counts))


@dataclass(frozen=True, slots=True)
class ObservationChain:
    segments: tuple
    descriptor_jsons: tuple
    locally_closed: bool = False

    @property
    def execution_ready(self):
        return False

    @property
    def evidence_complete(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


@dataclass(slots=True)
class _Job:
    archive: object
    prefix: dict
    descriptor: bytes
    directory: Path
    native_prefix: tuple = ()
    thread: object = None
    error: str | None = None


class ObservationRecorder:
    def __init__(self, dispatcher, path, *, run_id, inbox=None, max_segments=10000,
                 max_records=100000, max_bytes=DEFAULT_BYTES, max_total_bytes=MAX_BYTES,
                 native=False, coordinator=None, native_actions=None, execution=None, assertions=None, targets=None):
        _limits(max_segments, max_records, max_bytes, max_total_bytes)
        try:
            _text(run_id)
        except ICDError as error:
            raise ICDError('SCHEMA', 'explicit valid recording identity required') from error
        if not isinstance(dispatcher, UDPDispatcher):
            raise ICDError('STATE', 'original actual dispatcher required')
        if type(native) is not bool or not native and coordinator is not None:
            raise ICDError('STATE', 'explicit native recording mode required for coordinator')
        self._dispatcher = dispatcher
        self._source, self._transport = dispatcher.session, dispatcher.transport
        self._native, self._coordinator = native, coordinator
        self._actions, self._execution = native_actions, execution
        self._assertions,self._reader=assertions,None
        self._targets=targets
        self._driver = None
        self._scenario = native_actions is not None
        self._attached = False
        self._history_prefix = {'NATIVE_ACTION': (), 'SCENARIO': ()}
        self._plan_saved = False
        if execution is not None and native_actions is None or self._scenario and not native:
            raise ICDError('STATE', 'original scenario recording requires explicit native actions and mode')
        if self._scenario:
            from .native_scenario_actions import NativeScenarioActions
            from .scenario_execution import ScenarioExecution
            from .scenario_driver import OriginalScenarioDriver
            from ._scenario_evidence import ScenarioPlanRecord
            if (type(native_actions) is not NativeScenarioActions or native_actions.session is not self._source
                    or native_actions.dispatcher is not dispatcher or native_actions.coordinator is not coordinator):
                raise ICDError('STATE', 'same original native action owner required')
            self._plan = native_actions.plan
            self._action_pins = (native_actions.session, native_actions.dispatcher, native_actions.coordinator,
                                 native_actions.sender, native_actions.plan, native_actions.contract)
            self._identity_json, self._sid = self._source._identity_json, native_actions._sid
            if self._sid is None:
                raise ICDError('STATE', 'original granted scenario SID required')
            self._plan_record = ScenarioPlanRecord(self._plan.scenario_json, self._identity_json,
                                                    self._plan.model_id, self._sid)
            if execution is not None:
                if type(execution) is not ScenarioExecution or type(execution._driver) is not OriginalScenarioDriver:
                    raise ICDError('STATE', 'actual original scenario controller/driver required')
                self._driver = execution._driver
                self._services = self._driver.services
                if (execution._plan is not self._plan or self._driver.plan is not self._plan
                        or self._driver.native is not native_actions or self._driver.session is not self._source
                        or self._services.session is not self._source):
                    raise ICDError('STATE', 'same complete original plan and service source required')
        if assertions is not None:
            from .scenario_assertions import StatusScenarioAssertions,StatusObservationReader
            if (not self._scenario or type(assertions) is not StatusScenarioAssertions
                    or assertions.plan is not self._plan or type(assertions.reader) is not StatusObservationReader
                    or assertions.reader is not assertions._reader or assertions.reader._source is not self._source
                    or assertions.reader.session is not self._source
                    or assertions.contract is not self._actions.contract
                    or self._driver is not None and self._services._assertions is not assertions):
                raise ICDError('STATE','explicit actual same-plan assertion owners required')
            self._reader=assertions.reader
            self._assertion_pins=(assertions.plan,assertions.contract,self._reader.clock,self._reader._sid,self._reader._model)
            self._history_prefix.update({name:() for name in ('STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE')})
        if targets is not None:
            from .runtime_targets import RuntimeTargetAuthorizer
            if (not self._scenario or type(targets) is not RuntimeTargetAuthorizer
                    or targets.plan is not self._plan or targets.session is not self._source
                    or self._driver is not None and self._services._targets is not targets):
                raise ICDError('STATE','explicit original same-plan target recording owner required')
            self._target_pins=(targets.backend,targets._backend,targets._contract,targets._transport,
                targets._models,targets.clock,targets.lease,targets._can_sender,targets._can_binding,targets._can_builder)
            self._history_prefix.update(TARGET_AUTHORIZATION=(),MODEL_EPOCH=())
        self._profile = 4 if assertions is not None else 3 if self._scenario else 2 if native else 1
        self._stream_names = ASSERTION_STREAMS if assertions is not None else SCENARIO_STREAMS if self._scenario else NATIVE_STREAMS if native else STREAMS
        if targets is not None:
            self._profile=6 if assertions is not None else 5
            self._stream_names=FULL_RUNTIME_STREAMS if assertions is not None else TARGET_STREAMS
        self._senders = () if coordinator is None else getattr(coordinator, 'senders', ())
        self._inbox = dispatcher._evidence_inbox if inbox is None else inbox
        if self._inbox is not None and (type(self._inbox) is not EvidenceInbox or
                self._inbox._owner is not dispatcher or self._inbox.session is not dispatcher.session):
            raise ICDError('STATE', 'same original observation inbox required')
        self._root, self._run_id = Path(path), run_id
        self._max_segments, self._max_records = max_segments, max_records
        self._max_bytes, self._max_total_bytes = max_bytes, max_total_bytes
        self._lock = threading.Lock()
        self._job = None
        self._commits = []
        self._counts = dict.fromkeys(self._stream_names, 0)
        self._previous = '0'*64
        self._used_bytes = 0
        self._failed = None
        self._closed = False
        self._closeout = None
        with self._owners():
            self._check_available_owner()
        try:
            self._root.mkdir(parents=False, exist_ok=False)
        except (OSError, TypeError, ValueError) as error:
            raise ICDError('RESOURCE', 'exclusive new recording root required') from error
        with self._owners():
            self._check_available_owner()
            self._dropped = dispatcher.transport.dropped_feedback
            dispatcher._observation_recorder = dispatcher.session._observation_recorder = self
            if self._scenario:
                self._actions._recording_owner = self
                if self._execution is not None:
                    self._execution._recording_owner = self
            if self._assertions is not None:
                self._assertions._recording_owner = self
            if self._targets is not None:
                self._targets._recording_owner=self
            self._attached = True

    @contextmanager
    def _owners(self):
        with ExitStack() as stack:
            if self._scenario:
                for owner in (self._execution, self._driver, self._actions):
                    if owner is not None:
                        if not owner._lock.acquire(blocking=False):
                            raise ICDError('STATE', 'original scenario record owner is busy')
                        stack.callback(owner._lock.release)
                if (not self._action_identity_matches(self._actions)
                        or self._driver is not None and (self._execution._driver is not self._driver
                            or self._execution._plan is not self._plan or self._driver.plan is not self._plan
                            or self._driver.native is not self._actions or self._driver.services is not self._services
                            or self._driver.session is not self._source or self._services.session is not self._source)):
                    raise ICDError('STATE', 'scenario recorder cannot adopt replaced original owners')
                if self._assertions is not None:
                    handler,reader=self._assertions,self._reader
                    if not handler._lock.acquire(blocking=False):
                        raise ICDError('STATE','actual assertion recording owner is busy')
                    stack.callback(handler._lock.release)
                    if not self._assertion_identity_matches(handler):
                        raise ICDError('STATE','original assertion reader/handler identity changed')
                    if self._attached and not self._closed and handler._recording_owner is not self:
                        raise ICDError('STATE','original assertion recording ownership changed')
                if self._attached and not self._closed and (getattr(self._actions, '_recording_owner', None) is not self
                        or self._execution is not None and getattr(self._execution, '_recording_owner', None) is not self):
                    raise ICDError('STATE', 'original scenario recording ownership changed')
                if self._targets is not None:
                    if not self._targets._lock.acquire(blocking=False):
                        raise ICDError('STATE','original target recording owner is busy')
                    stack.callback(self._targets._lock.release)
                    if not self._target_identity_matches(self._targets):
                        raise ICDError('STATE','original target recording owners changed')
                    if self._attached and not self._closed and self._targets._recording_owner is not self:
                        raise ICDError('STATE','original target recording attachment changed')
            if self._native:
                owners = stack.enter_context(_native_owners(self._dispatcher, self._coordinator, self._inbox))
                if owners[0] is not self._source or owners[1] is not self._transport or owners[2] is not self._senders:
                    raise ICDError('STATE', 'native recorder cannot adopt replaced original owners')
                if self._scenario:
                    self._actions._check_records()
                if self._assertions is not None and self._source._status_assertion_reader is not self._reader:
                    if not self._reader._closed or self._source._status_assertion_reader is not None:
                        raise ICDError('STATE','actual original Status reader attachment changed')
                yield owners
            else:
                stack.enter_context(_owners(self._dispatcher))
                yield None

    def _action_identity_matches(self, actions):
        if not self._scenario or actions is not self._actions:
            return False
        pins = (actions.session, actions.dispatcher, actions.coordinator,
                actions.sender, actions.plan, actions.contract)
        return (all(a is b for a,b in zip(pins, self._action_pins))
                and actions._sid == self._sid and self._source._identity_json is self._identity_json)

    def _owns_scenario_actions(self, actions):
        return (not self._closed and self._attached and self._action_identity_matches(actions)
                and (self._assertions is None or self._assertion_identity_matches(self._assertions))
                and (self._targets is None or self._target_identity_matches(self._targets))
                and self._source._observation_recorder is self
                and self._dispatcher._observation_recorder is self)

    def _assertion_identity_matches(self,handler):
        reader=self._reader
        return (handler is self._assertions and reader is not None
            and handler.reader is reader and handler._reader is reader
            and handler.plan is self._assertion_pins[0] and handler.contract is self._assertion_pins[1]
            and reader.clock is self._assertion_pins[2] and reader.clock.session is self._source
            and reader.session is self._source and reader._source is self._source
            and reader._sid==self._assertion_pins[3] and reader._model==self._assertion_pins[4]
            and (self._source._status_assertion_reader is reader
                 or reader._closed and self._source._status_assertion_reader is None)
            and (self._driver is None or self._services._assertions is handler))

    def _owns_assertions(self,handler):
        return (not self._closed and self._attached and self._assertion_identity_matches(handler)
            and self._source._observation_recorder is self and self._dispatcher._observation_recorder is self)

    def _target_identity_matches(self,targets):
        pins=(targets.backend,targets._backend,targets._contract,targets._transport,targets._models,
              targets.clock,targets.lease,targets._can_sender,targets._can_binding,targets._can_builder)
        return (targets is self._targets and all(a is b for a,b in zip(pins,self._target_pins))
            and targets.plan is self._plan and targets._plan is self._plan
            and targets.session is self._source and targets._source is self._source
            and self._source.contract is targets._contract and self._source.transport is targets._transport
            and targets.backend.contract is targets._contract and targets.backend.model_ids==targets._models
            and targets.clock.session is self._source and targets.lease.session is self._source
            and targets._identity==self._identity_json and targets._sid==self._sid
            and self._source.session_id in (None,self._sid)
            and (targets._can_sender is None or targets._can_sender is self._actions.sender
                and targets._can_sender.builder is targets._can_builder
                and targets._can_sender.binding is targets._can_binding
                and targets._can_builder.session is self._source)
            and (self._driver is None or self._services._targets is targets))

    def _owns_targets(self,targets):
        return (not self._closed and self._attached and self._target_identity_matches(targets)
            and targets._recording_owner is self and self._source._observation_recorder is self
            and self._dispatcher._observation_recorder is self)

    def _owns_native(self, coordinator, sender):
        return (self._native and not self._closed and coordinator is self._coordinator
                and (self._assertions is None or self._assertion_identity_matches(self._assertions))
                and (self._targets is None or self._target_identity_matches(self._targets))
                and coordinator is not None and coordinator.session is self._source
                and coordinator.dispatcher is self._dispatcher and coordinator.senders is self._senders
                and any(s is sender and s.builder is pinned[1] and s.binding is pinned[2]
                        and s.book is pinned[3] for s, pinned in zip(self._senders, coordinator._observation_owners[4]))
                and self._dispatcher.session is self._source and self._dispatcher.transport is self._transport
                and self._source._observation_recorder is self
                and self._dispatcher._observation_recorder is self)

    def _live_streams(self, owners):
        streams = (_native_streams(self._dispatcher, owners) if self._native
                   else _streams(self._dispatcher, self._inbox))
        if self._scenario:
            streams['PLAN'] = () if self._plan_saved else (self._plan_record,)
            histories={'NATIVE_ACTION':self._actions.records,
                       'SCENARIO':() if self._execution is None else self._execution.records}
            if self._assertions is not None:
                histories.update(STATUS_SAMPLE=self._reader.records,STATUS_FAILURE=self._reader.failure_records,
                    ASSERTION=self._assertions.records,ASSERTION_LIFECYCLE=self._assertions.lifecycle_records)
            if self._targets is not None:
                histories.update(TARGET_AUTHORIZATION=self._targets.records,MODEL_EPOCH=self._targets.epoch_records)
            for name,rows in histories.items():
                retained = self._history_prefix[name]
                if len(rows) < len(retained) or any(a is not b for a,b in zip(rows, retained)):
                    raise ICDError('STATE', 'retained original scenario history identity changed')
                streams[name] = rows[len(retained):]
        return streams

    def _check_available_owner(self):
        if (self._dispatcher._observation_recorder is not None or
                self._dispatcher.session._observation_recorder is not None or self._scenario and (
                getattr(self._actions, '_recording_owner', None) is not None or
                self._execution is not None and getattr(self._execution, '_recording_owner', None) is not None)
                or self._assertions is not None and self._assertions._recording_owner is not None):
            raise ICDError('STATE', 'one original recorder per dispatcher/source required')
        if self._targets is not None and self._targets._recording_owner is not None:
            raise ICDError('STATE','one original recorder per target owner required')

    @contextmanager
    def _operation(self, *, closed_ok=False):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'recording operations require one serialized owner')
        try:
            if self._closed and not closed_ok:
                raise ICDError('STATE', 'observation recorder permanently closed')
            if self._closeout is not None and not closed_ok:
                raise ICDError('STATE', 'local close checkpoint already sealed')
            yield
        finally:
            self._lock.release()

    @property
    def status(self):
        return 'CLOSED' if self._closed else 'FAILED' if self._failed else 'SAVING' if self._job else 'LIVE'

    @property
    def committed_segments(self):
        return len(self._commits)

    @property
    def tip_sha256(self):
        return self._previous

    @property
    def execution_ready(self):
        return False

    def flush(self):
        with self._operation():
            if self._failed:
                raise ICDError('STATE', 'failed observation writer cannot start a new segment')
            if self._job is not None:
                raise ICDError('BUFFER_FULL', 'poll original single write job before another snapshot')
            if len(self._commits) >= self._max_segments:
                raise ICDError('CAPACITY', 'bounded recording segment count exhausted')
            native_prefix = ()
            if self._scenario:
                with self._owners() as owners:
                    prefix = self._live_streams(owners)
                    native_prefix = tuple(sender.records for sender in self._senders)
                    archive = _build_archive(self._dispatcher, prefix, run_id=self._run_id,
                        native=True, scenario=True, assertions=self._assertions is not None,
                        targets=self._targets is not None,
                        max_records=self._max_records, max_bytes=self._max_bytes)
            elif self._native:
                with self._owners():
                    pass
                archive, prefix, native_prefix = _prepare_native_evidence_snapshot(self._dispatcher,
                    run_id=self._run_id, coordinator=self._coordinator, inbox=self._inbox,
                    max_records=self._max_records, max_bytes=self._max_bytes)
            else:
                archive, prefix = _prepare_evidence_snapshot(self._dispatcher, run_id=self._run_id, inbox=self._inbox,
                                                             max_records=self._max_records, max_bytes=self._max_bytes)
            manifest = archive.manifest
            index = len(self._commits)
            descriptor = canonicalize({
                'format':f'HIL_OBSERVATION_CHAIN_LINK_{self._profile}',
                'index':index, 'segment':f'segment-{index:06d}',
                'run_id':self._run_id, 'baseline_sha256':manifest['baseline_sha256'], 'previous_sha256':self._previous,
                'archive_manifest_sha256':_digest(archive.manifest_json), 'archive_records_sha256':_digest(archive.records_jsonl),
                'stream_start_counts':dict(self._counts),
                'stream_end_counts':{k:self._counts[k]+len(prefix[k]) for k in self._stream_names},
                'dropped_feedback_before':self._dropped, 'dropped_feedback_after':manifest['dropped_feedback'],
                'execution_ready':False, 'qualification_status':'NOT_EVALUATED', 'evidence_complete':False})
            _link(descriptor, archive, index=index, run_id=self._run_id, previous=self._previous,
                  counts=self._counts, dropped_before=self._dropped)
            size = len(archive.records_jsonl)+len(archive.manifest_json)+len(descriptor)
            if len(descriptor) > DESCRIPTOR_BYTES or self._used_bytes+size > self._max_total_bytes:
                raise ICDError('CAPACITY', 'bounded recording total byte capacity exhausted')
            job = _Job(archive, prefix, descriptor, self._root/f'segment-{index:06d}', native_prefix)
            job.thread = threading.Thread(target=self._write, args=(job,), name='icd-observation-storage', daemon=False)
            self._job = job
            try:
                job.thread.start()
            except RuntimeError as error:
                job.error = self._failed = 'STATE'
                raise ICDError('STATE', 'original observation worker failed to start') from error
            return index

    def _write(self, job):
        try:
            job.archive.write_new_directory(job.directory)
            pending, final = job.directory.with_suffix('.pending.json'), job.directory.with_suffix('.json')
            with pending.open('xb') as stream:
                if stream.write(job.descriptor) != len(job.descriptor):
                    raise OSError('incomplete observation commit write')
                stream.flush()
                os.fsync(stream.fileno())
            if _read_bounded(pending, len(job.descriptor)) != job.descriptor:
                raise OSError('observation commit readback differs')
            os.link(pending, final)
        except (ICDError, OSError, RuntimeError, TypeError, ValueError):
            job.error = 'RESOURCE'

    def poll(self):
        with self._operation():
            return self._poll()

    def _poll(self):
        if self._failed:
            raise ICDError(self._failed, 'original observation writer failed; records retained')
        job = self._job
        if job is None or job.thread.is_alive():
            return False
        if job.error:
            self._failed = job.error
            raise ICDError(job.error, 'original observation persistence failed; records retained')
        try:
            saved = read_evidence_archive(job.directory, self._dispatcher.contract,
                                          max_records=self._max_records, max_bytes=self._max_bytes)
            raw = _read_bounded(job.directory.with_suffix('.json'), DESCRIPTOR_BYTES)
            if (saved.records_jsonl != job.archive.records_jsonl or saved.manifest_json != job.archive.manifest_json or
                    raw != job.descriptor or _read_bounded(job.directory.with_suffix('.pending.json'), len(raw)) != raw):
                raise ICDError('RESOURCE', 'persisted original segment differs before reclaim')
            link = _link(raw, saved, index=len(self._commits), run_id=self._run_id, previous=self._previous,
                         counts=self._counts, dropped_before=self._dropped)
        except (ICDError, OSError) as error:
            self._failed = 'RESOURCE'
            raise ICDError('RESOURCE', 'original segment readback failed; no records reclaimed') from error
        # Check every stream before deleting any: new observations after snapshot
        # are untouched, as are original pending reservations and probe watches.
        with self._owners() as owners:
            live = self._live_streams(owners)
            if any(len(live[k]) < len(job.prefix[k]) or
                   any(a is not b for a,b in zip(live[k],job.prefix[k]))
                   for k in self._stream_names if k != 'CAN'):
                self._failed = 'STATE'
                raise ICDError('STATE', 'original record identity changed; no partial reclaim')
            source = self._dispatcher.session
            source_bytes = sum(len(r.request_json)+(0 if r.reply_json is None else len(r.reply_json)) for r in job.prefix['SOURCE'])
            dispatch_bytes = sum(512+sum(len(b) for b in (r.request_json,r.reply_json,r.wire_data) if b is not None)
                                 for r in job.prefix['DISPATCH'])
            inbox_bytes = sum(r.stored_bytes for r in job.prefix['INBOX'])
            can_reclaim, l2_bytes = [], 0
            if self._native:
                grouped = tuple(r for prefix in job.native_prefix for r in prefix)
                if (len(job.native_prefix) != len(self._senders) or len(grouped) != len(job.prefix['CAN'])
                        or any(a is not b for a,b in zip(grouped,job.prefix['CAN']))):
                    self._failed = 'STATE'
                    raise ICDError('STATE', 'native original saved groups differ; no partial reclaim')
                for sender, prefix in zip(self._senders, job.native_prefix):
                    size = sum(sender._size(r) for r in prefix)
                    if (len(sender.records) < len(prefix) or
                            any(a is not b for a,b in zip(sender.records,prefix)) or size > sender._bytes):
                        self._failed = 'STATE'
                        raise ICDError('STATE', 'native original prefix/accounting differs; no partial reclaim')
                    can_reclaim.append((sender,len(prefix),size))
                l2_bytes = sum(512+len(r.ethernet_data)+len(r.udp_data) for r in job.prefix['L2'])
                if l2_bytes and l2_bytes > self._transport._l2_bytes:
                    self._failed = 'STATE'
                    raise ICDError('STATE', 'native original L2 accounting differs; no partial reclaim')
            if (source_bytes > source._record_bytes or dispatch_bytes > self._dispatcher._used_bytes or
                    len(job.prefix['DISPATCH']) > self._dispatcher._used_count or
                    self._inbox is not None and inbox_bytes > self._inbox._record_bytes):
                self._failed = 'STATE'
                raise ICDError('STATE', 'original record accounting differs; no partial reclaim')
            if self._scenario:
                # The original ETH handler consumes terminal feedback from these
                # rows, not from a successful disk write or an inferred ACK.
                for entry in self._actions._entries.values():
                    if (entry.result is None and entry.header is not None
                            and entry.scheduled.link_id == 'ETHGEN'
                            and any(r.header is entry.header for r in job.prefix['DISPATCH'])
                            and any(r.header is entry.header and r.kind in ('COMPLETE','FAILED','TIMEOUT','CANCEL')
                                    for r in live['DISPATCH'])):
                        return False
            del source._records[:len(job.prefix['SOURCE'])]
            source._record_bytes -= source_bytes
            del self._dispatcher._records[:len(job.prefix['DISPATCH'])]
            self._dispatcher._used_count -= len(job.prefix['DISPATCH'])
            self._dispatcher._used_bytes -= dispatch_bytes
            if self._inbox is not None:
                del self._inbox._records[:len(job.prefix['INBOX'])]
                self._inbox._record_bytes -= inbox_bytes
            for sender, count, size in can_reclaim:
                del sender._records[:count]
                sender._bytes -= size
            if self._native and job.prefix['L2']:
                del self._transport._l2_records[:len(job.prefix['L2'])]
                self._transport._l2_bytes -= l2_bytes
            if self._scenario:
                for name in self._history_prefix:
                    self._history_prefix[name] += job.prefix[name]
                self._plan_saved = True
                self._actions._anchor()
            self._counts = link['stream_end_counts']
            self._dropped = link['dropped_feedback_after']
            self._previous = _digest(raw)
            self._used_bytes += len(saved.records_jsonl)+len(saved.manifest_json)+len(raw)
            self._commits.append(raw)
            self._job = None
        return True

    def close(self, *, timeout=5):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 <= timeout <= 30:
            raise ICDError('SCHEMA', 'finite explicit local worker wait0..30s required')
        with self._operation(closed_ok=True):
            if self._closed:
                return self._closeout
            job = self._job
            if job is not None and job.thread.ident is not None:
                job.thread.join(timeout)
                if job.thread.is_alive():
                    raise ICDError('TIMEOUT', 'same observation worker still live; owner and handle retained')
            if self._closeout is None and not self._failed:
                try:
                    self._poll()
                except ICDError:
                    if not self._failed:
                        raise
            if self._closeout is None:
                if self._job is not None and not self._failed:
                    raise ICDError('STATE', 'original action must consume saved feedback before local close')
                with self._owners() as owners:
                    counts = tuple(len(rows) for rows in self._live_streams(owners).values())
                raw = canonicalize({
                    'format':f'HIL_OBSERVATION_CLOSE_{self._profile}',
                    'run_id':self._run_id,
                    'baseline_sha256':self._dispatcher.contract.baseline_sha256,
                    'committed_segments':len(self._commits), 'tip_sha256':self._previous,
                    'stream_counts':self._counts, 'persisted_segment_bytes':self._used_bytes,
                    'unpersisted_counts':dict(zip(self._stream_names,counts)), 'worker_stopped':True,
                    'error':self._failed, 'execution_ready':False,
                    'qualification_status':'NOT_EVALUATED', 'evidence_complete':False})
                # This seals a local snapshot, not a remote run end. Never hold
                # the dispatcher/source locks while performing filesystem IO.
                try:
                    if len(raw) > DESCRIPTOR_BYTES or self._used_bytes+len(raw) > self._max_total_bytes:
                        raise ICDError('CAPACITY', 'local close checkpoint exceeds recording capacity')
                    pending, final = self._root/'close.pending.json', self._root/'close.json'
                    with pending.open('xb') as stream:
                        if stream.write(raw) != len(raw):
                            raise OSError('incomplete local close checkpoint')
                        stream.flush()
                        os.fsync(stream.fileno())
                    if _read_bounded(pending,len(raw)) != raw:
                        raise OSError('local close checkpoint readback differs')
                    os.link(pending,final)
                    if _read_bounded(final,len(raw)) != raw:
                        raise OSError('published local close checkpoint differs')
                except ICDError as error:
                    self._failed = 'CAPACITY' if error.code == 'CAPACITY' else 'RESOURCE'
                except (OSError, TypeError, ValueError):
                    self._failed = 'RESOURCE'
                self._closeout = RecorderCloseout(len(self._commits),counts,True,self._failed,self._stream_names)
            with self._owners():
                if self._dispatcher._observation_recorder is self:
                    self._dispatcher._observation_recorder = None
                if self._dispatcher.session._observation_recorder is self:
                    self._dispatcher.session._observation_recorder = None
                if self._scenario:
                    if getattr(self._actions, '_recording_owner', None) is self:
                        self._actions._recording_owner = None
                    if self._execution is not None and getattr(self._execution, '_recording_owner', None) is self:
                        self._execution._recording_owner = None
                if self._assertions is not None and self._assertions._recording_owner is self:
                    self._assertions._recording_owner = None
                if self._targets is not None and self._targets._recording_owner is self:
                    self._targets._recording_owner=None
                self._closed = True
            return self._closeout


def read_observation_chain(path, contract, *, max_segments=10000, max_records=100000, max_bytes=MAX_BYTES,
                           expected_segments=None, expected_tip_sha256=None):
    if (type(max_segments) is not int or not 1 <= max_segments <= 100000 or
            type(max_records) is not int or not 1 <= max_records <= 1000000 or
            type(max_bytes) is not int or not 1 <= max_bytes <= 1024**3):
        raise ICDError('CAPACITY', 'strict bounded observation chain limits required')
    if ((expected_segments is None) != (expected_tip_sha256 is None) or
            expected_segments is not None and
            (type(expected_segments) is not int or not 1 <= expected_segments <= 100000 or
             type(expected_tip_sha256) is not str or re.fullmatch('[0-9a-f]{64}',expected_tip_sha256) is None)):
        raise ICDError('SCHEMA', 'trusted segment count and lower-case SHA256 tip must be supplied together')
    try:
        root, names = Path(path), set()
        if root.is_symlink() or not root.is_dir():
            raise OSError('original recording directory required')
        with os.scandir(root) as entries:
            for entry in entries:
                if len(names) >= 3*max_segments+2:
                    raise ICDError('CAPACITY', 'observation directory entry capacity exhausted')
                if entry.name not in ('close.json','close.pending.json') and re.fullmatch(r'segment-[0-9]{6}(?:\.pending\.json|\.json)?',entry.name) is None:
                    raise OSError('unknown observation chain file')
                names.add(entry.name)
        close_names = names & {'close.json','close.pending.json'}
        if close_names and close_names != {'close.json','close.pending.json'}:
            raise OSError('incomplete local close checkpoint')
        commits = {name for name in names-close_names if name.endswith('.json') and not name.endswith('.pending.json')}
        count = len(commits)
        expected = {f'segment-{i:06d}{suffix}' for i in range(count) for suffix in ('','.json','.pending.json')}
        if (not count or count > max_segments or names-close_names != expected or
                expected_segments is not None and count != expected_segments):
            raise OSError('observation chain missing, reordered or has uncommitted tail')
        segments, descriptors = [], []
        counts, previous, run_id, dropped = None, '0'*64, None, None
        streams, segment_format = None, None
        total_bytes = total_records = 0
        channel = None
        for index in range(count):
            directory = root/f'segment-{index:06d}'
            raw = _read_bounded(directory.with_suffix('.json'), min(DESCRIPTOR_BYTES,max_bytes-total_bytes))
            if _read_bounded(directory.with_suffix('.pending.json'),len(raw)) != raw:
                raise OSError('observation commit pending differs')
            total_bytes += len(raw)
            if total_records >= max_records or total_bytes >= max_bytes:
                raise ICDError('CAPACITY', 'observation chain count/bytes exhausted')
            archive = read_evidence_archive(directory,contract,max_records=min(100000,max_records-total_records),
                                             max_bytes=min(MAX_BYTES,max_bytes-total_bytes))
            manifest = archive.manifest
            if index == 0:
                segment_format = manifest['format']
                streams = FORMAT_STREAMS[segment_format]
                counts = dict.fromkeys(streams,0)
                initial = loads(raw)
                run_id = _text(initial['run_id'])
                dropped = _uint(initial['dropped_feedback_before'],2**53-1)
                channel = manifest['channel']
            if (manifest['run_id'] != run_id or manifest['channel'] != channel
                    or manifest['format'] != segment_format):
                raise OSError('original run/channel identity differs between segments')
            link = _link(raw,archive,index=index,run_id=run_id,previous=previous,counts=counts,dropped_before=dropped)
            total_bytes += len(archive.manifest_json)+len(archive.records_jsonl)
            total_records += manifest['record_count']
            counts, dropped, previous = link['stream_end_counts'],link['dropped_feedback_after'],_digest(raw)
            segments.append(archive)
            descriptors.append(raw)
        if expected_tip_sha256 is not None and previous != expected_tip_sha256:
            raise OSError('trusted terminal observation hash differs')
        if close_names:
            raw = _read_bounded(root/'close.json',min(DESCRIPTOR_BYTES,max_bytes-total_bytes))
            if _read_bounded(root/'close.pending.json',len(raw)) != raw:
                raise OSError('local close pending differs')
            value = loads(raw)
            if (type(value) is not dict or set(value) != CLOSE_KEYS or canonicalize(value) != raw or
                    value['format'] != f'HIL_OBSERVATION_CLOSE_{segment_format.rsplit("_", 1)[1]}'
                    or value['run_id'] != run_id or
                    value['baseline_sha256'] != segments[0].manifest['baseline_sha256'] or
                    _uint(value['committed_segments'],100000) != count or value['tip_sha256'] != previous or
                    _uint(value['persisted_segment_bytes'],1024**3) != total_bytes or
                    value['worker_stopped'] is not True or value['error'] not in (None,'STATE','RESOURCE','CAPACITY') or
                    value['execution_ready'] is not False or value['evidence_complete'] is not False or
                    value['qualification_status'] != 'NOT_EVALUATED'):
                raise OSError('local close identity/count/hash/flags differ')
            for name in ('stream_counts','unpersisted_counts'):
                if type(value[name]) is not dict or set(value[name]) != set(streams):
                    raise OSError('closed local snapshot stream counts required')
                for number in value[name].values():
                    _uint(number,10**10)
            if value['stream_counts'] != counts:
                raise OSError('local close cumulative counts differ')
        return ObservationChain(tuple(segments),tuple(descriptors),bool(close_names))
    except ICDError as error:
        if error.code == 'CAPACITY':
            raise
        raise ICDError('RESOURCE', 'invalid original observation chain') from error
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise ICDError('RESOURCE', 'original observation chain readback failed') from error
