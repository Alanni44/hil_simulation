"""Side-effect-free CREATE/GET management service for the input simulator."""

import copy
import datetime
import secrets
import threading
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from input_simulator.run_store import RunStore


SUPPORTED_COMMANDS = frozenset({
    "simulator_run_create", "simulator_run_get", "simulator_run_control", "simulator_records_list",
})

_ERROR_CODES = {
    "BASELINE": "BASELINE_MISMATCH", "HASH": "HASH_MISMATCH",
    "REFERENCE": "REFERENCE_INVALID", "MODEL": "MODEL_MAPPING_MISSING",
    "RESOURCE": "RESOURCE_INVALID", "CAPACITY": "QUOTA_EXCEEDED",
    "STATE": "STATE_CONFLICT", "CONTROL_CONFLICT": "CONTROL_CONFLICT",
    "VERSION_CONFLICT": "VERSION_CONFLICT", "TARGET_MISSING": "TOOL_UNAVAILABLE",
    "IDEMPOTENCY_CONFLICT": "IDEMPOTENCY_CONFLICT", "NOT_FOUND": "NOT_FOUND",
    "UNSUPPORTED": "OPERATION_NOT_ALLOWED", "SCHEMA": "INVALID_REQUEST",
    "TIMEOUT": "TIMEOUT", "EVIDENCE_INCOMPLETE": "EVIDENCE_INCOMPLETE",
    "BUFFER_FULL": "QUOTA_EXCEEDED", "STALE_SESSION": "TIMEOUT",
    "BUSINESS_FAILED": "EVIDENCE_INCOMPLETE", "AUTHORIZATION": "FORBIDDEN",
}

# A Record's public vocabulary has no dedicated HIL-fault kind.  Preserve the
# failure owner in the kind/reason pair instead of collapsing every execution
# failure into TOOL_ERROR.  The Run's schema-valid last_error remains the
# management-facing normalized code.
_HIL_FAILURE_CODES = frozenset({"AUTHORIZATION", "BUSINESS_FAILED", "MODEL", "STATE",
                                "TARGET_MISSING"})
