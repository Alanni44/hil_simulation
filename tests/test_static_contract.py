import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


class ModelContractStaticTests(unittest.TestCase):

    def test_build_does_not_force_include_model_config(self):
        self.assertNotIn("'-include \"%s\" '",
                         read('matlab_scripts/build_script.m'))

    def test_adapter_declares_required_position_outputs(self):
        source = read('matlab_scripts/adapt_model.m')
        self.assertIn("required_outputs = {'pos_x', 'pos_y', 'pos_z'}", source)

    def test_core_uses_generated_safe_accessors(self):
        source = read('c_core/src/main_rt.c')
        self.assertNotIn('#define MODEL_Y_GET', source)
        self.assertIn('MODEL_READ_pos_x', source)

    def test_core_applies_command_input_with_a_lock_free_snapshot(self):
        source = read('c_core/src/main_rt.c')
        self.assertIn('pending_input_seq', source)
        self.assertIn('apply_pending_input()', source)
        self.assertNotIn('pthread_mutex_lock(&model_input_lock)', source)

    def test_integration_test_uses_valid_flight_state_indexes(self):
        source = read('scripts/integration_test.sh')
        self.assertNotIn('v[34]', source)
        self.assertNotIn('v[35]', source)
        self.assertNotIn('v[33]', source)
        self.assertIn('v[2],v[3],v[4],v[27],v[29],v[28]', source)

    def test_integration_task_uses_the_slx_file_not_build_directory(self):
        source = read('scripts/integration_test.sh')
        self.assertIn('"slx_path":"SLX_PATH_PLACEHOLDER"', source)
        self.assertIn('s|SLX_PATH_PLACEHOLDER|$SLX|g', source)

    def test_adapter_accepts_jsondecoded_port_struct_arrays(self):
        source = read('matlab_scripts/adapt_model.m')
        self.assertIn('if iscell(ports)', source)
        self.assertIn('ports(index)', source)

    def test_integration_test_reports_matlab_build_error_details(self):
        source = read('scripts/integration_test.sh')
        self.assertIn('/tmp/hil_test_result.json', source)
        self.assertIn('ERT failure:', source)

    def test_test_model_uses_signal_products_for_pid_gains(self):
        source = read('matlab_scripts/generate_test_model.m')
        self.assertNotIn("'simulink/Math Operations/Gain'", source)
        self.assertIn("'simulink/Math Operations/Product'", source)
        for connection in (
                "'kpxy/1','P_X/2'", "'kixy/1','Ig_X/2'",
                "'kdxy/1','Dg_X/2'", "'kpz/1','P_Z/2'",
                "'kiz/1','Ig_Z/2'", "'kdz/1','Dg_Z/2'"):
            self.assertIn(connection, source)

    def test_build_uses_explicit_and_discovered_codegen_directory(self):
        source = read('matlab_scripts/build_script.m')
        self.assertIn("Simulink.fileGenControl('set'", source)
        self.assertIn("'CodeGenFolder', output_dir", source)
        self.assertIn('RTW.getBuildDir(build_model)', source)
        self.assertIn('onCleanup(@() close_model_without_save(build_model))', source)
        self.assertIn('cd(output_dir);', source)
        self.assertIn('onCleanup(@() cd(original_dir))', source)

    def test_python_dependency_is_pinned_for_python_36(self):
        self.assertEqual('PyYAML==6.0.1\n', read('requirements.txt'))


if __name__ == '__main__':
    unittest.main()
