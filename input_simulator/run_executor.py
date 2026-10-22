"""One-active-run executor shell with evidence-gated state callbacks.

It intentionally has no default backend.  A target integration must implement
``RunExecutionBackend`` using the formal Session/RunConfigure/Lifecycle path;
without it, management control remains unavailable rather than simulating a
successful HIL execution.
"""

from abc import ABC, abstractmethod
import copy
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads


class RunExecutionBackend(ABC):
    @abstractmethod
    def execute(self, snapshot, reporter, stop_requested):
        """Run one actual HIL operation and report evidence-backed milestones.

        ``reporter.running`` is legal only after HIL has supplied START APPLIED
        or an equivalent fresh actual status.  ``completed``/``failed`` must
        likewise be backed by retained execution evidence.
        """

    @abstractmethod
    def request_stop(self, operation_id):
        """Request cancellation; return only after issuing a real stop request.

        Confirmation remains the responsibility of ``execute`` via reporter.
        """


class ExecutionReporter:
    def __init__(self, *, running, completed, failed, record=None):
        self._running, self._completed, self._failed = running, completed, failed
        self._record = record
        self._state = "WAITING"
        self._lock = threading.Lock()

    def running(self, evidence_refs=()):
        with self._lock:
            if self._state != "WAITING":
                raise ICDError("STATE", "actual RUNNING evidence may be reported once")
            self._state = "RUNNING"
        self._running(tuple(evidence_refs))

    def completed(self, result, evidence_refs=()):
        with self._lock:
            if self._state not in {"WAITING", "RUNNING"}:
                raise ICDError("STATE", "actual terminal evidence may be reported once")
            if result not in {"PASS", "FAIL", "INCOMPLETE"}:
                raise ICDError("SCHEMA", "terminal Run result is invalid")
            self._state = "COMPLETED"
        self._completed(result, tuple(evidence_refs))

    def failed(self, code, detail, evidence_refs=()):
        with self._lock:
            if self._state == "COMPLETED":
                raise ICDError("STATE", "completed execution cannot become failed")
            if type(code) is not str or type(detail) is not str:
                raise ICDError("SCHEMA", "execution failure code and detail are required")
            self._state = "FAILED"
        self._failed(code, detail, tuple(evidence_refs))

    def record(self, kind, reason_code, **fields):
        if self._record is None:
            return
        self._record(kind, reason_code, **fields)

    @property
    def terminal(self):
        with self._lock:
            return self._state in {"COMPLETED", "FAILED"}


class RunExecutor:
    """Owns one bounded worker and delegates all target effects to a backend."""

    def __init__(self, backend):
        if not isinstance(backend, RunExecutionBackend):
            raise ICDError("TARGET_MISSING", "explicit actual RunExecutionBackend required")
        self.backend = backend
        self._lock = threading.Lock()
        self._active = None

    def submit(self, operation_id, snapshot, *, on_running, on_completed, on_failed, on_record=None):
        if (type(operation_id) is not str or not callable(on_running) or not callable(on_completed)
                or not callable(on_failed) or on_record is not None and not callable(on_record)):
            raise ICDError("SCHEMA", "bounded operation ID and execution callbacks required")
        with self._lock:
            if self._active is not None:
                raise ICDError("CONTROL_CONFLICT", "one simulator execution is already active")
            stopped = threading.Event()
            reporter = ExecutionReporter(running=on_running, completed=on_completed, failed=on_failed,
                                         record=on_record)
            begin = getattr(self.backend, "begin", None)
            if begin is not None:
                begin(operation_id, stopped)

            def worker():
                try:
                    self.backend.execute(snapshot, reporter, stopped)
                    if not reporter.terminal:
                        reporter.failed("INTERNAL_ERROR", "execution backend returned without terminal evidence")
                except ICDError as error:
                    if not reporter.terminal:
                        reporter.failed(error.code, error.detail)
                except Exception:
                    if not reporter.terminal:
                        reporter.failed("INTERNAL_ERROR", "execution backend raised unexpectedly")
                finally:
                    with self._lock:
                        self._active = None

            thread = threading.Thread(target=worker, name="simulator-run-" + operation_id, daemon=True)
            self._active = (operation_id, stopped, thread)
            thread.start()

    def request_stop(self, operation_id):
        with self._lock:
            active = self._active
            if active is None or active[0] != operation_id:
                raise ICDError("STATE", "requested operation is not the active execution")
            active[1].set()
        self.backend.request_stop(operation_id)

    @property
    def active_operation_id(self):
        with self._lock:
            return None if self._active is None else self._active[0]


