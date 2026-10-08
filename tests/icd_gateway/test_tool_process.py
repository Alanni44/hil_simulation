from dataclasses import FrozenInstanceError
import importlib.util
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from common import ROOT
from icd_runtime.errors import ICDError


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.tool_process'),
                             'shared bounded process supervision is missing')
        from input_simulator.tool_process import ProcessSupervisor
        self.Supervisor = ProcessSupervisor
        self.workers = []

    def tearDown(self):
        for worker in self.workers:
            worker.close()

    def worker(self, code, **kwargs):
        worker = self.Supervisor((sys.executable, '-c', code), cwd=ROOT, **kwargs)
        self.workers.append(worker)
        return worker

    def wait(self, worker):
        deadline = time.monotonic() + 8
        while True:
            value = worker.poll()
            if value.state != 'RUNNING':
                return value
            self.assertLess(time.monotonic(), deadline, 'actual direct process must become terminal')
            time.sleep(0.005)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as error:
            action()
        self.assertEqual(error.exception.code, code)

    def test_actual_binary_stdout_stderr_exit_and_immutable_snapshot(self):
        w = self.worker("import os; os.write(1,b'out\\x00\\xff'); os.write(2,b'err\\r\\n')")
        self.assertEqual(w.snapshot.state, 'NEW')
        initial = w.start()
        self.assertGreater(initial.pid, 0)
        value = self.wait(w)
        self.assertEqual(value.state, 'EXITED')
        self.assertEqual(value.stdout, b'out\x00\xff')
        self.assertEqual(value.stderr, b'err\r\n')
        self.assertEqual(value.returncode, 0)
        self.assertTrue(value.direct_child_terminal)
        self.assertTrue(value.output_complete)
        self.assertFalse(value.tree_cleanup_verified)
        self.assertFalse(value.execution_ready)
        self.assertGreaterEqual(value.completed_ns, value.started_ns)
        with self.assertRaises(FrozenInstanceError):
            value.stdout = b'changed'
        w.close()
        self.assertEqual(w.snapshot.stdout, value.stdout)

    def test_nonzero_exit_retains_actual_returncode_and_outputs(self):
        w = self.worker("import os; os.write(2,b'failure'); raise SystemExit(7)")
        w.start()
        value = self.wait(w)
        self.assertEqual((value.state, value.returncode, value.stderr), ('FAILED', 7, b'failure'))
        self.assertEqual(value.error, 'STATE')

    def test_output_limit_is_explicit_failure_not_silent_success(self):
        w = self.worker("import os; os.write(1,b'x'*1000000)", output_limit=127)
        w.start()
        value = self.wait(w)
        self.assertEqual((value.state, value.error), ('FAILED', 'BUFFER_FULL'))
        self.assertLessEqual(len(value.stdout) + len(value.stderr), 127)
        self.assertGreater(value.stdout_observed + value.stderr_observed, 127)
        self.assertFalse(value.output_complete)
        self.assertTrue(value.direct_child_terminal)

    def test_actual_large_both_streams_are_drained_without_deadlock(self):
        w = self.worker("import os; [(os.write(1,b'a'*4096),os.write(2,b'b'*4096)) for _ in range(40)]",
                        output_limit=400000)
        w.start()
        value = self.wait(w)
        self.assertEqual(value.state, 'EXITED')
        self.assertEqual(value.stdout, b'a' * 163840)
        self.assertEqual(value.stderr, b'b' * 163840)
        self.assertTrue(value.output_complete)

    def test_actual_timeout_kills_and_waits_for_direct_process(self):
        w = self.worker('import time; time.sleep(30)', timeout_ms=80)
        w.start()
        value = self.wait(w)
        self.assertEqual((value.state, value.error), ('FAILED', 'TIMEOUT'))
        self.assertIsNotNone(value.returncode)
        self.assertTrue(value.direct_child_terminal)

    def test_exit_observed_only_after_deadline_is_not_timely_success(self):
        w = self.worker('pass', timeout_ms=30)
        w.start()
        time.sleep(0.15)
        value = w.poll()
        self.assertEqual((value.state, value.error), ('FAILED', 'TIMEOUT'))
        self.assertFalse(value.output_complete)
        self.assertTrue(value.direct_child_terminal)

    def test_stop_after_already_completed_child_records_exit_not_invented_stop(self):
        w = self.worker("print('done')")
        w.start()
        time.sleep(0.15)
        value = w.stop()
        self.assertEqual(value.state, 'EXITED')
        self.assertEqual(value.stdout.strip(), b'done')
        self.assertEqual(value.returncode, 0)

    def test_stdout_and_stderr_share_one_limit(self):
        w = self.worker("import os; os.write(1,b'x'*90); os.write(2,b'y'*90)", output_limit=100)
        w.start()
        value = self.wait(w)
        self.assertEqual((value.state, value.error), ('FAILED', 'BUFFER_FULL'))
        self.assertEqual(len(value.stdout) + len(value.stderr), 100)

    def test_descendant_held_pipe_is_failure_not_complete_cleanup(self):
        w = self.worker("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.6)']); print('parent')",
                        timeout_ms=100, stop_timeout_ms=20)
        w.start()
        value = self.wait(w)
        self.assertEqual((value.state, value.error), ('FAILED', 'TIMEOUT'))
        self.assertTrue(value.direct_child_terminal)
        self.assertFalse(value.output_complete)
        self.assertFalse(value.tree_cleanup_verified)
        time.sleep(0.7)

    def test_natural_exit_with_late_pipe_eof_is_not_reported_as_stop(self):
        w = self.worker("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.3)']); print('parent')",
                        stop_timeout_ms=800)
        w.start()
        time.sleep(0.15)
        value = w.stop()
        self.assertEqual((value.state, value.returncode), ('EXITED', 0))
        self.assertTrue(value.output_complete)
        self.assertFalse(value.tree_cleanup_verified)

    def test_original_deadline_still_applies_during_natural_exit_pipe_wait(self):
        w = self.worker("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.4)']); print('parent')",
                        timeout_ms=250, stop_timeout_ms=800)
        w.start()
        deadline = time.monotonic() + 0.2
        while not w.poll().direct_child_terminal:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        self.assertEqual(w.snapshot.state, 'RUNNING')
        value = w.stop()
        self.assertEqual((value.state, value.error), ('FAILED', 'TIMEOUT'))
        self.assertFalse(value.output_complete)
        time.sleep(0.5)

    def test_manual_stop_and_close_are_terminal_but_not_remote_cleanup(self):
        w = self.worker("import os,time; os.write(1,b'started'); time.sleep(30)")
        w.start()
        deadline = time.monotonic() + 5
        while b'started' not in w.snapshot.stdout:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        value = w.stop()
        self.assertEqual(value.state, 'STOPPED')
        self.assertTrue(value.direct_child_terminal)
        self.assertEqual(value.stdout, b'started')
        self.assertFalse(value.tree_cleanup_verified)
        self.assertEqual(w.stop(), value)
        w.close()
        self.rejects('STATE', w.start)

    def test_shell_metacharacters_are_literal_arguments(self):
        w = self.Supervisor((sys.executable, '-c', 'import sys; print(sys.argv[1])', 'x; & | $(echo NO)'), cwd=ROOT)
        self.workers.append(w)
        w.start()
        self.assertEqual(self.wait(w).stdout.strip(), b'x; & | $(echo NO)')

    def test_start_is_once_and_close_before_start_is_permanent(self):
        w = self.worker('pass')
        w.close()
        self.assertEqual(w.snapshot.state, 'NEW')
        self.rejects('STATE', w.start)
        w2 = self.worker('pass')
        w2.start()
        self.rejects('STATE', w2.start)
        self.assertEqual(self.wait(w2).state, 'EXITED')

    def test_actual_creation_failure_is_retained_not_running(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td) / 'gone'
            cwd.mkdir()
            w = self.Supervisor((sys.executable, '-c', 'pass'), cwd=cwd)
            self.workers.append(w)
            cwd.rmdir()
            value = w.start()
            self.assertEqual((value.state, value.error), ('FAILED', 'RESOURCE'))
            self.assertIsNone(value.pid)
            self.assertIsNone(value.returncode)
            self.assertFalse(value.direct_child_terminal)
            self.rejects('STATE', w.start)

    def test_failed_stop_retains_actual_live_handle_for_later_retry(self):
        w = self.worker('import time; time.sleep(30)', stop_timeout_ms=20)
        w.start()
        with patch.object(subprocess.Popen, 'terminate', side_effect=OSError('cannot terminate')), \
                patch.object(subprocess.Popen, 'kill', side_effect=OSError('cannot kill')), \
                patch.object(subprocess.Popen, 'wait', side_effect=subprocess.TimeoutExpired('worker', 0.02)):
            value = w.stop()
        self.assertEqual((value.state, value.error), ('FAILED', 'STATE'))
        self.assertFalse(value.direct_child_terminal)
        value = w.stop()
        self.assertTrue(value.direct_child_terminal)
        self.assertEqual((value.state, value.error), ('FAILED', 'STATE'))

    def test_reader_start_failure_kills_actual_child_and_closes_unstarted_pipes(self):
        w = self.worker('import time; time.sleep(30)')
        with patch('input_simulator.tool_process.threading.Thread.start', side_effect=RuntimeError('reader failure')):
            value = w.start()
        self.assertEqual((value.state, value.error), ('FAILED', 'RESOURCE'))
        self.assertTrue(value.direct_child_terminal)
        self.assertFalse(value.output_complete)

    def test_os_wait_failure_is_retained_and_can_be_retried(self):
        w = self.worker('import time; time.sleep(30)', stop_timeout_ms=20)
        w.start()
        with patch.object(subprocess.Popen, 'wait', side_effect=OSError('wait failed')):
            value = w.stop()
        self.assertEqual((value.state, value.error), ('FAILED', 'STATE'))
        value = w.stop()
        self.assertTrue(value.direct_child_terminal)

    def test_strict_argv_paths_and_finite_integral_capacities(self):
        for argv in ('python -c pass', ['python'], (), ('python',), (sys.executable, '\x00')):
            self.rejects('SCHEMA', lambda: self.Supervisor(argv, cwd=ROOT))
        self.rejects('RESOURCE', lambda: self.Supervisor((str(ROOT / 'not-present'),), cwd=ROOT))
        self.rejects('SCHEMA', lambda: self.Supervisor((sys.executable,), cwd=Path('.')))
        for key, values in (('timeout_ms', (True, 0, 1.1, 3600001)),
                            ('stop_timeout_ms', (True, 0, 1.1, 10001)),
                            ('output_limit', (True, 0, 1.1, 67108865))):
            for value in values:
                self.rejects('CAPACITY', lambda: self.Supervisor((sys.executable,), cwd=ROOT, **{key: value}))


if __name__ == '__main__':
    unittest.main()
