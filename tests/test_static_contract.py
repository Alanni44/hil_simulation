import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding='utf-8')


class RuntimeContractStaticTests(unittest.TestCase):
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

    def test_bridge_does_not_fabricate_default_mission_or_nonfinite_values(self):
        source = read('python_services/bridge_tcp_client.py')
        self.assertNotIn('_DEFAULT_WAYPOINTS', source)
        self.assertIn("raise ValueError('refusing non-finite value for UE4 protocol')", source)
        self.assertIn('_mission_queue.append', source)

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


if __name__ == '__main__': unittest.main()
