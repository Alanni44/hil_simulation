#!/usr/bin/env python3
"""
UE4 TCP Client — 严格按 Simulink-UE4 协议 V1.0
- 请求-响应模式：发命令 → 等 UE4 返回 → relay 给调用方
- 不推送状态，不批量发送
"""
import json
import socket
import threading
import time
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('ue4_tcp')

UE4_HOST = CONFIG['ue4_tcp']['host']
UE4_PORT = CONFIG['ue4_tcp']['port']

_client_running = True
_sock = None
_sock_lock = threading.Lock()
_recv_buf = b''
_recv_buf_lock = threading.Lock()


def _ensure_connected():
    global _sock
    with _sock_lock:
        if _sock:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((UE4_HOST, UE4_PORT))
            s.settimeout(1.0)
            _sock = s
            logger.info("Connected to UE4 {}:{}".format(UE4_HOST, UE4_PORT))
            return True
        except Exception as e:
            logger.warning("UE4 {}:{} unreachable: {}".format(UE4_HOST, UE4_PORT, e))
            return False


def _read_response(timeout=5.0):
    raw = _read_raw_response(timeout)
    if raw is None:
        return {'status': 'error', 'message': 'UE4 not reachable'}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {'status': 'error', 'message': 'invalid JSON: {}'.format(raw[:100])}


def _read_raw_response(timeout=5.0):
    """从 socket 读取一行原始 JSON 字符串"""
    global _recv_buf
    with _sock_lock:
        if not _sock:
            return None
        try:
            _sock.settimeout(timeout)
            deadline = time.time() + timeout
            while time.time() < deadline:
                with _recv_buf_lock:
                    if b'\n' in _recv_buf:
                        line, _recv_buf = _recv_buf.split(b'\n', 1)
                        return line.strip().decode('utf-8')
                try:
                    chunk = _sock.recv(4096)
                    if not chunk:
                        _sock.close()
                        _sock = None
                        return None
                except socket.timeout:
                    continue
                with _recv_buf_lock:
                    _recv_buf += chunk
            _sock.settimeout(1.0)
            return None
        except Exception:
            _sock.close()
            _sock = None
            return None


def ue4_send_and_recv(cmd_dict, timeout=5.0):
    """
    发送命令给 UE4，等待并返回响应。阻塞调用。
    返回格式: {"status": "success"|"accepted"|"error", "message": "..."}
    """
    resp = ue4_send_and_recv_raw(cmd_dict, timeout)
    if resp is None:
        return {'status': 'error', 'message': 'UE4 not reachable'}
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        return {'status': 'error', 'message': 'invalid JSON: {}'.format(resp[:100])}


def ue4_send_and_recv_raw(cmd_dict, timeout=5.0):
    """
    发送命令给 UE4，返回原始 JSON 字符串。用于透传模式。
    """
    if not _ensure_connected():
        return None

    with _sock_lock:
        if not _sock:
            return None
        try:
            _sock.sendall((json.dumps(cmd_dict) + '\n').encode('utf-8'))
            logger.info("UE4 cmd: {}".format(cmd_dict.get('cmd', '?')))
        except Exception as e:
            logger.error("UE4 send failed: {}".format(e))
            _sock.close()
            _sock = None
            return None

    return _read_raw_response(timeout)


def ue4_send_command(cmd_dict):
    """异步发送（不等待响应），用于不需要回复的场景"""
    if not _ensure_connected():
        return
    with _sock_lock:
        if not _sock:
            return
        try:
            _sock.sendall((json.dumps(cmd_dict) + '\n').encode('utf-8'))
            logger.info("UE4 cmd: {}".format(cmd_dict.get('cmd', '?')))
        except Exception as e:
            logger.error("UE4 send failed: {}".format(e))
            _sock.close()
            _sock = None


def start_ue4_server():
    logger.info("UE4 TCP client started -> {}:{}".format(UE4_HOST, UE4_PORT))


def stop_ue4_server():
    global _client_running
    _client_running = False
    with _sock_lock:
        if _sock:
            _sock.close()
            _sock = None
