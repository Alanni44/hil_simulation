import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from hil_adapters.physical_uut import SimulatedUutAdapter  # noqa


class SimulatedUutAdapterTests(unittest.TestCase):
    def test_keeps_sensor_history_and_returns_latest_control(self):
        adapter = SimulatedUutAdapter(max_history=2)
        adapter.publish_sensor({'sequence': 1})
        adapter.publish_sensor({'sequence': 2})
        adapter.inject_actuators([0.1, 0.2])
        adapter.inject_actuators([0.3, 0.4])
        self.assertEqual([0.3, 0.4], adapter.poll_actuators())
        self.assertIsNone(adapter.poll_actuators())
        self.assertEqual([1, 2], [item['sequence'] for item in adapter.sensor_history])

    def test_close_rejects_new_input(self):
        adapter = SimulatedUutAdapter()
        adapter.close()
        with self.assertRaises(RuntimeError):
            adapter.publish_sensor({'sequence': 1})


if __name__ == '__main__':
    unittest.main()
