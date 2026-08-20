#!/usr/bin/env python3
"""The fixed, normalized C-core → Python NED state wire contract.

No model-specific schema is permitted here.  Model names occur only in the
build-time ``hil_contract.json``; by this boundary every model emits this
single layout.
"""
from __future__ import print_function

import math
import struct


# V2 is retained for already deployed models.  V3 appends fixed-wing fields
# after this immutable prefix: FRD angular acceleration, NED wind, throttle,
# optional true surface deflections and a C-core flight phase.
FLIGHT_STATE_V2_FORMAT = '=IQddddfffffffffffffBBH'
FLIGHT_STATE_V3_LEGACY_FORMAT = '=IQddddfffffffffffffBBHffffffffffBBH'
FLIGHT_STATE_V3_FORMAT = '=IQddddfffffffffffffBBHfffffffffffBBH'
FLIGHT_STATE_FORMAT = FLIGHT_STATE_V2_FORMAT
FLIGHT_STATE_SIZE = struct.calcsize(FLIGHT_STATE_V2_FORMAT)
FLIGHT_STATE_V3_LEGACY_SIZE = struct.calcsize(FLIGHT_STATE_V3_LEGACY_FORMAT)
FLIGHT_STATE_V3_SIZE = struct.calcsize(FLIGHT_STATE_V3_FORMAT)
FLIGHT_STATE_FIELDS = (
    'version', 'sequence', 'sim_time_s',
    'north_m', 'east_m', 'down_m',
    'vn_mps', 've_mps', 'vd_mps',
    'q_w', 'q_x', 'q_y', 'q_z',
    'p_radps', 'q_radps', 'r_radps',
    'ax_mps2', 'ay_mps2', 'az_mps2',
    'airborne', 'lifecycle', 'reserved',
)
FLIGHT_STATE_V3_FIELDS = FLIGHT_STATE_FIELDS + (
    'p_dot_radps2', 'q_dot_radps2', 'r_dot_radps2',
    'wind_n_mps', 'wind_e_mps', 'wind_d_mps',
    'throttle', 'aileron_rad', 'elevator_rad', 'rudder_rad', 'tas_min_mps',
    'flight_phase', 'control_surface_valid', 'reserved_v3',
)

LIFECYCLE_NAMES = {0: 'RUNNING', 1: 'PAUSED', 2: 'RESETTING', 3: 'ENDED'}
FLIGHT_PHASE_NAMES = {
    0: 'ready', 1: 'taking_off', 2: 'flying', 3: 'landing',
    4: 'landed', 5: 'fault',
}


def parse_flight_state(data):
    if len(data) == FLIGHT_STATE_SIZE:
        fields, layout = FLIGHT_STATE_FIELDS, FLIGHT_STATE_V2_FORMAT
    elif len(data) == FLIGHT_STATE_V3_SIZE:
        fields, layout = FLIGHT_STATE_V3_FIELDS, FLIGHT_STATE_V3_FORMAT
    elif len(data) == FLIGHT_STATE_V3_LEGACY_SIZE:
        fields, layout = FLIGHT_STATE_V3_FIELDS[:-4] + ('flight_phase', 'control_surface_valid', 'reserved_v3'), FLIGHT_STATE_V3_LEGACY_FORMAT
    else:
        raise ValueError('Bad state size: {} (expected V2 {} or V3 {})'.format(
            len(data), FLIGHT_STATE_SIZE, FLIGHT_STATE_V3_SIZE))
    state = dict(zip(fields, struct.unpack(layout, data)))
    if len(data) == FLIGHT_STATE_V3_LEGACY_SIZE:
        state['tas_min_mps'] = 0.1
    validate_flight_state(state)
    return state


def validate_flight_state(state):
    if state['version'] not in (2, 3):
        raise ValueError('unsupported state version {}'.format(state['version']))
    for field in ('sim_time_s', 'north_m', 'east_m', 'down_m', 'vn_mps', 've_mps',
                  'vd_mps', 'q_w', 'q_x', 'q_y', 'q_z', 'p_radps', 'q_radps', 'r_radps',
                  'ax_mps2', 'ay_mps2', 'az_mps2'):
        if not math.isfinite(state[field]):
            raise ValueError('non-finite {}'.format(field))
    norm = math.sqrt(sum(state[field] * state[field]
                         for field in ('q_w', 'q_x', 'q_y', 'q_z')))
    if norm == 0.0 or abs(norm - 1.0) > 0.02:
        raise ValueError('invalid quaternion norm {}'.format(norm))
    if state['airborne'] not in (0, 1):
        raise ValueError('invalid airborne flag')
    if state['lifecycle'] not in LIFECYCLE_NAMES:
        raise ValueError('invalid lifecycle')
    if state['version'] == 3:
        for field in ('p_dot_radps2', 'q_dot_radps2', 'r_dot_radps2',
                      'wind_n_mps', 'wind_e_mps', 'wind_d_mps', 'throttle', 'tas_min_mps',
                      'aileron_rad', 'elevator_rad', 'rudder_rad'):
            if not math.isfinite(state[field]):
                raise ValueError('non-finite {}'.format(field))
        if not 0.0 <= state['throttle'] <= 1.0:
            raise ValueError('invalid throttle')
        if state['tas_min_mps'] <= 0.0:
            raise ValueError('invalid tas_min_mps')
        if state['flight_phase'] not in FLIGHT_PHASE_NAMES:
            raise ValueError('invalid flight_phase')
        if state['control_surface_valid'] not in (0, 1):
            raise ValueError('invalid control_surface_valid')
    return state
