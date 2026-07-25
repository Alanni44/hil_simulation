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
import contextlib
import json
import struct
import base64
import datetime
import fcntl
import hashlib
import os
import re
import shutil
import socket
import secrets
import tempfile
import urllib.parse
import urllib.request
import subprocess
from shared.logger import get_logger
from shared import state_cache
from config_loader import CONFIG
import bridge_tcp_client as bridge

logger = get_logger('ws_v2')

CMD_HOST = '127.0.0.1'
CMD_PORT = CONFIG['local_udp']['command_port']
# Create this lazily: archive tooling and unit tests must not need network
# namespace permission merely to inspect or build a model.
CMD_SOCK = None

_ref_lat = 39.9
_ref_lon = 116.4

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_STORE = os.path.join(PROJECT_ROOT, 'models')
MODEL_READY_SIGNAL = os.environ.get('HIL_MODEL_READY_SIGNAL', '/tmp/model_ready.signal')
MODEL_READY_DIR = os.environ.get('HIL_MODEL_READY_DIR', '')
MODEL_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
REMOTE_MODEL_ADMIN_ENABLED = os.environ.get('HIL_ENABLE_REMOTE_MODEL_ADMIN', '0') == '1'
MODEL_DOWNLOAD_ALLOWLIST = frozenset(
    host.strip().lower() for host in
    os.environ.get('HIL_MODEL_DOWNLOAD_ALLOWLIST', '').split(',') if host.strip())
MODEL_DOWNLOAD_MAX_BYTES = int(os.environ.get('HIL_MODEL_DOWNLOAD_MAX_BYTES',
                                               str(100 * 1024 * 1024)))


# ---------- WebSocket Framing ----------

async def ws_pong(writer, data: bytes):
    """Send a WebSocket Pong frame (opcode 0xA) — no mask from server."""
    length = len(data)
    header = bytearray()
    header.append(0x8A)  # FIN + Pong opcode
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
    global CMD_SOCK
    try:
        if CMD_SOCK is None:
            CMD_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = json.dumps(cmd_dict).encode('utf-8')
        CMD_SOCK.sendto(payload, (CMD_HOST, CMD_PORT))
        logger.info("UDP -> C Core: {}".format(cmd_dict.get('cmd', '?')))
    except Exception as e:
        logger.error("UDP send failed: {}".format(e))


# ---------- MATLAB Builder ----------

def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path, data):
    temp_path = '{}.{}.tmp'.format(path, secrets.token_hex(4))
    with open(temp_path, 'w') as output:
        json.dump(data, output, indent=2, sort_keys=True)
        output.write('\n')
    os.replace(temp_path, path)


def _ready_signal_path(model_name):
    """Return the model-specific handoff path in production deployments.

    A legacy single signal remains available for local development.  Production
    must set HIL_MODEL_READY_DIR so independent hil-core@<model> instances do
    not consume each other's activation notifications.
    """
    if MODEL_READY_DIR:
        return os.path.join(MODEL_READY_DIR, model_name + '.signal')
    return MODEL_READY_SIGNAL


def _remote_model_admin_error():
    if not REMOTE_MODEL_ADMIN_ENABLED:
        return ('Remote model administration is disabled. Set '
                'HIL_ENABLE_REMOTE_MODEL_ADMIN=1 only behind an authenticated '
                'management boundary.')
    return None


