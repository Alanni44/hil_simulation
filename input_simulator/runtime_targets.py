"""Actual applied-context authorization before original native allocation/TX."""

from abc import ABC, abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
import threading

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import WireCodec
from icd_gateway.semantic_guards import LifecycleDecision, ModelView, SemanticGuards
from icd_gateway.session import RegisteredController, PeerBinding
from .model_clock import ObservedModelClock, ObservedControlLease
from .can_signal import CANSignalSender
from .native_scenario_actions import KINDS
from .scenario import ScenarioPlan, ScheduledAction
from .session import SourceSession


MAX_TIME=(1 << 64)-1
RESERVATION_BYTES=65536+12*4096+2048+40*1000+128


@dataclass(frozen=True, slots=True)
class RuntimeTargetSample:
    identity_json: bytes
    configuration_json: bytes
    view: ModelView
    producer: RegisteredController | None
    owner_session_id: int
    owner_lane: str
    owner_mode: str
    control_deadline_ns: int
    sampled_ns: int
    deadline_ns: int

    def __post_init__(self):
        if (type(self.identity_json) is not bytes or not 1<=len(self.identity_json)<=4096
                or type(self.configuration_json) is not bytes or not 1<=len(self.configuration_json)<=65536
                or type(self.view) is not ModelView
                or type(self.owner_session_id) is not int or not 0<=self.owner_session_id<=0xffffffff
                or type(self.owner_lane) is not str or self.owner_lane not in ('INTERNAL_CONTROLLER','FLIGHT_CONTROL','ACTUATOR')
                or type(self.owner_mode) is not str or self.owner_mode not in ('MANUAL','AUTO')
                or any(type(t) is not int or not 0<=t<=MAX_TIME for t in
                       (self.control_deadline_ns,self.sampled_ns,self.deadline_ns))
                or self.sampled_ns>=self.deadline_ns):
            raise ICDError('SCHEMA','complete immutable bounded target snapshot required')
        p=self.producer
        if p is not None and (type(p) is not RegisteredController
                or type(p.identity_json) is not bytes or not 1<=len(p.identity_json)<=4096
                or type(p.roles) is not tuple or type(p.bindings) is not tuple
                or not 1<=len(p.roles)<=3
                or any(type(r) is not str or r not in ('STIMULUS','CONTROLLER','OBSERVER') for r in p.roles)
                or len(set(p.roles))!=len(p.roles)
                or type(p.session_id) is not int or not 1<=p.session_id<=0xffffffff
                or any(type(t) is not int or not 0<=t<=MAX_TIME for t in (p.observed_ns,p.deadline_ns))
                or p.observed_ns>=p.deadline_ns
                or type(p.last_rx_sequence) is not int or not 1<=p.last_rx_sequence<=0xffffffff
                or type(p.nonce) is not str or len(p.nonce)!=32
                or any(c not in '0123456789abcdefABCDEF' for c in p.nonce)
                or not 1<=len(p.bindings)<=8 or any(type(b) is not PeerBinding
                    or type(b.channel) is not str or not 1<=len(b.channel)<=64
                    or type(b.transport) is not str or b.transport not in ('UDP','CANFD')
                    or type(b.peer) is not str or not 1<=len(b.peer)<=256 for b in p.bindings)):
            raise ICDError('SCHEMA','original immutable registered producer required')


class RuntimeTargetBackend(ABC):
    def __init__(self, contract, model_ids):
        if not isinstance(contract,Contract) or not contract.component_hashes:
            raise ICDError('HASH','actual verified target backend contract required')
        if (type(model_ids) is not tuple or not model_ids
                or any(type(m) is not str or m not in contract.entry(3)['model_ids'] for m in model_ids)
                or len(set(model_ids))!=len(model_ids)):
            raise ICDError('MODEL','explicit distinct frozen backend models required')
        self.contract,self.model_ids=contract,model_ids

    @abstractmethod
    def read_target(self, identity, *, now_ns):
        """Read actual coherent applied configuration/view/owner, in source time domain."""


