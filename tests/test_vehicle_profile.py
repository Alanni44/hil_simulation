import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python_services'))

from hil_adapters.virtual_quad_fc import controller_from_profile
from shared.vehicle_profile import VehicleProfileError, profile_from_contract


def common_contract(kind, channels):
    return {'contract_version': 3, 'model_name': '{}_test'.format(kind),
            'vehicle_kind': kind, 'control_sources': ['physical_uut'],
            'actuators': {'channels': channels}, 'sensors': {}}


def multirotor_contract(count=6):
    channels = [{'name': 'motor_{:02d}'.format(index + 1), 'min': 0.0,
                 'max': 1.0, 'safe_value': 0.0} for index in range(count)]
    positions = [(-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0), (1.0, 1.0),
                 (0.0, -1.2), (0.0, 1.2)]
    contract = common_contract('multirotor', channels)
    contract['virtual_fc'] = {'kind': 'multirotor', 'rotors': [
        {'channel': channel['name'], 'position_m': list(positions[index]),
         'spin': 'cw' if index % 2 == 0 else 'ccw', 'thrust_scale': 1.0}
        for index, channel in enumerate(channels)]}
    return contract


def fixed_wing_contract():
    channels = [{'name': 'throttle', 'min': 0.0, 'max': 1.0, 'safe_value': 0.0},
                {'name': 'aileron', 'min': -1.0, 'max': 1.0, 'safe_value': 0.0},
                {'name': 'elevator', 'min': -1.0, 'max': 1.0, 'safe_value': 0.0},
                {'name': 'rudder', 'min': -1.0, 'max': 1.0, 'safe_value': 0.0}]
    contract = common_contract('fixed_wing', channels)
    contract['virtual_fc'] = {'kind': 'fixed_wing', 'cruise_speed_mps': 15.0,
                              'axis_map': {'throttle': 'throttle', 'roll': 'aileron',
                                           'pitch': 'elevator', 'yaw': 'rudder'}}
    return contract


def seed_sensors(controller, now=1.0):
    controller.ingest({'frame_type': 'imu', 'timestamp_us': 1000000, 'valid': True,
                       'gyro_radps': [0.0, 0.0, 0.0], 'accel_mps2': [0.0, 0.0, -9.81]}, now)
    controller.ingest({'frame_type': 'gps', 'timestamp_us': 1000000, 'valid': True,
                       'latitude_deg': 31.2304, 'longitude_deg': 121.4737, 'altitude_m': 10.0,
                       'velocity_ned_mps': [0.0, 0.0, 0.0], 'heading_deg': 0.0, 'fix_type': 3}, now)
    controller.ingest({'frame_type': 'barometer', 'timestamp_us': 1000000,
                       'valid': True, 'altitude_m': 10.0}, now)


class VehicleProfileTest(unittest.TestCase):
    def test_multirotor_profile_allocates_contract_number_of_rotors(self):
        profile = profile_from_contract(multirotor_contract())
        controller = controller_from_profile({}, profile)
        seed_sensors(controller)
        controller.set_target(10.0, 0.0, 0.0, 0.0)
        values, armed, mode = controller.command(1.01)
        self.assertTrue(armed); self.assertEqual(mode, 'OFFBOARD')
        self.assertEqual(len(values), 6)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))
        self.assertGreater(max(values) - min(values), 0.01)

    def test_fixed_wing_profile_outputs_named_axes(self):
        profile = profile_from_contract(fixed_wing_contract())
        controller = controller_from_profile({}, profile)
        seed_sensors(controller)
        controller.set_target(100.0, 20.0, -10.0, 20.0)
        values, armed, mode = controller.command(1.01)
        self.assertTrue(armed); self.assertEqual(mode, 'OFFBOARD')
        self.assertEqual(len(values), 4)
        self.assertGreater(values[0], 0.0)  # throttle
        self.assertNotEqual(values[1], 0.0)  # aileron/course correction

    def test_contract_without_geometry_is_rejected_not_guessed(self):
        contract = multirotor_contract()
        del contract['virtual_fc']
        with self.assertRaises(VehicleProfileError):
            profile_from_contract(contract)

    def test_deployment_marker_contract_is_accepted(self):
        profile = profile_from_contract({'contract': fixed_wing_contract(), 'contract_sha256': 'x'})
        self.assertEqual(profile['vehicle_kind'], 'fixed_wing')
        self.assertEqual(profile['axis_map']['roll'], 'aileron')


if __name__ == '__main__':
    unittest.main()
