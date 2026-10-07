import copy
from dataclasses import replace
import importlib.util
import json

from common import GatewayTest, message


class SemanticTests(GatewayTest):
    def setup_guards(self):
        from icd_gateway.semantic_guards import SemanticGuards, ModelView
        self.guards = SemanticGuards(self.contract)
        self.view = ModelView("quadrotor_hil", "PAUSED", 10, 600000, "NONE", False, True)

    def command(self, action, state, *, target=10, count=3):
        value = message(4)
        value["header"]["target_step"] = target
        value["payload"] = {"action": action, "expected_state": state,
                            "reset_policy": "NEW_SESSION_RESTORE_INITIAL" if action == "RESET" else "NOT_APPLICABLE"}
        if action == "STEP":
            value["payload"]["step_count"] = count
        return value

    def test_semantic_guards_exist(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.semantic_guards"))

    def test_complete_lifecycle_action_state_matrix(self):
        self.setup_guards()
        accepted = {"START": {"CONFIGURED": "RUNNING"}, "PAUSE": {"RUNNING": "PAUSED"},
                    "RESUME": {"PAUSED": "RUNNING"},
                    "STOP": {"CONFIGURED": "STOPPED", "RUNNING": "STOPPED", "PAUSED": "STOPPED"},
                    "RESET": {"PAUSED": "CONFIGURED", "STOPPED": "CONFIGURED"},
                    "STEP": {"PAUSED": "PAUSED"}}
        for action, states in accepted.items():
            for state in ("CONFIGURED", "RUNNING", "PAUSED", "STOPPED"):
                view = replace(self.view, state=state)
                value = self.command(action, state, target=11 if state == "RUNNING" else 10)
                if state in states:
                    result = self.guards.lifecycle(value, view)
                    self.assertEqual(result.next_state, states[state])
                else:
                    self.rejects("SCHEMA" if action == "STEP" else "STATE",
                                 lambda value=value, view=view: self.guards.lifecycle(value, view))

    def test_expected_state_and_initial_configuration_cannot_be_assumed(self):
        self.setup_guards()
        self.rejects("STATE", lambda: self.guards.lifecycle(self.command("START", "CONFIGURED"), self.view))
        view = replace(self.view, state="CONFIGURED", configured_once=False)
        self.rejects("STATE", lambda: self.guards.lifecycle(self.command("START", "CONFIGURED"), view))
        view = replace(self.view, state="STOPPED", configured_once=False)
        self.rejects("STATE", lambda: self.guards.lifecycle(self.command("RESET", "STOPPED"), view))

    def test_frozen_boundary_is_current_and_running_boundary_is_future(self):
        self.setup_guards()
        for target in (9, 11, 1000):
            self.rejects("STATE", lambda target=target: self.guards.lifecycle(self.command("RESUME", "PAUSED", target=target), self.view))
        view = replace(self.view, state="RUNNING")
        for target, code in ((9, "LATE"), (10, "LATE"), (1011, "RANGE"), (600001, "RANGE")):
            self.rejects(code, lambda target=target: self.guards.lifecycle(self.command("PAUSE", "RUNNING", target=target), view))
        self.assertEqual(self.guards.lifecycle(self.command("PAUSE", "RUNNING", target=1010), view).target_step, 1010)

    def test_stop_reset_resume_require_cleanup_and_reset_restores_initial(self):
        self.setup_guards()
        for action in ("STOP", "RESET", "RESUME"):
            result = self.guards.lifecycle(self.command(action, "PAUSED"), self.view)
            self.assertTrue(result.clear_queues)
            self.assertTrue(result.safe_outputs)
            self.assertTrue(result.revoke_control)
            self.assertEqual(result.restore_initial, action == "RESET")
            self.assertEqual(result.new_session, action in ("RESET", "RESUME"))
        pause = self.guards.lifecycle(self.command("PAUSE", "RUNNING", target=11), replace(self.view, state="RUNNING"))
        self.assertTrue(pause.safe_outputs)
        self.assertEqual(self.view.state, "PAUSED")

    def test_step_is_exact_sequential_1ms_and_keeps_model_paused(self):
        self.setup_guards()
        result = self.guards.lifecycle(self.command("STEP", "PAUSED", count=3), self.view)
        self.assertEqual(result.steps, (11, 12, 13))
        self.assertEqual(result.next_state, "PAUSED")
        self.assertTrue(result.safe_outputs)
        self.assertTrue(result.revoke_control)
        self.assertEqual(self.guards.lifecycle(self.command("STEP", "PAUSED", count=1000), self.view).steps[-1], 1010)
        self.assertEqual(self.view.model_step, 10)

    def test_step_rejects_hardware_control_owner_duration_overflow_and_bad_counts(self):
        self.setup_guards()
        value = self.command("STEP", "PAUSED")
        self.rejects("UNSUPPORTED", lambda: self.guards.lifecycle(value, replace(self.view, physical_closed_loop=True)))
        self.rejects("CONTROL_OWNER", lambda: self.guards.lifecycle(value, replace(self.view, control_source="PX4_SITL")))
        self.rejects("RANGE", lambda: self.guards.lifecycle(value, replace(self.view, max_duration_steps=11)))
        for count in (0, True, 1001):
            self.rejects("SCHEMA", lambda count=count: self.guards.lifecycle(self.command("STEP", "PAUSED", count=count), self.view))

    def test_view_is_strict_immutable_and_missing_model_is_not_fabricated(self):
        self.setup_guards()
        for values in ({"model_step": True}, {"model_step": -1}, {"model_step": 600001},
                       {"physical_closed_loop": 1}, {"configured_once": 1},
                       {"state": "ENDED"}, {"control_source": "demo_mission"}, {"max_duration_steps": 86400001}):
            self.rejects("SCHEMA", lambda values=values: replace(self.view, **values))
        self.rejects("MODEL", lambda: self.guards.lifecycle(self.command("STEP", "PAUSED"), replace(self.view, model_id="unknown")))
        with self.assertRaises(AttributeError):
            self.view.state = "RUNNING"

    def owner(self, *, source="PX4_SITL", lane="ACTUATOR", role="CONTROLLER", target=10):
        value = message(6)
        value["header"]["target_step"] = target
        value["payload"].update(source=source, input_lane=lane, role=role)
        return value

    def validate_owner(self, value, *, view=None, declared="PX4_SITL", roles=("CONTROLLER",), ready=False):
        return self.guards.control_owner(value, self.view if view is None else view,
                                         declared_controller=declared, controller_session_roles=roles,
                                         internal_controller_ready=ready)

    def test_external_owner_grant_requires_safe_values_clear_queue_and_fixed_lease(self):
        self.setup_guards()
        for source in ("PX4_SITL", "PHYSICAL_UUT"):
            for lane in ("FLIGHT_CONTROL", "ACTUATOR"):
                result = self.validate_owner(self.owner(source=source, lane=lane), declared=source)
                self.assertEqual((result.source, result.input_lane, result.role), (source, lane, "CONTROLLER"))
                self.assertEqual(result.lease_ms, 100)
                self.assertTrue(result.safe_outputs and result.clear_queues and result.revoke_control)
                self.assertFalse(hasattr(result, "deadline_ns"))

    def test_external_owner_cannot_use_sender_role_or_unknown_declared_source(self):
        self.setup_guards()
        self.rejects("AUTHORIZATION", lambda: self.validate_owner(self.owner(), roles=("STIMULUS",)))
        self.rejects("CONTROL_OWNER", lambda: self.validate_owner(self.owner(), declared="PHYSICAL_UUT"))
        self.rejects("CONTROL_OWNER", lambda: self.validate_owner(self.owner(role="STIMULUS")))
        self.rejects("TARGET_MISSING", lambda: self.validate_owner(self.owner(lane="INTERNAL_CONTROLLER")))

    def test_internal_demo_controller_is_declared_quad_only_and_not_external_writer(self):
        self.setup_guards()
        value = self.owner(source="DEMO_MISSION", lane="INTERNAL_CONTROLLER", role="CONTROLLER")
        result = self.validate_owner(value, declared="DEMO_MISSION", roles=(), ready=True)
        self.assertEqual(result.source, "DEMO_MISSION")
        self.rejects("TARGET_MISSING", lambda: self.validate_owner(value, declared="DEMO_MISSION", ready=False))
        for model in ("multirotor_6_hil", "fixed_wing_hil"):
            self.rejects("UNSUPPORTED", lambda model=model: self.validate_owner(value, declared="DEMO_MISSION", ready=True,
                                                                               view=replace(self.view, model_id=model)))
        self.rejects("CONTROL_OWNER", lambda: self.validate_owner(self.owner(source="DEMO_MISSION", role="STIMULUS"), declared="DEMO_MISSION", ready=True))

    def test_handover_is_paused_only_and_none_is_revocation_not_grant(self):
        self.setup_guards()
        for state in ("CONFIGURED", "RUNNING", "STOPPED"):
            self.rejects("STATE", lambda state=state: self.validate_owner(self.owner(), view=replace(self.view, state=state)))
        value = self.owner(source="NONE", role="STIMULUS", lane="INTERNAL_CONTROLLER", target=11)
        result = self.validate_owner(value, view=replace(self.view, state="RUNNING"), declared="NONE", roles=())
        self.assertEqual(result.source, "NONE")
        self.assertEqual(result.lease_ms, 0)
        self.assertTrue(result.safe_outputs and result.revoke_control)

    def test_wrong_message_schema_model_and_no_application_evidence(self):
        self.setup_guards()
        self.rejects("UNSUPPORTED", lambda: self.guards.lifecycle(message(10), self.view))
        value = self.owner()
        del value["payload"]["lease_ms"]
        self.rejects("SCHEMA", lambda: self.validate_owner(value))
        result = self.guards.lifecycle(self.command("RESET", "PAUSED"), self.view)
        self.assertFalse(hasattr(result, "model_revision"))
        self.assertFalse(hasattr(result, "probe_id"))
        with self.assertRaises(AttributeError):
            result.next_state = "RUNNING"

    def configure(self, model="quadrotor_hil"):
        value = message(3)
        value["header"]["target_step"] = 10
        value["payload"].update(model_id=model, terrain_resource_sha256=None, obstacle_resource_sha256=None)
        initial = value["payload"]["initial_inputs"]
        initial["model_id"] = model
        if model != "quadrotor_hil":
            mids = (8, 12, 18) if model == "multirotor_6_hil" else (9, 13, 19)
            for group, mid in zip(("flight_control", "fault", "parameters"), mids):
                initial[group] = message(mid)["payload"]
            for key, raw in initial["flight_control"].items():
                initial["flight_control"][key] = [0] * len(raw) if type(raw) is list else 0
        return value

    def configure_view(self, model="quadrotor_hil"):
        return replace(self.view, model_id=model, state="STOPPED")

    def test_complete_configure_snapshot_is_immutable_and_not_model_ready(self):
        self.setup_guards()
        value = self.configure()
        raw = self.guards.run_configure(value, self.configure_view())
        snapshot = json.loads(raw)
        self.assertEqual(snapshot, value["payload"])
        self.assertEqual(set(snapshot["initial_inputs"]),
                         {"model_id", "flight_control", "environment", "fault", "parameters",
                          "environment_ext", "system_stimulus", "sensor_fault"})
        value["payload"]["initial_inputs"]["parameters"]["mass_kg"] = 2
        self.assertEqual(json.loads(raw)["initial_inputs"]["parameters"]["mass_kg"], 1.5)
        self.assertEqual(self.view.state, "PAUSED")

    def test_configure_only_stopped_or_initial_configured(self):
        self.setup_guards()
        value = self.configure()
        for state in ("RUNNING", "PAUSED", "FAILED", "CONFIGURED"):
            self.rejects("STATE", lambda state=state: self.guards.run_configure(value, replace(self.view, state=state)))
        raw = self.guards.run_configure(value, replace(self.view, state="CONFIGURED", configured_once=False))
        self.assertEqual(json.loads(raw)["model_id"], "quadrotor_hil")

    def test_configuration_model_and_complete_initial_branch_must_match(self):
        self.setup_guards()
        value = self.configure("multirotor_6_hil")
        self.rejects("MODEL", lambda: self.guards.run_configure(value, self.configure_view()))
        value = self.configure("multirotor_6_hil")
        value["payload"]["model_id"] = "quadrotor_hil"
        self.rejects("MODEL", lambda: self.guards.run_configure(value, self.configure_view()))
        value = self.configure()
        del value["payload"]["initial_inputs"]["sensor_fault"]
        self.rejects("SCHEMA", lambda: self.guards.run_configure(value, self.configure_view()))

    def test_every_model_requires_explicit_safe_zero_control_initial_values(self):
        self.setup_guards()
        for model in ("quadrotor_hil", "multirotor_6_hil", "fixed_wing_hil"):
            value = self.configure(model)
            control = value["payload"]["initial_inputs"]["flight_control"]
            key = next(iter(control))
            if type(control[key]) is list:
                control[key][0] = 0.1
            else:
                control[key] = 0.1
            self.rejects("SAFETY", lambda value=value, model=model: self.guards.run_configure(value, self.configure_view(model)))

    def test_invalid_quaternion_is_rejected_without_normalizing(self):
        self.setup_guards()
        value = self.configure()
        value["payload"]["initial_state"]["orientation"]["q_w"] = 0.5
        self.rejects("RANGE", lambda: self.guards.run_configure(value, self.configure_view()))
        self.assertEqual(value["payload"]["initial_state"]["orientation"]["q_w"], 0.5)
        value["payload"]["initial_state"]["orientation"]["q_w"] = 0.9999995
        raw = self.guards.run_configure(value, self.configure_view())
        self.assertEqual(json.loads(raw)["initial_state"]["orientation"]["q_w"], 0.9999995)

    def test_ground_sign_airborne_and_static_multirotor_are_consistent(self):
        self.setup_guards()
        for model in ("quadrotor_hil", "multirotor_6_hil"):
            for field, invalid in (("airborne", True), ("velocity_n_mps", 1), ("p_radps", 1)):
                value = self.configure(model)
                value["payload"]["initial_state"][field] = invalid
                self.rejects("RANGE", lambda value=value, model=model: self.guards.run_configure(value, self.configure_view(model)))
        value = self.configure()
        value["payload"]["initial_inputs"]["environment"]["ground_height_m"] = 20
        value["payload"]["initial_state"]["position"]["down_m"] = -20
        self.guards.run_configure(value, self.configure_view())
        value["payload"]["initial_state"]["position"]["down_m"] = 20
        self.rejects("RANGE", lambda: self.guards.run_configure(value, self.configure_view()))

    def test_terrain_requires_actual_sample_and_agrees_with_root_ground_height(self):
        self.setup_guards()
        value = self.configure()
        value["payload"]["terrain_resource_sha256"] = "1" * 64
        self.rejects("RESOURCE", lambda: self.guards.run_configure(value, self.configure_view()))
        self.rejects("RANGE", lambda: self.guards.run_configure(value, self.configure_view(), terrain_ground_down=5))
        for invalid in (True, float("nan"), float("inf"), 10 ** 400):
            self.rejects("RESOURCE", lambda invalid=invalid: self.guards.run_configure(value, self.configure_view(), terrain_ground_down=invalid))
        self.guards.run_configure(value, self.configure_view(), terrain_ground_down=0)

    def test_fixed_wing_explicit_velocity_is_not_overridden_and_airborne_matches_height(self):
        self.setup_guards()
        value = self.configure("fixed_wing_hil")
        value["payload"]["initial_state"]["velocity_n_mps"] = 37
        raw = self.guards.run_configure(value, self.configure_view("fixed_wing_hil"))
        self.assertEqual(json.loads(raw)["initial_state"]["velocity_n_mps"], 37)
        value["payload"]["initial_state"].update(airborne=True)
        self.rejects("RANGE", lambda: self.guards.run_configure(value, self.configure_view("fixed_wing_hil")))
        value["payload"]["initial_state"]["position"]["down_m"] = -10
        self.guards.run_configure(value, self.configure_view("fixed_wing_hil"))

    def test_initial_state_only_configured_paused_and_preserves_reset_requirement(self):
        self.setup_guards()
        value = message(5)
        value["header"]["target_step"] = 10
        for state in ("RUNNING", "STOPPED", "FAILED"):
            self.rejects("STATE", lambda state=state: self.guards.initial_state(value, replace(self.view, state=state), ground_down=0))
        raw = self.guards.initial_state(value, self.view, ground_down=0)
        self.assertEqual(json.loads(raw), value["payload"])
        self.assertEqual(self.view.model_step, 10)
        self.rejects("RESOURCE", lambda: self.guards.initial_state(value, self.view, ground_down=None))

    def test_initial_sensor_failure_is_consistent_and_demo_model_is_not_silently_changed(self):
        self.setup_guards()
        value = self.configure()
        value["payload"]["initial_inputs"]["sensor_fault"]["gps_valid"] = False
        self.rejects("BUSINESS_FAILED", lambda: self.guards.run_configure(value, self.configure_view()))
        value["payload"]["initial_inputs"]["sensor_fault"]["gps_fix_type"] = "NO_FIX"
        self.guards.run_configure(value, self.configure_view())
        value = self.configure("fixed_wing_hil")
        value["payload"]["controller"] = "DEMO_MISSION"
        self.rejects("UNSUPPORTED", lambda: self.guards.run_configure(value, self.configure_view("fixed_wing_hil")))
