"""Reception-purpose generated data through original CANT/ETHGEN tools."""

from dataclasses import asdict, dataclass
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from .can_signal import CANSignalSender
from .protocol import ProtocolParser
from .scapy_source import ScapySource
from .session import SourceSession, _snapshot_message
from .source_inputs import SourceInputAuditor


MAX_SAMPLES=4096
MAX_PLAN_BYTES=16*1024*1024


def _native_snapshot(record):
    fields=asdict(record)
    for key,value in fields.items():
        if type(value) is bytes:
            fields[key]={'encoding':'HEX','data':value.hex()}
        elif key.endswith('_ns') and value is not None:
            fields[key]=str(value)
    return _snapshot_message(fields)


@dataclass(frozen=True, slots=True)
class SendSample:
    step: int
    event_id: str
    link_id: str
    stimulus_json: bytes

    @property
    def stimulus(self):
        return loads(self.stimulus_json)


@dataclass(frozen=True, slots=True)
class SendPlan:
    _contract: object
    source_kind: str
    model_id: str
    actions: tuple
    baseline_sha256: str
    deferred_assertions_json: tuple = ()

    @property
    def model_application_verified(self):
        return False

    @classmethod
    def protocol(cls, contract, inputs, resources, *, model_id, stimuli, count, period_steps, first_step):
        if any(type(n) is not int for n in (count,period_steps,first_step)):
            raise ICDError('SCHEMA','exact integer generation count/period/first step required')
        if type(stimuli) is not list or not stimuli:
            raise ICDError('SCHEMA','explicit complete protocol Stimulus snapshots required')
        if not 1<=count<=MAX_SAMPLES or len(stimuli)*count>MAX_SAMPLES:
            raise ICDError('CAPACITY','bounded generated sample count required')
        if not 1<=period_steps<=0xffffffff or not 0<=first_step<=0xffffffff:
            raise ICDError('RANGE','positive period and uint32 first step required')
        if first_step+(count-1)*period_steps>0xffffffff:
            raise ICDError('RANGE','generated final target exceeds uint32')
        SourceInputAuditor(contract).audit(inputs,resources,model_id=model_id)
        parser=ProtocolParser(contract)
        parser.parse(inputs['protocol'],resources)
        actions=[]
        for index in range(count):
            for number,stimulus in enumerate(stimuli):
                contract.validate_stimulus(stimulus,model_id=model_id)
                mid=stimulus['message_id']
                entry=contract.entry(mid)
                if entry['direction']!='TO_36' or 'CANFD' not in entry['transports'] or mid in (1,2):
                    raise ICDError('UNSUPPORTED','protocol generation uses original CANT input frames, not openings/Status')
                if entry['period_ms'] and period_steps<entry['period_ms']:
                    raise ICDError('RANGE','generated period is faster than the frozen message period')
                parser.encode({**stimulus,'header':{'session_id':1,'sequence':2,'target_step':first_step,
                    'transaction_id':1,'valid_for_ms':entry['valid_for_ms']}})
                actions.append(SendSample(first_step+index*period_steps,f'protocol-{number}-{index}',
                                          'CANT',_snapshot_message(stimulus)))
        return cls._finish(contract,'PROTOCOL',model_id,actions)

    @classmethod
    def scenario(cls, contract, inputs, resources, *, model_id):
        audit=SourceInputAuditor(contract).audit(inputs,resources,model_id=model_id)
        plan=audit.scenario_plan
        if plan is None:
            raise ICDError('RESOURCE','an explicit frozen ScenarioSource is required')
        # Frozen ScenarioSource requires assertions even in a transmission projection.
        # Preserve their definitions explicitly; this profile never qualifies the scenario.
        deferred=tuple(_snapshot_message(a) for a in inputs['scenario']['assertions'])
        actions=[]
        for action in plan.iter_actions(max_actions=MAX_SAMPLES):
            if action.link_id not in ('CANT','ETHGEN'):
                raise ICDError('TARGET_MISSING','original non-native/external tool service required; no substitute')
            if action.kind=='PERIODIC_STOP':
                continue
            if action.kind not in ('SEND','FAULT','WAVEFORM','PERIODIC_START','PERIODIC_SAMPLE'):
                raise ICDError('TARGET_MISSING','non-transmission scenario event needs its explicit original service')
            stimulus=action.stimulus
            transport='CANFD' if action.link_id=='CANT' else 'UDP'
            entry=contract.entry(stimulus['message_id'])
            if transport not in entry['transports'] or stimulus['message_id'] in (1,2):
                raise ICDError('UNSUPPORTED','scenario input must use its original declared transmission transport')
            if stimulus['message_id'] not in inputs['protocol']['message_ids']:
                raise ICDError('RESOURCE','scenario input not declared by the protocol source')
            actions.append(SendSample(action.step,action.event_id,action.link_id,_snapshot_message(stimulus)))
        return cls._finish(contract,'SCENARIO',model_id,actions,deferred)

    @classmethod
    def _finish(cls, contract, kind, model, actions, deferred=()):
        if not actions:
            raise ICDError('RESOURCE','reception run must contain actual data samples')
        if len(actions)>MAX_SAMPLES or sum(len(a.stimulus_json)+256 for a in actions)+sum(map(len,deferred))>MAX_PLAN_BYTES:
            raise ICDError('CAPACITY','bounded complete generated plan required')
        return cls(contract,kind,model,tuple(actions),contract.baseline_sha256,deferred)