class FormalHILExecutionBackend(RunExecutionBackend):
    """Minimal formal second-circle executor with no synthetic scenario result.

    ``session_factory`` must create one new, unopened ``SourceSession`` and
    its owned UDP transport for each operation.  The backend sends the frozen
    RunConfigure, waits for its APPLIED receipt, then sends Lifecycle.START.
    It uses ID2 Status responses to choose the STOP target step.  No scenario
    input engine is installed here, so a user-requested stop ends as
    ``INCOMPLETE`` rather than claiming an assertion-derived PASS.
    """

    def __init__(self, session_factory, *, can_sender_factory=None, stop_lead_steps=100, status_poll_s=0.05):
        if (not callable(session_factory) or type(stop_lead_steps) is not int
                or not 1 <= stop_lead_steps <= 1000
                or type(status_poll_s) not in (int, float) or not 0.001 <= status_poll_s <= 1):
            raise ICDError("SCHEMA", "explicit bounded formal execution transport factory required")
        self._session_factory = session_factory
        if can_sender_factory is not None and not callable(can_sender_factory):
            raise ICDError("SCHEMA", "formal CANT sender factory must be callable")
        self._can_sender_factory = can_sender_factory
        self._stop_lead_steps = stop_lead_steps
        self._status_poll_s = status_poll_s
        self._active = {}
        self._lock = threading.Lock()

    @staticmethod
    def _applied(reply, message_id):
        if (type(reply) is not dict or reply.get("message_id") != 130
                or reply.get("payload", {}).get("request_message_id") != message_id
                or reply["payload"].get("stage") != "APPLIED"
                or reply["payload"].get("error") != "OK"):
            raise ICDError("BUSINESS_FAILED", "formal HIL request lacks an APPLIED receipt")
        return reply["payload"]

    @staticmethod
    def _correlation_refs(reply, session_id, reference):
        """Produce schema-bounded Record references from an actual receipt.

        Management Record has no separate session/transaction properties.
        These immutable reference IDs make the relation explicit without
        copying the raw transport exchange into the bounded API response.
        """
        transaction = (None if type(reply) is not dict else reply.get("header", {}).get("transaction_id"))
        if (type(session_id) is not int or not 1 <= session_id <= 0xffffffff
                or type(transaction) is not int or not 0 <= transaction <= 0xffffffff
                or type(reference) is not str or not reference):
            raise ICDError("STATE", "formal receipt lacks session/transaction correlation")
        return (reference, "session-" + str(session_id), "transaction-" + str(transaction))

    def _session(self, snapshot):
        from .session import SourceSession
        value = self._session_factory(snapshot)
        if not isinstance(value, SourceSession):
            raise ICDError("STATE", "formal execution factory must return an owned SourceSession")
        return value

    @staticmethod
    def _scenario_events(request, start_step):
        """Return fixed, direct CANT ID10 events from the frozen ScenarioSource."""
        inputs = request.get("source_inputs")
        scenario = None if type(inputs) is not dict else inputs.get("scenario")
        if scenario is None:
            return ()
        if type(scenario) is not dict or type(scenario.get("events")) is not list:
            raise ICDError("RESOURCE", "frozen Run ScenarioSource is incomplete")
        events = []
        for event in scenario["events"]:
            if type(event) is not dict or type(event.get("type")) is not str:
                raise ICDError("RESOURCE", "frozen ScenarioSource event is invalid")
            if event["type"] == "END_CLEANUP":
                continue
            stimulus = event.get("stimulus")
            if (event["type"] != "SEND" or event.get("link_id") != "CANT"
                    or type(event.get("at_step")) is not int or event["at_step"] < 1
                    or type(event.get("event_id")) is not str or not event["event_id"]
                    or type(stimulus) is not dict or stimulus.get("message_id") != 10):
                raise ICDError("TARGET_MISSING", "scenario needs an uninstalled original action driver")
            events.append((start_step + event["at_step"], event["event_id"], copy.deepcopy(stimulus)))
        return tuple(sorted(events))

    def request_stop(self, operation_id):
        with self._lock:
            event = self._active.get(operation_id)
        if event is None:
            raise ICDError("STATE", "formal execution operation is not active")
        event.set()

    def begin(self, operation_id, stop_requested):
        if type(operation_id) is not str or not isinstance(stop_requested, threading.Event):
            raise ICDError("SCHEMA", "formal execution needs original operation cancellation state")
        with self._lock:
            if operation_id in self._active:
                raise ICDError("STATE", "formal execution operation was already registered")
            self._active[operation_id] = stop_requested

    def _stop_hil(self, source, started, session_id, reporter):
        """Apply and read back a real safe STOP for a started execution."""
        status = source.heartbeat(started["applied_step"], target_step=started["applied_step"])
        payload = status["payload"]
        if payload["state"] != "RUNNING":
            raise ICDError("STATE", "actual HIL is not RUNNING at STOP request")
        stop_step = payload["model_step"] + self._stop_lead_steps
        stop_reply = source.request({"message_id": 4, "payload": {
            "action": "STOP", "expected_state": "RUNNING", "reset_policy": "NOT_APPLICABLE"}},
            target_step=stop_step)
        self._applied(stop_reply, 4)
        stop_refs = self._correlation_refs(stop_reply, session_id, "lifecycle-stop-applied")
        reporter.record("RESPONSE", "HIL_STOP_APPLIED", message_id="4", evidence_refs=stop_refs)
        stopped = source.heartbeat(stop_step, target_step=stop_step)
        if (stopped["payload"]["state"] != "STOPPED"
                or stopped["payload"]["control_source"] != "NONE"
                or stopped["payload"]["model_step"] != stop_step):
            raise ICDError("BUSINESS_FAILED", "HIL STOP lacks direct stopped/safe status evidence")
        return stop_refs

    def execute(self, snapshot, reporter, stop_requested):
        if not hasattr(snapshot, "create_snapshot") or type(snapshot.create_snapshot) is not bytes:
            raise ICDError("STATE", "original persisted Run execution snapshot required")
        # STOP can race the newly-created worker before it obtains any source
        # resource.  In that case there is no remote lifecycle effect to
        # confirm or compensate: keep the service's STOP_REQUESTED fact and
        # terminate locally without opening a Session or transmitting a
        # RunConfigure/START pair.
        if stop_requested.is_set():
            reporter.completed("INCOMPLETE", ("local-stop-before-session",))
            return
        source = self._session(snapshot)
        can_sender = None
        started = None
        session_id = None
        try:
            if stop_requested.is_set():
                reporter.completed("INCOMPLETE", ("local-stop-before-session",))
                return
            request = loads(snapshot.create_snapshot)
            configuration = request.get("run_configuration")
            if type(configuration) is not dict:
                raise ICDError("STATE", "persisted Run lacks its frozen RunConfigure")
            opened = source.open()
            if stop_requested.is_set():
                reporter.completed("INCOMPLETE", ("session-open", "local-stop-before-configure"))
                return
            caps = source.capabilities
            if (3 not in caps["implemented_message_ids"] or 4 not in caps["implemented_message_ids"]
                    or 2 not in caps["implemented_message_ids"]
                    or "consumer.RunConfigure" not in caps["available_probes"]
                    or "consumer.Lifecycle" not in caps["available_probes"]):
                raise ICDError("TARGET_MISSING", "formal HIL lacks required configuration/lifecycle/status consumers")
            initial_step = opened["header"]["target_step"]
            configured_reply = source.request(
                {"message_id": 3, "payload": copy.deepcopy(configuration)}, target_step=initial_step)
            configured = self._applied(configured_reply, 3)
            start_step = configured["applied_step"]
            # A concurrent STOP after same-configuration verification but
            # before START must not turn a cancelled management operation into
            # a target execution.  RunConfigure is a readback-only operation
            # for this prepared target, so local completion is still the only
            # truthful terminal fact here.
            if stop_requested.is_set():
                reporter.completed("INCOMPLETE", ("session-open", "run-configure-applied",
                                                   "local-stop-before-start"))
                return
            started_reply = source.request({"message_id": 4, "payload": {
                "action": "START", "expected_state": "CONFIGURED", "reset_policy": "NOT_APPLICABLE"}},
                target_step=start_step)
            started = self._applied(started_reply, 4)
            session_id = source.session_id
            configure_refs = self._correlation_refs(configured_reply, session_id, "run-configure-applied")
            start_refs = self._correlation_refs(started_reply, session_id, "lifecycle-start-applied")
            reporter.running(("session-open", "session-" + str(session_id), *configure_refs, *start_refs))
            events = list(self._scenario_events(request, started["applied_step"]))
            if events:
                if self._can_sender_factory is None:
                    raise ICDError("TARGET_MISSING", "scenario requires an installed original CANT sender")
                can_sender, _book, _token = self._can_sender_factory(source, request)
            evidence = ["lifecycle-stop-applied"]
            # Associate the RunExecutor's operation only after formal START is
            # evidence-backed; an early STOP cannot be mistaken for a target
            # lifecycle request before the model was running.
            while not stop_requested.wait(self._status_poll_s):
                status = source.heartbeat(started["applied_step"], target_step=started["applied_step"])
                if status["payload"]["state"] != "RUNNING":
                    raise ICDError("STATE", "actual HIL left RUNNING before requested STOP")
                current = status["payload"]["model_step"]
                # Keep a bounded lead: the C-core accepts target steps only
                # within its published look-ahead window, and the immutable
                # ID10 validity period begins at transmission.  Status is
                # read from the actual C-core, not the management Run view.
                while events and 0 < events[0][0] - current <= self._stop_lead_steps:
                    target, event_id, stimulus = events.pop(0)
                    if target <= current:
                        raise ICDError("TIMEOUT", "scenario target boundary was missed; no catch-up")
                    plan = can_sender.builder.prepare(can_sender.reservation, stimulus, can_sender.binding,
                                                      target_step=target)
                    can_sender.send(plan)
                    # The formal C-core returns the standard RECEIVED receipt
                    # before its consumer-owned APPLIED receipt.  A CAN plan
                    # retains that context until a terminal reply, so consume
                    # the bounded pair rather than mistaking RECEIVED for the
                    # final scenario outcome.
                    applied_reply = None
                    for _ in range(3):
                        reply = can_sender.receive_for(plan)
                        if reply.get("message_id") == 130 and reply.get("payload", {}).get("stage") == "RECEIVED":
                            continue
                        applied_reply = reply
                        break
                    if applied_reply is None:
                        raise ICDError("TIMEOUT", "CANT scenario lacks a terminal application receipt")
                    applied = self._applied(applied_reply, 10)
                    if applied["applied_step"] != target:
                        raise ICDError("BUSINESS_FAILED", "scenario model input applied at another boundary")
                    reference = "scenario-" + event_id + "-applied"
                    # SourceSession retained the original request/TX/RX before
                    # returning this APPLIED receipt; do not write a TX fact
                    # for a merely planned stimulus.
                    tx_refs = self._correlation_refs(applied_reply, session_id, "scenario-" + event_id + "-tx")
                    applied_refs = self._correlation_refs(applied_reply, session_id, reference)
                    reporter.record("TX", "SCENARIO_INPUT_TX", message_id="10", event_id=event_id,
                                    link_id="CANT", evidence_refs=tx_refs)
                    reporter.record("APPLIED", "SCENARIO_INPUT_APPLIED", message_id="10",
                                    input_event_id=event_id, event_id=event_id, link_id="CANT",
                                    step_index=str(target), sim_time_us=str(target * 1000),
                                    applied_values=copy.deepcopy(stimulus["payload"]),
                                    applied_mapping_ids=tuple("quadrotor_hil.input.environment." + key
                                                              for key in sorted(stimulus["payload"])),
                                    evidence_refs=applied_refs)
                    evidence.extend(applied_refs)
            stop_refs = self._stop_hil(source, started, session_id, reporter)
            evidence.extend(stop_refs)
            evidence.append("status-stopped-safe")
            reporter.completed("INCOMPLETE", tuple(evidence))
        except ICDError as failure:
            # A failed CANT input (including local capacity exhaustion) occurs
            # after the HIL has already been started.  Do not leave that model
            # running merely because this Run can no longer offer a STOP action.
            # The failure is still reported to management only after a direct
            # STOPPED/NONE readback, or with the original failure if the
            # compensating STOP itself cannot be confirmed.
            if started is not None:
                try:
                    self._stop_hil(source, started, session_id, reporter)
                except ICDError:
                    pass
            raise failure
        finally:
            with self._lock:
                for key, value in tuple(self._active.items()):
                    if value is stop_requested:
                        del self._active[key]
            try:
                if can_sender is not None:
                    can_sender.close()
            finally:
                pass
            try:
                source.close()
            finally:
                close = getattr(source.transport, "close", None)
                if callable(close):
                    close()
