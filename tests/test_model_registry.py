import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))
import ws_server  # noqa: E402


class ModelRegistryTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.temp_dir.name, 'models')
        self.ready_dir = os.path.join(self.temp_dir.name, 'run')
        os.makedirs(self.ready_dir)
        self.old_store = ws_server.MODEL_STORE
        self.old_ready_dir = ws_server.MODEL_READY_DIR
        self.old_ready_signal = ws_server.MODEL_READY_SIGNAL
        ws_server.MODEL_STORE = self.store
        ws_server.MODEL_READY_DIR = self.ready_dir
        ws_server.MODEL_READY_SIGNAL = os.path.join(self.temp_dir.name, 'legacy.signal')

    def tearDown(self):
        ws_server.MODEL_STORE = self.old_store
        ws_server.MODEL_READY_DIR = self.old_ready_dir
        ws_server.MODEL_READY_SIGNAL = self.old_ready_signal
        self.temp_dir.cleanup()

    def _successful_build(self, model_name='my_model', build_id='b001'):
        build_dir = os.path.join(self.store, 'registry', model_name, build_id)
        exe_dir = os.path.join(build_dir, 'executable')
        os.makedirs(exe_dir)
        executable = os.path.join(exe_dir, model_name + '_rt')
        with open(executable, 'wb') as handle:
            handle.write(b'not a real binary, but immutable test content')
        os.chmod(executable, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        with open(executable, 'rb') as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        with open(os.path.join(build_dir, 'manifest.json'), 'w') as handle:
            json.dump({
                'build_id': build_id,
                'model_name': model_name,
                'status': 'succeeded',
                'executable': {
                    'path': 'executable/{}_rt'.format(model_name),
                    'sha256': digest,
                },
            }, handle)
        return build_dir, executable

    def test_activation_is_checksum_verified_and_model_scoped(self):
        build_dir, executable = self._successful_build()
        activated = ws_server._activate_archived_build('my_model', 'b001')

        self.assertEqual(os.path.realpath(activated), os.path.realpath(executable))
        self.assertEqual(os.path.realpath(os.path.join(self.store, 'active', 'my_model')),
                         os.path.realpath(build_dir))
        with open(os.path.join(self.ready_dir, 'my_model.signal')) as handle:
            signal = json.load(handle)
        self.assertEqual('my_model', signal['model_name'])
        self.assertEqual('b001', signal['build_id'])
        self.assertFalse(os.path.exists(os.path.join(self.ready_dir, 'other_model.signal')))

        with open(executable, 'ab') as handle:
            handle.write(b'tampered')
        with self.assertRaises(ValueError):
            ws_server._activate_archived_build('my_model', 'b001')

    def test_remote_model_administration_fails_closed(self):
        old_value = ws_server.REMOTE_MODEL_ADMIN_ENABLED
        try:
            ws_server.REMOTE_MODEL_ADMIN_ENABLED = False
            self.assertIn('disabled', ws_server._remote_model_admin_error())
            ws_server.REMOTE_MODEL_ADMIN_ENABLED = True
            self.assertIsNone(ws_server._remote_model_admin_error())
        finally:
            ws_server.REMOTE_MODEL_ADMIN_ENABLED = old_value

    def test_source_tree_fingerprint_is_repeatable(self):
        first = ws_server._source_tree_sha256('c_core/src')
        second = ws_server._source_tree_sha256('c_core/src')
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))


if __name__ == '__main__':
    unittest.main()