@dataclass(frozen=True, slots=True)
class SendRecord:
    source_kind: str
    sample: SendSample
    request_json: bytes | None
    feedback_json: tuple
    started_ns: int
    completed_ns: int
    sent_fragments: int
    error: str | None
    native_json: tuple = ()

    @property
    def validation_scope(self):
        return 'WIRE_SCHEMA_SESSION_ONLY'

    def document(self):
        return {'format':'HIL_RECEPTION_TX_1','source_kind':self.source_kind,'event_id':self.sample.event_id,
            'link_id':self.sample.link_id,'planned_target_step':self.sample.step,
            'request':None if self.request_json is None else loads(self.request_json),
            'feedback':[loads(raw) for raw in self.feedback_json],
            'started_ns':str(self.started_ns),'completed_ns':str(self.completed_ns),
            'sent_fragments':self.sent_fragments,'sent_fragments_semantics':'COMPLETE_NATIVE_WRITES_NOT_REMOTE_RECEIPTS',
            'native_observations':[loads(raw) for raw in self.native_json],
            'error':self.error,'validation_scope':self.validation_scope,
            'model_application_verified':False,'physical_tool_qualification':'NOT_EVALUATED'}


class SendRun:
    def __init__(self, plan, session, *, can_sender=None, feedback_timeout=0.2):
        if (type(plan) is not SendPlan or type(session) is not SourceSession
                or session.contract is not plan._contract or session.contract.baseline_sha256!=plan.baseline_sha256
                or loads(session._identity_json)['model_id']!=plan.model_id):
            raise ICDError('STATE','same verified original plan/source session required')
        if type(feedback_timeout) not in (int,float) or not 0<feedback_timeout<=0.5:
            raise ICDError('SCHEMA','bounded positive reception feedback timeout required')
        links={a.link_id for a in plan.actions}
        if 'CANT' in links and (type(can_sender) is not CANSignalSender or can_sender.session is not session):
            raise ICDError('TARGET_MISSING','actual original CANT sender required')
        if 'ETHGEN' in links and not isinstance(session.transport,ScapySource):
            raise ICDError('TARGET_MISSING','actual original Scapy ETHGEN transport required; no UDP fallback')
        for action in plan.actions:
            if type(action) is not SendSample:
                raise ICDError('STATE','original immutable transmission samples required')
            session.contract.validate_stimulus(action.stimulus,model_id=plan.model_id)
            role=session.contract.entry(action.stimulus['message_id'])['role']
            if role!='ANY_SESSION_ROLE' and role not in session._roles_requested:
                raise ICDError('AUTHORIZATION','all planned input roles must be explicitly requested before TX')
        self.plan,self.session,self.can_sender=plan,session,can_sender
        self._timeout=feedback_timeout
        self._records=[]
        self._bytes=0
        self._started=False

    @property
    def records(self):
        return tuple(self._records)

    def _open(self):
        if self.session.session_id is None:
            self.session.open()
        caps=self.session.capabilities
        if any(a.stimulus['message_id'] not in caps['implemented_message_ids'] for a in self.plan.actions):
            raise ICDError('TARGET_MISSING','receiver did not publish reception for every planned input')

    def run(self, *, on_record=None):
        if self._started:
            raise ICDError('STATE','transmission run cannot reopen/retry completed or failed effects')
        if on_record is not None and not callable(on_record):
            raise ICDError('SCHEMA','explicit reception record sink must be callable')
        self._started=True
        self._open()
        origin=time.monotonic_ns()
        for sample in self.plan.actions:
            due=origin+sample.step*1000000
            while True:
                remaining=due-time.monotonic_ns()
                if remaining<=0:
                    break
                time.sleep(min(remaining/1000000000,0.02))
            if time.monotonic_ns()>=self.session._deadline_ns-100000000:
                self.session.abandon()
                self._open()
            # This is producer pacing/target planning, never measured model time.
            reserved=6*len(sample.stimulus_json)+131072
            if self._bytes+reserved>MAX_PLAN_BYTES:
                raise ICDError('BUFFER_FULL','save bounded send history before another transmission run')
            started=time.monotonic_ns()
            request=None
            replies=[]
            sent=0
            tool=item=None
            error=None
            native_start=(len(self.can_sender.records) if sample.link_id=='CANT'
                          else len(self.session.transport.l2_records))
            try:
                if sample.link_id=='CANT':
                    sender=self.can_sender
                    tool=sender.builder.prepare(sender.reservation,sample.stimulus,sender.binding,target_step=sample.step)
                    request=_snapshot_message(tool.source_input.message)
                    sent=sender.send(tool)
                    for _ in range(3):
                        reply=sender.receive_for(tool,timeout=self._timeout)
                        replies.append(_snapshot_message(reply))
                        if reply['message_id']==130 and reply['payload']['stage']!='RECEIVED':
                            break
                else:
                    item=self.session.prepare_input(sample.stimulus,'UDP',target_step=sample.step)
                    value=item.message
                    request=_snapshot_message(value)
                    with self.session._operation():
                        self.session._verify_input(item)
                        self.session._claim_first_attempt(value)
                        sent=self.session.transport.send(value,owner=self.session)
                        for _ in range(3):
                            reply=self.session.transport.receive_for(value,timeout=self._timeout,owner=self.session)
                            completed=self.session._now()
                            self.session._check_reply(value,reply,started,completed)
                            self.session._last_rx_sequence=max(self.session.last_rx_sequence,reply['header']['sequence'])
                            replies.append(_snapshot_message(reply))
                            if reply['message_id']==130 and reply['payload']['stage']!='RECEIVED':
                                break
                final=loads(replies[-1])
                if final['message_id']!=130 or final['payload']['stage']!='VALIDATED' or final['payload']['error']!='OK':
                    code=final['payload'].get('error','STATE')
                    raise ICDError(code if code!='OK' else 'STATE','run requires genuine correlated E1 VALIDATED, not model evidence')
                if final['payload']['probe_id']!=0:
                    raise ICDError('STATE','reception-only result must not claim a consumer probe')
            except ICDError as exc:
                error=exc.code
                raise
            except Exception as exc:
                error='RESOURCE'
                raise ICDError('RESOURCE','transmission failed; original attempt retained') from exc
            finally:
                if sample.link_id=='CANT':
                    observations=self.can_sender.records[native_start:]
                    sent=sum(row.kind=='TX' and row.send_completed is True for row in observations)
                else:
                    observations=self.session.transport.l2_records[native_start:]
                    sent=sum(row.sent_bytes==len(row.ethernet_data) for row in observations)
                native=tuple(_native_snapshot(row) for row in observations)
                record=SendRecord(self.plan.source_kind,sample,request,tuple(replies),started,
                                  time.monotonic_ns(),sent,error,native)
                self._records.append(record)
                self._bytes+=512+len(request or b'')+sum(map(len,replies))+len(sample.stimulus_json)+sum(map(len,native))
                try:
                    if on_record is not None:
                        on_record(record)
                finally:
                    if tool is not None:
                        self.can_sender.retire(tool)
                        self.can_sender.builder.discard(tool)
                    if item is not None:
                        self.session.discard_input(item)
        return self.records
