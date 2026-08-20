#!/usr/bin/env python3
"""V3 fixed-wing TCP server and latest-state AirSim adapter.

This is the protocol-defined direction: Simulink/C-core is the TCP client and
this Python process accepts its long-lived connection.  It deliberately keeps
only the newest valid state; rendering never replays a FIFO backlog.
"""
from __future__ import print_function

import json
import math
import socket
import struct
import threading
import time

from config_loader import CONFIG
from shared.logger import get_logger


logger = get_logger('fixed_wing_v3_bridge')
MAX_FRAME_BYTES = 1024 * 1024
VEHICLE_ID = 'FixedWing01'
PROTOCOL_VERSION = '3.0'
STATE_RATE_HZ = 50
_REQUIRED_ENVELOPE = frozenset(('protocol_version', 'type', 'seq', 'vehicle_id', 'data'))
_FLIGHT_STATES = frozenset(('ready', 'taking_off', 'flying', 'landing', 'landed', 'fault'))
_EVENTS = frozenset(('pause', 'resume', 'reset_scene', 'mission_end'))
_active_latest_state = None
_active_lock = threading.Lock()


class ProtocolError(ValueError):
    def __init__(self, code, message, ref_seq=None):
        ValueError.__init__(self, message)
        self.code = code
        self.ref_seq = ref_seq


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProtocolError('INVALID_VALUE', '{} must be a finite number'.format(label))
    return float(value)


def _exact_object(value, keys, label):
    if not isinstance(value, dict):
        raise ProtocolError('INVALID_VALUE', '{} must be an object'.format(label))
    if set(value) != set(keys):
        raise ProtocolError('MISSING_FIELD', '{} fields must be exactly {}'.format(label, sorted(keys)))


def _vector(value, keys, label):
    _exact_object(value, keys, label)
    return {key: _finite(value[key], '{}.{}'.format(label, key)) for key in keys}


