#!/usr/bin/env python3
"""Strict, deterministic validator for the local Mini-UE4 V2 session."""
from __future__ import print_function

import copy
import json
import math


OUTER_FIELDS = {'protocol_version', 'type', 'seq', 'vehicle_id', 'data'}
STATE_REQUIRED_FIELDS = {'mission_id', 'sim_time', 'position', 'attitude'}
STATE_OPTIONAL_FIELDS = {'velocity', 'angular_velocity', 'flight_state'}
STATE_PERIOD_S = 0.02
STATE_INTERVAL_TOLERANCE_S = 0.002


class ProtocolViolation(ValueError):
    pass


def _exact_fields(value, expected, label):
    if not isinstance(value, dict):
        raise ProtocolViolation('{} must be an object'.format(label))
    actual = set(value)
    if actual != set(expected):
        raise ProtocolViolation(
            '{} fields must be exactly {}; got {}'.format(
                label, sorted(expected), sorted(actual)))


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolViolation('{} must be a finite number'.format(label))
    if not math.isfinite(float(value)):
        raise ProtocolViolation('{} must be a finite number'.format(label))


def _validate_vector(value, fields, label):
    _exact_fields(value, fields, label)
    for field in fields:
        _finite_number(value[field], '{}.{}'.format(label, field))


