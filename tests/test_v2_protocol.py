import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from shared import state_cache  # noqa
from shared.flight_state import FLIGHT_STATE_SIZE  # noqa
import bridge_tcp_client  # noqa


class V2ProtocolTests(unittest.TestCase):
    def test_fixed_c_to_python_state_wire_layout_includes_acceleration(self):
        self.assertEqual(100, FLIGHT_STATE_SIZE)

    def test_v2_state_excludes_internal_acceleration_and_uses_only_allowed_fields(self):
        state = {
            'sequence': 9, 'sim_time_s': 1.25,
            'north_m': 10.0, 'east_m': 20.0, 'down_m': 30.0,
            'vn_mps': 1.0, 've_mps': 2.0, 'vd_mps': 3.0,
            'q_w': 0.7071067811865476, 'q_x': 0.0, 'q_y': 0.0,
            'q_z': 0.7071067811865476,
            'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
            'ax_mps2': 4.0, 'ay_mps2': 5.0, 'az_mps2': 6.0,
            'airborne': 1, 'lifecycle': 0,
        }
        packet = state_cache.vehicle_state_v2_from_state(state, 'mission-a')
        self.assertNotIn('acceleration', packet['data'])
        self.assertEqual(
            {'mission_id', 'sim_time', 'position', 'attitude', 'velocity',
             'angular_velocity'},
            set(packet['data']))
        self.assertEqual({'x': 10.0, 'y': 20.0, 'height': -30.0}, packet['data']['position'])
        self.assertTrue('flight_state' not in packet['data'])

    def test_v2_event_maps_internal_reset_to_reset_scene(self):
        self.assertEqual('reset_scene', state_cache.v2_event_name('reset'))

    def test_v2_rejects_missing_mission_identifier(self):
        with self.assertRaises(ValueError):
            state_cache.vehicle_state_v2_from_state({}, '')

    def test_mission_plan_requires_two_finite_waypoints(self):
        with self.assertRaises(ValueError):
            bridge_tcp_client.validate_mission_plan('mission-a', [
                {'x': 0.0, 'y': 0.0, 'height': 10.0, 'speed': 5.0}])
        with self.assertRaises(ValueError):
            bridge_tcp_client.validate_mission_plan('mission-a', [
                {'x': 0.0, 'y': 0.0, 'height': 10.0, 'speed': 5.0},
                {'x': float('nan'), 'y': 1.0, 'height': 10.0, 'speed': 5.0}])


if __name__ == '__main__':
    unittest.main()
