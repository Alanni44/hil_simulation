"""Bounded receiver-side sessions. Callers serialize access and supply real links."""

from collections import OrderedDict
import copy
from dataclasses import dataclass
import hashlib
import secrets

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


@dataclass(frozen=True, slots=True)
class PeerBinding:
    channel: str
    transport: str
    peer: str


@dataclass(frozen=True, slots=True)
class SourceGrant:
    identity: dict
    roles: tuple
    bindings: tuple


@dataclass(frozen=True, slots=True)
class Decision:
    session_id: int
    replay: tuple | None


@dataclass(frozen=True, slots=True)
class RegisteredController:
    session_id: int
    identity_json: bytes
    roles: tuple
    bindings: tuple
    nonce: str
    observed_ns: int
    deadline_ns: int
    last_rx_sequence: int

    @property
    def identity(self):
        return loads(self.identity_json)

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


@dataclass(slots=True)
class _Session:
    grant: int
    roles: tuple
    nonce: str
    deadline_ns: int
    last_rx: int = 1
    last_tx: int = 0


@dataclass(slots=True)
class _Record:
    digest: bytes
    deadline_ns: int
    received_ns: int
    responses: tuple | None = None
    queued: bool = False
    resource_deadline_ns: int | None = None


class SessionRegistry:
    def __init__(self, contract, grants, *, max_sessions=64):
        if type(max_sessions) is not int or not 1 <= max_sessions <= 64:
            raise ICDError("CAPACITY", "deployment session bound must be 1..64")
        self.contract = contract
        self._policy = contract.catalogue["policy"]
        self._max_sessions = max_sessions
        self._grants = copy.deepcopy(tuple(grants))
        if not 1 <= len(self._grants) <= 64:
            raise ICDError("CAPACITY", "explicit bounded source grants required")
        channels = {c["id"]: c["type"] for c in contract.catalogue["channels"]}
        self._links = {}
        identities = set()
        for index, grant in enumerate(self._grants):
            contract.validate_payload(1, {"identity": grant.identity, "roles": list(grant.roles),
                                         "baseline_sha256": contract.baseline_sha256,
                                         "nonce_hex": "0" * 32, "requested_lease_ms": 1000})
            identity = canonicalize(grant.identity)
            if identity in identities:
                raise ICDError("AUTHORIZATION", "one complete identity must own one grant with all its links")
            identities.add(identity)
            if not 1 <= len(grant.bindings) <= 8:
                raise ICDError("CAPACITY", "grant requires 1..8 explicit ingress bindings")
            for binding in grant.bindings:
                medium = "ETH" if binding.transport == "UDP" else "CANFD"
                if (binding.transport not in ("UDP", "CANFD") or channels.get(binding.channel) != medium
                        or type(binding.peer) is not str or not 1 <= len(binding.peer) <= 256
                        or binding in self._links):
                    raise ICDError("AUTHORIZATION", "invalid, duplicate or ambiguous ingress grant")
                self._links[binding] = index
        self._sessions = {}
        self._opens = OrderedDict()
        self._records = OrderedDict()
        self._next_id = secrets.randbelow(2**31) + 1
        self._last_now = -1
        self._model_queue = None
        self._resource_worker = None
        self._resource_shutdown = None
        self._shutdown_inputs = ()
        self._closed = False

    @property
    def active_count(self):
        return len(self._sessions)

    @property
    def session_ids(self):
        return tuple(self._sessions)

    @property
    def cache_count(self):
        return len(self._records)

    @property
    def configured_model_ids(self):
        return sorted({g.identity["model_id"] for g in self._grants})

    def _clock(self, now_ns):
        self.check_clock(now_ns)
        self._last_now = now_ns
        return now_ns

    def check_clock(self, now_ns):
        self._ensure_open()
        if type(now_ns) is not int or now_ns < 0 or now_ns < self._last_now:
            raise ICDError("SCHEMA", "nondecreasing receiver monotonic nanoseconds required")
        return now_ns

    def preview_maintenance(self, *, now_ns):
        self.check_clock(now_ns)
        expired = tuple(sid for sid, session in self._sessions.items() if now_ns >= session.deadline_ns)
        live = tuple(sid for sid in self._sessions if sid not in expired)
        rejected = self._model_queue.preview_expiry(live, now_ns=now_ns) if self._model_queue is not None else ()
        return expired, rejected

    def expire(self, *, now_ns):
        now = self._clock(now_ns)
        expired = [sid for sid, session in self._sessions.items() if now >= session.deadline_ns]
        for sid in expired:
            del self._sessions[sid]
            if self._resource_worker is not None:
                self._resource_worker.cancel_session(sid)
        for mapping in (self._records, self._opens):
            for key, value in list(mapping.items()):
                deadline = max(value.deadline_ns, value.resource_deadline_ns or 0) if isinstance(value, _Record) else value[2]
                if now >= deadline:
                    del mapping[key]
        return expired

    def revoke(self, session_id):
        self._ensure_open()
        self._sessions.pop(session_id, None)
        if self._resource_worker is not None and type(session_id) is int and 1 <= session_id <= 0xffffffff:
            self._resource_worker.cancel_session(session_id)

    def _ensure_open(self):
        if self._closed:
            raise ICDError("STATE", "session registry is permanently closed")

    def retire(self, session_id):
        self._ensure_open()
        if type(session_id) is not int or not 1 <= session_id <= 0xffffffff:
            raise ICDError("SCHEMA", "retirement requires a nonzero uint32 session")
        self.revoke(session_id)
        return self._model_queue.discard_session(session_id) if self._model_queue is not None else ()

    def expire_model_inputs(self, *, now_ns):
        self._clock(now_ns)
        if self._model_queue is not None:
            return self._model_queue.expire(now_ns=now_ns)
        self.expire(now_ns=now_ns)
        return ()

    def close(self):
        first = not self._closed
        if first:
            self._shutdown_inputs = self._model_queue.close() if self._model_queue is not None else ()
            self._sessions.clear()
            self._records.clear()
            self._opens.clear()
            self._closed = True
        if self._resource_worker is not None:
            self._resource_shutdown = self._resource_worker.close()
        return self._shutdown_inputs if first else ()

    @property
    def resource_shutdown(self):
        return self._resource_shutdown

    @property
    def shutdown_inputs(self):
        return self._shutdown_inputs

    def _attach_model_queue(self, queue):
        self._ensure_open()
        if self._model_queue is not None:
            raise ICDError("STATE", "one model queue lifetime per registry; replacing it would reset run history")
        self._model_queue = queue

    def _attach_resource_worker(self, worker):
        self._ensure_open()
        if self._resource_worker is not None:
            raise ICDError("STATE", "one resource worker lifetime per registry")
        self._resource_worker = worker

    def identity(self, session_id):
        return copy.deepcopy(self._grants[self._get(session_id).grant].identity)

    def roles(self, session_id):
        return self._get(session_id).roles

    def run_session_ids(self, origin_session_id, *, now_ns):
        """Serial-owner context selection, not renewal or lifecycle application."""
        if type(origin_session_id) is not int or not 1<=origin_session_id<=0xffffffff:
            raise ICDError('SCHEMA','original nonzero uint32 origin session required')
        if type(now_ns) is not int or not 0<=now_ns<=2**64-1:
            raise ICDError('SCHEMA','actual receiver uint64 observation time required')
        self.check_clock(now_ns)
        origin=self._get(origin_session_id)
        if now_ns>=origin.deadline_ns:
            raise ICDError('STALE_SESSION','origin session expired before run retirement')
        identity=self._grants[origin.grant].identity
        fields=('run_id','vehicle_id','scenario_id','model_id','definition_version')
        selected=tuple(sid for sid,session in self._sessions.items()
            if all(self._grants[session.grant].identity[key]==identity[key] for key in fields))
        self._clock(now_ns)
        return selected

    def registered_controller(self, identity, *, now_ns):
        """Resolve actual external registration under the receiver's serial owner.

        Reading advances the monotonic floor but never renews a lease, runs
        maintenance, or turns registration into applied control ownership.
        """
        self.contract.validate_payload(1, {'identity':identity,'roles':['CONTROLLER'],
            'baseline_sha256':self.contract.baseline_sha256,'nonce_hex':'0'*32,
            'requested_lease_ms':1000})
        now = self._clock(now_ns)
        index = next((i for i,g in enumerate(self._grants) if g.identity == identity),None)
        if index is None:
            raise ICDError('AUTHORIZATION', 'complete producer identity is not configured')
        if 'CONTROLLER' not in self._grants[index].roles:
            raise ICDError('AUTHORIZATION', 'configured producer has no CONTROLLER grant')
        live = [(sid,s) for sid,s in self._sessions.items()
                if s.grant == index and now < s.deadline_ns]
        controllers = [(sid,s) for sid,s in live if 'CONTROLLER' in s.roles]
        if not live:
            raise ICDError('STALE_SESSION', 'configured producer has no current live session')
        if not controllers:
            raise ICDError('AUTHORIZATION', 'actual producer session did not obtain CONTROLLER')
        if len(controllers) != 1:
            raise ICDError('CONTROL_OWNER', 'configured producer has ambiguous live controller sessions')
        sid, session = controllers[0]
        grant = self._grants[index]
        return RegisteredController(sid,canonicalize(grant.identity),session.roles,
            tuple(PeerBinding(b.channel,b.transport,b.peer) for b in grant.bindings),
            session.nonce,now,session.deadline_ns,session.last_rx)

    def _get(self, session_id):
        self._ensure_open()
        if session_id not in self._sessions:
            raise ICDError("STALE_SESSION", "session absent, revoked or expired")
        return self._sessions[session_id]

    def link_authorized(self, binding):
        return binding in self._links

    def open_namespace(self, binding):
        if binding not in self._links:
            raise ICDError("AUTHORIZATION", "pre-session namespace requires an actual authorized grant")
        return self._links[binding]

    def preauthorize(self, message_id, session_id, binding, *, now_ns):
        self.expire(now_ns=now_ns)
        if binding not in self._links:
            raise ICDError("AUTHORIZATION", "actual ingress peer is not registered")
        entry = self.contract.entry(message_id)
        if entry["direction"] != "TO_36" or binding.transport not in entry["transports"]:
            raise ICDError("AUTHORIZATION", "input direction/transport does not match grant")
        if message_id == 1:
            if session_id != 0:
                raise ICDError("STALE_SESSION", "SessionOpen must not name an existing session")
            return
        session = self._get(session_id)
        if session.grant != self._links[binding]:
            raise ICDError("AUTHORIZATION", "session identity cannot migrate to a foreign grant")
        if entry["role"] != "ANY_SESSION_ROLE" and entry["role"] not in session.roles:
            raise ICDError("AUTHORIZATION", "required message role is not granted")
        if self._grants[session.grant].identity["model_id"] not in entry["model_ids"]:
            raise ICDError("MODEL", "message does not apply to the session model")

    def _remember(self, key, digest, now):
        if len(self._records) >= self._policy["duplicate_cache_messages"]:
            oldest = next((k for k, value in self._records.items() if value.resource_deadline_ns is None), None)
            if oldest is None:
                raise ICDError("BUFFER_FULL", "pending resource feedback cannot be evicted")
            del self._records[oldest]
        self._records[key] = _Record(digest, now + self._policy["duplicate_retention_ms"] * 1_000_000, now)

    @staticmethod
    def _replay(record):
        if record.responses is None:
            raise ICDError("STATE", "accepted request has no completed real feedback yet")
        return copy.deepcopy(record.responses)

    def accept(self, message, binding, *, now_ns):
        self.contract.validate_message(message, direction="TO_36")
        header = message["header"]
        sid, sequence = int(header["session_id"]), int(header["sequence"])
        self.preauthorize(message["message_id"], sid, binding, now_ns=now_ns)
        digest = hashlib.sha256(canonicalize(message)).digest()
        if message["message_id"] == 1:
            return self._opening(message, binding, now_ns, digest, allocate=True)
        session = self._get(sid)
        key = (sid, sequence)
        previous = self._records.get(key)
        if previous:
            if digest != previous.digest:
                raise ICDError("DUPLICATE", "same session sequence has different logical content")
            return Decision(sid, self._replay(previous))
        if sequence <= session.last_rx:
            raise ICDError("OUT_OF_ORDER", "sequence is not fresh; cache eviction never resets freshness")
        self._remember(key, digest, now_ns)
        session.last_rx = sequence
        if message["message_id"] == 2:
            session.deadline_ns = now_ns + self._policy["session_lease_ms"] * 1_000_000
        return Decision(sid, None)

    def preview_open(self, message, binding, *, now_ns):
        self.contract.validate_message(message, direction="TO_36")
        if message['message_id'] != 1:
            raise ICDError('UNSUPPORTED', 'only original SessionOpen may be previewed')
        self.preauthorize(1, int(message['header']['session_id']), binding, now_ns=now_ns)
        digest = hashlib.sha256(canonicalize(message)).digest()
        return self._opening(message, binding, now_ns, digest, allocate=False)

    def _opening(self, message, binding, now_ns, digest, *, allocate):
        grant_index = self._links[binding]
        payload = message["payload"]
        grant = self._grants[grant_index]
        if payload["identity"] != grant.identity or not set(payload["roles"]) <= set(grant.roles):
            raise ICDError("AUTHORIZATION", "complete identity/roles differ from deployment grant")
        open_key = (grant_index, payload["nonce_hex"])
        previous = self._opens.get(open_key)
        if previous:
            old_digest, old_sid, _ = previous
            if digest != old_digest:
                raise ICDError("DUPLICATE", "nonce reused for a different open request")
            self._get(old_sid)
            record = self._records.get((old_sid, 1))
            if record is None:
                raise ICDError("OUT_OF_ORDER", "open response has left the retry cache")
            return Decision(old_sid, self._replay(record))
        if any(s.grant == grant_index and s.nonce == payload["nonce_hex"] for s in self._sessions.values()):
            raise ICDError("DUPLICATE", "active session nonce cannot create a second session")
        if len(self._sessions) >= self._max_sessions:
            raise ICDError("BUFFER_FULL", "live session capacity reached")
        if self._next_id > 0xffffffff:
            raise ICDError("CAPACITY", "session counter exhausted; wrap is forbidden")
        if (len(self._records) >= self._policy["duplicate_cache_messages"]
                and all(record.resource_deadline_ns is not None for record in self._records.values())):
            raise ICDError("BUFFER_FULL", "pending resource feedback cannot be evicted for an opening")
        if not allocate:
            return Decision(0, None)
        sid = self._next_id
        self._next_id += 1
        self._sessions[sid] = _Session(grant_index, tuple(payload["roles"]), payload["nonce_hex"],
                                       now_ns + self._policy["session_lease_ms"] * 1_000_000)
        self._opens[open_key] = (digest, sid, now_ns + self._policy["duplicate_retention_ms"] * 1_000_000)
        while len(self._opens) > self._policy["duplicate_cache_messages"]:
            self._opens.popitem(last=False)
        self._remember((sid, 1), digest, now_ns)
        return Decision(sid, None)

    def next_feedback_sequence(self, session_id):
        session = self._get(session_id)
        if session.last_tx == 0xffffffff:
            raise ICDError("CAPACITY", "feedback sequence exhausted; wrap is forbidden")
        session.last_tx += 1
        return session.last_tx

    def require_admitted(self, message, *, now_ns):
        self.contract.validate_message(message, direction="TO_36")
        self.expire(now_ns=now_ns)
        return self._admitted_record(message).received_ns

    def observe_admitted(self, message, *, now_ns):
        """Check original live admission without maintenance or queue claims."""
        self.contract.validate_message(message, direction="TO_36")
        now = self._clock(now_ns)
        session = self._get(int(message['header']['session_id']))
        if now >= session.deadline_ns:
            raise ICDError('STALE_SESSION', 'original selector session expired')
        record = self._admitted_record(message)
        if now >= max(record.deadline_ns,record.resource_deadline_ns or 0):
            raise ICDError('OUT_OF_ORDER', 'original admission observation expired')
        return record.received_ns

    def _admitted_record(self, message):
        sid = int(message["header"]["session_id"])
        self._get(sid)
        record = self._records.get((sid, int(message["header"]["sequence"])))
        if record is None:
            raise ICDError("OUT_OF_ORDER", "original session admission is absent or evicted")
        if record.digest != hashlib.sha256(canonicalize(message)).digest():
            raise ICDError("DUPLICATE", "queue content differs from the original admission")
        if record.queued:
            raise ICDError("DUPLICATE", "original admission already entered a queue")
        if record.responses and any(
                r["message_id"] == 130 and r["payload"]["stage"] in ("FAILED", "APPLIED", "CONSUMED")
                for r in record.responses):
            raise ICDError("STATE", "terminal request cannot subsequently enter a queue")
        return record

    def claim_admitted(self, message, *, now_ns):
        received_ns = self.require_admitted(message, now_ns=now_ns)
        key = (int(message["header"]["session_id"]), int(message["header"]["sequence"]))
        self._records[key].queued = True
        return received_ns

    def record_response(self, message, responses, *, now_ns):
        self.expire(now_ns=now_ns)
        sid = int(message["header"]["session_id"])
        if message["message_id"] == 1:
            matches = [value[1] for value in self._opens.values()
                       if value[0] == hashlib.sha256(canonicalize(message)).digest()]
            if not matches:
                raise ICDError("STATE", "open request was not admitted")
            sid = matches[0]
        record = self._records.get((sid, int(message["header"]["sequence"])))
        if record is None or record.digest != hashlib.sha256(canonicalize(message)).digest():
            raise ICDError("STATE", "only original admitted content can acquire feedback")
        responses = tuple(copy.deepcopy(responses))
        if not 1 <= len(responses) <= 3 or sum(len(canonicalize(r)) for r in responses) > 4096:
            raise ICDError("CAPACITY", "retry feedback exceeds bounded record storage")
        for reply in responses:
            self.contract.validate_message(reply, direction="FROM_36")
            if (reply["header"]["session_id"] != sid
                    or reply["header"]["transaction_id"] != message["header"]["transaction_id"]):
                raise ICDError("STATE", "feedback does not identify the admitted session/transaction")
            if reply["message_id"] == 130:
                payload = reply["payload"]
                if (payload["stage"] in ("APPLIED", "CONSUMED") or payload["probe_id"] != 0
                        or payload["request_sequence"] != message["header"]["sequence"]
                        or payload["request_message_id"] != message["message_id"]):
                    raise ICDError("STATE", "session layer cannot mint application/consumer evidence")
            elif reply["message_id"] == 141:
                self.contract.validate_resource_feedback(message, reply)
        if record.responses is not None:
            raise ICDError("STATE", "terminal feedback is immutable")
        record.responses = responses

    def _record_configuration_response(self, message, responses, service, *, now_ns):
        from .configuration_service import ModelConfigurationService
        if (type(service) is not ModelConfigurationService or service.registry is not self
                or service.contract is not self.contract
                or not service._owns_completed_reply(message,responses,now_ns)):
            raise ICDError('STATE','only the actual original configuration consumer may complete its receipt')
        self.observe_admitted(message,now_ns=now_ns)
        record=self._admitted_record(message)
        if message['message_id']!=3 or record.responses is not None or type(responses) is not tuple or len(responses)!=2:
            raise ICDError('STATE','original unapplied configuration admission required')
        for reply in responses:
            self.contract.validate_message(reply,direction='FROM_36')
            if (reply['message_id']!=130 or reply['header']['session_id']!=message['header']['session_id']
                    or reply['header']['transaction_id']!=message['header']['transaction_id']
                    or reply['payload']['request_sequence']!=message['header']['sequence']
                    or reply['payload']['request_message_id']!=3 or reply['payload']['error']!='OK'):
                raise ICDError('STATE','original configuration feedback correlation required')
        probe=next(p['id'] for p in self.contract.catalogue['probe_catalog'] if p['name']=='consumer.RunConfigure')
        if (responses[0]['payload']['stage']!='RECEIVED' or responses[0]['payload']['probe_id']!=0
                or responses[1]['payload']['stage']!='APPLIED' or responses[1]['payload']['probe_id']!=probe
                or sum(len(canonicalize(r)) for r in responses)>4096):
            raise ICDError('STATE','actual original configuration completion pair required')
        record.responses=copy.deepcopy(responses)
        record.deadline_ns=now_ns+self._policy['duplicate_retention_ms']*1000000

    def _record_lifecycle_response(self,message,responses,service,*,now_ns):
        from .lifecycle_service import ModelLifecycleService
        if (type(service) is not ModelLifecycleService or service.registry is not self
                or service.contract is not self.contract or not service._owns_completed_reply(message,responses,now_ns)):
            raise ICDError('STATE','only the actual original lifecycle operation may complete its reply')
        self.check_clock(now_ns)
        key=(message['header']['session_id'],message['header']['sequence'])
        record=self._records.get(key)
        if (message['message_id']!=4 or record is None or record is not service._completion[3]
                or record.digest!=hashlib.sha256(canonicalize(message)).digest() or record.responses is not None
                or type(responses) is not tuple or len(responses)!=2):
            raise ICDError('STATE','original retained lifecycle admission required')
        for reply in responses:
            self.contract.validate_message(reply,direction='FROM_36')
            if (reply['message_id']!=130 or reply['header']['session_id']!=key[0]
                    or reply['header']['transaction_id']!=message['header']['transaction_id']
                    or reply['payload']['request_sequence']!=key[1] or reply['payload']['request_message_id']!=4):
                raise ICDError('STATE','original lifecycle response correlation required')
        first,last=responses[0]['payload'],responses[1]['payload']
        if (first['stage']!='RECEIVED' or first['error']!='OK' or first['probe_id']!=0
                or last['stage'] not in ('APPLIED','FAILED')
                or last['stage']=='APPLIED' and (last['error']!='OK' or last['probe_id']!=1004)
                or last['stage']=='FAILED' and (last['error']=='OK' or last['probe_id']!=0)
                or sum(len(canonicalize(r)) for r in responses)>4096):
            raise ICDError('STATE','original actual lifecycle completion pair required')
        self._clock(now_ns)
        record.responses=copy.deepcopy(responses)
        record.deadline_ns=now_ns+self._policy['duplicate_retention_ms']*1000000

    def _resource_record(self, message, now_ns):
        self.contract.validate_message(message, direction="TO_36")
        if message["message_id"] != 34:
            raise ICDError("STATE", "only ResourceChunk may extend storage feedback")
        self.expire(now_ns=now_ns)
        sid = int(message["header"]["session_id"])
        self._get(sid)
        record = self._records.get((sid, int(message["header"]["sequence"])))
        if record is None or record.digest != hashlib.sha256(canonicalize(message)).digest():
            raise ICDError("STATE", "resource feedback requires original admission")
        return record

    def defer_resource_response(self, message, responses, *, now_ns):
        record = self._resource_record(message, now_ns)
        if type(responses) not in (tuple, list):
            raise ICDError("SCHEMA", "bounded deferred feedback collection required")
        responses = tuple(responses)
        for reply in responses:
            self.contract.validate_message(reply, direction="FROM_36")
        if (not record.queued or record.responses is not None or len(responses) != 1
                or responses[0].get("message_id") != 130
                or responses[0].get("payload", {}).get("stage") != "RECEIVED"
                or responses[0].get("payload", {}).get("error") != "OK"):
            raise ICDError("STATE", "only claimed resource RECEIVED feedback can be deferred")
        if sum(value.resource_deadline_ns is not None for value in self._records.values()) >= 64:
            raise ICDError("BUFFER_FULL", "pending resource feedback capacity is64")
        timeout = (self._policy["resource_commit_timeout_ms"] if message["payload"]["final"]
                   else message["header"]["valid_for_ms"])
        deadline = record.received_ns + timeout * 1_000_000
        if now_ns >= deadline:
            raise ICDError("EXPIRED", "resource request cannot start a new deferred stage after validity")
        self.record_response(message, responses, now_ns=now_ns)
        record.resource_deadline_ns = deadline

    def check_resource_deferral(self, message, response, *, now_ns):
        record = self._resource_record(message, now_ns)
        self.require_admitted(message, now_ns=now_ns)
        self.contract.validate_message(response, direction="FROM_36")
        payload = response["payload"]
        if (response["message_id"] != 130 or payload["stage"] != "RECEIVED" or payload["error"] != "OK"
                or payload["probe_id"] != 0 or payload["request_message_id"] != 34
                or payload["request_sequence"] != message["header"]["sequence"]
                or response["header"]["session_id"] != message["header"]["session_id"]
                or response["header"]["transaction_id"] != message["header"]["transaction_id"]
                or record.responses is not None):
            raise ICDError("STATE", "resource deferral needs its original RECEIVED prefix")
        if sum(value.resource_deadline_ns is not None for value in self._records.values()) >= 64:
            raise ICDError("BUFFER_FULL", "pending resource feedback capacity is64")
        timeout = self._policy["resource_commit_timeout_ms"] if message["payload"]["final"] else message["header"]["valid_for_ms"]
        if now_ns >= record.received_ns + timeout * 1_000_000:
            raise ICDError("EXPIRED", "resource deferral is beyond its original deadline")

    def finish_resource_response(self, message, reply, *, now_ns):
        record = self._resource_record(message, now_ns)
        if record.resource_deadline_ns is None:
            raise ICDError("STATE", "only original pending storage feedback can acquire a terminal result")
        self.contract.validate_resource_feedback(message, reply)
        if now_ns >= record.resource_deadline_ns and reply["payload"]["error"] == "OK":
            raise ICDError("TIMEOUT", "resource completion exceeded the original deadline")
        record.responses = record.responses + (copy.deepcopy(reply),)
        record.resource_deadline_ns = None
        record.deadline_ns = now_ns + self._policy["duplicate_retention_ms"] * 1_000_000
