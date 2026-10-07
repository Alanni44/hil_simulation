"""Standard ingress with honest E1/failure feedback; no fabricated model state."""

from collections import Counter, deque
from dataclasses import dataclass

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import WireCodec


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    expired_sessions: tuple
    rejected_inputs: tuple


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    closed_sessions: tuple
    discarded_inputs: tuple
    resource_shutdown: object = None


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    outcome: object
    reply_bytes: bytes | None
    error: str | None


@dataclass(frozen=True, slots=True)
class RetiredAssembly:
    key: tuple
    first: object
    deadline_ns: int
    reserved_bytes: int
    pieces: tuple

    @property
    def stored_bytes(self):
        return 1024+len(self.first.payload)+sum(128+len(raw) for _,raw in self.pieces)


@dataclass(frozen=True, slots=True)
class RunRetirement:
    origin_session_id: int
    identity_json: bytes
    observed_ns: int
    selected_sessions: tuple
    retired_sessions: tuple
    captured_inputs: tuple
    discarded_inputs: tuple
    captured_groups: tuple
    discarded_groups: tuple
    error: str | None

    @property
    def stored_bytes(self):
        return (512+len(self.identity_json)+64*len(self.selected_sessions)
            +sum(p.stored_bytes+128 for p in self.captured_inputs)
            +sum(g.stored_bytes for g in self.captured_groups))

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