_EVIDENCE_FAILURE_CODES = frozenset({"TIMEOUT", "EVIDENCE_INCOMPLETE", "STALE_SESSION",
                                     "BUFFER_FULL"})


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SimulatorRunService:
    """Management dispatcher that cannot open a Session or contact a HIL.

    START and every transport/HIL dependency are intentionally absent here.  A
    later executor receives only the persisted, audited snapshot.
    """

    def __init__(self, management, template, *, store=None, executor=None, clock=_utc_now,
                 run_id_factory=None, operation_id_factory=None):
        if (not callable(getattr(management, "validate_request", None))
                or not callable(getattr(management, "validate_response", None))
                or not hasattr(management, "contract")
                or not callable(clock)):
            raise ICDError("STATE", "verified management contract and clock required")
        if not isinstance(store, RunStore) and store is not None:
            raise ICDError("STATE", "original RunStore required")
        self.management = management
        self.template = template
        self.store = RunStore() if store is None else store
        if executor is not None:
            from input_simulator.run_executor import RunExecutor
            if not isinstance(executor, RunExecutor):
                raise ICDError("STATE", "original RunExecutor required")
        self.executor = executor
        self._clock = clock
        self._run_id_factory = run_id_factory or (lambda: "run-" + secrets.token_hex(12))
        self._operation_id_factory = operation_id_factory or (lambda: "operation-" + secrets.token_hex(12))
        self._active_operations = {}
        self._operation_lock = threading.Lock()

    def _timestamp(self):
        value = self._clock()
        if type(value) is not str:
            raise ICDError("STATE", "management clock must return a UTC string")
        self.management.validate_definition("UtcTime", value)
        return value

    def _response(self, request, *, status, code, message, data=None, error=None, operation_id=None):
        response = {
            "kind": "RESPONSE", "api_version": "0.3",
            "request_id": request["params"]["request_id"], "cmd": request["cmd"],
            "status": status, "code": code, "message": message[:1024],
            "timestamp": self._timestamp(), "operation_id": operation_id,
            "data": data, "error": error,
        }
        self.management.validate_response(response)
        return response

    def _failure(self, request, error):
        code = _ERROR_CODES.get(error.code, "INTERNAL_ERROR")
        return self._response(
            request, status="REJECTED", code=code, message=error.detail,
            error={"code": code, "retryable": False, "details": []})

    def _new_run(self, params):
        run_id = self._run_id_factory()
        if type(run_id) is not str:
            raise ICDError("STATE", "Run ID factory returned a non-string")
        self.management.validate_definition("Id", run_id)
        timestamp = self._timestamp()
        links = [{"link_id": link_id, "tx_frames": "0", "rx_frames": "0",
                  "rejected_inputs": "0", "tool_state": "IDLE"}
                 for link_id in self.template.link_ids]
        return {
            "run_id": run_id, "revision": "1", "mode": self.template.mode,
            "profile_ref": copy.deepcopy(self.template.profile_ref),
            "scenario_ref": copy.deepcopy(self.template.scenario_ref),
            "source_binding_ref": self.template.source_binding_ref,
            "state": "READY", "result": "NOT_RUN", "available_actions": ["START"],
            "stats": {"tx_frames": "0", "rx_frames": "0", "received_inputs": "0",
                      "applied_inputs": "0", "rejected_inputs": "0"},
            "evidence_complete": False, "last_error": None,
            "created_at": timestamp, "updated_at": timestamp,
            "package_ref": copy.deepcopy(self.template.package_ref),
            "link_ids": copy.deepcopy(self.template.link_ids),
            "clock_domain_id": self.template.clock_domain_id,
            "sim_time_us": "0", "step_index": "0", "active_event_id": None,
            "link_stats": links,
        }

    def _create(self, request):
        params = request["params"]
        self.template.verify_create(params, baseline_sha256=self.management.contract.baseline_sha256)
        audit = self.template.audit(self.management.contract)
        run = self._new_run(params)
        self.management.validate_definition("Run", run)
        self.store.create(
            run, create_snapshot=canonicalize(params), source_snapshot=audit.input_json,
            resource_evidence=audit.resources)
        # The frozen v0.3 API fixes the CREATE success envelope at
        # VALIDATING/NOT_RUN even when this bounded implementation completes
        # its offline audit synchronously.  Persist the actual READY Run, and
        # retain this contract-mandated acknowledgement as the idempotent
        # CREATE response; GET exposes the ready snapshot.
        acknowledgement = copy.deepcopy(run)
        acknowledgement["state"] = "VALIDATING"
        self.management.validate_definition("Run", acknowledgement)
        return self._response(
            request, status="SUCCESS", code="OK",
            message="Run validation accepted; query Run for ready snapshot", data=acknowledgement)

    def _get(self, request):
        run = self.store.get(request["params"]["run_id"])
        self.management.validate_definition("Run", run)
        return self._response(request, status="SUCCESS", code="OK", message="Run found", data=run)

    def append_record(self, record):
        """Retain one producer fact after validating its public Record shape."""
        self.management.validate_definition("Record", record)
        return self.store.append_record(record["run_id"], record)

    def _record_fact(self, run_id, *, kind, reason_code, operation_id=None,
                     message_id=None, evidence_refs=(), event_id=None, link_id=None,
                     operation_result=None, input_event_id=None, step_index=None,
                     sim_time_us=None, applied_values=None, applied_mapping_ids=None):
        """Persist a bounded management fact; never turn missing evidence into success."""
        if (kind not in {"TX", "RX", "RECEIVED", "APPLIED", "REJECTED", "RESPONSE", "SAFETY",
                         "TOOL_ERROR", "OPERATION_RESULT"}
                or type(reason_code) is not str or type(evidence_refs) not in (tuple, list)):
            raise ICDError("SCHEMA", "strict management evidence fact required")
        fact = {
            "input_event_id": None, "operation_id": operation_id, "kind": kind,
            "timestamp": self._timestamp(), "clock_domain": self.template.clock_domain_id,
            "monotonic_us": str(time.monotonic_ns() // 1000), "message_id": message_id,
            "reason_code": reason_code[:128], "evidence_refs": list(evidence_refs),
            "event_id": event_id, "link_id": link_id,
        }
        if kind == "APPLIED":
            fact.update(input_event_id=input_event_id, step_index=step_index,
                        sim_time_us=sim_time_us, applied_values=applied_values,
                        applied_mapping_ids=list(applied_mapping_ids or ()))
        if operation_result is not None:
            if kind != "OPERATION_RESULT" or operation_result not in {"SUCCEEDED", "FAILED"}:
                raise ICDError("SCHEMA", "strict terminal management operation result required")
            fact["operation_result"] = operation_result
        record = self.store.append_fact(run_id, fact)
        self.management.validate_definition("Record", record)
        return record

    def _records_list(self, request):
        params = request["params"]
        page = self.store.list_records(
            params["run_id"], after_cursor=params.get("after_cursor"), limit=params.get("limit", 100))
        self.management.validate_definition("RecordPage", page)
        return self._response(request, status="SUCCESS", code="OK", message="Records found", data=page)

    @staticmethod
    def _next_revision(value):
        revision = int(value)
        if revision >= 2**64 - 1:
            raise ICDError("CAPACITY", "Run revision has reached uint64 capacity")
        return str(revision + 1)

    def _transition(self, run_id, *, allowed_states, mutate):
        """Apply one schema-checked CAS transition; callbacks never infer HIL state."""
        for _attempt in range(4):
            current = self.store.get(run_id)
            if current["state"] not in allowed_states:
                return None
            replacement = copy.deepcopy(current)
            mutate(replacement)
            replacement["revision"] = self._next_revision(current["revision"])
            replacement["updated_at"] = self._timestamp()
            self.management.validate_definition("Run", replacement)
            try:
                return self.store.replace_run(run_id, current["revision"], replacement)
            except ICDError as error:
                if error.code != "VERSION_CONFLICT":
                    raise
        raise ICDError("VERSION_CONFLICT", "Run changed repeatedly during the requested transition")

    def _backend_failure(self, run_id, code, detail, evidence_refs=(), operation_id=None):
        mapped = _ERROR_CODES.get(code, "INTERNAL_ERROR")

        def failed(run):
            run.update(state="FAILED", result="FAIL", available_actions=[], evidence_complete=False,
                       last_error={"code": mapped, "retryable": False, "details": []})

        result = self._transition(run_id, allowed_states={"WAITING", "RUNNING", "STOPPING"}, mutate=failed)
        if result is not None:
            with self._operation_lock:
                self._active_operations.pop(run_id, None)
            if code in _HIL_FAILURE_CODES:
                kind, reason = "REJECTED", "HIL_" + code
            elif code in _EVIDENCE_FAILURE_CODES:
                kind, reason = "REJECTED", "EVIDENCE_" + code
            else:
                kind, reason = "TOOL_ERROR", "TOOL_" + mapped
            self._record_fact(run_id, kind=kind, reason_code=reason,
                              operation_id=operation_id, evidence_refs=evidence_refs)
            self._record_fact(run_id, kind="OPERATION_RESULT", reason_code="EXECUTION_FAILED",
                              operation_id=operation_id, evidence_refs=evidence_refs,
                              operation_result="FAILED")
            self.store.release_reserved_records(run_id)
        return result

    def _control(self, request):
        params = request["params"]
        run_id, expected, action = params["run_id"], params["expected_revision"], params["action"]
        current = self.store.get(run_id)
        if current["revision"] != expected:
            raise ICDError("VERSION_CONFLICT", "Run revision differs from the control request")
        if action == "START":
            if self.executor is None:
                raise ICDError("TARGET_MISSING", "START requires an installed actual HIL execution backend")
            if current["state"] != "READY" or current["available_actions"] != ["START"]:
                raise ICDError("STATE", "START is not available for this Run")
            operation_id = self._operation_id_factory()
            self.management.validate_definition("Id", operation_id)
            scenario = self.template.source_inputs.get("scenario")
            event_count = (0 if scenario is None else sum(
                event.get("type") == "SEND" and event.get("link_id") == "CANT"
                for event in scenario.get("events", ())))
            # START/RUNNING/local STOP/HIL STOP/terminal plus TX+APPLIED for
            # each permitted
            # ScenarioSource event. Reserve before changing Run state or
            # opening a Session so evidence exhaustion cannot follow an effect.
            self.store.reserve_records(run_id, 5 + 2 * event_count)

            def queued(run):
                run.update(state="WAITING", result="RUNNING", available_actions=["STOP"])

            queued_run = self._transition(run_id, allowed_states={"READY"}, mutate=queued)
            if queued_run is None:
                raise ICDError("VERSION_CONFLICT", "Run changed before START could be queued")
            snapshot = self.store.execution_snapshot(run_id)

            def running(_evidence_refs):
                def apply(run):
                    run.update(state="RUNNING", result="RUNNING", available_actions=["STOP"])
                if self._transition(run_id, allowed_states={"WAITING"}, mutate=apply) is not None:
                    self._record_fact(run_id, kind="RESPONSE", reason_code="HIL_START_APPLIED",
                                      operation_id=operation_id, evidence_refs=_evidence_refs)

            def completed(result, evidence_refs):
                def finish(run):
                    run.update(state="COMPLETED", result=result, available_actions=[],
                               evidence_complete=(result == "PASS"), last_error=None)
                if self._transition(run_id, allowed_states={"WAITING", "RUNNING", "STOPPING"}, mutate=finish) is not None:
                    with self._operation_lock:
                        self._active_operations.pop(run_id, None)
                    self._record_fact(run_id, kind="OPERATION_RESULT", reason_code="EXECUTION_" + result,
                                      operation_id=operation_id, evidence_refs=evidence_refs,
                                      operation_result="SUCCEEDED" if result == "PASS" else "FAILED")
                    self.store.release_reserved_records(run_id)

            def record(kind, reason_code, **fields):
                self._record_fact(run_id, kind=kind, reason_code=reason_code,
                                  operation_id=operation_id, **fields)

            try:
                with self._operation_lock:
                    self._active_operations[run_id] = operation_id
                # Retain management acceptance before starting the worker: a
                # fast real START callback must never precede its QUEUED fact.
                self._record_fact(run_id, kind="RESPONSE", reason_code="START_QUEUED", operation_id=operation_id)
                self.executor.submit(operation_id, snapshot, on_running=running,
                                     on_completed=completed,
                                     on_failed=lambda code, detail, evidence: self._backend_failure(
                                         run_id, code, detail, evidence, operation_id), on_record=record)
            except ICDError as error:
                self._backend_failure(run_id, error.code, error.detail, operation_id=operation_id)
                raise
            return self._response(request, status="ACCEPTED", code="QUEUED", message="START queued",
                                  data=queued_run, error=None, operation_id=operation_id)
        if action == "STOP":
            if self.executor is None:
                raise ICDError("TARGET_MISSING", "STOP requires an installed actual HIL execution backend")
            if current["state"] not in {"WAITING", "RUNNING"} or "STOP" not in current["available_actions"]:
                raise ICDError("STATE", "STOP is not available for this Run")
            with self._operation_lock:
                active = self._active_operations.get(run_id)
            if active is None:
                raise ICDError("STATE", "Run has no active execution operation")
            operation_id = self._operation_id_factory()
            self.management.validate_definition("Id", operation_id)

            def stopping(run):
                run.update(state="STOPPING", result="RUNNING", available_actions=[])

            stopping_run = self._transition(run_id, allowed_states={"WAITING", "RUNNING"}, mutate=stopping)
            if stopping_run is None:
                raise ICDError("VERSION_CONFLICT", "Run changed before STOP could be queued")
            # This is the local cancellation/dispatch fact.  Persist it before
            # the worker is signalled so a fast HIL STOP receipt can never be
            # ordered ahead of the caller's safe-stop request.
            self._record_fact(run_id, kind="SAFETY", reason_code="STOP_REQUESTED",
                              operation_id=operation_id)
            try:
                self.executor.request_stop(active)
            except ICDError as error:
                self._backend_failure(run_id, error.code, error.detail, operation_id=active)
                raise
            return self._response(request, status="ACCEPTED", code="QUEUED", message="STOP queued",
                                  data=stopping_run, error=None, operation_id=operation_id)
        raise ICDError("UNSUPPORTED", "only START and STOP are enabled by this minimal service")

    def handle(self, request):
        """Validate, execute CREATE/GET, and retain a byte-identical replay."""
        self.management.validate_request(request)
        request_id = request["params"]["request_id"]
        try:
            replay = self.store.replay(request_id, request)
        except ICDError as error:
            # A colliding key is a valid management rejection, but must never
            # replace the original request-id evidence.
            return self._failure(request, error)
        if replay is not None:
            return replay
        try:
            if request["cmd"] not in SUPPORTED_COMMANDS:
                raise ICDError("UNSUPPORTED", "management command is not enabled by this minimal service")
            if request["cmd"] == "simulator_run_create":
                response = self._create(request)
            elif request["cmd"] == "simulator_run_get":
                response = self._get(request)
            elif request["cmd"] == "simulator_run_control":
                response = self._control(request)
            else:
                response = self._records_list(request)
        except ICDError as error:
            response = self._failure(request, error)
        return self.store.remember(request_id, request, response)
