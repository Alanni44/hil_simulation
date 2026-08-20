import json
import pathlib
import socket
import struct
import sys
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))
from fixed_wing_v3_bridge import (FixedWingV3BridgeServer, FixedWingV3Session,
                                  LatestFixedWingState, ProtocolError, recv_frame,
                                  send_frame)  # noqa


def frame(message):
    body = json.dumps(message, separators=(',', ':')).encode('utf-8')
    return struct.pack('>I', len(body)) + body


def message(message_type, seq, data):
    return {'protocol_version': '3.0', 'type': message_type, 'seq': seq,
            'vehicle_id': 'FixedWing01', 'data': data}


def hello(seq=1):
    return message('hello', seq, {'role': 'simulink_fixedwing_state_source',
        'state_rate_hz': 50, 'coordinate_convention': 'x_forward_y_right_height_up',
        'body_frame': 'FRD', 'angle_unit': 'rad'})


def mission(seq=2):
    return message('mission_plan', seq, {'mission_id': 'm1', 'replace_previous': True,
        'waypoints': [{'id': 'P1', 'x': 0.0, 'y': 0.0, 'height': 2.0},
                      {'id': 'P2', 'x': 10.0, 'y': 3.0, 'height': 8.0,
                       'target_speed': 15.0}]})


def state(seq=3, sim_time=0.02):
    return message('vehicle_state', seq, {'mission_id': 'm1', 'sim_time': sim_time,
        'position': {'x': 1.0, 'y': 2.0, 'height': 3.0},
        'attitude': {'roll': 0.1, 'pitch': 0.2, 'yaw': 0.3},
        'velocity': {'vx': 11.0, 'vy': 1.0, 'vz': 2.0},
        'acceleration': {'ax': 0.5, 'ay': 0.2, 'az': 0.1},
        'angular_velocity': {'p': 0.1, 'q': 0.2, 'r': 0.3},
        'angular_acceleration': {'p_dot': 0.01, 'q_dot': 0.02, 'r_dot': 0.03},
        'aerodynamics': {'airspeed': 12.0, 'angle_of_attack': 0.04,
                          'sideslip_angle': -0.02},
        'control': {'throttle': 0.7, 'aileron': 0.1, 'elevator': -0.02,
                    'rudder': 0.03}, 'flight_state': 'flying'})


class FixedWingV3BridgeTests(unittest.TestCase):
    def test_fragmented_big_endian_utf8_frame_is_received(self):
        left, right = socket.socketpair()
        try:
            wire = frame(hello())
            right.sendall(wire[:3]); right.sendall(wire[3:])
            self.assertEqual(hello(), recv_frame(left))
        finally:
            left.close(); right.close()

    def test_handshake_acks_only_low_rate_messages_and_replaces_latest_state(self):
        latest = LatestFixedWingState(); session = FixedWingV3Session(latest)
        for value in (hello(), mission()):
            ack = session.observe(value)
            self.assertEqual('ack', ack['type'])
            self.assertEqual(value['seq'], ack['data']['ref_seq'])
        self.assertIsNone(session.observe(state()))
        self.assertIsNone(session.observe(state(4, 0.04)))
        snapshot = latest.snapshot()
        self.assertEqual(0.04, snapshot['state']['sim_time'])
        self.assertEqual('flying', snapshot['state']['flight_state'])
        self.assertEqual(2, len(snapshot['waypoints']))

    def test_rejects_bad_identity_and_throttle_and_discards_old_state(self):
        latest = LatestFixedWingState(); session = FixedWingV3Session(latest)
        invalid = hello(); invalid['vehicle_id'] = 'Drone1'
        with self.assertRaisesRegex(ProtocolError, 'vehicle_id'):
            session.observe(invalid)
        session.observe(hello()); session.observe(mission())
        invalid = state(); invalid['data']['control']['throttle'] = 1.1
        with self.assertRaisesRegex(ProtocolError, 'throttle'):
            session.observe(invalid)
        session.observe(state())
        self.assertIsNone(session.observe(state()))
        self.assertIsNone(session.observe(state(4, 0.01)))
        self.assertEqual(0.02, latest.snapshot()['state']['sim_time'])

    def test_reset_clears_latest_state_and_mission_end_requires_current_mission(self):
        latest = LatestFixedWingState(); session = FixedWingV3Session(latest)
        session.observe(hello()); session.observe(mission()); session.observe(state())
        self.assertEqual('ack', session.observe(message('simulation_event', 4, {'event': 'reset_scene'}))['type'])
        self.assertIsNone(latest.snapshot()['state'])
        with self.assertRaisesRegex(ProtocolError, 'mission_plan'):
            session.observe(state(5))
        session.observe(mission(5))
        with self.assertRaisesRegex(ProtocolError, 'mission_end'):
            session.observe(message('simulation_event', 6, {'event': 'mission_end', 'mission_id': 'other'}))

    def test_send_frame_is_length_prefixed(self):
        left, right = socket.socketpair()
        try:
            send_frame(left, hello())
            self.assertEqual(hello(), recv_frame(right))
        finally:
            left.close(); right.close()

    def test_server_accepts_real_tcp_client_and_publishes_latest_state(self):
        latest = LatestFixedWingState()
        server = FixedWingV3BridgeServer(
            {'host': '127.0.0.1', 'port': 0, 'airsim_enabled': False}, latest)
        server.start()
        try:
            port = server._server.getsockname()[1]
            client = socket.create_connection(('127.0.0.1', port), 1.0)
            client.settimeout(1.0)
            try:
                for value in (hello(), mission()):
                    send_frame(client, value)
                    reply = recv_frame(client)
                    self.assertEqual('ack', reply['type'])
                    self.assertEqual(value['seq'], reply['data']['ref_seq'])
                send_frame(client, state())
                time.sleep(0.02)
                self.assertEqual(0.02, latest.snapshot()['state']['sim_time'])
            finally:
                client.close()
        finally:
            server.stop()


if __name__ == '__main__':
    unittest.main()
