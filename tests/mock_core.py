#!/usr/bin/env python3
"""
Mock C-core: reads a CSV file and replays FlightState packets to UDP 9998.
Supports `--csv` for offline replay with pre-recorded trajectories.

Usage:
    python3 tests/mock_core.py --csv uav_circle_test_50hz_60s.csv

Without --csv, falls back to the original kinematic mock.
"""
import argparse
import csv
import struct
import socket
import math
import json
import time
import sys

FMT = "=I" "Q" "ddd" "ddd" "fff" "fff" "fff" "fff" "f" "ffff" "I" "I" "I" "B" "B" "2x"
SIZE = struct.calcsize(FMT)

status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cmd_sock.bind(('127.0.0.1', 9997))
cmd_sock.settimeout(0.001)


def replay_csv(path, rate_hz=20):
    """读取 CSV 并以指定频率发送 FlightState"""
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print("[mock_core] CSV replay: {} rows @ {} Hz".format(len(rows), rate_hz))
    interval = 1.0 / rate_hz
    index = 0
    start_time = time.time()
    row_duration = 1.0 / 50.0 if len(rows) > 1 else interval  # CSV is 50Hz

    while True:
        # ---- check for commands on 9997 ----
        try:
            raw, addr = cmd_sock.recvfrom(4096)
            req = json.loads(raw.decode('utf-8'))
            cmd = req.get('cmd', '')
            print('[mock_core] CMD "{}"  (ignored in CSV replay)'.format(cmd))
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
            pass

        row = rows[index]

        # 直接使用 CSV 中的经纬度（对方提供的 CSV 有 lat/lon）
        pos_x = float(row['x'])
        pos_y = float(row['y'])
        pos_z = float(row['height'])
        roll = float(row['roll'])
        pitch = float(row['pitch'])
        yaw = float(row['yaw'])
        vel_x = float(row['vx'])
        vel_y = float(row['vy'])
        vel_z = float(row['vz'])
        ang_vel_p = float(row['wx'])
        ang_vel_q = float(row['wy'])
        ang_vel_r = float(row['wz'])
        sim_time = float(row['sim_time'])

        # lat/lon 从 CSV 的行坐标中获取，使用比例系数来模拟经纬度
        lat = 39.9 + pos_y * 0.00001
        lon = 116.4 + pos_x * 0.00001
        alt = pos_z
        status_word = 1
        flight_state = 2  # flying

        data = struct.pack(FMT,
            1,                                # version
            int(sim_time * 1000000),          # timestamp_us
            pos_x, pos_y, pos_z,              # position
            lat, lon, alt,                     # lat/lon/alt
            roll, pitch, yaw,                  # attitude (rad)
            vel_x, vel_y, vel_z,               # velocity
            0.0, 0.0, 0.0,                     # acc_x/y/z
            ang_vel_p, ang_vel_q, ang_vel_r,  # angular velocity
            24.5,                              # battery
            5000.0, 4800.0, 5200.0, 4900.0,   # motors
            status_word,                       # status_word
            1, 0,                              # mission_id, waypoint_index
            2, flight_state                    # flight_phase, flight_state
        )
        status_sock.sendto(data, ('127.0.0.1', 9998))

        # 精确时间控制
        elapsed = time.time() - start_time
        expected_time = index * row_duration
        if elapsed < expected_time:
            time.sleep(expected_time - elapsed)

        index += 1
        if index >= len(rows):
            print("[mock_core] CSV replay finished, looping...")
            index = 0
            start_time = time.time()


def kinematic_mock():
    """原始的运动学模拟模式，与之前一样"""
    t = 0.0
    airborne = False
    alt_target = 0.0
    alt_current = 0.0
    target_x = 0.0
    target_y = 0.0

    while True:
        # ---- check for commands ----
        try:
            raw, addr = cmd_sock.recvfrom(4096)
            req = json.loads(raw.decode('utf-8'))
            cmd = req.get('cmd', '')
            params = req.get('params', {})
            if cmd == 'takeoff':
                airborne = True
                alt_target = params.get('height', 50.0)
                print('[mock_core] TAKEOFF height={}'.format(alt_target))
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
                print('[mock_core] TUNE {}'.format(params))
            elif cmd == 'init_sim':
                print('[mock_core] INIT_SIM params={}'.format(params))
            else:
                print('[mock_core] CMD "{}" params={}'.format(cmd, params))
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
            pass

        if t > 0.05:
            sat = 0.3
            yaw = math.atan2(
                max(-sat, min(sat, target_y - (t * 2.0))),
                max(-sat, min(sat, target_x - (t * 5.0)))
            )
        else:
            yaw = 0.0

        if airborne and alt_target < 1.0:
            alt_target = 1.0
        if not airborne:
            alt_target = 0.0
        if abs(alt_current - alt_target) > 0.05:
            alt_current += (alt_target - alt_current) * 3.0 * 0.001
        dx = target_x - (t * 5.0)
        dy = target_y - (t * 2.0)
        px = t * 5.0 + dx * (1 - math.exp(-t * 0.5)) if t > 0 else 0.0
        py = t * 2.0 + dy * (1 - math.exp(-t * 0.5)) if t > 0 else 0.0
        t += 0.001
        status_word = 1 if (airborne or alt_current > 0.5) else 0

        data = struct.pack(FMT,
            1, int(t * 1000000),
            px, py, alt_current,
            39.9 + px * 0.00001, 116.4 + py * 0.00001, alt_current,
            math.sin(t) * 0.1, math.cos(t) * 0.1, yaw,
            5.0, 2.0, (alt_target - alt_current) * 3.0 if alt_current < alt_target else 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            24.5, 5000.0, 4800.0, 5200.0, 4900.0,
            status_word, 1, 0, 2, 2
        )
        status_sock.sendto(data, ('127.0.0.1', 9998))
        time.sleep(0.001)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Mock C-core for HIL testing')
    parser.add_argument('--csv', help='CSV trajectory file for replay mode')
    args = parser.parse_args()

    if args.csv:
        print("[mock_core] CSV replay mode")
        print("  FlightState -> UDP 127.0.0.1:9998 (50Hz -> bridge 20Hz)")
        print("  CSV: {}".format(args.csv))
        print()
        replay_csv(args.csv)
    else:
        print("[mock_core] Kinematic mock mode")
        print("  FlightState -> UDP 127.0.0.1:9998 (1kHz)")
        print("  Commands    <- UDP 127.0.0.1:9997")
        print("  (use --csv for trajectory replay)")
        print()
        kinematic_mock()
