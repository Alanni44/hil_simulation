#!/usr/bin/env python3
"""Run the HIL UDP state collector and the read-only 3.6 telemetry WebSocket."""
from __future__ import absolute_import

import sys

from shared.logger import get_logger
from spring_ws_server import start_spring_ws_server
from udp_forwarder import start_udp_forwarder, stop_udp_forwarder


logger = get_logger('telemetry_main')


def main():
    start_udp_forwarder()
    logger.info('HIL telemetry service started')
    try:
        start_spring_ws_server()
    except KeyboardInterrupt:
        logger.info('HIL telemetry service stopping')
    finally:
        stop_udp_forwarder()
    return 0


if __name__ == '__main__':
    sys.exit(main())
