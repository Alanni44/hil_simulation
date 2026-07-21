#!/usr/bin/env python3
"""
Mock C-core: builds a fake FlightState and sends it to UDP 9998 at 1 kHz.
Also listens for JSON commands on UDP 9997 and simulates takeoff/land/hover.
Run this first, before starting python_services/main.py.

Usage:
    python3 tests/mock_core.py
"""
import struct
import socket
import math
import json
import time

FMT = "=I" "Q" "ddd" "ddd" "fff" "fff" "fff" "fff" "f" "ffff" "I" "I" "I" "B" "B" "2x"
SIZE = struct.calcsize(FMT)

status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cmd_sock.bind(('127.0.0.1', 9997))
cmd_sock.settimeout(0.001)

t = 0.0
airborne = False
alt_target = 0.0
alt_current = 0.0
target_x = 0.0
target_y = 0.0

print("Mock C-core running...")
print("  FlightState -> UDP 127.0.0.1:9998 (1 kHz)")
print("  Commands    <- UDP 127.0.0.1:9997")
print()

while True:
    # -------- check for commands --------
    try:
        raw, addr = cmd_sock.recvfrom(4096)
        req = json.loads(raw.decode('utf-8'))
        cmd = req.get('cmd', '')
        params = req.get('params', {})
        if cmd == 'takeoff':
            airborne = True
            alt_target = params.get('height', 50.0)
            print('[mock_core] TAKEOFF  height={}'.format(alt_target))
        elif cmd == 'land':
            airborne = False
            alt_target = 0.0
            print('[mock_core] LAND')
        elif cmd == 'hover':
            alt_target = alt_current
            print('[mock_core] HOVER at {:.1f}m'.format(alt_target))
        elif cmd == 'move_position':
            target_x = params.get('x', target_x)
            target_y = params.get('y', target_y)
            alt_target = params.get('height', alt_current)
            print('[mock_core] MOVE_POS x={} y={} h={}'.format(target_x, target_y, alt_target))
        elif cmd == 'move_velocity':
            print('[mock_core] MOVE_VEL vx={} vy={} vz={} dur={}'.format(
                params.get('vx', 0), params.get('vy', 0),
                params.get('vz', 0), params.get('duration', 0)))
        elif cmd == 'tune':
            print('[mock_core] TUNE  {}={}'.format(
                list(params.keys())[0] if params else '?',
                list(params.values())[0] if params else '?'))
        elif cmd == 'init_sim':
            print('[mock_core] INIT_SIM  params={}'.format(params))
        else:
            print('[mock_core] CMD "{}"  params={}'.format(cmd, params))
    except BlockingIOError:
        pass
    except socket.timeout:
        pass
    except Exception:
        pass

    # -------- simulate physics --------
    if airborne:
        if alt_target < 1.0:
            alt_target = 1.0
    else:
        alt_target = 0.0

    # altitude control
    if abs(alt_current - alt_target) > 0.05:
        alt_current += (alt_target - alt_current) * 3.0 * 0.001

    # simple XY move toward target
    dx = target_x - (t * 5.0)
    dy = target_y - (t * 2.0)
    px = t * 5.0 + dx * (1 - math.exp(-t * 0.5)) if t > 0 else 0.0
    py = t * 2.0 + dy * (1 - math.exp(-t * 0.5)) if t > 0 else 0.0

    t += 0.001
    status_word = 1 if (airborne or alt_current > 0.5) else 0

    data = struct.pack(FMT,
        1,                                    # version
        int(t * 1000000),                     # timestamp_us
        px, py, alt_current,                  # pos_x, pos_y, pos_z
        39.9 + px * 0.00001,                  # lat
        116.4 + py * 0.00001,                 # lon
        alt_current,                           # alt
        math.sin(t) * 0.1,                    # roll
        math.cos(t) * 0.1,                    # pitch
        0.0,                                  # yaw
        5.0, 2.0,                             # vel_x, vel_y
        (alt_target - alt_current) * 3.0 if alt_current < alt_target else 0.0,  # vel_z
        0.0, 0.0, 0.0,                        # acc_x, acc_y, acc_z
        0.0, 0.0, 0.0,                         # ang_vel_p, ang_vel_q, ang_vel_r
        24.5,                                   # battery
        5000.0, 4800.0, 5200.0, 4900.0,       # motors
        status_word,                            # status_word
        1, 0,                                   # mission_id, waypoint_index
        2, 2                                    # flight_phase, flight_state
    )
    status_sock.sendto(data, ('127.0.0.1', 9998))
    time.sleep(0.001)
