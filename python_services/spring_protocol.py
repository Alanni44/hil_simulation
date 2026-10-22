#!/usr/bin/env python3
"""HIL ↔ Spring WebSocket V0.3 message validation and state projection."""
from __future__ import absolute_import

import hashlib
import json
import math
import re
import time

from shared.flight_state import LIFECYCLE_NAMES


class ProtocolError(ValueError):
    """An input does not conform to the small V0.3 application envelope."""
    def __init__(self, message, request_id=None):
        ValueError.__init__(self, message)
        self.request_id = request_id


def parse_command(payload):
    """Return ``(request_id, action)`` for one contract COMMAND text frame."""
    try:
        message = json.loads(payload)
    except (TypeError, ValueError):
        raise ProtocolError('invalid JSON')
    if not isinstance(message, dict):
        raise ProtocolError('message must be a JSON object')
    request_id = message.get('request_id')
    if not isinstance(request_id, str) or not request_id:
        raise ProtocolError('request_id must be a non-empty string')
    if len(request_id) > 128:
        raise ProtocolError('request_id exceeds 128 characters')
    if message.get('type') != 'COMMAND':
        raise ProtocolError('type must be COMMAND', request_id)
    data = message.get('data')
    if not isinstance(data, dict):
        raise ProtocolError('data must be an object', request_id)
    action = data.get('action')
    if action not in ('START', 'STOP'):
        raise ProtocolError('data.action must be START or STOP', request_id)
    return request_id, action


def command_result(request_id, accepted, reason):
    """Build a receipt; ``accepted`` deliberately is not an execution result."""
    return {'type': 'COMMAND_RESULT', 'request_id': request_id,
            'data': {'accepted': bool(accepted), 'reason': str(reason)}}


MAX_CREATE_PARAMS_BYTES = 1024 * 1024
CREATE_PARAMS_FIELDS = (
    'package_ref', 'scenario_ref', 'mode', 'source_binding_ref',
    'link_ids', 'baseline_sha256', 'run_configuration', 'source_inputs',
)
_HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')


class InitializeRequest(object):
    """One validated first-circle INITIALIZE request."""

    __slots__ = ('request_id', 'model_id', 'config_id', 'config_sha256', 'raw',
                 'create_params', 'run_configuration', 'baseline_sha256')

    def __init__(self, request_id, model_id, config_id, config_sha256, raw,
                 create_params, run_configuration, baseline_sha256):
        self.request_id = request_id
        self.model_id = model_id
        self.config_id = config_id
        self.config_sha256 = config_sha256
        self.raw = raw
        self.create_params = create_params
        self.run_configuration = run_configuration
        self.baseline_sha256 = baseline_sha256


def _bounded_text(value, label, request_id, maximum=128):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ProtocolError('{} must be a bounded non-empty string'.format(label), request_id)
    return value


def _hash_text(value, label, request_id):
    if not isinstance(value, str) or _HASH_PATTERN.match(value) is None:
        raise ProtocolError('{} must be 64 lowercase hexadecimal characters'.format(label), request_id)
    return value