@dataclass(frozen=True, slots=True)
class RuntimeTargetRecord:
    action: ScheduledAction | None
    status: object
    sample: RuntimeTargetSample | None
    started_ns: int
    completed_ns: int
    target_step: int | None
    error: str | None
    control_lease: object = None
    lifecycle: LifecycleDecision | None = None

    @property
    def stored_bytes(self):
        size=1024+len(self.status.request_json)+len(self.status.status_json)
        if self.action is not None:
            size+=len(self.action.event_json)+len(self.action.stimulus_json or b'')
        if self.sample is not None:
            size+=len(self.sample.identity_json)+len(self.sample.configuration_json)
            if self.sample.producer is not None:
                size+=len(self.sample.producer.identity_json)+4096
        if self.control_lease is not None:
            size+=sum(len(raw) for raw in (self.control_lease.owner_request_json,self.control_lease.owner_reply_json,
                self.control_lease.lease_request_json,self.control_lease.lease_reply_json))
        if self.lifecycle is not None:
            size+=128+40*len(self.lifecycle.steps)
        return size


@dataclass(frozen=True, slots=True)
class RuntimeTargetGuard:
    authorizer: object
    record: RuntimeTargetRecord
    native: object
    sender: object
    lease: object

    def check(self, source, message_id, header, now, *, stimulus=None, packet=None):
        a,r=self.authorizer,self.record
        a._check()
        if (source is not a._source or self.native.session is not source
                or self.native.sender is not self.sender
                or header['session_id']!=a._sid or header['target_step']!=r.target_step
                or message_id!=r.action.stimulus['message_id']):
            raise ICDError('STATE','original native allocation/fragment approval required')
        if stimulus is not None and canonicalize({'message_id':stimulus['message_id'],
                'payload':stimulus['payload']})!=canonicalize(r.action.stimulus):
            raise ICDError('STATE','actual submitted stimulus differs from the original approval')
        if source._model_status is not r.status:
            raise ICDError('CLOCK_UNSYNC','original approved Status changed before allocation/TX')
        sample=r.sample
        if not sample.sampled_ns<=now<min(sample.deadline_ns,sample.sampled_ns+240_000_000,r.status.deadline_ns):
            raise ICDError('EXPIRED','original target approval expired before allocation/TX')
        if message_id==4:
            if 'consumer.Lifecycle' not in source.capabilities['available_probes']:
                raise ICDError('TARGET_MISSING','actual lifecycle consumer probe disappeared')
            decision=SemanticGuards(a._contract).lifecycle({**r.action.stimulus,'header':header},sample.view)
            if r.lifecycle is None or decision!=r.lifecycle:
                raise ICDError('STATE','original actual lifecycle decision required before allocation/TX')
            if packet is not None and packet not in WireCodec(a._contract).encode(
                    {**r.action.stimulus,'header':header},'UDP'):
                raise ICDError('STATE','actual encoded lifecycle bytes differ from original approval')
        if a._contract.entry(message_id)['role']=='CONTROLLER':
            p=sample.producer
            if (source._control_lease is not self.lease or self.lease is None
                    or now>=min(p.deadline_ns,sample.control_deadline_ns,self.lease.deadline_ns)):
                raise ICDError('CONTROL_OWNER','original producer/control lease expired or changed before allocation/TX')


