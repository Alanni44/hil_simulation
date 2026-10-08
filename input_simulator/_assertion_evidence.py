"""Closed lossless original Status/assertion rows, never stage qualification."""

import base64
import binascii
from dataclasses import fields
import re

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .assertion import AssertionSpec, MODELS
from .model_clock import ModelClockSnapshot, STATES
from .scenario_assertions import (AssertionHandle, RuntimeAssertionRecord,
    RuntimeAssertionLifecycle, StatusReaderFailure)
from .scenario_execution import ERRORS


TYPES={'STATUS_SAMPLE':ModelClockSnapshot,'STATUS_FAILURE':StatusReaderFailure,
       'ASSERTION':RuntimeAssertionRecord,'ASSERTION_LIFECYCLE':RuntimeAssertionLifecycle}
BYTES={'request_json','status_json','assertion_json'}
TIMES={'started_ns','completed_ns','deadline_ns','received_ns'}


def _uint(value,maximum=2**32-1,*,minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ICDError('RESOURCE','strict original assertion integer required')
    return value


def _text(value):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ICDError('RESOURCE','bounded required assertion identifier needed')
    return value


def _encode(value):
    if type(value) is bytes:
        return base64.b64encode(value).decode('ascii')
    if type(value) is tuple:
        return [_encode(v) for v in value]
    if type(value) in (ModelClockSnapshot,AssertionHandle,AssertionSpec):
        return {f.name:(str(getattr(value,f.name)) if f.name in TIMES else _encode(getattr(value,f.name)))
                for f in fields(value)}
    return value


def _decode(value,cls):
    if type(value) is not dict or set(value)!={f.name for f in fields(cls)}:
        raise ICDError('RESOURCE','closed original assertion fields required')
    result={}
    for name,item in value.items():
        if name in BYTES:
            if type(item) is not str:
                raise ICDError('RESOURCE','required original assertion bytes missing')
            try:
                raw=base64.b64decode(item,validate=True)
                if base64.b64encode(raw).decode('ascii')!=item:
                    raise ValueError('noncanonical')
                loads(raw)
            except (binascii.Error,ValueError,ICDError) as error:
                raise ICDError('RESOURCE','invalid original assertion JSON bytes') from error
            item=raw
        elif name in TIMES:
            if type(item) is not str or re.fullmatch(r'0|[1-9][0-9]{0,19}',item) is None:
                raise ICDError('RESOURCE','original assertion uint64 time needs decimal string')
            item=_uint(int(item),2**64-1)
        elif name=='handle':
            item=_decode(item,AssertionHandle)
        elif name=='sample':
            item=_decode(item,ModelClockSnapshot)
        elif name=='specs':
            if type(item) is not list or not 1 <= len(item) <= 65536:
                raise ICDError('RESOURCE','nonempty original compiled assertions required')
            item=tuple(_decode(s,AssertionSpec) for s in item)
        elif name=='model_id':
            if type(item) is not str or item not in MODELS:
                raise ICDError('RESOURCE','original frozen assertion model required')
        elif name=='session_id':
            _uint(item,minimum=1)
        elif name in ('ordinal','sample_sequence'):
            _uint(item,65536 if name=='ordinal' else 2**32-1,minimum=1)
        elif name in ('model_step','initial_sequence','probe_numeric_id'):
            if name!='model_step' or item is not None:
                _uint(item)
            elif cls is ModelClockSnapshot:
                raise ICDError('RESOURCE','actual sample model step required')
        elif name in ('comparison_matched','reader_path_pending'):
            if type(item) is not bool:
                raise ICDError('RESOURCE','original assertion boolean required')
        elif name=='assertion_id':
            _text(item)
        elif name=='baseline_sha256':
            if type(item) is not str or re.fullmatch('[0-9a-f]{64}',item) is None:
                raise ICDError('RESOURCE','original assertion baseline hash required')
        elif name=='error':
            if item is not None and (type(item) is not str or item not in ERRORS):
                raise ICDError('RESOURCE','closed original assertion error required')
        elif name=='transport':
            if type(item) is not str or item not in ('UDP','CANFD'):
                raise ICDError('RESOURCE','original assertion transport required')
        elif name=='channel':
            if type(item) is not str or item not in tuple(f'{prefix}_{i}' for prefix in ('ETH','CANFD') for i in range(4)):
                raise ICDError('RESOURCE','original assertion channel required')
        elif name=='mode':
            if type(item) is not str or item not in ('WAIT','ASSERT'):
                raise ICDError('RESOURCE','original assertion mode required')
        elif name=='kind':
            if type(item) is not str or item not in ('STARTED','RESULT'):
                raise ICDError('RESOURCE','original assertion lifecycle kind required')
        elif name=='state':
            allowed=STATES if cls is ModelClockSnapshot else ('PENDING','COMPLETE','FAILED')
            if type(item) is not str or item not in allowed:
                raise ICDError('RESOURCE','original assertion state required')
        result[name]=item
    record=cls(**result)
    if cls is ModelClockSnapshot:
        request,status=record.request,record.status
        try:
            if (request['message_id']!=2 or status['message_id']!=131
                    or request['header']['session_id']!=record.session_id
                    or status['header']['session_id']!=record.session_id
                    or request['header']['transaction_id']!=status['header']['transaction_id']
                    or status['payload']['model_step']!=record.model_step
                    or status['payload']['state']!=record.state
                    or not record.started_ns<=record.completed_ns<record.deadline_ns
                    or record.deadline_ns!=record.started_ns+240000000
                    or not record.channel.startswith('ETH_' if record.transport=='UDP' else 'CANFD_')):
                raise ValueError('inconsistent actual sample provenance')
        except (KeyError,TypeError,ValueError) as error:
            raise ICDError('RESOURCE','original Status sample provenance differs') from error
    if cls is StatusReaderFailure and record.error!='BUFFER_FULL':
        raise ICDError('RESOURCE','original finite sampling overflow required')
    if cls is RuntimeAssertionLifecycle:
        if (record.kind=='STARTED' and (record.state!='PENDING' or record.error is not None or record.model_step is None)
                or record.kind=='RESULT' and (record.state=='PENDING'
                    or (record.state=='FAILED')!=(record.error is not None))):
            raise ICDError('RESOURCE','original begin/terminal lifecycle differs')
    return record


def encode_assertion_record(stream,record):
    if stream not in TYPES or type(record) is not TYPES[stream]:
        raise ICDError('STATE','actual original typed assertion observation required')
    row={f.name:(str(getattr(record,f.name)) if f.name in TIMES else _encode(getattr(record,f.name)))
         for f in fields(record)}
    value={'stream':stream,'record':row}
    decode_assertion_record(value)
    return canonicalize(value)+b'\n'


def decode_assertion_record(value):
    if (type(value) is not dict or set(value)!={'stream','record'}
            or type(value['stream']) is not str or value['stream'] not in TYPES):
        raise ICDError('RESOURCE','closed original assertion stream required')
    return _decode(value['record'],TYPES[value['stream']])


def validate_assertion_record(record,contract):
    if type(record) is RuntimeAssertionLifecycle:
        for spec in record.specs:
            if spec!=AssertionSpec.compile(contract,spec.assertion,model_id=spec.model_id):
                raise ICDError('RESOURCE','compiled assertion differs from frozen contract')
    sample=record if type(record) is ModelClockSnapshot else record.sample if type(record) is RuntimeAssertionRecord else None
    if sample is not None:
        contract.validate_message(sample.request,direction='TO_36',model_id=sample.model_id)
        contract.validate_message(sample.status,direction='FROM_36',model_id=sample.model_id)
