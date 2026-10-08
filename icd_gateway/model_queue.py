"""Common queue primitives; real consumers must own validation, writes and probes."""

from dataclasses import dataclass
import hashlib

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from icd_runtime.payload import PayloadCodec


@dataclass(frozen=True, slots=True)
class PendingInput:
    key: tuple
    model_id: str
    message_id: int
    target_step: int
    received_ns: int
    message_json: bytes
    sha256: str
    values: tuple
    writer: tuple

    @property
    def stored_bytes(self):
        return len(self.message_json) + sum(len(value.value_json) for value in self.values)


@dataclass(frozen=True, slots=True)
class RejectedInput:
    pending: PendingInput
    error: str


@dataclass(frozen=True, slots=True)
class StepBatch:
    ready: tuple
    rejected: tuple


class ModelQueue:
    def __init__(self, contract, registry, mappings):
        self.contract = contract
        self.registry = registry
        self._policy = contract.catalogue["policy"]
        self._mappings = {}
        for mapping in mappings:
            if (mapping.baseline_sha256 != contract.baseline_sha256
                    or mapping.model_id in self._mappings):
                raise ICDError("MODEL", "one same-baseline binding map per model required")
            self._mappings[mapping.model_id] = mapping
        if not self._mappings or registry.contract.baseline_sha256 != contract.baseline_sha256:
            raise ICDError("MODEL", "same-baseline registry and at least one binding map required")
        self._steps = {model: 0 for model in self._mappings}
        self._pending = {}
        self._writers = {}
        self._reservations = {}
        self._stored_bytes = 0
        self._last_now = -1
        self._closed = False
        self._payload = PayloadCodec(contract)
        registry._attach_model_queue(self)

    @property
    def count(self):
        return len(self._pending)

    @property
    def stored_bytes(self):
        return self._stored_bytes

    def _clock(self, now_ns):
        self.check_clock(now_ns)
        self._last_now = now_ns

    def check_clock(self, now_ns):
        if self._closed:
            raise ICDError("STATE", "queue is closed")
        if type(now_ns) is not int or now_ns < 0 or now_ns < self._last_now:
            raise ICDError("SCHEMA", "nondecreasing receiving monotonic nanoseconds required")

    def preview_expiry(self, active_sessions, *, now_ns):
        self.check_clock(now_ns)
        if (type(active_sessions) is not tuple or any(
                type(sid) is not int or not 1 <= sid <= 0xffffffff for sid in active_sessions)):
            raise ICDError("SCHEMA", "explicit nonzero uint32 active sessions required")
        live = set(active_sessions)
        return tuple(RejectedInput(p, "STALE_SESSION") for p in self._pending.values() if p.key[0] not in live)

    @staticmethod
    def _running(state):
        if state != "RUNNING":
            raise ICDError("STATE", "frozen/service-boundary inputs are not running-step queue entries")

    def enqueue(self, message, *, state, now_ns, control_source=None, input_lane=None):
        self._clock(now_ns)
        self._running(state)
        self.contract.validate_message(message, direction="TO_36")
        sid = int(message["header"]["session_id"])
        self.registry.expire(now_ns=now_ns)
        model = self.registry.identity(sid)["model_id"]
        if model not in self._mappings:
            raise ICDError("TARGET_MISSING", "selected model has no structural binding map")
        values = self._mappings[model].map_message(message)
        mid = message["message_id"]
        entry = self.contract.entry(mid)
        role = entry["role"]
        if role not in self.registry.roles(sid):
            raise ICDError("AUTHORIZATION", "mapped input role not granted by the session")
        received_ns = self.registry.require_admitted(message, now_ns=now_ns)
        self._payload.encode(mid, message["payload"])
        step = int(message["header"]["target_step"])
        if step > self._policy["max_run_duration_steps"]:
            raise ICDError("RANGE", "target exceeds the frozen run duration")
        if step <= self._steps[model]:
            raise ICDError("LATE", "target model boundary already began; no catch-up")
        if step - self._steps[model] > self._policy["max_ahead_steps"]:
            raise ICDError("RANGE", "target is more than1000 model steps ahead")
        if role == "CONTROLLER":
            lane = "FLIGHT_CONTROL" if mid in (7, 8, 9) else "ACTUATOR"
            if (control_source not in ("DEMO_MISSION", "PX4_SITL", "PHYSICAL_UUT") or input_lane != lane
                    or control_source == "DEMO_MISSION" and model != "quadrotor_hil"):
                raise ICDError("CONTROL_OWNER", "external input does not match the declared source/lane/model")
            if now_ns - received_ns >= self._policy["control_timeout_ms"] * 1_000_000:
                raise ICDError("EXPIRED", "control reached100ms since original reception")
        elif control_source is not None or input_lane is not None:
            raise ICDError("CONTROL_OWNER", "stimulus cannot claim a controller source/lane")
        writer = (sid, role, control_source, input_lane)
        for value in values:
            owner = self._writers.get((model, value.path))
            if owner is not None and owner != writer:
                raise ICDError("CONTROL_OWNER", "target path already belongs to a different writer/lane")
            if (model, step, value.path) in self._reservations:
                raise ICDError("CONTROL_OWNER", "messages at the same target step must have disjoint paths")
        if self.count >= self._policy["queue_capacity"]:
            raise ICDError("BUFFER_FULL", "4096 logical messages; unapplied values are never overwritten")
        raw = canonicalize(message)
        pending = PendingInput((sid, int(message["header"]["sequence"])), model, mid, step,
                               received_ns, raw, hashlib.sha256(raw).hexdigest(), values, writer)
        # Commit only after every field, reservation and capacity check succeeds.
        self.registry.claim_admitted(message, now_ns=now_ns)
        self._pending[pending.key] = pending
        self._stored_bytes += pending.stored_bytes
        for value in values:
            self._writers[model, value.path] = writer
            self._reservations[model, step, value.path] = pending.key
        return pending

    def _remove(self, pending):
        del self._pending[pending.key]
        self._stored_bytes -= pending.stored_bytes
        for value in pending.values:
            del self._reservations[pending.model_id, pending.target_step, value.path]

    def discard_session(self, session_id):
        removed = tuple(p for p in self._pending.values() if p.key[0] == session_id)
        for pending in removed:
            self._remove(pending)
        self._writers = {key: writer for key, writer in self._writers.items() if writer[0] != session_id}
        return removed

    def expire(self, *, now_ns):
        self._clock(now_ns)
        self.registry.expire(now_ns=now_ns)
        live = set(self.registry.session_ids)
        stale = {p.key[0] for p in self._pending.values() if p.key[0] not in live}
        stale.update(writer[0] for writer in self._writers.values() if writer[0] not in live)
        rejected = []
        for sid in sorted(stale):
            rejected.extend(RejectedInput(p, "STALE_SESSION") for p in self.discard_session(sid))
        return tuple(rejected)

    def begin_step(self, model_id, step, *, state, now_ns):
        self._clock(now_ns)
        self._running(state)
        if model_id not in self._steps:
            raise ICDError("MODEL", "unknown selected model")
        if type(step) is not int or not 1 <= step <= self._policy["max_run_duration_steps"]:
            if step == 0 and type(step) is int:
                raise ICDError("OUT_OF_ORDER", "only the exact next model boundary is allowed")
            raise ICDError("RANGE", "model boundary outside the run duration")
        if step != self._steps[model_id] + 1:
            raise ICDError("OUT_OF_ORDER", "model boundaries must be sequential1ms steps")
        rejected = list(self.expire(now_ns=now_ns))
        self._steps[model_id] = step
        ready = []
        for pending in tuple(self._pending.values()):
            if pending.model_id != model_id or pending.target_step > step:
                continue
            self._remove(pending)
            if pending.target_step < step:
                rejected.append(RejectedInput(pending, "LATE"))
            elif (pending.writer[1] == "CONTROLLER" and
                  now_ns - pending.received_ns >= self._policy["control_timeout_ms"] * 1_000_000):
                rejected.append(RejectedInput(pending, "EXPIRED"))
            else:
                ready.append(pending)
        return StepBatch(tuple(ready), tuple(rejected))

    def clear(self):
        removed = tuple(self._pending.values())
        self._pending.clear()
        self._writers.clear()
        self._reservations.clear()
        self._stored_bytes = 0
        return removed

    def close(self):
        removed = self.clear()
        self._closed = True
        return removed
