"""Software-only virtual quadrotor flight-controller integration.

The generated C model remains the plant.  This service turns its fresh state
into virtual sensors, estimates vehicle state only from those sensor frames,
and closes a position/attitude/motor-control loop through ``physical_uut``.
A future CAN, Ethernet or serial UUT driver can retain the same boundary.
"""
from __future__ import print_function

import datetime
import gzip
import json
import math
import os
import random
import shutil
import socket
import threading
import time

from core_client import core_send
from shared.flight_state import parse_flight_state
from shared.vehicle_profile import VehicleProfileError, load_profile
from .physical_uut import PhysicalUutAdapter


_ACTIVE_SERVICE = None
_ACTIVE_LOCK = threading.Lock()
_FLIGHT_MODES = set(('MANUAL', 'OFFBOARD', 'FAILSAFE', 'LAND', 'HOLD'))


def register_service(service):
    global _ACTIVE_SERVICE
    with _ACTIVE_LOCK:
        _ACTIVE_SERVICE = service


def unregister_service(service):
    global _ACTIVE_SERVICE
    with _ACTIVE_LOCK:
        if _ACTIVE_SERVICE is service:
            _ACTIVE_SERVICE = None


def handle_command(cmd, params):
    """Handle the narrow WebSocket control surface for the virtual UUT."""
    with _ACTIVE_LOCK:
        service = _ACTIVE_SERVICE
    if service is None:
        return {'accepted': False, 'reason': 'virtual_quad_fc service is disabled'}
    if cmd == 'virtual_fc_start':
        return service.start_scenario(params.get('scenario', 'idle'))
    if cmd == 'virtual_fc_stop':
        return service.stop_scenario()
    if cmd == 'virtual_fc_status':
        return {'accepted': True, 'virtual_fc': service.status()}
    if cmd == 'virtual_fc_inject_fault':
        return service.inject_fault(params)
    if cmd == 'virtual_fc_set_target':
        return service.set_target(params)
    if cmd == 'virtual_fc_load_route':
        return service.load_route(params)
    if cmd == 'virtual_fc_reload_contract':
        return service.reload_contract(params.get('contract_path'))
    return {'accepted': False, 'reason': 'unsupported virtual FC command'}


def activate_deployed_contract(contract_path):
    """Safely follow a verified model deployment when the service is enabled."""
    with _ACTIVE_LOCK:
        service = _ACTIVE_SERVICE
    if service is None:
        return None
    service.stop_scenario()
    return service.reload_contract(contract_path)


class VirtualQuadrotorUutAdapter(PhysicalUutAdapter):
    """Normalized virtual-UUT endpoint with contract-bound actuator checks.

    The legacy class name is preserved for integrations.  It accepts an
    arbitrary V3 actuator list, rather than assuming four motor channels.
    """
    def __init__(self, hardware_id, recorder=None, actuators=None):
        self.hardware_id = str(hardware_id)
        self.recorder = recorder
        self._latest = None
        self._last_sequence = -1
        self._last_timestamp_us = -1
        self._closed = False
        self._lock = threading.Lock()
        self.configure_actuators(actuators or [
            {'name': 'motor_01', 'min': 0.0, 'max': 1.0, 'safe_value': 0.0},
            {'name': 'motor_02', 'min': 0.0, 'max': 1.0, 'safe_value': 0.0},
            {'name': 'motor_03', 'min': 0.0, 'max': 1.0, 'safe_value': 0.0},
            {'name': 'motor_04', 'min': 0.0, 'max': 1.0, 'safe_value': 0.0}])
        self.stats = {'accepted_actuators': 0, 'rejected_actuators': 0,
                      'sensor_frames': 0, 'sequence_discards': 0,
                      'timestamp_discards': 0}

    def _record(self, kind, frame, accepted=None, reason=None):
        if self.recorder is not None:
            self.recorder.record(kind, frame, accepted=accepted, reason=reason)

    def configure_actuators(self, actuators):
        if not isinstance(actuators, list) or not actuators:
            raise ValueError('virtual UUT requires at least one actuator')
        normalized = []
        for channel in actuators:
            if not isinstance(channel, dict) or not isinstance(channel.get('name'), str):
                raise ValueError('actuator requires a name')
            minimum = float(channel.get('min')); maximum = float(channel.get('max'))
            safe_value = float(channel.get('safe_value'))
            if not all(math.isfinite(value) for value in (minimum, maximum, safe_value)) or \
                    minimum > maximum or not minimum <= safe_value <= maximum:
                raise ValueError('actuator range is invalid')
            normalized.append({'name': channel['name'], 'min': minimum,
                               'max': maximum, 'safe_value': safe_value})
        if len(set(channel['name'] for channel in normalized)) != len(normalized):
            raise ValueError('actuator names must be unique')
        with self._lock:
            self.actuators = normalized

    def _finite_actuator_values(self, values):
        return isinstance(values, list) and len(values) == len(self.actuators) and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(float(value)) and self.actuators[index]['min'] <= float(value) <=
            self.actuators[index]['max'] for index, value in enumerate(values))

    def submit_actuator_frame(self, frame):
        """Validate, monotonically order and retain one virtual-FC command."""
        reason = None
        if not isinstance(frame, dict):
            reason = 'frame must be an object'
        elif frame.get('frame_type') != 'actuator_command':
            reason = 'frame_type must be actuator_command'
        elif frame.get('hardware_id') != self.hardware_id:
            reason = 'hardware_id mismatch'
        elif not isinstance(frame.get('sequence'), int) or isinstance(frame.get('sequence'), bool):
            reason = 'sequence must be an integer'
        elif not isinstance(frame.get('timestamp_us'), int) or isinstance(frame.get('timestamp_us'), bool):
            reason = 'timestamp_us must be an integer'
        elif not isinstance(frame.get('armed'), bool) or not isinstance(frame.get('valid'), bool):
            reason = 'armed and valid must be booleans'
        elif frame.get('flight_mode') not in _FLIGHT_MODES:
            reason = 'unsupported flight_mode'
        else:
            values = frame.get('actuator_values', frame.get('motor_command'))
            channels = frame.get('actuator_channels')
            if not self._finite_actuator_values(values):
                reason = 'actuator_values violate the contract count or range'
            elif channels is not None and channels != [channel['name'] for channel in self.actuators]:
                reason = 'actuator_channels do not match the active contract'
        with self._lock:
            if reason is None and frame['sequence'] <= self._last_sequence:
                self.stats['sequence_discards'] += 1; reason = 'non-monotonic sequence'
            if reason is None and frame['timestamp_us'] <= self._last_timestamp_us:
                self.stats['timestamp_discards'] += 1; reason = 'non-monotonic timestamp_us'
            if reason is None and not frame['valid']:
                reason = 'invalid actuator frame'
            if reason is None:
                self._latest = dict(frame)
                self._latest['actuator_values'] = [float(v) for v in values]
                self._last_sequence = frame['sequence']
                self._last_timestamp_us = frame['timestamp_us']
                self.stats['accepted_actuators'] += 1
            else:
                self.stats['rejected_actuators'] += 1
        self._record('actuator_command', frame, accepted=reason is None, reason=reason)
        return reason is None, reason

    def publish_sensor(self, sensor_frame):
        if self._closed:
            raise RuntimeError('virtual UUT adapter is closed')
        self.stats['sensor_frames'] += 1
        self._record('sensor', sensor_frame, accepted=True)

    def poll_actuators(self):
        with self._lock:
            return None if self._latest is None else dict(self._latest)

    def close(self):
        self._closed = True


