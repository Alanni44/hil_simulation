import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import run_virtual_fc_tuning_demo as demo


def registry(current):
    return {'accepted': True, 'fields': {'parameters': [
        {'name': 'thrust_coefficient_n', 'class': 'live', 'review_status': 'approved',
         'type': 'double', 'current': current, 'min': 0.01, 'max': 100.0}]}}


class FakeClient(object):
    def __init__(self):
        self.calls = []
        self.responses = [
            {'accepted': True, 'virtual_fc': {'running': True, 'stats': {'commands_sent': 10}}},
            {'accepted': True}, {'accepted': True, 'initialized': True},
            {'sequence': 100}, registry(4.2),
            {'accepted': True, 'effective_sequence': 101},
            {'sequence': 102}, registry(4.284),
            {'accepted': True, 'virtual_fc': {'running': True, 'stats': {'commands_sent': 20}}},
            {'accepted': True, 'effective_sequence': 103}, {'sequence': 104}, {'accepted': True}]

    def command(self, cmd, params=None):
        self.calls.append((cmd, params or {}))
        return self.responses.pop(0)


class VirtualFcTuningDemoTest(unittest.TestCase):
    def test_demo_tunes_live_parameter_while_virtual_fc_runs_then_restores(self):
        client = FakeClient()
        evidence = demo.run_demo(client, settle_s=0.0, sleep=lambda _value: None, dashboard=False)
        self.assertEqual(evidence['parameter']['name'], 'thrust_coefficient_n')
        self.assertEqual(evidence['parameter']['effective_sequence'], 101)
        self.assertEqual(client.calls[1], ('select_control_source', {'source': 'physical_uut'}))
        self.assertEqual(client.calls[2][0], 'virtual_fc_start')
        self.assertEqual(client.calls[-3], ('tune', {'thrust_coefficient_n': 4.2}))
        self.assertEqual(client.calls[-2], ('get_state', {}))
        self.assertEqual(client.calls[-1], ('virtual_fc_stop', {}))

    def test_rejects_non_live_requested_parameter(self):
        with self.assertRaises(demo.DemoError):
            demo.choose_live_parameter(registry(4.2), 'not_present')

    def test_dashboard_includes_tuning_and_control_observations(self):
        page = demo.format_dashboard('observing', {
            'running': True, 'vehicle': {'vehicle_kind': 'multirotor'}, 'scenario': 'hover',
            'stats': {'commands_sent': 16, 'commands_rejected': 1, 'failsafe_events': 0},
            'closed_loop': {'estimate': {'position_ned_m': [1, 2, 3], 'velocity_ned_mps': [0.1, 0.2, 0.3]},
                            'sensor_age_ms': {'imu': 1.0, 'gps': 20.0}}},
            {'sequence': 110}, {'name': 'mass_kg', 'original': 1.0, 'current': 1.02,
                                'effective_sequence': 101}, {'commands_sent': 10})
        self.assertIn('mass_kg：1 → 1.02（+2.00%）；生效序号 101', page)
        self.assertIn('已生效：C 核心已跨越生效序号，在新参数下运行 9 个模型步', page)
        self.assertIn('调参观测期间新增 6 条飞控命令；链路连续', page)

    def test_dashboard_marks_tune_as_waiting_before_effective_sequence(self):
        page = demo.format_dashboard('tune_pending', {'running': True, 'stats': {}}, {'sequence': 100},
                                     {'name': 'mass_kg', 'original': 1.0, 'current': 1.02,
                                      'effective_sequence': 101})
        self.assertIn('等待生效：当前 C 核心序号尚未到达 101', page)

    def test_dashboard_waits_past_short_observation_window_for_effective_sequence(self):
        class WaitingClient(object):
            def __init__(self): self.index = 0
            def command(self, command, params=None):
                if command == 'virtual_fc_status':
                    return {'accepted': True, 'virtual_fc': {'running': True, 'stats': {}}}
                self.index += 1
                return {'sequence': 100 + self.index}
        client = WaitingClient()
        _virtual, state = demo.wait_with_dashboard(
            client, 0.0, 'observing', required_sequence=101, effective_timeout_s=1.0,
            interval_s=0.0, sleep=lambda _value: None, output=type('Sink', (), {
                'write': lambda self, _value: None, 'flush': lambda self: None})())
        self.assertGreater(state['sequence'], 101)

    def test_wait_for_sequence_requires_state_after_effective_boundary(self):
        class SequenceClient(object):
            def __init__(self): self.sequence = 101
            def command(self, _command, _params=None):
                self.sequence += 1
                return {'sequence': self.sequence}
        self.assertEqual(demo.wait_for_sequence(SequenceClient(), 102, interval_s=0.0,
                                                sleep=lambda _value: None)['sequence'], 103)


if __name__ == '__main__':
    unittest.main()