class RuntimeTargetAuthorizer:
    def __init__(self, plan, session, backend, *, ahead_steps, can_sender=None,
                 max_records=4096,max_bytes=16*1024*1024):
        if not isinstance(session,SourceSession) or type(plan) is not ScenarioPlan:
            raise ICDError('STATE','original plan and actual source required')
        contract=session.contract
        if (plan.baseline_sha256!=contract.baseline_sha256
                or plan.model_id!=loads(session._identity_json)['model_id']):
            raise ICDError('MODEL','original target plan/model required')
        if not isinstance(backend,RuntimeTargetBackend) or backend.contract is not contract:
            raise ICDError('TARGET_MISSING','explicit same-contract actual target getter required')
        if can_sender is not None and (type(can_sender) is not CANSignalSender
                or can_sender.builder.session is not session):
            raise ICDError('STATE','actual same-source selected CAN sender required')
        self._can_sender=can_sender
        self._can_binding=None if can_sender is None else can_sender.binding
        self._can_builder=None if can_sender is None else can_sender.builder
        if (type(ahead_steps) is not int or not 1<=ahead_steps<=contract.catalogue['policy']['max_ahead_steps']
                or type(max_records) is not int or not 1<=max_records<=65536
                or type(max_bytes) is not int or not 1<=max_bytes<=128*1024*1024):
            raise ICDError('CAPACITY','explicit finite target lead/history required')
        self.plan,self.session,self.backend=plan,session,backend
        self._plan,self._source,self._backend=plan,session,backend
        self._contract,self._transport=contract,session.transport
        self._models=backend.model_ids
        self._sid,self._identity=session.session_id,session._identity_json
        self._ahead=ahead_steps
        self._actions={(a.event_id,a.index):a for a in plan.iter_actions(max_actions=65536)
                       if a.link_id in ('CANT','ETHGEN') and a.kind in KINDS}
        self._records,self._bytes=[],0
        self._max_records,self._max_bytes=max_records,max_bytes
        self._lock=threading.Lock()
        self._recording_owner=None
        self._epoch_retirement=None
        self.clock=ObservedModelClock(session)
        self.lease=ObservedControlLease(session)

    @property
    def records(self):
        return tuple(self._records)

    @property
    def epoch_records(self):
        return () if self._epoch_retirement is None else (self._epoch_retirement,)

    def _remember_epoch(self, guard, receipt):
        source=self._source
        request=loads(receipt.request_json)
        if (source._operation_thread!=threading.get_ident() or guard.authorizer is not self
                or source._model_epoch_retirement is not receipt or not source._model_clock_retired
                or receipt.session_id!=self._sid or receipt.identity_json!=self._identity
                or not any(r is guard.record for r in self._records)
                or guard.record.error is not None or guard.record.lifecycle is None
                or not guard.record.lifecycle.new_session
                or canonicalize({'message_id':request['message_id'],'payload':request['payload']})
                    !=canonicalize(guard.record.action.stimulus)):
            raise ICDError('STATE','actual original allocated approval must own retiring feedback')
        if self._epoch_retirement is None:
            self._epoch_retirement=receipt

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    def _check(self):
        recorder=self._source._observation_recorder
        if recorder is not None and recorder._targets is self and self._recording_owner is not recorder:
            raise ICDError('STATE','original target recording attachment cannot be removed')
        if self._recording_owner is not None and not self._recording_owner._owns_targets(self):
            raise ICDError('STATE','original target recording owners cannot be replaced')
        if (self.plan is not self._plan or self.session is not self._source or self.backend is not self._backend
                or self._backend.contract is not self._contract or self._backend.model_ids!=self._models
                or self._source.contract is not self._contract or self._source.transport is not self._transport
                or self._source._identity_json!=self._identity or self.clock.session is not self._source
                or self.lease.session is not self._source
                or self._can_sender is not None and (self._can_sender.builder is not self._can_builder
                    or self._can_sender.binding is not self._can_binding or self._can_builder.session is not self._source)):
            raise ICDError('STATE','original target owners cannot be replaced')
        if self._sid is None or self._source.session_id!=self._sid:
            raise ICDError('STALE_SESSION','original target grant required')

    def _source_state(self, step):
        self._check()
        status=self.clock.require_step(step)
        source=self._source
        with ExitStack() as stack:
            owner=source._dispatcher
            if owner is not None:
                stack.enter_context(owner._operation())
            stack.enter_context(source._operation(owner=owner))
            now=source._now()
            if source._model_status is not status or now>=status.deadline_ns:
                raise ICDError('EXPIRED','actual source Status changed or expired')
            return status,now,source.roles,source.capabilities

    def _completion_time(self):
        source=self._source
        with ExitStack() as stack:
            owner=source._dispatcher
            if owner is not None:
                stack.enter_context(owner._operation())
            stack.enter_context(source._operation(owner=owner))
            return source._now()

    def _action(self, action):
        if (type(action) is not ScheduledAction or type(action.index) is not int
                or type(action.event_id) is not str
                or type(action.step) is not int or type(action.priority) is not int
                or type(action.event_json) is not bytes or type(action.writable_targets) is not tuple
                or action.stimulus_json is not None and type(action.stimulus_json) is not bytes
                or self._actions.get((action.event_id,action.index))!=action):
            raise ICDError('STATE','exact original native scheduled action required')

    def _context(self, sample, status, now):
        if type(sample) is not RuntimeTargetSample:
            raise ICDError('STATE','actual immutable target snapshot required')
        if loads(sample.identity_json)!=loads(self._identity):
            raise ICDError('MODEL','target snapshot belongs to another complete identity')
        config=loads(sample.configuration_json)
        self._contract.validate_payload(3,config)
        view=sample.view
        if (view.model_id!=self._plan.model_id or config['model_id']!=view.model_id
                or config['max_duration_steps']!=view.max_duration_steps):
            raise ICDError('MODEL','actual configured model/duration differs')
        if view.model_step!=status.model_step:
            raise ICDError('CLOCK_UNSYNC','actual model getter and standard Status step differ')
        if view.state!=status.state:
            raise ICDError('STATE','actual model getter and standard Status lifecycle differ')
        if view.control_source!=status.status['payload']['control_source']:
            raise ICDError('CONTROL_OWNER','actual applied control source and Status differ')
        if not view.configured_once or view.state not in ('CONFIGURED','PAUSED','RUNNING','STOPPED'):
            raise ICDError('STATE','actual applied initial configuration and writable state required')
        if not sample.sampled_ns<=now<min(sample.deadline_ns,sample.sampled_ns+240_000_000):
            raise ICDError('EXPIRED','actual target sample is future or expired')
        return config

    def _permit(self, action, sample, config, now, roles, caps, *, preflight=False):
        lease=None
        if action.kind=='PERIODIC_STOP':
            return
        stimulus=action.stimulus
        self._contract.validate_stimulus(stimulus,model_id=self._plan.model_id)
        mid=stimulus['message_id']
        entry=self._contract.entry(mid)
        if mid not in caps['implemented_message_ids']:
            raise ICDError('TARGET_MISSING','actual source has no published input consumer')
        if mid==4 and 'consumer.Lifecycle' not in caps['available_probes']:
            raise ICDError('TARGET_MISSING','actual lifecycle consumer probe required')
        if sample.view.state=='STOPPED' and mid!=4:
            raise ICDError('STATE','stopped lifecycle management cannot authorize ordinary inputs')
        if entry['role'] not in roles:
            raise ICDError('AUTHORIZATION','actual source role cannot send this input')
        if action.link_id=='CANT':
            if self._can_sender is None:
                raise ICDError('TARGET_MISSING','actual selected CAN sender is unavailable')
            channel=self._can_binding.channel_id
        else:
            channel=self._source.transport.channel
        if channel not in config['active_channels']:
            raise ICDError('AUTHORIZATION','actual configured channel is inactive')
        if entry['role']=='CONTROLLER':
            p=sample.producer
            if (p is None or type(p.session_id) is not int or p.session_id!=self._sid
                    or sample.owner_session_id!=p.session_id or loads(p.identity_json)!=loads(self._identity)
                    or 'CONTROLLER' not in p.roles or sample.view.control_source=='NONE'
                    or config['controller']!=sample.view.control_source
                    or any(type(t) is not int for t in (p.observed_ns,p.deadline_ns))
                    or not sample.sampled_ns==p.observed_ns<=now<p.deadline_ns
                    or now>=sample.control_deadline_ns):
                raise ICDError('CONTROL_OWNER','unique actual applied registered control producer required')
            lane='FLIGHT_CONTROL' if mid in (7,8,9) else 'ACTUATOR'
            lease=self.lease.require(model_step=sample.view.model_step,source=config['controller'],input_lane=lane)
            if (sample.owner_lane!=lane or sample.owner_mode!=lease.mode or lease.role!='CONTROLLER'
                    or sample.view.model_id!='quadrotor_hil' and config['controller']=='DEMO_MISSION'):
                raise ICDError('CONTROL_OWNER','actual producer/lane/mode differs from original control lease')
        if not preflight and action.step!=sample.view.model_step:
            raise ICDError('TIMEOUT','original action model boundary missed; no catch-up')
        return lease

    def _read(self, action, step):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','single non-reentrant actual target reader owner required')
        try:
            if action is not None:
                self._action(action)
            status,started,roles,caps=self._source_state(step)
            reserve=RESERVATION_BYTES+(0 if action is None else len(action.event_json)+len(action.stimulus_json or b''))
            if len(self._records)>=self._max_records or self._bytes+reserve>self._max_bytes:
                raise ICDError('BUFFER_FULL','retain original target evidence before getter read')
            if self._plan.model_id not in self._models:
                raise ICDError('TARGET_MISSING','selected model has no actual target reader')
            sample,target,error,lease,lifecycle=None,None,None,None,None
            completed=started
            try:
                try:
                    value=self._backend.read_target(loads(self._identity),now_ns=started)
                    if type(value) is RuntimeTargetSample:
                        sample=value
                finally:
                    completed=self._completion_time()
                    current,completed,roles,caps=self._source_state(step)
                if current is not status:
                    raise ICDError('CLOCK_UNSYNC','standard Status changed during actual target read')
                config=self._context(sample,status,completed)
                if action is None:
                    for a in self._actions.values():
                        self._permit(a,sample,config,completed,roles,caps,preflight=True)
                else:
                    lease=self._permit(action,sample,config,completed,roles,caps)
                    target=step+self._ahead if sample.view.state=='RUNNING' else step
                    if target>sample.view.max_duration_steps or target>0xffffffff:
                        raise ICDError('RANGE','approved target exceeds actual configured duration')
                    if action.kind!='PERIODIC_STOP' and action.stimulus['message_id']==4:
                        source=self._source
                        with ExitStack() as stack:
                            owner=source._dispatcher
                            if owner is not None:
                                stack.enter_context(owner._operation())
                            stack.enter_context(source._operation(owner=owner))
                            header=source._preview_header(4,target,None)
                            lifecycle=SemanticGuards(self._contract).lifecycle(
                                {**action.stimulus,'header':asdict(header)},sample.view)
                self._check()
            except ICDError as exc:
                error=exc.code
                raise
            except Exception as exc:
                error='RESOURCE'
                raise ICDError(error,'actual applied target getter failed') from exc
            finally:
                record=RuntimeTargetRecord(action,status,sample,started,completed,target if error is None else None,error,lease,lifecycle)
                self._records.append(record)
                self._bytes+=record.stored_bytes
            return target
        finally:
            self._lock.release()

    def preflight(self, plan):
        if plan is not self._plan:
            raise ICDError('STATE','original complete target plan required')
        status=self.clock.snapshot()
        self._read(None,status.model_step)

    def approve(self, action, *, model_step):
        return self._read(action,model_step)

    @contextmanager
    def allocation_scope(self, action, target, native):
        self._check()
        if (not self._records or self._records[-1].action is not action
                or self._records[-1].target_step!=target or self._records[-1].error is not None
                or native.plan is not self._plan or native.session is not self._source):
            raise ICDError('STATE','original successful target observation required')
        source=self._source
        if not source._runtime_target_lock.acquire(blocking=False):
            raise ICDError('STATE','single original target allocation scope required')
        try:
            if source._runtime_target_scope is not None:
                raise ICDError('STATE','original target allocation scope cannot be replaced')
            guard=RuntimeTargetGuard(self,self._records[-1],native,native.sender,self._records[-1].control_lease)
            scope=(threading.get_ident(),guard)
            source._runtime_target_scope=scope
            yield
        finally:
            source._runtime_target_scope=None
            source._runtime_target_lock.release()
