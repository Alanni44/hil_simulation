import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

import model_runtime  # noqa: E402


class Process(object):
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


class ModelRuntimeTests(unittest.TestCase):
    def test_waits_for_core_ready_before_control_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = pathlib.Path(temporary) / 'model'
            executable.write_text('#!/bin/sh\n')
            executable.chmod(0o755)
            settings = {
                'execution_mode': 'development', 'control_mode': 'builtin_mission',
                'executable_path': str(executable), 'mission_path': 'missions/z_mission.json',
                'runtime_log': str(pathlib.Path(temporary) / 'model.log'),
                'ready_sample_count': 1, 'startup_timeout_s': 1,
            }
            calls = []
            runtime = model_runtime.ModelRuntime(settings, popen=lambda *args, **kwargs: Process())
            runtime._wait_for_core_ready = mock.Mock(side_effect=lambda: calls.append('ready'))
            runtime._wait_for_fresh_samples = mock.Mock(side_effect=lambda: calls.append('fresh'))
            def core(cmd, params):
                calls.append(cmd)
                if cmd == 'get_hil_status':
                    return {'accepted': True, 'fields': {
                        'initial_state_abi': True, 'full_configuration_abi': True,
                        'lifecycle': 'CONFIGURED', 'control_source': 'none'}}
                return {'accepted': True}
            runtime._require_core = mock.Mock(side_effect=core)
            runtime._start()
            self.assertEqual(['ready', 'get_hil_status', 'select_control_source', 'load_mission', 'start', 'fresh'], calls)

    def test_retries_only_missing_udp_receipt_with_same_request_id(self):
        replies = [
            {'accepted': False, 'reason': 'C core receipt failed: timed out'},
            {'accepted': True, 'reason': 'accepted'},
        ]
        sent = []

        def request(command):
            sent.append(command)
            return replies.pop(0)

        runtime = model_runtime.ModelRuntime({'command_retry_attempts': 2,
                                              'command_retry_delay_s': 0}, request_core=request)
        runtime._require_core('select_control_source', {'source': 'demo_mission'})
        self.assertEqual(2, len(sent))
        self.assertEqual(sent[0]['request_id'], sent[1]['request_id'])
