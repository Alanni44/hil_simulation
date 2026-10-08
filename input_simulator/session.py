"""Source-side actual grant and serial allocation, not model readiness or reset."""

from contextlib import contextmanager
import copy
from dataclasses import asdict, dataclass
import json
import secrets
import threading
import time

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import Header, WireCodec
from .model_clock import _remember_feedback, _remember_control_feedback


MAX_COUNTER = 0xffffffff
MAX_REPLY_BYTES = 65536 + 1024


def _snapshot_message(value):
    # Internal evidence only, not the RFC8785 wire encoder. Preserve packed
    # float signs and original number types after contract validation.
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')


@dataclass(frozen=True, slots=True)
class SourceExchange:
    request_json: bytes
    reply_json: bytes | None
    started_ns: int
    completed_ns: int | None
    error: str | None

    @property
    def request(self):
        return loads(self.request_json)

    @property
    def reply(self):
        return None if self.reply_json is None else loads(self.reply_json)


@dataclass(frozen=True, slots=True)
class PreparedSourceInput:
    message_json: bytes
    input_json: bytes
    transport: str
    frames: tuple
    allocated_ns: int
    baseline_sha256: str

    @property
    def message(self):
        return loads(self.input_json)

    @property
    def execution_ready(self):
        return False


class SourceSession:
    def __init__(self, transport, identity, roles, *, clock=time.monotonic_ns,
                 max_records=64, max_record_bytes=4 * 1024 * 1024):
        if (type(max_records) is not int or not 1 <= max_records <= 4096
                or type(max_record_bytes) is not int or not 1 <= max_record_bytes <= 64 * 1024 * 1024):
            raise ICDError("CAPACITY", "bounded source exchange count/byte capacities required")
        if (not isinstance(getattr(transport, "contract", None), Contract)
                or not transport.contract.component_hashes or not callable(getattr(transport, "request", None))
                or not callable(getattr(transport, "claim_session_owner", None))
                or getattr(transport, "channel", None) not in {f"ETH_{i}" for i in range(4)} or not callable(clock)):
            raise ICDError("STATE", "verified contract and standard Ethernet request transport required")
        if type(roles) is not tuple:
            raise ICDError("SCHEMA", "immutable explicit role tuple required")
        self.contract = transport.contract
        self._identity_json = canonicalize(identity)
        self._roles_requested = roles
        self._lease_ms = self.contract.catalogue["policy"]["session_lease_ms"]
        self.contract.validate_payload(1, self._opening_payload("0" * 32))
        self.transport = transport
        self._clock = clock
        self._lock = threading.Lock()
        self._operation_thread = None
        self._last_now = -1
        self._closed = False
        self._closed_sid = None
        self._state = "NEW"
        self._sid = None
        self._roles = ()
        self._capabilities_json = None
        self._deadline_ns = 0
        self._seen_sessions = set()
        self._next_sequence = 2
        self._last_allocation = None
        self._next_transaction = 1
        self._last_rx_sequence = 0
        self._model_status = None
        self._model_step_floor = -1
        self._model_status_request_sequence = 0
        self._model_status_transaction = -1
        self._model_clock_retired = False
        self._model_epoch_retirement = None
        self._control_lease = None
        self._control_boundary_sequence = 0
        self._control_requested_source = None
        self._status_assertion_reader = None
        self._can_attempt_sid, self._can_attempt_sequence = None, 0
        self._can_heartbeat_sid, self._can_heartbeat_transaction = None, -1
        self._heartbeat_attempt_sid, self._heartbeat_attempt_transaction = None, -1
        self._first_attempt_sid, self._first_attempt_sequence = None, 0
        self._native_tool_coordinator = None
        self._records = []
        self._record_bytes = 0
        self._inputs = {}
        self._runtime_target_scope = None
        self._runtime_target_lock = threading.Lock()
        self._runtime_target_guards = {}
        self._input_bytes = 0
        self._max_records = max_records
        self._max_record_bytes = max_record_bytes
        self._dispatcher = None
        self._observation_recorder = None
        floor = transport.claim_session_owner(self)
        if type(floor) is not int or not 1 <= floor <= MAX_COUNTER + 1:
            raise ICDError("STATE", "transport must preserve its lifetime transaction floor")
        self._next_transaction = floor

    def _opening_payload(self, nonce):
        return {"identity": loads(self._identity_json), "roles": list(self._roles_requested),
                "baseline_sha256": self.contract.baseline_sha256, "nonce_hex": nonce,
                "requested_lease_ms": self._lease_ms}

    @contextmanager
    def _operation(self, *, owner=None, closed_ok=False):
        if not self._lock.acquire(blocking=False):
            raise ICDError("STATE", "source session operations must be serialized by their owner")
        try:
            if self._closed and not closed_ok:
                raise ICDError("STATE", "source session manager is permanently closed")
            coordinator = self._native_tool_coordinator
            if coordinator is not None and owner is not coordinator.dispatcher:
                raise ICDError('STATE', 'attached native coordinator retains its original source owner')
            if self._dispatcher is not None and owner is not self._dispatcher:
                raise ICDError("STATE", "attached dispatcher exclusively owns source operations")
            self._operation_thread = threading.get_ident()
            yield
        finally:
            self._operation_thread = None
            self._lock.release()

    def _now(self):
        now = self._clock()
        if type(now) is not int or not 0 <= now <= 0xffffffffffffffff or now < self._last_now:
            raise ICDError("SCHEMA", "source local monotonic uint64 clock must not reverse")
        self._last_now = now
        return now

    @property
    def session_id(self):
        return self._sid

    @property
    def roles(self):
        return self._roles

    @property
    def capabilities(self):
        return None if self._capabilities_json is None else loads(self._capabilities_json)

    @property
    def last_rx_sequence(self):
        return self._last_rx_sequence

    @property
    def records(self):
        return tuple(self._records)

    def _record_capacity(self, value):
        raw = canonicalize(value)
        if (len(self._records) + len(self._inputs) >= self._max_records
                or self._record_bytes + self._input_bytes + len(raw) + MAX_REPLY_BYTES > self._max_record_bytes):
            raise ICDError("BUFFER_FULL", "drain source exchange records before another network request")
        return raw

    def _check_grant(self, request, reply, started, completed):
        payload = reply["payload"]
        if payload["session_id"] != reply["header"]["session_id"] or payload["session_id"] in self._seen_sessions:
            raise ICDError("STALE_SESSION", "grant SID differs from its header or was already used")
        cap = payload["capabilities"]
        if cap["baseline_sha256"] != self.contract.baseline_sha256:
            raise ICDError("HASH", "nested capabilities baseline differs from verified ICD")
        accepted = payload["accepted_roles"]
        if len(set(accepted)) != len(accepted) or not set(accepted) <= set(request["payload"]["roles"]):
            raise ICDError("AUTHORIZATION", "grant accepted roles are duplicate or exceed the request")
        if request["payload"]["identity"]["model_id"] not in cap["model_ids"]:
            raise ICDError("MODEL", "granted receiver has no selected model")
        for mid in cap["implemented_message_ids"]:
            self.contract.entry(mid)
        if completed >= started + payload["lease_ms"] * 1_000_000:
            raise ICDError("STALE_SESSION", "delayed grant is beyond the conservative original lease")

    def _check_reply(self, request, reply, started, completed):
        model_id = loads(self._identity_json)["model_id"]
        self.contract.validate_message(reply, direction="FROM_36", model_id=model_id)
        sent, received = request["header"], reply["header"]
        if (received["transaction_id"] != sent["transaction_id"]
                or request["message_id"] != 1 and received["session_id"] != sent["session_id"]):
            raise ICDError("STATE", "actual exchange reply differs from original SID/transaction")
        mid = reply["message_id"]
        if mid == 130:
            p = reply["payload"]
            if p["request_sequence"] != sent["sequence"] or p["request_message_id"] != request["message_id"]:
                raise ICDError("STATE", "actual ACK identifies another original request")
            if request["message_id"] == 1:
                raise ICDError(p["error"] if p["stage"] == "FAILED" else "STATE", "receiver did not grant the opening request")
        elif mid == 129 and request["message_id"] == 1:
            self._check_grant(request, reply, started, completed)
        elif mid == 131 and request["message_id"] == 2:
            pass
        elif mid == 142 and request["message_id"] == 33:
            if reply["payload"]["nonce"] != request["payload"]["nonce"]:
                raise ICDError("STATE", "measurement response nonce differs from original request")
        elif mid == 141:
            self.contract.validate_resource_feedback(request, reply)
        else:
            raise ICDError("STATE", "feedback is not defined for this serial request exchange")

    def _exchange(self, value):
        raw = self._record_capacity(value)
        started = self._now()
        completed, reply_raw, error = None, None, None
        try:
            self._check_first_attempt(value)
            self._claim_heartbeat_attempt(value)
            self._claim_first_attempt(value)
            reply = self.transport.request(value, owner=self)
            reply_raw = canonicalize(reply)
            if len(reply_raw) > MAX_REPLY_BYTES:
                reply_raw = None
                raise ICDError("CAPACITY", "actual feedback exceeds source record byte reservation")
            reply = loads(reply_raw)
            completed = self._now()
            self._check_reply(value, reply, started, completed)
            if reply["message_id"] == 130 and reply["payload"]["stage"] == "FAILED":
                error = reply["payload"]["error"]
            self._remember_model_feedback(value, reply, started, completed, transport='UDP',
                                          channel=self.transport.channel,
                                          fresh=reply['header']['sequence'] > self._last_rx_sequence)
            self._last_rx_sequence = max(self._last_rx_sequence, reply["header"]["sequence"])
            return reply
        except ICDError as exc:
            error = exc.code
            raise
        except OSError as exc:
            error = "STATE"
            raise ICDError("STATE", "actual source transport exchange failed") from exc
        finally:
            if completed is None:
                try:
                    completed = self._now()
                except ICDError:
                    error = "SCHEMA"
            record = SourceExchange(raw, reply_raw, started, completed, error)
            self._records.append(record)
            self._record_bytes += len(raw) + (0 if reply_raw is None else len(reply_raw))

    def open(self):
        with self._operation():
            if self._state not in ("NEW", "ABANDONED"):
                raise ICDError("STATE", "explicit local abandon is required before opening another session")
            if len(self._seen_sessions) >= 10000 or self._next_transaction > MAX_COUNTER:
                raise ICDError("CAPACITY", "source run SID/transaction history exhausted; wrap is forbidden")
            value = {"message_id": 1,
                     "header": {"session_id": 0, "sequence": 1, "target_step": 0,
                                "transaction_id": self._next_transaction, "valid_for_ms": 1000},
                     "payload": self._opening_payload(secrets.token_hex(16))}
            self.contract.validate_message(value, direction="TO_36")
            self._record_capacity(value)
            self._now()
            self._next_transaction += 1
            self._state = "OPENING"
            try:
                reply = self._exchange(value)
            except (ICDError, OSError):
                self._state = "FAILED"
                raise
            self._sid = reply["payload"]["session_id"]
            self._seen_sessions.add(self._sid)
            self._roles = tuple(reply["payload"]["accepted_roles"])
            self._capabilities_json = canonicalize(reply["payload"]["capabilities"])
            self._deadline_ns = self._records[-1].started_ns + reply["payload"]["lease_ms"] * 1_000_000
            self._next_sequence = 2
            self._state = "LIVE"
            return reply

    def _preview_header(self, mid, target_step, transaction_id):
        now = self._now()
        if self._sid is None or self._state != "LIVE" or now >= self._deadline_ns:
            raise ICDError("STALE_SESSION", "actual source grant absent or conservatively expired")
        entry = self.contract.entry(mid)
        if mid == 1:
            raise ICDError("STATE", "opening requests cannot be allocated inside a live session")
        if entry["direction"] != "TO_36":
            raise ICDError("AUTHORIZATION", "feedback cannot be allocated as source input")
        if loads(self._identity_json)["model_id"] not in entry["model_ids"]:
            raise ICDError("MODEL", "input belongs to another model")
        if entry["role"] != "ANY_SESSION_ROLE" and entry["role"] not in self._roles:
            raise ICDError("AUTHORIZATION", "actual grant lacks the required input role")
        if mid not in self.capabilities["implemented_message_ids"]:
            raise ICDError("TARGET_MISSING", "receiver did not publish this message implementation")
        if type(target_step) is not int or not 0 <= target_step <= MAX_COUNTER:
            raise ICDError("SCHEMA", "explicit uint32 target step required; no wall-clock model-step substitution")
        if transaction_id is not None and (type(transaction_id) is not int or not 0 <= transaction_id <= MAX_COUNTER):
            raise ICDError("SCHEMA", "explicit transaction must be uint32")
        transaction = self._next_transaction if transaction_id is None else transaction_id
        if self._next_sequence > MAX_COUNTER or transaction > MAX_COUNTER:
            raise ICDError("CAPACITY", "source counter exhausted; wrap is forbidden")
        header = Header(self._sid, self._next_sequence, target_step, transaction, entry["valid_for_ms"])
        self.contract.validate_header(mid, asdict(header))
        return header

    def _commit_header(self, header, message_id, stimulus=None):
        if self._runtime_target_scope is not None:
            from .runtime_targets import RuntimeTargetGuard
            thread,guard=self._runtime_target_scope
            if thread!=threading.get_ident() or type(guard) is not RuntimeTargetGuard:
                raise ICDError('STATE','original runtime allocation owner required')
            if stimulus is None:
                raise ICDError('STATE','actual original stimulus required for approved allocation')
            guard.check(self,message_id,asdict(header),self._now(),stimulus=stimulus)
            if len(self._runtime_target_guards)>=4096:
                raise ICDError('BUFFER_FULL','retain bounded original runtime approvals before allocation')
            self._runtime_target_guards[header.sequence]=guard
        self._last_allocation = (message_id, header)
        self._next_sequence += 1
        self._next_transaction = max(self._next_transaction, header.transaction_id + 1)

    def _header(self, mid, target_step, transaction_id):
        header = self._preview_header(mid, target_step, transaction_id)
        self._commit_header(header, mid)
        return header

    def allocate_header(self, message_id, target_step, transaction_id=None):
        with self._operation():
            return self._header(message_id, target_step, transaction_id)

    @property
    def prepared_inputs(self):
        return tuple(item for item, _ in self._inputs.values())

    def _prepare_input(self, stimulus, transport, target_step, transaction_id):
        stimulus = copy.deepcopy(stimulus)
        if type(stimulus) is not dict:
            raise ICDError('SCHEMA', 'input Stimulus object required')
        if type(stimulus.get('message_id')) is int and stimulus['message_id'] == 1:
            raise ICDError('STATE', 'opening requests cannot be prepared inside a live session')
        self.contract.validate_stimulus(stimulus, model_id=loads(self._identity_json)['model_id'])
        if type(transport) is not str or transport not in ('CANFD', 'UDP'):
            raise ICDError('UNSUPPORTED', 'formal CANFD or UDP input group required')
        header = self._preview_header(stimulus['message_id'], target_step, transaction_id)
        value = {**stimulus, 'header': asdict(header)}
        raw = canonicalize(value)
        snapshot = _snapshot_message(value)
        frames = tuple(WireCodec(self.contract).encode(value, transport))
        size = len(raw) + len(snapshot) + sum(len(f.data if transport == 'CANFD' else f) for f in frames) + 512
        if (len(self._records) + len(self._inputs) >= self._max_records
                or self._record_bytes + self._input_bytes + size > self._max_record_bytes):
            raise ICDError('BUFFER_FULL', 'drain or discard bounded source evidence before preparing another input')
        now = self._now()
        if now >= self._deadline_ns:
            raise ICDError('STALE_SESSION', 'grant expired during input encoding; counters not consumed')
        item = PreparedSourceInput(raw, snapshot, transport, frames, now, self.contract.baseline_sha256)
        self._commit_header(header, stimulus['message_id'],stimulus)
        self._inputs[id(item)] = (item, size)
        self._input_bytes += size
        return item

    def prepare_input(self, stimulus, transport, *, target_step, transaction_id=None):
        with self._operation():
            return self._prepare_input(stimulus, transport, target_step, transaction_id)

    def _owned_input(self, item):
        if type(item) is not PreparedSourceInput:
            raise ICDError('STATE', 'actual owned prepared input required')
        key = id(item)
        if key not in self._inputs or self._inputs[key][0] is not item:
            raise ICDError('STATE', 'prepared input is forged, foreign or discarded')
        return key

    def _verify_input(self, item):
        self._owned_input(item)
        now = self._now()
        if (self._state != 'LIVE' or self._sid != item.message['header']['session_id']
                or now >= self._deadline_ns):
            raise ICDError('STALE_SESSION', 'prepared input no longer belongs to a live current grant')
        value=item.message
        self._check_target_guard(value['message_id'],value['header'],stimulus=value)
        return item

    def _check_target_guard(self, message_id, header, *, stimulus=None, packet=None):
        guard=self._runtime_target_guards.get(header['sequence'])
        if guard is not None:
            if self._operation_thread!=threading.get_ident():
                raise ICDError('STATE','runtime fragment check requires actual source owner')
            guard.check(self,message_id,header,self._now(),stimulus=stimulus,packet=packet)

    def verify_input(self, item):
        with self._operation():
            return self._verify_input(item)

    def _claim_can_attempt(self, item):
        if self._operation_thread != threading.get_ident():
            raise ICDError('STATE', 'original CAN attempt requires the actual source operation owner')
        self._owned_input(item)
        value = item.message
        header = value['header']
        if item.transport != 'CANFD' or header['session_id'] != self._sid or self._state != 'LIVE':
            raise ICDError('STATE', 'actual current original CAN source input required')
        if (header['session_id'] == self._can_attempt_sid
                and header['sequence'] <= self._can_attempt_sequence):
            raise ICDError('STATE', 'original CAN input already attempted or behind source transmitted order')
        heartbeat = value['message_id'] == 2
        if (heartbeat and header['session_id'] == self._can_heartbeat_sid
                and header['transaction_id'] <= self._can_heartbeat_transaction):
            raise ICDError('STATE', 'CAN Status cannot distinguish a reused Heartbeat transaction')
        self._check_first_attempt(value)
        self._claim_heartbeat_attempt(value)
        self._claim_first_attempt(value)
        self._can_attempt_sid, self._can_attempt_sequence = header['session_id'], header['sequence']
        if heartbeat:
            self._can_heartbeat_sid, self._can_heartbeat_transaction = header['session_id'], header['transaction_id']

    def _claim_heartbeat_attempt(self, value):
        if self._operation_thread != threading.get_ident():
            raise ICDError('STATE', 'Heartbeat attempt requires the actual source operation owner')
        if value['message_id'] != 2:
            return
        header = value['header']
        if self._state != 'LIVE' or header['session_id'] != self._sid:
            raise ICDError('STALE_SESSION', 'Heartbeat attempt belongs to another grant')
        self._check_heartbeat_transaction(2, header['transaction_id'])
        self._heartbeat_attempt_sid = self._sid
        self._heartbeat_attempt_transaction = header['transaction_id']

    def _check_heartbeat_transaction(self, mid, transaction):
        if (mid == 2 and self._sid == self._heartbeat_attempt_sid
                and transaction <= self._heartbeat_attempt_transaction):
            raise ICDError('STATE', 'Status cannot distinguish a previously attempted Heartbeat transaction')

    def _check_first_attempt(self, value, *, already_claimed=False):
        if self._operation_thread != threading.get_ident():
            raise ICDError('STATE', 'first original TX attempt requires actual source operation owner')
        if value['message_id'] == 1:
            return
        header = value['header']
        self._check_target_guard(value['message_id'],header,stimulus=value)
        if self._state != 'LIVE' or header['session_id'] != self._sid:
            raise ICDError('STALE_SESSION', 'original first TX attempt belongs to another grant')
        if header['session_id'] == self._first_attempt_sid:
            sequence = header['sequence']
            if sequence < self._first_attempt_sequence or sequence == self._first_attempt_sequence and not already_claimed:
                raise ICDError('STATE', 'first original TX sequence is behind another source link attempt')

    def _claim_first_attempt(self, value):
        self._check_first_attempt(value)
        if value['message_id'] != 1:
            self._first_attempt_sid = value['header']['session_id']
            self._first_attempt_sequence = value['header']['sequence']
            mid = value['message_id']
            if (mid in (6, 37, 38) or mid == 4 and value['payload']['action'] != 'START'):
                self._control_boundary_sequence = value['header']['sequence']
                self._control_lease = None
                self._control_requested_source = (
                    value['payload']['source'] if mid == 6 else None)

    def discard_input(self, item):
        with self._operation():
            self._discard_input(item)

    def _discard_input(self, item):
        if self._operation_thread != threading.get_ident():
            raise ICDError('STATE', 'source input reclaim requires actual operation owner')
        key = self._owned_input(item)
        _, size = self._inputs.pop(key)
        self._input_bytes -= size

    def _request(self, stimulus, target_step, transaction_id):
        stimulus = copy.deepcopy(stimulus)
        self.contract.validate_stimulus(stimulus, model_id=loads(self._identity_json)["model_id"])
        # Reserve evidence before consuming sequence/transaction or sending.
        preview = {**stimulus, "header": {"session_id": MAX_COUNTER, "sequence": MAX_COUNTER,
                                         "target_step": MAX_COUNTER, "transaction_id": MAX_COUNTER,
                                         "valid_for_ms": self.contract.entry(stimulus["message_id"])["valid_for_ms"]}}
        self._record_capacity(preview)
        header = self._preview_header(stimulus["message_id"], target_step, transaction_id)
        self._check_heartbeat_transaction(stimulus['message_id'], header.transaction_id)
        self._commit_header(header, stimulus['message_id'],stimulus)
        value = {**stimulus, "header": asdict(header)}
        self.contract.validate_message(value, direction="TO_36")
        return self._exchange(value)

    def request(self, stimulus, *, target_step, transaction_id=None):
        with self._operation():
            return self._request(stimulus, target_step, transaction_id)

    def heartbeat(self, sender_step, *, target_step):
        with self._operation():
            reply = self._request({"message_id": 2, "payload": {"last_rx_sequence": self._last_rx_sequence,
                                                               "sender_step": sender_step}}, target_step, None)
            if reply["message_id"] == 131:
                self._deadline_ns = self._records[-1].started_ns + self._lease_ms * 1_000_000
            return reply

    def _abandon(self):
        self._sid = None
        self._roles = ()
        self._capabilities_json = None
        self._deadline_ns = 0
        self._last_rx_sequence = 0
        self._model_status = None
        self._model_step_floor = -1
        self._model_status_request_sequence = 0
        self._model_status_transaction = -1
        self._model_clock_retired = False
        self._model_epoch_retirement = None
        self._control_lease = None
        self._control_boundary_sequence = 0
        self._control_requested_source = None
        self._state = "ABANDONED"
        self._inputs.clear()
        self._input_bytes = 0

    def _remember_model_feedback(self, request, reply, started, completed, **metadata):
        _remember_feedback(self, request, reply, started, completed, **metadata)
        _remember_control_feedback(self, request, reply, started, completed, **metadata)
        reader = self._status_assertion_reader
        if reader is not None:
            reader._capture(request, reply, started, completed, **metadata)

    def abandon(self):
        with self._operation():
            self._abandon()

    def close(self):
        if not self._closed:
            with self._operation():
                self._closed_sid = self._sid
                self._abandon()
                self._closed = True

    def drain_records(self):
        with self._operation():
            if self._observation_recorder is not None:
                raise ICDError('STATE', 'original recorder owns persist-before-reclaim')
            result = tuple(self._records)
            self._records.clear()
            self._record_bytes = 0
            return result
