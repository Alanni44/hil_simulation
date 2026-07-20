"""
HIL WebSocket Server — V2.0 协议
WebSocket 客户端连接后端，接收命令转发到 C Core
TCP V2.0 由 bridge_tcp_client.py 独立处理
支持的命令:
  load_mission — 航点任务
  init_sim     — 初始化仿真
  tune         — 实时调参
  simulation control — pause/resume/reset_scene/mission_end
"""
import asyncio
import json
import struct
import base64
import os
import socket
import secrets
import urllib.request
import tempfile
import subprocess
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG
import bridge_tcp_client as bridge

logger = get_logger('ws_v2')

CMD_HOST = '127.0.0.1'
CMD_PORT = CONFIG['local_udp']['command_port']
CMD_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

_ref_lat = 39.9
_ref_lon = 116.4


# ---------- WebSocket Framing ----------

async def ws_send(writer, payload: str):
    data = payload.encode('utf-8')
    length = len(data)
    header = bytearray()
    header.append(0x81)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack('>H', length)
    else:
        header.append(0x80 | 127)
        header += struct.pack('>Q', length)
    mask = secrets.token_bytes(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    writer.write(bytes(header) + mask + masked)
    await writer.drain()


async def ws_recv(reader) -> str:
    hdr = await asyncio.wait_for(reader.readexactly(2), timeout=30.0)
    opcode = hdr[0] & 0x0F
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack('>H', await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack('>Q', await reader.readexactly(8))[0]
    payload = await reader.readexactly(length)
    if opcode == 0x09:
        return '__PING__'
    if opcode == 0x08:
        return '__CLOSE__'
    return payload.decode('utf-8')


# ---------- C Core UDP ----------

def _send_to_core(cmd_dict):
    try:
        payload = json.dumps(cmd_dict).encode('utf-8')
        CMD_SOCK.sendto(payload, (CMD_HOST, CMD_PORT))
        logger.info("UDP -> C Core: {}".format(cmd_dict.get('cmd', '?')))
    except Exception as e:
        logger.error("UDP send failed: {}".format(e))


# ---------- MATLAB Builder ----------

def build_model_from_slx(slx_path, model_name):
    matlab_bin = None
    for candidate in [
        '/usr/local/MATLAB/R2018b/bin/matlab',
        '/usr/local/bin/matlab',
    ]:
        if os.path.exists(candidate):
            matlab_bin = candidate
            break
    if not matlab_bin:
        return (False, 'MATLAB not found on this machine', None)

    script_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'matlab_scripts')
    build_script = os.path.join(script_dir, 'build_script.m')
    if not os.path.exists(build_script):
        return (False, 'build_script.m not found', None)

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'models', 'builds', model_name)
    os.makedirs(output_dir, exist_ok=True)

    task_file = os.path.join(output_dir, 'build_task.json')
    result_file = os.path.join(output_dir, 'build_result.json')

    with open(task_file, 'w') as f:
        json.dump({
            'model_name': model_name,
            'slx_path': slx_path,
            'output_dir': output_dir,
            'lib_name': 'lib' + model_name,
        }, f)

    try:
        cmd = [
            matlab_bin,
            '-nodisplay', '-nosplash', '-nodesktop',
            '-r',
            "addpath('{}');build_script('{}','{}');exit;".format(
                script_dir, task_file, result_file)
        ]
        logger.info("Running MATLAB...")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            logger.error("MATLAB stderr: {}".format(proc.stderr[-500:] if proc.stderr else ''))
    except subprocess.TimeoutExpired:
        return (False, 'MATLAB build timed out (5 min)', None)
    except Exception as e:
        return (False, 'MATLAB execution failed: {}'.format(e), None)

    if not os.path.exists(result_file):
        return (False, 'MATLAB did not produce result file', None)

    try:
        with open(result_file, 'r') as f:
            result = json.load(f)
    except json.JSONDecodeError:
        return (False, 'Invalid result JSON from MATLAB', None)

    if result.get('code') != 0:
        return (False, result.get('message', 'Build failed'), None)

    exe_path = result.get('exe_path')
    if not exe_path or not os.path.exists(exe_path):
        return (False, 'Executable not found', None)

    os.chmod(exe_path, 0o755)

    with open('/tmp/model_ready.signal', 'w') as f:
        json.dump({'exe_path': exe_path, 'model_name': model_name}, f)

    logger.info("Model executable ready: {}".format(exe_path))
    return (True, 'Build successful', exe_path)


# ---------- Command Handlers ----------

async def handle_load_mission(params, writer):
    """后端发航点(lat,lon) → C Core(原样) + bridge(x/y)"""
    mission_id = params.get('mission_id', 'mission_001')
    waypoints = params.get('waypoints', [])

    if not waypoints:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'no waypoints'}))
        return

    # 发给 C Core 执行航点飞行（经纬度原样，C Core 内部转换）
    _send_to_core({'cmd': 'load_mission', 'params': {
        'mission_id': mission_id,
        'waypoints': waypoints,
    }})

    # 给 bridge 发送 mission_plan（需转换为 x/y 坐标）
    if bridge.is_connected():
        xy_waypoints = []
        for wp in waypoints:
            lat = wp.get('lat', _ref_lat)
            lon = wp.get('lon', _ref_lon)
            xy_waypoints.append({
                'x': (lon - _ref_lon) / 0.00001,
                'y': (lat - _ref_lat) / 0.00001,
                'height': wp.get('height', 50),
                'speed': wp.get('speed', 5),
            })
        bridge.send_mission_plan(mission_id, xy_waypoints)

    logger.info("load_mission: {} waypoints".format(len(waypoints)))
    await ws_send(writer, json.dumps({'status': 'accepted'}))


