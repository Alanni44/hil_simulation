"""Explicit model-backed standard Heartbeat/Status service; no model defaults."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import threading
import time

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .session import SessionRegistry


MAX_SAMPLE_BYTES=4096
MAX_TIME=(1 << 64)-1


@dataclass(frozen=True, slots=True)
class ModelStatusSample:
    identity_json: bytes
    payload_json: bytes
    sampled_ns: int
    deadline_ns: int

    def __post_init__(self):
        if (type(self.identity_json) is not bytes or type(self.payload_json) is not bytes
                or not 1 <= len(self.identity_json) <= MAX_SAMPLE_BYTES
                or not 1 <= len(self.payload_json) <= MAX_SAMPLE_BYTES
                or type(self.sampled_ns) is not int or type(self.deadline_ns) is not int
                or not 0 <= self.sampled_ns < self.deadline_ns <= MAX_TIME):
            raise ICDError('SCHEMA','immutable bounded model sample bytes and uint64 times required')


class ModelStatusBackend(ABC):
    def __init__(self, contract, model_ids):
        if not isinstance(contract,Contract) or not contract.component_hashes:
            raise ICDError('HASH','original verified model backend contract required')
        models=contract.entry(2)['model_ids']
        if (type(model_ids) is not tuple or not model_ids
                or any(type(m) is not str or m not in models for m in model_ids)
                or len(set(model_ids))!=len(model_ids)):
            raise ICDError('MODEL','explicit distinct frozen backend models required')
        self.contract=contract
        self.model_ids=model_ids

    @abstractmethod
    def read_status(self, identity, *, now_ns):
        """Read a coherent actual applied snapshot; never derive it from the request."""


@dataclass(frozen=True, slots=True)
class ModelStatusRecord:
    request_json: bytes
    received_ns: int
    completed_ns: int
    sample: ModelStatusSample | None
    reply_json: bytes | None
    error: str | None

    @property
    def stored_bytes(self):
        return (512+len(self.request_json)+len(self.reply_json or b'')
                +(0 if self.sample is None else len(self.sample.identity_json)+len(self.sample.payload_json)))


class ModelStatusService:
    def __init__(self, contract, registry, backend, *, max_records=4096, max_bytes=16*1024*1024,
                 clock=time.monotonic_ns):
        if (not isinstance(contract,Contract) or not contract.component_hashes
                or type(registry) is not SessionRegistry or registry.contract is not contract):
            raise ICDError('HASH','same actual verified contract and registry required')
        if not isinstance(backend,ModelStatusBackend) or backend.contract is not contract:
            raise ICDError('TARGET_MISSING','explicit same-contract model status backend required')
        if (type(max_records) is not int or not 1 <= max_records <= 65536
                or type(max_bytes) is not int or not 1 <= max_bytes <= 128*1024*1024
                or not callable(clock)):
            raise ICDError('CAPACITY','finite original model status history required')
        self.contract,self.registry,self.backend=contract,registry,backend
        self._contract,self._registry,self._backend=contract,registry,backend
        self._models=backend.model_ids
        self._receiver=None
        self._records=[]
        self._bytes=0
        self._max_records,self._max_bytes=max_records,max_bytes
        self._floors={}
        self._attempted=set()
        self._opening_errors={}
        self._closed=False
        self._lock=threading.Lock()
        self._clock=clock
        self._last_observed_ns=None

    @property
    def last_observed_ns(self):
        return self._last_observed_ns

    def _observe_time(self, received_ns):
        now=self._clock()
        if (type(now) is not int or not 0 <= now <= MAX_TIME or now<received_ns
                or self._last_observed_ns is not None and now<self._last_observed_ns):
            raise ICDError('CLOCK_UNSYNC','actual status service clock regressed or differs from ingress domain')
        self._last_observed_ns=now
        return now

    @property
    def records(self):
        return tuple(self._records)

    @property
    def stored_bytes(self):
        return self._bytes

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
                or self._receiver is not None and (self._receiver.registry is not self._registry
                    or self._receiver.contract is not self._contract or self._receiver.status_service is not self)):
            raise ICDError('STATE','original status owners cannot be replaced')
        if self._closed and not closed_ok:
            raise ICDError('STATE','original status service is closed')

    def _bind(self, receiver):
        from .receiver import Receiver
        self._check()
        if (self._receiver is not None or type(receiver) is not Receiver
                or receiver.registry is not self._registry or receiver.contract is not self._contract):
            raise ICDError('STATE','status service needs one original receiver owner')
        self._receiver=receiver

    def supports(self, model):
        self._check()
        return model in self._models

    def respond(self, request, *, now_ns):
        return self._respond(request, now_ns=now_ns)

    def open_response(self, request, binding, *, now_ns):
        return self._respond(request, opening_binding=binding, now_ns=now_ns)

    def _respond(self, request, *, now_ns, opening_binding=None):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','single non-reentrant status service owner required')
        try:
            self._check()
            if self._receiver is None:
                raise ICDError('STATE','original receiver binding required')
            if type(now_ns) is not int or not 0 <= now_ns <= MAX_TIME:
                raise ICDError('SCHEMA','explicit uint64 receiver observation time required')
            completed=self._observe_time(now_ns)
            self.contract.validate_message(request,direction='TO_36')
            opening=opening_binding is not None
            if request['message_id']!=(1 if opening else 2):
                raise ICDError('UNSUPPORTED','original opening or Heartbeat operation required')
            if (type(request['message_id']) is not int
                    or any(type(value) is not int for value in request['header'].values())):
                raise ICDError('SCHEMA','original wire request integer types required')
            original=canonicalize(request)
            if opening:
                preview=self.registry.preview_open(request,opening_binding,now_ns=now_ns)
                if preview.replay is not None:
                    raise ICDError('STATE','opening retry must use original receiver cache')
                identity=request['payload']['identity']
                key=('OPEN',self.registry.open_namespace(opening_binding),original)
            else:
                self.registry.observe_admitted(request,now_ns=now_ns)
                identity=self.registry.identity(request['header']['session_id'])
                key=(request['header']['session_id'],request['header']['sequence'])
            if key in self._attempted:
                raise ICDError(self._opening_errors.get(key,'STATE'),
                               'original model read already attempted; no backend retry')
            if not self.supports(identity['model_id']):
                raise ICDError('TARGET_MISSING','original model has no installed status backend')
            reserve=512+len(original)+3*MAX_SAMPLE_BYTES
            if len(self._records)>=self._max_records or self._bytes+reserve>self._max_bytes:
                raise ICDError('BUFFER_FULL','retain status evidence before another backend read')
            self._attempted.add(key)
            sample,reply,error=None,None,None
            try:
                try:
                    value=self._backend.read_status(dict(identity),now_ns=now_ns)
                    if type(value) is ModelStatusSample:
                        sample=value
                finally:
                    completed=self._observe_time(now_ns)
                if opening:
                    if completed >= now_ns+request['header']['valid_for_ms']*1_000_000:
                        raise ICDError('EXPIRED','opening model read outlived the original request')
                    preview=self.registry.preview_open(request,opening_binding,now_ns=completed)
                    if preview.replay is not None:
                        raise ICDError('STATE','original open was completed during backend read')
                else:
                    self.registry.observe_admitted(request,now_ns=completed)
                if type(value) is not ModelStatusSample:
                    raise ICDError('STATE','backend must return its immutable actual model sample')
                if loads(sample.identity_json)!=identity:
                    raise ICDError('MODEL','actual model sample belongs to another run identity')
                payload=loads(sample.payload_json)
                self.contract.validate_payload(131,payload)
                for field,value in payload.items():
                    expected=bool if field=='safety_active' else str if field in ('state','phase','control_source') else int
                    if type(value) is not expected:
                        raise ICDError('SCHEMA','model status values require exact frozen types')
                if not sample.sampled_ns <= completed < min(sample.deadline_ns,
                        sample.sampled_ns+self.contract.entry(131)['valid_for_ms']*1_000_000):
                    raise ICDError('EXPIRED','actual model snapshot is future or expired')
                sid=request['header']['session_id']
                floor=None if opening else self._floors.get(sid)
                if floor is not None and (sample.sampled_ns<floor[0] or payload['model_step']<floor[1]):
                    raise ICDError('CLOCK_UNSYNC','actual same-session model sample regressed')
                self._check()
                if opening:
                    decision=self.registry.accept(request,opening_binding,now_ns=completed)
                    sid=decision.session_id
                    reply=self._receiver._opened(sid,request['header']['transaction_id'],
                                                 receiver_step=payload['model_step'])
                else:
                    self.registry.observe_admitted(request,now_ns=completed)
                    header=self._receiver._header(131,sid,request['header']['transaction_id'])
                    header['target_step']=payload['model_step']
                    reply={'message_id':131,'header':header,'payload':payload}
                self.contract.validate_message(reply,direction='FROM_36',model_id=identity['model_id'])
                encoded=canonicalize(reply)
                if len(encoded)>MAX_SAMPLE_BYTES:
                    raise ICDError('CAPACITY','standard status reply exceeds evidence reservation')
                self._floors[sid]=(sample.sampled_ns,payload['model_step'])
            except ICDError as exc:
                error=exc.code
                if opening:
                    self._opening_errors[key]=error
                raise
            except Exception as exc:
                error='RESOURCE'
                if opening:
                    self._opening_errors[key]=error
                raise ICDError(error,'actual model status backend failed') from exc
            finally:
                record=ModelStatusRecord(original,now_ns,completed,sample,
                                         canonicalize(reply) if error is None and reply is not None else None,error)
                self._records.append(record)
                self._bytes+=record.stored_bytes
            return reply
        finally:
            self._lock.release()

    def close(self):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE','cannot close status service during its original read')
        try:
            self._check(closed_ok=True)
            self._closed=True
        finally:
            self._lock.release()
