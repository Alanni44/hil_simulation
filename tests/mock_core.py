#!/usr/bin/env python3
"""
Mock C-core — drone dynamics with tunable PID and physical parameters.

Listens on UDP 9997 for JSON commands:
  init_sim        → set initial position
  takeoff         → ascend to target altitude
  land            → descend to ground
  hover           → hold position
  move_position   → fly to (x, y, height)
  tune            → modify any model parameter at runtime
  load_mission    → set waypoint queue
  get_state       → print current state

Sends binary FlightState_t packets to UDP 9998 at 50Hz.

Physical model: simplified point-mass drone with PID attitude control.
All coefficients are tunable via UDP JSON in real time.
"""
import argparse
import struct
import socket
import math
import json
import time

# ---- binary FlightState_t layout (matches c_core/src/flight_state.h) ----
FMT = "=I" "Q" "ddd" "ddd" "fff" "fff" "fff" "fff" "f" "ffff" "I" "I" "I" "B" "B" "2x"
SIZE = struct.calcsize(FMT)

status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# 同时发送到 9998 (python_services/udp_forwarder.py) 和 9999 (测试脚本)
_monitor_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cmd_sock.bind(('127.0.0.1', 9997))
cmd_sock.settimeout(0.001)

# ---- drone state ----
state = {
    'px': 0.0, 'py': 0.0, 'pz': 0.0,     # position (m)
    'vx': 0.0, 'vy': 0.0, 'vz': 0.0,     # velocity (m/s)
    'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, # attitude (rad)
    'wx': 0.0, 'wy': 0.0, 'wz': 0.0,     # angular velocity (rad/s)
}

# ---- drone physical params (all tunable) ----
params = {
    'mass': 0.65,           # kg
    'gravity': 9.81,        # m/s^2
    'thrust_max': 30.0,     # N
    'thrust_min': 0.0,      # N
    'drag_coeff_x': 0.05,   # N/(m/s)^2
    'drag_coeff_y': 0.05,
    'drag_coeff_z': 0.10,
    'inertia_roll': 0.02,   # kg⋅m^2 (approximate)
    'inertia_pitch': 0.02,
    'inertia_yaw': 0.04,
    'motor_tau': 0.05,      # motor time constant (s)
    'arm_length': 0.225,    # m
    'kt': 1.0e-5,           # thrust coefficient
    'kd': 1.0e-7,           # drag torque coefficient
    'max_angle': 0.52,      # max tilt angle (30 deg)
}

# ---- PID params (all tunable) ----
pid = {
    'kp_roll': 0.8,  'ki_roll': 0.01,  'kd_roll': 0.15,
    'kp_pitch': 0.8, 'ki_pitch': 0.01, 'kd_pitch': 0.15,
    'kp_yaw': 1.2,   'ki_yaw': 0.02,   'kd_yaw': 0.30,
    'kp_z': 2.5,     'ki_z': 0.05,     'kd_z': 1.2,
    'kp_xy': 1.5,    'ki_xy': 0.02,    'kd_xy': 0.8,
}

# ---- control targets ----
target = {
    'x': 0.0, 'y': 0.0, 'z': 0.0, 'yaw': 0.0,
}

# ---- integrator accumulators ----
integral = {
    'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0,
    'z': 0.0, 'x': 0.0, 'y': 0.0,
}
_prev_err = {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, 'z': 0.0, 'x': 0.0, 'y': 0.0}

# ---- flight control ----
airborne = False
flight_phase = 5  # landed
sim_time = 0.0
step = 0
DT = 0.02  # 50Hz

# ---- waypoint queue ----
waypoints = []
wp_index = 0
wp_active = False
mission_id = ""

# ---- init params ----
init_lat = 39.9
init_lon = 116.4


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def parse_commands():
    """Non-blocking read of UDP 9997, return list of (cmd, params)."""
    cmds = []
    while True:
        try:
            raw, _addr = cmd_sock.recvfrom(4096)
            req = json.loads(raw.decode('utf-8'))
            cmds.append((req.get('cmd', ''), req.get('params', {})))
        except (BlockingIOError, socket.timeout):
            break
        except Exception:
            break
    return cmds


