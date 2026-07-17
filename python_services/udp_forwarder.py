#!/usr/bin/env python3
import socket
import time
import threading
from shared.flight_state import FLIGHT_STATE_SIZE
from shared.logger import get_logger
from config_loader import CONFIG
from ue4_tcp_server import update_state

logger = get_logger('udp_forwarder')

recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_sock.bind(('0.0.0.0', CONFIG['local_udp']['status_port']))

send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
TARGET_IP = CONFIG['udp_forward']['target_ip']
TARGET_PORT = CONFIG['udp_forward']['target_port']
SEND_INTERVAL = 1.0 / CONFIG['udp_forward']['send_hz']

latest_state = None
state_lock = threading.Lock()

def recv_worker():
    logger.info(f"Receiving from UDP {CONFIG['local_udp']['status_port']}")
    while True:
        try:
            data, addr = recv_sock.recvfrom(4096)
            if len(data) == FLIGHT_STATE_SIZE:
                with state_lock:
                    latest_state = data
                update_state(data)
            else:
                logger.warning(f"Bad size: {len(data)}")
        except Exception as e:
            logger.error(f"Recv error: {e}")

def send_worker():
    logger.info(f"Forwarding to {TARGET_IP}:{TARGET_PORT}, {CONFIG['udp_forward']['send_hz']}Hz")
    while True:
        start = time.time()
        with state_lock:
            if latest_state:
                try:
                    send_sock.sendto(latest_state, (TARGET_IP, TARGET_PORT))
                except Exception as e:
                    logger.error(f"Send error: {e}")
        elapsed = time.time() - start
        if elapsed < SEND_INTERVAL:
            time.sleep(SEND_INTERVAL - elapsed)

def start_udp_forwarder():
    threading.Thread(target=recv_worker, daemon=True).start()
    threading.Thread(target=send_worker, daemon=True).start()
    logger.info("UDP forwarder started")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("UDP forwarder stopped")

if __name__ == '__main__':
    start_udp_forwarder()