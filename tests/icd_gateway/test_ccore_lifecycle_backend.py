from common import GatewayTest, message

from icd_runtime.json_codec import canonicalize, loads
from icd_gateway.semantic_guards import SemanticGuards


class CcoreLifecycleBackendTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.model_consumer import CcoreLifecycleBackend
        self.backend = CcoreLifecycleBackend(
            self.contract, {"quadrotor_hil": ("127.0.0.1", 9997)}, clock=lambda: 100)
        self.identity = message(1)["payload"]["identity"]
        self.configuration = message(3)["payload"]
        self.configuration.update(terrain_resource_sha256=None, obstacle_resource_sha256=None)
        self.lifecycle = "CONFIGURED"
        self.sequence = 0
        self.commands = []

        def exchange(command):
            self.commands.append(command)
            if command["cmd"] == "get_configuration_snapshot":
                return {"accepted": True, "fields": {
                    "configuration": self.configuration, "model_revision": 1}}
            if command["cmd"] == "get_hil_status":
                state = message(132)["payload"]
                state["model_step"] = self.sequence
                state["position"] = self.configuration["initial_state"]["position"]
                state["orientation"] = self.configuration["initial_state"]["orientation"]
                return {"accepted": True, "fields": {
                    "lifecycle": self.lifecycle, "sequence": self.sequence,
                    "control_source": "none", "model_loaded": True,
                    "actuator_output": [0.0, 0.0, 0.0, 0.0],
                    "initial_state_abi": True, "full_configuration_abi": True,
                    "model_revision": 1,
                    "initial_state": self.configuration["initial_state"],
                    "model_state": state,
                }}
            if command["cmd"] == "get_icd_snapshot":
                return {"accepted": True, "fields": {
                    "inputs": {key: self.configuration["initial_inputs"][key]
                               for key in ("flight_control", "environment", "fault")},
                    "parameters": self.configuration["initial_inputs"]["parameters"],
                }}
            if command["cmd"] == "stage_lifecycle":
                action = command["params"]["action"]
                self.lifecycle = {"START": "RUNNING", "PAUSE": "PAUSED", "RESUME": "RUNNING",
                                  "STOP": "STOPPED", "RESET": "CONFIGURED", "STEP": "PAUSED"}[action]
                self.sequence = (command["params"]["target_step"] + command["params"].get("step_count", 0))
                return {"accepted": True, "lifecycle": self.lifecycle,
                        "effective_sequence": self.sequence}
            if command["cmd"] == "get_lifecycle_step_result":
                params = command["params"]
                samples = []
                for number in range(params["start_index"] + 1,
                                    params["start_index"] + params["count"] + 1):
                    state = message(132)["payload"]
                    state["model_step"] = number
                    state["position"] = self.configuration["initial_state"]["position"]
                    state["orientation"] = self.configuration["initial_state"]["orientation"]
                    samples.append({"state_vector": [number, state["position"]["north_m"],
                                    state["position"]["east_m"], state["position"]["down_m"],
                                    state["vn_mps"], state["ve_mps"], state["vd_mps"],
                                    state["orientation"]["q_w"], state["orientation"]["q_x"],
                                    state["orientation"]["q_y"], state["orientation"]["q_z"],
                                    state["p_radps"], state["q_radps"], state["r_radps"],
                                    state["airborne"], state["ax_mps2"], state["ay_mps2"], state["az_mps2"]],
                                    "actuator_output": [0.0] * 4,
                                    "sampled_ns": number})
                return {"accepted": True, "fields": {
                    "stage_request_id": params["stage_request_id"], "total_count": 2,
                    "start_index": params["start_index"], "samples": samples}}
            raise AssertionError(command)

        self.backend._bridges["quadrotor_hil"]._exchange = exchange

    def test_start_uses_c_model_boundary_receipt_not_host_sleep(self):
        request = message(4)
        request["header"].update(session_id=1, sequence=2, transaction_id=2, target_step=0)
        request["payload"] = {"action": "START", "expected_state": "CONFIGURED",
                              "reset_policy": "NOT_APPLICABLE"}
        raw = canonicalize(request)
        context = self.backend.read_context(self.identity, raw, now_ns=0)
        decision = SemanticGuards(self.contract).lifecycle(request, context.view)
        receipt = self.backend.apply_lifecycle(raw, context, decision, now_ns=0)
        self.assertEqual((receipt.view.state, receipt.view.model_step), ("RUNNING", 0))
        staged = [command for command in self.commands if command["cmd"] == "stage_lifecycle"]
        self.assertEqual(staged[0]["params"], {"action": "START", "target_step": 0})
        self.assertEqual(receipt.steps, ())

    def test_step_reads_each_retained_c_model_observation(self):
        self.lifecycle = "PAUSED"
        request = message(4)
        request["header"].update(session_id=1, sequence=2, transaction_id=2, target_step=0)
        request["payload"] = {"action": "STEP", "expected_state": "PAUSED",
                              "reset_policy": "NOT_APPLICABLE", "step_count": 2}
        raw = canonicalize(request)
        context = self.backend.read_context(self.identity, raw, now_ns=0)
        decision = SemanticGuards(self.contract).lifecycle(request, context.view)
        receipt = self.backend.apply_lifecycle(raw, context, decision, now_ns=0)
        self.assertEqual((receipt.view.state, receipt.view.model_step), ("PAUSED", 2))
        self.assertEqual([loads(sample.state_json)["model_step"] for sample in receipt.steps], [1, 2])
        self.assertEqual([loads(sample.actuators_json) for sample in receipt.steps],
                         [{"motor_command": [0.0] * 4}] * 2)
        staged = [command for command in self.commands if command["cmd"] == "stage_lifecycle"]
        self.assertEqual(staged[0]["params"], {"action": "STEP", "target_step": 0, "step_count": 2})

    def test_status_backend_projects_direct_c_status_for_standard_heartbeat(self):
        from icd_gateway.model_consumer import CcoreStatusBackend

        backend = CcoreStatusBackend(
            self.contract, {"quadrotor_hil": ("127.0.0.1", 9997)}, clock=lambda: 100)
        backend._bridges["quadrotor_hil"]._exchange = lambda command: {
            "accepted": True, "fields": {
                "lifecycle": "RUNNING", "control_source": "none", "sequence": 42}}
        sample = backend.read_status(self.identity, now_ns=0)
        from icd_runtime.json_codec import loads
        self.assertEqual(loads(sample.payload_json), {
            "state": "RUNNING", "phase": "FLYING", "control_source": "NONE",
            "safety_active": True, "model_step": 42, "last_applied_sequence": 42,
            "receive_queue_depth": 0, "missed_deadline_count": 0, "received_count": 0,
            "rejected_count": 0, "applied_count": 0, "consumed_count": 0})