def handle_commands(cmds):
    global airborne, target, wp_active, wp_index, waypoints, mission_id
    global state, integral, _prev_err

    for cmd, p in cmds:
        if cmd == 'takeoff':
            airborne = True
            target['z'] = p.get('height', 10.0)
            target['x'] = state['px']
            target['y'] = state['py']
            target['yaw'] = state['yaw']
            wp_active = False
            print('[mock_core] TAKEOFF → target_z={:.1f}m'.format(target['z']))

        elif cmd == 'land':
            airborne = False

            target['z'] = 0.0
            target['x'] = state['px']
            target['y'] = state['py']

            wp_active = False

            # ---- 降落清理 PID ----
            integral['z'] = 0.0
            _prev_err['z'] = 0.0

            print('[mock_core] LAND')

        elif cmd == 'hover':
            target['x'] = state['px']
            target['y'] = state['py']
            target['z'] = state['pz']
            target['yaw'] = state['yaw']
            # 刹车：清零速度、姿态、积分，避免残余推力分量导致漂移
            state['vx'] = state['vy'] = state['vz'] = 0.0
            state['roll'] = 0.0
            state['pitch'] = 0.0
            state['wx'] = state['wy'] = state['wz'] = 0.0
            for k in integral:
                integral[k] = 0.0
            for k in _prev_err:
                _prev_err[k] = 0.0
            wp_active = False
            print('[mock_core] HOVER at ({:.1f},{:.1f},{:.1f})'.format(
                state['px'], state['py'], state['pz']))

        elif cmd == 'move_position':
            target['x'] = p.get('x', target['x'])
            target['y'] = p.get('y', target['y'])
            target['z'] = p.get('height', target['z'])
            target['yaw'] = p.get('yaw', target['yaw'])
            wp_active = False
            print('[mock_core] MOVE → ({:.1f},{:.1f},{:.1f}) yaw={:.2f}'.format(
                target['x'], target['y'], target['z'], target['yaw']))

        elif cmd == 'move_velocity':
            vx = p.get('vx', 0.0)
            vy = p.get('vy', 0.0)
            vz = p.get('vz', 0.0)
            dur = p.get('duration', 1.0)
            target['x'] = state['px'] + vx * dur
            target['y'] = state['py'] + vy * dur
            target['z'] = state['pz'] + vz * dur
            wp_active = False
            print('[mock_core] MOVE_VEL → target after {:.1f}s: ({:.1f},{:.1f},{:.1f})'.format(
                dur, target['x'], target['y'], target['z']))

        elif cmd == 'tune':
            changed = []

            for key, val in p.items():

                # ---- 参数安全保护 ----
                if key == 'mass':
                    # 防止负质量导致动力学爆炸
                    val = max(float(val), 0.05)

                elif key == 'gravity':
                    # 防止负重力
                    val = max(float(val), 0.1)

                elif key == 'thrust_max':
                    val = max(float(val), 1.0)


                if key in params:
                    params[key] = float(val)
                    changed.append('{}={:.3f}'.format(key, val))

                if key in pid:
                    pid[key] = float(val)
                    changed.append('{}={:.3f}'.format(key, val))

            if changed:
                print('[mock_core] TUNE {}'.format(', '.join(changed)))

        elif cmd == 'init_sim':
            if 'initial_lat' in p:
                globals()['init_lat'] = p['initial_lat']
            if 'initial_lon' in p:
                globals()['init_lon'] = p['initial_lon']
            if 'init_x' in p:
                state['px'] = p['init_x']
            if 'init_y' in p:
                state['py'] = p['init_y']
            print('[mock_core] INIT_SIM lat={:.4f} lon={:.4f} x={:.1f} y={:.1f}'.format(
                init_lat, init_lon, state['px'], state['py']))

        elif cmd == 'load_mission':
            wps = p.get('waypoints', [])
            mission_id = p.get('mission_id', '')
            waypoints = []
            for wp in wps:
                lat = wp.get('lat', init_lat)
                lon = wp.get('lon', init_lon)
                h = wp.get('height', 50)
                spd = wp.get('speed', 5)
                x = (lon - init_lon) / 0.00001
                y = (lat - init_lat) / 0.00001
                waypoints.append({'x': x, 'y': y, 'height': h, 'speed': spd})
            wp_index = 0
            wp_active = len(waypoints) > 0
            if wp_active:
                target['x'] = waypoints[0]['x']
                target['y'] = waypoints[0]['y']
                target['z'] = waypoints[0]['height']
            print('[mock_core] LOAD_MISSION "{}" {} waypoints'.format(
                mission_id, len(waypoints)))

        elif cmd == 'get_state':
            print('[mock_core] STATE pos=({:.2f},{:.2f},{:.2f}) vel=({:.2f},{:.2f},{:.2f}) '
                  'att=({:.3f},{:.3f},{:.3f}) airborne={} wp={}/{}'.format(
                      state['px'], state['py'], state['pz'],
                      state['vx'], state['vy'], state['vz'],
                      state['roll'], state['pitch'], state['yaw'],
                      airborne, wp_index, len(waypoints)))

        elif cmd == 'simulation_event':
            ev = p.get('event', '')
            print('[mock_core] EVENT: {}'.format(ev))


