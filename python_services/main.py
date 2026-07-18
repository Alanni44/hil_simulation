#!/usr/bin/env python3
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.logger import get_logger
from ws_server import start_ws_server
from udp_forwarder import start_udp_forwarder
from ue4_tcp_server import start_ue4_server

logger = get_logger('main')


def main():
    print("=" * 60)
    print("  HIL Python Services")
    print("=" * 60)
    print("  WebSocket (Spring Boot)   ws://0.0.0.0:8100/ws/hil")
    print("  flight_data push          10Hz")
    print("  sim_heartbeat push         1Hz")
    print("  UE4 TCP push (JSON)       10Hz  -> TCP 8889")
    print("  C-core UDP relay          internal")
    print("=" * 60)

    threads = [
        threading.Thread(target=start_udp_forwarder, daemon=True, name='udp'),
        threading.Thread(target=start_ue4_server, daemon=True, name='ue4'),
        threading.Thread(target=start_ws_server, daemon=True, name='ws'),
    ]

    for t in threads:
        t.start()
        logger.info(f"{t.name} started")

    logger.info("All services running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        sys.exit(0)


if __name__ == '__main__':
    main()