class ProtocolSequenceValidator(object):
    """Validate one client session and generate only matching accepted ACKs."""

    def __init__(self):
        self.phase = 'hello'
        self.last_seq = None
        self.mission_id = None
        self.last_sim_time = None
        self.state_times = []
        self.transcript = []
        self._ack_seq = 0
        self._mission_end_acknowledged = False

    def _record(self, direction, message, timestamp_s):
        self.transcript.append({
            'direction': direction,
            'timestamp_s': timestamp_s,
            'message': copy.deepcopy(message),
        })

    def _ack(self, message, timestamp_s):
        self._ack_seq += 1
        ack = {
            'protocol_version': '2.0',
            'type': 'ack',
            'seq': self._ack_seq,
            'vehicle_id': 'Drone1',
            'data': {
                'ref_type': message['type'],
                'ref_seq': message['seq'],
                'accepted': True,
            },
        }
        self._record('sent', ack, timestamp_s)
        return ack

    def _validate_envelope(self, message):
        _exact_fields(message, OUTER_FIELDS, 'message')
        if message['protocol_version'] != '2.0':
            raise ProtocolViolation('protocol_version must be 2.0')
        if message['vehicle_id'] != 'Drone1':
            raise ProtocolViolation('vehicle_id must be Drone1')
        seq = message['seq']
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise ProtocolViolation('seq must be a positive integer')
        if self.last_seq is not None and seq <= self.last_seq:
            raise ProtocolViolation('seq must be strictly increasing')

    def _validate_hello(self, data):
        expected = {
            'role': 'simulink_state_source',
            'state_rate_hz': 50,
            'coordinate_convention': 'x_forward_y_right_height_up',
            'angle_unit': 'rad',
        }
        _exact_fields(data, expected, 'hello.data')
        for field, value in expected.items():
            if data[field] != value:
                raise ProtocolViolation(
                    'hello.data.{} must be {!r}'.format(field, value))

    def _validate_mission(self, data):
        _exact_fields(
            data, {'mission_id', 'replace_previous', 'waypoints'},
            'mission_plan.data')
        mission_id = data['mission_id']
        if not isinstance(mission_id, str) or not mission_id:
            raise ProtocolViolation('mission_plan.data.mission_id is required')
        if data['replace_previous'] is not True:
            raise ProtocolViolation('mission_plan.data.replace_previous must be true')
        waypoints = data['waypoints']
        if not isinstance(waypoints, list) or len(waypoints) < 2:
            raise ProtocolViolation('mission_plan requires at least two waypoints')
        for index, waypoint in enumerate(waypoints):
            label = 'mission_plan.data.waypoints[{}]'.format(index)
            _exact_fields(
                waypoint, {'id', 'x', 'y', 'height', 'target_speed'}, label)
            if not isinstance(waypoint['id'], str) or not waypoint['id']:
                raise ProtocolViolation('{}.id is required'.format(label))
            for field in ('x', 'y', 'height', 'target_speed'):
                _finite_number(waypoint[field], '{}.{}'.format(label, field))
        self.mission_id = mission_id

    def _validate_state(self, data, timestamp_s):
        if not isinstance(data, dict):
            raise ProtocolViolation('vehicle_state.data must be an object')
        fields = set(data)
        if not STATE_REQUIRED_FIELDS.issubset(fields) or not fields.issubset(
                STATE_REQUIRED_FIELDS | STATE_OPTIONAL_FIELDS):
            raise ProtocolViolation(
                'vehicle_state.data fields must be required V2 fields plus only '
                'velocity, angular_velocity, or flight_state; got {}'.format(
                    sorted(fields)))
        if data['mission_id'] != self.mission_id:
            raise ProtocolViolation('vehicle_state mission_id does not match mission_plan')
        _finite_number(data['sim_time'], 'vehicle_state.data.sim_time')
        if (self.last_sim_time is not None and
                data['sim_time'] <= self.last_sim_time):
            raise ProtocolViolation('vehicle_state sim_time must strictly increase')
        _validate_vector(
            data['position'], {'x', 'y', 'height'},
            'vehicle_state.data.position')
        _validate_vector(
            data['attitude'], {'roll', 'pitch', 'yaw'},
            'vehicle_state.data.attitude')
        if 'velocity' in data:
            _validate_vector(
                data['velocity'], {'vx', 'vy', 'vz'},
                'vehicle_state.data.velocity')
        if 'angular_velocity' in data:
            _validate_vector(
                data['angular_velocity'], {'p', 'q', 'r'},
                'vehicle_state.data.angular_velocity')
        if 'flight_state' in data and not isinstance(data['flight_state'], str):
            raise ProtocolViolation('vehicle_state.data.flight_state must be a string')
        _finite_number(timestamp_s, 'received timestamp')
        if self.state_times and timestamp_s <= self.state_times[-1]:
            raise ProtocolViolation('received timestamps must strictly increase')
        self.last_sim_time = data['sim_time']
        self.state_times.append(float(timestamp_s))

    def _validate_mission_end(self, data):
        _exact_fields(data, {'event', 'mission_id'}, 'simulation_event.data')
        if data['event'] != 'mission_end':
            raise ProtocolViolation('only optional mission_end is valid here')
        if data['mission_id'] != self.mission_id:
            raise ProtocolViolation('mission_end mission_id does not match mission_plan')

    def observe(self, message, timestamp_s):
        self._validate_envelope(message)
        message_type = message['type']
        ack = None
        if self.phase == 'hello':
            if message_type != 'hello':
                raise ProtocolViolation('expected hello before {}'.format(message_type))
            self._validate_hello(message['data'])
            self.phase = 'mission_plan'
            ack = True
        elif self.phase == 'mission_plan':
            if message_type != 'mission_plan':
                raise ProtocolViolation(
                    'expected mission_plan before {}'.format(message_type))
            self._validate_mission(message['data'])
            self.phase = 'vehicle_state'
            ack = True
        elif self.phase == 'vehicle_state':
            if message_type == 'vehicle_state':
                self._validate_state(message['data'], timestamp_s)
            elif message_type == 'simulation_event':
                if not self.state_times:
                    raise ProtocolViolation('mission_end requires prior vehicle_state')
                self._validate_mission_end(message['data'])
                self.phase = 'complete'
                self._mission_end_acknowledged = True
                ack = True
            else:
                raise ProtocolViolation(
                    'expected vehicle_state or optional mission_end; got {}'.format(
                        message_type))
        else:
            raise ProtocolViolation('no messages are allowed after mission_end')
        self.last_seq = message['seq']
        self._record('received', message, timestamp_s)
        return self._ack(message, timestamp_s) if ack else None

    def finish(self):
        if self.phase in ('hello', 'mission_plan'):
            raise ProtocolViolation('session ended before handshake completed')
        if len(self.state_times) < 2:
            raise ProtocolViolation(
                'at least two vehicle_state frames are required to verify 50 Hz')
        elapsed = self.state_times[-1] - self.state_times[0]
        rate_hz = (len(self.state_times) - 1) / elapsed
        intervals = [
            current - previous
            for previous, current in zip(
                self.state_times[:-1], self.state_times[1:])]
        interval_errors = [
            abs(interval - STATE_PERIOD_S) for interval in intervals]
        if any(error > STATE_INTERVAL_TOLERANCE_S
               for error in interval_errors):
            raise ProtocolViolation(
                'individual vehicle_state intervals must match 50 Hz within '
                '+/-{:.3f} s; observed {}'.format(
                    STATE_INTERVAL_TOLERANCE_S,
                    [round(interval, 6) for interval in intervals]))
        if not 49.0 <= rate_hz <= 51.0:
            raise ProtocolViolation(
                'vehicle_state stream must average 50 Hz; observed {:.3f} Hz'.format(
                    rate_hz))
        return {
            'local_simulator_only': True,
            'vehicle_state_count': len(self.state_times),
            'average_state_rate_hz': round(rate_hz, 6),
            'state_interval_tolerance_s': STATE_INTERVAL_TOLERANCE_S,
            'mission_end_acknowledged': self._mission_end_acknowledged,
        }

    def write_transcript(self, path, summary):
        with open(path, 'w') as output:
            json.dump(
                {'summary': summary, 'frames': self.transcript}, output,
                indent=2, sort_keys=True)
            output.write('\n')


