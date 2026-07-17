#!/usr/bin/env python3
import socket
import json
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('init_server')
cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
CMD_PORT = CONFIG['local_udp']['command_port']

def start_init_server():
    port = CONFIG['tcp_services']['init_port']
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(5)
    logger.info(f"Init server listening on {port}")

    while True:
        try:
            client, addr = server.accept()
            data = client.recv(4096)
            if data:
                try:
                    json.loads(data.decode('utf-8'))
                    cmd_sock.sendto(data, ('127.0.0.1', CMD_PORT))
                    client.send(b'{"code":0,"msg":"INIT_FORWARDED"}')
                    logger.info(f"Init from {addr}")
                except json.JSONDecodeError:
                    client.send(b'{"code":-1,"msg":"Invalid JSON"}')
            client.close()
        except Exception as e:
            logger.error(f"Init error: {e}")

if __name__ == '__main__':
    start_init_server()