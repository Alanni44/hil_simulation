#!/usr/bin/env python3
"""
V2.0 TCP Bridge Client — 严格按 Simulink-三维视景通信协议 V2.0
连接 UE4 侧的 Python Bridge（TCP Server :5000）
帧格式: [4字节大端无符号长度][UTF-8 JSON]
消息类型:
  hello           → 握手
  mission_plan    → 发送航点规划
  vehicle_state   → 50Hz 实时状态
  simulation_event → 仿真生命周期
  ack / error     → 接收响应

正确时序:
  TCP连接 → hello → ACK → mission_plan → ACK → vehicle_state @50Hz
"""
import json
import os
import socket
import struct
import threading
import time
import weakref
from collections import OrderedDict
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG

logger = get_logger('bridge_v2')

UE4_HOST = CONFIG['ue4_tcp']['host']
UE4_PORT = CONFIG['ue4_tcp']['port']

_sock = None
_sock_lock = threading.Lock()
_send_lock = threading.Lock()
_connected = threading.Event()
_running = True
_stop_event = threading.Event()
_seq = 0
_seq_lock = threading.Lock()

_status_lock = threading.Lock()
_session_phase = 'connecting'
_last_error = None
_STATUS_UNCHANGED = object()

_current_mission_id = None
_pending_waypoints = None
_mission_queue = []
_event_queue = []
_event_reservations = {}
_queue_lock = threading.Lock()
_recv_buffer_lock = threading.Lock()
_recv_buffers = weakref.WeakKeyDictionary()

MAX_FRAME_BYTES = 1048576
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_OUTER_FIELDS = ('protocol_version', 'type', 'seq', 'vehicle_id', 'data')
V2_ACK_DATA_FIELDS = ('ref_type', 'ref_seq', 'accepted')
V2_STATE_REQUIRED_FIELDS = ('mission_id', 'sim_time', 'position', 'attitude')
V2_STATE_OPTIONAL_FIELDS = ('velocity', 'angular_velocity', 'flight_state')
_wire_log_lock = threading.Lock()
_wire_log_failure_reported = False


class ProtocolFrameError(ValueError):
    pass


def _ordered_fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ProtocolFrameError('{} fields must be exactly {}'.format(
            label, ', '.join(fields)))
    return OrderedDict((field, value[field]) for field in fields)


def _ordered_v2_message(message):
    """Return a V2 message whose serialized key order is protocol-defined."""
    ordered = _ordered_fields(message, V2_OUTER_FIELDS, 'V2 envelope')
    message_type = ordered['type']
    data = ordered['data']
    if message_type == 'hello':
        ordered['data'] = _ordered_fields(
            data, ('role', 'state_rate_hz', 'coordinate_convention',
                   'angle_unit'), 'hello.data')
    elif message_type == 'mission_plan':
        mission = _ordered_fields(
            data, ('mission_id', 'replace_previous', 'waypoints'),
            'mission_plan.data')
        if not isinstance(mission['waypoints'], list):
            raise ProtocolFrameError('mission_plan.data.waypoints must be a list')
        mission['waypoints'] = [
            _ordered_fields(waypoint,
                            ('id', 'x', 'y', 'height', 'target_speed'),
                            'mission_plan waypoint')
            for waypoint in mission['waypoints']]
        ordered['data'] = mission
    elif message_type == 'vehicle_state':
        if not isinstance(data, dict):
            raise ProtocolFrameError('vehicle_state.data must be an object')
        optional = tuple(field for field in V2_STATE_OPTIONAL_FIELDS
                         if field in data)
        expected = V2_STATE_REQUIRED_FIELDS + optional
        if set(data) != set(expected):
            raise ProtocolFrameError(
                'vehicle_state.data fields must be {}'.format(
                    ', '.join(expected)))
        state = OrderedDict((field, data[field]) for field in expected)
        state['position'] = _ordered_fields(
            state['position'], ('x', 'y', 'height'), 'vehicle_state.position')
        state['attitude'] = _ordered_fields(
            state['attitude'], ('roll', 'pitch', 'yaw'), 'vehicle_state.attitude')
        if 'velocity' in state:
            state['velocity'] = _ordered_fields(
                state['velocity'], ('vx', 'vy', 'vz'), 'vehicle_state.velocity')
        if 'angular_velocity' in state:
            state['angular_velocity'] = _ordered_fields(
                state['angular_velocity'], ('p', 'q', 'r'),
                'vehicle_state.angular_velocity')
        ordered['data'] = state
    elif message_type == 'simulation_event':
        fields = ('event', 'mission_id') if 'mission_id' in data else ('event',)
        ordered['data'] = _ordered_fields(data, fields, 'simulation_event.data')
    else:
        raise ProtocolFrameError('unsupported outbound V2 message {}'.format(
            message_type))
    return ordered


