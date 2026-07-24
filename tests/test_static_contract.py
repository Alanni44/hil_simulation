import pathlib
import re
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
        self.assertIn('adopt_pending_command_state()', source)
        self.assertNotIn('pthread_mutex_lock(&model_input_lock)', source)

    def test_command_parser_does_not_mutate_active_mission_state(self):
        source = read('c_core/src/main_rt.c')
        parser = source[source.index('static int parse_command'):source.index('void* command_thread')]
        self.assertNotIn('_wp_active', parser)
        self.assertNotIn('_wp_queue', parser)
        self.assertNotIn('_last_cmd_mode_written', parser)

    def test_core_only_applies_model_input_when_snapshot_changes(self):
        source = read('c_core/src/main_rt.c')
        self.assertIn('uint32_t input_generation;', source)
        self.assertIn('_adopted_input_generation', source)
        self.assertIn('candidate.input_generation != _adopted_input_generation', source)

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
        self.assertIn("build_work_dir = fullfile(output_dir, 'matlab_build_work');", source)
        self.assertIn('cd(build_work_dir);', source)
        self.assertIn('onCleanup(@() cd(original_dir))', source)

    def test_bridge_header_macro_is_an_unquoted_include_token(self):
        source = read('matlab_scripts/build_script.m')
        wrapper = read('c_core/src/model_rt_wrapper.c')
        self.assertIn("bridge_header_name = 'model_rt_bridge.h';", source)
        self.assertIn("-DMODEL_RT_BRIDGE_HEADER=%s", source)
        self.assertIn('#define MODEL_RT_BRIDGE_HEADER my_uav_model.h', wrapper)

    def test_generated_header_parser_strips_c_comments_before_fields(self):
        source = read('matlab_scripts/build_script.m')
        self.assertIn("inner = regexprep(inner, '/\\*[\\s\\S]*?\\*/', '');", source)
        self.assertIn("inner = regexprep(inner, '//[^\\r\\n]*', '');", source)

    def test_build_excludes_ert_example_main(self):
        source = read('matlab_scripts/build_script.m')
        self.assertIn("excluded_sources = {'ert_main.c'}", source)
        self.assertIn('any(strcmp(c_files(i).name, excluded_sources))', source)

    def test_integration_executable_matches_build_output(self):
        source = read('scripts/integration_test.sh')
        self.assertIn('EXE="$ROOT/executables/hil_test_model_rt"', source)

    def test_core_publishes_mission_metadata_with_the_input_snapshot(self):
        source = read('c_core/src/main_rt.c')
        self.assertIn('PendingCommandState_t pending_command', source)
        self.assertIn('adopt_pending_command_state()', source)
        self.assertNotIn('static int _cmd_mode_snapshot', source)

    def test_core_validates_waypoint_array_before_access(self):
        source = read('c_core/src/main_rt.c')
        guard = ('!params_obj || !json_object_object_get_ex(params_obj, "waypoints", &wps_obj) '
                 '|| json_object_get_type(wps_obj) != json_type_array')
        normalized = re.sub(r'\s+', ' ', source)
        self.assertIn(guard, normalized)
        self.assertLess(normalized.index(guard), normalized.index('json_object_array_length(wps_obj)'))

    def test_start_script_confirms_core_and_python_survive_startup(self):
        source = read('scripts/start_all.sh')
        self.assertIn('sudo "$EXE_PATH"', source)
        self.assertIn('kill -0 "$RT_PID"', source)
        self.assertIn('kill -0 "$PY_PID"', source)

    def test_integration_sender_uses_an_empty_object_for_omitted_params(self):
        source = read('scripts/integration_test.sh')
        self.assertIn('local params="${2:-{}}"', source)

    def test_python_dependency_is_pinned_for_python_36(self):
        self.assertEqual('PyYAML==6.0.1\n', read('requirements.txt'))


if __name__ == '__main__':
    unittest.main()
