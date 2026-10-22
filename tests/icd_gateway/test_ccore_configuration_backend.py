from common import GatewayTest, message

from icd_runtime.json_codec import canonicalize


class CcoreConfigurationBackendTests(GatewayTest):
    def _backend(self):
        from icd_gateway.model_consumer import CcoreConfigurationBackend
        return CcoreConfigurationBackend(
            self.contract, {"quadrotor_hil": ("127.0.0.1", 9997)}, clock=lambda: 100)

    def _second_circle_backend(self):
        from icd_gateway.model_consumer import CcoreConfigurationBackend
        return CcoreConfigurationBackend(
            self.contract, {"quadrotor_hil": ("127.0.0.1", 9997)}, clock=lambda: 100,
            require_prepared_existing=True)

    @staticmethod
    def _status(*, initial_state_abi=False, full_configuration_abi=False):
        return {
            "accepted": True,
            "fields": {
                "lifecycle": "STOPPED", "sequence": 0,
                "control_source": "none", "model_loaded": True,
                "initial_state_abi": initial_state_abi,
                "full_configuration_abi": full_configuration_abi,
            },
        }

    def _request(self):
        request = message(3)
        request["payload"]["terrain_resource_sha256"] = None
        request["payload"]["obstacle_resource_sha256"] = None
        return request

    def test_extu_exty_only_runtime_is_refused_before_any_configure_write(self):
        backend = self._backend()
        commands = []

        def exchange(command):
            commands.append(command["cmd"])
            return self._status()

        backend._bridges["quadrotor_hil"]._exchange = exchange
        self.rejects("TARGET_MISSING", lambda: backend.read_context(
            {"model_id": "quadrotor_hil"}, canonicalize(self._request()), now_ns=0))
        self.assertEqual(commands, ["get_hil_status"])

    def test_resource_backed_terrain_requires_an_installed_actual_resolver(self):
        backend = self._backend()
        backend._bridges["quadrotor_hil"]._exchange = lambda command: self._status(
            initial_state_abi=True, full_configuration_abi=True)
        self.rejects("TARGET_MISSING", lambda: backend.read_context(
            {"model_id": "quadrotor_hil"}, canonicalize(message(3)), now_ns=0))

    def test_actual_resource_fact_supplies_the_context_ground_sample(self):
        from icd_gateway.model_consumer import ResolvedRunConfigurationResources

        class Resolver:
            def resolve(self, payload):
                return ResolvedRunConfigurationResources(
                    payload["terrain_resource_sha256"], payload["obstacle_resource_sha256"], -7.5)

        backend = self._backend()
        backend._resource_resolver = Resolver()
        backend._bridges["quadrotor_hil"]._exchange = lambda command: self._status(
            initial_state_abi=True, full_configuration_abi=True)
        context = backend.read_context({"model_id": "quadrotor_hil"}, canonicalize(message(3)), now_ns=0)
        self.assertEqual(context.ground_down, -7.5)

    def test_configuration_receipt_uses_direct_state_and_input_readback(self):
        backend = self._backend()
        request = self._request()
        lifecycle = ["STOPPED"]
        commands = []

        def exchange(command):
            commands.append(command)
            if command["cmd"] == "get_hil_status":
                reply = self._status(initial_state_abi=True, full_configuration_abi=True)
                reply["fields"].update(lifecycle=lifecycle[0], model_revision=1,
                                       initial_state=request["payload"]["initial_state"])
                return reply
            if command["cmd"] == "configure":
                self.assertEqual(command["params"]["configuration"], request["payload"])
                self.assertEqual(command["params"]["resource_context"], {
                    "terrain_sha256": None, "obstacle_sha256": None, "ground_down": 0.0})
                lifecycle[0] = "CONFIGURED"
                return {"accepted": True, "fields": {
                    "configuration": request["payload"], "model_revision": 1}}
            if command["cmd"] == "get_icd_snapshot":
                return {"accepted": True, "fields": {
                    "inputs": {key: request["payload"]["initial_inputs"][key]
                               for key in ("flight_control", "environment", "fault")},
                    "parameters": request["payload"]["initial_inputs"]["parameters"]}}
            raise AssertionError(command)

        backend._bridges["quadrotor_hil"]._exchange = exchange
        original = canonicalize(request)
        context = backend.read_context({"model_id": "quadrotor_hil"}, original, now_ns=0)
        receipt = backend.apply_configuration(original, context, now_ns=0)
        self.assertEqual(receipt.view.state, "CONFIGURED")
        self.assertEqual(receipt.model_revision, 1)
        self.assertEqual(receipt.initial_state_json, canonicalize(request["payload"]["initial_state"]))
        self.assertEqual(receipt.initial_inputs_json, canonicalize(request["payload"]["initial_inputs"]))
        self.assertEqual([command["cmd"] for command in commands], [
            "get_hil_status", "get_hil_status", "configure", "get_hil_status", "get_icd_snapshot"])

    def test_existing_matching_configuration_is_read_back_without_configure_write(self):
        backend = self._backend()
        request = self._request()
        commands = []

        def exchange(command):
            commands.append(command["cmd"])
            if command["cmd"] == "get_hil_status":
                reply = self._status(initial_state_abi=True, full_configuration_abi=True)
                reply["fields"].update(lifecycle="CONFIGURED", model_revision=7,
                                       initial_state=request["payload"]["initial_state"])
                return reply
            if command["cmd"] == "get_configuration_snapshot":
                return {"accepted": True, "fields": {
                    "configuration": request["payload"], "model_revision": 7}}
            if command["cmd"] == "get_icd_snapshot":
                return {"accepted": True, "fields": {
                    "inputs": {key: request["payload"]["initial_inputs"][key]
                               for key in ("flight_control", "environment", "fault")},
                    "parameters": request["payload"]["initial_inputs"]["parameters"]}}
            raise AssertionError(command)

        backend._bridges["quadrotor_hil"]._exchange = exchange
        original = canonicalize(request)
        context = backend.read_context({"model_id": "quadrotor_hil"}, original, now_ns=0)
        self.assertTrue(context.idempotent_existing)
        receipt = backend.apply_configuration(original, context, now_ns=0)
        self.assertEqual(receipt.view.state, "CONFIGURED")
        self.assertEqual(receipt.model_revision, 7)
        self.assertNotIn("configure", commands)

    def test_second_circle_rejects_stopped_target_before_any_configuration_write(self):
        backend = self._second_circle_backend()
        commands = []

        def exchange(command):
            commands.append(command["cmd"])
            return self._status(initial_state_abi=True, full_configuration_abi=True)

        backend._bridges["quadrotor_hil"]._exchange = exchange
        self.rejects("STATE", lambda: backend.read_context(
            {"model_id": "quadrotor_hil"}, canonicalize(self._request()), now_ns=0))
        self.assertEqual(commands, ["get_hil_status"])

    def test_existing_different_configuration_is_rejected_before_write(self):
        backend = self._backend()
        request = self._request()
        commands = []

        def exchange(command):
            commands.append(command["cmd"])
            if command["cmd"] == "get_hil_status":
                reply = self._status(initial_state_abi=True, full_configuration_abi=True)
                reply["fields"].update(lifecycle="CONFIGURED")
                return reply
            if command["cmd"] == "get_configuration_snapshot":
                changed = dict(request["payload"])
                changed["max_duration_steps"] += 1
                return {"accepted": True, "fields": {
                    "configuration": changed, "model_revision": 1}}
            raise AssertionError(command)

        backend._bridges["quadrotor_hil"]._exchange = exchange
        self.rejects("STATE", lambda: backend.read_context(
            {"model_id": "quadrotor_hil"}, canonicalize(request), now_ns=0))
        self.assertEqual(commands, ["get_hil_status", "get_configuration_snapshot"])
