#!/usr/bin/env python3
"""
V2.0 TCP Bridge Client — 严格按 Simulink-三维视景通信协议 V2.0
连接 UE4 侧的 Python Bridge（TCP Server :5000）
帧格式: [4字节大端长度头][UTF-8 JSON]
消息类型:
  hello           → 握手
  mission_plan    → 发送航点规划
  vehicle_state   → 20Hz 实时状态
  simulation_event → 仿真生命周期
  ack / error     → 接收响应
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
_send_lock = threading.Lock()  # protect socket from concurrent writes
_connected = threading.Event()
_running = True
_seq = 0
_seq_lock = threading.Lock()

_current_mission_id = 'mission_001'
_mission_queue = []   # items: (mission_id, waypoints_list)
_event_queue = []     # items: (event_name, mission_id)
_queue_lock = threading.Lock()


def _next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def _frame_send(sock, data):
    body = json.dumps(data).encode('utf-8')
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
    """非阻塞：队列发送 mission_plan"""
    with _queue_lock:
        _mission_queue.append((mission_id, list(waypoints)))


def send_simulation_event(event_name, mission_id=''):
    """非阻塞：队列发送 simulation_event"""
    with _queue_lock:
        _event_queue.append((event_name, mission_id))


def is_connected():
    return _connected.is_set()


def _drain_queues(sock):
    """发送队列中的 mission_plan 和 simulation_event"""
    with _queue_lock:
        missions = list(_mission_queue)
        events = list(_event_queue)
        _mission_queue.clear()
        _event_queue.clear()

    for mission_id, waypoints in missions:
        _current_mission_id = mission_id
        wps = []
        for i, wp in enumerate(waypoints):
            wps.append({
                'id': 'P{}'.format(i + 1),
                'x': wp.get('x', 0),
                'y': wp.get('y', 0),
                'height': wp.get('height', 0),
                'target_speed': wp.get('speed', 5),
            })
        msg = {
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
        _frame_send(sock, msg)
        logger.info("mission_plan sent: {} waypoints".format(len(wps)))

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
        _frame_send(sock, msg)
        logger.info("simulation_event: {}".format(event_name))


def _run():
    global _sock
    logger.info("V2.0 bridge starting -> {}:{}".format(UE4_HOST, UE4_PORT))

    while _running:
        _connected.clear()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect((UE4_HOST, UE4_PORT))
            with _sock_lock:
                _sock = s
            logger.info("V2.0 bridge connected to {}:{}".format(UE4_HOST, UE4_PORT))

            # ---- hello ----
            _frame_send(s, {
                'protocol_version': '2.0',
                'type': 'hello',
                'seq': _next_seq(),
                'vehicle_id': 'Drone1',
                'data': {
                    'role': 'simulink_state_source',
                    'state_rate_hz': 20,
                    'coordinate_convention': 'x_forward_y_right_height_up',
                    'angle_unit': 'rad',
                }
            })
            logger.info("hello sent")

            ack = _frame_recv(s, timeout=5.0)
            if ack and ack.get('type') == 'ack' and\
               ack.get('data', {}).get('accepted'):
                logger.info("hello acked, bridge ready")
            else:
                logger.warning("hello ack failed, got: {}".format(ack))
                s.close()
                time.sleep(3)
                continue

            _connected.set()
            _drain_queues(s)

            # ---- sender thread (20Hz) ----
            def vehicle_state_sender():
                while _connected.is_set():
                    vs = state_cache.get_vehicle_state_v2(_current_mission_id)
                    if vs is not None:
                        try:
                            vs['seq'] = _next_seq()
                            _frame_send(s, vs)
                        except Exception as e:
                            logger.warning("vehicle_state send failed: {}".format(e))
                            _connected.clear()
                            break
                    time.sleep(0.05)

            sender_t = threading.Thread(target=vehicle_state_sender, daemon=True)
            sender_t.start()

            # ---- read loop ----
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
                _drain_queues(s)

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
    with _sock_lock:
        if _sock:
            try:
                _sock.close()
            except Exception:
                pass
            _sock = None
