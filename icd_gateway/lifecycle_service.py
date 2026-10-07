"""Explicit Lifecycle consumer; actual effects require the installed model backend."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import threading
import time

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .semantic_guards import ModelView, SemanticGuards
from .session import SessionRegistry


MAX_TIME=2**64-1
MAX_BYTES=65536


def _raw(value,maximum):
    if type(value) is not bytes or not 1<=len(value)<=maximum:
        raise ICDError('SCHEMA','bounded immutable original lifecycle bytes required')


def _sample(identity,view,sampled,deadline):
    _raw(identity,4096)
    if (type(view) is not ModelView or len(view.model_id)>64 or type(view.state) is not str
            or type(view.control_source) is not str or type(sampled) is not int or type(deadline) is not int
            or not 0<=sampled<deadline<=MAX_TIME):
        raise ICDError('SCHEMA','strict immutable actual lifecycle view and uint64 times required')


@dataclass(frozen=True, slots=True)
class ModelLifecycleContext:
    identity_json: bytes
    request_json: bytes
    configuration_json: bytes
    state_json: bytes
    inputs_json: bytes
    view: ModelView
    sampled_ns: int
    deadline_ns: int

    def __post_init__(self):
        _sample(self.identity_json,self.view,self.sampled_ns,self.deadline_ns)
        for name,maximum in (('request_json',MAX_BYTES+4096),('configuration_json',MAX_BYTES),
                             ('state_json',4096),('inputs_json',MAX_BYTES)):
            _raw(getattr(self,name),maximum)

    @property
    def stored_bytes(self):
        return 512+sum(len(getattr(self,name)) for name in
            ('identity_json','request_json','configuration_json','state_json','inputs_json'))


@dataclass(frozen=True, slots=True)
class ModelLifecycleStep:
    state_json: bytes
    actuators_json: bytes
    sampled_ns: int
    step_us: int

    def __post_init__(self):
        _raw(self.state_json,4096)
        _raw(self.actuators_json,1024)
        if (type(self.sampled_ns) is not int or not 0<=self.sampled_ns<=MAX_TIME
                or type(self.step_us) is not int or not 1<=self.step_us<=1000000):
            raise ICDError('SCHEMA','actual solver step and strict uint64 sample time required')

    @property
    def stored_bytes(self):
        return 128+len(self.state_json)+len(self.actuators_json)


@dataclass(frozen=True, slots=True)
class ModelLifecycleReceipt:
    identity_json: bytes
    request_json: bytes
    configuration_json: bytes
    state_json: bytes
    inputs_json: bytes
    view: ModelView
    actuators_json: bytes
    owner_session_id: int
    receive_queue_depth: int
    steps: tuple
    model_revision: int
    sampled_ns: int
    deadline_ns: int

    def __post_init__(self):
        _sample(self.identity_json,self.view,self.sampled_ns,self.deadline_ns)
        for name,maximum in (('request_json',MAX_BYTES+4096),('configuration_json',MAX_BYTES),
                             ('state_json',4096),('inputs_json',MAX_BYTES)):
            _raw(getattr(self,name),maximum)
        _raw(self.actuators_json,1024)
        if (type(self.owner_session_id) is not int or not 0<=self.owner_session_id<=0xffffffff
                or type(self.receive_queue_depth) is not int or not 0<=self.receive_queue_depth<=4096
                or type(self.model_revision) is not int or not 0<=self.model_revision<=0xffffffff
                or type(self.steps) is not tuple or len(self.steps)>1000
                or any(type(s) is not ModelLifecycleStep for s in self.steps)):
            raise ICDError('SCHEMA','actual immutable lifecycle owner/queue/revision/step readback required')

    @property
    def stored_bytes(self):
        return (640+sum(len(getattr(self,name)) for name in
            ('identity_json','request_json','configuration_json','state_json','inputs_json','actuators_json'))
            +sum(s.stored_bytes for s in self.steps))


class ModelLifecycleBackend(ABC):
    def __init__(self,contract,model_ids):
        if not isinstance(contract,Contract) or not contract.component_hashes:
            raise ICDError('HASH','verified actual lifecycle contract required')
        if (type(model_ids) is not tuple or not model_ids or len(set(model_ids))!=len(model_ids)
                or any(type(m) is not str or m not in contract.entry(4)['model_ids'] for m in model_ids)):
            raise ICDError('MODEL','explicit distinct frozen lifecycle models required')
        self.contract,self.model_ids=contract,model_ids

    @abstractmethod
    def read_context(self,identity,request_json,*,now_ns):
        """Read coherent actual configuration, State132 and every applied input.

        Preserve the actual complete solver state inside the backend as needed for
        RESUME; the State132 projection alone is not an internal-state getter.
        All sample times use the receiving monotonic domain.
        """

    @abstractmethod
    def apply_lifecycle(self,request_json,context,decision,*,now_ns):
        """Own/recheck the atomic model boundary and execute the decision once.

        Actual STEP executes each separate 1000us solver step, never a larger
        step or host-sleep inference. Read actual outputs/control/C queue and
        every step afterward. RESET restores full configured initial inputs and
        initialization; RESUME preserves full paused solver state and confirmed
        inputs. Do not mutate Python receiver/queue/session owners here.
        Failure is not rollback; platform qualification remains a separate gate.
        """


@dataclass(frozen=True, slots=True)
class ModelLifecycleRecord:
    request_json: bytes
    received_ns: int
    completed_ns: int
    context: ModelLifecycleContext | None
    receipt: ModelLifecycleReceipt | None
    decision: object
    write_attempted: bool
    captured_inputs: tuple
    discarded_inputs: tuple
    captured_groups: tuple
    discarded_groups: tuple
    retirement: object
    reply_json: bytes | None
    error: str | None

    @property
    def stored_bytes(self):
        return (1024+len(self.request_json)+len(self.reply_json or b'')
            +(self.context.stored_bytes if self.context is not None else 0)
            +(self.receipt.stored_bytes if self.receipt is not None else 0)
            +(128+40*len(self.decision.steps) if self.decision is not None else 0)
            +sum(p.stored_bytes+128 for p in self.captured_inputs)
            +sum(g.stored_bytes for g in self.captured_groups))


class ModelLifecycleService:
    def __init__(self,contract,registry,backend,*,max_records=4096,max_bytes=16*1024*1024,clock=time.monotonic_ns):
        if (not isinstance(contract,Contract) or not contract.component_hashes
                or type(registry) is not SessionRegistry or registry.contract is not contract):
            raise ICDError('HASH','same verified actual lifecycle registry/contract required')
        if not isinstance(backend,ModelLifecycleBackend) or backend.contract is not contract:
            raise ICDError('TARGET_MISSING','mandatory same-contract actual lifecycle backend required')
        if (type(max_records) is not int or not 1<=max_records<=65536
                or type(max_bytes) is not int or not 1<=max_bytes<=128*1024*1024 or not callable(clock)):
            raise ICDError('CAPACITY','finite original lifecycle evidence required')
        self.contract,self.registry,self.backend=contract,registry,backend
        self._contract,self._registry,self._backend=contract,registry,backend
        self._models=backend.model_ids
        self._clock=self._original_clock=clock
        self._max_records,self._max_bytes=max_records,max_bytes
        self._records,self._attempted=[],set()
        self._bytes=0
        self._receiver=None
        self._closed=False
        self._lock=threading.Lock()
        self._last_observed_ns=None
        self._operation_thread=self._completion=None
        self._cleanup_active=False

    @property
    def records(self):
        return tuple(self._records)

    @property
    def stored_bytes(self):
        return self._bytes

    @property
    def last_observed_ns(self):
        return self._last_observed_ns

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    def _check(self,*,closed_ok=False):
        if (self.contract is not self._contract or self.registry is not self._registry
                or self.backend is not self._backend or self._backend.contract is not self._contract
                or self._backend.model_ids!=self._models or self._registry.contract is not self._contract
                or self._clock is not self._original_clock
                or self._receiver is not None and (self._receiver.contract is not self._contract
                    or self._receiver.registry is not self._registry or self._receiver.lifecycle_service is not self
                    or self._receiver._lifecycle_service is not self)):
            raise ICDError('STATE','original lifecycle service owners cannot be replaced')
        if self._closed and not closed_ok:
            raise ICDError('STATE','original lifecycle service is closed')

    def _bind(self,receiver):
        from .receiver import Receiver
        self._check()
        if type(receiver) is not Receiver or self._receiver is not None:
            raise ICDError('STATE','one original actual lifecycle receiver required')
        self._receiver=receiver
        self._check()

    def supports(self,model_id):
        self._check()
        return model_id in self._models

    def _observe_time(self,received):
        now=self._clock()
        if (type(now) is not int or not 0<=now<=MAX_TIME or now<received
                or self._last_observed_ns is not None and now<self._last_observed_ns):
            raise ICDError('CLOCK_UNSYNC','actual lifecycle receiving clock regressed or differs')
        self._last_observed_ns=now
        return now

    def _admitted(self,request,now):
        self._check()
        received=self._registry.observe_admitted(request,now_ns=now)
        if now>=received+request['header']['valid_for_ms']*1000000:
            raise ICDError('EXPIRED','original lifecycle request expired')
        return received

    def _snapshot(self,value,identity,original,now,earliest):
        if type(value) not in (ModelLifecycleContext,ModelLifecycleReceipt):
            raise ICDError('STATE','actual immutable complete lifecycle snapshot required')
        if loads(value.identity_json)!=identity or value.view.model_id!=identity['model_id']:
            raise ICDError('MODEL','lifecycle snapshot belongs to another original run/model')
        if canonicalize(loads(value.request_json))!=original:
            raise ICDError('DUPLICATE','lifecycle snapshot does not name the original request')
        if not earliest<=value.sampled_ns<=now<min(value.deadline_ns,value.sampled_ns+240000000):
            raise ICDError('EXPIRED','actual lifecycle snapshot is future or expired')
        config,state,inputs=loads(value.configuration_json),loads(value.state_json),loads(value.inputs_json)
        self._contract.validate_payload(3,config)
        self._contract.validate_payload(132,state)
        self._contract.validate_payload(3,{**config,'initial_inputs':inputs})
        if (config['model_id']!=identity['model_id'] or inputs['model_id']!=identity['model_id']
                or value.view.max_duration_steps!=config['max_duration_steps']
                or state['model_step']!=value.view.model_step):
            raise ICDError('MODEL','actual lifecycle configuration/state/input boundary differs')
        return config,state,inputs

    def _actuators(self,raw,model,*,safe):
        mid={'quadrotor_hil':14,'multirotor_6_hil':15,'fixed_wing_hil':16}[model]
        values=loads(raw)
        self._contract.validate_payload(mid,values)
        if safe and any(v!=0 for value in values.values() for v in (value if type(value) is list else (value,))):
            raise ICDError('SAFETY','actual actuator readback is not safe zero')

    def _receipt(self,receipt,context,decision,identity,original,started,now):
        if type(receipt) is not ModelLifecycleReceipt:
            raise ICDError('STATE','complete actual post-effect lifecycle receipt required')
        config,state,inputs=self._snapshot(receipt,identity,original,now,started)
        expected=0 if decision.restore_initial else decision.steps[-1] if decision.steps else decision.target_step
        view=receipt.view
        if (view.state!=decision.next_state or view.model_step!=expected or not view.configured_once
                or view.physical_closed_loop!=context.view.physical_closed_loop
                or canonicalize(config)!=canonicalize(loads(context.configuration_json))):
            raise ICDError('STATE','actual applied lifecycle state/configuration/boundary differs')
        self._actuators(receipt.actuators_json,identity['model_id'],safe=decision.safe_outputs)
        if decision.safe_outputs:
            if view.control_source!='NONE' or receipt.owner_session_id!=0:
                raise ICDError('CONTROL_OWNER','actual lifecycle control owner was not revoked')
        if decision.clear_queues and receipt.receive_queue_depth!=0:
            raise ICDError('STATE','actual model receive queue was not cleared')
        if decision.restore_initial:
            initial=config['initial_state']
            restored={key:state[key] for key in ('position','orientation','p_radps','q_radps','r_radps','airborne')}
            restored.update({f'velocity_{axis}_mps':state[f'v{axis}_mps'] for axis in ('n','e','d')})
            if (canonicalize(restored)!=canonicalize(initial)
                    or canonicalize(inputs)!=canonicalize(config['initial_inputs'])):
                raise ICDError('BUSINESS_FAILED','RESET did not restore all explicit initial state/inputs')
        elif loads(original)['payload']['action']=='RESUME':
            if (canonicalize(state)!=canonicalize(loads(context.state_json))
                    or canonicalize(inputs)!=canonicalize(loads(context.inputs_json))):
                raise ICDError('BUSINESS_FAILED','RESUME changed paused state or confirmed input snapshot')
        if len(receipt.steps)!=len(decision.steps):
            raise ICDError('STATE','exact actual sequential STEP observations required')
        previous=started
        for expected_step,sample in zip(decision.steps,receipt.steps):
            actual=loads(sample.state_json)
            self._contract.validate_payload(132,actual)
            if actual['model_step']!=expected_step or sample.step_us!=1000:
                raise ICDError('STATE','STEP skipped/reordered a boundary or changed solver step')
            if not previous<sample.sampled_ns<=receipt.sampled_ns:
                raise ICDError('CLOCK_UNSYNC','actual STEP samples are not strictly ordered')
            self._actuators(sample.actuators_json,identity['model_id'],safe=True)
            previous=sample.sampled_ns
        if receipt.steps and canonicalize(loads(receipt.steps[-1].state_json))!=canonicalize(state):
            raise ICDError('STATE','last actual STEP observation differs from final state readback')

    def _scope(self,sid,now):
        from .model_queue import ModelQueue
        from .receiver import RetiredAssembly
        from .resource_worker import ResourceWorker
        selected=self._registry.run_session_ids(sid,now_ns=now)
        model=self._registry.identity(sid)['model_id']
        if any(self._registry.identity(other)['model_id']==model for other in self._registry.session_ids if other not in selected):
            raise ICDError('CONTROL_OWNER','another run owns the same global model boundary')
        queue,worker=self._registry._model_queue,self._registry._resource_worker
        assembler=self._receiver.assembler
        if queue is not None:
            if type(queue) is not ModelQueue or queue.registry is not self._registry or queue.contract is not self._contract:
                raise ICDError('STATE','actual original lifecycle queue required')
            queue.check_clock(now)
            if model not in queue._steps:
                raise ICDError('TARGET_MISSING','selected model has no original queue boundary')
        if worker is not None:
            if type(worker) is not ResourceWorker or worker.registry is not self._registry or worker.contract is not self._contract:
                raise ICDError('STATE','actual original lifecycle resource worker required')
            worker.check_clock(now)
        if self._receiver.resource_worker is not None and self._receiver.resource_worker is not worker:
            raise ICDError('STATE','original lifecycle receiver resource owner differs')
        if assembler is not self._receiver._run_assembler:
            raise ICDError('STATE','original lifecycle reassembler differs')
        inputs=tuple(p for p in queue._pending.values() if p.key[0] in selected) if queue is not None else ()
        groups=tuple(RetiredAssembly(key,g.first,g.deadline_ns,g.reserved,tuple(sorted(g.pieces.items())))
            for key,g in assembler._groups.items() if key[3] in selected)
        return selected,queue,assembler,worker,inputs,groups

    def _scope_check(self,scope,context,now,origin_sid):
        self._check()
        selected,queue,assembler,worker,inputs,groups=scope
        if (self._registry._model_queue is not queue or self._registry._resource_worker is not worker
                or self._receiver.assembler is not assembler):
            raise ICDError('STATE','original lifecycle local owners changed during operation')
        current=self._scope(origin_sid,now)
        if current[0]!=selected or current[4]!=inputs or current[5]!=groups:
            raise ICDError('STATE','original lifecycle sessions/inputs/fragments changed during operation')
        if queue is not None and queue._steps[context.view.model_id]!=context.view.model_step:
            raise ICDError('STATE','actual model and original queue step differ before lifecycle')

    def _owns_local_cleanup(self):
        return self._operation_thread==threading.get_ident() and self._lock.locked() and self._cleanup_active

    def _owns_completed_reply(self,request,replies,now):
        self._check()
        return (self._operation_thread==threading.get_ident() and self._lock.locked()
            and self._completion is not None and self._completion[0]==canonicalize(request)
            and self._completion[1]==canonicalize(list(replies)) and self._completion[2]==now)

    def respond(self,request,received_reply,*,now_ns):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','one non-reentrant original lifecycle operation required')
        try:
            self._operation_thread=threading.get_ident()
            self._check()
            if self._receiver is None or self._receiver._closed or self._receiver._closing:
                raise ICDError('STATE','live original lifecycle receiver required')
            self._contract.validate_message(request,direction='TO_36')
            if request['message_id']!=4:
                raise ICDError('UNSUPPORTED','only frozen Lifecycle is handled')
            if any(type(v) is not int for v in request['header'].values()):
                raise ICDError('SCHEMA','strict lifecycle header integers required')
            self._contract.validate_message(received_reply,direction='FROM_36')
            received_header,received_payload=received_reply['header'],received_reply['payload']
            if (received_reply['message_id']!=130 or received_header['session_id']!=request['header']['session_id']
                    or received_header['transaction_id']!=request['header']['transaction_id']
                    or received_payload['request_sequence']!=request['header']['sequence']
                    or received_payload['request_message_id']!=4 or received_payload['stage']!='RECEIVED'
                    or received_payload['error']!='OK' or received_payload['probe_id']!=0):
                raise ICDError('STATE','original correlated RECEIVED lifecycle reply required before effects')
            received=self._admitted(request,now_ns)
            sid=request['header']['session_id']
            identity=self._registry.identity(sid)
            if not self.supports(identity['model_id']):
                raise ICDError('TARGET_MISSING','selected model has no actual lifecycle backend')
            original=canonicalize(request)
            key=(sid,request['header']['sequence'])
            if key in self._attempted:
                raise ICDError('STATE','original lifecycle already attempted; no backend retry')
            scope=self._scope(sid,now_ns)
            selected,queue,assembler,worker,inputs,groups=scope
            scope_bytes=sum(p.stored_bytes+128 for p in inputs)+sum(g.stored_bytes for g in groups)
            count=request['payload'].get('step_count',0)
            reserve=32768+len(original)+4*MAX_BYTES+2*(MAX_BYTES+4096)+count*(5248+40)+scope_bytes
            if len(self._records)>=self._max_records or self._bytes+reserve>self._max_bytes:
                raise ICDError('BUFFER_FULL','retain complete lifecycle evidence before getter/effects')
            # Reserve the real terminal sequence before RESET/RESUME can revoke SID.
            terminal=self._receiver._header(130,sid,request['header']['transaction_id'])
            admission=self._registry._admitted_record(request)
            origin=self._registry._sessions[sid]
            self._attempted.add(key)
            context=receipt=decision=retirement=reply=error=None
            attempted=False
            completed=now_ns
            try:
                try:
                    value=self._backend.read_context(dict(identity),original,now_ns=now_ns)
                    if type(value) is ModelLifecycleContext:
                        context=value
                finally:
                    completed=self._observe_time(now_ns)
                self._admitted(request,completed)
                self._snapshot(context,identity,original,completed,0)
                decision=SemanticGuards(self._contract).lifecycle(request,context.view)
                self._scope_check(scope,context,completed,sid)
                if decision.new_session:
                    from .receiver import RunRetirement
                    preview=RunRetirement(sid,canonicalize(identity),completed,selected,(),inputs,(),groups,(),None)
                    self._receiver._check_run_retirement_capacity(preview)
                started=completed
                attempted=True
                try:
                    value=self._backend.apply_lifecycle(original,context,decision,now_ns=started)
                    if type(value) is ModelLifecycleReceipt:
                        receipt=value
                finally:
                    completed=self._observe_time(started)
                self._admitted(request,completed)
                self._receipt(receipt,context,decision,identity,original,started,completed)
                self._scope_check(scope,context,completed,sid)
                self._cleanup_active=True
                try:
                    if decision.new_session:
                        retirement=self._receiver.retire_run(sid,now_ns=completed)
                        if retirement.error is not None or retirement.retired_sessions!=selected:
                            raise ICDError(retirement.error or 'STATE','original lifecycle retirement did not complete')
                    elif decision.clear_queues:
                        for actor in selected:
                            if queue is not None:
                                queue.discard_session(actor)
                            assembler.discard_session(actor)
                    self._check()
                    if (self._registry._model_queue is not queue or self._registry._resource_worker is not worker
                            or self._receiver.assembler is not assembler
                            or assembler is not self._receiver._run_assembler):
                        raise ICDError('STATE','original lifecycle local owners changed during cleanup')
                    if decision.clear_queues and (
                            queue is not None and any(p.key[0] in selected for p in queue._pending.values())
                            or any(key[3] in selected for key in assembler._groups)):
                        raise ICDError('STATE','original lifecycle selected inputs/fragments were not cleared')
                    if queue is not None:
                        queue._steps[identity['model_id']]=receipt.view.model_step
                finally:
                    self._cleanup_active=False
                    completed=self._observe_time(completed)
                self._check()
                if completed>=min(origin.deadline_ns,received+request['header']['valid_for_ms']*1000000,
                                  receipt.deadline_ns,receipt.sampled_ns+240000000):
                    raise ICDError('EXPIRED','lifecycle completion expired after actual local effects')
                reply={'message_id':130,'header':terminal,'payload':{
                    'request_sequence':key[1],'request_message_id':4,'stage':'APPLIED','error':'OK',
                    'applied_step':receipt.view.model_step,'model_revision':receipt.model_revision,'probe_id':1004}}
            except ICDError as exc:
                error=exc.code
            except Exception:
                error='RESOURCE'
            finally:
                if error is not None:
                    reply={'message_id':130,'header':terminal,'payload':{'request_sequence':key[1],
                        'request_message_id':4,'stage':'FAILED','error':error,'applied_step':0,'model_revision':0,'probe_id':0}}
                removed=tuple(p for p in inputs if queue is not None and p.key not in queue._pending)
                discarded=tuple(g for g in groups if g.key not in assembler._groups)
                replies=(received_reply,reply)
                record=ModelLifecycleRecord(original,received,completed,context,receipt,decision,attempted,
                    inputs,removed,groups,discarded,retirement,canonicalize(reply),error)
                self._records.append(record)
                self._bytes+=record.stored_bytes
            self._completion=(original,canonicalize(list(replies)),completed,admission)
            self._registry._record_lifecycle_response(request,replies,self,now_ns=completed)
            return replies
        finally:
            self._cleanup_active=False
            self._completion=self._operation_thread=None
            self._lock.release()

    def close(self):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','cannot close lifecycle service during original operation')
        try:
            self._check(closed_ok=True)
            self._closed=True
        finally:
            self._lock.release()
