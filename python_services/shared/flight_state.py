#!/usr/bin/env python3
"""Binary flight state protocol definition and parser.
Packed little-endian struct shared with the C core (flight_state.h).

Layout — core fields always present:
    =I Q ddd ddd fff fff fff fff f ffff I I I B B 2x

Field names are read from flight_state_schema.json if present (allows
per-model field remapping). Falls back to the default list below.
"""
import struct
import os

FLIGHT_STATE_FORMAT = (
    "=I" "Q" "ddd" "ddd" "fff" "fff" "fff" "fff" "f" "ffff" "I" "I" "I" "B" "B" "2x"
)

FLIGHT_STATE_SIZE = struct.calcsize(FLIGHT_STATE_FORMAT)

_DEFAULT_FIELDS = [
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

FLIGHT_STATE_FIELDS = list(_DEFAULT_FIELDS)  # may be replaced by load_schema()

# Schema file path — set by ws_server.py after build completes
_SCHEMA_PATH = '/tmp/flight_state_schema.json'


def load_schema(schema_path=None):
    """Load a per-model flight state schema.

    The schema is a JSON array of field names matching the binary layout.
    Size must match FLIGHT_STATE_SIZE.  Call this after a model hot-reload.

    Returns True if loaded successfully; False otherwise (defaults stay).
    """
    global FLIGHT_STATE_FIELDS
    path = schema_path or _SCHEMA_PATH
    try:
        import json
        with open(path, 'r') as f:
            fields = json.load(f)
        # Verify the schema size matches the C struct
        fmt = ''.join(
            'd' if n.startswith(('pos_', 'lat', 'lon', 'alt', 'acc_')) else
            'f' if n.startswith(('roll', 'pitch', 'yaw', 'vel_', 'ang_', 'battery', 'motor')) else
            'I' if n in ('version', 'status_word', 'mission_id', 'waypoint_index') else
            'Q' if n == 'timestamp_us' else
            'B' if n in ('flight_phase', 'flight_state') else
            'x' if n == 'reserved' else
            None
            for n in fields
        )
        if None not in fmt and struct.calcsize('=' + ''.join(fmt)) == FLIGHT_STATE_SIZE:
            FLIGHT_STATE_FIELDS = list(fields)
            return True
    except Exception:
        pass
    FLIGHT_STATE_FIELDS = list(_DEFAULT_FIELDS)
    return False


def parse_flight_state(data: bytes):
    """Parse a raw binary FlightState_t into a dict.

    Uses the current FLIGHT_STATE_FIELDS list (default or schema-loaded).
    """
    if len(data) != FLIGHT_STATE_SIZE:
        raise ValueError("Bad size: {} != {}".format(len(data), FLIGHT_STATE_SIZE))
    return dict(zip(FLIGHT_STATE_FIELDS, struct.unpack(FLIGHT_STATE_FORMAT, data)))