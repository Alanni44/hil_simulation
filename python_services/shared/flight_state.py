#!/usr/bin/env python3
import struct

FLIGHT_STATE_FORMAT = (
    "=I" "Q" "ddd" "ddd" "fff" "fff" "fff" "fff" "f" "ffff" "I" "I" "I" "B" "B" "2x"
)

FLIGHT_STATE_SIZE = struct.calcsize(FLIGHT_STATE_FORMAT)

FLIGHT_STATE_FIELDS = [
    'version', 'timestamp_us',
    'pos_x', 'pos_y', 'pos_z',
    'lat', 'lon', 'alt',
    'roll', 'pitch', 'yaw',
    'vel_x', 'vel_y', 'vel_z',
    'acc_x', 'acc_y', 'acc_z',
    'ang_vel_p', 'ang_vel_q', 'ang_vel_r',
    'battery_voltage',
    'motor_speed_0', 'motor_speed_1', 'motor_speed_2', 'motor_speed_3',
    'status_word', 'mission_id', 'waypoint_index', 'flight_phase',
    'flight_state'
]

def parse_flight_state(data: bytes):
    if len(data) != FLIGHT_STATE_SIZE:
        raise ValueError(f"Bad size: {len(data)} != {FLIGHT_STATE_SIZE}")
    return dict(zip(FLIGHT_STATE_FIELDS, struct.unpack(FLIGHT_STATE_FORMAT, data)))