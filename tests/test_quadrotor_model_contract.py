import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


class QuadrotorModelContractTests(unittest.TestCase):
    def test_contract_declares_motor_mode_internal_rate_and_state_mapping(self):
        source = read('matlab_scripts/create_quadrotor_contract.m')
        self.assertIn('contract.contract_version = 2', source)
        self.assertIn("contract.state.frame = 'NED'", source)
        self.assertIn("contract.state.orientation = 'FRD_TO_NED_QUATERNION'", source)
        self.assertIn("flight_control.mode = 'motor_command'", source)
        self.assertRegex(source, r"motor_command[^\n]*descriptor\([^\n]*4")
        self.assertIn('contract.outputs.internal_state.rate_hz = 50', source)
        self.assertIn('contract.outputs.internal_state.include_in_ue4_json = false', source)
        self.assertNotIn('outputs.ue4_state', source)
        for field in ('north_m', 'east_m', 'down_m', 'vn_mps', 've_mps',
                      'vd_mps', 'q_w', 'q_x', 'q_y', 'q_z', 'p_radps',
                      'q_radps', 'r_radps', 'airborne'):
            self.assertRegex(source, r"state_outputs\.%s\s*=\s*'%s'" % (field, field))
        for field in ('ax_mps2', 'ay_mps2', 'az_mps2'):
            self.assertRegex(source, r"internal_acceleration\.%s\s*=\s*descriptor\('%s'" %
                             (field, field))

    def test_contract_declares_all_generated_tunable_abi(self):
        source = read('matlab_scripts/create_quadrotor_contract.m')
        expected = {
            'mass_kg': 'uav_mass_kg',
            'inertia_xx_kgm2': 'uav_inertia_xx_kgm2',
            'inertia_yy_kgm2': 'uav_inertia_yy_kgm2',
            'inertia_zz_kgm2': 'uav_inertia_zz_kgm2',
            'thrust_coefficient_n': 'uav_thrust_coefficient_n',
            'moment_coefficient_nm': 'uav_moment_coefficient_nm',
            'linear_drag_ns_m': 'uav_linear_drag_ns_m',
            'angular_drag_nms': 'uav_angular_drag_nms',
            'wind_n_bias_mps': 'uav_wind_n_bias_mps',
            'wind_e_bias_mps': 'uav_wind_e_bias_mps',
            'wind_d_bias_mps': 'uav_wind_d_bias_mps',
            'motor_efficiency': 'uav_motor_efficiency',
        }
        for name, symbol in expected.items():
            pattern = (r"parameter\('%s',\s*'%s',[^\n]*" % (name, symbol))
            self.assertRegex(source, pattern)
        self.assertIn("'class', parameter_class", source)
        self.assertIn("'min', minimum", source)
        self.assertIn("'max', maximum", source)

    def test_generator_is_fixed_step_exported_global_four_rotor_plant(self):
        source = read('matlab_scripts/generate_quadrotor_model.m')
        for setting in ("'SystemTargetFile', 'ert.tlc'",
                        "'Solver', 'FixedStepDiscrete'",
                        "'FixedStep', '0.001'"):
            self.assertIn(setting, source)
        self.assertIn("'motor_command'", source)
        self.assertIn("'PortDimensions', '4'", source)
        self.assertIn("CoderInfo.StorageClass = 'ExportedGlobal'", source)
        for state in ('position_ned', 'velocity_ned', 'quaternion_frd_to_ned',
                      'body_rates', 'motor_response'):
            self.assertIn(state, source)
        for physics in ('relative_wind_ned', 'gravity_ned', 'motor_thrust',
                        'x_frame_moment'):
            self.assertIn(physics, source)

    def test_environment_defaults_reach_generated_external_inputs_and_takeoff(self):
        contract_source = read('matlab_scripts/create_quadrotor_contract.m')
        build_source = read('matlab_scripts/build_script.m')
        plant_source = read('matlab_scripts/generate_quadrotor_model.m')

        expected_defaults = {
            'wind_n_mps': 0.0,
            'wind_e_mps': 0.0,
            'wind_d_mps': 0.0,
            'pressure_pa': 101325.0,
            'temperature_k': 288.15,
            'ground_height_m': 0.0,
        }
        for name, default in expected_defaults.items():
            self.assertRegex(
                contract_source,
                r"environment\.ports\.%s\s*=\s*defaulted_descriptor\([^\n]*,\s*%s\s*\)" %
                (name, re.escape(str(default))))

        self.assertIn("isfield(descriptor, 'default')", build_source)
        self.assertIn('descriptors(end).default = descriptor.default',
                      build_source)
        self.assertRegex(
            build_source,
            r"fprintf\(fid, 'u->%s = \(%s\)%.17g;\\n',\s*"
            r"d\.field, c_cast_type\(d\.type\), d\.default\)")

        pressure_pa = expected_defaults['pressure_pa']
        temperature_k = expected_defaults['temperature_k']
        density_scale = pressure_pa / (287.05 * temperature_k) / 1.225
        available_thrust_n = 4.0 * 4.2 * density_scale
        weight_n = 1.5 * 9.80665
        self.assertGreater(available_thrust_n, weight_n)
        self.assertIn(
            'motor_thrust = uav_thrust_coefficient_n .* motor_response.^2 .* density_scale;',
            plant_source)

    def test_builder_rejects_missing_generated_parameter_and_confines_artifacts(self):
        matlab_source = read('matlab_scripts/build_script.m')
        self.assertIn('Missing declared generated parameter ABI', matlab_source)
        self.assertNotIn('default_generated_parameter', matlab_source)
        shell_source = read('scripts/build_quadrotor_demo.sh')
        self.assertIn('set -euo pipefail', shell_source)
        self.assertIn('artifacts/z_mission/model', shell_source)
        self.assertIn('artifacts/z_mission/bin', shell_source)
        self.assertIn('artifacts/z_mission/logs', shell_source)
        self.assertIn('generate_quadrotor_model', shell_source)
        self.assertIn('create_quadrotor_contract', shell_source)
        self.assertIn('build_script(', shell_source)

    def test_matlab_validators_require_internal_acceleration_contract(self):
        for path in ('matlab_scripts/adapt_model.m',
                     'matlab_scripts/build_script.m'):
            source = read(path)
            self.assertIn('contract.outputs.internal_state', source)
            self.assertNotIn('contract.outputs.ue4_state', source)

    def test_acceptance_fixture_uses_internal_acceleration_contract(self):
        package_source = read('scripts/create_acceptance_package.py')
        acceptance_source = read('scripts/accept_runtime_contract.py')
        self.assertIn("'internal_state': {'rate_hz': 50", package_source)
        self.assertNotIn("'ue4_state': {'rate_hz': 50", package_source)
        self.assertIn("contract['outputs']['internal_state']['acceleration']", acceptance_source)
        self.assertNotIn("contract['outputs']['ue4_state']['acceleration']", acceptance_source)


if __name__ == '__main__':
    unittest.main()
