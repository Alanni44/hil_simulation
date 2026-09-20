"""Safely validate and publish an immutable model package from GitLab."""
from __future__ import absolute_import

import os
import shutil
import stat
import uuid
import zipfile

from shared.model_package import package_sha256, validate_package


class GitLabStageError(ValueError):
    """Raised when a GitLab release cannot be staged safely."""


MAX_ARCHIVE_MEMBERS = 10000
MAX_SINGLE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


def _safe_component(value, label):
    if not isinstance(value, str) or not value or value in ('.', '..'):
        raise GitLabStageError('{0} is invalid.'.format(label))
    for forbidden in ('/', '\\', '\0'):
        if forbidden in value:
            raise GitLabStageError('{0} is invalid.'.format(label))
    return value


def _project_directory(project):
    return _safe_component(project.replace('/', '_'), 'GitLab project')


def _select_release(client, project, tag_name):
    _safe_component(tag_name, 'GitLab release tag')
    for release in client.list_releases(project):
        if release.get('tag_name') == tag_name:
            return release
    raise GitLabStageError('Requested GitLab release was not found.')


def _is_symlink(zip_info):
    mode = zip_info.external_attr >> 16
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _validated_archive_members(archive, limit):
    members = []
    total_size = 0
    root_name = None
    archive_members = archive.infolist()
    if len(archive_members) > MAX_ARCHIVE_MEMBERS:
        raise GitLabStageError('GitLab archive contains too many members.')
    for info in archive_members:
        name = info.filename.replace('\\', '/')
        if not name or name.startswith('/') or name.startswith('../'):
            raise GitLabStageError('GitLab archive contains an unsafe path.')
        normalized = os.path.normpath(name).replace('\\', '/')
        if normalized in ('.', '..') or normalized.startswith('../') or ':' in normalized.split('/')[0]:
            raise GitLabStageError('GitLab archive contains an unsafe path.')
        if _is_symlink(info):
            raise GitLabStageError('GitLab archive may not contain symbolic links.')
        if not info.is_dir():
            if info.file_size > min(limit, MAX_SINGLE_MEMBER_BYTES):
                raise GitLabStageError('GitLab archive contains an oversized member.')
            if info.file_size and (not info.compress_size or
                                   float(info.file_size) / info.compress_size > MAX_COMPRESSION_RATIO):
                raise GitLabStageError('GitLab archive contains an unsafe compression ratio.')
            total_size += info.file_size
            if total_size > limit:
                raise GitLabStageError('GitLab archive exceeds the configured size limit.')
        top_level = normalized.split('/', 1)[0]
        if root_name is None:
            root_name = top_level
        elif root_name != top_level:
            raise GitLabStageError('GitLab archive must contain one package directory.')
        members.append(info)
    if not members or root_name is None:
        raise GitLabStageError('GitLab archive is empty.')
    return members, root_name


def _extract_archive(payload, destination, limit):
    try:
        with zipfile.ZipFile(_bytes_stream(payload), 'r') as archive:
            members, root_name = _validated_archive_members(archive, limit)
            archive.extractall(destination, members)
    except (IOError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise GitLabStageError('GitLab release asset is not a valid ZIP package: {0}'.format(exc))
    return os.path.join(destination, root_name)


def _bytes_stream(payload):
    try:
        from io import BytesIO
    except ImportError:  # pragma: no cover
        from StringIO import StringIO as BytesIO
    if not isinstance(payload, bytes):
        raise GitLabStageError('GitLab release asset is invalid.')
    return BytesIO(payload)


def _staged_result(project, tag_name, release, package_path, controlled_root, validator,
                   digest=None, validated=None):
    """Revalidate one immutable local package and return public provenance."""
    if digest is None:
        digest = package_sha256(package_path)
    if validated is None:
        validated = validator(package_path, controlled_root, digest)
    manifest = validated.get('manifest', {})
    contract = validated.get('contract', {})
    return {
        'project': project,
        'tag_name': tag_name,
        'asset_name': release.get('asset_name'),
        'package_path': package_path,
        'package_sha256': digest,
        'model_ref': manifest.get('model_ref'),
        'model_revision_ref': manifest.get('model_revision_ref'),
        'model_name': contract.get('model_name'),
        'commit_id': release.get('commit_id'),
    }


def stage_release(client, project, tag_name, controlled_root, validator=validate_package):
    """Download, validate and atomically publish one immutable release package.

    ``validator`` is injectable solely to unit-test staging mechanics; normal
    callers use the strict local package validator.
    """
    if not isinstance(controlled_root, str) or not controlled_root:
        raise GitLabStageError('Controlled package root is invalid.')
    release = _select_release(client, project, tag_name)
    controlled_root = os.path.abspath(controlled_root)
    os.makedirs(controlled_root, exist_ok=True)
    project_part = _project_directory(project)
    tag_part = _safe_component(tag_name, 'GitLab release tag')
    published_path = os.path.join(controlled_root, 'gitlab', project_part, tag_part)
    if os.path.exists(published_path):
        # A receipt is intentionally short-lived and consumable. Re-staging a
        # previously verified immutable package must therefore issue a fresh
        # receipt, not require a re-download or permit an overwrite.
        try:
            return _staged_result(project, tag_name, release, published_path,
                                  controlled_root, validator)
        except Exception as exc:
            raise GitLabStageError(
                'Existing immutable GitLab package failed validation: {0}'.format(exc))

    payload = client.download_asset(release['asset_url'])
    staging_parent = os.path.join(controlled_root, '.gitlab-stage')
    staging_root = os.path.join(staging_parent, uuid.uuid4().hex)
    package_path = None
    try:
        os.makedirs(staging_root)
        limit = getattr(client, 'max_download_bytes', 512 * 1024 * 1024)
        package_path = _extract_archive(payload, staging_root, limit)
        digest = package_sha256(package_path)
        validated = validator(package_path, controlled_root, digest)
        if os.path.exists(published_path):
            raise GitLabStageError('GitLab release is already staged and immutable.')
        os.makedirs(os.path.dirname(published_path), exist_ok=True)
        os.replace(package_path, published_path)
        return _staged_result(project, tag_name, release, published_path,
                              controlled_root, validator, digest, validated)
    except GitLabStageError:
        raise
    except Exception as exc:
        raise GitLabStageError('GitLab package validation failed: {0}'.format(exc))
    finally:
        if os.path.isdir(staging_root):
            shutil.rmtree(staging_root)