class _RunRecorder(object):
    """Bounded, compressed per-run protocol recorder.

    Virtual-FC traffic includes a 250 Hz actuator stream, so an unbounded
    NDJSON file can consume tens of gigabytes during a long soak run.  Keep a
    readable active file, compress completed chunks, and stop recording once
    the configured raw-data allowance for this run is reached.
    """
    def __init__(self, root, max_file_bytes=64 * 1024 * 1024,
                 max_run_bytes=512 * 1024 * 1024, retention_days=14):
        if max_file_bytes < 1 or max_run_bytes < max_file_bytes:
            raise ValueError('virtual FC recorder byte limits are invalid')
        if retention_days < 0:
            raise ValueError('virtual FC recorder retention_days must be non-negative')
        self.root = root
        self.max_file_bytes = int(max_file_bytes)
        self.max_run_bytes = int(max_run_bytes)
        self.retention_days = int(retention_days)
        os.makedirs(root, exist_ok=True)
        self._purge_expired_runs()
        run_id = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        self.directory = os.path.join(root, run_id)
        os.makedirs(self.directory)
        self.path = os.path.join(self.directory, 'frames.ndjson')
        self._lock = threading.Lock()
        self._output = open(self.path, 'a')
        self._current_bytes = 0
        self._run_bytes = 0
        self._part = 0
        self.limited = False

    def _purge_expired_runs(self):
        if not self.retention_days:
            return
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=self.retention_days)
        for name in os.listdir(self.root):
            try:
                created = datetime.datetime.strptime(name, '%Y%m%dT%H%M%SZ')
            except ValueError:
                continue
            directory = os.path.join(self.root, name)
            if os.path.isdir(directory) and created < cutoff:
                shutil.rmtree(directory)

    def _rotate(self):
        self._output.flush()
        self._output.close()
        self._part += 1
        compressed = os.path.join(self.directory, 'frames.{:04d}.ndjson.gz'.format(self._part))
        temporary = compressed + '.tmp'
        try:
            with open(self.path, 'rb') as source:
                with gzip.open(temporary, 'wb') as destination:
                    shutil.copyfileobj(source, destination)
            os.replace(temporary, compressed)
            os.remove(self.path)
        except Exception:
            # Preserve the active, uncompressed evidence if compression fails.
            if os.path.exists(temporary):
                os.remove(temporary)
        self._output = open(self.path, 'a')
        self._current_bytes = 0

    def record(self, kind, frame, accepted=None, reason=None):
        event = {'recorded_at_us': int(time.time() * 1000000), 'kind': kind, 'frame': frame}
        if accepted is not None:
            event['accepted'] = bool(accepted)
        if reason:
            event['reason'] = reason
        line = json.dumps(event, separators=(',', ':'), sort_keys=True, allow_nan=False)
        encoded = (line + '\n').encode('utf-8')
        with self._lock:
            if self._output.closed or self.limited:
                return False
            if self._run_bytes + len(encoded) > self.max_run_bytes:
                self._output.flush()
                self.limited = True
                return False
            self._output.write(line + '\n')
            self._current_bytes += len(encoded)
            self._run_bytes += len(encoded)
            if self._current_bytes >= self.max_file_bytes:
                self._rotate()
            return True

    def close(self):
        with self._lock:
            if not self._output.closed:
                self._output.flush()
                self._output.close()


