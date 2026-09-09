"""Read-only client for approved GitLab model-release assets.

Credentials are supplied only by the process environment.  This module never
writes to GitLab and deliberately exposes no token value in responses or
exceptions.
"""
from __future__ import absolute_import

import json

try:
    from urllib.parse import quote, urlparse
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from urllib.error import HTTPError
except ImportError:  # pragma: no cover - retained for legacy Python runtime
    from urllib import quote
    from urlparse import urlparse
    from urllib2 import Request, build_opener, HTTPRedirectHandler, HTTPError


class GitLabReleaseError(ValueError):
    """Raised when a requested release cannot be accessed safely."""


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects before urllib can resend PRIVATE-TOKEN elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_DEFAULT_OPENER = build_opener(NoRedirectHandler())


def _open_without_redirects(request, timeout):
    return _DEFAULT_OPENER.open(request, timeout=timeout)


class GitLabReleaseClient(object):
    """Small allowlisted client for GitLab's release-list REST endpoint."""

    _MAX_RESPONSE_BYTES = 1024 * 1024

    def __init__(self, config, token, opener=None):
        self._config = config if isinstance(config, dict) else {}
        self._token = token or ''
        self._opener = opener or _open_without_redirects
        self._validation_code = self._validate_config()

    @classmethod
    def from_config(cls, config, token, opener=None):
        return cls(config, token, opener)

    def _validate_config(self):
        if self._config.get('enabled') is not True:
            return 'NOT_CONFIGURED'
        base_url = self._config.get('base_url')
        if not isinstance(base_url, str) or not base_url.strip():
            return 'INVALID_BASE_URL'
        parsed = urlparse(base_url.strip())
        allow_insecure_http = self._config.get('allow_insecure_http') is True
        allowed_schemes = ('https', 'http') if allow_insecure_http else ('https',)
        if parsed.scheme not in allowed_schemes or not parsed.netloc:
            return 'INVALID_BASE_URL'
        projects = self._config.get('projects')
        if not isinstance(projects, list) or not projects or not all(
                isinstance(project, str) and project.strip() for project in projects):
            return 'INVALID_PROJECTS'
        asset_name = self._config.get('release_asset_name')
        if not isinstance(asset_name, str) or not asset_name.strip():
            return 'INVALID_ASSET_NAME'
        timeout = self._config.get('timeout_seconds')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            return 'INVALID_TIMEOUT'
        max_download = self._config.get('max_download_mb')
        if isinstance(max_download, bool) or not isinstance(max_download, (int, float)) or max_download <= 0:
            return 'INVALID_DOWNLOAD_LIMIT'
        if not self._token:
            return 'MISSING_TOKEN'
        return None

    def status(self):
        """Return a browser-safe configuration state without making a request."""
        projects = self._config.get('projects')
        project_count = len(projects) if isinstance(projects, list) else 0
        if self._validation_code is None:
            return {
                'configured': True,
                'code': 'READY',
                'message': 'GitLab release integration is ready.',
                'allowed_project_count': project_count,
            }
        messages = {
            'NOT_CONFIGURED': 'GitLab release integration is disabled.',
            'INVALID_BASE_URL': 'GitLab base URL must be HTTPS, or HTTP with allow_insecure_http=true.',
            'INVALID_PROJECTS': 'GitLab project allowlist is invalid.',
            'INVALID_ASSET_NAME': 'GitLab release asset name is invalid.',
            'INVALID_TIMEOUT': 'GitLab request timeout is invalid.',
            'INVALID_DOWNLOAD_LIMIT': 'GitLab download limit is invalid.',
            'MISSING_TOKEN': 'GitLab access token is not configured.',
        }
        return {
            'configured': False,
            'code': self._validation_code,
            'message': messages[self._validation_code],
            'allowed_project_count': project_count,
        }

    @property
    def asset_name(self):
        return self._config.get('release_asset_name', '')

    @property
    def max_download_bytes(self):
        return int(self._config.get('max_download_mb', 0) * 1024 * 1024)

    def _require_ready(self):
        if self._validation_code is not None:
            raise GitLabReleaseError(self.status()['message'])

    def _require_allowed_project(self, project):
        if not isinstance(project, str) or project not in self._config['projects']:
            raise GitLabReleaseError('GitLab project is not in the configured allowlist.')

    def _base_url(self):
        return self._config['base_url'].strip().rstrip('/')

    def _request(self, url):
        request = Request(url, headers={'PRIVATE-TOKEN': self._token})
        try:
            response = self._opener(request, timeout=self._config['timeout_seconds'])
            status = response.getcode() if hasattr(response, 'getcode') else 200
            if status is not None and (status < 200 or status >= 300):
                raise GitLabReleaseError('GitLab returned HTTP status {0}.'.format(status))
            # urllib follows redirects by default.  Verify the final response
            # URL as well as the release asset URL we originally approved.
            final_url = response.geturl() if hasattr(response, 'geturl') else None
            if final_url and not self.is_safe_asset_url(final_url):
                if hasattr(response, 'close'):
                    response.close()
                raise GitLabReleaseError('GitLab redirected outside the configured origin.')
            return response
        except GitLabReleaseError:
            raise
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise GitLabReleaseError('GitLab redirect was rejected.')
            raise GitLabReleaseError('GitLab returned HTTP status {0}.'.format(exc.code))
        except Exception as exc:
            raise GitLabReleaseError('GitLab request failed: {0}'.format(exc.__class__.__name__))

    def _read_limited(self, response, limit):
        content_length = None
        headers = getattr(response, 'headers', None)
        if headers is not None:
            try:
                content_length = headers.get('Content-Length')
            except AttributeError:
                content_length = None
        if content_length:
            try:
                if int(content_length) > limit:
                    raise GitLabReleaseError('GitLab response exceeds the configured size limit.')
            except ValueError:
                pass
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise GitLabReleaseError('GitLab response exceeds the configured size limit.')
        return payload

    def list_releases(self, project):
        """List release metadata and the configured model-package asset only."""
        self._require_ready()
        self._require_allowed_project(project)
        project_id = quote(project, safe='')
        url = '{0}/api/v4/projects/{1}/releases'.format(self._base_url(), project_id)
        response = self._request(url)
        try:
            payload = self._read_limited(response, self._MAX_RESPONSE_BYTES)
        finally:
            if hasattr(response, 'close'):
                response.close()
        try:
            raw_releases = json.loads(payload.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise GitLabReleaseError('GitLab returned an invalid release response.')
        if not isinstance(raw_releases, list):
            raise GitLabReleaseError('GitLab returned an invalid release response.')

        releases = []
        for release in raw_releases:
            normalized = self._normalize_release(release)
            if normalized is not None:
                releases.append(normalized)
        return releases

    def _normalize_release(self, release):
        if not isinstance(release, dict):
            return None
        tag_name = release.get('tag_name')
        assets = release.get('assets')
        if not isinstance(tag_name, str) or not isinstance(assets, dict):
            return None
        links = assets.get('links')
        if not isinstance(links, list):
            return None
        asset_url = None
        for link in links:
            if isinstance(link, dict) and link.get('name') == self.asset_name:
                candidate_url = link.get('url')
                if self.is_safe_asset_url(candidate_url):
                    asset_url = candidate_url
                    break
        if asset_url is None:
            return None
        commit = release.get('commit') if isinstance(release.get('commit'), dict) else {}
        return {
            'tag_name': tag_name,
            'released_at': release.get('released_at'),
            'commit_id': commit.get('id'),
            'asset_name': self.asset_name,
            'asset_url': asset_url,
        }

    def is_safe_asset_url(self, asset_url):
        """Require the configured scheme and exact GitLab origin for assets."""
        if not isinstance(asset_url, str):
            return False
        expected = urlparse(self._base_url())
        actual = urlparse(asset_url)
        return actual.scheme == expected.scheme and actual.netloc == expected.netloc

    def download_asset(self, asset_url):
        """Download an already-verified release asset with a strict byte limit."""
        self._require_ready()
        if not self.is_safe_asset_url(asset_url):
            raise GitLabReleaseError('GitLab asset URL is outside the configured origin.')
        response = self._request(asset_url)
        try:
            return self._read_limited(response, self.max_download_bytes)
        finally:
            if hasattr(response, 'close'):
                response.close()