def _strict_json(text, request_id):
    """Parse create_params_json without duplicate keys or non-JSON constants."""
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key {!r}'.format(key))
            result[key] = value
        return result

    def constant(value):
        raise ValueError('invalid JSON numeric literal {}'.format(value))

    try:
        return json.loads(text, object_pairs_hook=object_pairs, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError('create_params_json is not valid JSON: {}'.format(exc), request_id)


def _check_json_domain(value, request_id, depth=0):
    """Match the project's strict JSON domain before canonicalization downstream."""
    if depth > 128:
        raise ProtocolError('create_params_json nesting exceeds 128', request_id)
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        try:
            representable = math.isfinite(float(value)) and int(float(value)) == value
        except OverflowError:
            representable = False
        if not representable:
            raise ProtocolError('create_params_json integer loses IEEE754 precision', request_id)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError('create_params_json contains a non-finite number', request_id)
    elif isinstance(value, str):
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ProtocolError('create_params_json contains an isolated surrogate', request_id)
    elif isinstance(value, list):
        for item in value:
            _check_json_domain(item, request_id, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError('create_params_json keys must be strings', request_id)
            _check_json_domain(key, request_id, depth + 1)
            _check_json_domain(item, request_id, depth + 1)
    else:
        raise ProtocolError('create_params_json is outside the JSON domain', request_id)


def _resource_ref(value, label, id_name, hash_name, request_id):
    if not isinstance(value, dict):
        raise ProtocolError('{} must be an object'.format(label), request_id)
    _bounded_text(value.get(id_name), '{}.{}'.format(label, id_name), request_id)
    _bounded_text(value.get('revision'), '{}.revision'.format(label), request_id)
    fingerprint = _hash_text(value.get(hash_name), '{}.{}'.format(label, hash_name), request_id)
    if fingerprint == '0' * 64:
        raise ProtocolError('{}.{} is an unresolved all-zero placeholder'.format(
            label, hash_name), request_id)


def _link_ids(value, request_id):
    if not isinstance(value, list) or not 1 <= len(value) <= 10000:
        raise ProtocolError('link_ids must be a non-empty array', request_id)
    seen = set()
    for item in value:
        _bounded_text(item, 'link_ids item', request_id)
        if item in seen:
            raise ProtocolError('link_ids must be unique', request_id)
        seen.add(item)


def parse_initialize(payload):
    """Validate one INITIALIZE text frame and return its verified request.

    ``config_sha256`` is recomputed over the raw UTF-8 bytes of
    ``create_params_json``; the outer frame bytes never participate.
    """
    try:
        message = json.loads(payload)
    except (TypeError, ValueError):
        raise ProtocolError('invalid JSON')
    if not isinstance(message, dict):
        raise ProtocolError('message must be a JSON object')
    request_id = message.get('request_id')
    if not isinstance(request_id, str) or not request_id:
        raise ProtocolError('request_id must be a non-empty string')
    if len(request_id) > 128:
        raise ProtocolError('request_id exceeds 128 characters')
    if message.get('type') != 'INITIALIZE':
        raise ProtocolError('type must be INITIALIZE', request_id)
    data = message.get('data')
    if not isinstance(data, dict):
        raise ProtocolError('data must be an object', request_id)
    expected = {'model_id', 'config_id', 'config_sha256', 'create_params_json'}
    if set(data) != expected:
        raise ProtocolError('data fields differ from the INITIALIZE contract', request_id)
    model_id = _bounded_text(data['model_id'], 'data.model_id', request_id)
    config_id = _bounded_text(data['config_id'], 'data.config_id', request_id)
    config_sha256 = _hash_text(data['config_sha256'], 'data.config_sha256', request_id)
    text = data['create_params_json']
    if not isinstance(text, str) or not text:
        raise ProtocolError('data.create_params_json must be a non-empty string', request_id)
    try:
        raw = text.encode('utf-8')
    except UnicodeError:
        raise ProtocolError('data.create_params_json is not valid UTF-8 text', request_id)
    if len(raw) > MAX_CREATE_PARAMS_BYTES:
        raise ProtocolError('data.create_params_json exceeds 1 MiB', request_id)
    if hashlib.sha256(raw).hexdigest() != config_sha256:
        raise ProtocolError(
            'data.config_sha256 does not match create_params_json UTF-8 bytes', request_id)
    create_params = _strict_json(text, request_id)
    if not isinstance(create_params, dict):
        raise ProtocolError('create_params_json must be a JSON object', request_id)
    _check_json_domain(create_params, request_id)
    missing = [name for name in CREATE_PARAMS_FIELDS if name not in create_params]
    if missing:
        raise ProtocolError('create_params_json lacks {}'.format(', '.join(missing)), request_id)
    baseline_sha256 = _hash_text(
        create_params['baseline_sha256'], 'baseline_sha256', request_id)
    run_configuration = create_params['run_configuration']
    if not isinstance(run_configuration, dict):
        raise ProtocolError('run_configuration must be an object', request_id)
    if run_configuration.get('model_id') != model_id:
        raise ProtocolError(
            'run_configuration.model_id does not match data.model_id', request_id)
    source_inputs = create_params['source_inputs']
    if not isinstance(source_inputs, dict):
        raise ProtocolError('source_inputs must be an object', request_id)
    source_baseline = source_inputs.get('baseline_sha256')
    if isinstance(source_baseline, str) and source_baseline != baseline_sha256:
        raise ProtocolError(
            'source_inputs.baseline_sha256 differs from baseline_sha256', request_id)
    _resource_ref(create_params['package_ref'], 'package_ref',
                  'package_id', 'package_hash', request_id)
    _resource_ref(create_params['scenario_ref'], 'scenario_ref',
                  'scenario_id', 'scenario_hash', request_id)
    _bounded_text(create_params['mode'], 'mode', request_id)
    _bounded_text(create_params['source_binding_ref'], 'source_binding_ref', request_id)
    _link_ids(create_params['link_ids'], request_id)
    return InitializeRequest(
        request_id=request_id, model_id=model_id, config_id=config_id,
        config_sha256=config_sha256, raw=payload,
        create_params=create_params, run_configuration=run_configuration,
        baseline_sha256=baseline_sha256)


def initialize_result(request_id, ready, lifecycle=None, model_id=None, config_id=None,
                      config_sha256=None, reason=None):
    """Build one first-circle receipt; readiness is never inferred from transport."""
    data = {'ready': bool(ready)}
    if lifecycle is not None:
        data['lifecycle'] = str(lifecycle)
    if model_id is not None:
        data['model_id'] = str(model_id)
    if config_id is not None:
        data['config_id'] = str(config_id)
    if config_sha256 is not None:
        data['config_sha256'] = str(config_sha256)
    if reason is not None:
        data['reason'] = str(reason)
    return {'type': 'INITIALIZE_RESULT', 'request_id': request_id, 'data': data}


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def project_state(state, timestamp_ms=None):
    """Project one normalized C-core snapshot without inventing missing fields."""
    if not isinstance(state, dict):
        return None
    sequence = state.get('sequence')
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        return None
    lifecycle = LIFECYCLE_NAMES.get(state.get('lifecycle'))
    if lifecycle is None:
        return None
    data = {'sequence': str(sequence), 'lifecycle': lifecycle}
    # These are the V0.3 State/Telemetry fields.  V2 intentionally omits V3
    # additions instead of filling them with zeros.
    names = (
        'version', 'sim_time_s', 'north_m', 'east_m', 'down_m',
        'vn_mps', 've_mps', 'vd_mps',
        'q_w', 'q_x', 'q_y', 'q_z',
        'p_radps', 'q_radps', 'r_radps',
        'ax_mps2', 'ay_mps2', 'az_mps2',
        'p_dot_radps2', 'q_dot_radps2', 'r_dot_radps2',
        'wind_n_mps', 'wind_e_mps', 'wind_d_mps',
    )
    for name in names:
        value = state.get(name)
        if _finite(value):
            data[name] = value
    if state.get('airborne') in (0, 1, False, True):
        data['airborne'] = bool(state['airborne'])
    if isinstance(state.get('flight_phase'), int):
        data['flight_phase'] = state['flight_phase']
    message = {'type': 'STATE_TELEMETRY', 'data': data}
    if timestamp_ms is not None:
        message['timestamp_ms'] = int(timestamp_ms)
    return message


def current_timestamp_ms():
    return int(time.time() * 1000)
