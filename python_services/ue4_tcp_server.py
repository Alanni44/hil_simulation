#!/usr/bin/env python3
import json
import socket
import threading
import time
from shared.flight_state import parse_flight_state
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('ue4_tcp')

TCP_PORT = CONFIG['ue4_tcp']['port']
SEND_INTERVAL = 1.0 / CONFIG['ue4_tcp']['send_hz']

latest_raw = None
raw_lock = threading.Lock()
clients = []
clients_lock = threading.Lock()
server_running = True


def update_state(data: bytes):
    global latest_raw
    with raw_lock:
        latest_raw = data


def make_state_json(data: bytes) -> dict:
    s = parse_flight_state(data)
    return {
        "position": {"x": s['pos_x'], "y": s['pos_y'], "height": s['pos_z']},
        "velocity": {"vx": s['vel_x'], "vy": s['vel_y'], "vz": s['vel_z']},
        "status": "Flying"
    }


def broadcast_worker():
    logger.info(f"UE4 broadcast TCP {TCP_PORT}, {CONFIG['ue4_tcp']['send_hz']}Hz")
    while server_running:
        start = time.time()
        with raw_lock:
            raw = latest_raw
        if raw is None:
            time.sleep(SEND_INTERVAL)
            continue

        try:
            state = make_state_json(raw)
        except Exception:
            time.sleep(SEND_INTERVAL)
            continue

        msg = (json.dumps(state) + '\n').encode('utf-8')
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
            logger.info(f"UE4 client connected: {addr}, count: {len(clients)}")
        except socket.timeout:
            continue
        except Exception as e:
            if server_running:
                logger.error(f"TCP error: {e}")
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

if __name__ == '__main__':
    start_ue4_server()
