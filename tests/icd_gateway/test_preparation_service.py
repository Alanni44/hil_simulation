import copy
from dataclasses import replace

from common import GatewayTest, message


class PreparationServiceTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.configuration_service import (
            ModelConfigurationBackend,
            ModelConfigurationContext,
            ModelConfigurationReceipt,
        )
        from icd_gateway.semantic_guards import ModelView
        from icd_runtime.json_codec import canonicalize, loads

        self.identity = message(1)["payload"]["identity"]
        self.request = message(3)
        self.request["header"].update(session_id=1, sequence=2, transaction_id=3, target_step=0)
        test = self

        class ActualBoundaryDouble(ModelConfigurationBackend):
            def __init__(self):
                super().__init__(test.contract, ("quadrotor_hil",))
                self.calls = 0
                self.view = ModelView("quadrotor_hil", "STOPPED", 0, 600000, "NONE", False, False)

            def read_context(self, identity, request_json, *, now_ns):
                return ModelConfigurationContext(canonicalize(identity), request_json, self.view, 0.0,
                                                 now_ns, now_ns + 240_000_000,
                                                 self.view.state == "CONFIGURED")

            def apply_configuration(self, request_json, context, *, now_ns):
                config = loads(request_json)["payload"]
                if not context.idempotent_existing:
                    self.calls += 1
                    self.view = replace(self.view, state="CONFIGURED", configured_once=True,
                                        max_duration_steps=config["max_duration_steps"])
                return ModelConfigurationReceipt(
                    canonicalize(test.identity), request_json, canonicalize(config),
                    canonicalize(config["initial_state"]), canonicalize(config["initial_inputs"]),
                    self.view, self.calls, now_ns, now_ns + 240_000_000)

        self.backend = ActualBoundaryDouble()
        from icd_gateway.preparation_service import PreparationService
        self.service = PreparationService(self.contract, self.backend, clock=lambda: 100)

    def test_preparation_uses_actual_receipt_and_equal_snapshot_runs_once(self):
        result = self.service.prepare("prepare-01", self.identity, copy.deepcopy(self.request))
        self.assertTrue(result.configured)
        self.assertEqual(result.model_step, 0)
        self.assertEqual(result.baseline_sha256, self.contract.baseline_sha256)
        self.assertEqual(self.backend.calls, 1)
        self.assertEqual(self.service.prepare("prepare-02", self.identity, copy.deepcopy(self.request)), result)
        self.assertEqual(self.backend.calls, 1)

    def test_new_first_circle_service_reconciles_the_same_configured_snapshot(self):
        self.service.prepare("prepare-01", self.identity, copy.deepcopy(self.request))
        from icd_gateway.preparation_service import PreparationService
        restarted = PreparationService(self.contract, self.backend, clock=lambda: 100)
        result = restarted.prepare("prepare-02", self.identity, copy.deepcopy(self.request))
        self.assertTrue(result.configured)
        self.assertEqual(result.state, "CONFIGURED")
        self.assertEqual(self.backend.calls, 1)

    def test_same_prepare_id_cannot_name_another_snapshot(self):
        self.service.prepare("prepare-01", self.identity, copy.deepcopy(self.request))
        changed = copy.deepcopy(self.request)
        changed["payload"]["random_seed"] = 2
        self.rejects("DUPLICATE", lambda: self.service.prepare("prepare-01", self.identity, changed))

    def test_backend_receipt_that_only_echoes_a_wrong_readback_is_rejected(self):
        original = self.backend.apply_configuration

        def wrong(*args, **kwargs):
            receipt = original(*args, **kwargs)
            return replace(receipt, initial_state_json=b'{"wrong":true}')

        self.backend.apply_configuration = wrong
        self.rejects("BUSINESS_FAILED", lambda: self.service.prepare(
            "prepare-wrong", self.identity, copy.deepcopy(self.request)))
