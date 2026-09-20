from __future__ import absolute_import

import io
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from shared.gitlab_stage import GitLabStageError, stage_release


class FakeClient(object):
    def __init__(self, payload):
        self.payload = payload
        self.downloaded_urls = []

    def list_releases(self, project):
        return [{
            'tag_name': 'v1.0.0',
            'asset_name': 'hil_model_package.zip',
            'asset_url': 'https://gitlab.example.test/releases/v1.0.0.zip',
            'commit_id': 'abc123',
        }]

    def download_asset(self, asset_url):
        self.downloaded_urls.append(asset_url)
        return self.payload


def package_zip(entries):
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return content.getvalue()


class GitLabStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controlled_root = os.path.join(self.temp.name, 'controlled')

    def tearDown(self):
        self.temp.cleanup()

    def test_stages_validated_package_under_immutable_release_path(self):
        client = FakeClient(package_zip({'release/example.slx': b'model'}))
        calls = []

        def validator(package_path, controlled_root, expected_sha256):
            calls.append((package_path, controlled_root, expected_sha256))
            self.assertTrue(os.path.isfile(os.path.join(package_path, 'example.slx')))
            return {
                'manifest': {'model_ref': 'model-42', 'model_revision_ref': 'rev-9'},
                'contract': {'model_name': 'example'},
            }

        result = stage_release(client, 'uav/hil-models', 'v1.0.0', self.controlled_root, validator)

        self.assertEqual(result['model_ref'], 'model-42')
        self.assertEqual(result['model_revision_ref'], 'rev-9')
        self.assertTrue(os.path.isdir(result['package_path']))
        self.assertTrue(result['package_path'].startswith(os.path.abspath(self.controlled_root)))
        self.assertIn('uav_hil-models', result['package_path'])
        self.assertIn('v1.0.0', result['package_path'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(client.downloaded_urls), 1)

    def test_restage_revalidates_immutable_package_without_redownloading(self):
        client = FakeClient(package_zip({'release/example.slx': b'model'}))
        calls = []

        def validator(package_path, controlled_root, expected_sha256):
            calls.append((package_path, expected_sha256))
            return {
                'manifest': {'model_ref': 'model-42', 'model_revision_ref': 'rev-9'},
                'contract': {'model_name': 'example'},
            }

        first = stage_release(client, 'uav/hil-models', 'v1.0.0', self.controlled_root, validator)
        second = stage_release(client, 'uav/hil-models', 'v1.0.0', self.controlled_root, validator)

        self.assertEqual(first['package_path'], second['package_path'])
        self.assertEqual(first['package_sha256'], second['package_sha256'])
        self.assertEqual(len(client.downloaded_urls), 1)
        self.assertEqual(len(calls), 2)

    def test_rejects_zip_path_traversal_before_publish(self):
        client = FakeClient(package_zip({'../escape.txt': b'bad'}))

        with self.assertRaises(GitLabStageError):
            stage_release(client, 'uav/hil-models', 'v1.0.0', self.controlled_root,
                          lambda *args: self.fail('validator must not run'))

        self.assertFalse(os.path.exists(os.path.join(self.temp.name, 'escape.txt')))
        published_root = os.path.join(self.controlled_root, 'gitlab')
        self.assertFalse(os.path.exists(published_root))

    def test_rejects_unknown_release_without_download(self):
        client = FakeClient(package_zip({'release/example.slx': b'model'}))

        with self.assertRaises(GitLabStageError):
            stage_release(client, 'uav/hil-models', 'not-a-release', self.controlled_root,
                          lambda *args: self.fail('validator must not run'))

        self.assertEqual(client.downloaded_urls, [])

    def test_rejects_archive_with_excessive_member_count_before_validation(self):
        entries = {'release/{:05}.txt'.format(index): b'x' for index in range(10001)}
        client = FakeClient(package_zip(entries))
        validated = []

        with self.assertRaises(GitLabStageError):
            stage_release(client, 'uav/hil-models', 'v1.0.0', self.controlled_root,
                          lambda *args: validated.append(True))

        self.assertEqual(validated, [])

    def test_rejects_high_compression_ratio_before_validation(self):
        client = FakeClient(package_zip({'release/repetitive.bin': b'0' * (128 * 1024)}))
        validated = []

        with self.assertRaises(GitLabStageError):
            stage_release(client, 'uav/hil-models', 'v1.0.0', self.controlled_root,
                          lambda *args: validated.append(True))

        self.assertEqual(validated, [])
        staging_parent = os.path.join(self.controlled_root, '.gitlab-stage')
        self.assertFalse(os.path.exists(staging_parent) and os.listdir(staging_parent))


if __name__ == '__main__':
    unittest.main()