class VirtualQuadrotorClosedLoopController(object):
    """Small deterministic cascaded controller driven only by sensor frames.

    It is intentionally a virtual-UUT control law, not a replacement for the
    C model.  GPS/barometer provide position and velocity; gyro integration
    provides the attitude estimate used by the inner loop.  This makes sensor
    loss meaningful: a stale estimate produces a safe zero command instead of
    continuing the last scripted motor value.
    """
    GRAVITY_MPS2 = 9.80665

    def __init__(self, config):
        self.origin_lat_deg = float(config.get('origin_lat_deg', 31.2304))
        self.origin_lon_deg = float(config.get('origin_lon_deg', 121.4737))
        self.origin_alt_m = float(config.get('origin_alt_m', 10.0))
        self.mass_kg = self._positive(config.get('mass_kg', 1.5), 1.5)
        self.thrust_coefficient_n = self._positive(config.get('thrust_coefficient_n', 4.2), 4.2)
        self.motor_efficiency = self._positive(config.get('motor_efficiency', 1.0), 1.0)
        self.position_ned_m = None
        self.velocity_ned_mps = None
        self.roll_rad = 0.0; self.pitch_rad = 0.0; self.yaw_rad = 0.0
        self.body_rates_radps = [0.0, 0.0, 0.0]
        self._last_imu_timestamp_us = None
        self._last_imu_wall_s = None; self._last_gps_wall_s = None
        self._last_baro_wall_s = None
        self.target = None
        self.route = []; self.route_index = 0
        self.scenario = 'stopped'
        self.stats = {'imu_updates': 0, 'gps_updates': 0, 'barometer_updates': 0,
                      'sensor_rejects': 0, 'failsafe_commands': 0,
                      'waypoints_completed': 0}

    @staticmethod
    def _positive(value, fallback):
        try: value = float(value)
        except (TypeError, ValueError): return fallback
        return value if math.isfinite(value) and value > 0.0 else fallback

    @staticmethod
    def _clamp(value, minimum, maximum):
        return min(maximum, max(minimum, value))

    @staticmethod
    def _wrap_pi(value):
        while value > math.pi: value -= 2.0 * math.pi
        while value < -math.pi: value += 2.0 * math.pi
        return value

    @staticmethod
    def _finite_values(values, count):
        return isinstance(values, list) and len(values) == count and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(float(value)) for value in values)

    def ingest(self, frame, now):
        """Consume a normalized virtual sensor frame; truth is never used."""
        if not isinstance(frame, dict) or not frame.get('valid', False):
            self.stats['sensor_rejects'] += 1; return False
        frame_type = frame.get('frame_type')
        timestamp_us = frame.get('timestamp_us')
        if not isinstance(timestamp_us, int) or isinstance(timestamp_us, bool):
            self.stats['sensor_rejects'] += 1; return False
        if frame_type == 'imu':
            rates = frame.get('gyro_radps')
            if not self._finite_values(rates, 3): self.stats['sensor_rejects'] += 1; return False
            if self._last_imu_timestamp_us is not None:
                dt_s = (timestamp_us - self._last_imu_timestamp_us) / 1000000.0
                if 0.0 < dt_s <= 0.1:
                    # Small-angle integration is deterministic and sufficient
                    # for the bounded HIL manoeuvres; yaw is additionally
                    # corrected by GPS course while translating.
                    self.roll_rad = self._wrap_pi(self.roll_rad + float(rates[0]) * dt_s)
                    self.pitch_rad = self._wrap_pi(self.pitch_rad + float(rates[1]) * dt_s)
                    self.yaw_rad = self._wrap_pi(self.yaw_rad + float(rates[2]) * dt_s)
            self._last_imu_timestamp_us = timestamp_us
            self.body_rates_radps = [float(value) for value in rates]
            self._last_imu_wall_s = now; self.stats['imu_updates'] += 1
            return True
        if frame_type == 'gps':
            velocity = frame.get('velocity_ned_mps')
            if not self._finite_values(velocity, 3) or not all(
                    isinstance(frame.get(name), (int, float)) and math.isfinite(float(frame[name]))
                    for name in ('latitude_deg', 'longitude_deg', 'altitude_m')):
                self.stats['sensor_rejects'] += 1; return False
            latitude = float(frame['latitude_deg']); longitude = float(frame['longitude_deg'])
            north = (latitude - self.origin_lat_deg) * 111111.0
            east = (longitude - self.origin_lon_deg) * 111111.0 * max(
                math.cos(math.radians(self.origin_lat_deg)), 1.0e-6)
            self.position_ned_m = [north, east, self.origin_alt_m - float(frame['altitude_m'])]
            self.velocity_ned_mps = [float(value) for value in velocity]
            speed = math.hypot(self.velocity_ned_mps[0], self.velocity_ned_mps[1])
            if speed > 0.25 and isinstance(frame.get('heading_deg'), (int, float)):
                course = math.radians(float(frame['heading_deg']))
                self.yaw_rad = self._wrap_pi(0.85 * self.yaw_rad + 0.15 * course)
            self._last_gps_wall_s = now; self.stats['gps_updates'] += 1
            return True
        if frame_type == 'barometer':
            altitude = frame.get('altitude_m')
            if not isinstance(altitude, (int, float)) or not math.isfinite(float(altitude)):
                self.stats['sensor_rejects'] += 1; return False
            if self.position_ned_m is not None:
                self.position_ned_m[2] = self.origin_alt_m - float(altitude)
            self._last_baro_wall_s = now; self.stats['barometer_updates'] += 1
            return True
        return False

    def ready(self, now):
        return self.position_ned_m is not None and self.velocity_ned_mps is not None and \
            self._last_imu_wall_s is not None and self._last_gps_wall_s is not None and \
            self._last_baro_wall_s is not None and now - self._last_imu_wall_s <= 0.10 and \
            now - self._last_gps_wall_s <= 0.20 and now - self._last_baro_wall_s <= 0.20

    def _set_target(self, north_m, east_m, down_m, yaw_rad=None, landing=False):
        values = (north_m, east_m, down_m)
        if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values):
            raise ValueError('target coordinates must be finite')
        if yaw_rad is not None and (not isinstance(yaw_rad, (int, float)) or not math.isfinite(float(yaw_rad))):
            raise ValueError('target yaw must be finite')
        self.target = {'north_m': float(north_m), 'east_m': float(east_m),
                       'down_m': float(down_m), 'yaw_rad': self.yaw_rad if yaw_rad is None else float(yaw_rad),
                       'landing': bool(landing)}

    def set_target(self, north_m, east_m, down_m, yaw_deg=None):
        self._set_target(north_m, east_m, down_m,
                         None if yaw_deg is None else math.radians(float(yaw_deg)))
        self.route = []; self.route_index = 0; self.scenario = 'target'

    def load_route(self, waypoints):
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError('waypoints must be a non-empty array')
        route = []
        for waypoint in waypoints:
            if not isinstance(waypoint, dict): raise ValueError('waypoint must be an object')
            try:
                north = float(waypoint['north_m']); east = float(waypoint['east_m']); down = float(waypoint['down_m'])
            except (KeyError, TypeError, ValueError):
                raise ValueError('waypoint requires north_m/east_m/down_m')
            if not all(math.isfinite(value) for value in (north, east, down)):
                raise ValueError('waypoint coordinates must be finite')
            yaw = waypoint.get('yaw_deg')
            route.append({'north_m': north, 'east_m': east, 'down_m': down,
                          'yaw_rad': self.yaw_rad if yaw is None else math.radians(float(yaw)),
                          'landing': bool(waypoint.get('landing', False))})
        self.route = route; self.route_index = 0; self.target = dict(route[0]); self.scenario = 'route'

    def start_scenario(self, scenario):
        self.scenario = scenario; self.route = []; self.route_index = 0
        if scenario in ('stopped', 'idle'):
            self.target = None; return True
        if self.position_ned_m is None:
            self.target = None; return False
        north, east, down = self.position_ned_m
        if scenario == 'takeoff': self._set_target(north, east, min(down - 5.0, -5.0), self.yaw_rad)
        elif scenario == 'hover': self._set_target(north, east, down, self.yaw_rad)
        elif scenario == 'forward': self._set_target(north + 10.0, east, down, self.yaw_rad)
        elif scenario == 'turn': self._set_target(north, east, down, self.yaw_rad + math.pi / 2.0)
        elif scenario == 'land': self._set_target(north, east, 0.0, self.yaw_rad, landing=True)
        else: raise ValueError('unsupported scenario')
        return True

    def _try_initialize_pending_scenario(self):
        if self.target is None and self.scenario not in ('stopped', 'idle', 'target', 'route'):
            self.start_scenario(self.scenario)

    def _advance_route_if_reached(self):
        if self.target is None or self.position_ned_m is None or self.velocity_ned_mps is None:
            return
        north_error = self.target['north_m'] - self.position_ned_m[0]
        east_error = self.target['east_m'] - self.position_ned_m[1]
        down_error = self.target['down_m'] - self.position_ned_m[2]
        if math.hypot(north_error, east_error) > 0.30 or abs(down_error) > 0.20 or \
                math.sqrt(sum(value * value for value in self.velocity_ned_mps)) > 0.40:
            return
        if self.target.get('landing'):
            self.target = None; self.scenario = 'idle'; return
        if self.route and self.route_index + 1 < len(self.route):
            self.route_index += 1; self.target = dict(self.route[self.route_index])
            self.stats['waypoints_completed'] += 1

    def _control_demand(self, now):
        self._try_initialize_pending_scenario()
        if self.scenario in ('stopped', 'idle') or self.target is None:
            return None, False, 'MANUAL'
        if not self.ready(now):
            self.stats['failsafe_commands'] += 1
            return None, False, 'FAILSAFE'
        self._advance_route_if_reached()
        if self.target is None:
            return None, False, 'MANUAL'
        north_error = self.target['north_m'] - self.position_ned_m[0]
        east_error = self.target['east_m'] - self.position_ned_m[1]
        down_error = self.target['down_m'] - self.position_ned_m[2]
        desired_vn = self._clamp(0.8 * north_error, -3.0, 3.0)
        desired_ve = self._clamp(0.8 * east_error, -3.0, 3.0)
        desired_vd = self._clamp(0.9 * down_error, -1.5, 1.5)
        acceleration_n = self._clamp(1.6 * (desired_vn - self.velocity_ned_mps[0]), -3.0, 3.0)
        acceleration_e = self._clamp(1.6 * (desired_ve - self.velocity_ned_mps[1]), -3.0, 3.0)
        acceleration_d = self._clamp(1.8 * (desired_vd - self.velocity_ned_mps[2]), -2.5, 2.5)
        forward_acceleration = math.cos(self.yaw_rad) * acceleration_n + math.sin(self.yaw_rad) * acceleration_e
        right_acceleration = -math.sin(self.yaw_rad) * acceleration_n + math.cos(self.yaw_rad) * acceleration_e
        pitch_target = self._clamp(math.atan2(-forward_acceleration, self.GRAVITY_MPS2 - acceleration_d), -0.45, 0.45)
        roll_target = self._clamp(math.atan2(right_acceleration, self.GRAVITY_MPS2 - acceleration_d), -0.45, 0.45)
        yaw_error = self._wrap_pi(self.target['yaw_rad'] - self.yaw_rad)
        collective = math.sqrt(self._clamp(self.mass_kg * (self.GRAVITY_MPS2 - acceleration_d) /
                                            (4.0 * self.thrust_coefficient_n * self.motor_efficiency ** 2), 0.0, 1.0))
        roll_mix = self._clamp(0.22 * (roll_target - self.roll_rad) - 0.04 * self.body_rates_radps[0], -0.12, 0.12)
        pitch_mix = self._clamp(0.22 * (pitch_target - self.pitch_rad) - 0.04 * self.body_rates_radps[1], -0.12, 0.12)
        yaw_mix = self._clamp(0.12 * yaw_error - 0.03 * self.body_rates_radps[2], -0.08, 0.08)
        mode = 'LAND' if self.target.get('landing') else 'OFFBOARD'
        return {'collective': collective, 'roll': roll_mix, 'pitch': pitch_mix,
                'yaw': yaw_mix, 'north_error': north_error, 'east_error': east_error,
                'down_error': down_error}, True, mode

    def command(self, now):
        demand, armed, mode = self._control_demand(now)
        if not armed:
            return [0.0] * 4, False, mode
        motor = [demand['collective'] + demand['roll'] + demand['pitch'] - demand['yaw'],
                 demand['collective'] - demand['roll'] + demand['pitch'] + demand['yaw'],
                 demand['collective'] - demand['roll'] - demand['pitch'] - demand['yaw'],
                 demand['collective'] + demand['roll'] - demand['pitch'] + demand['yaw']]
        return [self._clamp(value, 0.0, 1.0) for value in motor], True, mode

    def status(self, now):
        sensor_age_ms = lambda timestamp: None if timestamp is None else round((now - timestamp) * 1000.0, 3)
        return {'ready': self.ready(now), 'scenario': self.scenario, 'target': self.target,
                'route_index': self.route_index, 'route_count': len(self.route),
                'sensor_age_ms': {'imu': sensor_age_ms(self._last_imu_wall_s),
                                  'gps': sensor_age_ms(self._last_gps_wall_s),
                                  'barometer': sensor_age_ms(self._last_baro_wall_s)},
                'estimate': {'position_ned_m': self.position_ned_m,
                             'velocity_ned_mps': self.velocity_ned_mps,
                             'attitude_rpy_rad': [self.roll_rad, self.pitch_rad, self.yaw_rad]},
                'stats': dict(self.stats)}


