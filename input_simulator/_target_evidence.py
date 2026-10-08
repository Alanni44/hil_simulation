"""Closed original authorization/epoch observations, not applied-model verdicts."""

import base64
import binascii
from dataclasses import fields
import re

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_gateway.semantic_guards import LifecycleDecision, ModelView, SemanticGuards
from icd_gateway.session import PeerBinding, RegisteredController
from ._assertion_evidence import _decode as decode_assertion
from .assertion import MODELS
from .model_clock import CONTROL_SOURCES, ControlLeaseSnapshot, ModelClockSnapshot, ModelEpochRetirement
from .runtime_targets import RuntimeTargetRecord, RuntimeTargetSample
from .scenario import ScheduledAction
from .scenario_execution import ERRORS


TYPES={'TARGET_AUTHORIZATION':RuntimeTargetRecord,'MODEL_EPOCH':ModelEpochRetirement}
NESTED={RuntimeTargetRecord:{'action':ScheduledAction,'status':ModelClockSnapshot,
    'sample':RuntimeTargetSample,'control_lease':ControlLeaseSnapshot,'lifecycle':LifecycleDecision},
    RuntimeTargetSample:{'view':ModelView,'producer':RegisteredController}}
OPTIONAL={(RuntimeTargetRecord,n) for n in ('action','sample','control_lease','lifecycle','target_step','error')}
OPTIONAL.add((ScheduledAction,'stimulus_json'))
OPTIONAL.add((RuntimeTargetSample,'producer'))
TUPLES={'roles','bindings','writable_targets','steps'}
BOOLS={'configured_once','physical_closed_loop','clear_queues','safe_outputs',
       'revoke_control','new_session','restore_initial'}
NUMBERS={'owner_session_id','session_id','last_rx_sequence','model_step','max_duration_steps',
         'target_step','step','priority','index'}


def _uint(value,maximum=2**32-1):
    if type(value) is not int or not 0<=value<=maximum:
        raise ICDError('RESOURCE','strict original target integer required')
    return value


def _encode(record):
    result={}
    for field in fields(record):
        name,value=field.name,getattr(record,field.name)
        if value is None:
            result[name]=None
        elif name.endswith('_json'):
            if type(value) is not bytes:
                raise ICDError('STATE','original immutable target bytes required')
            result[name]=base64.b64encode(value).decode('ascii')
        elif name.endswith('_ns'):
            result[name]=str(_uint(value,2**64-1))
        elif name in NESTED.get(type(record),{}):
            if type(value) is not NESTED[type(record)][name]:
                raise ICDError('STATE','original typed nested target observation required')
            result[name]=_encode(value)
        elif name=='bindings':
            if type(value) is not tuple or any(type(v) is not PeerBinding for v in value):
                raise ICDError('STATE','original immutable producer bindings required')
            result[name]=[_encode(v) for v in value]
        elif name in TUPLES:
            if type(value) is not tuple:
                raise ICDError('STATE','original immutable target tuple required')
            result[name]=list(value)
        else:
            result[name]=value
    return result


def _decode(value,cls):
    if cls is ModelClockSnapshot:
        return decode_assertion(value,cls)
    if type(value) is not dict or set(value)!={f.name for f in fields(cls)}:
        raise ICDError('RESOURCE','closed original target fields required')
    result={}
    for name,item in value.items():
        if item is None:
            if (cls,name) not in OPTIONAL:
                raise ICDError('RESOURCE','required original target field missing')
        elif name.endswith('_json'):
            if type(item) is not str:
                raise ICDError('RESOURCE','original target bytes require canonical base64')
            try:
                raw=base64.b64decode(item,validate=True)
                if base64.b64encode(raw).decode('ascii')!=item:
                    raise ValueError('noncanonical')
            except (binascii.Error,ValueError) as error:
                raise ICDError('RESOURCE','original target base64 differs') from error
            item=raw
        elif name.endswith('_ns'):
            if type(item) is not str or re.fullmatch(r'0|[1-9][0-9]{0,19}',item) is None:
                raise ICDError('RESOURCE','target uint64 time requires decimal string')
            item=_uint(int(item),2**64-1)
        elif name in NESTED.get(cls,{}):
            item=_decode(item,NESTED[cls][name])
        elif name in TUPLES:
            if type(item) is not list or len(item)>1000:
                raise ICDError('RESOURCE','bounded original target tuple required')
            if name=='bindings':
                item=tuple(_decode(v,PeerBinding) for v in item)
            elif name=='steps':
                item=tuple(_uint(v) for v in item)
            else:
                if any(type(v) is not str or not 1<=len(v)<=256 for v in item):
                    raise ICDError('RESOURCE','original target tuple identifiers required')
                item=tuple(item)
        elif name in BOOLS:
            if type(item) is not bool:
                raise ICDError('RESOURCE','original target boolean required')
        elif name in NUMBERS:
            _uint(item)
        else:
            if type(item) is not str or not 1<=len(item)<=256:
                raise ICDError('RESOURCE','bounded original target identifier required')
            if name=='model_id' and item not in MODELS:
                raise ICDError('RESOURCE','original frozen target model required')
            if name=='error' and item not in ERRORS:
                raise ICDError('RESOURCE','original target error vocabulary required')
        result[name]=item
    try:
        record=cls(**result)
    except (ICDError,TypeError,ValueError) as error:
        raise ICDError('RESOURCE','original target snapshot structure differs') from error
    if cls is RuntimeTargetRecord:
        if record.started_ns>record.completed_ns or record.error is not None and record.target_step is not None:
            raise ICDError('RESOURCE','original target failure/time provenance differs')
        if record.error is None and (record.sample is None or (record.action is None)!=(record.target_step is None)):
            raise ICDError('RESOURCE','successful target read must retain its actual sample/boundary')
    if cls is ScheduledAction:
        if record.link_id not in ('CANT','ETHGEN') or record.kind not in (
                'SEND','FAULT','WAVEFORM','PERIODIC_START','PERIODIC_SAMPLE','PERIODIC_STOP'):
            raise ICDError('RESOURCE','original native approval action required')
        event=loads(record.event_json)
        if type(event) is not dict or event.get('event_id')!=record.event_id:
            raise ICDError('RESOURCE','original scheduled event identity differs')
        if record.stimulus_json is not None:
            loads(record.stimulus_json)
    if cls is LifecycleDecision:
        if record.next_state not in ('CONFIGURED','RUNNING','PAUSED','STOPPED') or any(
                b!=a+1 for a,b in zip(record.steps,record.steps[1:])):
            raise ICDError('RESOURCE','original sequential lifecycle decision required')
    return record


