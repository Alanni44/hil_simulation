import os
import pathlib
import shutil
import shlex
import subprocess
import tempfile
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def find_bash():
    configured = os.environ.get('HIL_TEST_BASH')
    if configured:
        return configured
    discovered = shutil.which('bash')
    if discovered:
        return discovered
    for candidate in (r'D:\Git\bin\bash.exe',
                      r'C:\Program Files\Git\bin\bash.exe'):
        if os.path.isfile(candidate):
            return candidate
    return None


BASH = find_bash()


@unittest.skipUnless(BASH, 'Bash is required for operator-script behavior tests')
class ZOperatorBashBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temporary_directory.name) / 'repo'
        (self.repo / 'scripts').mkdir(parents=True)
        (self.repo / 'python_services').mkdir()
        (self.repo / 'missions').mkdir()
        shutil.copy2(str(ROOT / 'scripts' / 'start_z_debug.sh'),
                     str(self.repo / 'scripts' / 'start_z_debug.sh'))
        shutil.copy2(str(ROOT / 'scripts' / 'stop_z_debug.sh'),
                     str(self.repo / 'scripts' / 'stop_z_debug.sh'))
        (self.repo / 'python_services' / 'debug_main.py').write_text(
            '# hermetic test placeholder\n', encoding='utf-8')
        (self.repo / 'config.yaml').write_text(
            'debug_ue4_tcp: {host: 192.168.100.172, port: 5000}\n',
            encoding='utf-8')
        (self.repo / 'missions' / 'z_mission.json').write_text(
            '{}\n', encoding='utf-8')

        self.model_marker = self.repo / 'model-launched'
        self.debug_marker = self.repo / 'debug-launched'
        self.model = self.repo / 'fake-model'
        self.python = self.repo / 'fake-python'
        self.model.write_text(
            '#!/usr/bin/env bash\n'
            'printf "launched\\n" >>"%s"\n'
            "trap 'exit 0' TERM INT\n"
            'while :; do sleep 1; done\n' %
            self.to_bash_path(self.model_marker),
            encoding='utf-8')
        self.python.write_text(
            '#!/usr/bin/env bash\n'
            'if [ "${1:-}" = "-c" ]; then\n'
            '  case "${2:-}" in\n'
            '    *sys.version_info*) exit 0 ;;\n'
            '    *) printf "192.168.100.172:5000\\n"; exit 0 ;;\n'
            '  esac\n'
            'fi\n'
            'printf "launched\\n" >>"%s"\n'
            "trap 'exit 0' TERM INT\n"
            'while :; do sleep 1; done\n' %
            self.to_bash_path(self.debug_marker),
            encoding='utf-8')
        self.bash('chmod', '755', self.to_bash_path(self.model),
                  self.to_bash_path(self.python),
                  self.to_bash_path(self.repo / 'scripts' / 'start_z_debug.sh'),
                  self.to_bash_path(self.repo / 'scripts' / 'stop_z_debug.sh'))
        self.environment = os.environ.copy()
        self.environment['HIL_Z_PYTHON'] = self.to_bash_path(self.python)
        self.environment['HIL_Z_MODEL_EXECUTABLE'] = self.to_bash_path(
            self.model)

    def tearDown(self):
        stop_script = self.repo / 'scripts' / 'stop_z_debug.sh'
        if stop_script.exists():
            self.bash('chmod', '755', self.to_bash_path(stop_script),
                      check=False)
            subprocess.run(
                [BASH, self.to_bash_path(stop_script)],
                env=self.environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=15,
                check=False)
        self.temporary_directory.cleanup()

    def to_bash_path(self, path):
        if os.name != 'nt' and not shutil.which('cygpath'):
            return str(path)
        return subprocess.check_output(
            [BASH, '-lc', 'cygpath -u "$1"', 'bash', str(path)],
            universal_newlines=True).strip()

    def bash(self, *arguments, **kwargs):
        check = kwargs.pop('check', True)
        return subprocess.run(
            [BASH, '-lc', ' '.join(shlex.quote(value)
                                   for value in arguments)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=15,
            check=check)

    def start_command(self):
        return [BASH,
                self.to_bash_path(self.repo / 'scripts' / 'start_z_debug.sh')]

    def wait_for(self, path, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return
            time.sleep(0.02)
        self.fail('timed out waiting for {}'.format(path))

    def test_concurrent_stop_cannot_release_a_startup_owned_lock(self):
        run_dir = self.repo / 'runtime' / 'z_debug'
        run_dir.mkdir(parents=True)
        owner_ready = run_dir / 'startup-owner-ready'
        owner_release = run_dir / 'startup-owner-release'
        owner = subprocess.Popen(
            [BASH, '-lc',
             ('mkdir "$1" && printf "ready\\n" >"$2" && '
              'while [ ! -f "$3" ]; do sleep 0.05; done'),
             'bash', self.to_bash_path(run_dir / 'run.lock'),
             self.to_bash_path(owner_ready),
             self.to_bash_path(owner_release)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        try:
            self.wait_for(owner_ready)
            stop = subprocess.run(
                [BASH, self.to_bash_path(
                    self.repo / 'scripts' / 'stop_z_debug.sh')],
                env=self.environment, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, universal_newlines=True,
                timeout=10, check=False)
            second = subprocess.run(
                self.start_command(), env=self.environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=10, check=False)

            self.assertNotEqual(0, stop.returncode, stop.stdout + stop.stderr)
            self.assertNotEqual(0, second.returncode,
                                second.stdout + second.stderr)
            self.assertIn('owns', second.stderr)
        finally:
            owner_release.write_text('release\n', encoding='utf-8')
            owner.communicate(timeout=5)

    def test_non_executable_stop_script_blocks_start_before_model_launch(self):
        stop_script = self.repo / 'scripts' / 'stop_z_debug.sh'
        stop_path = self.to_bash_path(stop_script)
        self.bash('chmod', '644', stop_path)
        environment = self.environment.copy()
        if subprocess.run(
                [BASH, '-lc', '[ ! -x "$1" ]', 'bash', stop_path],
                check=False).returncode != 0:
            # MSYS derives executability for shebang scripts from Windows
            # file semantics and cannot represent chmod -x. Disable Bash's
            # `[` builtin and inject only the missing permission result.
            fake_bin = self.repo / 'fake-bin'
            fake_bin.mkdir()
            bracket = fake_bin / '['
            bracket.write_text(
                '#!/usr/bin/env bash\n'
                'if /usr/bin/[ "${1:-}" = "-x" ] &&\n'
                '        /usr/bin/[ "${2:-}" = '
                '"$HIL_TEST_NON_EXECUTABLE" ]; then\n'
                '    exit 1\n'
                'fi\n'
                'exec /usr/bin/[ "$@"\n', encoding='utf-8')
            bash_environment = self.repo / 'disable-bracket-builtin'
            bash_environment.write_text(
                'enable -n [\n'
                'PATH="$HIL_TEST_FAKE_BIN:$PATH"\n', encoding='utf-8')
            self.bash('chmod', '755', self.to_bash_path(bracket))
            environment['BASH_ENV'] = self.to_bash_path(bash_environment)
            environment['HIL_TEST_FAKE_BIN'] = self.to_bash_path(fake_bin)
            environment['HIL_TEST_NON_EXECUTABLE'] = stop_path

        result = subprocess.run(
            self.start_command(), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=10, check=False)

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn('stop_z_debug.sh', result.stderr)
        self.assertIn('not executable', result.stderr)
        self.assertFalse(self.model_marker.exists(),
                         'model launched before stop-script preflight failed')


if __name__ == '__main__':
    unittest.main()
