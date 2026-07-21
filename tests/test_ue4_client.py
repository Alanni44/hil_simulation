#!/usr/bin/env python3
"""
UE4 / Python Bridge Simulator — for testing HIL V2.0 bridge client.
Listens on TCP 5000, accepts HIL connection, returns ack per V2.0 protocol,
prints received messages.

Usage:
    python3 tests/test_ue4_client.py
"""
import socket
import json
import struct

HOST = '0.0.0.0'
PORT = 5000

print("UE4 Simulator (V2.0) listening on {}:{}".format(HOST, PORT))
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)


def frame_recv(sock, timeout=0.5):
    sock.settimeout(timeout)
    try:
        hdr = b''
        while len(hdr) < 4:
            chunk = sock.recv(4 - len(hdr))
            if not chunk:
                return None
            hdr += chunk
        length = struct.unpack('>I', hdr)[0]
        if length > 1048576:
            return None
        body = b''
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                return None
            body += chunk
        return json.loads(body.decode('utf-8'))
    except socket.timeout:
        return None
    except Exception as e:
        print("Frame recv error: {}".format(e))
        return None


def frame_send(sock, data):
    body = json.dumps(data).encode('utf-8')
    header = struct.pack('>I', len(body))
    sock.sendall(header + body)


try:
    client, addr = server.accept()
    print("HIL connected: {}\n".format(addr))

    state_count = 0
    event_count = 0

    while True:
        j = frame_recv(client, timeout=0.5)
        if j is None:
            continue

        mtype = j.get('type', '')

        if mtype == 'hello':
            print("[HELLO] role={} rate={}hz".format(
                j.get('data', {}).get('role', '?'),
                j.get('data', {}).get('state_rate_hz', '?')))
            frame_send(client, {
                'protocol_version': '2.0',
                'type': 'ack',
                'seq': 1,
                'vehicle_id': 'Drone1',
                'data': {
                    'ref_seq': j.get('seq', 0),
                    'ref_type': 'hello',
                    'accepted': True,
                }
            })

        elif mtype == 'mission_plan':
            wps = j.get('data', {}).get('waypoints', [])
            mid = j.get('data', {}).get('mission_id', '?')
            print("[MISSION_PLAN] mission={} waypoints={}".format(mid, len(wps)))
            for wp in wps:
                print("  {}: x={:.1f} y={:.1f} h={:.1f} spd={:.1f}".format(
                    wp.get('id', '?'), wp.get('x', 0), wp.get('y', 0),
                    wp.get('height', 0), wp.get('target_speed', 0)))
            frame_send(client, {
                'protocol_version': '2.0',
                'type': 'ack',
                'seq': j.get('seq', 0) + 1,
                'vehicle_id': 'Drone1',
                'data': {
                    'ref_seq': j.get('seq', 0),
                    'ref_type': 'mission_plan',
                    'accepted': True,
                }
            })

        elif mtype == 'vehicle_state':
            state_count += 1
            d = j.get('data', {})
            if state_count <= 3:
                pos = d.get('position', {})
                att = d.get('attitude', {})
                print("[STATE #{:d}] sim_time={:.2f} pos=({:.1f},{:.1f},{:.1f}) "
                      "att=({:.2f},{:.2f},{:.2f}) fs={}".format(
                          state_count, d.get('sim_time', 0),
                          pos.get('x', 0), pos.get('y', 0), pos.get('height', 0),
                          att.get('roll', 0), att.get('pitch', 0), att.get('yaw', 0),
                          d.get('flight_state', '?')))
            elif state_count == 4:
                print("[STATE] ... (suppressing)")
            elif state_count % 100 == 0:
                print("[STATE] ... {} total".format(state_count))

        elif mtype == 'simulation_event':
            event_count += 1
            ev = j.get('data', {}).get('event', '?')
            print("[EVENT #{:d}] {}".format(event_count, ev))
            frame_send(client, {
                'protocol_version': '2.0',
                'type': 'ack',
                'seq': j.get('seq', 0) + 1,
                'vehicle_id': 'Drone1',
                'data': {
                    'ref_seq': j.get('seq', 0),
                    'ref_type': 'simulation_event',
                    'accepted': True,
                }
            })

        else:
            print("[UNKNOWN] type={} seq={}".format(mtype, j.get('seq', 0)))

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    client.close()
    server.close()
