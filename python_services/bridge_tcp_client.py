#!/usr/bin/env python3
"""
V2.0 TCP Bridge Client — 严格按 Simulink-三维视景通信协议 V2.0
连接 UE4 侧的 Python Bridge（TCP Server :5000）
帧格式: [4字节大端长度头][UTF-8 JSON]
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
import socket
import struct
import threading
import time
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
_seq = 0
_seq_lock = threading.Lock()

_current_mission_id = 'mission_001'
_mission_ready = threading.Event()  # mission_plan ACK 后才 set
_event_queue = []
_queue_lock = threading.Lock()

# 默认圆形航线 (V2.0 测试用)
_DEFAULT_WAYPOINTS = [
    {'x': 30.0, 'y': 15.0, 'height': 10.0, 'speed': 5.0},
    {'x': 28.8, 'y': 22.8, 'height': 10.0, 'speed': 5.0},
    {'x': 22.8, 'y': 28.8, 'height': 10.0, 'speed': 5.0},
    {'x': 15.0, 'y': 30.0, 'height': 10.0, 'speed': 5.0},
    {'x': 7.2, 'y': 22.8, 'height': 10.0, 'speed': 5.0},
    {'x': 1.2, 'y': 15.0, 'height': 10.0, 'speed': 5.0},
    {'x': 7.2, 'y': 7.2, 'height': 10.0, 'speed': 5.0},
    {'x': 15.0, 'y': 0.0, 'height': 10.0, 'speed': 5.0},
    {'x': 22.8, 'y': 7.2, 'height': 10.0, 'speed': 5.0},
    {'x': 30.0, 'y': 15.0, 'height': 10.0, 'speed': 5.0},
]


def _next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def _sanitize(obj):
    if isinstance(obj, float):
        import math
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _frame_send(sock, data):
    clean = _sanitize(data)
    body = json.dumps(clean).encode('utf-8')
    header = struct.pack('>I', len(body))
    with _send_lock:
        sock.sendall(header + body)


def _frame_recv(sock, timeout=0.5):
    sock.settimeout(timeout)
    try:
        hdr = b''
        while len(hdr) < 4:
            chunk = sock.recv(4 - len(hdr))
            if not chunk:
                return None
            hdr += chunk
        length = struct.unpack('>I', hdr)[0]
        if length > 1048576:
            return None
        body = b''
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                return None
            body += chunk
        return json.loads(body.decode('utf-8'))
    except socket.timeout:
        return None
    except Exception as e:
        logger.warning("Frame recv error: {}".format(e))
        return None


def send_mission_plan(mission_id, waypoints):
    """非阻塞：设置 mission_id 并触发 mission_plan 发送"""
    global _current_mission_id
    _current_mission_id = mission_id
    with _queue_lock:
        _mission_queue.append((mission_id, list(waypoints)))


def send_simulation_event(event_name, mission_id=''):
    with _queue_lock:
        _event_queue.append((event_name, mission_id))


def is_connected():
    return _connected.is_set()


def _build_mission_plan(mission_id, waypoints):
    wps = []
    for i, wp in enumerate(waypoints):
        wps.append({
            'id': 'P{}'.format(i + 1),
            'x': wp.get('x', 0),
            'y': wp.get('y', 0),
            'height': wp.get('height', 0),
            'target_speed': wp.get('speed', 5),
        })
    return {
        'protocol_version': '2.0',
        'type': 'mission_plan',
        'seq': _next_seq(),
        'vehicle_id': 'Drone1',
        'data': {
            'mission_id': mission_id,
            'replace_previous': True,
            'waypoints': wps,
        }
    }


def _run():
    global _sock
    logger.info("V2.0 bridge starting -> {}:{}".format(UE4_HOST, UE4_PORT))

    while _running:
        _connected.clear()
        _mission_ready.clear()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect((UE4_HOST, UE4_PORT))
            with _sock_lock:
                _sock = s
            logger.info("V2.0 bridge connected to {}:{}".format(UE4_HOST, UE4_PORT))

            # ---- step 1: hello ----
            _frame_send(s, {
                'protocol_version': '2.0',
                'type': 'hello',
                'seq': _next_seq(),
                'vehicle_id': 'Drone1',
                'data': {
                    'role': 'simulink_state_source',
                    'state_rate_hz': 50,
                    'coordinate_convention': 'x_forward_y_right_height_up',
                    'angle_unit': 'rad',
                }
            })
            logger.info("hello sent")

            ack = _frame_recv(s, timeout=5.0)
            if not (ack and ack.get('type') == 'ack'
                    and ack.get('data', {}).get('accepted')):
                logger.warning("hello ack failed, got: {}".format(ack))
                s.close()
                time.sleep(3)
                continue
            logger.info("hello acked")

            # ---- step 2: send mission_plan (default or queued) ----
            _connected.set()

            # 发默认 mission_plan
            msg = _build_mission_plan(_current_mission_id, _DEFAULT_WAYPOINTS)
            _frame_send(s, msg)
            logger.info("mission_plan sent: {} waypoints".format(
                len(_DEFAULT_WAYPOINTS)))

            # 等 mission_plan ACK
            mp_acked = False
            deadline = time.time() + 10.0
            while time.time() < deadline:
                resp = _frame_recv(s, timeout=0.3)
                if resp and resp.get('type') == 'ack' \
                        and resp.get('data', {}).get('ref_type') == 'mission_plan':
                    logger.info("mission_plan acked")
                    mp_acked = True
                    break
                elif resp and resp.get('type') == 'error':
                    logger.warning("mission_plan error: {} / {}".format(
                        resp.get('data', {}).get('code', '?'),
                        resp.get('data', {}).get('message', '?')))
                    break

            if not mp_acked:
                logger.warning("mission_plan ack not received")
                s.close()
                time.sleep(3)
                continue

            _mission_ready.set()

            # ---- step 3: vehicle_state @50Hz ----
            def vehicle_state_sender():
                # 没有 timeout fallback——必须等到 _mission_ready
                if not _mission_ready.wait(timeout=10.0):
                    logger.error("mission_ready timeout, not starting vehicle_state")
                    return
                while _connected.is_set():
                    vs = state_cache.get_vehicle_state_v2(_current_mission_id, 50)
                    if vs is not None:
                        try:
                            vs['seq'] = _next_seq()
                            _frame_send(s, vs)
                        except Exception as e:
                            logger.warning("vehicle_state send failed: {}".format(e))
                            _connected.clear()
                            break
                    time.sleep(0.02)

            sender_t = threading.Thread(target=vehicle_state_sender, daemon=True)
            sender_t.start()

            # ---- step 4: read loop (处理后续 ack/error/event) ----
            while _connected.is_set():
                resp = _frame_recv(s, timeout=0.3)
                if resp:
                    rtype = resp.get('type', '')
                    if rtype == 'ack':
                        ref = resp.get('data', {}).get('ref_type', '')
                        logger.info("ACK ref_type={}".format(ref))
                    elif rtype == 'error':
                        logger.warning("ERROR: {} / {}".format(
                            resp.get('data', {}).get('code', '?'),
                            resp.get('data', {}).get('message', '?')))

                # 发送队列中的 events
                with _queue_lock:
                    events = list(_event_queue)
                    _event_queue.clear()
                for event_name, mission_id in events:
                    msg = {
                        'protocol_version': '2.0',
                        'type': 'simulation_event',
                        'seq': _next_seq(),
                        'vehicle_id': 'Drone1',
                        'data': {'event': event_name},
                    }
                    if mission_id:
                        msg['data']['mission_id'] = mission_id
                    _frame_send(s, msg)
                    logger.info("simulation_event: {}".format(event_name))

            s.close()
            with _sock_lock:
                _sock = None
            logger.info("V2.0 bridge disconnected")
        except (ConnectionRefusedError, OSError) as e:
            logger.warning("Bridge connect failed: {}".format(e))
        except Exception as e:
            logger.error("Bridge error: {}".format(e))

        time.sleep(3)


def start_bridge():
    t = threading.Thread(target=_run, daemon=True, name='bridge_v2')
    t.start()
    logger.info("V2.0 bridge started")


def stop_bridge():
    global _running, _sock
    _running = False
    _connected.clear()
    _mission_ready.clear()
    with _sock_lock:
        if _sock:
            try:
                _sock.close()
            except Exception:
                pass
            _sock = None