def _wire_log_settings():
    settings = CONFIG.get('wire_log', {})
    path = settings.get('path', 'runtime/z_debug/ue4_tcp_wire.jsonl')
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    max_bytes = int(settings.get('max_bytes', 16777216))
    backup_count = int(settings.get('backup_count', 5))
    if max_bytes < 1024 or backup_count < 0:
        raise ValueError('invalid wire_log rotation settings')
    return path, max_bytes, backup_count


def _rotate_wire_log(path, backup_count):
    if backup_count == 0:
        os.remove(path)
        return
    oldest = '{}.{}'.format(path, backup_count)
    if os.path.exists(oldest):
        os.remove(oldest)
    for index in range(backup_count - 1, 0, -1):
        source = '{}.{}'.format(path, index)
        if os.path.exists(source):
            os.rename(source, '{}.{}'.format(path, index + 1))
    os.rename(path, '{}.1'.format(path))


def _record_wire_frame(direction, sock, header, body, message):
    """Persist bounded raw-frame evidence without affecting the session."""
    global _wire_log_failure_reported
    try:
        path, max_bytes, backup_count = _wire_log_settings()
        try:
            peer_address = sock.getpeername()
            if isinstance(peer_address, tuple) and len(peer_address) >= 2:
                peer = '{}:{}'.format(peer_address[0], peer_address[1])
            else:
                peer = str(peer_address) or 'local'
        except (AttributeError, OSError, TypeError):
            peer = 'unavailable'
        record = OrderedDict((
            ('utc', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())),
            ('direction', direction), ('peer', peer),
            ('length_bytes', len(body)), ('length_header_hex', header.hex()),
            ('json_utf8', body.decode('utf-8')), ('json_utf8_hex', body.hex()),
            ('message_type', message.get('type') if isinstance(message, dict) else None),
            ('seq', message.get('seq') if isinstance(message, dict) else None),
        ))
        encoded = (json.dumps(record, ensure_ascii=False,
                              separators=(',', ':')) + '\n').encode('utf-8')
        with _wire_log_lock:
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            if os.path.exists(path) and os.path.getsize(path) + len(encoded) > max_bytes:
                _rotate_wire_log(path, backup_count)
            with open(path, 'ab') as output:
                output.write(encoded)
        _wire_log_failure_reported = False
    except Exception as exc:
        if not _wire_log_failure_reported:
            logger.warning('wire-frame logging disabled after error: %s', exc)
            _wire_log_failure_reported = True


def _set_session_status(phase=None, last_error=_STATUS_UNCHANGED):
    global _session_phase, _last_error
    with _status_lock:
        if phase is not None:
            _session_phase = phase
        if last_error is not _STATUS_UNCHANGED:
            _last_error = last_error


def get_status():
    with _status_lock:
        phase = _session_phase
        last_error = _last_error
    with _queue_lock:
        mission_id = _current_mission_id
    return {
        'phase': phase,
        'connected': _connected.is_set(),
        'mission_id': mission_id,
        'last_error': last_error,
    }


def _next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def _reset_session_sequence():
    global _seq
    with _seq_lock:
        _seq = 0


def _protocol_settings():
    bridge = CONFIG.get('bridge', {})
    version = bridge.get('protocol_version', '2.0')
    if version == '3.0':
        return {'version': '3.0', 'vehicle_id': 'FixedWing01',
                'role': 'simulink_fixedwing_state_source', 'body_frame': 'FRD'}
    return {'version': '2.0', 'vehicle_id': 'Drone1',
            'role': 'simulink_state_source', 'body_frame': None}


