"""Lossless original plan/action/controller rows, never qualified run evidence."""

import base64
import binascii
from dataclasses import asdict, dataclass, fields

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import Header
from .native_scenario_actions import NativeActionHandle, NativeActionRecord
from .scenario_driver import DriverHandle
from .scenario_execution import CLEANUP_FIELDS, ERRORS, ScenarioRecord


@dataclass(frozen=True, slots=True)
class ScenarioPlanRecord:
    scenario_json: bytes
    identity_json: bytes
    model_id: str
    session_id: int
    qualification_status: str = 'NOT_EVALUATED'


TYPES = {'PLAN': ScenarioPlanRecord, 'NATIVE_ACTION': NativeActionRecord, 'SCENARIO': ScenarioRecord}
BYTES = frozenset(('scenario_json', 'identity_json', 'request_json', 'reply_json'))
NATIVE_KINDS = frozenset(('STARTED', 'COMPLETE', 'FAILED', 'LOCAL_PERIODIC_STOP',
                          'LOCAL_CANCELLED', 'LOCAL_RECLAIM_FAILED'))
SCENARIO_KINDS = frozenset(('ROOT_ASSERTIONS', 'RUN', 'CLEANUP', 'SEND', 'FAULT', 'WAVEFORM',
    'PERIODIC_START', 'PERIODIC_SAMPLE', 'PERIODIC_STOP', 'WAIT', 'ASSERT', 'REPLAY',
    'NEGATIVE_SEND', 'END_CLEANUP'))
OUTCOMES = frozenset(('STARTED', 'COMPLETE', 'FAILED', 'REQUESTED', 'PROGRESS', 'LOCAL_CANCELLED'))


def _uint(value, maximum=2**32-1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ICDError('RESOURCE', 'strict original unsigned integer required')
    return value


def _text(value):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ICDError('RESOURCE', 'bounded original string required')
    return value


def _structured(value, cls):
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ICDError('RESOURCE', 'closed original typed handle/header required')
    if cls is Header:
        for name, number in value.items():
            _uint(number, 65535 if name == 'valid_for_ms' else 2**32-1)
    elif cls is NativeActionHandle:
        _text(value['event_id'])
        if value['link_id'] not in ('CANT', 'ETHGEN'):
            raise ICDError('RESOURCE', 'original native tool link required')
        for name in ('index', 'model_step', 'target_step'):
            _uint(value[name])
    else:
        _uint(value['ordinal'], 65536)
        if type(value['kind']) is not str or value['kind'] not in SCENARIO_KINDS | {'ASSERTIONS'}:
            raise ICDError('RESOURCE', 'original driver handle kind required')
    return cls(**value)


def encode_scenario_record(stream, record):
    if stream not in TYPES or type(record) is not TYPES[stream]:
        raise ICDError('STATE', 'original typed scenario observation required')
    row = {}
    for field in fields(record):
        name, value = field.name, getattr(record, field.name)
        if name in BYTES and value is not None:
            if type(value) is not bytes:
                raise ICDError('STATE', 'original immutable scenario bytes required')
            value = base64.b64encode(value).decode('ascii')
        elif name in ('handle', 'header') and value is not None:
            cls = Header if name == 'header' else NativeActionHandle if stream == 'NATIVE_ACTION' else DriverHandle
            if type(value) is not cls:
                raise ICDError('STATE', 'actual original typed handle/header required')
            value = asdict(value)
        elif name == 'completed_cleanup_fields':
            if type(value) is not tuple:
                raise ICDError('STATE', 'original immutable cleanup receipts required')
            value = list(value)
        row[name] = value
    result = {'stream': stream, 'record': row}
    decode_scenario_record(result)
    return canonicalize(result) + b'\n'


def decode_scenario_record(row):
    if (type(row) is not dict or set(row) != {'stream', 'record'}
            or type(row['stream']) is not str or row['stream'] not in TYPES):
        raise ICDError('RESOURCE', 'closed scenario observation stream required')
    stream, value = row['stream'], row['record']
    cls = TYPES[stream]
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ICDError('RESOURCE', 'closed original scenario record fields required')
    decoded = dict(value)
    for name, item in value.items():
        if name in BYTES and item is not None:
            if type(item) is not str:
                raise ICDError('RESOURCE', 'explicit original base64 bytes required')
            try:
                raw = base64.b64decode(item, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ICDError('RESOURCE', 'invalid original scenario bytes') from error
            if base64.b64encode(raw).decode('ascii') != item:
                raise ICDError('RESOURCE', 'canonical original base64 required')
            loads(raw)
            decoded[name] = raw
        elif name in ('handle', 'header') and item is not None:
            handle_cls = Header if name == 'header' else NativeActionHandle if stream == 'NATIVE_ACTION' else DriverHandle
            decoded[name] = _structured(item, handle_cls)
        elif name in ('index', 'model_step', 'session_id'):
            _uint(item)
        elif name == 'completed_cleanup_fields':
            if (type(item) is not list or any(type(f) is not str or f not in CLEANUP_FIELDS for f in item)
                    or len(set(item)) != len(item)):
                raise ICDError('RESOURCE', 'distinct original named cleanup receipts required')
            decoded[name] = tuple(item)
        elif name == 'qualification_status':
            if item != 'NOT_EVALUATED':
                raise ICDError('RESOURCE', 'observations cannot claim qualification')
        elif name == 'error':
            if item is not None and (type(item) is not str or item not in ERRORS):
                raise ICDError('RESOURCE', 'original closed error required')
        elif name == 'kind':
            kinds = NATIVE_KINDS if stream == 'NATIVE_ACTION' else SCENARIO_KINDS
            if type(item) is not str or item not in kinds:
                raise ICDError('RESOURCE', 'original closed record kind required')
        elif name == 'outcome':
            if type(item) is not str or item not in OUTCOMES:
                raise ICDError('RESOURCE', 'original closed progress outcome required')
        elif name in ('event_id', 'model_id') or name == 'assertion_id' and item is not None:
            _text(item)
    if stream == 'PLAN' and (decoded['scenario_json'] is None or decoded['identity_json'] is None):
        raise ICDError('RESOURCE', 'both original plan and source identity required')
    if stream == 'NATIVE_ACTION' and decoded['handle'] is None:
        raise ICDError('RESOURCE', 'original native handle required')
    return cls(**decoded)