def pid_control(err, dt, name, first_call=False):
    """Single-axis PID controller."""
    integral[name] += err * dt
    integral[name] = clamp(integral[name], -5.0, 5.0)
    if first_call:
        derivative = 0.0   # suppress D kick on first call
    else:
        derivative = (err - _prev_err[name]) / dt if dt > 0 else 0.0
    _prev_err[name] = err
    # 先按精确键名查，找不到 fallback 到通用键 (如 'x'/'y' 用 'xy')
    kp = pid.get('kp_' + name, pid.get('kp_xy', 0.0))
    ki = pid.get('ki_' + name, pid.get('ki_xy', 0.0))
    kd = pid.get('kd_' + name, pid.get('kd_xy', 0.0))
    return kp * err + ki * integral[name] + kd * derivative


def step_dynamics():
    """One 50Hz dynamics step."""
    global sim_time, step, wp_active, wp_index
    global _prev_target_z, _prev_target_x, _prev_target_y
    if '_prev_target_z' not in globals():
        _prev_target_z = target.get('z', 0)
        _prev_target_x = target.get('x', 0)
        _prev_target_y = target.get('y', 0)

    dt = DT
    m = params['mass']
    g = params['gravity']

    if step % 50 == 0:
        _prev_target_z = target.get('z', 0)
        _prev_target_x = target.get('x', 0)
        _prev_target_y = target.get('y', 0)
    if wp_active and waypoints and wp_index < len(waypoints):
        dx = state['px'] - waypoints[wp_index]['x']
        dy = state['py'] - waypoints[wp_index]['y']
        dz = state['pz'] - waypoints[wp_index]['height']
        if dx*dx + dy*dy + dz*dz < 1.0:
            wp_index += 1
            if wp_index < len(waypoints):
                target['x'] = waypoints[wp_index]['x']
                target['y'] = waypoints[wp_index]['y']
                target['z'] = waypoints[wp_index]['height']
                print('[mock_core] Waypoint {}/{} reached'.format(
                    wp_index, len(waypoints)))
            else:
                wp_active = False
                print('[mock_core] All waypoints complete')

    # ---- vertical PID (thrust) ----
    err_z = target['z'] - state['pz']
    first_z = (step == 0 or target['z'] != _prev_target_z)
    thrust_desired = clamp(m * g + pid_control(err_z, dt, 'z', first_z),
                           params['thrust_min'], params['thrust_max'])
    if not airborne and target['z'] < 0.5:
        thrust_desired = 0.0

    # ---- horizontal PID → desired tilt angles ----
    err_x = target['x'] - state['px']
    err_y = target['y'] - state['py']
    first_xy = (target['x'] != _prev_target_x or target['y'] != _prev_target_y)
    ax_desired = pid_control(err_x, dt, 'x', first_xy)
    ay_desired = pid_control(err_y, dt, 'y', first_xy)

    # Desired roll/pitch from horizontal acceleration
    pitch_desired = clamp(ax_desired / g, -params['max_angle'], params['max_angle'])
    roll_desired = clamp(-ay_desired / g, -params['max_angle'], params['max_angle'])
    yaw_desired = target['yaw']

    # ---- attitude PID → angular rates ----
    err_roll = roll_desired - state['roll']
    err_pitch = pitch_desired - state['pitch']
    err_yaw = yaw_desired - state['yaw']

    # Normalize yaw error to [-pi, pi]
    while err_yaw > math.pi:
        err_yaw -= 2 * math.pi
    while err_yaw < -math.pi:
        err_yaw += 2 * math.pi

    wx_cmd = pid_control(err_roll, dt, 'roll')
    wy_cmd = pid_control(err_pitch, dt, 'pitch')
    wz_cmd = pid_control(err_yaw, dt, 'yaw')

    # ---- attitude dynamics (first-order approximation) ----
    state['roll'] += wx_cmd * dt
    state['pitch'] += wy_cmd * dt
    state['yaw'] += wz_cmd * dt
    state['yaw'] = state['yaw'] % (2 * math.pi)
    if state['yaw'] > math.pi:
        state['yaw'] -= 2 * math.pi

    state['wx'] = wx_cmd
    state['wy'] = wy_cmd
    state['wz'] = wz_cmd

    # ---- translational dynamics ----
    # Rotate thrust to world frame
    sr, cr = math.sin(state['roll']), math.cos(state['roll'])
    sp, cp = math.sin(state['pitch']), math.cos(state['pitch'])
    sy, cy = math.sin(state['yaw']), math.cos(state['yaw'])

    # World-frame thrust (body Z is upward)
    fx = thrust_desired * (sr*sy + cr*cy*sp)
    fy = thrust_desired * (-sr*cy + cr*sp*sy)
    fz = thrust_desired * (cr * cp)

    # Drag
    fx -= params['drag_coeff_x'] * state['vx'] * abs(state['vx'])
    fy -= params['drag_coeff_y'] * state['vy'] * abs(state['vy'])
    fz -= params['drag_coeff_z'] * state['vz'] * abs(state['vz'])

    # Acceleration
    ax = fx / m
    ay = fy / m
    az = fz / m - g

    # Integrate
    state['vx'] += ax * dt
    state['vy'] += ay * dt
    state['vz'] += az * dt
    state['px'] += state['vx'] * dt
    state['py'] += state['vy'] * dt
    state['pz'] += state['vz'] * dt

    if state['pz'] < 0.0:
        state['pz'] = 0.0
        if state['vz'] < 0.0:
            state['vz'] = 0.0

    step += 1
    sim_time = step * dt


