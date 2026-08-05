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


if __name__ == '__main__':
    unittest.main()
