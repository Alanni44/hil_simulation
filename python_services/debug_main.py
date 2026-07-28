#!/usr/bin/env python3
"""Terminal-only real UE4 Z-mission debug entry point.

Runtime networking dependencies are imported only after ``run_debug`` is
called, so importing this module is safe for tests and operator tooling.
"""

from __future__ import print_function

import os
import time

from config_loader import CONFIG, load_config
from mission_file import load_mission, to_ue4_waypoints


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MISSION_PATH = os.path.join(ROOT, 'missions', 'z_mission.json')


class _Runtime(object):
    def __init__(self):
        import bridge_tcp_client as bridge
        import udp_forwarder
        from shared import state_cache

        self.start_udp_forwarder = udp_forwarder.start_udp_forwarder
        self.stop_udp_forwarder = udp_forwarder.stop_udp_forwarder
        self.send_mission_plan = bridge.send_mission_plan
        self.start_bridge = bridge.start_bridge
        self.stop_bridge = bridge.stop_bridge
        self.get_bridge_status = bridge.get_status
        self.get_flight_data = state_cache.get_flight_data


def get_debug_target(config):
    target = config.get('debug_ue4_tcp')
    if not isinstance(target, dict):
        raise ValueError('debug_ue4_tcp configuration is required')
    host = target.get('host')
    port = target.get('port')
    if not isinstance(host, str) or not host.strip():
        raise ValueError('debug UE4 host must be a non-empty string')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('debug UE4 port must be an integer from 1 to 65535')
    return host.strip(), port


def _bridge_waypoints(mission):
    converted = to_ue4_waypoints(mission)
    return [
        {
            'x': waypoint['x'],
            'y': waypoint['y'],
            'height': waypoint['height'],
            'speed': waypoint['target_speed'],
        }
        for waypoint in converted
    ]


def format_dashboard_snapshot(host, port, mission_id, bridge_status,
                              flight_data):
    connection = 'connected' if bridge_status.get('connected') else 'disconnected'
    phase = bridge_status.get('phase') or 'connecting'
    error = bridge_status.get('last_error') or 'none'
    lines = [
        'UE4 {}:{} | V2 {} | {}'.format(host, port, phase, connection),
        'Mission {}'.format(mission_id),
    ]
    if flight_data:
        position = flight_data['position']
        attitude = flight_data['attitude']
        lines.extend([
            'Position x={:.2f} y={:.2f} height={:.2f} m'.format(
                position['x'], position['y'], position['height']),
            'Attitude roll={:.3f} pitch={:.3f} yaw={:.3f} rad'.format(
                attitude['roll'], attitude['pitch'], attitude['yaw']),
        ])
    else:
        lines.extend(['Position unavailable', 'Attitude unavailable'])
    lines.append('Error {}'.format(error))
    return '\n'.join(lines)


def run_debug(config=None, mission_path=DEFAULT_MISSION_PATH, runtime=None,
              output_fn=print, sleep_fn=time.sleep, max_updates=None):
    config = CONFIG if config is None else config
    host, port = get_debug_target(config)
    mission = load_mission(mission_path)
    runtime = runtime or _Runtime()
    workers = []
    bridge_started = False
    udp_started = False

    runtime.send_mission_plan(
        mission['mission_id'], _bridge_waypoints(mission))
    try:
        workers.append(runtime.start_udp_forwarder())
        udp_started = True
        workers.append(runtime.start_bridge(host, port))
        bridge_started = True
        updates = 0
        while max_updates is None or updates < max_updates:
            output_fn(format_dashboard_snapshot(
                host, port, mission['mission_id'],
                runtime.get_bridge_status(), runtime.get_flight_data()))
            updates += 1
            if max_updates is None or updates < max_updates:
                sleep_fn(1.0)
    except KeyboardInterrupt:
        output_fn('Shutdown requested')
    finally:
        if bridge_started:
            runtime.stop_bridge()
        if udp_started:
            runtime.stop_udp_forwarder()
        for worker in workers:
            if worker is not None:
                worker.join(2.0)
    return 0


def main():
    return run_debug()


if __name__ == '__main__':
    raise SystemExit(main())
