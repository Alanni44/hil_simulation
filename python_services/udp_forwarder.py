#!/usr/bin/env python3
import socket
import threading
from shared.flight_state import FLIGHT_STATE_SIZE
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG

logger = get_logger('udp_forwarder')

recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_sock.bind(('0.0.0.0', CONFIG['local_udp']['status_port']))


def recv_worker():
    logger.info(f"UDP status receiver on {CONFIG['local_udp']['status_port']}")
    while True:
        try:
            data, addr = recv_sock.recvfrom(4096)
            if len(data) == FLIGHT_STATE_SIZE:
                state_cache.update(data)
            else:
                logger.warning(f"Bad size: {len(data)}")
        except Exception as e:
            logger.error(f"UDP recv error: {e}")


def start_udp_forwarder():
    threading.Thread(target=recv_worker, daemon=True).start()
    logger.info("UDP forwarder started (receiving from C core)")