def pack_and_send():
    """Pack current state into binary FlightState_t and send to UDP 9998."""
    lat = init_lat + state['py'] * 0.00001
    lon = init_lon + state['px'] * 0.00001
    alt = state['pz']

    # Determine flight_state code
    if not airborne and abs(state['pz']) < 0.3 and abs(state['vz']) < 0.05:
        fs_code = 5  # landed
    elif not airborne and state['pz'] > 0.3:
        fs_code = 0  # ready
    elif airborne and state['pz'] < 0.5:
        fs_code = 0
    elif wp_active:
        fs_code = 2  # flying
    else:
        fs_code = 3  # hovering

    data = struct.pack(FMT,
        1,                                 # version
        int(sim_time * 1000000),           # timestamp_us
        state['px'], state['py'], state['pz'],  # position
        lat, lon, alt,                      # lat/lon/alt
        state['roll'], state['pitch'], state['yaw'],  # attitude
        state['vx'], state['vy'], state['vz'],        # velocity
        0.0, 0.0, 0.0,                                 # acc (stub)
        state['wx'], state['wy'], state['wz'],  # angular velocity
        24.5,                               # battery
        5000.0, 4800.0, 5200.0, 4900.0,    # motors
        1 if airborne else 0,               # status_word
        1,                                  # mission_id (int)
        wp_index,                             # waypoint_index
        2,                                  # flight_phase
        fs_code,                            # flight_state
    )
    status_sock.sendto(data, ('127.0.0.1', 9998))
    _monitor_sock.sendto(data, ('127.0.0.1', 9999))  # for test script


def kinematic_mock():
    """Main 50Hz loop with drone dynamics."""
    global airborne

    print('[mock_core] Drone dynamics mock — 50Hz')
    print('[mock_core]   UDP CMD  ← :9997')
    print('[mock_core]   UDP STATUS → :9998')
    print('[mock_core]   Tunable params: {}'.format(
        ', '.join(sorted(params.keys()))))
    print('[mock_core]   Tunable PID: {}'.format(
        ', '.join(sorted(pid.keys()))))
    print()

    next_tick = time.time()

    while True:
        cmds = parse_commands()
        if cmds:
            handle_commands(cmds)

        step_dynamics()
        pack_and_send()

        # Sleep to maintain 50Hz
        next_tick += DT
        now = time.time()
        if next_tick > now:
            time.sleep(next_tick - now)
        else:
            # Lagging behind — reset
            next_tick = now + DT


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Mock C-core for HIL testing')
    parser.add_argument('--csv', help='CSV trajectory file (legacy replay mode)')
    args = parser.parse_args()

    if args.csv:
        # Legacy CSV replay — not used for new tests
        from mock_core_legacy import replay_csv
        replay_csv(args.csv)
    else:
        kinematic_mock()