def _sanitize(obj):
    if isinstance(obj, float):
        import math
        if not math.isfinite(obj):
            raise ValueError('refusing non-finite value for UE4 protocol')
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def validate_mission_plan(mission_id, waypoints):
    import math
    if not isinstance(mission_id, str) or not mission_id:
        raise ValueError('mission_id must be a non-empty string')
    if not isinstance(waypoints, list) or len(waypoints) < 2:
        raise ValueError('mission_plan requires at least two waypoints')
    validated = []
    for index, waypoint in enumerate(waypoints):
        if not isinstance(waypoint, dict):
            raise ValueError('waypoint {} must be an object'.format(index))
        required = ('x', 'y', 'height')
        if any(key not in waypoint for key in required):
            raise ValueError('waypoint {} lacks x/y/height'.format(index))
        value = {'x': waypoint['x'], 'y': waypoint['y'], 'height': waypoint['height'],
                 'speed': waypoint.get('speed', 5.0)}
        for key, number in value.items():
            if (not isinstance(number, (int, float)) or isinstance(number, bool) or
                    not math.isfinite(number)):
                raise ValueError('waypoint {} has invalid {}'.format(index, key))
        _sanitize(value)
        validated.append(value)
    return validated


def _frame_send(sock, data):
    if data.get('protocol_version') == '2.0':
        data = _ordered_v2_message(data)
    clean = _sanitize(data)
    body = json.dumps(clean, separators=(',', ':')).encode('utf-8')
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolFrameError('JSON frame exceeds frame limit')
    header = struct.pack('>I', len(body))
    with _send_lock:
        sock.sendall(header + body)
    _record_wire_frame('outbound', sock, header, body, clean)


def _frame_recv(sock, timeout=0.5):
    sock.settimeout(timeout)
    with _recv_buffer_lock:
        body = _recv_buffers.setdefault(sock, bytearray())
    try:
        while True:
            if len(body) >= 4:
                frame_length = struct.unpack('>I', bytes(body[:4]))[0]
                if frame_length > MAX_FRAME_BYTES:
                    body[:] = []
                    raise ProtocolFrameError('JSON frame exceeds frame limit')
                if len(body) >= 4 + frame_length:
                    header = bytes(body[:4])
                    frame = bytes(body[4:4 + frame_length])
                    del body[:4 + frame_length]
                    try:
                        message = json.loads(
                            frame.decode('utf-8'), object_pairs_hook=OrderedDict)
                        _record_wire_frame(
                            'inbound', sock, header, frame, message)
                        return message
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise ProtocolFrameError(
                            'invalid UTF-8 JSON frame: {}'.format(exc))
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError('TCP peer closed')
            body.extend(chunk)
            if len(body) > MAX_FRAME_BYTES + 4:
                body[:] = []
                raise ProtocolFrameError('JSON frame exceeds frame limit')
    except socket.timeout:
        return None


def _is_matching_accepted_ack(message, ref_type, ref_seq):
    if not isinstance(message, dict) or tuple(message) != V2_OUTER_FIELDS:
        return False
    if (message.get('protocol_version') != '2.0'
            or message.get('type') != 'ack'
            or message.get('vehicle_id') != 'Drone1'
            or isinstance(message.get('seq'), bool)
            or not isinstance(message.get('seq'), int)
            or message.get('seq') < 1):
        return False
    data = message.get('data')
    return (isinstance(data, dict) and tuple(data) == V2_ACK_DATA_FIELDS
            and data.get('ref_type') == ref_type
            and type(data.get('ref_seq')) is int
            and data.get('ref_seq') == ref_seq
            and data.get('accepted') is True)


def _send_and_wait_for_ack(sock, message, timeout):
    _frame_send(sock, message)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        response = _frame_recv(sock, timeout=min(0.3, max(0.001, remaining)))
        if response is None:
            continue
        return _is_matching_accepted_ack(
            response, message['type'], message['seq'])
    return False


def _hello_message():
    protocol = _protocol_settings()
    data = {
        'role': protocol['role'], 'state_rate_hz': 50,
        'coordinate_convention': 'x_forward_y_right_height_up',
        'angle_unit': 'rad',
    }
    if protocol['body_frame']:
        data['body_frame'] = protocol['body_frame']
    return {
        'protocol_version': protocol['version'],
        'type': 'hello',
        'seq': _next_seq(),
        'vehicle_id': protocol['vehicle_id'], 'data': data,
    }


