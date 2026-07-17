#!/usr/bin/env python3
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.logger import get_logger
from init_server import start_init_server
from tuning_server import start_tuning_server
from udp_forwarder import start_udp_forwarder
from ue4_tcp_server import start_ue4_server
from model_upload import start_upload_server
from model_build_monitor import start_build_monitor

logger = get_logger('main')

def main():
    print("=" * 60)
    print("  HIL Python Services")
    print("=" * 60)
    print("服务: 初始化(9997) 调参(8888) 转发(10Hz) UE4(8889)")
    print("      上传(9996) 构建监控(MATLAB)")
    print("=" * 60)

    threads = [
        threading.Thread(target=start_init_server, daemon=True, name='init'),
        threading.Thread(target=start_tuning_server, daemon=True, name='tune'),
        threading.Thread(target=start_udp_forwarder, daemon=True, name='udp_fwd'),
        threading.Thread(target=start_ue4_server, daemon=True, name='ue4'),
        threading.Thread(target=start_upload_server, daemon=True, name='upload'),
        threading.Thread(target=start_build_monitor, daemon=True, name='build'),
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