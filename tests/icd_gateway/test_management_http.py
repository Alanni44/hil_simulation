import copy
import http.client
import json
import socket
import tempfile
from pathlib import Path

from common import EXPECTED, INTERFACES, ROOT, GatewayTest


class ManagementHTTPTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_runtime.management import ManagementContract
        from input_simulator.run_service import SimulatorRunService
        from input_simulator.run_template import FixedRunTemplate

        management = ManagementContract.load(INTERFACES, contract=self.contract)
        self.create = json.loads((INTERFACES / "input-simulator-v0.3.examples.json").read_text())["management_create_schema_fixture"]
        params = self.create["params"]
        template = FixedRunTemplate(
            model_id="quadrotor_hil",
            profile_ref={"profile_id": "minimal-profile", "version": "1",
                         "profile_hash": "8ddeeac31fad309043ed8d60f8f1aa585c749f65f34a1bc972a05b3f16bf38b2"},
            package_ref=params["package_ref"], scenario_ref=params["scenario_ref"],
            mode=params["mode"], source_binding_ref=params["source_binding_ref"],
            link_ids=params["link_ids"], run_configuration=params["run_configuration"],
            source_inputs=params["source_inputs"], resource_root=INTERFACES,
            clock_domain_id="SIMULATOR_MONOTONIC")
        self.service = SimulatorRunService(
            management, template, clock=lambda: "2026-10-20T00:00:00Z",
            run_id_factory=lambda: "run-http-01")
        from input_simulator.management_http import SimulatorManagementHTTPServer
        self.server = SimulatorManagementHTTPServer(self.service)
        self.thread = self.server.serve_in_thread()

    def tearDown(self):
        self.server.close()
        self.thread.join(timeout=2)

    def request(self, value, path="/api/simulator/commands"):
        connection = http.client.HTTPConnection(*self.server.address, timeout=5)
        try:
            connection.request("POST", path, body=json.dumps(value).encode("utf-8"),
                               headers={"Content-Type": "application/json"})
            reply = connection.getresponse()
            return reply.status, json.loads(reply.read().decode("utf-8"))
        finally:
            connection.close()

    def test_http_boundary_returns_v03_create_and_get(self):
        status, created = self.request(copy.deepcopy(self.create))
        self.assertEqual(status, 200)
        self.assertEqual(created["status"], "SUCCESS")
        get = {"cmd": "simulator_run_get", "params": {"api_version": "0.3",
               "request_id": "http-get-01", "run_id": created["data"]["run_id"]}}
        status, found = self.request(get)
        self.assertEqual((status, found["data"]["state"]), (200, "READY"))

    def test_http_boundary_rejects_unknown_path_and_malformed_json(self):
        status, body = self.request(copy.deepcopy(self.create), "/wrong")
        self.assertEqual((status, body), (404, {"error": "not_found"}))
        connection = http.client.HTTPConnection(*self.server.address, timeout=5)
        try:
            connection.request("POST", "/api/simulator/commands", body=b"{",
                               headers={"Content-Length": "1", "Content-Type": "application/json"})
            reply = connection.getresponse()
            self.assertEqual((reply.status, json.loads(reply.read())), (400, {"error": "invalid_request", "code": "SCHEMA"}))
        finally:
            connection.close()

    def test_http_boundary_requires_utf8_json_media_type(self):
        connection = http.client.HTTPConnection(*self.server.address, timeout=5)
        try:
            connection.request("POST", "/api/simulator/commands", body=json.dumps(self.create).encode("utf-8"),
                               headers={"Content-Type": "text/plain"})
            reply = connection.getresponse()
            self.assertEqual((reply.status, json.loads(reply.read())),
                             (415, {"error": "unsupported_media_type"}))
        finally:
            connection.close()

    def test_cli_builder_uses_verified_contract_and_repository_fixed_template(self):
        from input_simulator.manage import build_service

        service = build_service(
            contract_directory=INTERFACES, expected_sha256=EXPECTED,
            template_path=INTERFACES.parents[2] / "config/minimal-integration-template.json")
        self.assertEqual(service.management.contract.baseline_sha256, self.contract.baseline_sha256)
        self.assertEqual(service.template.model_id, "quadrotor_hil")

    def test_formal_runtime_factory_validates_and_releases_its_startup_probe(self):
        from input_simulator.runtime_factory import FormalRuntimeFactory

        def available_port():
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.bind(("127.0.0.1", 0))
                return probe.getsockname()[1]
            finally:
                probe.close()

        value = json.loads((ROOT / "config/minimal-integration-simulator.json").read_text())
        value["source_bind"] = "127.0.0.1:{}".format(available_port())
        value["feedback_bind"] = "127.0.0.1:{}".format(available_port())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as output:
            json.dump(value, output); output.flush()
            factory = FormalRuntimeFactory.load(self.contract, output.name)
        backend = factory.backend()
        self.assertEqual((backend._stop_lead_steps, backend._status_poll_s), (180, .02))
        # The startup probe must have released source/feedback sockets, so a
        # fresh source can claim the same configured endpoints.
        session = backend._session_factory(None)
        try:
            self.assertIsNone(session.session_id)
        finally:
            session.close()
            session.transport.close()

    def test_formal_runtime_factory_fails_before_service_start_when_udp_port_is_busy(self):
        from icd_runtime.errors import ICDError
        from input_simulator.runtime_factory import FormalRuntimeFactory

        held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            held.bind(("127.0.0.1", 0))
            value = json.loads((ROOT / "config/minimal-integration-simulator.json").read_text())
            value["source_bind"] = "127.0.0.1:{}".format(held.getsockname()[1])
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as output:
                json.dump(value, output); output.flush()
                with self.assertRaisesRegex(ICDError, "UDP endpoints cannot be bound"):
                    FormalRuntimeFactory.load(self.contract, output.name)
        finally:
            held.close()

    def test_cli_builder_installs_execution_only_for_explicit_runtime_config(self):
        from input_simulator.manage import build_service

        value = json.loads((ROOT / "config/minimal-integration-simulator.json").read_text())
        def available_port():
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.bind(("127.0.0.1", 0)); return probe.getsockname()[1]
            finally:
                probe.close()
        value["source_bind"] = "127.0.0.1:{}".format(available_port())
        value["feedback_bind"] = "127.0.0.1:{}".format(available_port())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as output:
            json.dump(value, output); output.flush()
            service = build_service(contract_directory=INTERFACES, expected_sha256=EXPECTED,
                                    template_path=ROOT / "config/minimal-integration-template.json",
                                    runtime_config=output.name)
        self.assertIsNotNone(service.executor)

    def test_cli_builder_requires_a_real_writable_state_directory_when_requested(self):
        from input_simulator.manage import build_service

        with tempfile.TemporaryDirectory() as temporary:
            service = build_service(
                contract_directory=INTERFACES, expected_sha256=EXPECTED,
                template_path=ROOT / "config/minimal-integration-template.json",
                state_directory=temporary)
            self.assertTrue((Path(temporary) / "run-store-v1.json").is_file())
            self.assertIsNotNone(service.store)
        with tempfile.NamedTemporaryFile() as not_a_directory:
            with self.assertRaisesRegex(Exception, "persistent Run state path is not a directory"):
                build_service(contract_directory=INTERFACES, expected_sha256=EXPECTED,
                              template_path=ROOT / "config/minimal-integration-template.json",
                              state_directory=not_a_directory.name)