def _mission_plan_message(mission_id, waypoints):
    protocol = _protocol_settings()
    protocol_waypoints = []
    for index, waypoint in enumerate(validate_mission_plan(mission_id, waypoints)):
        protocol_waypoints.append({
            'id': 'P{}'.format(index + 1),
            'x': waypoint['x'],
            'y': waypoint['y'],
            'height': waypoint['height'],
            'target_speed': waypoint['speed'],
        })
    return {
        'protocol_version': protocol['version'],
        'type': 'mission_plan',
        'seq': _next_seq(),
        'vehicle_id': protocol['vehicle_id'],
        'data': {
            'mission_id': mission_id,
            'replace_previous': True,
            'waypoints': protocol_waypoints,
        },
    }


def _perform_handshake(sock, mission_id, waypoints, ack_timeout=5.0):
    hello = _hello_message()
    if not _send_and_wait_for_ack(sock, hello, ack_timeout):
        logger.warning('hello acknowledgement failed')
        return False
    mission = _mission_plan_message(mission_id, waypoints)
    if not _send_and_wait_for_ack(sock, mission, ack_timeout):
        logger.warning('mission_plan acknowledgement failed')
        return False
    return True


def _vehicle_state_sender(sock, mission_id, stop_event, max_frames=None,
                          monotonic_fn=None, sleep_fn=None):
    monotonic_fn = monotonic_fn or time.monotonic
    sleep_fn = sleep_fn or time.sleep
    next_send = monotonic_fn()
    sent = 0
    stale_flagged = False
    stale_warned = False
    while not stop_event.is_set() and (max_frames is None or sent < max_frames):
        try:
            if _protocol_settings()['version'] == '3.0':
                state_message = state_cache.get_vehicle_state_v3(mission_id, 50)
            else:
                state_message = state_cache.get_vehicle_state_v2(mission_id, 50)
        except ValueError as exc:
            logger.warning('vehicle_state withheld: {}'.format(exc))
            state_message = None
        if state_message is not None:
            stale_flagged = False
            stale_warned = False
            state_message['seq'] = _next_seq()
            _frame_send(sock, state_message)
            _set_session_status('state streaming', None)
            sent += 1
        else:
            age = state_cache.state_age_s()
            if age is not None and age > 0.5 and not stale_flagged:
                logger.warning(
                    'vehicle_state stale for {:.3f}s; withholding state frame'.format(age))
                stale_flagged = True
            if age is not None and age > 2.0 and not stale_warned:
                logger.warning('vehicle_state stale for {:.3f}s'.format(age))
                stale_warned = True
        next_send += 0.02
        sleep_fn(max(0.0, next_send - monotonic_fn()))
    return sent


def _simulation_event_message(event_name, mission_id=''):
    protocol = _protocol_settings()
    message = {
        'protocol_version': protocol['version'],
        'type': 'simulation_event',
        'seq': _next_seq(),
        'vehicle_id': protocol['vehicle_id'],
        'data': {'event': state_cache.v2_event_name(event_name)},
    }
    if mission_id:
        message['data']['mission_id'] = mission_id
    return message


def _send_simulation_event_message(sock, event_name, mission_id='',
                                   ack_timeout=5.0):
    message = _simulation_event_message(event_name, mission_id)
    return _send_and_wait_for_ack(sock, message, ack_timeout)


def _send_mission_end(sock, mission_id, enabled, ack_timeout=5.0):
    if not enabled:
        return True
    return _send_simulation_event_message(
        sock, 'mission_end', mission_id, ack_timeout)


def send_mission_plan(mission_id, waypoints):
    """Queue an externally accepted NED-derived route for UE4 delivery.

    There is deliberately no built-in route.  A mission must have passed the
    C-core ``load_mission`` validation before this function is called.
    """
    global _current_mission_id, _pending_waypoints
    validated = validate_mission_plan(mission_id, waypoints)
    with _queue_lock:
        _current_mission_id = mission_id
        _pending_waypoints = validated
        _mission_queue.append((mission_id, validated))


