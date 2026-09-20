import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / 'deploy' / 'systemd' / 'hil-deploy'


def load_helper():
    loader = importlib.machinery.SourceFileLoader('hil_deploy_test_helper', str(HELPER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SystemdDeployHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = pathlib.Path(self.temporary.name) / 'runtime'
        (self.runtime / 'work' / 'run-1').mkdir(parents=True)
        (self.runtime / 'pending').mkdir()
        (self.runtime / 'verified').mkdir()
        self.helper = load_helper()
        self.helper.RUNTIME_ROOT = str(self.runtime)

    def tearDown(self):
        self.temporary.cleanup()

    def write_descriptor(self, executable, sha256):
        with open(str(self.runtime / 'pending' / 'current.json'), 'w') as output:
            json.dump({'executable_path': str(executable), 'executable_sha256': sha256}, output)

    def test_accepts_a_hashed_executable_below_work_root(self):
        executable = self.runtime / 'work' / 'run-1' / 'model_rt'
        executable.write_bytes(b'verified model')
        executable.chmod(0o750)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        self.write_descriptor(executable, digest)

        pending, path, actual_digest = self.helper._read_descriptor('current')

        self.assertEqual(str(self.runtime / 'pending' / 'current.json'), pending)
        self.assertEqual(str(executable), path)
        self.assertEqual(digest, actual_digest)

    def test_rejects_an_executable_outside_work_root(self):
        outside = pathlib.Path(self.temporary.name) / 'outside_rt'
        outside.write_bytes(b'not controlled')
        self.write_descriptor(outside, hashlib.sha256(outside.read_bytes()).hexdigest())

        with self.assertRaisesRegex(self.helper.DeployError, 'outside the verified work root'):
            self.helper._read_descriptor('current')

    def test_rejects_invalid_hash_before_any_install(self):
        executable = self.runtime / 'work' / 'run-1' / 'model_rt'
        executable.write_bytes(b'fixture')
        self.write_descriptor(executable, 'not-a-sha256')

        with self.assertRaisesRegex(self.helper.DeployError, 'SHA-256 is invalid'):
            self.helper._read_descriptor('current')
