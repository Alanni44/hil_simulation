#!/usr/bin/env python3
"""Validated NED state cache and the sole NED → UE4 adapter."""
from __future__ import print_function

import math
import threading
import time
from datetime import datetime

from .flight_state import LIFECYCLE_NAMES, parse_flight_state

_latest_raw = None
_latest_received_monotonic = None
_lock = threading.Lock()


def _utcnow_iso():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')


def ned_quaternion_to_ue4_rpy(q_w, q_x, q_y, q_z):
    """FRD→NED quaternion to UE4 X-forward/Y-right/Z-up Euler radians.

    UE4 exposes a left-handed visual frame.  With North=+X, East=+Y and
    Down=-Z, a positive NED yaw (North toward East) is a positive UE4 yaw.
    The FRD down axis is reflected for the visual body convention, yielding
    pitch and roll sign inversion.  This formula is exercised by acceptance
    tests using identity and +90 degree yaw vectors.
    """
    sinr_cosp = 2.0 * (q_w * q_x + q_y * q_z)
    cosr_cosp = 1.0 - 2.0 * (q_x * q_x + q_y * q_y)
    roll_ned = math.atan2(sinr_cosp, cosr_cosp)
    sinp = 2.0 * (q_w * q_y - q_z * q_x)
    pitch_ned = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    siny_cosp = 2.0 * (q_w * q_z + q_x * q_y)
    cosy_cosp = 1.0 - 2.0 * (q_y * q_y + q_z * q_z)
    yaw_ned = math.atan2(siny_cosp, cosy_cosp)
    return -roll_ned, -pitch_ned, yaw_ned


def ned_to_ue4(state):
    roll, pitch, yaw = ned_quaternion_to_ue4_rpy(
        state['q_w'], state['q_x'], state['q_y'], state['q_z'])
    return {
        'position': {'x': state['north_m'], 'y': state['east_m'],
                     'height': -state['down_m']},
        'attitude': {'roll': roll, 'pitch': pitch, 'yaw': yaw},
        'velocity': {'vx': state['vn_mps'], 'vy': state['ve_mps'],
                     'vz': -state['vd_mps']},
    }


def update(data):
    global _latest_raw, _latest_received_monotonic
    state = parse_flight_state(data)
    with _lock:
        previous = _latest_raw
        if previous and state['sequence'] < previous['sequence']:
            raise ValueError('state sequence regressed')
        if previous and state['sim_time_s'] < previous['sim_time_s']:
            raise ValueError('state simulation time regressed')
        _latest_raw = state
        _latest_received_monotonic = time.monotonic()


def state_age_s():
    with _lock:
        received = _latest_received_monotonic
    return None if received is None else time.monotonic() - received


def is_stale(max_age_s=0.5):
    age = state_age_s()
    return age is None or age > max_age_s


def get_flight_data():
    with _lock:
        state = _latest_raw
    if not state:
        return None
    converted = ned_to_ue4(state)
    converted.update({'timestamp': _utcnow_iso(), 'frame': state['sequence']})
    return converted


def get_heartbeat():
    with _lock:
        state = _latest_raw
    return {'sim_time': state['sim_time_s'] if state else 0.0,
            'rt_factor': 0.98, 'task_cpu': 5,
            'status': LIFECYCLE_NAMES.get(state['lifecycle'], 'IDLE') if state else 'IDLE'}


def get_state_dict():
    with _lock:
        state = _latest_raw
    if not state:
        return None
    converted = ned_to_ue4(state)
    return {'position': converted['position'], 'velocity': converted['velocity'],
            'landed_state': 'Flying' if state['airborne'] else 'Landed',
            'sequence': state['sequence'], 'sim_time_s': state['sim_time_s'],
            'lifecycle': LIFECYCLE_NAMES[state['lifecycle']]}


def vehicle_state_v2_from_state(state, mission_id):
    if not isinstance(mission_id, str) or not mission_id:
        raise ValueError('mission_id is required for V2 vehicle_state')
    converted = ned_to_ue4(state)
    return {'protocol_version': '2.0', 'type': 'vehicle_state', 'vehicle_id': 'Drone1',
            'data': {'mission_id': mission_id, 'sim_time': state['sim_time_s'],
                     'position': converted['position'], 'attitude': converted['attitude'],
                     'velocity': converted['velocity'],
                     'angular_velocity': {'p': state['p_radps'], 'q': state['q_radps'],
                                          'r': state['r_radps']}}}


def v2_event_name(event_name):
    mapping = {'pause': 'pause', 'resume': 'resume', 'reset': 'reset_scene',
               'mission_end': 'mission_end'}
    if event_name not in mapping:
        raise ValueError('unsupported V2 simulation event {}'.format(event_name))
    return mapping[event_name]


def get_vehicle_state_v2(mission_id, rate_hz=50):
    if rate_hz != 50:
        raise ValueError('V2 vehicle_state rate is fixed at 50 Hz')
    with _lock:
        state = _latest_raw
    if not state or is_stale():
        return None
    return vehicle_state_v2_from_state(state, mission_id)


def get_mission_waypoints_from_cache():
    return []
