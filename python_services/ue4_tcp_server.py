#!/usr/bin/env python3
import json
import socket
import threading
import time
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG

logger = get_logger('ue4_tcp')

TCP_PORT = CONFIG['ue4_tcp']['port']
SEND_INTERVAL = 1.0 / CONFIG['ue4_tcp']['send_hz']

clients = []
clients_lock = threading.Lock()
server_running = True


def broadcast_worker():
    logger.info(f"UE4 broadcast TCP {TCP_PORT}, {CONFIG['ue4_tcp']['send_hz']}Hz")
    while server_running:
        start = time.time()
        s = state_cache.get_ue4_state()
        if s is None:
            time.sleep(SEND_INTERVAL)
            continue

        msg = (json.dumps(s) + '\n').encode('utf-8')
        with clients_lock:
            dead = []
            for c in clients:
                try:
                    c.send(msg)
                except Exception:
                    dead.append(c)
            for d in dead:
                try:
                    d.close()
                except Exception:
                    pass
                clients.remove(d)
        elapsed = time.time() - start
        if elapsed < SEND_INTERVAL:
            time.sleep(SEND_INTERVAL - elapsed)


def tcp_server_worker():
    global server_running
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', TCP_PORT))
    server.listen(5)
    server.settimeout(1.0)
    logger.info(f"UE4 TCP server listening on {TCP_PORT}")

    while server_running:
        try:
            client, addr = server.accept()
            with clients_lock:
                clients.append(client)
            logger.info(f"UE4 client: {addr}, count={len(clients)}")
        except socket.timeout:
            continue
        except Exception as e:
            if server_running:
                logger.error(f"TCP accept error: {e}")
    server.close()


def start_ue4_server():
    global server_running
    server_running = True
    threading.Thread(target=tcp_server_worker, daemon=True).start()
    threading.Thread(target=broadcast_worker, daemon=True).start()
    logger.info("UE4 service started")


def stop_ue4_server():
    global server_running
    server_running = False
    with clients_lock:
        for c in clients:
            try:
                c.close()
            except Exception:
                pass
        clients.clear()
