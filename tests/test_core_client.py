import json
import pathlib
import socket
import sys
import threading
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

import core_client  # noqa: E402


class CoreClientTests(unittest.TestCase):
    def test_core_request_sends_exact_load_mission_command_and_matches_receipt(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(('127.0.0.1', 0))
        host, port = server.getsockname()
        received = []

        command = {
            'request_id': 'debug-load-z_mission_001',
            'cmd': 'load_mission',
            'params': {
                'mission_id': 'z_mission_001',
                'completion_radius_m': 1.0,
                'waypoints': [
                    {'id': 'TAKEOFF', 'north_m': 0.0, 'east_m': 0.0,
                     'down_m': -20.0, 'speed_mps': 2.0},
                    {'id': 'Z1', 'north_m': 40.0, 'east_m': 0.0,
                     'down_m': -20.0, 'speed_mps': 5.0},
                    {'id': 'Z2', 'north_m': 0.0, 'east_m': 20.0,
                     'down_m': -20.0, 'speed_mps': 5.0},
                ],
                'landing': {
                    'id': 'LAND', 'north_m': 40.0, 'east_m': 20.0,
                    'down_m': 0.0, 'speed_mps': 1.5,
                },
            },
        }

        def core_peer():
            payload, sender = server.recvfrom(65536)
            received.append(json.loads(payload.decode('utf-8')))
            server.sendto(json.dumps({
                'request_id': 'debug-load-z_mission_001',
                'accepted': True,
                'reason': 'mission accepted as explicit NED route',
                'effective_sequence': 8,
                'lifecycle': 'RUNNING',
            }).encode('utf-8'), sender)

        peer = threading.Thread(target=core_peer)
        peer.start()
        try:
            receipt = core_client.core_request(
                command, host=host, port=port, timeout_s=0.5)
            peer.join(1.0)
        finally:
            server.close()
            peer.join(1.0)

        self.assertEqual([command], received)
        self.assertTrue(receipt['accepted'])
        self.assertEqual(8, receipt['effective_sequence'])


if __name__ == '__main__':
    unittest.main()