class ContractMultirotorClosedLoopController(VirtualQuadrotorClosedLoopController):
    """N-rotor controller using an explicit contract rotor allocation matrix."""
    def __init__(self, config, profile):
        profile_config = dict(config)
        for parameter in profile.get('parameters', []):
            if parameter.get('name') in ('mass_kg', 'thrust_coefficient_n', 'motor_efficiency') and \
                    parameter.get('name') not in profile_config:
                profile_config[parameter['name']] = parameter.get('default')
        super(ContractMultirotorClosedLoopController, self).__init__(profile_config)
        self.profile = profile
        self.actuators = list(profile['actuators'])
        self._rotors_by_channel = {rotor['channel']: rotor for rotor in profile['rotors']}
        self._allocation = self._build_allocation()

    @staticmethod
    def _solve(matrix, vector):
        """Small Gaussian solver, avoiding a numerical-library dependency."""
        size = len(vector)
        augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
        for column in range(size):
            pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
            if abs(augmented[pivot][column]) < 1.0e-8: return None
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            scale = augmented[column][column]
            augmented[column] = [value / scale for value in augmented[column]]
            for row in range(size):
                if row == column: continue
                scale = augmented[row][column]
                augmented[row] = [augmented[row][item] - scale * augmented[column][item]
                                  for item in range(size + 1)]
        return [augmented[row][-1] for row in range(size)]

    def _build_allocation(self):
        # Rows are collective, roll, pitch and yaw.  The least-norm solution
        # distributes each demand across any explicitly described rotor count.
        radius = max(math.hypot(rotor['position_m'][0], rotor['position_m'][1])
                     for rotor in self.profile['rotors'])
        columns = []
        for channel in self.actuators:
            rotor = self._rotors_by_channel[channel['name']]
            x, y = rotor['position_m']
            columns.append([rotor['thrust_scale'], rotor['thrust_scale'] * y / radius,
                            -rotor['thrust_scale'] * x / radius,
                            rotor['thrust_scale'] * (-1.0 if rotor['spin'] == 'cw' else 1.0)])
        gram = [[sum(columns[column][row] * columns[column][other]
                     for column in range(len(columns))) for other in range(4)] for row in range(4)]
        # Profile validity includes geometrical controllability, not just a
        # syntactically correct list of rotors.
        if self._solve(gram, [1.0, 0.0, 0.0, 0.0]) is None:
            raise VehicleProfileError('multirotor rotor layout has no four-axis control authority')
        return columns, gram

    def command(self, now):
        demand, armed, mode = self._control_demand(now)
        if not armed:
            return [channel['safe_value'] for channel in self.actuators], False, mode
        columns, gram = self._allocation
        count = len(self.actuators)
        solution = self._solve(gram, [count * demand['collective'], count * demand['roll'],
                                      count * demand['pitch'], count * demand['yaw']])
        if solution is None:
            self.stats['failsafe_commands'] += 1
            return [channel['safe_value'] for channel in self.actuators], False, 'FAILSAFE'
        values = [sum(columns[index][row] * solution[row] for row in range(4))
                  for index in range(count)]
        return [self._clamp(values[index], self.actuators[index]['min'], self.actuators[index]['max'])
                for index in range(count)], True, mode