def send_simulation_event(event_name, mission_id=''):
    # Validate at ingress but keep the internal lifecycle name in the queue.
    # Wire-name conversion belongs to _simulation_event_message(); converting
    # here as well turns ``reset`` into ``reset_scene`` twice.
    state_cache.v2_event_name(event_name)
    with _queue_lock:
        _event_queue.append((event_name, mission_id))


def reserve_simulation_event(event_name, mission_id=''):
    """Mark a lifecycle producer as in flight before its C-core request."""
    state_cache.v2_event_name(event_name)
    reservation = object()
    with _queue_lock:
        _event_reservations[reservation] = (event_name, mission_id)
    return reservation


def resolve_simulation_event(reservation, accepted):
    """Atomically cancel or enqueue a previously reserved lifecycle event."""
    with _queue_lock:
        event = _event_reservations.pop(reservation, None)
        if event is None:
            return False
        if accepted is True:
            _event_queue.append(event)
        return True


def is_connected():
    return _connected.is_set()


def _build_and_send_mission_plan(sock, mission_id, waypoints):
    message = _mission_plan_message(mission_id, waypoints)
    accepted = _send_and_wait_for_ack(sock, message, 10.0)
    if accepted:
        _set_session_status('mission plan acknowledged', None)
        logger.info('mission_plan acked: {} waypoints'.format(
            len(message['data']['waypoints'])))
    else:
        logger.warning('mission_plan acknowledgement failed')
    return accepted


def _discard_queued_mission(mission_id, waypoints):
    with _queue_lock:
        _mission_queue[:] = [
            queued for queued in _mission_queue
            if queued != (mission_id, waypoints)]


def _snapshot_pending_mission():
    with _queue_lock:
        if _current_mission_id is None or _pending_waypoints is None:
            return None
        return _current_mission_id, _pending_waypoints


def _drain_queues():
    with _queue_lock:
        missions = list(_mission_queue)
        events = list(_event_queue)
        _mission_queue[:] = []
        _event_queue[:] = []
    return missions, events


def _requeue_events(events):
    with _queue_lock:
        _event_queue[0:0] = events


def _finish_mission(mission_id):
    global _current_mission_id, _pending_waypoints
    with _queue_lock:
        if _current_mission_id == mission_id:
            _current_mission_id = None
            _pending_waypoints = None


def _finish_mission_if_no_queued_end(mission_id):
    global _current_mission_id, _pending_waypoints
    with _queue_lock:
        pending_end = any(
            event_name == 'mission_end'
            and (not event_mission_id or event_mission_id == mission_id)
            for event_name, event_mission_id in _event_queue)
        reserved_end = any(
            event_name == 'mission_end'
            and (not event_mission_id or event_mission_id == mission_id)
            for event_name, event_mission_id in _event_reservations.values())
        if pending_end or reserved_end:
            return False
        if _current_mission_id == mission_id:
            _current_mission_id = None
            _pending_waypoints = None
        return True


