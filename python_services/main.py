#!/usr/bin/env python3
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.logger import get_logger
from ws_server import start_ws_server, _ws_listen_host
from udp_forwarder import start_udp_forwarder
from bridge_tcp_client import start_bridge
from fixed_wing_v3_bridge import FixedWingV3BridgeServer
from config_loader import CONFIG
from hil_adapters.px4_hil_service import Px4HilService
from hil_adapters.virtual_quad_fc import VirtualQuadrotorFcService, register_service

logger = get_logger('main')


def main():
    # Fail the complete service before any worker starts when GitLab management
    # would violate its loopback-only boundary.
    _ws_listen_host()
    bridge_version = CONFIG.get('bridge', {}).get('protocol_version', '2.0')
    print("=" * 60)
    print("  HIL Python Services (V{} protocol)".format(bridge_version))
    print("=" * 60)
    print("  WebSocket (client)           -> Spring Boot {}:{}{}".format(
        CONFIG['spring_boot'].get('host', '?'),
        CONFIG['spring_boot']['websocket_port'],
        CONFIG['spring_boot'].get('path', '/ws/hil')))
    if bridge_version == '3.0':
        endpoint = CONFIG.get('fixed_wing_v3', {})
        print("  V3.0 Bridge (server)         <- Fixed-wing client {}:{}".format(
            endpoint.get('host', '0.0.0.0'), endpoint.get('port', 5000)))
    else:
        print("  V{} Bridge (client)         -> Python Bridge {}:{}".format(bridge_version,
            CONFIG['ue4_tcp']['host'], CONFIG['ue4_tcp']['port']))
    print("  C-core UDP relay            -> {}:{}".format(
        '127.0.0.1', CONFIG['local_udp']['command_port']))
    print("  UDP status receiver          <- {}:{}".format(
        '0.0.0.0', CONFIG['local_udp']['status_port']))
    print("  vehicle_state push          @50Hz")
    print("  MATLAB builder               on demand")
    print("=" * 60)

    workers = [
        threading.Thread(target=start_udp_forwarder, daemon=True, name='udp'),
        threading.Thread(target=start_ws_server, daemon=True, name='ws'),
    ]
    v3_server = None
    if bridge_version == '3.0':
        v3_server = FixedWingV3BridgeServer()
    else:
        workers.append(threading.Thread(target=start_bridge, daemon=True, name='bridge'))

    px4_service = None
    virtual_fc_service = None
    px4_config = CONFIG.get('px4_hil', {})
    if px4_config.get('enabled'):
        px4_service = Px4HilService(px4_config)

    for t in workers:
        t.start()
        logger.info("{} started".format(t.name))
    if v3_server is not None:
        v3_server.start()
        logger.info("fixed_wing_v3_server started")

    if px4_service is not None:
        px4_service.start()
        logger.info("px4_hil started")

    virtual_fc_config = CONFIG.get('virtual_quad_fc', {})
    if virtual_fc_config.get('enabled'):
        virtual_fc_config = dict(virtual_fc_config)
        virtual_fc_config.setdefault('sensor_port', CONFIG['local_udp'].get('sensor_port', 9996))
        virtual_fc_service = VirtualQuadrotorFcService(virtual_fc_config)
        register_service(virtual_fc_service)
        virtual_fc_service.start()
        logger.info("virtual_quad_fc started; fresh C state input on UDP {}".format(
            virtual_fc_config['sensor_port']))

    logger.info("All services running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        if px4_service is not None:
            px4_service.stop()
        if virtual_fc_service is not None:
            virtual_fc_service.stop()
        if v3_server is not None:
            v3_server.stop()
        sys.exit(0)


if __name__ == '__main__':
    main()