async def handle_init_sim(params, writer):
    global _ref_lat, _ref_lon
    if 'initial_lat' in params:
        _ref_lat = params['initial_lat']
    if 'initial_lon' in params:
        _ref_lon = params['initial_lon']
    _send_to_core({'cmd': 'init_sim', 'params': params})
    await ws_send(writer, json.dumps({'status': 'accepted'}))


async def handle_tune(params, writer):
    _send_to_core({'cmd': 'tune', 'params': params})
    await ws_send(writer, json.dumps({'status': 'accepted'}))


async def handle_load_model(params, writer):
    url = params.get('url', '')
    model_name = params.get('model_name', '')
    if not url or not model_name:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'Missing url or model_name'}))
        return

    local_path = os.path.join(tempfile.gettempdir(), model_name + '.slx')
    try:
        urllib.request.urlretrieve(url, local_path)
        logger.info("Downloaded {} ({} bytes)".format(
            model_name, os.path.getsize(local_path)))
    except Exception as e:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'Download failed: {}'.format(e)}))
        return

    success, msg, exe_path = build_model_from_slx(local_path, model_name)
    try:
        os.remove(local_path)
    except OSError:
        pass

    if success:
        await ws_send(writer, json.dumps(
            {'status': 'success', 'message': msg, 'exe_path': exe_path}))
    else:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': msg}))


async def handle_simulation_event(event, params, writer):
    """暂停/恢复/重置/结束 → C Core + bridge simulation_event"""
    _send_to_core({'cmd': 'simulation_event', 'params': {
        'event': event,
        'mission_id': params.get('mission_id', ''),
    }})

    if bridge.is_connected():
        bridge.send_simulation_event(event, params.get('mission_id', ''))

    await ws_send(writer, json.dumps({'status': 'accepted'}))


async def handle_get_state(writer):
    s = state_cache.get_state_dict()
    if not s:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'no state available'}))
        return
    await ws_send(writer, json.dumps(s))


# ---------- Main Client ----------

async def command_loop(reader, writer):
    while True:
        try:
            raw = await ws_recv(reader)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            break
        except Exception:
            break

        if raw == '__PING__':
            try:
                await ws_send(writer, '')
            except Exception:
                break
            continue
        if raw == '__CLOSE__':
            break

        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            await ws_send(writer, json.dumps(
                {'status': 'error', 'message': 'invalid JSON'}))
            continue

        cmd = req.get('cmd', '')
        logger.info("WS recv: {}".format(cmd))

        try:
            # V2.0 命令
            if cmd == 'load_mission':
                await handle_load_mission(req.get('params', {}), writer)
            elif cmd == 'init_sim':
                await handle_init_sim(req.get('params', {}), writer)
            elif cmd == 'tune':
                await handle_tune(req.get('params', {}), writer)
            elif cmd == 'load_model':
                await handle_load_model(req.get('params', {}), writer)
            elif cmd in ('pause', 'resume', 'reset_scene', 'mission_end'):
                await handle_simulation_event(
                    cmd, req.get('params', {}), writer)
            elif cmd == 'get_state':
                await handle_get_state(writer)
            else:
                await ws_send(writer, json.dumps(
                    {'status': 'error',
                     'message': 'unknown cmd: {}'.format(cmd)}))

        except Exception as e:
            logger.error("Handler error [{}]: {}".format(cmd, e))
            try:
                await ws_send(writer, json.dumps(
                    {'status': 'error', 'message': str(e)}))
            except Exception:
                break


def start_ws_server():
    host = CONFIG['spring_boot'].get('host', '127.0.0.1')
    port = CONFIG['spring_boot']['websocket_port']
    path = CONFIG['spring_boot'].get('path', '/ws/hil')
    logger.info("WebSocket V2.0 -> ws://{}:{}{}".format(host, port, path))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_client():
        while True:
            try:
                reader, writer = await asyncio.open_connection(host, port)

                key = base64.b64encode(secrets.token_bytes(16)).decode('ascii')
                writer.write(
                    "GET {} HTTP/1.1\r\n"
                    "Host: {}:{}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Key: {}\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    "\r\n"
                    .format(path, host, port, key).encode('ascii'))
                await writer.drain()

                resp = (await asyncio.wait_for(
                    reader.read(4096), timeout=5.0)).decode('utf-8')
                if '101' not in resp:
                    logger.error(
                        "WebSocket handshake failed: {}".format(resp))
                    writer.close()
                    await asyncio.sleep(3)
                    continue

                logger.info("Connected to ws://{}:{}{}".format(
                    host, port, path))

                await command_loop(reader, writer)

                writer.close()
                logger.info("Disconnected, reconnecting in 3s...")
            except (ConnectionRefusedError, OSError) as e:
                logger.warning(
                    "{}:{} unreachable: {}, retrying in 3s...".format(
                        host, port, e))
            except Exception as e:
                logger.error("Connection error: {}".format(e))
            await asyncio.sleep(3)

    loop.run_until_complete(run_client())
