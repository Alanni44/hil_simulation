#!/usr/bin/env python3
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.logger import get_logger
from ws_server import start_ws_server
from udp_forwarder import start_udp_forwarder
from bridge_tcp_client import start_bridge
from config_loader import CONFIG

logger = get_logger('main')


def main():
    print("=" * 60)
    print("  HIL Python Services (V2.0 protocol)")
    print("=" * 60)
    print("  WebSocket (client)           -> Spring Boot {}:{}{}".format(
        CONFIG['spring_boot'].get('host', '?'),
        CONFIG['spring_boot']['websocket_port'],
        CONFIG['spring_boot'].get('path', '/ws/hil')))
    print("  V2.0 Bridge (client)         -> Python Bridge {}:{}".format(
        CONFIG['ue4_tcp']['host'],
        CONFIG['ue4_tcp']['port']))
    print("  C-core UDP relay            -> {}:{}".format(
        '127.0.0.1', CONFIG['local_udp']['command_port']))
    print("  UDP status receiver          <- {}:{}".format(
        '0.0.0.0', CONFIG['local_udp']['status_port']))
    print("  vehicle_state push          @20Hz")
    print("  MATLAB builder               on demand")
    print("=" * 60)

    threads = [
        threading.Thread(target=start_udp_forwarder, daemon=True, name='udp'),
        threading.Thread(target=start_ws_server, daemon=True, name='ws'),
        threading.Thread(target=start_bridge, daemon=True, name='bridge'),
    ]

    for t in threads:
        t.start()
        logger.info("{} started".format(t.name))

    logger.info("All services running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        sys.exit(0)


if __name__ == '__main__':
    main()
