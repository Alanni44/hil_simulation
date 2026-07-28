import json
import pathlib
import socket
import sys
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

import bridge_tcp_client  # noqa: E402


WAYPOINTS = [
    {'x': 0.0, 'y': 0.0, 'height': 20.0, 'speed': 2.0},
    {'x': 40.0, 'y': 0.0, 'height': 20.0, 'speed': 5.0},
]


def recv_json_line(sock):
    data = bytearray()
    while not data.endswith(b'\n'):
        chunk = sock.recv(1)
        if not chunk:
            raise EOFError('peer closed before JSON line completed')
        data.extend(chunk)
    return json.loads(data.decode('utf-8'))


def send_fragmented_ack(sock, message, accepted=True, ref_type=None,
                        ref_seq=None):
    ack = {
        'protocol_version': '2.0',
        'type': 'ack',
        'seq': message['seq'] + 100,
        'vehicle_id': 'Drone1',
        'data': {
            'ref_type': ref_type or message['type'],
            'ref_seq': message['seq'] if ref_seq is None else ref_seq,
            'accepted': accepted,
        },
    }
    wire = json.dumps(ack).encode('utf-8') + b'\n'
    for split in (wire[:3], wire[3:11], wire[11:]):
        sock.sendall(split)


class BridgeTcpClientTests(unittest.TestCase):
    def test_json_line_fragment_survives_a_receive_timeout(self):
        client, peer = socket.socketpair()
        message = {
            'type': 'ack',
            'data': {'ref_type': 'hello', 'ref_seq': 1, 'accepted': True},
        }
        wire = json.dumps(message).encode('utf-8') + b'\n'
        try:
            peer.sendall(wire[:9])
            self.assertIsNone(bridge_tcp_client._frame_recv(client, 0.01))
            peer.sendall(wire[9:])
            self.assertEqual(message, bridge_tcp_client._frame_recv(client, 0.1))
        finally:
            client.close()
            peer.close()

    def test_hello_and_mission_acknowledgements_gate_state_publication(self):
        self.assertTrue(hasattr(bridge_tcp_client, '_perform_handshake'))
        client, peer = socket.socketpair()
        result = []
        state = {
            'sim_time_s': 1.25,
            'north_m': 10.0, 'east_m': 20.0, 'down_m': -30.0,
            'vn_mps': 1.0, 've_mps': 2.0, 'vd_mps': 3.0,
            'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
            'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
        }
        packet = bridge_tcp_client.state_cache.vehicle_state_v2_from_state(
            state, 'mission-a')

        def client_side():
            accepted = bridge_tcp_client._perform_handshake(
                client, 'mission-a', WAYPOINTS, ack_timeout=0.2)
            result.append(accepted)
            if accepted:
                bridge_tcp_client._vehicle_state_sender(
                    client, 'mission-a', threading.Event(), max_frames=1)

        with mock.patch.object(bridge_tcp_client.state_cache,
                               'get_vehicle_state_v2', return_value=packet):
            thread = threading.Thread(target=client_side)
            thread.start()
            try:
                hello = recv_json_line(peer)
                self.assertEqual('hello', hello['type'])
                peer.settimeout(0.03)
                with self.assertRaises(socket.timeout):
                    peer.recv(1)
                send_fragmented_ack(peer, hello)

                mission = recv_json_line(peer)
                self.assertEqual('mission_plan', mission['type'])
                send_fragmented_ack(peer, mission)
                state_message = recv_json_line(peer)
                self.assertEqual('vehicle_state', state_message['type'])
                thread.join(1.0)
                self.assertEqual([True], result)
            finally:
                client.close()
                peer.close()
                thread.join(1.0)

    def test_rejected_or_mismatched_ack_never_sends_mission(self):
        cases = (
            {'accepted': False},
            {'ref_type': 'mission_plan'},
            {'ref_seq': -1},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                client, peer = socket.socketpair()
                result = []

                def client_side():
                    result.append(bridge_tcp_client._perform_handshake(
                        client, 'mission-a', WAYPOINTS, ack_timeout=0.1))

                thread = threading.Thread(target=client_side)
                thread.start()
                try:
                    hello = recv_json_line(peer)
                    send_fragmented_ack(peer, hello, **changes)
                    thread.join(1.0)
                    self.assertEqual([False], result)
                    peer.settimeout(0.03)
                    with self.assertRaises(socket.timeout):
                        peer.recv(1)
                finally:
                    client.close()
                    peer.close()
                    thread.join(1.0)

    def test_vehicle_state_uses_exact_twenty_ms_cadence_and_protocol_fields(self):
        self.assertTrue(hasattr(bridge_tcp_client, '_vehicle_state_sender'))

        class FakeClock(object):
            def __init__(self):
                self.now = 10.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        class CaptureSocket(object):
            def __init__(self, clock):
                self.clock = clock
                self.messages = []

            def sendall(self, wire):
                self.messages.append((self.clock.now, json.loads(wire.decode('utf-8'))))

        state = {
            'sim_time_s': 1.25,
            'north_m': 10.0, 'east_m': 20.0, 'down_m': -30.0,
            'vn_mps': 1.0, 've_mps': 2.0, 'vd_mps': 3.0,
            'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
            'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
        }
        packet = bridge_tcp_client.state_cache.vehicle_state_v2_from_state(
            state, 'mission-a')
        clock = FakeClock()
        capture = CaptureSocket(clock)
        with mock.patch.object(bridge_tcp_client.state_cache,
                               'get_vehicle_state_v2', return_value=packet):
            bridge_tcp_client._vehicle_state_sender(
                capture, 'mission-a', threading.Event(), max_frames=3,
                monotonic_fn=clock.monotonic, sleep_fn=clock.sleep)

        self.assertEqual([10.0, 10.02, 10.04],
                         [round(item[0], 2) for item in capture.messages])
        for _, message in capture.messages:
            self.assertEqual(
                {'protocol_version', 'type', 'seq', 'vehicle_id', 'data'},
                set(message))
            self.assertEqual(
                {'mission_id', 'sim_time', 'position', 'attitude', 'velocity',
                 'angular_velocity'},
                set(message['data']))
            self.assertNotIn('acceleration', message['data'])
            self.assertNotIn('rate_hz', message['data'])
            self.assertNotIn('sequence', message['data'])

    def test_optional_mission_end_is_omitted_or_strictly_acknowledged(self):
        self.assertTrue(hasattr(bridge_tcp_client, '_send_mission_end'))
        client, peer = socket.socketpair()
        try:
            self.assertTrue(bridge_tcp_client._send_mission_end(
                client, 'mission-a', enabled=False, ack_timeout=0.1))
            peer.settimeout(0.03)
            with self.assertRaises(socket.timeout):
                peer.recv(1)

            result = []
            thread = threading.Thread(target=lambda: result.append(
                bridge_tcp_client._send_mission_end(
                    client, 'mission-a', enabled=True, ack_timeout=0.2)))
            thread.start()
            event = recv_json_line(peer)
            self.assertEqual('simulation_event', event['type'])
            self.assertEqual({'event': 'mission_end', 'mission_id': 'mission-a'},
                             event['data'])
            send_fragmented_ack(peer, event)
            thread.join(1.0)
            self.assertEqual([True], result)
        finally:
            client.close()
            peer.close()
            if 'thread' in locals():
                thread.join(1.0)


if __name__ == '__main__':
    unittest.main()
