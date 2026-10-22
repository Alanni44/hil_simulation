import copy
import json
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
from pathlib import Path

from common import EXPECTED, INTERFACES, ROOT, GatewayTest


class SimulatorRunServiceTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_runtime.management import ManagementContract
        from input_simulator.run_service import SimulatorRunService
        from input_simulator.run_template import FixedRunTemplate

        self.management = ManagementContract.load(INTERFACES, contract=self.contract)
        self.create = json.loads(
            (INTERFACES / "input-simulator-v0.3.examples.json").read_text(encoding="utf-8"))["management_create_schema_fixture"]
        params = self.create["params"]
        self.template = FixedRunTemplate(
            model_id="quadrotor_hil",
            profile_ref={"profile_id": "minimal-profile", "version": "1",
                         "profile_hash": "8ddeeac31fad309043ed8d60f8f1aa585c749f65f34a1bc972a05b3f16bf38b2"},
            package_ref=params["package_ref"], scenario_ref=params["scenario_ref"],
            mode=params["mode"], source_binding_ref=params["source_binding_ref"],
            link_ids=params["link_ids"], run_configuration=params["run_configuration"],
            source_inputs=params["source_inputs"], resource_root=INTERFACES,
            clock_domain_id="SIMULATOR_MONOTONIC",
        )
        self._next_run = 0

        def next_run():
            self._next_run += 1
            return "run-test-{}".format(self._next_run)

        self.service = SimulatorRunService(
            self.management, self.template, clock=lambda: "2026-10-20T00:00:00Z",
            run_id_factory=next_run)

    def test_create_get_and_replay_are_schema_valid_without_hil_side_effects(self):
        created = self.service.handle(copy.deepcopy(self.create))
        self.management.validate_response(created)
        self.assertEqual(created["status"], "SUCCESS")
        self.assertEqual(created["data"]["state"], "VALIDATING")
        self.assertEqual(created["data"]["result"], "NOT_RUN")
        self.assertEqual(created["data"]["available_actions"], ["START"])
        self.assertEqual(self.service.store.run_count, 1)
        self.assertEqual(self.service.handle(copy.deepcopy(self.create)), created)
        self.assertEqual(self.service.store.run_count, 1)

        get = {"cmd": "simulator_run_get", "params": {
            "api_version": "0.3", "request_id": "get-01", "run_id": created["data"]["run_id"]}}
        found = self.service.handle(get)
        self.management.validate_response(found)
        self.assertEqual(found["data"]["state"], "READY")
        self.assertEqual(found["data"]["result"], "NOT_RUN")
        self.assertEqual(found["data"]["run_id"], created["data"]["run_id"])

    def test_template_baseline_and_active_run_conflicts_are_rejected_as_management_errors(self):
        mismatch = copy.deepcopy(self.create)
        mismatch["params"]["baseline_sha256"] = "0" * 64
        mismatch["params"]["request_id"] = "baseline-mismatch"
        rejected = self.service.handle(mismatch)
        self.assertEqual((rejected["status"], rejected["code"]), ("REJECTED", "BASELINE_MISMATCH"))
        self.assertEqual(self.service.store.run_count, 0)

        self.service.handle(copy.deepcopy(self.create))
        second = copy.deepcopy(self.create)
        second["params"]["request_id"] = "create-02"
        rejected = self.service.handle(second)
        self.assertEqual((rejected["status"], rejected["code"]), ("REJECTED", "CONTROL_CONFLICT"))

    def test_request_id_collision_never_reuses_or_creates_a_run(self):
        self.service.handle(copy.deepcopy(self.create))
        collision = copy.deepcopy(self.create)
        collision["params"]["mode"] = "FORMAL"
        response = self.service.handle(collision)
        self.management.validate_response(response)
        self.assertEqual((response["status"], response["code"]), ("REJECTED", "IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.service.store.run_count, 1)

    def test_resource_bytes_are_rechecked_below_template_root(self):
        from input_simulator.run_service import SimulatorRunService
        from input_simulator.run_template import FixedRunTemplate

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("input-simulator-icd-v0.3.json", "input-simulator-canfd-v0.3.dbc"):
                shutil.copy2(INTERFACES / name, root / name)
            (root / "input-simulator-canfd-v0.3.dbc").write_bytes(b"tampered")
            template = FixedRunTemplate(
                model_id=self.template.model_id, profile_ref=self.template.profile_ref,
                package_ref=self.template.package_ref, scenario_ref=self.template.scenario_ref,
                mode=self.template.mode, source_binding_ref=self.template.source_binding_ref,
                link_ids=self.template.link_ids, run_configuration=self.template.run_configuration,
                source_inputs=self.template.source_inputs, resource_root=root,
                clock_domain_id=self.template.clock_domain_id)
            service = SimulatorRunService(
                self.management, template, clock=lambda: "2026-10-20T00:00:00Z",
                run_id_factory=lambda: "run-tampered")
            response = service.handle(copy.deepcopy(self.create))
        self.assertEqual((response["status"], response["code"]), ("REJECTED", "RESOURCE_INVALID"))
        self.assertEqual(service.store.run_count, 0)

    def test_repository_minimal_template_loads_only_its_frozen_fixture_and_resource_root(self):
        from input_simulator.run_template import FixedRunTemplate

        template = FixedRunTemplate.load(ROOT / "config/minimal-integration-template.json")
        self.assertEqual(template.model_id, "quadrotor_hil")
        self.assertEqual(template.resource_root, INTERFACES)
        self.assertEqual(template.source_inputs, self.template.source_inputs)
        self.assertIsNone(template.run_configuration["terrain_resource_sha256"])
        self.assertIsNone(template.run_configuration["obstacle_resource_sha256"])

    def test_record_page_exposes_only_schema_valid_retained_facts(self):
        created = self.service.handle(copy.deepcopy(self.create))
        run_id = created["data"]["run_id"]
        record = {
            "record_id": "record-01", "cursor": "1", "run_id": run_id,
            "input_event_id": None, "operation_id": None, "kind": "SAFETY",
            "timestamp": "2026-10-20T00:00:00Z", "clock_domain": "SIMULATOR_MONOTONIC",
            "monotonic_us": "0", "message_id": None, "reason_code": "CREATE_AUDITED",
            "evidence_refs": [], "event_id": None, "link_id": None,
        }
        self.service.append_record(record)
        request = {"cmd": "simulator_records_list", "params": {
            "api_version": "0.3", "request_id": "records-01", "run_id": run_id, "limit": 100}}
        response = self.service.handle(request)
        self.management.validate_response(response)
        self.assertEqual(response["data"]["items"], [record])
        self.assertTrue(response["data"]["complete"])

    def test_start_is_refused_without_an_actual_hil_execution_backend(self):
        created = self.service.handle(copy.deepcopy(self.create))
        control = {"cmd": "simulator_run_control", "params": {
            "api_version": "0.3", "request_id": "start-without-backend",
            "run_id": created["data"]["run_id"], "expected_revision": "1", "action": "START"}}
        response = self.service.handle(control)
        self.assertEqual((response["status"], response["code"]), ("REJECTED", "TOOL_UNAVAILABLE"))

    def test_formal_execution_stop_before_worker_session_has_no_hil_side_effect(self):
        from input_simulator.run_executor import ExecutionReporter, FormalHILExecutionBackend

        opened = []
        backend = FormalHILExecutionBackend(lambda _snapshot: opened.append(True))
        stopped = threading.Event()
        stopped.set()
        completed, failed = [], []
        reporter = ExecutionReporter(running=lambda _refs: self.fail("early STOP cannot report RUNNING"),
                                     completed=lambda result, refs: completed.append((result, refs)),
                                     failed=lambda code, detail, refs: failed.append((code, detail, refs)))
        backend.begin("operation-early-stop", stopped)
        backend.execute(SimpleNamespace(create_snapshot=b"{}"), reporter, stopped)

        self.assertEqual(opened, [])
        self.assertEqual(completed, [("INCOMPLETE", ("local-stop-before-session",))])
        self.assertEqual(failed, [])

    def test_formal_execution_stop_after_configure_never_sends_lifecycle_start(self):
        from input_simulator.run_executor import ExecutionReporter, FormalHILExecutionBackend

        backend = FormalHILExecutionBackend(lambda _snapshot: self.fail("patched source is required"))
        stopped = threading.Event()
        requested = []
        source = SimpleNamespace(
            open=lambda: {"header": {"target_step": 0}},
            capabilities={"implemented_message_ids": [2, 3, 4],
                          "available_probes": ["consumer.RunConfigure", "consumer.Lifecycle"]},
            close=lambda: None,
            transport=SimpleNamespace(close=lambda: None),
        )

        def request(message, *, target_step):
            requested.append((message["message_id"], target_step))
            stopped.set()
            return {"message_id": 130, "payload": {"request_message_id": 3,
                    "stage": "APPLIED", "error": "OK", "applied_step": target_step}}

        source.request = request
        backend._session = lambda _snapshot: source
        completed, failed = [], []
        reporter = ExecutionReporter(running=lambda _refs: self.fail("cancelled execution cannot run"),
                                     completed=lambda result, refs: completed.append((result, refs)),
                                     failed=lambda code, detail, refs: failed.append((code, detail, refs)))
        backend.begin("operation-stop-after-configure", stopped)
        backend.execute(SimpleNamespace(create_snapshot=b'{"run_configuration": {}}'), reporter, stopped)

        self.assertEqual(requested, [(3, 0)])
        self.assertEqual(completed, [("INCOMPLETE", ("session-open", "run-configure-applied",
                                                       "local-stop-before-start"))])
        self.assertEqual(failed, [])

    def test_formal_execution_stop_during_session_open_never_sends_configure(self):
        from input_simulator.run_executor import ExecutionReporter, FormalHILExecutionBackend

        backend = FormalHILExecutionBackend(lambda _snapshot: self.fail("patched source is required"))
        stopped = threading.Event()
        source = SimpleNamespace(
            close=lambda: None,
            request=lambda *args, **kwargs: self.fail("cancelled execution cannot configure"),
            transport=SimpleNamespace(close=lambda: None),
        )

        def open_session():
            stopped.set()
            return {"header": {"target_step": 0}}

        source.open = open_session
        backend._session = lambda _snapshot: source
        completed, failed = [], []
        reporter = ExecutionReporter(running=lambda _refs: self.fail("cancelled execution cannot run"),
                                     completed=lambda result, refs: completed.append((result, refs)),
                                     failed=lambda code, detail, refs: failed.append((code, detail, refs)))
        backend.begin("operation-stop-during-open", stopped)
        backend.execute(SimpleNamespace(create_snapshot=b'{"run_configuration": {}}'), reporter, stopped)

        self.assertEqual(completed, [("INCOMPLETE", ("session-open", "local-stop-before-configure"))])
        self.assertEqual(failed, [])

    def test_actual_backend_evidence_drives_start_stop_transitions(self):
        from input_simulator.run_executor import RunExecutionBackend, RunExecutor
        from input_simulator.run_service import SimulatorRunService

        started, stopped = threading.Event(), threading.Event()

        class EvidenceBackend(RunExecutionBackend):
            def execute(self, snapshot, reporter, stop_requested):
                self.snapshot = snapshot
                reporter.running(("hil-start-ack",))
                started.set()
                stop_requested.wait(2)
                reporter.record("RESPONSE", "HIL_STOP_APPLIED", message_id="4",
                                evidence_refs=("hil-stop-ack",))
                reporter.completed("INCOMPLETE", ("hil-stop-ack",))

            def request_stop(self, operation_id):
                self.stop_operation = operation_id
                stopped.set()

        backend = EvidenceBackend()
        ids = iter(("operation-start", "operation-stop"))
        service = SimulatorRunService(
            self.management, self.template, executor=RunExecutor(backend),
            clock=lambda: "2026-10-20T00:00:00Z", run_id_factory=lambda: "run-evidence",
            operation_id_factory=lambda: next(ids))
        created = service.handle(copy.deepcopy(self.create))
        run_id = created["data"]["run_id"]
        start = {"cmd": "simulator_run_control", "params": {
            "api_version": "0.3", "request_id": "evidence-start", "run_id": run_id,
            "expected_revision": "1", "action": "START"}}
        accepted = service.handle(start)
        self.management.validate_response(accepted)
        self.assertEqual((accepted["status"], accepted["operation_id"]), ("ACCEPTED", "operation-start"))
        self.assertTrue(started.wait(2))
        deadline = time.monotonic() + 2
        while service.store.get(run_id)["state"] != "RUNNING" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(service.store.get(run_id)["state"], "RUNNING")
        stop = {"cmd": "simulator_run_control", "params": {
            "api_version": "0.3", "request_id": "evidence-stop", "run_id": run_id,
            "expected_revision": service.store.get(run_id)["revision"], "action": "STOP"}}
        self.assertEqual(service.handle(stop)["status"], "ACCEPTED")
        self.assertTrue(stopped.wait(2))
        deadline = time.monotonic() + 2
        while service.store.get(run_id)["state"] != "COMPLETED" and time.monotonic() < deadline:
            time.sleep(.01)
        finished = service.store.get(run_id)
        self.assertEqual((finished["state"], finished["result"]), ("COMPLETED", "INCOMPLETE"))
        self.assertEqual(backend.snapshot.run["run_id"], run_id)
        records = service.store.list_records(run_id, limit=100)["items"]
        self.assertEqual([record["cursor"] for record in records], ["1", "2", "3", "4", "5"])
        self.assertEqual([record["reason_code"] for record in records], [
            "START_QUEUED", "HIL_START_APPLIED", "STOP_REQUESTED", "HIL_STOP_APPLIED",
            "EXECUTION_INCOMPLETE"])
        self.assertEqual(records[1]["evidence_refs"], ["hil-start-ack"])
        self.assertEqual(records[-1]["evidence_refs"], ["hil-stop-ack"])
        self.assertEqual((records[-1]["kind"], records[-1]["operation_result"]),
                         ("OPERATION_RESULT", "FAILED"))

    def test_formal_execution_stop_is_bound_to_its_registered_operation(self):
        from input_simulator.run_executor import FormalHILExecutionBackend

        backend = FormalHILExecutionBackend(lambda snapshot: None)
        cancellation = threading.Event()
        backend.begin("operation-formal", cancellation)
        backend.request_stop("operation-formal")
        self.assertTrue(cancellation.is_set())
        self.rejects("STATE", lambda: backend.request_stop("operation-missing"))

    def test_formal_executor_accepts_only_fixed_cant_environment_scenario_events(self):
        from input_simulator.run_executor import FormalHILExecutionBackend

        request = copy.deepcopy(self.create["params"])
        request["source_inputs"]["scenario"]["events"][0]["link_id"] = "CANT"
        events = FormalHILExecutionBackend._scenario_events(request, 10)
        self.assertEqual([(step, event_id, stimulus["message_id"])
                          for step, event_id, stimulus in events], [(260, "wind-step-01", 10)])
        changed = copy.deepcopy(request)
        changed["source_inputs"]["scenario"]["events"][0]["link_id"] = "ETHGEN"
        self.rejects("TARGET_MISSING", lambda: FormalHILExecutionBackend._scenario_events(changed, 10))

    def test_formal_receipt_references_bind_record_to_actual_session_and_transaction(self):
        from input_simulator.run_executor import FormalHILExecutionBackend

        self.assertEqual(FormalHILExecutionBackend._correlation_refs(
            {"header": {"transaction_id": 42}}, 9, "scenario-wind-step-01-applied"),
            ("scenario-wind-step-01-applied", "session-9", "transaction-42"))
        self.rejects("STATE", lambda: FormalHILExecutionBackend._correlation_refs(
            {"header": {}}, 9, "receipt"))

    def test_applied_scenario_record_keeps_model_step_values_and_mapping_ids(self):
        created = self.service.handle(copy.deepcopy(self.create))
        run_id = created["data"]["run_id"]
        record = self.service._record_fact(
            run_id, kind="APPLIED", reason_code="SCENARIO_INPUT_APPLIED", operation_id="operation-01",
            message_id="10", input_event_id="wind-step-01", event_id="wind-step-01", link_id="ETHGEN",
            step_index="250", sim_time_us="250000", applied_values={"wind_n_mps": 1},
            applied_mapping_ids=("quadrotor_hil.input.environment.wind_n_mps",),
            evidence_refs=("scenario-wind-step-01-applied",))
        self.assertEqual((record["kind"], record["step_index"], record["applied_values"]),
                         ("APPLIED", "250", {"wind_n_mps": 1}))

    def test_start_reserves_all_scenario_evidence_before_worker_or_state_change(self):
        from input_simulator.run_executor import RunExecutionBackend, RunExecutor
        from input_simulator.run_service import SimulatorRunService
        from input_simulator.run_store import RunStore

        class NeverStarted(RunExecutionBackend):
            def execute(self, *_args):
                raise AssertionError("worker must not start without evidence capacity")
            def request_stop(self, _operation_id):
                raise AssertionError("worker must not start without evidence capacity")

        service = SimulatorRunService(
            self.management, self.template, store=RunStore(max_records_per_run=1),
            executor=RunExecutor(NeverStarted()), clock=lambda: "2026-10-20T00:00:00Z",
            run_id_factory=lambda: "run-reservation", operation_id_factory=lambda: "operation-reservation")
        created = service.handle(copy.deepcopy(self.create))
        response = service.handle({"cmd": "simulator_run_control", "params": {
            "api_version": "0.3", "request_id": "reservation-start", "run_id": created["data"]["run_id"],
            "expected_revision": "1", "action": "START"}})
        self.assertEqual((response["status"], response["code"]), ("REJECTED", "QUOTA_EXCEEDED"))
        self.assertEqual(service.store.get(created["data"]["run_id"])["state"], "READY")

    def test_execution_failure_records_preserve_hil_evidence_and_tool_failure_origins(self):
        from icd_runtime.errors import ICDError
        from input_simulator.run_executor import RunExecutionBackend, RunExecutor
        from input_simulator.run_service import SimulatorRunService

        cases = (
            ("BUSINESS_FAILED", "REJECTED", "HIL_BUSINESS_FAILED", "EVIDENCE_INCOMPLETE"),
            ("TIMEOUT", "REJECTED", "EVIDENCE_TIMEOUT", "TIMEOUT"),
            ("INTERNAL_ERROR", "TOOL_ERROR", "TOOL_INTERNAL_ERROR", "INTERNAL_ERROR"),
        )
        for index, (code, kind, reason, public_code) in enumerate(cases):
            with self.subTest(code=code):
                class FailedBackend(RunExecutionBackend):
                    def execute(self, _snapshot, _reporter, _stop_requested):
                        raise ICDError(code, "controlled " + code)

                    def request_stop(self, _operation_id):
                        raise AssertionError("failed execution has no active STOP")

                service = SimulatorRunService(
                    self.management, self.template, executor=RunExecutor(FailedBackend()),
                    clock=lambda: "2026-10-20T00:00:00Z",
                    run_id_factory=lambda: "run-failure-{}".format(index),
                    operation_id_factory=lambda: "operation-failure-{}".format(index))
                created = service.handle(copy.deepcopy(self.create))
                run_id = created["data"]["run_id"]
                response = service.handle({"cmd": "simulator_run_control", "params": {
                    "api_version": "0.3", "request_id": "failure-start-{}".format(index),
                    "run_id": run_id, "expected_revision": "1", "action": "START"}})
                self.assertEqual(response["status"], "ACCEPTED")
                deadline = time.monotonic() + 2
                while service.store.get(run_id)["state"] != "FAILED" and time.monotonic() < deadline:
                    time.sleep(.01)
                failed = service.store.get(run_id)
                self.assertEqual((failed["state"], failed["last_error"]["code"]),
                                 ("FAILED", public_code))
                records = service.store.list_records(run_id, limit=100)["items"]
                self.assertEqual([(item["kind"], item["reason_code"]) for item in records], [
                    ("RESPONSE", "START_QUEUED"), (kind, reason),
                    ("OPERATION_RESULT", "EXECUTION_FAILED")])
                self.assertEqual(records[-1]["operation_result"], "FAILED")

    def test_assertion_failure_is_a_completed_fail_not_a_hil_or_tool_error(self):
        from input_simulator.run_executor import RunExecutionBackend, RunExecutor
        from input_simulator.run_service import SimulatorRunService

        class AssertionBackend(RunExecutionBackend):
            def execute(self, _snapshot, reporter, _stop_requested):
                reporter.running(("hil-start-ack",))
                reporter.completed("FAIL", ("assertion-wind-boundary",))

            def request_stop(self, _operation_id):
                raise AssertionError("completed assertion cannot be stopped")

        service = SimulatorRunService(
            self.management, self.template, executor=RunExecutor(AssertionBackend()),
            clock=lambda: "2026-10-20T00:00:00Z", run_id_factory=lambda: "run-assertion",
            operation_id_factory=lambda: "operation-assertion")
        created = service.handle(copy.deepcopy(self.create))
        run_id = created["data"]["run_id"]
        response = service.handle({"cmd": "simulator_run_control", "params": {
            "api_version": "0.3", "request_id": "assertion-start", "run_id": run_id,
            "expected_revision": "1", "action": "START"}})
        self.assertEqual(response["status"], "ACCEPTED")
        deadline = time.monotonic() + 2
        while ((service.store.get(run_id)["state"] != "COMPLETED"
                or len(service.store.list_records(run_id, limit=100)["items"]) != 3)
               and time.monotonic() < deadline):
            time.sleep(.01)
        run = service.store.get(run_id)
        self.assertEqual((run["state"], run["result"], run["last_error"]),
                         ("COMPLETED", "FAIL", None))
        records = service.store.list_records(run_id, limit=100)["items"]
        self.assertEqual([(item["kind"], item["reason_code"]) for item in records], [
            ("RESPONSE", "START_QUEUED"), ("RESPONSE", "HIL_START_APPLIED"),
            ("OPERATION_RESULT", "EXECUTION_FAIL")])
        self.assertEqual(records[-1]["evidence_refs"], ["assertion-wind-boundary"])

    def test_persistent_run_store_preserves_replay_snapshots_and_records(self):
        from input_simulator.run_service import SimulatorRunService
        from input_simulator.run_store import RunStore

        with tempfile.TemporaryDirectory() as temporary:
            first = SimulatorRunService(
                self.management, self.template, store=RunStore(state_directory=temporary),
                clock=lambda: "2026-10-20T00:00:00Z", run_id_factory=lambda: "run-persisted")
            created = first.handle(copy.deepcopy(self.create))
            run_id = created["data"]["run_id"]
            first._record_fact(run_id, kind="SAFETY", reason_code="CREATE_AUDITED")

            reloaded_store = RunStore(state_directory=temporary)
            restored = SimulatorRunService(
                self.management, self.template, store=reloaded_store,
                clock=lambda: "2026-10-20T00:00:00Z", run_id_factory=lambda: "unexpected")
            self.assertEqual(reloaded_store.get(run_id)["state"], "READY")
            self.assertEqual(reloaded_store.list_records(run_id, limit=10)["items"][0]["reason_code"],
                             "CREATE_AUDITED")
            self.assertEqual(restored.handle(copy.deepcopy(self.create)), created)

    def test_persistent_store_marks_interrupted_run_incomplete_without_resuming_it(self):
        from input_simulator.run_store import RunStore

        with tempfile.TemporaryDirectory() as temporary:
            store = RunStore(state_directory=temporary)
            run = self._new_run_for_store("run-recovery")
            store.create(run, create_snapshot=b"{}", source_snapshot=b"{}", resource_evidence=())
            active = store.get("run-recovery")
            active.update(state="WAITING", result="RUNNING", available_actions=["STOP"], revision="2")
            store.replace_run("run-recovery", "1", active)

            recovered = RunStore(state_directory=temporary)
            run = recovered.get("run-recovery")
            self.assertEqual((run["state"], run["result"], run["available_actions"],
                              run["last_error"]["code"]),
                             ("COMPLETED", "INCOMPLETE", [], "EVIDENCE_INCOMPLETE"))
            self.management.validate_definition("Run", run)
            records = recovered.list_records("run-recovery", limit=10)["items"]
            self.assertEqual([(row["kind"], row["reason_code"], row["operation_result"])
                              for row in records],
                             [("OPERATION_RESULT", "RECOVERY_INCOMPLETE", "FAILED")])
            self.management.validate_definition("Record", records[0])

    def _new_run_for_store(self, run_id):
        run = self.service._new_run(self.create["params"])
        run["run_id"] = run_id
        return run
