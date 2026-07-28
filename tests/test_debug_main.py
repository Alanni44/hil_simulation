import importlib
import pathlib
import socket
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
PYTHON_SERVICES = ROOT / 'python_services'
sys.path.insert(0, str(PYTHON_SERVICES))


class DebugMainImportTests(unittest.TestCase):
    def test_import_does_not_create_a_network_socket_or_import_websocket(self):
        sys.modules.pop('debug_main', None)
        sys.modules.pop('ws_server', None)
        with mock.patch.object(socket, 'socket') as socket_factory:
            module = importlib.import_module('debug_main')

        socket_factory.assert_not_called()
        self.assertNotIn('ws_server', sys.modules)
        self.assertTrue(callable(module.main))


import debug_main  # noqa: E402


class FakeWorker(object):
    def __init__(self):
        self.join_timeouts = []

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)


class FakeRuntime(object):
    def __init__(self):
        self.calls = []
        self.udp_worker = FakeWorker()
        self.bridge_worker = FakeWorker()
        self.submitted = None

    def start_udp_forwarder(self):
        self.calls.append('start_udp')
        return self.udp_worker

    def stop_udp_forwarder(self):
        self.calls.append('stop_udp')

    def send_mission_plan(self, mission_id, waypoints):
        self.calls.append('submit_mission')
        self.submitted = (mission_id, waypoints)

    def start_bridge(self, host, port):
        self.calls.append(('start_bridge', host, port))
        return self.bridge_worker

    def stop_bridge(self):
        self.calls.append('stop_bridge')

    def get_bridge_status(self):
        return {
            'phase': 'mission plan acknowledged',
            'connected': True,
            'last_error': None,
        }

    def get_flight_data(self):
        return None


class DebugMainTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'debug_ue4_tcp': {'host': '192.168.100.172', 'port': 5000},
        }

    def test_repository_debug_target_is_explicit_and_valid(self):
        config = debug_main.load_config()
        target = debug_main.get_debug_target(config)
        self.assertEqual(('192.168.100.172', 5000), target)
        with self.assertRaises(ValueError):
            debug_main.get_debug_target(
                {'debug_ue4_tcp': {'host': '', 'port': 5000}})
        with self.assertRaises(ValueError):
            debug_main.get_debug_target(
                {'debug_ue4_tcp': {'host': '192.168.100.172', 'port': 70000}})

    def test_run_composes_only_udp_bridge_and_existing_z_mission(self):
        runtime = FakeRuntime()
        lines = []

        result = debug_main.run_debug(
            config=self.config,
            runtime=runtime,
            output_fn=lines.append,
            sleep_fn=lambda _seconds: None,
            max_updates=1)

        self.assertEqual(0, result)
        self.assertEqual(
            ['submit_mission', 'start_udp',
             ('start_bridge', '192.168.100.172', 5000),
             'stop_bridge', 'stop_udp'],
            runtime.calls)
        mission_id, waypoints = runtime.submitted
        self.assertEqual('z_mission_001', mission_id)
        self.assertEqual(
            [(0.0, 0.0, 20.0, 2.0),
             (40.0, 0.0, 20.0, 5.0),
             (0.0, 20.0, 20.0, 5.0),
             (40.0, 20.0, 20.0, 5.0)],
            [(item['x'], item['y'], item['height'], item['speed'])
             for item in waypoints])
        self.assertEqual([2.0], runtime.bridge_worker.join_timeouts)
        self.assertEqual([2.0], runtime.udp_worker.join_timeouts)

    def test_dashboard_snapshot_formats_target_v2_state_pose_and_error(self):
        rendered = debug_main.format_dashboard_snapshot(
            '192.168.100.172', 5000, 'z_mission_001',
            {'phase': 'state streaming', 'connected': True,
             'last_error': 'none'},
            {'position': {'x': 40.0, 'y': 20.0, 'height': 19.75},
             'attitude': {'roll': 0.01, 'pitch': -0.02, 'yaw': 1.5}})

        self.assertEqual(
            'UE4 192.168.100.172:5000 | V2 state streaming | connected\n'
            'Mission z_mission_001\n'
            'Position x=40.00 y=20.00 height=19.75 m\n'
            'Attitude roll=0.010 pitch=-0.020 yaw=1.500 rad\n'
            'Error none',
            rendered)

    def test_dashboard_snapshot_handles_absent_state(self):
        rendered = debug_main.format_dashboard_snapshot(
            '192.168.100.172', 5000, 'z_mission_001',
            {'phase': 'connecting', 'connected': False,
             'last_error': 'connection refused'}, None)

        self.assertIn('V2 connecting | disconnected', rendered)
        self.assertIn('Position unavailable', rendered)
        self.assertIn('Attitude unavailable', rendered)
        self.assertIn('Error connection refused', rendered)


if __name__ == '__main__':
    unittest.main()
