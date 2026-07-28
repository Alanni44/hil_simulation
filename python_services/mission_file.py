"""Load validated NED mission files and convert their waypoints for UE4."""

from __future__ import absolute_import

import json
import math


_WAYPOINT_FIELDS = ('id', 'north_m', 'east_m', 'down_m', 'speed_mps')


def load_mission(path):
    """Load a mission JSON file, validating all fields used by the controller."""
    with open(path, 'r') as mission_file:
        mission = json.load(mission_file)
    _validate_mission(mission)
    return mission


def to_ue4_waypoints(mission):
    """Convert NED mission waypoints to UE4's x/y/height coordinate convention."""
    return [_to_ue4_waypoint(waypoint) for waypoint in mission['waypoints']]


def _validate_mission(mission):
    if not isinstance(mission, dict):
        raise ValueError('mission must be an object')
    _require_nonempty_string(mission, 'mission_id')
    _require_positive_number(mission, 'completion_radius_m')

    waypoints = mission.get('waypoints')
    if not isinstance(waypoints, list) or len(waypoints) < 3:
        raise ValueError('mission must contain takeoff and at least two cruise waypoints')
    for waypoint in waypoints:
        _validate_waypoint(waypoint)
    _validate_waypoint(mission.get('landing'))


def _validate_waypoint(waypoint):
    if not isinstance(waypoint, dict):
        raise ValueError('waypoint must be an object')
    _require_nonempty_string(waypoint, 'id')
    for field in _WAYPOINT_FIELDS[1:]:
        _require_finite_number(waypoint, field)
    if waypoint['speed_mps'] <= 0:
        raise ValueError('speed_mps must be positive')


def _require_nonempty_string(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError('%s must be a non-empty string' % field)


def _require_positive_number(data, field):
    _require_finite_number(data, field)
    if data[field] <= 0:
        raise ValueError('%s must be positive' % field)


def _require_finite_number(data, field):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s must be a finite number' % field)
    if not math.isfinite(value):
        raise ValueError('%s must be a finite number' % field)


def _to_ue4_waypoint(waypoint):
    return {
        'id': waypoint['id'],
        'x': waypoint['north_m'],
        'y': waypoint['east_m'],
        'height': -waypoint['down_m'],
        'target_speed': waypoint['speed_mps'],
    }