def build_self_test_session():
    validator = ProtocolSequenceValidator()
    messages = [
        ({'protocol_version': '2.0', 'type': 'hello', 'seq': 1,
          'vehicle_id': 'Drone1', 'data': {
              'role': 'simulink_state_source', 'state_rate_hz': 50,
              'coordinate_convention': 'x_forward_y_right_height_up',
              'angle_unit': 'rad'}}, 1.000),
        ({'protocol_version': '2.0', 'type': 'mission_plan', 'seq': 2,
          'vehicle_id': 'Drone1', 'data': {
              'mission_id': 'z_mission_001', 'replace_previous': True,
              'waypoints': [
                  {'id': 'P1', 'x': 0.0, 'y': 0.0, 'height': 20.0,
                   'target_speed': 2.0},
                  {'id': 'P2', 'x': 40.0, 'y': 0.0, 'height': 20.0,
                   'target_speed': 5.0}]}}, 1.010),
    ]
    for index in range(3):
        messages.append((
            {'protocol_version': '2.0', 'type': 'vehicle_state',
             'seq': index + 3, 'vehicle_id': 'Drone1', 'data': {
                 'mission_id': 'z_mission_001', 'sim_time': index * 0.02,
                 'position': {'x': 0.0, 'y': 0.0, 'height': 20.0},
                 'attitude': {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0},
                 'velocity': {'vx': 0.0, 'vy': 0.0, 'vz': 0.0},
                 'angular_velocity': {'p': 0.0, 'q': 0.0, 'r': 0.0}}},
            1.020 + index * 0.02))
    messages.append((
        {'protocol_version': '2.0', 'type': 'simulation_event', 'seq': 6,
         'vehicle_id': 'Drone1', 'data': {
             'event': 'mission_end', 'mission_id': 'z_mission_001'}},
        1.070))
    for session_message, timestamp_s in messages:
        validator.observe(session_message, timestamp_s)
    return validator, validator.finish()
