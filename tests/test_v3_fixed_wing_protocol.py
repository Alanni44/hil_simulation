import math
import json
import pathlib
import struct
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

import bridge_tcp_client  # noqa: E402
from shared import state_cache  # noqa: E402
from shared.flight_state import (FLIGHT_STATE_V3_FORMAT, FLIGHT_STATE_V3_SIZE,
                                 parse_flight_state)  # noqa: E402


def v3_state(**changes):
    state = {
        'version': 3, 'sequence': 8, 'sim_time_s': 1.0,
        'north_m': 100.0, 'east_m': 20.0, 'down_m': -30.0,
        'vn_mps': 10.0, 've_mps': 2.0, 'vd_mps': 1.0,
        'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
        'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
        'ax_mps2': 4.0, 'ay_mps2': 5.0, 'az_mps2': 6.0,
        'airborne': 1, 'lifecycle': 0, 'reserved': 0,
        'p_dot_radps2': 0.01, 'q_dot_radps2': -0.02, 'r_dot_radps2': 0.03,
        'wind_n_mps': 1.0, 'wind_e_mps': 0.5, 'wind_d_mps': 0.2,
        'throttle': 0.72, 'aileron_rad': 0.08, 'elevator_rad': -0.03,
        'rudder_rad': 0.01, 'tas_min_mps': 0.1, 'flight_phase': 2, 'control_surface_valid': 0,
        'reserved_v3': 0,
    }
    state.update(changes)
    return state


def pack_v3(state):
    values = [state[name] for name in (
        'version', 'sequence', 'sim_time_s', 'north_m', 'east_m', 'down_m',
        'vn_mps', 've_mps', 'vd_mps', 'q_w', 'q_x', 'q_y', 'q_z',
        'p_radps', 'q_radps', 'r_radps', 'ax_mps2', 'ay_mps2', 'az_mps2',
        'airborne', 'lifecycle', 'reserved', 'p_dot_radps2', 'q_dot_radps2',
        'r_dot_radps2', 'wind_n_mps', 'wind_e_mps', 'wind_d_mps', 'throttle',
        'aileron_rad', 'elevator_rad', 'rudder_rad', 'tas_min_mps', 'flight_phase',
        'control_surface_valid', 'reserved_v3')]
    return struct.pack(FLIGHT_STATE_V3_FORMAT, *values)


class FixedWingV3ProtocolTests(unittest.TestCase):
    def test_v3_binary_state_layout_parses_and_has_declared_size(self):
        raw = pack_v3(v3_state())
        self.assertEqual(FLIGHT_STATE_V3_SIZE, len(raw))
        self.assertEqual(3, parse_flight_state(raw)['version'])
        self.assertAlmostEqual(0.1, parse_flight_state(raw)['tas_min_mps'])

    def test_v3_vehicle_state_uses_confirmed_frames_and_required_fields(self):
        state = v3_state()
        packet = state_cache.vehicle_state_v3_from_state(state, 'fixed-1')
        self.assertEqual('3.0', packet['protocol_version'])
        self.assertEqual('FixedWing01', packet['vehicle_id'])
        data = packet['data']
        self.assertEqual(-6.0, data['acceleration']['az'])
        self.assertEqual('flying', data['flight_state'])
        self.assertEqual({'throttle': 0.72}, data['control'])
        self.assertAlmostEqual(math.atan2(0.8, 9.0), data['aerodynamics']['angle_of_attack'])
        self.assertAlmostEqual(math.asin(1.5 / math.sqrt(9.0 ** 2 + 1.5 ** 2 + 0.8 ** 2)),
                               data['aerodynamics']['sideslip_angle'])
        for key in ('mission_id', 'sim_time', 'position', 'attitude', 'velocity',
                    'acceleration', 'angular_velocity', 'control', 'flight_state'):
            self.assertIn(key, data)

    def test_v3_omits_optional_aerodynamics_at_low_tas_and_surfaces_without_mapping(self):
        packet = state_cache.vehicle_state_v3_from_state(
            v3_state(vn_mps=0.01, ve_mps=0.0, vd_mps=0.0,
                     wind_n_mps=0.0, wind_e_mps=0.0, wind_d_mps=0.0), 'fixed-1')
        self.assertNotIn('aerodynamics', packet['data'])
        self.assertEqual({'throttle': 0.72}, packet['data']['control'])

    def test_v3_includes_true_surfaces_only_when_c_core_marks_them_valid(self):
        packet = state_cache.vehicle_state_v3_from_state(
            v3_state(control_surface_valid=1), 'fixed-1')
        self.assertEqual({'throttle': 0.72, 'aileron': 0.08,
                          'elevator': -0.03, 'rudder': 0.01}, packet['data']['control'])

    def test_v3_hello_declares_fixed_wing_identity_and_frd(self):
        with mock.patch.dict(bridge_tcp_client.CONFIG, {'bridge': {'protocol_version': '3.0'}}, clear=False):
            hello = bridge_tcp_client._hello_message()
        self.assertEqual('3.0', hello['protocol_version'])
        self.assertEqual('FixedWing01', hello['vehicle_id'])
        self.assertEqual('simulink_fixedwing_state_source', hello['data']['role'])
        self.assertEqual('FRD', hello['data']['body_frame'])

    def test_v3_sender_keeps_twenty_ms_cadence_and_sends_v3_payload(self):
        class Clock(object):
            def __init__(self): self.now = 10.0
            def monotonic(self): return self.now
            def sleep(self, seconds): self.now += seconds
        class Capture(object):
            def __init__(self, clock): self.clock = clock; self.messages = []
            def sendall(self, wire): self.messages.append((self.clock.now, json.loads(wire[4:].decode('utf-8'))))
        clock = Clock(); capture = Capture(clock)
        packet = state_cache.vehicle_state_v3_from_state(v3_state(), 'fixed-1')
        with mock.patch.dict(bridge_tcp_client.CONFIG, {'bridge': {'protocol_version': '3.0'}}, clear=False), \
                mock.patch.object(bridge_tcp_client.state_cache, 'get_vehicle_state_v3', return_value=packet):
            bridge_tcp_client._vehicle_state_sender(capture, 'fixed-1', __import__('threading').Event(),
                                                    max_frames=3, monotonic_fn=clock.monotonic,
                                                    sleep_fn=clock.sleep)
        self.assertEqual([10.0, 10.02, 10.04], [round(item[0], 2) for item in capture.messages])
        self.assertTrue(all(item[1]['protocol_version'] == '3.0' and
                            item[1]['vehicle_id'] == 'FixedWing01' and
                            'acceleration' in item[1]['data'] for item in capture.messages))


if __name__ == '__main__':
    unittest.main()
