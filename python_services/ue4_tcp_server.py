#!/usr/bin/env python3
import socket
import struct
import threading
import time
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('ue4_tcp')

TCP_PORT = CONFIG['ue4_tcp']['port']
SEND_INTERVAL = 1.0 / CONFIG['ue4_tcp']['send_hz']

latest_state = None
state_lock = threading.Lock()
clients = []
clients_lock = threading.Lock()
server_running = True

def update_state(data: bytes):
    global latest_state
    with state_lock:
        latest_state = data

def broadcast_worker():
    logger.info(f"UE4 broadcast {TCP_PORT}, {CONFIG['ue4_tcp']['send_hz']}Hz")
    while server_running:
        start = time.time()
        with state_lock:
            if latest_state is None:
                time.sleep(SEND_INTERVAL)
                continue
            data = latest_state
        packet = struct.pack('>I', len(data)) + data
        with clients_lock:
            dead = []
            for c in clients:
                try:
                    c.send(packet)
                except:
                    dead.append(c)
            for d in dead:
                try:
                    d.close()
                except:
                    pass
                clients.remove(d)
                logger.info(f"UE4 client removed, count: {len(clients)}")
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
            logger.info(f"UE4 client connected: {addr}, count: {len(clients)}")
        except socket.timeout:
            continue
        except Exception as e:
            if server_running:
                logger.error(f"TCP error: {e}")
    server.close()
    logger.info("UE4 TCP server stopped")

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
            except:
                pass
        clients.clear()
    logger.info("UE4 service stopped")