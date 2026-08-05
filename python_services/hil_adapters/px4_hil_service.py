"""PX4 MAVLink-HIL loop built on the normalized C-core flight state.

The service is deliberately transport-only: it never selects ``px4_sitl`` as
the active control source.  An operator must perform that explicit, mutually
exclusive switch through ``select_control_source`` before PX4 controls can
affect the generated plant.
"""
from __future__ import print_function

import math
import threading
import time

from core_client import core_send
from shared import state_cache
from .mavlink_hil import MavlinkHilAdapter


class Px4HilService(object):
    def __init__(self, config, adapter=None, state_provider=None, command_send=None,
                 clock=None, sleep=None):
        self.config = config
        self.adapter = adapter or MavlinkHilAdapter(
            peer_host=config.get('peer_host', '127.0.0.1'),
            peer_port=int(config.get('peer_port', 14560)),
            bind_host=config.get('bind_host', '127.0.0.1'),
            bind_port=int(config.get('bind_port', 14580)),
            system_id=int(config.get('system_id', 1)),
            component_id=int(config.get('component_id', 1)))
        self.state_provider = state_provider or self._cached_state
        self.command_send = command_send or core_send
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.actuator_count = int(config.get('actuator_count', 4))
        if not 1 <= self.actuator_count <= 16:
            raise ValueError('px4_hil.actuator_count must be 1..16')
        self.imu_rate_hz = int(config.get('imu_rate_hz', 250))
        self.gps_rate_hz = int(config.get('gps_rate_hz', 20))
        if not 1 <= self.gps_rate_hz <= self.imu_rate_hz <= 1000:
            raise ValueError('PX4 HIL rates must satisfy 1 <= gps <= imu <= 1000')
        self.origin_lat_deg = float(config.get('origin_lat_deg', 31.2304))
        self.origin_lon_deg = float(config.get('origin_lon_deg', 121.4737))
        self.origin_alt_m = float(config.get('origin_alt_m', 10.0))
        self._period_s = 1.0 / self.imu_rate_hz
        self._next_gps = 0.0
        self._running = threading.Event()
        self._thread = None
        self.stats = {'sensor_frames': 0, 'gps_frames': 0, 'actuator_frames': 0,
                      'command_send_failures': 0, 'state_misses': 0}

    @staticmethod
    def _cached_state():
        # State cache has already checked version, finiteness and quaternion.
        return state_cache.get_normalized_state()

    def _time_usec(self):
        return int(self.clock() * 1000000)

    def _sensor_from_state(self, state):
        # C state uses NED.  MAVLink HIL_SENSOR axes are body FRD; using the
        # current normalized acceleration/rates is the conservative fallback
        # until a contract exposes an explicit body-frame IMU output.
        return {'time_usec': self._time_usec(),
                'accel_mps2': [state['ax_mps2'], state['ay_mps2'], state['az_mps2']],
                'gyro_radps': [state['p_radps'], state['q_radps'], state['r_radps']],
                'mag_gauss': [0.215, 0.002, 0.427],
                'abs_pressure_hpa': 1013.25 * math.exp(state['down_m'] / 8434.5),
                'diff_pressure_hpa': 0.0,
                'pressure_alt_m': -state['down_m'],
                'temperature_c': 15.0,
                'fields_updated': 0x1FFF}

    def _gps_from_state(self, state):
        latitude = self.origin_lat_deg + state['north_m'] / 111111.0
        longitude = self.origin_lon_deg + state['east_m'] / (
            111111.0 * max(math.cos(math.radians(self.origin_lat_deg)), 1.0e-6))
        velocity = math.sqrt(state['vn_mps'] ** 2 + state['ve_mps'] ** 2 + state['vd_mps'] ** 2)
        cog = math.degrees(math.atan2(state['ve_mps'], state['vn_mps'])) % 360.0
        return {'time_usec': self._time_usec(), 'lat_e7': round(latitude * 1.0e7),
                'lon_e7': round(longitude * 1.0e7),
                'alt_mm': round((self.origin_alt_m - state['down_m']) * 1000.0),
                'eph_cm': 100, 'epv_cm': 150, 'velocity_cmps': round(velocity * 100.0),
                'vn_cmps': round(state['vn_mps'] * 100.0),
                've_cmps': round(state['ve_mps'] * 100.0),
                'vd_cmps': round(state['vd_mps'] * 100.0),
                'cog_cdeg': round(cog * 100.0), 'fix_type': 3,
                'satellites_visible': 12}

    def step(self, now=None):
        now = self.clock() if now is None else now
        state = self.state_provider()
        if state is None:
            self.stats['state_misses'] += 1
        else:
            self.adapter.send_sensor(self._sensor_from_state(state))
            self.stats['sensor_frames'] += 1
            if now >= self._next_gps:
                self.adapter.send_gps(self._gps_from_state(state))
                self.stats['gps_frames'] += 1
                self._next_gps = now + 1.0 / self.gps_rate_hz
        controls = self.adapter.poll_actuators()
        if controls is not None:
            command = {'cmd': 'actuator_command', 'params': {
                'source': 'px4_sitl', 'values': controls['controls'][:self.actuator_count]}}
            if self.command_send(command):
                self.stats['actuator_frames'] += 1
            else:
                self.stats['command_send_failures'] += 1

    def _run(self):
        deadline = self.clock()
        while self._running.is_set():
            self.step(deadline)
            deadline += self._period_s
            self.sleep(max(0.0, deadline - self.clock()))

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._running.set()
        self._thread = threading.Thread(target=self._run, name='px4_hil', daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(2.0)
        self.adapter.close()