class Receiver:
    def __init__(self, contract, registry, *, maintenance_input_capacity=4096,
                 resource_worker=None, resource_record_capacity=64, status_service=None,
                 configuration_service=None, run_retirement_capacity=64,
                 run_retirement_bytes=16*1024*1024, lifecycle_service=None, reception_service=None):
        if type(maintenance_input_capacity) is not int or not 1 <= maintenance_input_capacity <= 4096:
            raise ICDError("CAPACITY", "maintenance input storage requires1..4096 entries")
        if type(resource_record_capacity) is not int or not 1 <= resource_record_capacity <= 64:
            raise ICDError("CAPACITY", "resource completion storage requires1..64 entries")
        if (type(run_retirement_capacity) is not int or not 1<=run_retirement_capacity<=4096
                or type(run_retirement_bytes) is not int or not 1<=run_retirement_bytes<=128*1024*1024):
            raise ICDError('CAPACITY','finite retained run-retirement history required')
        if resource_worker is not None:
            from .resource_worker import ResourceWorker
            if (type(resource_worker) is not ResourceWorker or resource_worker.contract is not contract
                    or resource_worker.registry is not registry
                    or registry._resource_worker is not resource_worker or not resource_worker.available):
                raise ICDError("STATE", "actual owned same-contract resource worker required")
        self.contract = contract
        self.registry = registry
        self.wire = WireCodec(contract)
        self.assembler = Reassembler(contract, retain_completed=False)
        self._run_contract,self._run_registry,self._run_assembler=contract,registry,self.assembler
        self._run_records,self._run_by_origin=[],{}
        self._run_capacity,self._run_byte_capacity=run_retirement_capacity,run_retirement_bytes
        self._run_bytes=self._run_inputs=0
        self._run_busy=self._run_queue_bound=False
        self._run_queue=None
        self._run_allowed_sid=None
        self._run_worker_bound=False
        self._run_worker=self._run_receiver_worker=None
        self.admitted_count = 0
        self.errors = Counter()
        self.error_details = deque(maxlen=128)
        self._zero_feedback_sequence = 0
        self._closed = False
        self._maintenance_capacity = maintenance_input_capacity
        self._maintenance_session_capacity = contract.catalogue["policy"]["duplicate_cache_messages"]
        self._maintenance = MaintenanceResult((), ())
        self._shutdown = ShutdownResult((), ())
        self.resource_worker = resource_worker
        self._resource_capacity = resource_record_capacity
        self._resource_records = deque()
        self._closing = False
        self.status_service = status_service
        self._status_service = status_service
        self.configuration_service=configuration_service
        self._configuration_service=configuration_service
        self.lifecycle_service=self._lifecycle_service=lifecycle_service
        self.reception_service=self._reception_service=reception_service
        if reception_service is not None:
            from .reception_service import ReceptionService
            if (type(reception_service) is not ReceptionService or reception_service.contract is not contract
                    or reception_service.registry is not registry):
                raise ICDError('STATE','actual same-owner reception service required')
        if lifecycle_service is not None:
            from .lifecycle_service import ModelLifecycleService
            if (type(lifecycle_service) is not ModelLifecycleService or lifecycle_service.contract is not contract
                    or lifecycle_service.registry is not registry):
                raise ICDError('STATE','actual same-owner lifecycle service required')
            lifecycle_service._bind(self)
        if configuration_service is not None:
            from .configuration_service import ModelConfigurationService
            if (type(configuration_service) is not ModelConfigurationService
                    or configuration_service.contract is not contract or configuration_service.registry is not registry):
                raise ICDError('STATE','actual same-owner configuration service required')
            configuration_service._bind(self)
        if status_service is not None:
            from .status_service import ModelStatusService
            if (type(status_service) is not ModelStatusService or status_service.contract is not contract
                    or status_service.registry is not registry):
                raise ICDError('STATE', 'actual same-owner status service required')
            status_service._bind(self)

    def note_error(self, error):
        self.errors[error.code] += 1
        self.error_details.append((error.code, error.detail[:256]))

    def tick(self, *, now_ns):
        if self._closed or self._closing or self._run_busy or self._lifecycle_active():
            raise ICDError("STATE", "receiver is closed")
        expired, rejected = self.registry.preview_maintenance(now_ns=now_ns)
        self.assembler.check_clock(now_ns)
        if self.resource_worker is not None and self.resource_worker.available:
            self.resource_worker.check_clock(now_ns)
        if (len(self._maintenance.rejected_inputs) + len(rejected) > self._maintenance_capacity
                or len(self._maintenance.expired_sessions) + len(expired)
                > self._maintenance_session_capacity):
            raise ICDError("BUFFER_FULL", "drain maintenance records before deleting more inputs/sessions")
        expired = tuple(self.registry.expire(now_ns=now_ns))
        rejected = self.registry.expire_model_inputs(now_ns=now_ns)
        self._maintenance = MaintenanceResult(self._maintenance.expired_sessions + expired,
                                              self._maintenance.rejected_inputs + rejected)
        self.assembler.discard_inactive_sessions(self.registry.session_ids)
        self.assembler.expire(now_ns=now_ns)
        if self.resource_worker is not None and self.resource_worker.available:
            self.resource_worker.synchronize_sessions(self.registry.session_ids, now_ns=now_ns)
        return self._maintenance

    def resource_feedback(self, *, now_ns):
        self.tick(now_ns=now_ns)
        if self.resource_worker is None:
            return ()
        replies = []
        for outcome in self.resource_worker.peek_results():
            if len(self._resource_records) >= self._resource_capacity:
                break
            reply, error = None, None
            try:
                request = loads(outcome.request_bytes)
                sid = int(request["header"]["session_id"])
                if sid not in self.registry.session_ids:
                    raise ICDError("STALE_SESSION", "resource outcome belongs to a retired session")
                reply = {"message_id": 141,
                         "header": self._header(141, sid, int(request["header"]["transaction_id"])),
                         "payload": loads(outcome.payload_bytes)}
                self.registry.finish_resource_response(request, reply, now_ns=now_ns)
            except ICDError as exc:
                self.note_error(exc)
                reply, error = None, exc.code
            record = ResourceRecord(outcome, canonicalize(reply) if reply is not None else None, error)
            self._resource_records.append(record)
            self.resource_worker.release_result(outcome.key)
            if reply is not None:
                replies.append((outcome.binding, reply))
        return tuple(replies)

    def drain_resource_records(self):
        if self._run_busy or self._lifecycle_active():
            raise ICDError('STATE','cannot drain records during original run retirement')
        result = tuple(self._resource_records)
        self._resource_records.clear()
        return result

    def drain_maintenance(self):
        if self._run_busy or self._lifecycle_active():
            raise ICDError('STATE','cannot drain records during original run retirement')
        result = self._maintenance
        self._maintenance = MaintenanceResult((), ())
        return result

    def drain_shutdown(self):
        if self._run_busy or self._lifecycle_active():
            raise ICDError('STATE','cannot drain records during original run retirement')
        result = self._shutdown
        self._shutdown = ShutdownResult((), ())
        return result

    def retire_session(self, session_id):
        if self._closed:
            raise ICDError("STATE", "receiver is closed")
        if self._lifecycle_active() and not (self._run_busy and self._lifecycle_cleanup_owned()):
            raise ICDError('STATE','cannot independently retire during original lifecycle operation')
        if self._run_busy:
            if type(session_id) is not int or session_id != self._run_allowed_sid:
                raise ICDError('STATE','only the original selected retirement operation may delete a session')
            self._check_run_retirement_owners()
            self._run_allowed_sid=None
        removed = self.registry.retire(session_id)
        self.assembler.discard_session(session_id)
        return removed

    @property
    def run_retirements(self):
        return tuple(self._run_records)

    def _check_run_retirement_owners(self):
        worker=self._run_worker
        if (self.registry is not self._run_registry or self.assembler is not self._run_assembler
                or self.contract is not self._run_contract or self.registry.contract is not self._run_contract
                or self.registry._model_queue is not self._run_queue
                or self.registry._resource_worker is not worker or self.resource_worker is not self._run_receiver_worker
                or (worker is not None and (worker.registry is not self._run_registry
                    or worker.contract is not self._run_contract
                    or worker.store.contract is not self._run_contract))):
            raise ICDError('STATE','original retirement owners changed during cleanup')

    def _check_run_retirement_capacity(self,record):
        if (len(self._run_records)>=self._run_capacity or self._run_bytes+record.stored_bytes>self._run_byte_capacity
                or self._run_inputs+len(record.captured_inputs)>self._maintenance_capacity):
            raise ICDError('BUFFER_FULL','retain all original retirement evidence before deletion')

    def retire_run(self, origin_session_id, *, now_ns):
        """Local serial-owner cleanup; never proves model RESET/RESUME or safety."""
        if self._closed or self._closing or self._run_busy:
            raise ICDError('STATE','live non-reentrant original retirement owner required')
        if self._lifecycle_active() and not self._lifecycle_cleanup_owned():
            raise ICDError('STATE','only original lifecycle completion may retire its run')
        from .session import SessionRegistry
        if (type(self.registry) is not SessionRegistry or self.registry is not self._run_registry
                or self.contract is not self._run_contract or self.registry.contract is not self.contract
                or self.assembler is not self._run_assembler):
            raise ICDError('STATE','original run registry/contract/reassembler cannot be replaced')
        if type(origin_session_id) is not int or not 1<=origin_session_id<=0xffffffff:
            raise ICDError('SCHEMA','original nonzero uint32 origin session required')
        if type(now_ns) is not int or not 0<=now_ns<=2**64-1:
            raise ICDError('SCHEMA','actual receiver uint64 observation time required')
        self.registry.check_clock(now_ns)
        self.assembler.check_clock(now_ns)
        registry,assembler=self.registry,self.assembler
        queue=registry._model_queue
        if queue is not None:
            from .model_queue import ModelQueue
            if type(queue) is not ModelQueue or queue.contract is not self.contract or queue.registry is not registry:
                raise ICDError('STATE','original same-owner model queue required')
            queue.check_clock(now_ns)
        if self._run_queue_bound and queue is not self._run_queue:
            raise ICDError('STATE','original retirement queue cannot be replaced')
        worker,receiver_worker=registry._resource_worker,self.resource_worker
        if worker is not None:
            from .resource_worker import ResourceWorker
            if (type(worker) is not ResourceWorker or worker.contract is not self._run_contract
                    or worker.registry is not registry or worker.store.contract is not self._run_contract):
                raise ICDError('STATE','actual original same-owner resource worker required')
            worker.check_clock(now_ns)
        if receiver_worker is not None and receiver_worker is not worker:
            raise ICDError('STATE','receiver resource worker must be the original attached worker')
        if self._run_worker_bound and (worker is not self._run_worker
                or receiver_worker is not self._run_receiver_worker):
            raise ICDError('STATE','original retirement resource owners cannot be replaced')
        if origin_session_id in self._run_by_origin:
            self.registry._clock(now_ns)
            return self._run_by_origin[origin_session_id]
        selected=self.registry.run_session_ids(origin_session_id,now_ns=now_ns)
        identity=canonicalize(self.registry.identity(origin_session_id))
        inputs=tuple(p for p in queue._pending.values() if p.key[0] in selected) if queue is not None else ()
        groups=tuple(RetiredAssembly(key,group.first,group.deadline_ns,group.reserved,
            tuple(sorted(group.pieces.items()))) for key,group in self.assembler._groups.items() if key[3] in selected)
        self._check_run_retirement_capacity(RunRetirement(origin_session_id,identity,now_ns,selected,(),inputs,(),groups,(),None))
        self._run_queue,self._run_queue_bound=queue,True
        self._run_worker,self._run_receiver_worker=worker,receiver_worker
        self._run_worker_bound=True
        self._run_busy=True
        operation=self.retire_session
        error=None
        try:
            for sid in selected:
                self._run_allowed_sid=sid
                operation(sid)
                self._check_run_retirement_owners()
                if self.retire_session!=operation:
                    raise ICDError('STATE','original retirement owners changed during cleanup')
        except ICDError as exc:
            error=exc.code
        except Exception:
            error='RESOURCE'
        finally:
            retired=tuple(sid for sid in selected if sid not in registry.session_ids)
            removed=tuple(p for p in inputs if p.key not in queue._pending) if queue is not None else ()
            discarded=tuple(g for g in groups if g.key not in assembler._groups)
            record=RunRetirement(origin_session_id,identity,now_ns,selected,retired,inputs,removed,groups,discarded,error)
            self._run_records.append(record)
            self._run_by_origin[origin_session_id]=record
            self._run_bytes+=record.stored_bytes
            self._run_inputs+=len(inputs)
            self._run_allowed_sid=None
            self._run_busy=False
        return record

    def close(self):
        if self._closed:
            return ()
        if self._run_busy:
            raise ICDError('STATE','cannot close during original run retirement')
        self._check_status_service(closed_ok=True)
        self._check_configuration_service(closed_ok=True)
        self._check_lifecycle_service(closed_ok=True)
        self._check_reception_service(closed_ok=True)
        if any(service is not None and service._lock.locked()
               for service in (self.status_service,self.configuration_service,self.lifecycle_service)):
            raise ICDError('STATE','cannot partially close installed model services during an operation')
        if self.lifecycle_service is not None:
            self.lifecycle_service.close()
        if self.configuration_service is not None:
            self.configuration_service.close()
        if self.status_service is not None:
            self.status_service.close()
        if self.reception_service is not None:
            self.reception_service.close()
        if not self._closing:
            self._closing = True
            self._shutdown = ShutdownResult(self.registry.session_ids, ())
        try:
            removed = self.registry.close()
        finally:
            self._shutdown = ShutdownResult(self._shutdown.closed_sessions,
                                            self.registry.shutdown_inputs,
                                            self.registry.resource_shutdown)
        self.assembler.clear()
        self._closed = True
        return removed

    def _header(self, mid, sid, transaction_id):
        if sid == 0:
            if self._zero_feedback_sequence == 0xffffffff:
                raise ICDError("CAPACITY", "zero-session feedback counter exhausted")
            self._zero_feedback_sequence += 1
            sequence = self._zero_feedback_sequence
        else:
            sequence = self.registry.next_feedback_sequence(sid)
        return {"session_id": sid, "sequence": sequence, "target_step": 0,
                "transaction_id": transaction_id, "valid_for_ms": self.contract.entry(mid)["valid_for_ms"]}

    def _ack(self, request_id, header, *, stage, error):
        reply = {"message_id": 130,
                 "header": self._header(130, int(header.session_id), int(header.transaction_id)),
                 "payload": {"request_sequence": int(header.sequence), "request_message_id": request_id,
                             "stage": stage, "error": error, "applied_step": 0,
                             "model_revision": 0, "probe_id": 0}}
        self.contract.validate_message(reply, direction="FROM_36")
        return reply

    def _opened(self, sid, transaction_id, *, receiver_step=0):
        capabilities = {
            "baseline_version": "HIL-ICD-1.0", "baseline_sha256": self.contract.baseline_sha256,
            "model_ids": self.registry.configured_model_ids,
            "implemented_message_ids": [1, 34] if self.resource_worker is not None and self.resource_worker.available else [1],
            "qualified_channels": [], "max_payload_bytes": 65536, "max_target_ahead_steps": 1000,
            "queue_capacity": 4096, "supported_codecs": [], "initialization_port_ready": False,
            "extended_environment_ready": False, "system_model_ready": False,
            "hex_motor_faults_ready": False, "phase_controller_ready": False,
            "replacement_ready": False, "available_probes": [],
        }
        if self.status_service is not None and self.status_service.supports(self.registry.identity(sid)['model_id']):
            capabilities['implemented_message_ids'].append(2)
            capabilities['implemented_message_ids'].sort()
            capabilities['available_probes']=['consumer.Status']
        if self.configuration_service is not None and self.configuration_service.supports(self.registry.identity(sid)['model_id']):
            capabilities['implemented_message_ids'].append(3)
            capabilities['implemented_message_ids'].sort()
            capabilities['available_probes'].append('consumer.RunConfigure')
        if self.lifecycle_service is not None and self.lifecycle_service.supports(self.registry.identity(sid)['model_id']):
            capabilities['implemented_message_ids'].append(4)
            capabilities['implemented_message_ids'].sort()
            capabilities['available_probes'].append('consumer.Lifecycle')
        if self.reception_service is not None:
            model=self.registry.identity(sid)['model_id']
            capabilities['implemented_message_ids']=sorted(set(capabilities['implemented_message_ids']) | {
                mid for mid in self.reception_service.message_ids if self.reception_service.supports(mid,model)})
        reply = {"message_id": 129, "header": self._header(129, sid, transaction_id),
                 "payload": {"session_id": sid, "lease_ms": 1000, "receiver_step": receiver_step,
                             "baseline_sha256": self.contract.baseline_sha256,
                             "accepted_roles": list(self.registry.roles(sid)), "capabilities": capabilities}}
        reply['header']['target_step']=receiver_step
        self.contract.validate_message(reply, direction="FROM_36")
        return reply

    def _check_status_service(self, *, closed_ok=False):
        if self.status_service is not self._status_service:
            raise ICDError('STATE', 'original receiver status service cannot be replaced')
        if self._status_service is not None:
            self._status_service._check(closed_ok=closed_ok)

    def _check_configuration_service(self, *, closed_ok=False):
        if self.configuration_service is not self._configuration_service:
            raise ICDError('STATE','original receiver configuration service cannot be replaced')
        if self._configuration_service is not None:
            self._configuration_service._check(closed_ok=closed_ok)

    def _check_lifecycle_service(self, *, closed_ok=False):
        if self.lifecycle_service is not self._lifecycle_service:
            raise ICDError('STATE','original receiver lifecycle service cannot be replaced')
        if self._lifecycle_service is not None:
            self._lifecycle_service._check(closed_ok=closed_ok)

    def _lifecycle_active(self):
        return self._lifecycle_service is not None and self._lifecycle_service._lock.locked()

    def _check_reception_service(self, *, closed_ok=False):
        if self.reception_service is not self._reception_service:
            raise ICDError('STATE','original reception service cannot be replaced')
        if self._reception_service is not None:
            self._reception_service._check(closed_ok=closed_ok)

    def _reception_handles(self, mid, sid):
        if self.reception_service is None or mid in (1,2):
            return False
        if (mid==3 and self.configuration_service is not None
                or mid==4 and self.lifecycle_service is not None
                or mid==34 and self.resource_worker is not None):
            return False
        return self.reception_service.supports(mid,self.registry.identity(sid)['model_id'])

    def _lifecycle_cleanup_owned(self):
        self._check_lifecycle_service()
        return self._lifecycle_service is not None and self._lifecycle_service._owns_local_cleanup()

    def receive(self, packet, binding, *, now_ns):
        if self._closed or self._run_busy or self._lifecycle_active():
            raise ICDError("STATE", "receiver is closed")
        self._check_status_service()
        self._check_configuration_service()
        self._check_lifecycle_service()
        self._check_reception_service()
        self.tick(now_ns=now_ns)
        if not self.registry.link_authorized(binding):
            raise ICDError("AUTHORIZATION", "unregistered actual peer; no decode or allocation")
        fragment = self.wire.decode(packet, binding.transport, direction="TO_36")
        self.registry.preauthorize(fragment.message_id, int(fragment.header.session_id), binding, now_ns=now_ns)
        try:
            complete = self.assembler.push(fragment, channel=binding.channel, direction="TO_36",
                                           authorized=True, now_ns=now_ns,
                                           pre_session_namespace=self.registry.open_namespace(binding)
                                           if fragment.message_id == 1 else None)
            if complete is None:
                return ()
            if (fragment.message_id == 1 and self.status_service is not None
                    and self.status_service.supports(complete.message['payload']['identity']['model_id'])):
                preview = self.registry.preview_open(complete.message, binding, now_ns=now_ns)
                if preview.replay is not None:
                    return preview.replay
                reply = self.status_service.open_response(complete.message, binding, now_ns=now_ns)
                self.registry.record_response(complete.message, (reply,),
                                              now_ns=self.status_service.last_observed_ns)
                self.admitted_count += 1
                return (reply,)
            if self._reception_handles(fragment.message_id,int(fragment.header.session_id)):
                self.reception_service.check_capacity(complete.message,binding,now_ns=now_ns)
            decision = self.registry.accept(complete.message, binding, now_ns=now_ns)
        except ICDError as error:
            self.note_error(error)
            return (self._ack(fragment.message_id, fragment.header, stage="FAILED", error=error.code),)
        if decision.replay is not None:
            return decision.replay
        self.admitted_count += 1
        if fragment.message_id == 1:
            replies = (self._opened(decision.session_id, int(fragment.header.transaction_id)),)
        elif fragment.message_id == 2 and self.status_service is not None:
            try:
                replies = (self.status_service.respond(complete.message, now_ns=now_ns),)
            except ICDError as error:
                self.note_error(error)
                completed = self.status_service.last_observed_ns
                if completed is not None:
                    self.registry.observe_admitted(complete.message, now_ns=max(now_ns, completed))
                replies = (self._ack(2, fragment.header, stage='RECEIVED', error='OK'),
                           self._ack(2, fragment.header, stage='FAILED', error=error.code))
            completed = self.status_service.last_observed_ns
            if completed is not None:
                now_ns = max(now_ns, completed)
        elif fragment.message_id == 3 and self.configuration_service is not None:
            received=self._ack(3,fragment.header,stage='RECEIVED',error='OK')
            try:
                return self.configuration_service.respond(complete.message,received,now_ns=now_ns)
            except ICDError as error:
                self.note_error(error)
                completed=self.configuration_service.last_observed_ns
                if completed is not None:
                    now_ns=max(now_ns,completed)
                    self.registry.observe_admitted(complete.message,now_ns=now_ns)
                replies=(received,self._ack(3,fragment.header,stage='FAILED',error=error.code))
        elif fragment.message_id == 4 and self.lifecycle_service is not None:
            received=self._ack(4,fragment.header,stage='RECEIVED',error='OK')
            try:
                return self.lifecycle_service.respond(complete.message,received,now_ns=now_ns)
            except ICDError as error:
                self.note_error(error)
                completed=self.lifecycle_service.last_observed_ns
                if completed is not None:
                    now_ns=max(now_ns,completed)
                replies=(received,self._ack(4,fragment.header,stage='FAILED',error=error.code))
        elif fragment.message_id == 34 and self.resource_worker is not None:
            received = self._ack(34, fragment.header, stage="RECEIVED", error="OK")
            try:
                self.resource_worker.submit(complete.message, binding, now_ns=now_ns,
                                            received_response=received)
                return (received,)
            except ICDError as error:
                self.note_error(error)
                replies = (received, self._ack(34, fragment.header, stage="FAILED", error=error.code))
        elif self._reception_handles(fragment.message_id,int(fragment.header.session_id)):
            self.reception_service.record(complete.message,binding,now_ns=now_ns)
            replies=(self._ack(fragment.message_id,fragment.header,stage='RECEIVED',error='OK'),
                     self._ack(fragment.message_id,fragment.header,stage='VALIDATED',error='OK'))
        else:
            missing = "TARGET_MISSING" if fragment.message_id == 2 or self.contract.entry(fragment.message_id)["application"] != "SERVICE_BOUNDARY" else "UNSUPPORTED"
            replies = (self._ack(fragment.message_id, fragment.header, stage="RECEIVED", error="OK"),
                       self._ack(fragment.message_id, fragment.header, stage="FAILED", error=missing))
        self.registry.record_response(complete.message, replies, now_ns=now_ns)
        return replies