def _read_exact(connection, count):
    data = bytearray()
    while len(data) < count:
        chunk = connection.recv(count - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def recv_frame(connection):
    header = _read_exact(connection, 4)
    if header is None:
        return None
    size = struct.unpack('>I', header)[0]
    if size > MAX_FRAME_BYTES:
        raise ProtocolError('INVALID_FRAME', 'frame exceeds 1 MiB')
    body = _read_exact(connection, size)
    if body is None:
        raise ProtocolError('INVALID_FRAME', 'incomplete frame')
    try:
        message = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError('INVALID_JSON', 'invalid UTF-8 JSON: {}'.format(exc))
    if not isinstance(message, dict):
        raise ProtocolError('INVALID_JSON', 'message must be an object')
    return message


def send_frame(connection, message):
    body = json.dumps(message, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError('INVALID_FRAME', 'outbound frame exceeds 1 MiB')
    connection.sendall(struct.pack('>I', len(body)) + body)


class LatestFixedWingState(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._state = None
        self._received_at = None
        self._mission = None
        self._planned_waypoints = []
        self._actual_trajectory = []
        self._paused = False

    def replace(self, state):
        with self._lock:
            self._state = state
            self._received_at = time.monotonic()
            self._actual_trajectory.append({
                'sim_time': state['sim_time'], 'x': state['position']['x'],
                'y': state['position']['y'], 'height': state['position']['height']})
            # Visual consumers need the recent route, not an unbounded replay
            # queue.  This is history for drawing only; rendering always uses
            # _state (the latest state) above.
            if len(self._actual_trajectory) > 5000:
                del self._actual_trajectory[:1000]

    def set_mission(self, mission_id, waypoints):
        with self._lock:
            self._mission = mission_id
            self._planned_waypoints = list(waypoints)

    def event(self, event_name):
        with self._lock:
            if event_name == 'pause': self._paused = True
            elif event_name == 'resume': self._paused = False
            elif event_name == 'reset_scene':
                self._state = None; self._received_at = None
                self._mission = None; self._planned_waypoints = []
                self._actual_trajectory = []; self._paused = False

    def snapshot(self):
        with self._lock:
            state = dict(self._state) if self._state else None
            age = None if self._received_at is None else time.monotonic() - self._received_at
            return {'state': state, 'age_s': age, 'mission_id': self._mission,
                    'waypoints': list(self._planned_waypoints),
                    'actual_trajectory': list(self._actual_trajectory),
                    'paused': self._paused}


def get_hud_state():
    """Expose the exact V3 latest-state cache to HUD/logging consumers."""
    with _active_lock:
        latest = _active_latest_state
    if latest is None:
        return None
    snapshot = latest.snapshot()
    state = snapshot['state']
    if state is None:
        return {'status': 'waiting_for_vehicle_state', 'age_s': snapshot['age_s'],
                'paused': snapshot['paused'], 'mission_id': snapshot['mission_id']}
    result = dict(state)
    result.update({'age_s': snapshot['age_s'], 'paused': snapshot['paused'],
                   'stale': snapshot['age_s'] is None or snapshot['age_s'] > 0.5,
                   'timeout_warning': snapshot['age_s'] is not None and snapshot['age_s'] > 2.0,
                   'planned_waypoints': snapshot['waypoints'],
                   'actual_trajectory': snapshot['actual_trajectory']})
    return result


class FixedWingV3Session(object):
    """Strict per-connection protocol validator with latest-state semantics."""
    def __init__(self, latest_state):
        self.latest_state = latest_state
        self.last_seq = 0
        self.last_sim_time = None
        self.phase = 'hello'
        self.mission_id = None
        self._server_seq = 0

    def _response(self, message_type, data):
        self._server_seq += 1
        return {'protocol_version': PROTOCOL_VERSION, 'type': message_type,
                'seq': self._server_seq, 'vehicle_id': VEHICLE_ID, 'data': data}

    def ack(self, message):
        return self._response('ack', {'ref_seq': message['seq'], 'ref_type': message['type'], 'accepted': True})

    def error(self, error):
        data = {'code': error.code, 'message': str(error)}
        if error.ref_seq is not None: data['ref_seq'] = error.ref_seq
        return self._response('error', data)

    def _envelope(self, message):
        if set(message) != _REQUIRED_ENVELOPE:
            raise ProtocolError('MISSING_FIELD', 'message envelope fields are invalid')
        ref_seq = message.get('seq')
        if message['protocol_version'] != PROTOCOL_VERSION:
            raise ProtocolError('UNSUPPORTED_VERSION', 'protocol_version must be 3.0', ref_seq)
        if message['vehicle_id'] != VEHICLE_ID:
            raise ProtocolError('VEHICLE_ID_MISMATCH', 'vehicle_id must be FixedWing01', ref_seq)
        if isinstance(ref_seq, bool) or not isinstance(ref_seq, int) or ref_seq < 1:
            raise ProtocolError('INVALID_SEQUENCE', 'seq must be a positive integer')
        if ref_seq <= self.last_seq:
            raise ProtocolError('INVALID_SEQUENCE', 'seq must be strictly increasing', ref_seq)
        if not isinstance(message['type'], str) or not isinstance(message['data'], dict):
            raise ProtocolError('INVALID_VALUE', 'type must be string and data must be object', ref_seq)

    def _hello(self, data):
        expected = {'role': 'simulink_fixedwing_state_source', 'state_rate_hz': STATE_RATE_HZ,
                    'coordinate_convention': 'x_forward_y_right_height_up',
                    'body_frame': 'FRD', 'angle_unit': 'rad'}
        _exact_object(data, expected, 'hello.data')
        if any(data[key] != value for key, value in expected.items()):
            raise ProtocolError('INVALID_VALUE', 'hello capabilities do not match V3')
        self.phase = 'mission_plan'

    def _mission_plan(self, data):
        _exact_object(data, ('mission_id', 'replace_previous', 'waypoints'), 'mission_plan.data')
        if not isinstance(data['mission_id'], str) or not data['mission_id']:
            raise ProtocolError('INVALID_VALUE', 'mission_plan mission_id is required')
        if data['replace_previous'] is not True:
            raise ProtocolError('INVALID_VALUE', 'mission_plan replace_previous must be true')
        if not isinstance(data['waypoints'], list) or len(data['waypoints']) < 2:
            raise ProtocolError('INVALID_VALUE', 'mission_plan needs at least two waypoints')
        ids = set()
        for index, waypoint in enumerate(data['waypoints']):
            allowed = set(('id', 'x', 'y', 'height', 'target_speed'))
            if not isinstance(waypoint, dict) or not set(('id', 'x', 'y', 'height')).issubset(waypoint) or not set(waypoint).issubset(allowed):
                raise ProtocolError('MISSING_FIELD', 'mission waypoint {} is invalid'.format(index))
            if not isinstance(waypoint['id'], str) or not waypoint['id'] or waypoint['id'] in ids:
                raise ProtocolError('INVALID_VALUE', 'mission waypoint id is invalid')
            ids.add(waypoint['id'])
            for key in ('x', 'y', 'height'):
                _finite(waypoint[key], 'waypoint.{}'.format(key))
            if 'target_speed' in waypoint: _finite(waypoint['target_speed'], 'waypoint.target_speed')
        self.mission_id = data['mission_id']
        self.latest_state.set_mission(self.mission_id, data['waypoints'])
        self.phase = 'state'

    def _vehicle_state(self, data):
        required = set(('mission_id', 'sim_time', 'position', 'attitude', 'velocity',
                        'acceleration', 'angular_velocity', 'control', 'flight_state'))
        optional = set(('angular_acceleration', 'aerodynamics'))
        if not required.issubset(data) or not set(data).issubset(required | optional):
            raise ProtocolError('MISSING_FIELD', 'vehicle_state fields are invalid')
        if data['mission_id'] != self.mission_id:
            raise ProtocolError('INVALID_VALUE', 'vehicle_state mission_id does not match mission_plan')
        sim_time = _finite(data['sim_time'], 'vehicle_state.sim_time')
        if self.last_sim_time is not None and sim_time < self.last_sim_time:
            # Latest State Wins: a delayed state is intentionally ignored;
            # it must not replace the already rendered newest snapshot.
            return False
        position = _vector(data['position'], ('x', 'y', 'height'), 'position')
        attitude = _vector(data['attitude'], ('roll', 'pitch', 'yaw'), 'attitude')
        velocity = _vector(data['velocity'], ('vx', 'vy', 'vz'), 'velocity')
        acceleration = _vector(data['acceleration'], ('ax', 'ay', 'az'), 'acceleration')
        angular_velocity = _vector(data['angular_velocity'], ('p', 'q', 'r'), 'angular_velocity')
        control = data['control']
        if not isinstance(control, dict) or 'throttle' not in control or not set(control).issubset(
                ('throttle', 'aileron', 'elevator', 'rudder')):
            raise ProtocolError('MISSING_FIELD', 'control must contain throttle and optional surfaces')
        throttle = _finite(control['throttle'], 'control.throttle')
        if not 0.0 <= throttle <= 1.0:
            raise ProtocolError('INVALID_VALUE', 'control.throttle must be within [0,1]')
        for surface in ('aileron', 'elevator', 'rudder'):
            if surface in control: _finite(control[surface], 'control.{}'.format(surface))
        if data['flight_state'] not in _FLIGHT_STATES:
            raise ProtocolError('INVALID_VALUE', 'flight_state is invalid')
        normalized = {'mission_id': data['mission_id'], 'sim_time': sim_time, 'position': position,
                      'attitude': attitude, 'velocity': velocity, 'acceleration': acceleration,
                      'angular_velocity': angular_velocity, 'control': dict(control),
                      'flight_state': data['flight_state']}
        if 'angular_acceleration' in data:
            normalized['angular_acceleration'] = _vector(
                data['angular_acceleration'], ('p_dot', 'q_dot', 'r_dot'), 'angular_acceleration')
        if 'aerodynamics' in data:
            aero = _vector(data['aerodynamics'], ('airspeed', 'angle_of_attack', 'sideslip_angle'), 'aerodynamics')
            if aero['airspeed'] < 0.0:
                raise ProtocolError('INVALID_VALUE', 'aerodynamics.airspeed must be non-negative')
            normalized['aerodynamics'] = aero
        self.last_sim_time = sim_time
        self.latest_state.replace(normalized)
        return True

    def _event(self, data):
        if not isinstance(data, dict) or set(data) not in (set(('event',)), set(('event', 'mission_id'))):
            raise ProtocolError('MISSING_FIELD', 'simulation_event fields are invalid')
        if data['event'] not in _EVENTS:
            raise ProtocolError('INVALID_VALUE', 'unsupported simulation event')
        if data['event'] == 'mission_end' and data.get('mission_id') != self.mission_id:
            raise ProtocolError('INVALID_VALUE', 'mission_end mission_id does not match current mission')
        self.latest_state.event(data['event'])
        if data['event'] == 'reset_scene':
            self.mission_id = None
            self.last_sim_time = None
            self.phase = 'mission_plan'

    def observe(self, message):
        # V3 explicitly allows duplicate/older state frames to be discarded.
        # Low-rate handshake, mission and lifecycle frames remain strictly
        # sequenced and are validated by _envelope below.
        if (isinstance(message, dict) and message.get('type') == 'vehicle_state' and
                type(message.get('seq')) is int and message['seq'] <= self.last_seq):
            return None
        self._envelope(message)
        message_type = message['type']
        if self.phase == 'hello':
            if message_type != 'hello': raise ProtocolError('INVALID_SEQUENCE', 'hello must be first', message['seq'])
            self._hello(message['data'])
        elif self.phase == 'mission_plan':
            if message_type != 'mission_plan': raise ProtocolError('INVALID_SEQUENCE', 'mission_plan must follow hello', message['seq'])
            self._mission_plan(message['data'])
        elif message_type == 'mission_plan':
            self._mission_plan(message['data'])
        elif message_type == 'vehicle_state':
            self._vehicle_state(message['data'])
        elif message_type == 'simulation_event':
            self._event(message['data'])
        else:
            raise ProtocolError('UNKNOWN_MESSAGE_TYPE', 'unsupported message type {}'.format(message_type), message['seq'])
        self.last_seq = message['seq']
        return self.ack(message) if message_type != 'vehicle_state' else None


class AirSimFixedWingAdapter(object):
    """Optional state injector; imports AirSim only when explicitly enabled."""
    def __init__(self, latest_state, config):
        self.latest_state, self.config = latest_state, config
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        global _active_latest_state
        if not self.config.get('airsim_enabled', False): return None
        self._thread = threading.Thread(target=self._run, daemon=True, name='fixed_wing_v3_airsim')
        self._thread.start()
        return self._thread

    def stop(self): self._stop.set()

    def _run(self):
        try:
            import airsim
            client = airsim.MultirotorClient(ip=self.config.get('airsim_host', '127.0.0.1'))
            client.confirmConnection()
        except Exception as exc:
            logger.error('AirSim adapter unavailable: %s', exc); return
        vehicle_name = self.config.get('airsim_vehicle_name', VEHICLE_ID)
        last_sim_time = None
        while not self._stop.wait(1.0 / STATE_RATE_HZ):
            snapshot = self.latest_state.snapshot(); state = snapshot['state']
            if not state or snapshot['paused'] or snapshot['age_s'] is None or snapshot['age_s'] > 0.5:
                continue
            if state['sim_time'] == last_sim_time: continue
            last_sim_time = state['sim_time']
            try:
                position = state['position']; attitude = state['attitude']; velocity = state['velocity']
                acceleration = state['acceleration']
                kin = airsim.KinematicsState()
                kin.position = airsim.Vector3r(position['x'], position['y'], -position['height'])
                kin.orientation = airsim.to_quaternion(attitude['pitch'], attitude['roll'], attitude['yaw'])
                kin.linear_velocity = airsim.Vector3r(velocity['vx'], velocity['vy'], -velocity['vz'])
                kin.linear_acceleration = airsim.Vector3r(acceleration['ax'], acceleration['ay'], -acceleration['az'])
                client.simSetKinematics(kin, True, vehicle_name=vehicle_name)
            except Exception as exc:
                logger.error('AirSim state injection failed: %s', exc)


class FixedWingV3BridgeServer(object):
    def __init__(self, config=None, latest_state=None):
        self.config = config or CONFIG.get('fixed_wing_v3', {})
        self.latest_state = latest_state or LatestFixedWingState()
        self._stop = threading.Event(); self._server = None; self._thread = None
        self._health_thread = None; self._timeout_warned = False
        self._adapter = AirSimFixedWingAdapter(self.latest_state, self.config)

    def start(self):
        host = self.config.get('host', '0.0.0.0'); port = int(self.config.get('port', 5000))
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._server.bind((host, port)); self._server.listen(1); self._server.settimeout(0.5)
        with _active_lock:
            _active_latest_state = self.latest_state
        self._adapter.start()
        self._thread = threading.Thread(target=self._serve, daemon=True, name='fixed_wing_v3_server')
        self._health_thread = threading.Thread(target=self._health_monitor, daemon=True,
                                               name='fixed_wing_v3_health')
        self._thread.start(); self._health_thread.start(); logger.info('V3 server listening on %s:%s', host, port)
        return self._thread

    def stop(self):
        self._stop.set(); self._adapter.stop()
        if self._server:
            try: self._server.close()
            except OSError: pass

    def _serve(self):
        while not self._stop.is_set():
            try: connection, address = self._server.accept()
            except socket.timeout: continue
            except OSError: return
            logger.info('V3 client connected from %s:%s', address[0], address[1])
            try:
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                connection.settimeout(0.5); session = FixedWingV3Session(self.latest_state)
                while not self._stop.is_set():
                    try: message = recv_frame(connection)
                    except socket.timeout: continue
                    except ProtocolError as exc:
                        send_frame(connection, session.error(exc)); continue
                    if message is None: break
                    try: response = session.observe(message)
                    except ProtocolError as exc: response = session.error(exc)
                    if response is not None: send_frame(connection, response)
            except (OSError, ProtocolError) as exc:
                logger.warning('V3 client session ended: %s', exc)
            finally:
                try: connection.close()
                except OSError: pass

    def _health_monitor(self):
        while not self._stop.wait(0.5):
            age = self.latest_state.snapshot()['age_s']
            if age is not None and age > 2.0 and not self._timeout_warned:
                logger.warning('V3 vehicle_state timeout: %.3f s without a fresh state', age)
                self._timeout_warned = True
            elif age is not None and age <= 0.5 and self._timeout_warned:
                logger.info('V3 vehicle_state stream recovered')
                self._timeout_warned = False
