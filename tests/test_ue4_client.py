#!/usr/bin/env python3
"""
UE4 Server Simulator — for testing HIL UE4 TCP client.
Listens on TCP 5000, accepts HIL connection, handshakes hello,
returns responses per protocol Ch.7, prints received messages.

Usage:
    python3 tests/test_ue4_client.py
"""
import socket
import json

HOST = '0.0.0.0'
PORT = 5000

print("UE4 Simulator listening on {}:{}".format(HOST, PORT))
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)

try:
    client, addr = server.accept()
    print("HIL connected: {}\n".format(addr))

    buf = b''
    state_count = 0
    cmd_count = 0

    while True:
        data = client.recv(4096)
        if not data:
            break
        buf += data
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            j = json.loads(line.decode('utf-8'))
            cmd = j.get('cmd', None)

            if cmd in ('takeoff', 'land', 'hover'):
                cmd_count += 1
                print("[CMD #{}] {} -> {}".format(cmd_count, cmd, json.dumps({'status': 'success'})))
                client.sendall((json.dumps({'status': 'success'}) + '\n').encode('utf-8'))

            elif cmd in ('move_position', 'move_velocity'):
                cmd_count += 1
                print("[CMD #{}] {} params={} -> {}".format(
                    cmd_count, cmd, j.get('params', {}),
                    json.dumps({'status': 'accepted'})))
                client.sendall((json.dumps({'status': 'accepted'}) + '\n').encode('utf-8'))

            elif cmd == 'get_state':
                cmd_count += 1
                # 返回模拟的 UE4 状态
                resp = {
                    'position': {'x': 0.0, 'y': 0.0, 'height': 50.0},
                    'velocity': {'vx': 0.0, 'vy': 0.0, 'vz': 0.0},
                    'landed_state': 'Flying',
                }
                print("[CMD #{}] get_state -> {}".format(cmd_count, json.dumps(resp)))
                client.sendall((json.dumps(resp) + '\n').encode('utf-8'))

            else:
                # 状态推送
                state_count += 1
                if state_count <= 3:
                    print("[STATE #{}] {}".format(state_count, json.dumps(j)))
                elif state_count == 4:
                    print("[STATE] ... (suppressing)")
                elif state_count % 100 == 0:
                    print("[STATE] ... {} total".format(state_count))

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    client.close()
    server.close()
