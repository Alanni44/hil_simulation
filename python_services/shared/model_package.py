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
DEPENDENCY_KINDS = ('model_ref', 'data_dictionary', 'init_script', 'mat_data', 'custom_code')
REQUIRED_EXECUTION_LOCKS = (
    'solver_step_s', 'model_topology', 'port_schema', 'communication_endpoint',
)
REQUIRED_ENVIRONMENT_PORTS = {
    'wind_n_mps': ('m/s', 'double'), 'wind_e_mps': ('m/s', 'double'),
    'wind_d_mps': ('m/s', 'double'), 'pressure_pa': ('Pa', 'double'),
    'temperature_k': ('K', 'double'), 'ground_height_m': ('m', 'double'),
}
REQUIRED_FAULT_PORTS = {
    'gps_bias_n_m': ('m', 'double'), 'gps_bias_e_m': ('m', 'double'),
    'gps_bias_d_m': ('m', 'double'),
    'imu_bias_p_radps': ('rad/s', 'double'), 'imu_bias_q_radps': ('rad/s', 'double'),
    'imu_bias_r_radps': ('rad/s', 'double'),
    'motor_1_failed': ('bool', 'bool'), 'motor_2_failed': ('bool', 'bool'),
    'motor_3_failed': ('bool', 'bool'), 'motor_4_failed': ('bool', 'bool'),
    'command_delay_ms': ('ms', 'double'), 'sensor_delay_ms': ('ms', 'double'),
    'packet_loss_ratio': ('1', 'double'),
}
REQUIRED_AXIS_PORTS = ('throttle', 'roll_cmd', 'pitch_cmd', 'yaw_cmd')
REQUIRED_ACCELERATION_PORTS = ('ax_mps2', 'ay_mps2', 'az_mps2')


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


def _validate_port_descriptor(descriptor, label, expected_unit=None,
                              expected_type=None, expected_dimension=1):
    if not isinstance(descriptor, dict):
        raise PackageError('{} must be an object'.format(label))
    _require_string(descriptor.get('field'), label + '.field')
    if descriptor.get('unit') != expected_unit:
        raise PackageError('{}.unit must be {}'.format(label, expected_unit))
    if descriptor.get('type') != expected_type:
        raise PackageError('{}.type must be {}'.format(label, expected_type))
    if descriptor.get('dimension') != expected_dimension:
        raise PackageError('{}.dimension must be {}'.format(label, expected_dimension))
    minimum = descriptor.get('min')
    maximum = descriptor.get('max')
    if not _finite_number(minimum) or not _finite_number(maximum) or minimum > maximum:
        raise PackageError('{}.min and .max must be finite and ordered'.format(label))
    return descriptor


def _validate_port_group(group, label, required):
    if not isinstance(group, dict) or not isinstance(group.get('ports'), dict):
        raise PackageError('{}.ports must be an object'.format(label))
    ports = group['ports']
    for name, expected in required.items():
        if name not in ports:
            raise PackageError('{}.ports missing {}'.format(label, name))
        _validate_port_descriptor(ports[name], '{}.ports.{}'.format(label, name),
                                  expected[0], expected[1])
    return ports


def _validate_inputs(contract):
    inputs = contract.get('inputs')
    if not isinstance(inputs, dict):
        raise PackageError('contract.inputs must be an object')
    control = inputs.get('flight_control')
    if not isinstance(control, dict) or not isinstance(control.get('ports'), dict):
        raise PackageError('contract.inputs.flight_control.ports must be an object')
    mode = control.get('mode')
    ports = control['ports']
    if mode == 'axis_command':
        if 'motor_command' in ports:
            raise PackageError('axis_command and motor_command are mutually exclusive')
        for name in REQUIRED_AXIS_PORTS:
            if name not in ports:
                raise PackageError('flight_control axis_command missing {}'.format(name))
            _validate_port_descriptor(ports[name], 'contract.inputs.flight_control.ports.{}'.format(name),
                                      '1', 'double')
    elif mode == 'motor_command':
        if any(name in ports for name in REQUIRED_AXIS_PORTS):
            raise PackageError('motor_command and axis_command are mutually exclusive')
        if 'motor_command' not in ports:
            raise PackageError('flight_control motor_command missing motor_command')
        _validate_port_descriptor(ports['motor_command'],
                                  'contract.inputs.flight_control.ports.motor_command',
                                  '1', 'double', 4)
    else:
        raise PackageError('flight_control.mode must be axis_command or motor_command')
    _validate_port_group(inputs.get('environment'), 'contract.inputs.environment',
                         REQUIRED_ENVIRONMENT_PORTS)
    _validate_port_group(inputs.get('fault'), 'contract.inputs.fault', REQUIRED_FAULT_PORTS)
    mission = inputs.get('mission')
    if mission is not None:
        if not isinstance(mission, dict) or not isinstance(mission.get('enabled'), bool):
            raise PackageError('contract.inputs.mission.enabled must be boolean when mission is declared')
        if mission['enabled']:
            raise PackageError('contract mission-to-model bindings are not implemented; omit mission or set enabled=false')
    field_names = []
    for group_name in ('flight_control', 'environment', 'fault'):
        field_names.extend(item['field'] for item in inputs[group_name]['ports'].values())
    if len(set(field_names)) != len(field_names):
        raise PackageError('every declared model input must map to a distinct root input field')


