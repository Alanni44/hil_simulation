"""Validated virtual-flight-controller profiles derived from HIL V3 contracts.

The C runtime intentionally needs only an ordered actuator vector.  A virtual
controller needs more semantics: rotor geometry or named fixed-wing axes.  We
therefore keep those semantics in the model contract's optional ``virtual_fc``
section and reject unsupported contracts instead of guessing an airframe.
"""
from __future__ import print_function

import json
import math


class VehicleProfileError(ValueError):
    pass


def _finite(value, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise VehicleProfileError('{} must be finite'.format(label))
    return float(value)


def _channels(contract):
    channels = contract.get('actuators', {}).get('channels')
    if not isinstance(channels, list) or not channels:
        raise VehicleProfileError('contract actuators.channels is required')
    result = []
    names = set()
    for index, channel in enumerate(channels):
        label = 'actuators.channels[{}]'.format(index)
        if not isinstance(channel, dict) or not isinstance(channel.get('name'), str):
            raise VehicleProfileError('{} requires name'.format(label))
        name = channel['name']
        if name in names: raise VehicleProfileError('duplicate actuator {}'.format(name))
        names.add(name)
        minimum = _finite(channel.get('min'), label + '.min')
        maximum = _finite(channel.get('max'), label + '.max')
        safe_value = _finite(channel.get('safe_value'), label + '.safe_value')
        if minimum > maximum or not minimum <= safe_value <= maximum:
            raise VehicleProfileError('{} has invalid range'.format(label))
        result.append({'name': name, 'min': minimum, 'max': maximum, 'safe_value': safe_value})
    return result


def _unwrap_contract(document):
    if not isinstance(document, dict):
        raise VehicleProfileError('contract document must be an object')
    # The deployment marker contains the immutable contract under this key.
    return document.get('contract', document)


def profile_from_contract(document):
    contract = _unwrap_contract(document)
    if contract.get('contract_version') != 3:
        raise VehicleProfileError('virtual FC requires a V3 vehicle contract')
    vehicle_kind = contract.get('vehicle_kind')
    if vehicle_kind not in ('multirotor', 'fixed_wing'):
        raise VehicleProfileError('vehicle_kind must be multirotor or fixed_wing')
    if 'physical_uut' not in contract.get('control_sources', []):
        raise VehicleProfileError('contract must permit physical_uut control')
    channels = _channels(contract)
    profile = contract.get('virtual_fc')
    if not isinstance(profile, dict):
        raise VehicleProfileError('contract.virtual_fc profile is required for virtual closed loop')
    if profile.get('kind') != vehicle_kind:
        raise VehicleProfileError('virtual_fc.kind must match vehicle_kind')
    result = {'model_name': contract.get('model_name', ''), 'vehicle_kind': vehicle_kind,
              'actuators': channels, 'sensors': dict(contract.get('sensors', {})),
              'parameters': list(contract.get('parameters', []))}
    if vehicle_kind == 'multirotor':
        rotors = profile.get('rotors')
        if not isinstance(rotors, list) or len(rotors) != len(channels) or len(rotors) < 4:
            raise VehicleProfileError('multirotor virtual_fc.rotors must describe every actuator (minimum four)')
        by_name = {channel['name']: channel for channel in channels}
        seen = set(); normalized = []
        for index, rotor in enumerate(rotors):
            label = 'virtual_fc.rotors[{}]'.format(index)
            if not isinstance(rotor, dict) or rotor.get('channel') not in by_name:
                raise VehicleProfileError('{} must reference an actuator channel'.format(label))
            channel = rotor['channel']
            if channel in seen: raise VehicleProfileError('duplicate rotor channel {}'.format(channel))
            seen.add(channel)
            position = rotor.get('position_m')
            if not isinstance(position, list) or len(position) != 2:
                raise VehicleProfileError('{}.position_m must be [x,y]'.format(label))
            x = _finite(position[0], label + '.position_m[0]')
            y = _finite(position[1], label + '.position_m[1]')
            if math.hypot(x, y) <= 1.0e-6:
                raise VehicleProfileError('{} position must not be the centre'.format(label))
            spin = rotor.get('spin')
            if spin not in ('cw', 'ccw'):
                raise VehicleProfileError('{}.spin must be cw or ccw'.format(label))
            normalized.append({'channel': channel, 'position_m': [x, y], 'spin': spin,
                               'thrust_scale': _finite(rotor.get('thrust_scale', 1.0), label + '.thrust_scale')})
        if seen != set(by_name): raise VehicleProfileError('rotor channels must match actuator channels')
        result['rotors'] = normalized
        return result
    axis_map = profile.get('axis_map')
    required = ('throttle', 'roll', 'pitch', 'yaw')
    if not isinstance(axis_map, dict) or set(axis_map) != set(required):
        raise VehicleProfileError('fixed_wing virtual_fc.axis_map must map throttle/roll/pitch/yaw')
    names = set(channel['name'] for channel in channels)
    if any(axis_map[axis] not in names for axis in required):
        raise VehicleProfileError('fixed-wing axis_map must reference actuator channels')
    if len(set(axis_map.values())) != len(required):
        raise VehicleProfileError('fixed-wing axis_map channels must be distinct')
    result['axis_map'] = dict(axis_map)
    result['cruise_speed_mps'] = _finite(profile.get('cruise_speed_mps', 15.0), 'virtual_fc.cruise_speed_mps')
    if result['cruise_speed_mps'] <= 0.0:
        raise VehicleProfileError('virtual_fc.cruise_speed_mps must be positive')
    return result


def load_profile(path):
    if not isinstance(path, str) or not path:
        raise VehicleProfileError('contract path is required')
    try:
        with open(path, 'r') as source:
            document = json.load(source)
    except (OSError, ValueError) as exc:
        raise VehicleProfileError('cannot load vehicle contract: {}'.format(exc))
    return profile_from_contract(document)
