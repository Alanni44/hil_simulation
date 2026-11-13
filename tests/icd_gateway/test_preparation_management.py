import copy
import http.client
import json
from types import SimpleNamespace
import unittest

from icd_gateway.preparation_http import COMMAND_PATH, PreparationHTTPServer
from icd_gateway.preparation_management import PreparationCommandService
from icd_gateway.preparation_service import PreparationResult, ResetResult
from icd_gateway.configuration_service import ModelRuntimeStatus


CONFIGURATION = {
    "model_id": "quadrotor_hil", "initial_state": {"north_m": 0.0},
    "initial_inputs": {"wind_n_mps": 0.0}, "max_duration_steps": 1000,
}
IDENTITY = {"model_id": "quadrotor_hil", "run_id": "item-01"}


class FakePreparation:
    def __init__(self):
        self.calls = []
        self.resets = []
        self.status_calls = 0

    def prepare_current(self, prepare_id, identity, configuration):
        self.calls.append((prepare_id, identity, configuration))
        return PreparationResult(
            prepare_id=prepare_id, model_id="quadrotor_hil", config_id="config-01",
            config_sha256="a" * 64, baseline_sha256="b" * 64,
            configuration_json=b"{}", initial_state_json=b"{}", initial_inputs_json=b"{}",
            model_revision=1, model_step=0, state="CONFIGURED", control_source="NONE",
            sampled_ns=1)

    def reset_current(self, reset_id, identity):
        self.resets.append((reset_id, identity))
        return ResetResult(reset_id=reset_id, model_id="quadrotor_hil", model_revision=1,
                           model_step=0, sim_time_us=0, state="STOPPED",
                           control_source="NONE", sampled_ns=1)

    def status_current(self, identity):
        self.status_calls += 1
        return ModelRuntimeStatus("STOPPED", 17, 1, "NONE", 17000, 1, 2)


def request(*, request_id="request-01", prepare_id="prepare-01", run_id="business-run-01"):
    return {"cmd": "hil_prepare", "params": {
        "api_version": "1.0", "request_id": request_id, "prepare_id": prepare_id,
        "run_id": run_id, "run_configuration": copy.deepcopy(CONFIGURATION),
    }}


class PreparationManagementTests(unittest.TestCase):
    def setUp(self):
        self.preparation = FakePreparation()
        self.service = PreparationCommandService(
            SimpleNamespace(model_id="quadrotor_hil", run_configuration=CONFIGURATION),
            IDENTITY, self.preparation)

    def test_prepares_fixed_snapshot_and_retains_query_result(self):
        prepared = self.service.handle(request())
        repeated = self.service.handle(request())
        found = self.service.handle({"cmd": "hil_prepare_get", "params": {
            "api_version": "1.0", "request_id": "request-get-01", "prepare_id": "prepare-01",
        }})
        self.assertEqual("SUCCESS", prepared["status"])
        self.assertEqual("business-run-01", prepared["data"]["run_id"])
        self.assertEqual("CONFIGURED", prepared["data"]["state"])
        self.assertEqual(prepared, repeated)
        self.assertEqual(prepared["data"], found["data"])
        self.assertEqual(1, len(self.preparation.calls))
        self.assertEqual(CONFIGURATION, self.preparation.calls[0][2])

    def test_rejects_configuration_drift_and_request_id_reuse(self):
        changed = request()
        changed["params"]["request_id"] = "request-drift-01"
        changed["params"]["run_configuration"]["max_duration_steps"] = 2
        rejected = self.service.handle(changed)
        self.assertEqual(("REJECTED", "REFERENCE"), (rejected["status"], rejected["code"]))
        self.service.handle(request())
        conflict = self.service.handle(request(run_id="business-run-02"))
        self.assertEqual(("REJECTED", "IDEMPOTENCY_CONFLICT"),
                         (conflict["status"], conflict["code"]))
        self.assertEqual(1, len(self.preparation.calls))

    def test_reset_has_its_own_idempotent_zero_step_response(self):
        reset = {"cmd": "hil_reset", "params": {
            "api_version": "1.0", "request_id": "reset-request-01",
            "reset_id": "reset-01", "run_id": "business-run-01",
        }}
        first = self.service.handle(reset)
        second = self.service.handle(reset)
        self.assertEqual(("SUCCESS", "OK"), (first["status"], first["code"]))
        self.assertEqual("STOPPED", first["data"]["state"])
        self.assertEqual("0", first["data"]["model_step"])
        self.assertEqual("0", first["data"]["sim_time_us"])
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.preparation.resets))

    def test_status_get_is_a_fresh_runtime_readback(self):
        response = self.service.handle({"cmd": "hil_status_get", "params": {
            "api_version": "1.0", "request_id": "status-request-01",
        }})
        self.assertEqual(("SUCCESS", "OK"), (response["status"], response["code"]))
        self.assertEqual("17", response["data"]["model_step"])
        self.assertEqual("17000", response["data"]["sim_time_us"])
        self.assertTrue(response["data"]["fresh"])
        self.assertEqual(1, self.preparation.status_calls)


class PreparationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.preparation = FakePreparation()
        self.server = PreparationHTTPServer(PreparationCommandService(
            SimpleNamespace(model_id="quadrotor_hil", run_configuration=CONFIGURATION),
            IDENTITY, self.preparation))
        self.thread = self.server.serve_in_thread()

    def tearDown(self):
        self.server.close()
        self.thread.join(timeout=2)

    def test_http_boundary_serves_preparation_command(self):
        connection = http.client.HTTPConnection(*self.server.address, timeout=5)
        try:
            connection.request("POST", COMMAND_PATH, body=json.dumps(request()).encode("utf-8"),
                               headers={"Content-Type": "application/json"})
            reply = connection.getresponse()
            self.assertEqual(200, reply.status)
            self.assertEqual("SUCCESS", json.loads(reply.read().decode("utf-8"))["status"])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
