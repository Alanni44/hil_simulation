#!/usr/bin/env python3
"""Strict local HIL model-package and contract validation.

This module deliberately contains no registry, download, activation history or
path discovery logic.  The external model-management system owns those
concerns; the HIL executor accepts one immutable package below its configured
controlled root.
"""
from __future__ import print_function

import hashlib
import json
import math
import os


REQUIRED_STATE_FIELDS = (
    'north_m', 'east_m', 'down_m',
    'vn_mps', 've_mps', 'vd_mps',
    'q_w', 'q_x', 'q_y', 'q_z',
    'p_radps', 'q_radps', 'r_radps', 'airborne',
)

REQUIRED_UNITS = {
    'north_m': 'm', 'east_m': 'm', 'down_m': 'm',
    'vn_mps': 'm/s', 've_mps': 'm/s', 'vd_mps': 'm/s',
    'q_w': '1', 'q_x': '1', 'q_y': '1', 'q_z': '1',
    'p_radps': 'rad/s', 'q_radps': 'rad/s', 'r_radps': 'rad/s',
    'airborne': 'bool',
}


class PackageError(ValueError):
    """A package or explicit contract is not deployable."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def package_sha256(package_path):
    """Hash package payload files deterministically, excluding its manifest.

    The manifest declares this digest, so including the manifest itself would
    make the declaration circular.  Symlinks are rejected by validation and
    consequently are not a meaningful input here.
    """
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(package_path):
        dirs.sort()
        files.sort()
        for filename in files:
            path = os.path.join(base, filename)
            relative = os.path.relpath(path, package_path).replace(os.sep, '/')
            if relative == 'package_manifest.json':
                continue
            digest.update(relative.encode('utf-8'))
            digest.update(b'\0')
            digest.update(sha256_file(path).encode('ascii'))
            digest.update(b'\0')
    return digest.hexdigest()


def _read_json(path, label):
    try:
        with open(path, 'r') as source:
            value = json.load(source)
    except (IOError, ValueError) as exc:
        raise PackageError('{} is invalid: {}'.format(label, exc))
    if not isinstance(value, dict):
        raise PackageError('{} must be a JSON object'.format(label))
    return value


def _require_string(value, label):
    if not isinstance(value, str) or not value:
        raise PackageError('{} must be a non-empty string'.format(label))
    return value


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_contract(contract):
    if contract.get('contract_version') != 1:
        raise PackageError('contract_version must equal 1')
    _require_string(contract.get('model_name'), 'contract.model_name')
    state = contract.get('state')
    if not isinstance(state, dict):
        raise PackageError('contract.state must be an object')
    if state.get('frame') != 'NED':
        raise PackageError('contract.state.frame must be NED')
    if state.get('orientation') != 'FRD_TO_NED_QUATERNION':
        raise PackageError('contract.state.orientation must be FRD_TO_NED_QUATERNION')
    outputs = state.get('outputs')
    units = state.get('units')
    if not isinstance(outputs, dict) or not isinstance(units, dict):
        raise PackageError('contract.state.outputs and contract.state.units must be objects')
    for field in REQUIRED_STATE_FIELDS:
        _require_string(outputs.get(field), 'contract.state.outputs.{}'.format(field))
        if units.get(field) != REQUIRED_UNITS[field]:
            raise PackageError('contract.state.units.{} must be {}'.format(
                field, REQUIRED_UNITS[field]))
    if len(set(outputs[field] for field in REQUIRED_STATE_FIELDS)) != len(REQUIRED_STATE_FIELDS):
        raise PackageError('each required state field must map to a distinct root output')

    parameters = contract.get('parameters')
    if not isinstance(parameters, list):
        raise PackageError('contract.parameters must be an array')
    names = set()
    for index, parameter in enumerate(parameters):
        label = 'contract.parameters[{}]'.format(index)
        if not isinstance(parameter, dict):
            raise PackageError('{} must be an object'.format(label))
        name = _require_string(parameter.get('name'), label + '.name')
        if name in names:
            raise PackageError('duplicate parameter {}'.format(name))
        names.add(name)
        _require_string(parameter.get('generated_field'), label + '.generated_field')
        if parameter.get('type') not in ('double', 'float', 'bool'):
            raise PackageError('{} has unsupported type'.format(label))
        _require_string(parameter.get('unit'), label + '.unit')
        if parameter.get('class') not in ('live', 'reset_only', 'readonly'):
            raise PackageError('{} has unsupported class'.format(label))
        phases = parameter.get('allowed_phases')
        if not isinstance(phases, list) or not phases or any(
                phase not in ('RUNNING', 'PAUSED', 'RESETTING', 'ENDED') for phase in phases):
            raise PackageError('{} has invalid allowed_phases'.format(label))
        for key in ('default', 'min', 'max'):
            value = parameter.get(key)
            if parameter.get('type') == 'bool':
                if not isinstance(value, bool):
                    raise PackageError('{}.{} must be boolean'.format(label, key))
            elif not _finite_number(value):
                raise PackageError('{}.{} must be a finite scalar'.format(label, key))
        if parameter.get('type') != 'bool' and parameter['min'] > parameter['max']:
            raise PackageError('{}.min must not exceed max'.format(label))
    return contract


def controlled_path(path, controlled_root):
    real_root = os.path.realpath(controlled_root)
    real_path = os.path.realpath(path)
    if real_path == real_root or not real_path.startswith(real_root + os.sep):
        raise PackageError('package_path is outside the controlled package root')
    return real_path


def validate_package(package_path, controlled_root, expected_sha256=None):
    package_path = controlled_path(package_path, controlled_root)
    if not os.path.isdir(package_path):
        raise PackageError('package_path is not a directory')
    for base, dirs, files in os.walk(package_path):
        for name in dirs + files:
            if os.path.islink(os.path.join(base, name)):
                raise PackageError('package must not contain symlinks')
    manifest = _read_json(os.path.join(package_path, 'package_manifest.json'),
                          'package_manifest.json')
    for key in ('model_ref', 'model_revision_ref', 'top_model', 'matlab_version',
                'files', 'package_sha256'):
        if key not in manifest:
            raise PackageError('package_manifest.json missing {}'.format(key))
    for key in ('model_ref', 'model_revision_ref', 'top_model', 'matlab_version',
                'package_sha256'):
        _require_string(manifest[key], 'manifest.{}'.format(key))
    if not isinstance(manifest['files'], dict) or not manifest['files']:
        raise PackageError('manifest.files must be a non-empty object')
    top_model = manifest['top_model']
    if not top_model.endswith('.slx') or '/' in top_model or '\\' in top_model:
        raise PackageError('manifest.top_model must name a package-root .slx')
    required_files = set(['hil_contract.json', top_model])
    payload_files = set()
    for base, _, names in os.walk(package_path):
        for name in names:
            relative = os.path.relpath(os.path.join(base, name), package_path).replace(os.sep, '/')
            if relative != 'package_manifest.json':
                payload_files.add(relative)
    if set(manifest['files']) != payload_files:
        raise PackageError('manifest.files must checksum every package payload file exactly once')
    for relative, expected in manifest['files'].items():
        if not isinstance(relative, str) or relative.startswith('/') or '..' in relative.split('/'):
            raise PackageError('manifest.files contains unsafe path')
        if not isinstance(expected, str) or len(expected) != 64:
            raise PackageError('manifest.files.{} must be a SHA-256'.format(relative))
        full_path = os.path.join(package_path, *relative.split('/'))
        if not os.path.isfile(full_path) or sha256_file(full_path) != expected:
            raise PackageError('file checksum mismatch: {}'.format(relative))
    if not required_files.issubset(set(manifest['files'])):
        raise PackageError('manifest.files must include top_model and hil_contract.json')
    actual_sha = package_sha256(package_path)
    if manifest['package_sha256'] != actual_sha:
        raise PackageError('package_sha256 mismatch')
    if expected_sha256 and expected_sha256 != actual_sha:
        raise PackageError('request package_sha256 mismatch')
    contract_path = os.path.join(package_path, 'hil_contract.json')
    contract = validate_contract(_read_json(contract_path, 'hil_contract.json'))
    if contract['model_name'] != os.path.splitext(top_model)[0]:
        raise PackageError('contract.model_name must match manifest.top_model')
    return {'path': package_path, 'manifest': manifest, 'contract': contract,
            'package_sha256': actual_sha, 'contract_sha256': sha256_file(contract_path)}