class FixedWingClosedLoopController(VirtualQuadrotorClosedLoopController):
    """Course, altitude and airspeed controller for named fixed-wing axes."""
    def __init__(self, config, profile):
        super(FixedWingClosedLoopController, self).__init__(config)
        self.profile = profile; self.actuators = list(profile['actuators'])
        self.axis_map = dict(profile['axis_map'])
        self.cruise_speed_mps = float(profile['cruise_speed_mps'])
        self._channel_index = {channel['name']: index for index, channel in enumerate(self.actuators)}

    def start_scenario(self, scenario):
        self.scenario = scenario; self.route = []; self.route_index = 0
        if scenario in ('stopped', 'idle'):
            self.target = None; return True
        if scenario not in ('takeoff', 'forward', 'turn', 'land'):
            self.scenario = 'stopped'
            raise ValueError('fixed_wing scenario must be idle/takeoff/forward/turn/land')
        if self.position_ned_m is None:
            self.target = None; return False
        north, east, down = self.position_ned_m
        if scenario == 'takeoff': self._set_target(north + 80.0, east, min(down - 20.0, -10.0), self.yaw_rad)
        elif scenario == 'forward': self._set_target(north + 120.0, east, down, self.yaw_rad)
        elif scenario == 'turn':
            yaw = self.yaw_rad + math.pi / 2.0
            self._set_target(north + 80.0 * math.cos(yaw), east + 80.0 * math.sin(yaw), down, yaw)
        elif scenario == 'land': self._set_target(north + 150.0, east, 0.0, self.yaw_rad, landing=True)
        return True

    def command(self, now):
        self._try_initialize_pending_scenario()
        if self.scenario in ('stopped', 'idle') or self.target is None:
            return [channel['safe_value'] for channel in self.actuators], False, 'MANUAL'
        if not self.ready(now):
            self.stats['failsafe_commands'] += 1
            return [channel['safe_value'] for channel in self.actuators], False, 'FAILSAFE'
        self._advance_route_if_reached()
        if self.target is None:
            return [channel['safe_value'] for channel in self.actuators], False, 'MANUAL'
        north_error = self.target['north_m'] - self.position_ned_m[0]
        east_error = self.target['east_m'] - self.position_ned_m[1]
        down_error = self.target['down_m'] - self.position_ned_m[2]
        desired_course = math.atan2(east_error, north_error) if math.hypot(north_error, east_error) > 1.0 else self.target['yaw_rad']
        course_error = self._wrap_pi(desired_course - self.yaw_rad)
        speed = math.hypot(self.velocity_ned_mps[0], self.velocity_ned_mps[1])
        throttle = self._clamp(0.55 + 0.04 * (self.cruise_speed_mps - speed) -
                               0.015 * down_error, 0.0, 1.0)
        roll = self._clamp(1.1 * course_error - 0.10 * self.body_rates_radps[0], -1.0, 1.0)
        pitch = self._clamp(-0.09 * down_error - 0.12 * self.velocity_ned_mps[2] -
                            0.08 * self.body_rates_radps[1], -1.0, 1.0)
        yaw = self._clamp(0.65 * self._wrap_pi(self.target['yaw_rad'] - self.yaw_rad) -
                          0.10 * self.body_rates_radps[2], -1.0, 1.0)
        command = {'throttle': throttle, 'roll': roll, 'pitch': pitch, 'yaw': yaw}
        values = [channel['safe_value'] for channel in self.actuators]
        for axis, normalized in command.items():
            index = self._channel_index[self.axis_map[axis]]; channel = self.actuators[index]
            values[index] = self._clamp(normalized, channel['min'], channel['max'])
        return values, True, 'LAND' if self.target.get('landing') else 'OFFBOARD'


