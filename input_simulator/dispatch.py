"""Single-owner cooperative UDP exchanges; no model/tool readiness is invented."""

from contextlib import contextmanager
import copy
from dataclasses import asdict, dataclass
import threading
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import Header
from .session import MAX_COUNTER, MAX_REPLY_BYTES, SourceSession


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    kind: str
    header: object
    at_ns: int | None
    attempt: int
    fragment_index: int | None = None
    request_json: bytes | None = None
    reply_json: bytes | None = None
    wire_data: bytes | None = None
    error: str | None = None

    @property
    def reply(self):
        return None if self.reply_json is None else loads(self.reply_json)

    @property
    def request(self):
        return None if self.request_json is None else loads(self.request_json)


@dataclass(slots=True)
class _Pending:
    request: dict
    packets: tuple
    header: object
    submitted_ns: int
    maximum_attempts: int
    reserved_count: int
    reserved_bytes: int
    token: object = None
    heartbeat_due: int | None = None
    attempt: int = 0
    index: int = 0
    first_perf: int | None = None
    started_ns: int | None = None
    deadline_ns: int | None = None
    sent_once: bool = False
    feedback_count: int = 0
    heartbeat_claimed: bool = False
    first_attempt_claimed: bool = False


class UDPDispatcher:
    def __init__(self, session, *, capacity=64, max_records=4096, max_bytes=16 * 1024 * 1024):
        if (type(capacity) is not int or not 1 <= capacity <= 64
                or type(max_records) is not int or not 1 <= max_records <= 65536
                or type(max_bytes) is not int or not 1 <= max_bytes <= 128 * 1024 * 1024):
            raise ICDError("CAPACITY", "bounded dispatcher capacities required")
        if not isinstance(session, SourceSession):
            raise ICDError("STATE", "actual source session required")
        self.session = session
        self.transport = session.transport
        self.contract = session.contract
        self._observation_owners = (session, self.transport, self.contract)
        if any(not callable(getattr(self.transport, name, None)) for name in
               ("receive_matching", "prepare_transmission", "transmit_fragment", "discard_transmission")):
            raise ICDError("STATE", "cooperative standard UDP transport required")
        self._lock = threading.Lock()
        self._closed = False
        self._pending = {}
        self._records = []
        self._used_count = self._used_bytes = 0
        self._reserved_count = self._reserved_bytes = 0
        self._capacity, self._max_records, self._max_bytes = capacity, max_records, max_bytes
        self._provider = None
        self._next_heartbeat = None
        self._policy = self.contract.catalogue["policy"]
        self._evidence_inbox = None
        self._observation_recorder = None
        with session._operation():
            if session._native_tool_coordinator is not None:
                raise ICDError('STATE', 'detach original native coordinator before replacing its dispatcher')
            if session._observation_recorder is not None:
                raise ICDError('STATE', 'detach original recorder before replacing its dispatcher')
            now = session._now()
            if session.session_id is None or now >= session._deadline_ns or session._state != "LIVE":
                raise ICDError("STALE_SESSION", "dispatcher requires an actual live grant")
            session._dispatcher = self

    @contextmanager
    def _operation(self, *, closed_ok=False):
        if not self._lock.acquire(blocking=False):
            raise ICDError("STATE", "dispatcher operations require a single serialized owner")
        try:
            if self._closed and not closed_ok:
                raise ICDError("STATE", "dispatcher permanently closed")
            coordinator = self.session._native_tool_coordinator
            if coordinator is not None and coordinator._closing and not closed_ok:
                raise ICDError('STATE', 'attached original native coordinator is closing')
            yield
        finally:
            self._lock.release()

    @property
    def pending_count(self):
        return len(self._pending)

    @property
    def records(self):
        return tuple(self._records)

    def enable_evidence_collection(self, **limits):
        from .evidence import EvidenceInbox
        from .udp_source import UDPSource
        with self._operation(), self.session._operation(owner=self):
            if self._observation_recorder is not None:
                raise ICDError('STATE', 'stop the original recorder before replacing its feedback reader')
            self._check_lease(self.session._now())
            if (not isinstance(self.transport,UDPSource) or self.transport.socket.fileno() < 0 or
                    self.transport.feedback_socket.fileno() < 0):
                raise ICDError('STATE', 'actual live standard UDP sockets required for evidence')
            if self._evidence_inbox is not None or self.transport._evidence_inbox is not None:
                raise ICDError('STATE', 'one original feedback reader/inbox per transport')
            inbox = EvidenceInbox(self.session,**limits)
            self._evidence_inbox = self.transport._evidence_inbox = inbox
            return inbox

    def watch_evidence(self, header, *, event_id, trace_id, min_step, max_step, stages=('E1','E2','E3')):
        with self._operation(), self.session._operation(owner=self):
            self._check_lease(self.session._now())
            pending = self._pending.get(getattr(header,'sequence',None))
            if (self._evidence_inbox is None or pending is None or pending.header is not header or pending.attempt != 0):
                raise ICDError('STATE', 'watch the original pending Header before actual first TX')
            self._evidence_inbox._watch(header,pending.request,event_id=event_id,trace_id=trace_id,
                                         min_step=min_step,max_step=max_step,stages=stages)

    def unwatch_evidence(self, header):
        with self._operation(), self.session._operation(owner=self):
            if self._evidence_inbox is None:
                raise ICDError('STATE', 'evidence collection not enabled')
            self._evidence_inbox._unwatch(header)

    def _record(self, pending, kind, now, *, reply=None, wire=None, index=None, request=None, error=None):
        size = 512 + sum(len(x) for x in (reply, wire, request) if x is not None)
        if pending.reserved_count < 1 or pending.reserved_bytes < size:
            raise ICDError("BUFFER_FULL", "dispatcher record reservation exhausted")
        pending.reserved_count -= 1
        pending.reserved_bytes -= size
        self._reserved_count -= 1
        self._reserved_bytes -= size
        self._used_count += 1
        self._used_bytes += size
        self._records.append(DispatchRecord(kind, pending.header, now, pending.attempt,
                                            index, request, reply, wire, error))

    def _finish(self, pending, kind, now, error=None):
        self._record(pending, kind, now, error=error)
        self.transport.discard_transmission(pending.token, owner=self.session)
        self._reserved_count -= pending.reserved_count
        self._reserved_bytes -= pending.reserved_bytes
        del self._pending[pending.header.sequence]

    def _check_lease(self, now):
        if now >= self.session._deadline_ns:
            for p in tuple(self._pending.values()):
                self._finish(p,"FAILED",now,"STALE_SESSION")
            raise ICDError("STALE_SESSION", "actual source lease expired; pending inputs cancelled locally")

    def _submit(self, stimulus, target_step, transaction_id):
        stimulus = copy.deepcopy(stimulus)
        model = loads(self.session._identity_json)["model_id"]
        self.contract.validate_stimulus(stimulus, model_id=model)
        mid = stimulus["message_id"]
        entry = self.contract.entry(mid)
        preview = {**stimulus, "header": {"session_id": MAX_COUNTER, "sequence": MAX_COUNTER,
                                          "target_step": MAX_COUNTER, "transaction_id": MAX_COUNTER,
                                          "valid_for_ms": entry["valid_for_ms"]}}
        packets = self.transport.wire.encode(preview, "UDP")
        attempts = 4 if entry["period_ms"] == 0 else 1
        count = 2 + len(packets) * attempts + 8
        size = count * 512 + len(canonicalize(preview)) + sum(map(len, packets)) * attempts + 8 * MAX_REPLY_BYTES
        if (len(self._pending) >= self._capacity or self._used_count + self._reserved_count + count > self._max_records
                or self._used_bytes + self._reserved_bytes + size > self._max_bytes):
            raise ICDError("BUFFER_FULL", "dispatcher pending/evidence capacity full before allocation/TX")
        txn = self.session._next_transaction if transaction_id is None else transaction_id
        # Typed replies without request_sequence cannot disambiguate these groups.
        for other in self._pending.values():
            if other.header.transaction_id != txn or other.request["message_id"] != mid:
                continue
            if (mid == 2 or mid == 33 and other.request["payload"]["nonce"] == stimulus["payload"]["nonce"]
                    or mid == 34 and other.request["payload"]["resource_sha256"] == stimulus["payload"]["resource_sha256"]):
                raise ICDError("STATE", "typed feedback would be ambiguous between in-flight requests")
        header = self.session._preview_header(mid, target_step, transaction_id)
        self.session._check_heartbeat_transaction(mid, header.transaction_id)
        self.session._commit_header(header, mid,stimulus)
        request = {**stimulus, "header": asdict(header)}
        packets = self.transport.wire.encode(request, "UDP")
        now = self.session._now()
        pending = _Pending(request, packets, header, now, attempts, count, size)
        pending.token = self.transport.prepare_transmission(request, owner=self.session)
        self._pending[header.sequence] = pending
        self._reserved_count += count
        self._reserved_bytes += size
        self._record(pending, "SUBMITTED", now, request=canonicalize(request))
        return header

    def submit(self, stimulus, *, target_step, transaction_id=None):
        with self._operation(), self.session._operation(owner=self):
            return self._submit(stimulus, target_step, transaction_id)

    def enable_heartbeat(self, step_provider):
        with self._operation(), self.session._operation(owner=self):
            if not callable(step_provider):
                raise ICDError("SCHEMA", "actual sender/target-step provider required")
            if 2 not in self.session.capabilities["implemented_message_ids"]:
                raise ICDError("TARGET_MISSING", "receiver does not publish Heartbeat implementation")
            if self._provider is not None:
                raise ICDError("STATE", "heartbeat schedule already enabled")
            self._provider = step_provider
            self._next_heartbeat = self.session._now()

    def _heartbeat(self, now):
        if self._provider is None or now < self._next_heartbeat:
            return
        if now - self._next_heartbeat > self._policy["transport_jitter_budget_us"] * 1000:
            self._provider = None
            raise ICDError("TIMEOUT", "heartbeat tick late; no catch-up or wall-clock model-step substitution")
        steps = self._provider()
        if type(steps) is not tuple or len(steps) != 2:
            raise ICDError("SCHEMA", "explicit sender_step/target_step pair required")
        header = self._submit({"message_id": 2, "payload": {"last_rx_sequence": self.session.last_rx_sequence,
                                                            "sender_step": steps[0]}}, steps[1], None)
        self._pending[header.sequence].heartbeat_due = self._next_heartbeat
        self._next_heartbeat += self._policy["heartbeat_period_ms"] * 1_000_000

    def _receive(self, now):
        for _ in range(64):
            pending = tuple(p for p in self._pending.values() if p.sent_once)
            if not pending and self._evidence_inbox is None:
                break
            try:
                index, reply = self.transport.receive_matching(tuple(p.request for p in pending), timeout=0, owner=self.session)
            except ICDError as error:
                if error.code == "TIMEOUT":
                    break
                raise
            p = pending[index]
            raw = canonicalize(reply)
            if len(raw) > MAX_REPLY_BYTES:
                self._finish(p, "FAILED", now, "CAPACITY")
                continue
            try:
                now = self.session._now()
                self.session._check_reply(p.request, reply, p.started_ns, now)
            except ICDError as error:
                self._record(p,"RX",None if error.code == "SCHEMA" else now,reply=raw,error=error.code)
                self._finish(p,"FAILED",None if error.code == "SCHEMA" else now,error.code)
                raise
            final_resource = p.request["message_id"] == 34 and p.request["payload"]["final"]
            if now >= self.session._deadline_ns:
                self._record(p,"RX",now,reply=raw,error="STALE_SESSION")
                self._check_lease(now)
            validity_deadline = p.started_ns + p.header.valid_for_ms * 1_000_000
            deadline = (p.submitted_ns + self._policy["resource_commit_timeout_ms"] * 1_000_000
                        if final_resource else min(p.deadline_ns if p.deadline_ns is not None else validity_deadline,
                                                   validity_deadline))
            if now >= deadline:
                self._record(p,"RX",now,reply=raw,error="TIMEOUT")
                self._finish(p,"TIMEOUT",now,"TIMEOUT")
                continue
            self.session._remember_model_feedback(p.request, reply, p.started_ns, now, transport='UDP',
                channel=self.transport.channel, fresh=reply['header']['sequence'] > self.session.last_rx_sequence)
            self.session._last_rx_sequence = max(self.session.last_rx_sequence, reply["header"]["sequence"])
            mid = reply["message_id"]
            error = reply["payload"]["error"] if mid in (130,141) and reply["payload"]["error"] != "OK" else None
            self._record(p, "RX", now, reply=raw, error=error)
            p.feedback_count += 1
            if mid == 131:
                self.session._deadline_ns = max(self.session._deadline_ns, p.started_ns + self._policy["session_lease_ms"] * 1_000_000)
            terminal = mid != 130 or reply["payload"]["stage"] in ("FAILED","APPLIED","CONSUMED")
            if terminal:
                self._finish(p, "COMPLETE" if error is None else "FAILED", now, error)
            elif p.feedback_count == 8:
                self._finish(p, "FAILED", now, "BUFFER_FULL")

    def _transmit(self, now):
        work = 0
        for _ in range(64):
            progressed = False
            ordered = sorted(self._pending.values(), key=lambda p: p.header.sequence)
            for p in ordered:
                now = self.session._now()
                self._check_lease(now)
                if p.header.sequence not in self._pending:
                    continue
                if p.heartbeat_due is not None and not p.sent_once and now - p.heartbeat_due > self._policy["transport_jitter_budget_us"] * 1000:
                    self._finish(p,"TIMEOUT",now,"TIMEOUT")
                    self._provider = None
                    raise ICDError("TIMEOUT", "actual heartbeat TX deadline missed")
                if not p.sent_once and any(q.header.sequence < p.header.sequence and not q.sent_once for q in self._pending.values()):
                    continue
                final_resource = p.request["message_id"] == 34 and p.request["payload"]["final"]
                if final_resource and now >= p.submitted_ns + self._policy["resource_commit_timeout_ms"] * 1_000_000:
                    self._finish(p,"TIMEOUT",now,"TIMEOUT")
                    continue
                if p.deadline_ns is not None:
                    if now < p.deadline_ns:
                        continue
                    if p.attempt >= p.maximum_attempts:
                        if final_resource:
                            continue
                        self._finish(p,"TIMEOUT",now,"TIMEOUT")
                        continue
                    p.deadline_ns = None
                    p.index = 0
                    p.first_perf = None
                if p.started_ns is not None and now >= p.started_ns + p.header.valid_for_ms * 1_000_000:
                    if final_resource and p.index == len(p.packets):
                        continue
                    self._finish(p,"TIMEOUT",now,"TIMEOUT")
                    continue
                perf = time.perf_counter_ns()
                if p.first_perf is not None and perf - p.first_perf >= self.transport._resource_group_ns:
                    self._finish(p,"TIMEOUT",now,"TIMEOUT")
                    continue
                try:
                    if p.started_ns is None:
                        self.session._check_first_attempt(p.request, already_claimed=p.first_attempt_claimed)
                    if p.request['message_id'] == 2 and not p.heartbeat_claimed:
                        self.session._claim_heartbeat_attempt(p.request)
                        p.heartbeat_claimed = True
                    if not p.first_attempt_claimed:
                        self.session._claim_first_attempt(p.request)
                        p.first_attempt_claimed = True
                    sent = self.transport.transmit_fragment(p.token,p.index,owner=self.session)
                except (ICDError,OSError) as error:
                    self._finish(p,"FAILED",now,error.code if isinstance(error,ICDError) else "STATE")
                    continue
                if not sent:
                    continue
                if p.index == 0:
                    p.attempt += 1
                    p.first_perf = perf
                    if p.started_ns is None:
                        p.started_ns = now
                index = p.index
                p.index += 1
                work += 1
                progressed = True
                if p.index == len(p.packets):
                    p.sent_once = True
                    p.first_perf = None
                    p.deadline_ns = now + self._policy["ack_timeout_ms"] * 1_000_000
                try:
                    now = self.session._now()
                except ICDError as error:
                    self._record(p,"TX",None,wire=p.packets[index],index=index,error=error.code)
                    self._finish(p,"FAILED",None,error.code)
                    raise
                self._record(p,"TX",now,wire=p.packets[index],index=index,
                             error="STALE_SESSION" if now >= self.session._deadline_ns else None)
                if self._evidence_inbox is not None:
                    self._evidence_inbox._note_tx(p.header,index,p.packets[index])
                self._check_lease(now)
                if p.heartbeat_due is not None and now - p.heartbeat_due > self._policy["transport_jitter_budget_us"] * 1000:
                    self._finish(p,"TIMEOUT",now,"TIMEOUT")
                    self._provider = None
                    raise ICDError("TIMEOUT", "actual heartbeat TX was late")
                if work >= 64:
                    return work
            if not progressed:
                break
        return work

    def poll(self):
        with self._operation(), self.session._operation(owner=self):
            now = self.session._now()
            self._check_lease(now)
            self._receive(now)
            self._heartbeat(self.session._now())
            return self._transmit(now)

    def close(self):
        with self._operation(closed_ok=True):
            if self._closed:
                return
            with self.session._operation(owner=self):
                error = "STATE"
                try:
                    now = self.session._now()
                except ICDError:
                    now, error = None, "SCHEMA"
                for p in tuple(self._pending.values()):
                    self._finish(p,"CANCEL",now,error)
                self._provider = None
                if self._evidence_inbox is not None:
                    self._evidence_inbox._close()
                    self.transport._evidence_inbox = None
                self.session._dispatcher = None
                self._closed = True

    def cancel(self, header):
        with self._operation(closed_ok=True), self.session._operation(owner=self, closed_ok=True):
            if type(header) is not Header:
                raise ICDError('STATE', 'actual pending Header object required for local cancellation')
            pending = self._pending.get(header.sequence)
            if pending is None or pending.header is not header:
                raise ICDError('STATE', 'foreign, forged or terminal Header cannot cancel a pending group')
            try:
                now, error = self.session._now(), 'STATE'
            except ICDError:
                now, error = None, 'SCHEMA'
            self._finish(pending, 'CANCEL', now, error)

    def drain_records(self):
        with self._operation(closed_ok=True):
            if self._observation_recorder is not None:
                raise ICDError('STATE', 'original recorder owns persist-before-reclaim')
            records = tuple(self._records)
            self._records.clear()
            self._used_count = self._used_bytes = 0
            return records