def encode_target_record(stream,record):
    if stream not in TYPES or type(record) is not TYPES[stream]:
        raise ICDError('STATE','actual original target observation required')
    value={'stream':stream,'record':_encode(record)}
    decode_target_record(value)
    return canonicalize(value)+b'\n'


def decode_target_record(value):
    if (type(value) is not dict or set(value)!={'stream','record'}
            or type(value['stream']) is not str or value['stream'] not in TYPES):
        raise ICDError('RESOURCE','closed original target observation stream required')
    return _decode(value['record'],TYPES[value['stream']])


def _validate_control_lease(record,contract,config):
    lease,sample,status=record.control_lease,record.sample,record.status
    producer=sample.producer
    mid=record.action.stimulus['message_id']
    lane='FLIGHT_CONTROL' if mid in (7,8,9) else 'ACTUATOR'
    duration=contract.catalogue['policy']['control_timeout_ms']*1000000
    if (type(lease) is not ControlLeaseSnapshot or producer is None
            or lease.session_id!=status.session_id or producer.session_id!=status.session_id
            or sample.owner_session_id!=producer.session_id or lease.model_id!=status.model_id
            or loads(producer.identity_json)!=loads(sample.identity_json)
            or 'CONTROLLER' not in producer.roles or lease.role!='CONTROLLER'
            or lease.source not in CONTROL_SOURCES
            or lease.source!=config['controller'] or lease.source!=sample.view.control_source
            or lease.source!=status.status['payload']['control_source']
            or status.status['payload']['safety_active'] or status.state not in ('PAUSED','RUNNING')
            or lease.input_lane!=lane or sample.owner_lane!=lane or lease.mode!=sample.owner_mode
            or lease.mode not in ('MANUAL','AUTO')
            or lease.source=='DEMO_MISSION' and status.model_id!='quadrotor_hil'
            or sample.sampled_ns!=producer.observed_ns
            or not producer.observed_ns<=record.completed_ns<producer.deadline_ns
            or record.completed_ns>=sample.control_deadline_ns
            or not lease.owner_started_ns<=lease.owner_completed_ns<lease.owner_started_ns+duration
            or lease.lease_started_ns<lease.owner_started_ns
            or not lease.lease_started_ns<=lease.lease_completed_ns<=record.completed_ns<lease.deadline_ns
            or lease.deadline_ns!=lease.lease_started_ns+duration
            or lease.transport not in ('UDP','CANFD')
            or lease.channel not in tuple(f"{'ETH' if lease.transport=='UDP' else 'CANFD'}_{i}" for i in range(4))):
        raise ICDError('RESOURCE','original successful control producer/lease differs')
    owner=loads(lease.owner_request_json)
    for request_raw,reply_raw,is_owner in (
            (lease.owner_request_json,lease.owner_reply_json,True),
            (lease.lease_request_json,lease.lease_reply_json,False)):
        request,reply=loads(request_raw),loads(reply_raw)
        contract.validate_message(request,direction='TO_36',model_id=status.model_id)
        contract.validate_message(reply,direction='FROM_36',model_id=status.model_id)
        request_mid=request['message_id']
        payload=reply['payload']
        if (is_owner and request_mid!=6 or not is_owner and request_mid not in (6,7,8,9,14,15,16)):
            raise ICDError('RESOURCE','original control feedback request differs')
        probe=next(p['id'] for p in contract.catalogue['probe_catalog'] if p.get('message_id')==request_mid)
        if (reply['message_id']!=130 or request['header']['session_id']!=lease.session_id
                or reply['header']['session_id']!=lease.session_id
                or request['header']['transaction_id']!=reply['header']['transaction_id']
                or payload['request_message_id']!=request_mid
                or payload['request_sequence']!=request['header']['sequence']
                or payload['error']!='OK'
                or payload['stage'] not in (('APPLIED',) if is_owner or request_mid==6 else ('VALIDATED','APPLIED'))
                or payload['stage']=='APPLIED' and (payload['probe_id']!=probe
                    or payload['applied_step']!=request['header']['target_step'])):
            raise ICDError('RESOURCE','original control feedback correlation differs')
        if request_mid==6:
            if (any(request['payload'][name]!=getattr(lease,name) for name in ('source','role','input_lane','mode'))
                    or request_raw!=lease.owner_request_json or reply_raw!=lease.owner_reply_json
                    or not is_owner and (lease.lease_started_ns!=lease.owner_started_ns
                        or lease.lease_completed_ns!=lease.owner_completed_ns)):
                raise ICDError('RESOURCE','original owner lease grant differs')
        elif ('FLIGHT_CONTROL' if request_mid in (7,8,9) else 'ACTUATOR')!=lane or request['header']['sequence']<=owner['header']['sequence']:
            raise ICDError('RESOURCE','original control lease renewal differs')


