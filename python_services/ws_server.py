import asyncio
import json
import struct
import hashlib
import base64
import socket
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG

logger = get_logger('ws_server')

CMD_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
CMD_PORT = CONFIG['local_udp']['command_port']

_sim_status = 'unloaded'

# ---------- WebSocket Framing ----------


async def ws_send(writer, payload: str):
    data = payload.encode('utf-8')
    length = len(data)
    header = bytearray()
    header.append(0x81)  # FIN + text
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += struct.pack('>H', length)
    else:
        header.append(127)
        header += struct.pack('>Q', length)
    writer.write(bytes(header) + data)
    await writer.drain()


async def ws_recv(reader) -> str:
    hdr = await asyncio.wait_for(reader.readexactly(2), timeout=30.0)
    opcode = hdr[0] & 0x0F
    masked = hdr[1] & 0x80
    length = hdr[1] & 0x7F

    if length == 126:
        length = struct.unpack('>H', await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack('>Q', await reader.readexactly(8))[0]

    mask_key = await reader.readexactly(4) if masked else None
    payload = await reader.readexactly(length)

    if mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

    if opcode == 0x09:  # ping
        return '__PING__'
    if opcode == 0x08:  # close
        return '__CLOSE__'
    return payload.decode('utf-8')


def respond(seq, cmd, code, msg, data=None):
    frame = {'cmd': cmd, 'code': code, 'msg': msg, 'seq': seq}
    if data:
        frame['data'] = data
    return json.dumps(frame)


# ---------- Command Handlers ----------


async def handle_hello(req, seq, writer):
    src = req.get('params', {}).get('source', 'unknown')
    logger.info(f"hello from '{src}'")
    await ws_send(writer, respond(seq, 'hello', 0, 'ok', {'source': 'model'}))


async def handle_ping(seq, writer):
    await ws_send(writer, respond(seq, 'pong', 0, 'ok', {}))


async def handle_load_model(req, seq, writer):
    global _sim_status
    model_id = req.get('params', {}).get('model_id', '')
    model_name = req.get('params', {}).get('model_name', '')
    logger.info(f"load_model: id={model_id}, name={model_name}")
    _sim_status = 'loaded'
    await ws_send(writer, respond(seq, 'load_model', 0, 'success',
                                   {'status': 'loaded'}))


async def handle_start_sim(req, seq, writer):
    global _sim_status
    _sim_status = 'running'
    logger.info("start_sim: simulation started")
    await ws_send(writer, respond(seq, 'start_sim', 0, 'success',
                                   {'status': 'running', 'sim_time': 0.0}))


async def handle_stop_sim(seq, writer):
    global _sim_status
    _sim_status = 'stopped'
    logger.info("stop_sim")
    await ws_send(writer, respond(seq, 'stop_sim', 0, 'success',
                                   {'status': 'stopped'}))


async def handle_pause_sim(seq, writer):
    global _sim_status
    _sim_status = 'paused'
    logger.info("pause_sim")
    await ws_send(writer, respond(seq, 'pause_sim', 0, 'success',
                                   {'status': 'paused'}))


async def handle_resume_sim(seq, writer):
    global _sim_status
    _sim_status = 'running'
    logger.info("resume_sim")
    await ws_send(writer, respond(seq, 'resume_sim', 0, 'success',
                                   {'status': 'running'}))


async def handle_set_param(req, seq, writer):
    key = req.get('params', {}).get('key', '')
    value = req.get('params', {}).get('value', 0.0)
    payload = json.dumps({'cmd': 'tune', 'params': {key: value}})
    CMD_SOCK.sendto(payload.encode('utf-8'), ('127.0.0.1', CMD_PORT))
    logger.info(f"set_param: {key}={value}")
    await ws_send(writer, respond(seq, 'set_param', 0, 'success',
                                   {'status': 'ok'}))


async def handle_get_param(req, seq, writer):
    key = req.get('params', {}).get('key', '')
    await ws_send(writer, respond(seq, 'get_param', 0, 'success',
                                   {'key': key, 'value': 1.0}))


async def handle_get_status(seq, writer):
    await ws_send(writer, respond(seq, 'get_status', 0, 'success', {
        'model_status': _sim_status,
        'sim_time': state_cache.get_heartbeat()['sim_time'],
        'fps': 1000,
    }))


async def handle_get_state(req, seq, writer):
    s = state_cache.get_state_dict()
    if not s:
        await ws_send(writer, respond(seq, 'get_state', -2, 'no state'))
        return
    await ws_send(writer, respond(seq, 'get_state', 0, 'success', s))


def _forward_control(cmd, params):
    payload = json.dumps({'cmd': cmd, 'params': params})
    CMD_SOCK.sendto(payload.encode('utf-8'), ('127.0.0.1', CMD_PORT))


async def handle_control(cmd, req, seq, writer):
    params = req.get('params', {})
    _forward_control(cmd, params)
    status_map = {
        'takeoff': 'taking_off', 'land': 'landing',
        'hover': 'hovering', 'move_position': 'executing',
        'move_velocity': 'executing', 'goto_waypoint': 'executing',
        'set_mode': 'ok',
    }
    await ws_send(writer, respond(seq, cmd, 0, 'success',
                                   {'status': status_map.get(cmd, 'executing')}))


# ---------- Push Workers ----------


async def push_worker(connections: list):
    """10Hz flight_data + 1Hz sim_heartbeat to all connected clients."""
    counter = 0
    while True:
        await asyncio.sleep(0.1)
        counter += 1

        # flight_data @ 10Hz
        fd = state_cache.get_flight_data()
        if fd is not None and connections:
            msg = json.dumps({'cmd': 'flight_data', 'data': fd, 'seq': 0})
            dead = []
            for w in connections:
                try:
                    await ws_send(w, msg)
                except Exception:
                    dead.append(w)
            for d in dead:
                connections.remove(d)

        # sim_heartbeat @ 1Hz
        if counter % 10 == 0 and connections:
            hb = json.dumps(
                {'cmd': 'sim_heartbeat', 'data': state_cache.get_heartbeat(),
                 'seq': 0})
            dead = []
            for w in connections:
                try:
                    await ws_send(w, hb)
                except Exception:
                    dead.append(w)
            for d in dead:
                connections.remove(d)


# ---------- Main ----------


async def handle_client(reader, writer, connections):
    addr = writer.get_extra_info('peername')
    logger.info(f"WS connected: {addr}")

    try:
        ok = await asyncio.wait_for(ws_accept_inner(reader, writer), timeout=5.0)
    except Exception:
        writer.close()
        return

    if ok is None:
        writer.close()
        return

    connections.append(writer)

    while True:
        try:
            raw = await ws_recv(reader)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            break
        except Exception:
            break

        if raw == '__PING__':
            try:
                await ws_send(writer, '')  # pong via opcode
            except Exception:
                break
            continue
        if raw == '__CLOSE__':
            break

        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            await ws_send(writer, respond(0, '', -1, 'invalid json'))
            continue

        cmd = req.get('cmd', '')
        seq = req.get('seq', 0)
        addr_info = str(addr)

        try:
            if cmd == 'hello':
                await handle_hello(req, seq, writer)
            elif cmd == 'ping':
                await handle_ping(seq, writer)
            elif cmd == 'load_model':
                await handle_load_model(req, seq, writer)
            elif cmd == 'start_sim':
                await handle_start_sim(req, seq, writer)
            elif cmd == 'stop_sim':
                await handle_stop_sim(seq, writer)
            elif cmd == 'pause_sim':
                await handle_pause_sim(seq, writer)
            elif cmd == 'resume_sim':
                await handle_resume_sim(seq, writer)
            elif cmd == 'set_param':
                await handle_set_param(req, seq, writer)
            elif cmd == 'get_param':
                await handle_get_param(req, seq, writer)
            elif cmd == 'get_status':
                await handle_get_status(seq, writer)
            elif cmd == 'get_state':
                await handle_get_state(req, seq, writer)
            elif cmd in ('takeoff', 'land', 'hover', 'move_position',
                         'move_velocity', 'goto_waypoint', 'set_mode'):
                await handle_control(cmd, req, seq, writer)
            else:
                await ws_send(writer, respond(seq, cmd, -1, f'unknown cmd: {cmd}'))
        except Exception as e:
            logger.error(f"Handler error [{cmd}]: {e}")
            try:
                await ws_send(writer, respond(seq, cmd, -2, str(e)))
            except Exception:
                break

    connections.remove(writer)
    try:
        writer.close()
    except Exception:
        pass
    logger.info(f"WS disconnected: {addr}")


async def ws_accept_inner(reader, writer):
    data_str = (await asyncio.wait_for(reader.read(4096), timeout=5.0)).decode(
        'utf-8', errors='replace')
    key = None
    for line in data_str.split('\r\n'):
        if line.lower().startswith('sec-websocket-key:'):
            key = line.split(':', 1)[1].strip()
            break
    if not key:
        return None
    accept = base64.b64encode(
        hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode(
            'ascii')).digest()).decode('ascii')
    writer.write(
        ('HTTP/1.1 101 Switching Protocols\r\n'
         'Upgrade: websocket\r\n'
         'Connection: Upgrade\r\n'
         f'Sec-WebSocket-Accept: {accept}\r\n\r\n').encode('ascii'))
    await writer.drain()
    return accept


def start_ws_server():
    port = CONFIG['spring_boot']['websocket_port']
    connections = []
    logger.info(f"WebSocket server starting on ws://0.0.0.0:{port}/ws/hil")

    async def _run():
        server = await asyncio.start_server(
            lambda r, w: handle_client(r, w, connections), '0.0.0.0', port)
        asyncio.create_task(push_worker(connections))
        logger.info(f"WebSocket server listening on {port}")
        async with server:
            await server.serve_forever()

    asyncio.run(_run())
