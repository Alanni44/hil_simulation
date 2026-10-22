import pathlib
import socket
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from service_startup import StartupError, preflight_listeners  # noqa: E402


class StartupTests(unittest.TestCase):
    def test_preflight_reports_bound_listener(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
            with self.assertRaises(StartupError):
                preflight_listeners((('test listener', socket.SOCK_STREAM, '127.0.0.1', port),))
        except PermissionError:
            self.skipTest('test environment does not permit loopback sockets')
        finally:
            probe.close()
