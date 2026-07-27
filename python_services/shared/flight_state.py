#!/usr/bin/env python3
"""The fixed, normalized C-core → Python NED state wire contract.

No model-specific schema is permitted here.  Model names occur only in the
build-time ``hil_contract.json``; by this boundary every model emits this
single layout.
"""
from __future__ import print_function

import math
import struct


# uint32 version, uint64 sequence, double sim time and NED position,
# float NED velocity, quaternion, body rates, airborne, lifecycle, padding.
FLIGHT_STATE_FORMAT = '=IQddddffffffffffBBH'
FLIGHT_STATE_SIZE = struct.calcsize(FLIGHT_STATE_FORMAT)
FLIGHT_STATE_FIELDS = (
    'version', 'sequence', 'sim_time_s',
    'north_m', 'east_m', 'down_m',
    'vn_mps', 've_mps', 'vd_mps',
    'q_w', 'q_x', 'q_y', 'q_z',
    'p_radps', 'q_radps', 'r_radps',
    'airborne', 'lifecycle', 'reserved',
)

LIFECYCLE_NAMES = {0: 'RUNNING', 1: 'PAUSED', 2: 'RESETTING', 3: 'ENDED'}


def parse_flight_state(data):
    if len(data) != FLIGHT_STATE_SIZE:
        raise ValueError('Bad state size: {} != {}'.format(len(data), FLIGHT_STATE_SIZE))
    state = dict(zip(FLIGHT_STATE_FIELDS, struct.unpack(FLIGHT_STATE_FORMAT, data)))
    validate_flight_state(state)
    return state


def validate_flight_state(state):
    if state['version'] != 1:
        raise ValueError('unsupported state version {}'.format(state['version']))
    for field in ('sim_time_s', 'north_m', 'east_m', 'down_m', 'vn_mps', 've_mps',
                  'vd_mps', 'q_w', 'q_x', 'q_y', 'q_z', 'p_radps', 'q_radps', 'r_radps'):
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
    return state
