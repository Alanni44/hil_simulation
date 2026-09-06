from __future__ import absolute_import

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

import ws_server


class FakeClient(object):
    def status(self):
        return {'configured': True, 'code': 'READY', 'message': 'ready'}

    def list_releases(self, project):
        return [{'tag_name': 'v1.0.0', 'asset_name': 'hil_model_package.zip'}]


class GitLabCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit_root = os.path.join(self.temp.name, 'audit')
        self.controlled_root = os.path.join(self.temp.name, 'controlled')
        self.patches = [
            mock.patch.object(ws_server, 'GITLAB_CLIENT', FakeClient()),
            mock.patch.object(ws_server, 'GITLAB_AUDIT_ROOT', self.audit_root),
            mock.patch.object(ws_server, 'CONTROLLED_PACKAGE_ROOT', self.controlled_root),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp.cleanup()

    def test_status_and_release_listing_are_read_only(self):
        status = ws_server._handle_gitlab_command('gitlab_status', {})
        releases = ws_server._handle_gitlab_command(
            'gitlab_list_releases', {'project': 'uav/hil-models'})

        self.assertEqual(status['status'], 'OK')
        self.assertEqual(status['gitlab']['code'], 'READY')
        self.assertEqual(releases['status'], 'OK')
        self.assertEqual(releases['releases'][0]['tag_name'], 'v1.0.0')

    def test_stage_writes_redacted_audit_record_and_returns_build_inputs(self):
        staged = {
            'project': 'uav/hil-models', 'tag_name': 'v1.0.0',
            'package_path': os.path.join(self.controlled_root, 'gitlab', 'uav_hil-models', 'v1.0.0'),
            'package_sha256': 'a' * 64, 'model_ref': 'model-42',
            'model_revision_ref': 'rev-9', 'model_name': 'example',
        }
        with mock.patch.object(ws_server, 'stage_release', return_value=staged) as stage:
            result = ws_server._handle_gitlab_command(
                'gitlab_stage_release',
                {'request_id': 'request-1', 'project': 'uav/hil-models', 'tag_name': 'v1.0.0'})

        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['build_request']['package_sha256'], 'a' * 64)
        stage.assert_called_once()
        history = ws_server._handle_gitlab_command('gitlab_history', {})
        self.assertEqual(len(history['events']), 1)
        self.assertEqual(history['events'][0]['action'], 'stage_release')
        serialized = repr(history)
        self.assertNotIn('PRIVATE-TOKEN', serialized)
        self.assertNotIn('secret', serialized.lower())

    def test_stage_requires_project_and_tag(self):
        result = ws_server._handle_gitlab_command('gitlab_stage_release', {'project': 'uav/hil-models'})

        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('tag_name', result['message'])


if __name__ == '__main__':
    unittest.main()
