import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding='utf-8')
def string_literal(node):
    if hasattr(node, 'value'):
        return node.value
    return node.s if isinstance(node, ast.Str) else None


class RuntimeContractStaticTests(unittest.TestCase):
    def test_acceptance_submits_complete_task_4_mission_schema(self):
        tree = ast.parse(read('scripts/accept_runtime_contract.py'))
        mission_params = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and
                    node.func.id == 'core_command' and
                    len(node.args) >= 5 and
                    string_literal(node.args[2]) == 'mission-ned'):
                mission_params = ast.literal_eval(node.args[4])
                break

        self.assertIsNotNone(mission_params)
        self.assertGreaterEqual(len(mission_params['waypoints']), 3)
        self.assertEqual(
            {'north_m', 'east_m', 'down_m', 'speed_mps'},
            set(mission_params['landing']))
        self.assertGreater(mission_params['landing']['speed_mps'], 0.0)
        self.assertGreater(mission_params['completion_radius_m'], 0.0)

    def test_core_reserves_capacity_for_50_route_points_plus_landing(self):
        header = read('c_core/src/mission_controller.h')
        source = read('c_core/src/main_rt.c')
        self.assertIn('#define MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS 50U', header)
        self.assertIn('#define MISSION_CONTROLLER_MAX_WAYPOINTS', header)
        self.assertIn(
            '(MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS + 1U)', header)
        self.assertIn(
            'count > MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS', source)
        self.assertNotIn(
            'count + 1U > MISSION_CONTROLLER_MAX_WAYPOINTS', source)

    def test_no_model_registry_or_hot_reload_implementation(self):
        combined = '\n'.join(read(path) for path in (
            'python_services/ws_server.py', 'c_core/src/model_rt_wrapper.c',
            'scripts/start_all.sh', 'scripts/test_hot_reload.sh'))
        self.assertNotIn('_activate_archived_build', combined)
        self.assertNotIn('execv(', combined)
        self.assertNotIn('urlopen(', combined)
        self.assertIn('intentionally unsupported', read('scripts/test_hot_reload.sh'))

    def test_adapter_requires_explicit_ned_contract_not_aliases(self):
        source = read('matlab_scripts/adapt_model.m')
        self.assertIn('FRD_TO_NED_QUATERNION', source)
        self.assertIn('required_state_fields()', source)
        self.assertNotIn('make_output_aliases', source)
        self.assertNotIn('map_ports', source)

    def test_build_validates_generated_abi_and_emits_no_defaults(self):
        source = read('matlab_scripts/build_script.m')
        self.assertIn('validate_contract_abi(contract, y_fields, u_fields, model_h)', source)
        self.assertIn('Generated ExtY field missing', source)
        self.assertIn('model_contract.h', source)
        self.assertIn('[HIL] GCC command:', source)
        self.assertIn('validate_input_contract_abi(contract, u_fields)', source)
        self.assertIn('hil_contract_set_input', source)
        self.assertIn('MODEL_READ_ax_mps2', source)
        self.assertNotIn('MODEL_DEFAULT_', source)

    def test_core_has_fixed_state_receipts_and_lifecycle(self):
        source = read('c_core/src/main_rt.c')
        protocol = read('c_core/src/flight_state.h')
        self.assertIn('send_receipt', source)
        self.assertIn('atomic parameter group rejected', source)
        self.assertIn('HIL_PAUSED', source)
        self.assertIn('if (lifecycle == HIL_RUNNING)', source)
        self.assertIn('north_m', protocol)
        self.assertIn('q_w', protocol)
        self.assertNotIn('pos_x', protocol)
        self.assertIn('have_valid_state', source)
        self.assertIn('if (have_valid_state)', source)
        self.assertIn('parse_load_mission', source)
        self.assertIn('finite north_m/east_m/down_m/speed_mps', source)
        self.assertIn('parse_set_inputs', source)
        self.assertIn('atomic input group rejected', source)
        self.assertIn('MODEL_READ_az_mps2', source)

    def test_core_enables_realtime_scheduler_and_memory_lock(self):
        source = read('c_core/src/realtime.c')
        self.assertIn('SCHED_FIFO', source)
        self.assertIn('mlockall(MCL_CURRENT | MCL_FUTURE)', source)
        self.assertIn('hil_realtime_init(90)', read('c_core/src/main_rt.c'))

    def test_production_deploy_uses_systemd_and_health_gate(self):
        source = read('python_services/ws_server.py')
        self.assertIn("['systemctl', 'restart', 'hil-deploy@current.service']", source)
        self.assertIn('_wait_for_healthy_core()', source)
        self.assertNotIn('subprocess.Popen', source)
        self.assertIn('DEV_DEPLOYED', source)

    def test_python_only_location_of_ned_to_ue4_conversion(self):
        source = read('python_services/shared/state_cache.py')
        self.assertIn('def ned_to_ue4', source)
        self.assertIn("'height': -state['down_m']", source)
        self.assertIn('ned_quaternion_to_ue4_rpy', source)
        self.assertNotIn('flight_state_schema', read('python_services/shared/flight_state.py'))
        parser = read('python_services/shared/flight_state.py')
        cache = read('python_services/shared/state_cache.py')
        self.assertIn("unsupported state version", parser)
        self.assertIn("state simulation time regressed", cache)
        self.assertNotIn("'acceleration'", cache)
        self.assertIn("'flight_state' not", read('tests/test_v2_protocol.py'))

    def test_bridge_does_not_fabricate_default_mission_or_nonfinite_values(self):
        source = read('python_services/bridge_tcp_client.py')
        self.assertNotIn('_DEFAULT_WAYPOINTS', source)
        self.assertIn("raise ValueError('refusing non-finite value for UE4 protocol')", source)
        self.assertIn('_mission_queue.append', source)
        self.assertIn('validate_mission_plan', source)
        self.assertIn("state_rate_hz': 50", source)
        self.assertIn("state_cache.v2_event_name", source)

    def test_build_request_is_controlled_and_auditable(self):
        source = read('python_services/ws_server.py')
        for value in ('request_id', 'package_path', 'package_sha256', 'VALIDATING', 'VERIFYING', 'evidence_path'):
            self.assertIn(value, source)
        self.assertIn('validate_package(', source)
        self.assertIn("_handle_load_mission", source)
        self.assertIn("previous_core_stopped_before_build", source)
        self.assertLess(source.index("previous_core_stopped_before_build"),
                        source.index("transitions.append('BUILDING')"))

    def test_acceptance_refuses_wrong_target_or_unconfirmed_lifecycle_event(self):
        source = read('scripts/accept_runtime_contract.py')
        self.assertIn('acceptance target must be Ubuntu 18.04 RT', source)
        self.assertIn('acceptance target must use GCC 7.x', source)
        self.assertIn('acceptance target must use Python 3.6.9', source)
        self.assertIn("'python_services_sha256'", source)
        self.assertIn("'scripts_sha256'", source)
        self.assertIn("['git', 'rev-parse', 'HEAD']", source)
        self.assertIn("['git', 'status', '--porcelain']", source)
        self.assertIn("'git_head'", source)
        self.assertIn("'realtime.json'", source)
        self.assertIn('realtime_30_minute_gate', source)
        self.assertIn('[Python UE4 Bridge]', source)
        self.assertIn('redirected stdout is now flushed', source)
        self.assertIn("'skipped': []", source)
        ws = read('python_services/ws_server.py')
        self.assertIn("if lifecycle_event and receipt.get('accepted')", ws)
        self.assertIn("elif cmd == 'set_inputs'", ws)
        self.assertIn("'inputs-atomic-reject'", source)
        self.assertIn("'contract_input_effect_at_step_boundary'", source)

    def test_ue4_acceptance_contract_excludes_internal_acceleration_and_rate(self):
        source = read('scripts/accept_runtime_contract.py')
        docs = read('docs/ubuntu-interface-acceptance.md')
        self.assertNotIn("ue4['acceleration']", source)
        self.assertNotIn("ue4['rate_hz']", source)
        self.assertNotIn('"acceleration":', docs)
        self.assertIn('不得要求或发送 `acceleration`、`rate_hz`', docs)
        self.assertIn('`state_rate_hz`', docs)

    def test_one_command_ubuntu_acceptance_runner_exists(self):
        source = read('scripts/run_ubuntu_acceptance.sh')
        self.assertIn('set -euo pipefail', source)
        self.assertIn('Ubuntu 18.04 RT', source)
        self.assertIn('python3 -m unittest', source)
        self.assertIn('scripts/accept_runtime_contract.py', source)
        self.assertIn('HIL_SKIP_REALTIME_GATE', source)
        self.assertIn('artifacts/acceptance', source)


if __name__ == '__main__': unittest.main()
