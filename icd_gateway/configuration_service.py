"""Explicit actual RunConfigure consumer with complete post-write readback."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import threading
import time

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .semantic_guards import ModelView, SemanticGuards
from .session import SessionRegistry


MAX_TIME=2**64-1
MAX_BYTES=65536


def _sample(identity,view,sampled,deadline):
    if (type(identity) is not bytes or not 1<=len(identity)<=4096 or type(view) is not ModelView
            or len(view.model_id)>64 or type(view.state) is not str or type(view.control_source) is not str
            or type(sampled) is not int or type(deadline) is not int
            or not 0<=sampled<deadline<=MAX_TIME):
        raise ICDError('SCHEMA','bounded immutable actual configuration context and uint64 times required')


@dataclass(frozen=True, slots=True)
class ModelConfigurationContext:
    identity_json: bytes
    request_json: bytes
    view: ModelView
    ground_down: float | None
    sampled_ns: int
    deadline_ns: int

    def __post_init__(self):
        _sample(self.identity_json,self.view,self.sampled_ns,self.deadline_ns)
        if type(self.request_json) is not bytes or not 1<=len(self.request_json)<=MAX_BYTES+4096:
            raise ICDError('SCHEMA','immutable bounded original configuration request required')
        if self.ground_down is not None:
            try:
                valid=type(self.ground_down) in (int,float) and math.isfinite(self.ground_down)
            except OverflowError:
                valid=False
            if not valid:
                raise ICDError('SCHEMA','actual finite terrain ground sample required')


@dataclass(frozen=True, slots=True)
class ModelConfigurationReceipt:
    identity_json: bytes
    request_json: bytes
    configuration_json: bytes
    initial_state_json: bytes
    initial_inputs_json: bytes
    view: ModelView
    model_revision: int
    sampled_ns: int
    deadline_ns: int

    def __post_init__(self):
        _sample(self.identity_json,self.view,self.sampled_ns,self.deadline_ns)
        for raw,maximum in ((self.request_json,MAX_BYTES+4096),(self.configuration_json,MAX_BYTES),
                            (self.initial_state_json,4096),(self.initial_inputs_json,MAX_BYTES)):
            if type(raw) is not bytes or not 1<=len(raw)<=maximum:
                raise ICDError('SCHEMA','complete immutable bounded actual configuration readback required')
        if type(self.model_revision) is not int or not 0<=self.model_revision<=0xffffffff:
            raise ICDError('SCHEMA','actual uint32 model revision required')


class ModelConfigurationBackend(ABC):
    def __init__(self, contract, model_ids):
        if not isinstance(contract,Contract) or not contract.component_hashes:
            raise ICDError('HASH','verified actual configuration backend contract required')
        if (type(model_ids) is not tuple or not model_ids
                or any(type(m) is not str or m not in contract.entry(3)['model_ids'] for m in model_ids)
                or len(set(model_ids))!=len(model_ids)):
            raise ICDError('MODEL','explicit distinct frozen configuration models required')
        self.contract,self.model_ids=contract,model_ids

    @abstractmethod
    def read_context(self, identity, request_json, *, now_ns):
        """Read actual state and requested terrain at the requested initial point.

        Resolve the exact request's resource hash, origin and frame before sampling;
        retain that request with the sample in the receiving clock domain.
        """

    @abstractmethod
    def apply_configuration(self, request_json, context, *, now_ns):
        """Prepare all resources/model/initial inputs once, then read actual results.

        The backend must own an atomic model safety boundary, recheck the supplied
        actual context before any effect, and not copy request values as readback.
        A thrown/invalid result does not imply rollback or absence of effects.
        """


@dataclass(frozen=True, slots=True)
class ModelConfigurationRecord:
    request_json: bytes
    received_ns: int
    completed_ns: int
    context: ModelConfigurationContext | None
    receipt: ModelConfigurationReceipt | None
    write_attempted: bool
    reply_json: bytes | None
    error: str | None

    @property
    def stored_bytes(self):
        size=512+len(self.request_json)+len(self.reply_json or b'')
        if self.context is not None:
            size+=len(self.context.identity_json)+len(self.context.request_json)+512
        if self.receipt is not None:
            size+=512+sum(len(getattr(self.receipt,name)) for name in
                ('identity_json','request_json','configuration_json','initial_state_json','initial_inputs_json'))
        return size


class ModelConfigurationService:
    def __init__(self, contract, registry, backend, *, max_records=4096,max_bytes=16*1024*1024,
                 clock=time.monotonic_ns):
        if (not isinstance(contract,Contract) or not contract.component_hashes
                or type(registry) is not SessionRegistry or registry.contract is not contract):
            raise ICDError('HASH','same actual verified configuration contract/registry required')
        if not isinstance(backend,ModelConfigurationBackend) or backend.contract is not contract:
            raise ICDError('TARGET_MISSING','explicit actual same-contract configuration backend required')
        if (type(max_records) is not int or not 1<=max_records<=65536
                or type(max_bytes) is not int or not 1<=max_bytes<=128*1024*1024 or not callable(clock)):
            raise ICDError('CAPACITY','finite original configuration service history required')
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

    def _check(self, *, closed_ok=False):
        if (self.contract is not self._contract or self.registry is not self._registry
                or self.backend is not self._backend or self._backend.contract is not self._contract
                or self._backend.model_ids!=self._models or self._registry.contract is not self._contract
                or self._clock is not self._original_clock
                or self._receiver is not None and (self._receiver.contract is not self._contract
                    or self._receiver.registry is not self._registry
                    or self._receiver.configuration_service is not self
                    or self._receiver._configuration_service is not self)):
            raise ICDError('STATE','original configuration service owners cannot be replaced')
        if self._closed and not closed_ok:
            raise ICDError('STATE','original configuration service is closed')

    def _bind(self, receiver):
        from .receiver import Receiver
        self._check()
        if type(receiver) is not Receiver or self._receiver is not None:
            raise ICDError('STATE','one original actual configuration receiver required')
        self._receiver=receiver
        self._check()

    def supports(self, model_id):
        self._check()
        return model_id in self._models

    def _observe_time(self, received):
        now=self._clock()
        if (type(now) is not int or not 0<=now<=MAX_TIME or now<received
                or self._last_observed_ns is not None and now<self._last_observed_ns):
            raise ICDError('CLOCK_UNSYNC','actual configuration clock differs or regressed')
        self._last_observed_ns=now
        return now

    def _admitted(self, request, now):
        self._check()
        received=self._registry.observe_admitted(request,now_ns=now)
        if now>=received+request['header']['valid_for_ms']*1000000:
            raise ICDError('EXPIRED','original configuration request expired')
        return received

    def _context(self, context,identity,original,now):
        if type(context) is not ModelConfigurationContext:
            raise ICDError('STATE','actual immutable configuration context required')
        if loads(context.identity_json)!=identity or context.view.model_id!=identity['model_id']:
            raise ICDError('MODEL','actual configuration context belongs to another run/model')
        if canonicalize(loads(context.request_json))!=original:
            raise ICDError('DUPLICATE','terrain/safety context does not name the original configuration request')
        if not context.sampled_ns<=now<min(context.deadline_ns,context.sampled_ns+240000000):
            raise ICDError('EXPIRED','actual configuration safety context is future or expired')

    def _queue(self, context):
        queue=self._registry._model_queue
        if queue is None:
            return
        from .model_queue import ModelQueue
        if type(queue) is not ModelQueue or queue.contract is not self._contract or queue.registry is not self._registry:
            raise ICDError('STATE','original configuration model queue owner required')
        model=context.view.model_id
        if model not in queue._steps:
            raise ICDError('TARGET_MISSING','selected configuration model has no original queue')
        if queue._steps[model]!=context.view.model_step or any(p.model_id==model for p in queue._pending.values()):
            raise ICDError('STATE','configuration requires the empty actual frozen model boundary')

    def _receipt(self, receipt,original,context,identity,write_started,now):
        if type(receipt) is not ModelConfigurationReceipt:
            raise ICDError('STATE','actual post-write immutable configuration receipt required')
        if loads(receipt.identity_json)!=identity or receipt.view.model_id!=identity['model_id']:
            raise ICDError('MODEL','actual configuration receipt belongs to another run/model')
        if canonicalize(loads(receipt.request_json))!=original:
            raise ICDError('DUPLICATE','actual configuration receipt does not name the original request')
        if not write_started<=receipt.sampled_ns<=now<min(receipt.deadline_ns,receipt.sampled_ns+240000000):
            raise ICDError('EXPIRED','actual post-write configuration readback is future or expired')
        expected=loads(original)['payload']
        config=loads(receipt.configuration_json)
        state,inputs=loads(receipt.initial_state_json),loads(receipt.initial_inputs_json)
        self._contract.validate_payload(3,config)
        if (canonicalize(config)!=canonicalize(expected)
                or canonicalize(state)!=canonicalize(expected['initial_state'])
                or canonicalize(inputs)!=canonicalize(expected['initial_inputs'])):
            raise ICDError('BUSINESS_FAILED','complete actual configuration/state/input readback differs')
        view=receipt.view
        if (view.state!='CONFIGURED' or not view.configured_once or view.control_source!='NONE'
                or view.model_step!=context.view.model_step
                or view.max_duration_steps!=config['max_duration_steps']
                or view.physical_closed_loop!=context.view.physical_closed_loop):
            raise ICDError('STATE','actual configured model boundary/readiness differs')

    def _owns_completed_reply(self, request,replies,now):
        self._check()
        return (self._operation_thread==threading.get_ident() and self._lock.locked()
            and self._completion is not None and self._completion[0]==canonicalize(request)
            and self._completion[1] is not None and self._completion[2]==canonicalize(list(replies))
            and self._completion[3]==now)

    def respond(self, request,received_reply, *, now_ns):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','single non-reentrant configuration operation required')
        try:
            self._operation_thread=threading.get_ident()
            self._check()
            if self._receiver is None or self._receiver._closed or self._receiver._closing:
                raise ICDError('STATE','live original configuration receiver required')
            self._contract.validate_message(request,direction='TO_36')
            if request['message_id']!=3:
                raise ICDError('UNSUPPORTED','only original RunConfigure is handled')
            if any(type(v) is not int for v in request['header'].values()):
                raise ICDError('SCHEMA','strict original request header integers required')
            received=self._admitted(request,now_ns)
            identity=self._registry.identity(request['header']['session_id'])
            if not self.supports(identity['model_id']):
                raise ICDError('TARGET_MISSING','actual model has no configuration backend')
            original=canonicalize(request)
            key=(request['header']['session_id'],request['header']['sequence'])
            if key in self._attempted:
                raise ICDError('STATE','original configuration already attempted; no backend retry')
            # Failed receipts may contain independent maximum-sized raw fields.
            reserve=24576+len(original)+4*MAX_BYTES
            if len(self._records)>=self._max_records or self._bytes+reserve>self._max_bytes:
                raise ICDError('BUFFER_FULL','retain complete configuration evidence before getter/write')
            self._attempted.add(key)
            context=receipt=reply=error=None
            attempted=False
            completed=now_ns
            try:
                try:
                    value=self._backend.read_context(dict(identity),original,now_ns=now_ns)
                    if type(value) is ModelConfigurationContext:
                        context=value
                finally:
                    completed=self._observe_time(now_ns)
                self._admitted(request,completed)
                self._context(context,identity,original,completed)
                SemanticGuards(self._contract).run_configure(request,context.view,terrain_ground_down=context.ground_down)
                self._queue(context)
                if self._registry._sessions[key[0]].last_tx==0xffffffff:
                    raise ICDError('CAPACITY','original configuration feedback sequence exhausted before write')
                started=completed
                attempted=True
                try:
                    value=self._backend.apply_configuration(original,context,now_ns=started)
                    if type(value) is ModelConfigurationReceipt:
                        receipt=value
                finally:
                    completed=self._observe_time(started)
                self._admitted(request,completed)
                self._receipt(receipt,original,context,identity,started,completed)
                from icd_runtime.wire import Header
                reply=self._receiver._ack(3,Header(**request['header']),stage='APPLIED',error='OK')
                reply['payload'].update(applied_step=receipt.view.model_step,model_revision=receipt.model_revision,
                    probe_id=next(p['id'] for p in self._contract.catalogue['probe_catalog'] if p['name']=='consumer.RunConfigure'))
                self._contract.validate_message(reply,direction='FROM_36',model_id=identity['model_id'])
                replies=(received_reply,reply)
                self._completion=(original,receipt,canonicalize(list(replies)),completed)
                self._registry._record_configuration_response(request,replies,self,now_ns=completed)
            except ICDError as exc:
                error=exc.code
                raise
            except Exception as exc:
                error='RESOURCE'
                raise ICDError(error,'actual configuration backend/readback failed') from exc
            finally:
                record=ModelConfigurationRecord(original,received,completed,context,receipt,attempted,
                    canonicalize(reply) if reply is not None and error is None else None,error)
                self._records.append(record)
                self._bytes+=record.stored_bytes
            return replies
        finally:
            self._completion=self._operation_thread=None
            self._lock.release()

    def close(self):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','cannot close configuration service during its original operation')
        try:
            self._check(closed_ok=True)
            self._closed=True
        finally:
            self._lock.release()
