from __future__ import absolute_import

import io
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from shared.gitlab_release import GitLabReleaseClient, GitLabReleaseError, NoRedirectHandler


READY_CONFIG = {
    'enabled': True,
    'base_url': 'https://gitlab.example.test',
    'projects': ['uav/hil-models'],
    'release_asset_name': 'hil_model_package.zip',
    'timeout_seconds': 10,
    'max_download_mb': 1,
}


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200, headers=None):
        io.BytesIO.__init__(self, payload)
        self.status = status
        self.headers = headers or {}

    def getcode(self):
        return self.status


class RedirectedResponse(FakeResponse):
    def geturl(self):
        return 'https://untrusted.example.test/archive.zip'


class RecordingOpener(object):
    def __init__(self, response):
        self.response = response
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        return self.response


def unexpected_open(*args, **kwargs):
    raise AssertionError('network opener should not be called')


class GitLabReleaseClientTests(unittest.TestCase):
    def test_disabled_configuration_reports_not_configured_without_network(self):
        client = GitLabReleaseClient.from_config(
            {'enabled': False}, 'secret-token', unexpected_open
        )

        status = client.status()

        self.assertFalse(status['configured'])
        self.assertEqual(status['code'], 'NOT_CONFIGURED')
        self.assertEqual(status['allowed_project_count'], 0)
        self.assertNotIn('secret-token', status['message'])

    def test_missing_token_reports_not_configured_without_network(self):
        client = GitLabReleaseClient.from_config(
            READY_CONFIG, '', unexpected_open
        )

        status = client.status()

        self.assertFalse(status['configured'])
        self.assertEqual(status['code'], 'MISSING_TOKEN')
        self.assertEqual(status['allowed_project_count'], 1)

    def test_list_releases_uses_read_only_encoded_project_request(self):
        payload = json.dumps([
            {
                'tag_name': 'v1.2.0',
                'released_at': '2026-09-06T00:00:00Z',
                'commit': {'id': 'abc123'},
                'assets': {
                    'links': [
                        {'name': 'notes.txt', 'url': 'https://gitlab.example.test/notes'},
                        {
                            'name': 'hil_model_package.zip',
                            'url': 'https://gitlab.example.test/downloads/v1.2.0.zip',
                        },
                    ]
                },
            }
        ]).encode('utf-8')
        opener = RecordingOpener(FakeResponse(payload))
        client = GitLabReleaseClient.from_config(READY_CONFIG, 'secret-token', opener)

        releases = client.list_releases('uav/hil-models')

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]['tag_name'], 'v1.2.0')
        self.assertEqual(releases[0]['asset_url'], 'https://gitlab.example.test/downloads/v1.2.0.zip')
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertIn('/api/v4/projects/uav%2Fhil-models/releases', request.full_url)
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Private-token'), 'secret-token')
        self.assertEqual(timeout, 10)

    def test_rejects_projects_outside_configured_allowlist(self):
        client = GitLabReleaseClient.from_config(
            READY_CONFIG, 'secret-token', unexpected_open
        )

        with self.assertRaises(GitLabReleaseError):
            client.list_releases('different/project')

    def test_rejects_non_https_base_url_without_network(self):
        config = dict(READY_CONFIG)
        config['base_url'] = 'http://gitlab.example.test'
        client = GitLabReleaseClient.from_config(config, 'secret-token', unexpected_open)

        status = client.status()

        self.assertFalse(status['configured'])
        self.assertEqual(status['code'], 'INVALID_BASE_URL')

    def test_rejects_asset_download_redirected_to_another_origin(self):
        opener = RecordingOpener(RedirectedResponse(b'package'))
        client = GitLabReleaseClient.from_config(READY_CONFIG, 'secret-token', opener)

        with self.assertRaises(GitLabReleaseError):
            client.download_asset('https://gitlab.example.test/releases/v1.2.0.zip')

    def test_default_redirect_handler_never_constructs_a_follow_up_request(self):
        handler = NoRedirectHandler()
        request = handler.redirect_request(
            __import__('urllib.request').request.Request(
                'https://gitlab.example.test/api/v4/projects/1/releases'),
            FakeResponse(b'', status=302), 302, 'Found', {},
            'https://untrusted.example.test/asset.zip')

        self.assertIsNone(request)

    def test_download_is_rejected_when_it_exceeds_configured_byte_limit(self):
        opener = RecordingOpener(FakeResponse(b'x' * (1024 * 1024 + 1)))
        client = GitLabReleaseClient.from_config(READY_CONFIG, 'secret-token', opener)

        with self.assertRaises(GitLabReleaseError):
            client.download_asset('https://gitlab.example.test/releases/v1.2.0.zip')


if __name__ == '__main__':
    unittest.main()