def _download_slx(url, destination):
    """Download a bounded, allowlisted SLX archive for an authorized build."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or not host:
        raise ValueError('Model URL must use http or https and include a host')
    if not MODEL_DOWNLOAD_ALLOWLIST:
        raise ValueError('HIL_MODEL_DOWNLOAD_ALLOWLIST is required for remote model download')
    if host not in MODEL_DOWNLOAD_ALLOWLIST:
        raise ValueError('Model download host is not allowlisted')
    if MODEL_DOWNLOAD_MAX_BYTES <= 0:
        raise ValueError('HIL_MODEL_DOWNLOAD_MAX_BYTES must be positive')

    request = urllib.request.Request(url, headers={'User-Agent': 'hil-model-builder/2'})
    total = 0
    with urllib.request.urlopen(request, timeout=30) as response:
        with open(destination, 'wb') as output:
            while True:
                block = response.read(min(1024 * 1024, MODEL_DOWNLOAD_MAX_BYTES - total + 1))
                if not block:
                    break
                total += len(block)
                if total > MODEL_DOWNLOAD_MAX_BYTES:
                    raise ValueError('Model download exceeds configured size limit')
                output.write(block)
    if total == 0:
        raise ValueError('Model download is empty')


@contextlib.contextmanager
def _model_lock(model_name):
    lock_dir = os.path.join(MODEL_STORE, 'locks')
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, model_name + '.lock')
    with open(lock_path, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _command_version(command):
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT,
                                         universal_newlines=True)
        return output.splitlines()[0] if output else ''
    except Exception:
        return ''


def _git_revision():
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL, universal_newlines=True).strip()
    except Exception:
        return ''


def _git_is_dirty():
    try:
        return bool(subprocess.check_output(
            ['git', 'status', '--porcelain'], cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL, universal_newlines=True).strip())
    except Exception:
        return None


def _source_tree_sha256(relative_dir):
    """Fingerprint the builder inputs used to produce an archived binary."""
    root = os.path.join(PROJECT_ROOT, relative_dir)
    digest = hashlib.sha256()
    for directory, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            path = os.path.join(directory, filename)
            relative_path = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, '/')
            digest.update(relative_path.encode('utf-8'))
            digest.update(b'\0')
            with open(path, 'rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            digest.update(b'\0')
    return digest.hexdigest()


def _publish_active_model(model_name, build_dir, executable_path):
    active_dir = os.path.join(MODEL_STORE, 'active')
    os.makedirs(active_dir, exist_ok=True)
    active_link = os.path.join(active_dir, model_name)
    temp_link = '{}.{}.tmp'.format(active_link, secrets.token_hex(4))
    os.symlink(os.path.relpath(build_dir, active_dir), temp_link)
    try:
        os.replace(temp_link, active_link)
    except Exception:
        try:
            os.unlink(temp_link)
        except OSError:
            pass
        raise

    # Compatibility signal for the existing core hot-reload watcher.  Publish
    # it only after the active symlink was atomically updated.
    _write_json_atomic(_ready_signal_path(model_name), {
        'build_id': os.path.basename(build_dir),
        'exe_path': executable_path,
        'model_name': model_name,
    })


def _activate_archived_build(model_name, build_id):
    if not MODEL_NAME_RE.match(model_name or ''):
        raise ValueError('Invalid model_name')
    if not re.match(r'^[A-Za-z0-9_]+$', build_id or ''):
        raise ValueError('Invalid build_id')

    build_dir = os.path.join(MODEL_STORE, 'registry', model_name, build_id)
    manifest_path = os.path.join(build_dir, 'manifest.json')
    if not os.path.isfile(manifest_path):
        raise ValueError('Build manifest not found')
    with open(manifest_path, 'r') as manifest_handle:
        manifest = json.load(manifest_handle)
    if manifest.get('status') != 'succeeded':
        raise ValueError('Only succeeded builds can be activated')
    executable = manifest.get('executable', {})
    executable_path = os.path.realpath(os.path.join(build_dir, executable.get('path', '')))
    expected_root = os.path.realpath(build_dir) + os.sep
    if not executable_path.startswith(expected_root) or not os.path.isfile(executable_path):
        raise ValueError('Archived executable is missing or outside its build directory')
    if executable.get('sha256') != _sha256_file(executable_path):
        raise ValueError('Archived executable checksum mismatch')

    with _model_lock(model_name):
        _publish_active_model(model_name, build_dir, executable_path)
    return executable_path


def _list_archived_builds(model_name):
    if not MODEL_NAME_RE.match(model_name or ''):
        raise ValueError('Invalid model_name')
    registry_dir = os.path.join(MODEL_STORE, 'registry', model_name)
    if not os.path.isdir(registry_dir):
        return []
    builds = []
    for build_id in sorted(os.listdir(registry_dir), reverse=True):
        manifest_path = os.path.join(registry_dir, build_id, 'manifest.json')
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, 'r') as manifest_handle:
                manifest = json.load(manifest_handle)
            builds.append({
                'build_id': build_id,
                'created_at': manifest.get('created_at'),
                'completed_at': manifest.get('completed_at'),
                'source_sha256': manifest.get('source', {}).get('sha256'),
                'status': manifest.get('status'),
            })
        except (ValueError, IOError):
            logger.warning('Ignoring unreadable build manifest: {}'.format(manifest_path))
    return builds


def build_model_from_slx(slx_path, model_name):
    if not MODEL_NAME_RE.match(model_name or ''):
        return (False, 'model_name must match {}'.format(MODEL_NAME_RE.pattern), None, None)
    if not os.path.isfile(slx_path):
        return (False, 'SLX file does not exist', None, None)

    matlab_bin = None
    for candidate in [
        '/usr/local/MATLAB/R2018b/bin/matlab',
        '/usr/local/bin/matlab',
    ]:
        if os.path.exists(candidate):
            matlab_bin = candidate
            break
    if not matlab_bin:
        return (False, 'MATLAB not found on this machine', None, None)

    script_dir = os.path.join(PROJECT_ROOT, 'matlab_scripts')
    build_script = os.path.join(script_dir, 'build_script.m')
    if not os.path.exists(build_script):
        return (False, 'build_script.m not found', None, None)

    source_sha256 = _sha256_file(slx_path)
    created_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    build_id = '{}_{}_{}'.format(
        datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'),
        source_sha256[:12], secrets.token_hex(4))
    model_root = os.path.join(MODEL_STORE, 'registry', model_name)
    os.makedirs(model_root, exist_ok=True)
    with _model_lock(model_name):
        build_dir = os.path.join(model_root, build_id)
        source_dir = os.path.join(build_dir, 'source')
        artifact_dir = os.path.join(build_dir, 'artifacts')
        executable_dir = os.path.join(build_dir, 'executable')
        log_dir = os.path.join(build_dir, 'logs')
        os.makedirs(source_dir)
        os.makedirs(artifact_dir)
        os.makedirs(executable_dir)
        os.makedirs(log_dir)

        archived_slx = os.path.join(source_dir, model_name + '.slx')
        shutil.copy2(slx_path, archived_slx)
        task_file = os.path.join(build_dir, 'build_task.json')
        result_file = os.path.join(build_dir, 'build_result.json')
        build_log = os.path.join(log_dir, 'matlab_build.log')
        task = {
            'model_name': model_name,
            'slx_path': archived_slx,
            'output_dir': artifact_dir,
            'executable_dir': executable_dir,
            'lib_name': 'lib' + model_name,
        }
        _write_json_atomic(task_file, task)
        manifest = {
            'schema_version': 1,
            'build_id': build_id,
            'created_at': created_at,
            'model_name': model_name,
            'source': {
                'path': os.path.relpath(archived_slx, build_dir),
                'sha256': source_sha256,
            },
            'status': 'building',
            'task': task,
            'toolchain': {
                'gcc': _command_version(['gcc', '--version']),
                'git_revision': _git_revision(),
                'git_dirty': _git_is_dirty(),
                'matlab_executable': matlab_bin,
            },
            'build_context': {
                'c_core_src_sha256': _source_tree_sha256('c_core/src'),
                'matlab_scripts_sha256': _source_tree_sha256('matlab_scripts'),
            },
        }
        manifest_file = os.path.join(build_dir, 'manifest.json')
        _write_json_atomic(manifest_file, manifest)

        try:
            cmd = [
                matlab_bin,
                '-nodisplay', '-nosplash', '-nodesktop',
                '-r',
                "addpath('{}');build_script('{}','{}');exit;".format(
                    script_dir, task_file, result_file)
            ]
            logger.info("Running MATLAB build {} for model {}".format(build_id, model_name))
            with open(build_log, 'w') as output:
                proc = subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT,
                                      universal_newlines=True, timeout=300)
            if proc.returncode != 0:
                raise RuntimeError('MATLAB exited with status {}'.format(proc.returncode))
        except subprocess.TimeoutExpired:
            manifest['status'] = 'failed'
            manifest['error'] = 'MATLAB build timed out (5 min)'
            _write_json_atomic(manifest_file, manifest)
            return (False, manifest['error'], None, build_id)
        except Exception as e:
            manifest['status'] = 'failed'
            manifest['error'] = 'MATLAB execution failed: {}'.format(e)
            _write_json_atomic(manifest_file, manifest)
            return (False, manifest['error'], None, build_id)

        if not os.path.exists(result_file):
            manifest['status'] = 'failed'
            manifest['error'] = 'MATLAB did not produce result file'
            _write_json_atomic(manifest_file, manifest)
            return (False, manifest['error'], None, build_id)
        try:
            with open(result_file, 'r') as result_handle:
                result = json.load(result_handle)
        except (ValueError, IOError) as e:
            manifest['status'] = 'failed'
            manifest['error'] = 'Invalid result JSON from MATLAB: {}'.format(e)
            _write_json_atomic(manifest_file, manifest)
            return (False, manifest['error'], None, build_id)

        if result.get('code') != 0:
            manifest['status'] = 'failed'
            manifest['error'] = result.get('message', 'Build failed')
            manifest['result'] = result
            _write_json_atomic(manifest_file, manifest)
            return (False, manifest['error'], None, build_id)

        exe_path = result.get('exe_path')
        if not exe_path or not os.path.isfile(exe_path):
            manifest['status'] = 'failed'
            manifest['error'] = 'Executable not found'
            _write_json_atomic(manifest_file, manifest)
            return (False, manifest['error'], None, build_id)

        os.chmod(exe_path, 0o755)
        manifest['status'] = 'succeeded'
        manifest['completed_at'] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
        manifest['result'] = result
        manifest['executable'] = {
            'path': os.path.relpath(exe_path, build_dir),
            'sha256': _sha256_file(exe_path),
        }
        _write_json_atomic(manifest_file, manifest)
        _publish_active_model(model_name, build_dir, exe_path)
        logger.info("Model executable ready: {} (build {})".format(exe_path, build_id))
        return (True, 'Build successful', exe_path, build_id)


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
    admin_error = _remote_model_admin_error()
    if admin_error:
        await ws_send(writer, json.dumps({'status': 'error', 'message': admin_error}))
        return
    url = params.get('url', '')
    model_name = params.get('model_name', '')
    if not url or not model_name:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'Missing url or model_name'}))
        return
    if not MODEL_NAME_RE.match(model_name):
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'Invalid model_name'}))
        return

    temp_handle = tempfile.NamedTemporaryFile(prefix='hil_model_', suffix='.slx', delete=False)
    local_path = temp_handle.name
    temp_handle.close()
    try:
        _download_slx(url, local_path)
        logger.info("Downloaded {} ({} bytes)".format(
            model_name, os.path.getsize(local_path)))
    except Exception as e:
        try:
            os.remove(local_path)
        except OSError:
            pass
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': 'Download failed: {}'.format(e)}))
        return

    success, msg, exe_path, build_id = build_model_from_slx(local_path, model_name)
    try:
        os.remove(local_path)
    except OSError:
        pass

    if success:
        await ws_send(writer, json.dumps(
            {'status': 'success', 'message': msg, 'exe_path': exe_path,
             'build_id': build_id,
             'active_path': os.path.join(MODEL_STORE, 'active', model_name)}))
    else:
        await ws_send(writer, json.dumps(
            {'status': 'error', 'message': msg, 'build_id': build_id}))


async def handle_list_model_builds(params, writer):
    admin_error = _remote_model_admin_error()
    if admin_error:
        await ws_send(writer, json.dumps({'status': 'error', 'message': admin_error}))
        return
    model_name = params.get('model_name', '')
    try:
        builds = _list_archived_builds(model_name)
    except ValueError as exc:
        await ws_send(writer, json.dumps({'status': 'error', 'message': str(exc)}))
        return
    await ws_send(writer, json.dumps({
        'status': 'success', 'model_name': model_name, 'builds': builds,
    }))


async def handle_activate_model_build(params, writer):
    admin_error = _remote_model_admin_error()
    if admin_error:
        await ws_send(writer, json.dumps({'status': 'error', 'message': admin_error}))
        return
    model_name = params.get('model_name', '')
    build_id = params.get('build_id', '')
    try:
        executable_path = _activate_archived_build(model_name, build_id)
    except (ValueError, IOError) as exc:
        await ws_send(writer, json.dumps({'status': 'error', 'message': str(exc)}))
        return
    logger.info('Activated model {} build {}'.format(model_name, build_id))
    await ws_send(writer, json.dumps({
        'status': 'success', 'model_name': model_name,
        'build_id': build_id, 'exe_path': executable_path,
    }))


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
                await ws_pong(writer, b'')
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
            elif cmd == 'list_model_builds':
                await handle_list_model_builds(req.get('params', {}), writer)
            elif cmd == 'activate_model_build':
                await handle_activate_model_build(req.get('params', {}), writer)
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
