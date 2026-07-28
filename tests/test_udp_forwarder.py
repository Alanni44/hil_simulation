import importlib
import pathlib
import socket
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))


class FakeSocket(object):
    def __init__(self):
        self.bound = None
        self.timeout = None
        self.closed = False

    def bind(self, address):
        self.bound = address

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        self.closed = True


class FakeThread(object):
    def __init__(self, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self):
        self.started = True


class UdpForwarderLifecycleTests(unittest.TestCase):
    def test_import_has_no_socket_side_effect_and_start_stop_owns_socket(self):
        sys.modules.pop('udp_forwarder', None)
        with mock.patch.object(socket, 'socket') as socket_factory:
            udp_forwarder = importlib.import_module('udp_forwarder')
        socket_factory.assert_not_called()

        fake_socket = FakeSocket()
        with mock.patch.object(udp_forwarder.socket, 'socket',
                               return_value=fake_socket), \
                mock.patch.object(udp_forwarder.threading, 'Thread',
                                  FakeThread):
            worker = udp_forwarder.start_udp_forwarder()
            udp_forwarder.stop_udp_forwarder()

        self.assertEqual(('0.0.0.0', 9998), fake_socket.bound)
        self.assertEqual(0.5, fake_socket.timeout)
        self.assertTrue(worker.daemon)
        self.assertTrue(worker.started)
        self.assertTrue(fake_socket.closed)


if __name__ == '__main__':
    unittest.main()
