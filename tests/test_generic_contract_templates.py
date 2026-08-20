import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class GenericContractTemplateTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'matlab_scripts' / 'create_generic_vehicle_contract.m').read_text()

    def test_declares_v3_n_motor_and_fixed_wing_template_paths(self):
        self.assertIn("vehicle_kind = 'multirotor'", self.source)
        self.assertIn("'fixed_wing'", self.source)
        self.assertIn("motor_count > 32", self.source)
        self.assertIn("flight_control.motor_command", self.source)
        self.assertIn("'throttle','roll_cmd','pitch_cmd','yaw_cmd'", self.source)

    def test_fixed_wing_cannot_select_quadrotor_demo_controller(self):
        self.assertIn("if strcmp(vehicle_kind, 'fixed_wing') || motor_count ~= 4", self.source)
        self.assertIn("if strcmp(names{i}, 'throttle'), minimum = 0.0; end", self.source)

    def test_template_covers_sensor_rates_faults_and_complex_parameters(self):
        for expected in ("'imu'", "'gps'", "'magnetometer'", "'barometer'",
                         "'motor_4_failed'", "'packet_loss_ratio'", "'inertia_zz_kgm2'",
                         "'wind_d_bias_mps'"):
            self.assertIn(expected, self.source)

    def test_fixed_wing_template_declares_v3_phase_thresholds_without_fake_surfaces(self):
        self.assertIn("contract.protocol_v3", self.source)
        self.assertIn("'c_core_state_machine'", self.source)
        self.assertIn("'tas_min_mps'", self.source)
        self.assertIn('Surfaces are intentionally omitted', self.source)

    def test_build_emits_surface_values_only_from_explicit_v3_mapping(self):
        source = (ROOT / 'matlab_scripts' / 'build_script.m').read_text()
        self.assertIn("isfield(contract.protocol_v3, 'control_surfaces')", source)
        self.assertIn('#define HIL_SURFACE_OUTPUT_VALID 1', source)
        self.assertIn('surfaces.aileron.scale_rad', source)
        self.assertIn("strcmp(surfaces.source, 'model_output')", source)
        self.assertIn('HIL_READ_FLIGHT_PHASE_MODEL', source)
        self.assertIn('fixed_environment.wind_n_mps.field', source)
        self.assertIn('fixed_control.throttle.field', source)


if __name__ == '__main__':
    unittest.main()