def validate_target_record(record,contract):
    try:
        if type(record) is ModelEpochRetirement:
            identity=loads(record.identity_json)
            request,reply=loads(record.request_json),loads(record.reply_json)
            contract.validate_message(request,direction='TO_36',model_id=record.model_id)
            contract.validate_message(reply,direction='FROM_36',model_id=record.model_id)
            probe=next(p['id'] for p in contract.catalogue['probe_catalog'] if p['name']=='consumer.Lifecycle')
            if (identity['model_id']!=record.model_id or request['message_id']!=4 or reply['message_id']!=130
                    or request['payload']['action'] not in ('RESET','RESUME')
                    or request['header']['session_id']!=record.session_id or reply['header']['session_id']!=record.session_id
                    or request['header']['transaction_id']!=reply['header']['transaction_id']
                    or reply['payload']['request_message_id']!=4
                    or reply['payload']['request_sequence']!=request['header']['sequence']
                    or reply['payload']['stage']!='APPLIED' or reply['payload']['error']!='OK'
                    or reply['payload']['probe_id']!=probe or record.started_ns>record.completed_ns
                    or record.transport not in ('UDP','CANFD')
                    or record.channel not in tuple(f"{'ETH' if record.transport=='UDP' else 'CANFD'}_{i}" for i in range(4))):
                raise ICDError('RESOURCE','original retiring transaction provenance differs')
            return
        from ._assertion_evidence import validate_assertion_record
        validate_assertion_record(record.status,contract)
        action=record.action
        if action is not None:
            contract.validate_source_definition('Event',action.event)
            if action.stimulus is not None:
                contract.validate_stimulus(action.stimulus,model_id=record.status.model_id)
        # Failed raw backend bytes remain evidence, not validated configuration.
        if record.error is not None:
            return
        sample=record.sample
        identity,config=loads(sample.identity_json),loads(sample.configuration_json)
        contract.validate_payload(3,config)
        if (identity['model_id']!=record.status.model_id or sample.view.model_id!=record.status.model_id
                or config['model_id']!=sample.view.model_id or config['max_duration_steps']!=sample.view.max_duration_steps
                or sample.view.state!=record.status.state or sample.view.model_step!=record.status.model_step
                or not sample.sampled_ns<=record.completed_ns<min(sample.deadline_ns,sample.sampled_ns+240000000)):
            raise ICDError('RESOURCE','successful original target context differs')
        if action is not None and action.stimulus is not None and contract.entry(action.stimulus['message_id'])['role']=='CONTROLLER':
            _validate_control_lease(record,contract,config)
        if action is not None and action.stimulus is not None and action.stimulus['message_id']==4:
            header={**record.status.request['header'],'target_step':record.target_step,
                    'valid_for_ms':contract.entry(4)['valid_for_ms']}
            decision=SemanticGuards(contract).lifecycle({**action.stimulus,'header':header},sample.view)
            if decision!=record.lifecycle:
                raise ICDError('RESOURCE','original target lifecycle decision differs')
    except (ICDError,KeyError,TypeError,ValueError) as error:
        raise ICDError('RESOURCE','original target observation provenance differs') from error