def _run_connected_session(sock):
    _reset_session_sequence()
    hello = _hello_message()
    if not _send_and_wait_for_ack(sock, hello, 5.0):
        _set_session_status(last_error='hello acknowledgement failed')
        logger.warning('hello acknowledgement failed')
        return False
    _set_session_status('hello acknowledged', None)
    logger.info('hello acked')

    # A mission can arrive after the TCP connection.  Expose handshake
    # readiness to the local command path, but never publish state yet.
    _connected.set()
    pending_mission = _snapshot_pending_mission()
    while _running and _connected.is_set() and pending_mission is None:
        response = _frame_recv(sock, timeout=0.1)
        if response and response.get('type') == 'error':
            _set_session_status(last_error='UE4 error while waiting for mission_plan')
            logger.warning('UE4 error while waiting for mission_plan')
            return False
        pending_mission = _snapshot_pending_mission()
    if not _running or not _connected.is_set():
        return False

    mission_id, waypoints = pending_mission
    state_before_mission = state_cache.get_state_dict()
    state_sequence_before_mission = (
        state_before_mission.get('sequence') if state_before_mission else None)
    if not _build_and_send_mission_plan(sock, mission_id, waypoints):
        return False
    _discard_queued_mission(mission_id, waypoints)

    publisher_stop = threading.Event()
    publisher = None

    def start_publisher(active_mission_id):
        def publish():
            try:
                _vehicle_state_sender(sock, active_mission_id, publisher_stop)
            except Exception as exc:
                _set_session_status(last_error='vehicle_state send failed: {}'.format(exc))
                logger.warning('vehicle_state send failed: {}'.format(exc))
                publisher_stop.set()
                _connected.clear()
        thread = threading.Thread(target=publish, daemon=True,
                                  name='bridge_v2_state')
        thread.start()
        return thread

    publisher = start_publisher(mission_id)
    try:
        while (_running and _connected.is_set()
               and not publisher_stop.is_set()):
            response = _frame_recv(sock, timeout=0.1)
            if response and response.get('type') == 'error':
                _set_session_status(last_error='UE4 protocol error: {}'.format(response))
                logger.warning('UE4 protocol error: {}'.format(response))
                return False

            missions, events = _drain_queues()
            for next_mission_id, next_waypoints in missions:
                publisher_stop.set()
                publisher.join(1.0)
                if not _build_and_send_mission_plan(
                        sock, next_mission_id, next_waypoints):
                    return False
                mission_id = next_mission_id
                publisher_stop = threading.Event()
                publisher = start_publisher(mission_id)

            for event_index, (event_name, event_mission_id) in enumerate(events):
                if not _send_simulation_event_message(
                        sock, event_name, event_mission_id, 5.0):
                    _requeue_events(events[event_index:])
                    logger.warning(
                        'simulation_event acknowledgement failed: {}'.format(
                            event_name))
                    return False
                logger.info('simulation_event acked: {}'.format(event_name))
                if event_name == 'mission_end':
                    _finish_mission(event_mission_id or mission_id)
                    _set_session_status('mission ended', None)
                    return True

            current_state = state_cache.get_state_dict()
            if (current_state and current_state.get('lifecycle') == 'ENDED'
                    and (state_sequence_before_mission is None
                         or current_state.get('sequence')
                         > state_sequence_before_mission)):
                if _finish_mission_if_no_queued_end(mission_id):
                    _set_session_status('mission ended', None)
                    return True
    finally:
        publisher_stop.set()
        if publisher is not None:
            publisher.join(1.0)
        _connected.clear()
    return False


def _run(host=None, port=None):
    global _sock
    host = UE4_HOST if host is None else host
    port = UE4_PORT if port is None else port
    logger.info("V2.0 bridge starting -> {}:{}".format(host, port))

    while _running and not _stop_event.is_set():
        _set_session_status('connecting', None)
        _connected.clear()
        s = None
        mission_completed = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Disable Nagle so 20 ms vehicle_state frames leave immediately
            # instead of being buffered behind delayed-ACKs (which would
            # burst them and break the strict 50 Hz interval contract).
            if s.family == socket.AF_INET:
                try:
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
            s.settimeout(0.2)
            s.connect((host, port))
            with _sock_lock:
                _sock = s
            logger.info("V2.0 bridge connected to {}:{}".format(
                host, port))
            mission_completed = _run_connected_session(s)
        except (ConnectionRefusedError, OSError) as e:
            _set_session_status(last_error=str(e))
            logger.warning("Bridge connect failed: {}".format(e))
        except Exception as e:
            _set_session_status(last_error=str(e))
            logger.error("Bridge error: {}".format(e))
        finally:
            _connected.clear()
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            with _sock_lock:
                _sock = None
            logger.info('V2.0 bridge disconnected')

        if mission_completed:
            return
        _stop_event.wait(3.0)


def start_bridge(host=None, port=None):
    global _running
    host = UE4_HOST if host is None else host
    port = UE4_PORT if port is None else port
    _running = True
    _stop_event.clear()
    t = threading.Thread(target=_run, args=(host, port), daemon=True,
                         name='bridge_v2')
    t.start()
    logger.info("V2.0 bridge started")
    return t


def stop_bridge():
    global _running, _sock
    _running = False
    _stop_event.set()
    _connected.clear()
    with _sock_lock:
        if _sock:
            try:
                _sock.close()
            except Exception:
                pass
            _sock = None
