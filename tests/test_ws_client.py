#!/usr/bin/env python3
"""
V2.0 protocol demo client — connects to HIL WebSocket and sends V2.0 commands.
For debugging the Spring Boot <-> HIL protocol.

Usage:
    python3 tests/test_ws_client.py [host] [port]
    Default: 192.168.100.138:8080
"""
import asyncio
import json
import struct
import base64
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else '192.168.100.138'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080


async def ws_handshake(reader, writer):
    key = base64.b64encode(b'0123456789abcdef').decode('ascii')
    req = (
        "GET /ws/hil HTTP/1.1\r\n"
        "Host: {}:{}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: {}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).format(HOST, PORT, key)
    writer.write(req.encode('ascii'))
    await writer.drain()
    resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
    if b'101' not in resp:
        print("HANDSHAKE FAILED:\n{}".format(resp.decode(errors='replace')))
        return False
    return True


async def ws_send(writer, payload):
    data = payload.encode('utf-8')
    n = len(data)
    h = bytearray()
    h.append(0x81)
    if n < 126:
        h.append(0x80 | n)
    elif n < 65536:
        h.append(0x80 | 126)
        h += struct.pack('>H', n)
    else:
        h.append(0x80 | 127)
        h += struct.pack('>Q', n)
    mask = b'\x12\x34\x56\x78'
    h += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    writer.write(bytes(h) + masked)
    await writer.drain()


async def ws_recv(reader):
    hdr = await asyncio.wait_for(reader.readexactly(2), timeout=30.0)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack('>H', await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack('>Q', await reader.readexactly(8))[0]
    payload = await reader.readexactly(length)
    return payload.decode('utf-8')


async def send_cmd(writer, cmd, params=None):
    msg = {'cmd': cmd}
    if params is not None:
        msg['params'] = params
    print('\n>>> {}'.format(json.dumps(msg)))
    await ws_send(writer, json.dumps(msg))


async def main():
    print("Connecting to ws://{}:{} ...".format(HOST, PORT))
    reader, writer = await asyncio.open_connection(HOST, PORT)
    if not await ws_handshake(reader, writer):
        writer.close()
        return
    print("WebSocket connected!")

    async def reader_task():
        while True:
            try:
                r = await ws_recv(reader)
                j = json.loads(r)
                print('<<< {}'.format(json.dumps(j, indent=2)))
            except Exception:
                break

    asyncio.ensure_future(reader_task())
    await asyncio.sleep(0.3)

    print('\n===== V2.0 Demo sequence =====')
    # init_sim
    await send_cmd(writer, 'init_sim', {
        'initial_lat': 39.90, 'initial_lon': 116.40,
        'initial_alt': 50, 'initial_roll': 0, 'initial_pitch': 0, 'initial_yaw': 0,
        'min_speed': 0, 'max_speed': 30, 'min_height': 10, 'max_height': 500,
    })
    await asyncio.sleep(0.3)

    # load_mission
    await send_cmd(writer, 'load_mission', {
        'mission_id': 'mission_001',
        'waypoints': [
            {'lat': 39.90, 'lon': 116.40, 'height': 30, 'speed': 5},
            {'lat': 39.91, 'lon': 116.41, 'height': 40, 'speed': 5},
            {'lat': 39.92, 'lon': 116.42, 'height': 30, 'speed': 3},
        ]
    })
    await asyncio.sleep(0.5)

    # tune
    await send_cmd(writer, 'tune', {'throttle': 80, 'flight_mode': 0})
    await asyncio.sleep(0.3)

    # get_state
    await send_cmd(writer, 'get_state')
    await asyncio.sleep(0.3)

    # lifecycle events
    await send_cmd(writer, 'pause')
    await asyncio.sleep(0.2)
    await send_cmd(writer, 'resume')
    await asyncio.sleep(0.2)

    await send_cmd(writer, 'mission_end', {'mission_id': 'mission_001'})
    await asyncio.sleep(0.3)

    print('\n===== Done =====')
    writer.close()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
