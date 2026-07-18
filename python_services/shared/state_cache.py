#!/usr/bin/env python3
import threading
import time
from datetime import datetime, timezone
from .flight_state import parse_flight_state

_latest_raw = None
_frame = 0
_sim_time = 0.0
_lock = threading.Lock()


def update(data: bytes):
    global _latest_raw, _frame, _sim_time
    try:
        s = parse_flight_state(data)
    except Exception:
        return
    _sim_time = s['timestamp_us'] / 1_000_000.0
    _frame = s.get('mission_id', 0)
    with _lock:
        _latest_raw = s


def get_flight_data():
    with _lock:
        s = _latest_raw
    if not s:
        return None
    airborne = (s['status_word'] & 1) != 0
    return {
        'position': {'x': s['pos_x'], 'y': s['pos_y'], 'height': s['pos_z']},
        'attitude': {'yaw': s['yaw'], 'pitch': s['pitch'], 'roll': s['roll']},
        'velocity': {'vx': s['vel_x'], 'vy': s['vel_y'], 'vz': s['vel_z']},
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        'frame': _frame,
    }


def get_heartbeat():
    with _lock:
        s = _latest_raw
    return {
        'sim_time': _sim_time,
        'rt_factor': 0.98,
        'task_cpu': 5,
        'status': 'running' if (s and (s['status_word'] & 1)) else 'idle',
    }


def get_ue4_state():
    with _lock:
        s = _latest_raw
    if not s:
        return None
    airborne = (s['status_word'] & 1) != 0
    return {
        'position': {'x': s['pos_x'], 'y': s['pos_y'], 'height': s['pos_z']},
        'velocity': {'vx': s['vel_x'], 'vy': s['vel_y'], 'vz': s['vel_z']},
        'attitude': {'roll': s['roll'], 'pitch': s['pitch'], 'yaw': s['yaw']},
        'status': 'Flying' if airborne else 'Landed',
    }


def get_state_dict():
    with _lock:
        s = _latest_raw
    if not s:
        return None
    airborne = (s['status_word'] & 1) != 0
    return {
        'position': {'x': s['pos_x'], 'y': s['pos_y'], 'height': s['pos_z']},
        'velocity': {'vx': s['vel_x'], 'vy': s['vel_y'], 'vz': s['vel_z']},
        'status': 'flying' if airborne else 'landed',
    }
