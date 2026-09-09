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
        return [{'tag_name': 'v1.0.0', 'asset_name': 'hil_model_package.zip',
                 'asset_url': 'https://gitlab.example.test/private/asset.zip'}]


class GitLabCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit_root = os.path.join(self.temp.name, 'audit')
        self.receipt_root = os.path.join(self.temp.name, 'receipts')
        self.controlled_root = os.path.join(self.temp.name, 'controlled')
        self.patches = [
            mock.patch.object(ws_server, 'GITLAB_CLIENT', FakeClient()),
            mock.patch.object(ws_server, 'GITLAB_AUDIT_ROOT', self.audit_root),
            mock.patch.object(ws_server, 'GITLAB_RECEIPT_ROOT', self.receipt_root),
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
        self.assertNotIn('asset_url', releases['releases'][0])

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
        self.assertIn('gitlab_stage_receipt', result['build_request'])
        stage.assert_called_once()
        history = ws_server._handle_gitlab_command('gitlab_history', {})
        self.assertEqual(len(history['events']), 1)
        self.assertEqual(history['events'][0]['action'], 'stage_release')
        self.assertEqual(history['events'][0]['outcome'], 'SUCCEEDED')
        serialized = repr(history)
        self.assertNotIn('PRIVATE-TOKEN', serialized)
        self.assertNotIn('secret', serialized.lower())

    def test_stage_receipt_replaces_client_supplied_build_provenance(self):
        staged = {
            'project': 'uav/hil-models', 'tag_name': 'v1.0.0',
            'package_path': os.path.join(self.controlled_root, 'gitlab', 'uav_hil-models', 'v1.0.0'),
            'package_sha256': 'a' * 64, 'model_ref': 'model-42',
            'model_revision_ref': 'rev-9', 'commit_id': 'abc123',
        }
        with mock.patch.object(ws_server, 'stage_release', return_value=staged):
            reply = ws_server._handle_gitlab_command(
                'gitlab_stage_release', {'project': 'uav/hil-models', 'tag_name': 'v1.0.0'})
        hydrated = ws_server._hydrate_gitlab_stage_receipt({
            'gitlab_stage_receipt': reply['build_request']['gitlab_stage_receipt'],
            'package_path': 'forged-path', 'package_sha256': 'f' * 64,
        }, 'build')

        self.assertEqual(hydrated['package_path'], staged['package_path'])
        self.assertEqual(hydrated['package_sha256'], staged['package_sha256'])
        self.assertTrue(hydrated['_gitlab_receipt_verified'])

    def test_stage_receipt_expires_and_each_operation_can_only_run_once(self):
        staged = {
            'project': 'uav/hil-models', 'tag_name': 'v1.0.0',
            'package_path': os.path.join(self.controlled_root, 'gitlab', 'uav_hil-models', 'v1.0.0'),
            'package_sha256': 'a' * 64, 'model_ref': 'model-42',
            'model_revision_ref': 'rev-9', 'commit_id': 'abc123',
        }
        with mock.patch.dict(ws_server.CONFIG['gitlab_release'],
                             {'stage_receipt_ttl_seconds': 60}, clear=False), \
                mock.patch.object(ws_server.time, 'time', return_value=1000):
            receipt_id = ws_server._create_gitlab_stage_receipt(staged)
            request = {'gitlab_stage_receipt': receipt_id}
            self.assertTrue(ws_server._hydrate_gitlab_stage_receipt(request, 'build')['_gitlab_receipt_verified'])
            self.assertTrue(ws_server._hydrate_gitlab_stage_receipt(request, 'deploy')['_gitlab_receipt_verified'])
            with self.assertRaisesRegex(ws_server.PackageError, 'already used'):
                ws_server._hydrate_gitlab_stage_receipt(request, 'build')
        with mock.patch.object(ws_server.time, 'time', return_value=1060):
            with self.assertRaisesRegex(ws_server.PackageError, 'expired'):
                ws_server._hydrate_gitlab_stage_receipt({'gitlab_stage_receipt': receipt_id}, 'deploy')

    def test_build_and_deploy_are_rejected_when_another_operation_holds_lock(self):
        self.assertTrue(ws_server.BUILD_DEPLOY_LOCK.acquire(False))
        try:
            request, result = ws_server._run_gitlab_build_or_deploy(
                {'gitlab_stage_receipt': 'a' * 32}, 'build')
        finally:
            ws_server.BUILD_DEPLOY_LOCK.release()
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('already running', result['message'])
        self.assertEqual(request['gitlab_stage_receipt'], 'a' * 32)

    def test_gitlab_enabled_defaults_to_loopback_listener(self):
        with mock.patch.dict(ws_server.CONFIG, {'gitlab_release': {'enabled': True}}, clear=False):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(ws_server._ws_listen_host(), '127.0.0.1')

    def test_stage_requires_project_and_tag(self):
        result = ws_server._handle_gitlab_command('gitlab_stage_release', {'project': 'uav/hil-models'})

        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('tag_name', result['message'])

    def test_failed_stage_is_recorded_without_error_secrets(self):
        with mock.patch.object(ws_server, 'stage_release',
                               side_effect=ws_server.GitLabStageError('secret-token rejected')):
            result = ws_server._handle_gitlab_command(
                'gitlab_stage_release',
                {'request_id': 'request-2', 'project': 'uav/hil-models', 'tag_name': 'v1.0.0'})

        self.assertEqual(result['status'], 'FAILED')
        history = ws_server._handle_gitlab_command('gitlab_history', {})
        event = next(item for item in history['events'] if item['action'] == 'stage_release')
        self.assertEqual(event['outcome'], 'FAILED')
        self.assertNotIn('secret-token', repr(event))

    def test_build_result_with_release_provenance_is_audited(self):
        ws_server._audit_gitlab_build_or_deploy({
            'operation': 'build', 'request_id': 'request-3', '_gitlab_receipt_verified': True,
            'gitlab_provenance': {
                'project': 'uav/hil-models', 'tag_name': 'v1.0.0',
                'commit_id': 'abc123', 'package_sha256': 'b' * 64,
            },
        }, {'status': 'READY', 'contract_sha256': 'c' * 64})

        history = ws_server._handle_gitlab_command('gitlab_history', {})
        event = next(item for item in history['events'] if item['action'] == 'build_package')
        self.assertEqual(event['outcome'], 'SUCCEEDED')
        self.assertEqual(event['contract_sha256'], 'c' * 64)

    def test_same_request_id_keeps_stage_and_build_audit_events(self):
        ws_server._write_gitlab_audit({'action': 'stage_release', 'outcome': 'SUCCEEDED',
                                       'request_id': 'same-request'})
        ws_server._write_gitlab_audit({'action': 'build_package', 'outcome': 'SUCCEEDED',
                                       'request_id': 'same-request'})

        events = ws_server._gitlab_history()

        self.assertEqual({event['action'] for event in events}, {'stage_release', 'build_package'})


if __name__ == '__main__':
    unittest.main()
