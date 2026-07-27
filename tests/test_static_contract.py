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
        self.assertIn('validate_contract_abi(contract, y_fields, u_fields)', source)
        self.assertIn('Generated ExtY field missing', source)
        self.assertIn('model_contract.h', source)
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

    def test_python_only_location_of_ned_to_ue4_conversion(self):
        source = read('python_services/shared/state_cache.py')
        self.assertIn('def ned_to_ue4', source)
        self.assertIn("'height': -state['down_m']", source)
        self.assertIn('ned_quaternion_to_ue4_rpy', source)
        self.assertNotIn('flight_state_schema', read('python_services/shared/flight_state.py'))

    def test_build_request_is_controlled_and_auditable(self):
        source = read('python_services/ws_server.py')
        for value in ('request_id', 'package_path', 'package_sha256', 'VALIDATING', 'VERIFYING', 'evidence_path'):
            self.assertIn(value, source)
        self.assertIn('validate_package(', source)


if __name__ == '__main__': unittest.main()