def controller_from_profile(config, profile):
    if profile['vehicle_kind'] == 'multirotor':
        return ContractMultirotorClosedLoopController(config, profile)
    if profile['vehicle_kind'] == 'fixed_wing':
        return FixedWingClosedLoopController(config, profile)
    raise VehicleProfileError('unsupported vehicle kind')


class VirtualQuadrotorFcService(object):
    """250 Hz virtual sensor publisher and closed-loop quadrotor FC."""
    def __init__(self, config, adapter=None, command_send=None, clock=None, sleep=None,
                 recorder_root=None):
        self.config = dict(config)
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.command_send = command_send or core_send
        self.hardware_id = str(config.get('hardware_id', 'virtual_quad_fc_01'))
        self.command_rate_hz = int(config.get('command_rate_hz', 250))
        self.imu_rate_hz = int(config.get('imu_rate_hz', 250))
        self.barometer_rate_hz = int(config.get('barometer_rate_hz', 50))
        self.gps_rate_hz = int(config.get('gps_rate_hz', 20))
        self.health_rate_hz = int(config.get('health_rate_hz', 10))
        if min(self.command_rate_hz, self.imu_rate_hz, self.barometer_rate_hz,
               self.gps_rate_hz, self.health_rate_hz) < 1 or self.command_rate_hz > 1000:
            raise ValueError('virtual_quad_fc rates must be positive and command rate <= 1000 Hz')
        self.origin_lat_deg = float(config.get('origin_lat_deg', 31.2304))
        self.origin_lon_deg = float(config.get('origin_lon_deg', 121.4737))
        self.origin_alt_m = float(config.get('origin_alt_m', 10.0))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        recording = config.get('recording', {})
        if not isinstance(recording, dict):
            raise ValueError('virtual_quad_fc.recording must be an object')
        self.recorder = _RunRecorder(
            recorder_root or os.path.join(project_root, 'runtime', 'virtual_fc'),
            max_file_bytes=int(recording.get('max_file_mb', 64)) * 1024 * 1024,
            max_run_bytes=int(recording.get('max_run_mb', 512)) * 1024 * 1024,
            retention_days=int(recording.get('retention_days', 14)))
        self.adapter = adapter or VirtualQuadrotorUutAdapter(self.hardware_id, self.recorder)
        self._actuator_sequence = 0; self._last_dispatched_frame = None; self._delayed = []
        self._scenario = 'stopped'; self._scenario_started = 0.0
        self.vehicle_profile = None
        self.contract_path = config.get('contract_path') or os.environ.get('HIL_ACTIVE_CONTRACT_PATH')
        if not self.contract_path:
            candidate = os.path.join(project_root, 'runtime', 'active_vehicle_contract.json')
            self.contract_path = candidate if os.path.isfile(candidate) else None
        self.controller = VirtualQuadrotorClosedLoopController(config)
        if self.contract_path:
            result = self.reload_contract(self.contract_path, initial=True)
            if not result.get('accepted'):
                raise ValueError(result['reason'])
        self._period_s = 1.0 / self.command_rate_hz
        self._running = threading.Event()
        self._thread = None
        self._sensor_sock = None
        self._latest_state = None
        self._last_sensor_sequence = -1
        self._faults = {}
        self._lock = threading.Lock()
        self._next_baro = 0.0; self._next_gps = 0.0; self._next_health = 0.0
        self._next_imu = 0.0
        self.stats = {'state_frames': 0, 'state_parse_errors': 0, 'imu_frames': 0,
                      'barometer_frames': 0, 'gps_frames': 0, 'health_frames': 0,
                      'commands_sent': 0, 'command_send_failures': 0,
                      'invalid_sensor_suppressed': 0}

    def _record(self, kind, frame, accepted=None, reason=None):
        self.recorder.record(kind, frame, accepted, reason)

    def _open_sensor_socket(self):
        port = int(self.config.get('sensor_port', 9996))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port)); sock.setblocking(False)
        self._sensor_sock = sock

    def _drain_sensor_socket(self):
        if self._sensor_sock is None:
            return
        while True:
            try:
                raw, _sender = self._sensor_sock.recvfrom(4096)
            except BlockingIOError:
                return
            try:
                state = parse_flight_state(raw)
            except ValueError as exc:
                self.stats['state_parse_errors'] += 1
                self._record('invalid_model_state', {'error': str(exc)}, accepted=False, reason=str(exc))
                continue
            self._latest_state = state; self.stats['state_frames'] += 1

    def _sensor_timestamp(self, state):
        return int(state['sim_time_s'] * 1000000)

    def _sensor_base(self, frame_type, state):
        return {'frame_type': frame_type, 'hardware_id': self.hardware_id,
                'sequence': int(state['sequence']), 'timestamp_us': self._sensor_timestamp(state),
                'valid': True}

    def _imu_from_state(self, state):
        frame = self._sensor_base('imu', state)
        frame.update({'accel_mps2': [state['ax_mps2'], state['ay_mps2'], state['az_mps2']],
                      'gyro_radps': [state['p_radps'], state['q_radps'], state['r_radps']]})
        return frame

    def _barometer_from_state(self, state):
        frame = self._sensor_base('barometer', state)
        altitude = self.origin_alt_m - state['down_m']
        frame.update({'abs_pressure_hpa': 1013.25 * math.exp(-altitude / 8434.5),
                      'altitude_m': altitude, 'temperature_c': 15.0})
        return frame

    def _gps_from_state(self, state):
        frame = self._sensor_base('gps', state)
        latitude = self.origin_lat_deg + state['north_m'] / 111111.0
        longitude = self.origin_lon_deg + state['east_m'] / (111111.0 * max(
            math.cos(math.radians(self.origin_lat_deg)), 1.0e-6))
        heading = math.degrees(math.atan2(state['ve_mps'], state['vn_mps'])) % 360.0
        frame.update({'latitude_deg': latitude, 'longitude_deg': longitude,
                      'altitude_m': self.origin_alt_m - state['down_m'],
                      'velocity_ned_mps': [state['vn_mps'], state['ve_mps'], state['vd_mps']],
                      'heading_deg': heading, 'fix_type': 3})
        return frame

    def _truth_from_state(self, state):
        frame = self._sensor_base('model_truth', state)
        frame.update({'position_ned_m': [state['north_m'], state['east_m'], state['down_m']],
                      'velocity_ned_mps': [state['vn_mps'], state['ve_mps'], state['vd_mps']],
                      'quaternion_wxyz': [state['q_w'], state['q_x'], state['q_y'], state['q_z']]})
        return frame

    def _publish(self, frame):
        if self._faults.get('sensor_invalid'):
            frame = dict(frame); frame['valid'] = False
        # This is the only path from model data to the virtual controller.
        # ``model_truth`` is deliberately recorded but never ingested.
        self.controller.ingest(frame, self.clock())
        self.adapter.publish_sensor(frame)

    def _publish_fresh_sensors(self, now):
        state = self._latest_state
        if state is None or state['sequence'] == self._last_sensor_sequence:
            return
        self._last_sensor_sequence = state['sequence']
        if self._faults.get('model_invalid'):
            self.stats['invalid_sensor_suppressed'] += 1
            return
        self._publish(self._truth_from_state(state))
        if now >= self._next_imu:
            self._publish(self._imu_from_state(state)); self.stats['imu_frames'] += 1
            self._next_imu = now + 1.0 / self.imu_rate_hz
        if now >= self._next_baro:
            self._publish(self._barometer_from_state(state)); self.stats['barometer_frames'] += 1
            self._next_baro = now + 1.0 / self.barometer_rate_hz
        if now >= self._next_gps:
            self._publish(self._gps_from_state(state)); self.stats['gps_frames'] += 1
            self._next_gps = now + 1.0 / self.gps_rate_hz

    def _health_frame(self, now):
        valid = not (self._faults.get('model_invalid') or self._faults.get('sensor_invalid')) and \
                self.controller.ready(now)
        return {'frame_type': 'health', 'hardware_id': self.hardware_id,
                'timestamp_us': int(now * 1000000), 'valid': valid,
                'faults': sorted(self._faults), 'state_available': self._latest_state is not None,
                'counters': dict(self.adapter.stats),
                'controller': self.controller.status(now)}

    def _command_frame(self, now):
        values, armed, mode = self.controller.command(now)
        self._actuator_sequence += 1
        frame = {'frame_type': 'actuator_command', 'hardware_id': self.hardware_id,
                'sequence': self._actuator_sequence, 'timestamp_us': int(now * 1000000),
                'armed': armed, 'flight_mode': mode, 'valid': True,
                'actuator_channels': [channel['name'] for channel in self.adapter.actuators],
                'actuator_values': values}
        if self.vehicle_profile is None:
            frame['motor_command'] = list(values)  # V2 virtual-quad compatibility only.
        return frame

    def _dispatch(self, frame, now):
        # One-shot malformed/order faults exercise the adapter's validation
        # path without ever delivering malformed values to the C core.
        if self._faults.pop('duplicate_next', False) and self._last_dispatched_frame is not None:
            self._send_frame(dict(self._last_dispatched_frame))
        if self._faults.pop('out_of_order_next', False) and self._last_dispatched_frame is not None:
            stale = dict(self._last_dispatched_frame)
            stale['sequence'] = max(0, frame['sequence'] - 2)
            self._send_frame(stale)
        if self._faults.pop('timestamp_rollback_next', False):
            frame = dict(frame); frame['timestamp_us'] = max(0, frame['timestamp_us'] - 1000000)
        if self._faults.pop('invalid_frame_next', False):
            frame = dict(frame); frame['actuator_values'] = list(frame['actuator_values'])
            frame['actuator_values'][0] = self.adapter.actuators[0]['max'] + 0.1
        self._last_dispatched_frame = dict(frame)
        delay_ms = float(self._faults.get('fixed_delay_ms', 0.0))
        if delay_ms > 0.0:
            self._delayed.append((now + delay_ms / 1000.0, frame)); return
        self._send_frame(frame)

    def _flush_delayed(self, now):
        ready = [item for item in self._delayed if item[0] <= now]
        self._delayed = [item for item in self._delayed if item[0] > now]
        for _deadline, frame in ready:
            self._send_frame(frame)

    def _send_frame(self, frame):
        loss_ratio = float(self._faults.get('packet_loss_ratio', 0.0))
        if loss_ratio > 0.0 and random.random() < loss_ratio:
            self._record('actuator_transport_drop', frame, accepted=False, reason='injected packet loss')
            return
        accepted, reason = self.adapter.submit_actuator_frame(frame)
        if not accepted:
            return
        command = {'cmd': 'actuator_command', 'params': {
            'source': 'physical_uut', 'values': frame['actuator_values']}}
        if self.command_send(command):
            self.stats['commands_sent'] += 1
        else:
            self.stats['command_send_failures'] += 1

    def step(self, now=None):
        now = self.clock() if now is None else now
        self._drain_sensor_socket(); self._publish_fresh_sensors(now); self._flush_delayed(now)
        frame = self._command_frame(now)
        self._dispatch(frame, now)
        if now >= self._next_health:
            self._publish(self._health_frame(now)); self.stats['health_frames'] += 1
            self._next_health = now + 1.0 / self.health_rate_hz

    def _run(self):
        try:
            self._open_sensor_socket()
            deadline = self.clock()
            while self._running.is_set():
                self.step(deadline); deadline += self._period_s
                self.sleep(max(0.0, deadline - self.clock()))
        finally:
            if self._sensor_sock is not None:
                self._sensor_sock.close(); self._sensor_sock = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._running.set()
        self._thread = threading.Thread(target=self._run, name='virtual_quad_fc', daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(2.0)
        self.adapter.close(); self.recorder.close(); unregister_service(self)

    def start_scenario(self, scenario):
        if scenario not in ('idle', 'takeoff', 'hover', 'forward', 'turn', 'land'):
            return {'accepted': False, 'reason': 'scenario must be idle/takeoff/hover/forward/turn/land'}
        with self._lock:
            self._scenario = scenario; self._scenario_started = self.clock()
            try:
                initialized = self.controller.start_scenario(scenario)
            except ValueError as exc:
                self._scenario = 'stopped'
                return {'accepted': False, 'reason': str(exc)}
        self._record('scenario', {'scenario': scenario, 'initialized_from_sensor_estimate': initialized}, accepted=True)
        return {'accepted': True, 'scenario': scenario,
                'initialized': initialized,
                'note': 'closed loop waits for valid IMU/GPS before arming; select_control_source physical_uut separately'}

    def stop_scenario(self):
        with self._lock:
            self._scenario = 'stopped'; self._scenario_started = self.clock()
            self.controller.start_scenario('stopped')
        self._record('scenario', {'scenario': 'stopped'}, accepted=True)
        return {'accepted': True, 'scenario': 'stopped'}

    def set_target(self, params):
        try:
            self.controller.set_target(params['north_m'], params['east_m'], params['down_m'],
                                       params.get('yaw_deg'))
        except (KeyError, TypeError, ValueError) as exc:
            return {'accepted': False, 'reason': str(exc)}
        self._scenario = 'target'
        self._record('target', dict(self.controller.target), accepted=True)
        return {'accepted': True, 'target': dict(self.controller.target)}

    def load_route(self, params):
        try:
            self.controller.load_route(params.get('waypoints'))
        except (TypeError, ValueError) as exc:
            return {'accepted': False, 'reason': str(exc)}
        self._scenario = 'route'
        self._record('route', {'waypoints': list(self.controller.route)}, accepted=True)
        return {'accepted': True, 'waypoint_count': len(self.controller.route),
                'target': dict(self.controller.target)}

    def reload_contract(self, contract_path=None, initial=False):
        path = contract_path or self.contract_path
        if not path:
            return {'accepted': False, 'reason': 'contract_path is required'}
        if not initial and self._scenario != 'stopped':
            return {'accepted': False, 'reason': 'stop the virtual FC before changing vehicle contract'}
        try:
            profile = load_profile(path)
            controller = controller_from_profile(self.config, profile)
            if not hasattr(self.adapter, 'configure_actuators'):
                raise VehicleProfileError('adapter does not support contract actuator configuration')
            self.adapter.configure_actuators(profile['actuators'])
        except (VehicleProfileError, ValueError) as exc:
            return {'accepted': False, 'reason': str(exc)}
        self.controller = controller; self.vehicle_profile = profile; self.contract_path = path
        self._actuator_sequence = 0; self._last_dispatched_frame = None; self._delayed = []
        self._record('vehicle_contract', {'path': path, 'model_name': profile['model_name'],
                                          'vehicle_kind': profile['vehicle_kind'],
                                          'actuator_count': len(profile['actuators'])}, accepted=True)
        return {'accepted': True, 'model_name': profile['model_name'],
                'vehicle_kind': profile['vehicle_kind'], 'actuator_count': len(profile['actuators'])}

    def inject_fault(self, params):
        name = params.get('name')
        if name not in ('sensor_invalid', 'model_invalid', 'fixed_delay_ms', 'packet_loss_ratio',
                        'duplicate_next', 'out_of_order_next', 'timestamp_rollback_next',
                        'invalid_frame_next', 'clear'):
            return {'accepted': False, 'reason': 'unsupported fault'}
        with self._lock:
            if name == 'clear': self._faults.clear()
            elif name == 'fixed_delay_ms':
                value = float(params.get('value', 0.0))
                if value < 0.0 or value > 10000.0: return {'accepted': False, 'reason': 'delay must be 0..10000 ms'}
                self._faults[name] = value
            elif name == 'packet_loss_ratio':
                value = float(params.get('value', 0.0))
                if value < 0.0 or value > 1.0: return {'accepted': False, 'reason': 'loss ratio must be 0..1'}
                self._faults[name] = value
            elif name.endswith('_next'):
                self._faults[name] = True
            else:
                self._faults[name] = bool(params.get('enabled', True))
        event = {'name': name, 'params': dict(params), 'active_faults': sorted(self._faults)}
        self._record('fault_injection', event, accepted=True)
        return {'accepted': True, 'faults': sorted(self._faults)}

    def status(self):
        now = self.clock()
        return {'hardware_id': self.hardware_id, 'running': self._running.is_set(),
                'scenario': self._scenario, 'faults': dict(self._faults),
                'record_path': self.recorder.path,
                'recording': {'bytes_recorded': self.recorder._run_bytes,
                              'max_run_bytes': self.recorder.max_run_bytes,
                              'max_file_bytes': self.recorder.max_file_bytes,
                              'retention_days': self.recorder.retention_days,
                              'limited': self.recorder.limited},
                'stats': dict(self.stats),
                'adapter': dict(self.adapter.stats), 'closed_loop': self.controller.status(now),
                'vehicle': {'contract_path': self.contract_path,
                            'model_name': self.vehicle_profile['model_name'] if self.vehicle_profile else 'legacy_quadrotor',
                            'vehicle_kind': self.vehicle_profile['vehicle_kind'] if self.vehicle_profile else 'multirotor',
                            'actuator_count': len(self.adapter.actuators)}}
