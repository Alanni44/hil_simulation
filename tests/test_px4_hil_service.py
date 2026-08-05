import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from hil_adapters.px4_hil_service import Px4HilService  # noqa


class FakeAdapter(object):
    def __init__(self):
        self.sensors = []
        self.gps = []
        self.controls = None
        self.closed = False

    def send_sensor(self, value): self.sensors.append(value)
    def send_gps(self, value): self.gps.append(value)
    def poll_actuators(self): return self.controls
    def close(self): self.closed = True


def state():
    return {'north_m': 12.0, 'east_m': -3.0, 'down_m': -20.0,
            'vn_mps': 4.0, 've_mps': 1.0, 'vd_mps': 0.0,
            'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
            'ax_mps2': 0.4, 'ay_mps2': 0.5, 'az_mps2': -9.4}


class Px4HilServiceTests(unittest.TestCase):
    def test_step_sends_sensor_gps_and_truncated_px4_controls(self):
        adapter, sent = FakeAdapter(), []
        adapter.controls = {'controls': [0.1, 0.2, 0.3, 0.4, 0.5]}
        service = Px4HilService({'actuator_count': 4, 'imu_rate_hz': 250,
                                 'gps_rate_hz': 20}, adapter=adapter,
                                state_provider=state,
                                command_send=lambda command: (sent.append(command) or True),
                                clock=lambda: 10.0)
        service.step(now=10.0)
        self.assertEqual(1, len(adapter.sensors))
        self.assertEqual(1, len(adapter.gps))
        self.assertEqual([0.1, 0.2, 0.3, 0.4], sent[0]['params']['values'])
        self.assertEqual('px4_sitl', sent[0]['params']['source'])

    def test_no_state_does_not_emit_sensor(self):
        adapter = FakeAdapter()
        service = Px4HilService({}, adapter=adapter, state_provider=lambda: None,
                                command_send=lambda _: True, clock=lambda: 1.0)
        service.step(now=1.0)
        self.assertEqual(1, service.stats['state_misses'])
        self.assertFalse(adapter.sensors)


if __name__ == '__main__':
    unittest.main()
