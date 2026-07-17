#!/usr/bin/env python3
import socket
import json
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('cmd_server')
cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
CMD_PORT = CONFIG['local_udp']['command_port']

VALID_CMDS = {'INIT', 'takeoff', 'land', 'hover', 'move_position', 'move_velocity',
              'get_state', 'TUNE'}

def start_init_server():
    port = CONFIG['tcp_services']['init_port']
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(5)
    logger.info(f"Command server listening on TCP {port}")

    while True:
        try:
            client, addr = server.accept()
            data = client.recv(4096)
            if data:
                try:
                    req = json.loads(data.decode('utf-8'))
                    cmd = req.get('cmd', '')
                    if cmd in VALID_CMDS:
                        cmd_sock.sendto(data, ('127.0.0.1', CMD_PORT))
                        client.send(b'{"code":0,"msg":"OK"}')
                        logger.info(f"Cmd '{cmd}' from {addr}")
                    else:
                        client.send(b'{"code":-1,"msg":"Unknown command"}')
                except json.JSONDecodeError:
                    client.send(b'{"code":-1,"msg":"Invalid JSON"}')
            client.close()
        except Exception as e:
            logger.error(f"Cmd error: {e}")

if __name__ == '__main__':
    start_init_server()
