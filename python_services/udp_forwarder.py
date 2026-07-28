#!/usr/bin/env python3
import socket
import threading
from shared.flight_state import FLIGHT_STATE_SIZE
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG

logger = get_logger('udp_forwarder')

_recv_sock = None
_socket_lock = threading.Lock()
_running = threading.Event()


def recv_worker():
    logger.info(f"UDP status receiver on {CONFIG['local_udp']['status_port']}")
    while _running.is_set():
        try:
            with _socket_lock:
                recv_sock = _recv_sock
            if recv_sock is None:
                return
            data, addr = recv_sock.recvfrom(4096)
            if len(data) == FLIGHT_STATE_SIZE:
                state_cache.update(data)
            else:
                logger.warning(f"Bad size: {len(data)}")
        except socket.timeout:
            continue
        except OSError as e:
            if _running.is_set():
                logger.error(f"UDP recv error: {e}")
            return
        except Exception as e:
            logger.error(f"UDP recv error: {e}")


def start_udp_forwarder():
    global _recv_sock
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind(('0.0.0.0', CONFIG['local_udp']['status_port']))
    recv_sock.settimeout(0.5)
    with _socket_lock:
        _recv_sock = recv_sock
    _running.set()
    worker = threading.Thread(
        target=recv_worker, daemon=True, name='udp_forwarder')
    worker.start()
    logger.info("UDP forwarder started (receiving from C core)")
    return worker


def stop_udp_forwarder():
    global _recv_sock
    _running.clear()
    with _socket_lock:
        recv_sock = _recv_sock
        _recv_sock = None
    if recv_sock is not None:
        recv_sock.close()
