import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


class ZOperatorScriptStaticTests(unittest.TestCase):
    def test_start_requires_verified_model_and_launches_only_debug_path(self):
        source = read('scripts/start_z_debug.sh')

        self.assertIn('set -euo pipefail', source)
        self.assertIn('HIL_Z_MODEL_EXECUTABLE', source)
        self.assertIn('MODEL_EXECUTABLE', source)
        self.assertIn('[ -x "$MODEL_EXECUTABLE" ]', source)
        self.assertIn('python_services/debug_main.py', source)
        self.assertNotIn('python_services/main.py', source)
        self.assertNotRegex(source, r'\bws_server\b|\bwebsocket\b')
        self.assertLess(source.index('\n"$MODEL_EXECUTABLE" >'),
                        source.index(
                            '\n"$PYTHON_EXECUTABLE" -u '
                            '"$ROOT/python_services/debug_main.py"'))

    def test_start_preflights_exact_target_and_scopes_failure_cleanup(self):
        source = read('scripts/start_z_debug.sh')

        self.assertIn('192.168.100.172:5000', source)
        self.assertIn('runtime/z_debug', source)
        self.assertIn('sys.version_info[:3] == (3, 6, 9)', source)
        self.assertIn('load_mission(sys.argv[1])', source)
        self.assertIn('_bridge_waypoints(mission)', source)
        self.assertIn('_Runtime()', source)
        self.assertIn('RUN_LOCK="$RUN_DIR/run.lock"', source)
        self.assertIn('[ -f "$BUILD_SCRIPT" ]', source)
        self.assertIn('mkdir "$RUN_LOCK"', source)
        self.assertLess(source.index('mkdir "$RUN_LOCK"'),
                        source.index('\n"$MODEL_EXECUTABLE" >'))
        self.assertIn('trap cleanup_partial_start', source)
        self.assertIn('kill -0', source)
        self.assertNotRegex(source, r'\bsudo\b|\bkillall\b|\bpkill\b|\brm\s+-rf\b')

    def test_stop_checks_recorded_pid_ownership_and_is_idempotent(self):
        source = read('scripts/stop_z_debug.sh')

        self.assertIn('set -euo pipefail', source)
        self.assertIn('runtime/z_debug', source)
        self.assertIn('/proc/$pid/cmdline', source)
        self.assertIn('/proc/$pid/exe', source)
        self.assertIn('/proc/$pid/stat', source)
        self.assertIn('recorded_start', source)
        self.assertIn('current_start', source)
        self.assertIn('kill -0', source)
        self.assertIn('if ! kill "$pid"', source)
        self.assertIn('rmdir "$RUN_LOCK"', source)
        self.assertIn('No recorded Z debug run', source)
        self.assertNotRegex(source, r'\bkillall\b|\bpkill\b|\brm\s+-rf\b')
        self.assertLess(source.index('while recorded_process_is_alive'),
                        source.rindex('rm -f "$pid_file"'))

    def test_runtime_artifacts_are_ignored_and_runbook_has_required_commands(self):
        ignore = read('.gitignore')
        runbook = read('docs/z-mission-operator-runbook.md')

        self.assertIn('/runtime/z_debug/', ignore)
        self.assertIn('mini_ue4_sim.py --self-test', runbook)
        self.assertIn('./scripts/start_z_debug.sh', runbook)
        self.assertIn('./scripts/stop_z_debug.sh', runbook)
        self.assertIn('Ubuntu 18.04 RT', runbook)
        self.assertIn('MATLAB R2018b', runbook)
        self.assertIn('GCC 7.x', runbook)
        self.assertIn('Python 3.6.9', runbook)
        self.assertIn('192.168.100.172:5000', runbook)
        self.assertIn('LOCAL SIMULATOR PASSED', runbook)
        self.assertIn('REAL UE4 ACKNOWLEDGED', runbook)
        self.assertIn("grep -q '^VERSION_ID=\"18.04\"$' /etc/os-release",
                      runbook)
        self.assertIn("uname -a | grep -Eqi 'PREEMPT[ _-]?RT'", runbook)
        self.assertIn("sys.version_info[:3] == (3, 6, 9)", runbook)
        self.assertIn('python3 -m pip install --requirement requirements.txt',
                      runbook)
        self.assertIn('import yaml, debug_main', runbook)
        self.assertIn('gcc -dumpfullversion -dumpversion', runbook)
        self.assertIn('bash scripts/build_quadrotor_demo.sh', runbook)
        self.assertIn('readlink -f -- "$MODEL_EXECUTABLE"', runbook)
        self.assertIn('test -f "$MODEL_EXECUTABLE"', runbook)
        self.assertIn('test -x "$MODEL_EXECUTABLE"', runbook)


if __name__ == '__main__':
    unittest.main()
