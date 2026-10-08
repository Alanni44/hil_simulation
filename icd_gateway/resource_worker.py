"""One bounded actual storage thread; session admission and feedback stay on caller."""

from collections import OrderedDict, deque
from dataclasses import dataclass
import math
import threading
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.resource_budget import ResourceBudget
from icd_runtime.wire import WireCodec
from .resources import ResourceStore


@dataclass(frozen=True, slots=True)
class ResourceOutcome:
    key: tuple
    request_bytes: bytes
    binding: object
    payload_bytes: bytes
    completed_ns: int


@dataclass(frozen=True, slots=True)
class ResourceShutdown:
    outcomes: tuple
    aborted_resources: tuple
    error: str | None
    unfinished_resources: tuple = ()


@dataclass(frozen=True, slots=True)
class _Job:
    key: tuple
    request_bytes: bytes
    binding: object
    received_ns: int
    due_ns: int


class ResourceWorker:
    def __init__(self, contract, registry, store, *, capacity=64, max_pending_bytes=4194304):
        if type(capacity) is not int or not 1 <= capacity <= 64:
            raise ICDError("CAPACITY", "resource task/result capacity requires1..64")
        if type(max_pending_bytes) is not int or not 1 <= max_pending_bytes <= 4194304:
            raise ICDError("CAPACITY", "pending original resource bytes require1..4MiB")
        if (type(store) is not ResourceStore or store.contract is not contract
                or registry.contract is not contract or registry._resource_worker is not None):
            raise ICDError("STATE", "one actual same-contract resource store/registry required")
        registry._ensure_open()
        store._claim_worker()
        self.contract, self.registry, self.store = contract, registry, store
        self.capacity, self.max_pending_bytes = capacity, max_pending_bytes
        self._condition = threading.Condition()
        self._queue = deque()
        self._jobs = {}
        self._results = OrderedDict()
        self._pending_bytes = 0
        self._live = set(registry.session_ids)
        self._upload_sessions = set()
        self._last_now = -1
        self._closing = False
        self._closed = False
        self._fatal = None
        self._drain_command = None
        self._shutdown = None
        self._budget = ResourceBudget(contract)
        self._wire = WireCodec(contract)
        self._thread = threading.Thread(target=self._run, name="icd-resource-storage", daemon=False)
        try:
            self._thread.start()
        except RuntimeError as exc:
            if self._thread.is_alive():
                self.close()
            else:
                store._worker_claimed = False
                store.close()
            raise ICDError("STATE", "actual resource thread could not start") from exc
        registry._attach_resource_worker(self)

    @property
    def pending_count(self):
        with self._condition:
            return len(self._jobs)

    @property
    def available(self):
        return self._thread.is_alive() and not self._closing and self._fatal is None

    def check_clock(self, now_ns):
        if type(now_ns) is not int or now_ns < 0 or now_ns < self._last_now:
            raise ICDError("SCHEMA", "nondecreasing resource service clock required")
        if not self.available:
            raise ICDError("STATE", "resource worker unavailable")

    def submit(self, message, binding, *, now_ns, received_response=None):
        self.check_clock(now_ns)
        self.contract.validate_message(message, direction="TO_36")
        if message["message_id"] != 34:
            raise ICDError("UNSUPPORTED", "resource worker accepts only ResourceChunk34")
        self.registry.preauthorize(34, int(message["header"]["session_id"]), binding, now_ns=now_ns)
        received = self.registry.require_admitted(message, now_ns=now_ns)
        if message["payload"]["resource_kind"] in ("MODEL", "TERRAIN"):
            raise ICDError("TARGET_MISSING", "MODEL/TERRAIN submission requires the actual stopped model/state contract gate")
        original = canonicalize(message)
        packets = tuple(self._wire.encode(message, "UDP"))
        with self._condition:
            if len(self._jobs) >= self.capacity or self._pending_bytes + len(original) > self.max_pending_bytes:
                raise ICDError("BUFFER_FULL", "resource task/result reservation full; no eviction")
            due = self._budget.preview(packets, now_ns=now_ns)
            if due >= received + message["header"]["valid_for_ms"] * 1_000_000:
                raise ICDError("CAPACITY", "resource budget would schedule an expired write start")
            if received_response is not None:
                self.registry.check_resource_deferral(message, received_response, now_ns=now_ns)
            self.registry.claim_admitted(message, now_ns=now_ns)
            if received_response is not None:
                self.registry.defer_resource_response(message, (received_response,), now_ns=now_ns)
            key = (int(message["header"]["session_id"]), int(message["header"]["sequence"]))
            job = _Job(key, original, binding, received, due)
            self._budget.reserve(packets, now_ns=now_ns)
            self._jobs[key] = job
            self._queue.append(job)
            self._pending_bytes += len(original)
            self._last_now = now_ns
            self._live = set(self.registry.session_ids)
            self._condition.notify_all()

    def synchronize_sessions(self, session_ids, *, now_ns):
        self.check_clock(now_ns)
        if (type(session_ids) is not tuple or len(session_ids) > 64
                or any(type(sid) is not int or not 1 <= sid <= 0xffffffff for sid in session_ids)
                or len(set(session_ids)) != len(session_ids)):
            raise ICDError("SCHEMA", "actual unique nonzero uint32 live sessions required")
        with self._condition:
            self._live = set(session_ids)
            self._last_now = now_ns
            self._condition.notify_all()

    def peek_results(self):
        with self._condition:
            return tuple(self._results.values())

    def cancel_session(self, session_id):
        if type(session_id) is not int or not 1 <= session_id <= 0xffffffff:
            raise ICDError("SCHEMA", "nonzero uint32 cancellation session required")
        with self._condition:
            self._live.discard(session_id)
            self._condition.notify_all()

    def release_result(self, key):
        with self._condition:
            if key not in self._results:
                raise ICDError("STATE", "only a completed preserved resource result can be released")
            del self._results[key]
            self._pending_bytes -= len(self._jobs[key].request_bytes)
            del self._jobs[key]

    def drain_abort_records(self, *, timeout=1):
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ICDError("SCHEMA", "finite resource drain timeout requires0..10s")
        with self._condition:
            if self._closed:
                result = self._shutdown.aborted_resources
                self._shutdown = ResourceShutdown(self._shutdown.outcomes, (), self._shutdown.error,
                                                  self._shutdown.unfinished_resources)
                return result
            command = self._drain_command
            if command is None:
                if not self.available:
                    raise ICDError("STATE", "resource abort drain service unavailable")
                command = {"done": False, "result": ()}
                self._drain_command = command
                self._condition.notify_all()
            if not self._condition.wait_for(lambda: command["done"] or self._fatal is not None, timeout):
                raise ICDError("TIMEOUT", "background resource abort drain still pending")
            if not command["done"]:
                raise ICDError("STATE", "resource worker failed during drain")
            self._drain_command = None
            return command["result"]

    def _payload(self, request, error):
        progress = self.store.progress_for(request).payload()
        progress["error"] = error
        if error != "OK":
            progress["complete"] = False
        return progress

    def _process(self, job):
        request = loads(job.request_bytes)
        with self._condition:
            cancelled = job.key[0] not in self._live or self._closing
        now = time.monotonic_ns()
        if cancelled:
            error = "STATE" if self._closing else "STALE_SESSION"
        elif now >= job.received_ns + request["header"]["valid_for_ms"] * 1_000_000:
            error = "EXPIRED"
        else:
            try:
                self.store.accept(request, now_ns=now)
                error = "OK"
            except ICDError as exc:
                error = exc.code
        completed = time.monotonic_ns()
        deadline = job.received_ns + (self.contract.catalogue["policy"]["resource_commit_timeout_ms"]
                                     if request["payload"]["final"] else request["header"]["valid_for_ms"]) * 1_000_000
        with self._condition:
            if job.key[0] not in self._live or self._closing:
                error = "STATE" if self._closing else "STALE_SESSION"
            elif completed >= deadline:
                error = "TIMEOUT"
        if error in ("EXPIRED", "TIMEOUT"):
            try:
                self.store.abort_resource(job.key[0], request["payload"]["resource_sha256"], error=error)
            except ICDError as exc:
                if exc.code != "AUTHORIZATION":
                    raise
        payload = self._payload(request, error)
        outcome = ResourceOutcome(job.key, job.request_bytes, job.binding, canonicalize(payload), completed)
        sessions = self.store.active_session_ids()
        with self._condition:
            self._upload_sessions = set(sessions)
            self._results[job.key] = outcome
            self._condition.notify_all()

    def _run(self):
        try:
            self.store._bind_worker_thread()
            while True:
                with self._condition:
                    invalid = self._upload_sessions - self._live
                    if invalid:
                        action, value = "abort", next(iter(invalid))
                    elif self._drain_command is not None and not self._drain_command["done"]:
                        action, value = "drain", self._drain_command
                    elif self._queue:
                        job = self._queue[0]
                        remaining = job.due_ns - time.monotonic_ns()
                        if remaining > 0 and not self._closing and job.key[0] in self._live:
                            self._condition.wait(min(remaining / 1_000_000_000, 0.02))
                            continue
                        action, value = "job", self._queue.popleft()
                    elif self._closing:
                        break
                    else:
                        self._condition.wait(0.02)
                        continue
                if action == "abort":
                    self.store.abort_session(value)
                    with self._condition:
                        self._upload_sessions.discard(value)
                elif action == "drain":
                    records = self.store.drain_aborted()
                    with self._condition:
                        value.update(done=True, result=records)
                        self._condition.notify_all()
                else:
                    self._process(value)
        except Exception as exc:
            with self._condition:
                self._fatal = exc.code if isinstance(exc, ICDError) else "STATE"
                for key, job in self._jobs.items():
                    if key not in self._results:
                        request = loads(job.request_bytes)
                        payload = {"resource_sha256": request["payload"]["resource_sha256"],
                                   "next_offset": 0, "complete": False, "stored_bytes": 0, "error": self._fatal}
                        self._results[key] = ResourceOutcome(key, job.request_bytes, job.binding,
                                                             canonicalize(payload), time.monotonic_ns())
                self._queue.clear()
                self._condition.notify_all()
        finally:
            error = self._fatal
            aborted = ()
            try:
                self.store.close()
            except ICDError as exc:
                error = exc.code
            aborted = self.store.drain_aborted()
            unfinished = self.store.pending_cleanup_records()
            with self._condition:
                if self._drain_command is not None and self._drain_command["done"]:
                    aborted = self._drain_command["result"] + aborted
                    self._drain_command = None
                self._shutdown = ResourceShutdown(tuple(self._results.values()), aborted, error, unfinished)
                self._condition.notify_all()

    def close(self, *, timeout=10):
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ICDError("SCHEMA", "finite resource shutdown timeout requires0..10s")
        if self._closed:
            return self._shutdown
        with self._condition:
            self._closing = True
            self._live.clear()
            self._condition.notify_all()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise ICDError("TIMEOUT", "resource worker is still running; no forced termination or false shutdown")
        self._closed = True
        return self._shutdown