def _validate_outputs(contract):
    outputs = contract.get('outputs')
    if not isinstance(outputs, dict) or not isinstance(outputs.get('internal_state'), dict):
        raise PackageError('contract.outputs.internal_state must be an object')
    internal = outputs['internal_state']
    if internal.get('rate_hz') != 50:
        raise PackageError('contract.outputs.internal_state.rate_hz must equal 50')
    if internal.get('include_in_ue4_json') is not False:
        raise PackageError('internal acceleration must be excluded from UE4 JSON')
    acceleration = internal.get('acceleration')
    if not isinstance(acceleration, dict):
        raise PackageError('contract.outputs.internal_state.acceleration must be an object')
    fields = []
    for name in REQUIRED_ACCELERATION_PORTS:
        if name not in acceleration:
            raise PackageError('contract.outputs.internal_state.acceleration missing {}'.format(name))
        descriptor = _validate_port_descriptor(
            acceleration[name], 'contract.outputs.internal_state.acceleration.{}'.format(name),
            'm/s2', 'double')
        fields.append(descriptor['field'])
    if len(set(fields)) != len(fields):
        raise PackageError('each acceleration field must map to a distinct root output')


def _validate_execution(contract):
    execution = contract.get('execution')
    if not isinstance(execution, dict):
        raise PackageError('contract.execution must be an object')
    if execution.get('step_s') != 0.001:
        raise PackageError('contract.execution.step_s must equal 0.001')
    locked = execution.get('locked_configuration')
    if not isinstance(locked, list) or not set(REQUIRED_EXECUTION_LOCKS).issubset(set(locked)):
        raise PackageError('contract.execution.locked_configuration is incomplete')


def validate_contract(contract):
    if contract.get('contract_version') != 2:
        raise PackageError('contract_version must equal 2')
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

    _validate_inputs(contract)
    _validate_outputs(contract)
    _validate_execution(contract)

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
        parameter_class = parameter.get('class')
        if parameter_class not in ('live', 'reset_only', 'readonly'):
            raise PackageError('{} has unsupported class'.format(label))
        phases = parameter.get('allowed_phases')
        if not isinstance(phases, list) or not phases or any(
                phase not in ('RUNNING', 'PAUSED', 'RESETTING', 'ENDED') for phase in phases):
            raise PackageError('{} has invalid allowed_phases'.format(label))
        if parameter_class == 'live' and (not set(phases).issubset(set(('RUNNING', 'PAUSED'))) or
                                          'RUNNING' not in phases):
            raise PackageError('{} live parameter must allow RUNNING only or RUNNING/PAUSED'.format(label))
        if parameter_class == 'reset_only' and phases != ['PAUSED']:
            raise PackageError('{} reset_only parameter must allow only PAUSED'.format(label))
        for key in ('default', 'min', 'max'):
            value = parameter.get(key)
            if parameter.get('type') == 'bool':
                if not isinstance(value, bool):
                    raise PackageError('{}.{} must be boolean'.format(label, key))
            elif not _finite_number(value):
                raise PackageError('{}.{} must be a finite scalar'.format(label, key))
        if parameter.get('type') != 'bool' and parameter['min'] > parameter['max']:
            raise PackageError('{}.min must not exceed max'.format(label))
        if parameter.get('type') != 'bool' and not (parameter['min'] <= parameter['default'] <= parameter['max']):
            raise PackageError('{}.default must be inside the declared range'.format(label))
        if parameter_class != 'readonly':
            binding = parameter.get('binding')
            if not isinstance(binding, dict):
                raise PackageError('{}.binding must be an object for writable parameter'.format(label))
            if binding.get('kind') == 'extu':
                _require_string(binding.get('field'), label + '.binding.field')
                if binding['field'] != parameter['generated_field']:
                    raise PackageError('{}.binding.field must match generated_field'.format(label))
            elif binding.get('kind') == 'exported_global':
                _require_string(binding.get('symbol'), label + '.binding.symbol')
            else:
                raise PackageError('{}.binding.kind must be extu or exported_global'.format(label))
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
                'files', 'package_sha256', 'dependencies'):
        if key not in manifest:
            raise PackageError('package_manifest.json missing {}'.format(key))
    for key in ('model_ref', 'model_revision_ref', 'top_model', 'matlab_version',
                'package_sha256'):
        _require_string(manifest[key], 'manifest.{}'.format(key))
    if not isinstance(manifest['files'], dict) or not manifest['files']:
        raise PackageError('manifest.files must be a non-empty object')
    if not isinstance(manifest['dependencies'], list):
        raise PackageError('manifest.dependencies must be an array')
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
    dependency_paths = []
    dependency_seen = set()
    for index, dependency in enumerate(manifest['dependencies']):
        label = 'manifest.dependencies[{}]'.format(index)
        if not isinstance(dependency, dict):
            raise PackageError('{} must be an object'.format(label))
        relative = _require_string(dependency.get('path'), label + '.path')
        if relative in dependency_seen:
            raise PackageError('duplicate dependency path {}'.format(relative))
        dependency_seen.add(relative)
        if not relative.startswith('dependencies/') or relative.startswith('/') or '..' in relative.split('/'):
            raise PackageError('{} must be a safe dependencies/ path'.format(label))
        if dependency.get('kind') not in DEPENDENCY_KINDS:
            raise PackageError('{} has unsupported kind'.format(label))
        if relative not in manifest['files']:
            raise PackageError('{} is not checksummed in manifest.files'.format(label))
        resolved = os.path.join(package_path, *relative.split('/'))
        if not os.path.isfile(resolved):
            raise PackageError('{} is not a package file'.format(label))
        dependency_paths.append(resolved)
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
            'package_sha256': actual_sha, 'contract_sha256': sha256_file(contract_path),
            'dependency_paths': dependency_paths,
            'dependency_relpaths': [item['path'] for item in manifest['dependencies']]}
