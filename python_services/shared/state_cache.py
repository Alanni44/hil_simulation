#!/usr/bin/env python3
import threading
import time
from datetime import datetime
from .flight_state import parse_flight_state

_latest_raw = None
_frame = 0
_sim_time = 0.0
_lock = threading.Lock()

FLIGHT_STATE_NAMES = {
    0: 'ready', 1: 'taking_off', 2: 'flying',
    3: 'hovering', 4: 'landing', 5: 'landed', 6: 'fault'
}


def _utcnow_iso():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')


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
    return {
        'position': {'x': s['pos_x'], 'y': s['pos_y'], 'height': s['pos_z']},
        'attitude': {'yaw': s['yaw'], 'pitch': s['pitch'], 'roll': s['roll']},
        'velocity': {'vx': s['vel_x'], 'vy': s['vel_y'], 'vz': s['vel_z']},
        'timestamp': _utcnow_iso(),
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


def get_state_dict():
    with _lock:
        s = _latest_raw
    if not s:
        return None
    airborne = (s['status_word'] & 1) != 0
    return {
        'position': {'x': s['pos_x'], 'y': s['pos_y'], 'height': s['pos_z']},
        'velocity': {'vx': s['vel_x'], 'vy': s['vel_y'], 'vz': s['vel_z']},
        'landed_state': 'Flying' if airborne else 'Landed',
    }


def get_vehicle_state_v2():
    """V2.0 vehicle_state 消息完整体"""
    with _lock:
        s = _latest_raw
    if not s:
        return None
    fs_code = s.get('flight_state', 0)
    return {
        'protocol_version': '2.0',
        'type': 'vehicle_state',
        'vehicle_id': 'Drone1',
        'data': {
            'mission_id': 'mission_{:03d}'.format(s.get('mission_id', 1)),
            'sim_time': _sim_time,
            'position': {
                'x': s['pos_x'],
                'y': s['pos_y'],
                'height': s['pos_z'],
            },
            'attitude': {
                'roll': s['roll'],
                'pitch': s['pitch'],
                'yaw': s['yaw'],
            },
            'velocity': {
                'vx': s['vel_x'],
                'vy': s['vel_y'],
                'vz': s['vel_z'],
            },
            'angular_velocity': {
                'p': s.get('ang_vel_p', 0.0),
                'q': s.get('ang_vel_q', 0.0),
                'r': s.get('ang_vel_r', 0.0),
            },
            'flight_state': FLIGHT_STATE_NAMES.get(fs_code, 'ready'),
        },
    }


def get_mission_waypoints_from_cache():
    """返回最近一次 load_mission 的航点（供 bridge 发送 mission_plan）"""
    with _lock:
        s = _latest_raw
    return []  # 航点由 ws_server 直接从后端命令提取并转发
