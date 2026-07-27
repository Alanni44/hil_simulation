#!/usr/bin/env python3
"""HIL execution boundary: local verified packages and C-core receipts only."""
from __future__ import print_function

import asyncio
import base64
import datetime
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile

from config_loader import CONFIG
from shared import state_cache
from shared.logger import get_logger
from shared.model_package import PackageError, sha256_file, validate_package
import bridge_tcp_client as bridge

logger = get_logger('ws_v2')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLED_PACKAGE_ROOT = os.environ.get('HIL_CONTROLLED_PACKAGE_ROOT',
                                         os.path.join(PROJECT_ROOT, 'packages'))
WORK_ROOT = os.environ.get('HIL_WORK_ROOT', os.path.join(PROJECT_ROOT, 'runtime', 'work'))
ACCEPTANCE_ROOT = os.environ.get('HIL_ACCEPTANCE_ROOT',
                                 os.path.join(PROJECT_ROOT, 'artifacts', 'acceptance'))
CMD_HOST = '127.0.0.1'
CMD_PORT = CONFIG['local_udp']['command_port']
ACTIVE_CORE = None


def _utc_id(request_id):
    clean = ''.join(c for c in request_id if c.isalnum() or c in '-_')[:48]
    return '{}-{}'.format(datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'), clean or secrets.token_hex(4))


async def ws_pong(writer, data):
    writer.write(bytes([0x8A, len(data)]) + data)
    await writer.drain()


async def ws_send(writer, payload):
    data = payload.encode('utf-8')
    header = bytearray([0x81])
    if len(data) < 126:
        header.append(0x80 | len(data))
    elif len(data) < 65536:
        header.extend([0x80 | 126]); header.extend(struct.pack('>H', len(data)))
    else:
        header.extend([0x80 | 127]); header.extend(struct.pack('>Q', len(data)))
    mask = secrets.token_bytes(4)
    writer.write(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
    await writer.drain()


async def ws_recv(reader):
    hdr = await asyncio.wait_for(reader.readexactly(2), timeout=30.0)
    opcode, length = hdr[0] & 0x0F, hdr[1] & 0x7F
    if length == 126: length = struct.unpack('>H', await reader.readexactly(2))[0]
    elif length == 127: length = struct.unpack('>Q', await reader.readexactly(8))[0]
    payload = await reader.readexactly(length)
    if opcode == 0x09: return '__PING__'
    if opcode == 0x08: return '__CLOSE__'
    return payload.decode('utf-8')


def _core_request(command):
    """Send one local command and wait for its C-core receipt."""
    request_id = command.setdefault('request_id', secrets.token_hex(12))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(('127.0.0.1', 0)); sock.settimeout(2.0)
        sock.sendto(json.dumps(command, separators=(',', ':')).encode('utf-8'), (CMD_HOST, CMD_PORT))
        while True:
            payload, _ = sock.recvfrom(65536)
            receipt = json.loads(payload.decode('utf-8'))
            if receipt.get('request_id') == request_id:
                return receipt
    except (OSError, ValueError) as exc:
        return {'request_id': request_id, 'accepted': False, 'reason': 'C core receipt failed: {}'.format(exc)}
    finally:
        sock.close()


def _matlab_binary():
    for candidate in ('/usr/local/MATLAB/R2018b/bin/matlab', '/usr/local/bin/matlab'):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK): return candidate
    raise PackageError('MATLAB R2018b executable is unavailable')


def _write_json(path, value):
    with open(path, 'w') as output:
        json.dump(value, output, indent=2, sort_keys=True); output.write('\n')


def _build_or_deploy(request):
    global ACTIVE_CORE
    required = ('request_id', 'operation', 'model_ref', 'model_revision_ref', 'package_path', 'package_sha256')
    request_id = request.get('request_id') or 'invalid-request'
    run_id = _utc_id(request_id)
    work_dir = os.path.join(WORK_ROOT, run_id)
    evidence_path = os.path.join(ACCEPTANCE_ROOT, run_id)
    os.makedirs(work_dir); os.makedirs(evidence_path)
    log_path = os.path.join(work_dir, 'build.log')
    open(log_path, 'a').close()
    missing = [key for key in required if not request.get(key)]
    if missing:
        response = {'request_id': request.get('request_id', ''), 'status': 'FAILED',
                'failed_stage': 'RECEIVED', 'message': 'missing {}'.format(', '.join(missing)),
                'log_path': log_path, 'evidence_path': evidence_path, 'transitions': ['RECEIVED']}
        _write_json(os.path.join(evidence_path, 'build-result.json'), response)
        return response
    request_id = request['request_id']
    transitions = ['RECEIVED']
    response = {'request_id': request_id, 'status': 'FAILED', 'model_ref': request['model_ref'],
                'model_revision_ref': request['model_revision_ref'], 'failed_stage': None,
                'log_path': log_path, 'evidence_path': evidence_path, 'transitions': transitions}
    try:
        transitions.append('VALIDATING')
        package = validate_package(request['package_path'], CONTROLLED_PACKAGE_ROOT,
                                   request['package_sha256'])
        manifest = package['manifest']
        if manifest['model_ref'] != request['model_ref'] or manifest['model_revision_ref'] != request['model_revision_ref']:
            raise PackageError('request model_ref/model_revision_ref does not match manifest')
        response.update({'model_sha256': package['package_sha256'], 'contract_sha256': package['contract_sha256']})
        source_dir = os.path.join(work_dir, 'package')
        shutil.copytree(package['path'], source_dir)
        top_model = manifest['top_model']; model_name = package['contract']['model_name']
        artifact_dir = os.path.join(work_dir, 'generated'); executable_dir = os.path.join(work_dir, 'executable')
        task = {'model_name': model_name, 'slx_path': os.path.join(source_dir, top_model),
                'contract_path': os.path.join(source_dir, 'hil_contract.json'),
                'output_dir': artifact_dir, 'executable_dir': executable_dir}
        task_path, result_path = os.path.join(work_dir, 'build_task.json'), os.path.join(work_dir, 'build_result.json')
        _write_json(task_path, task)
        transitions.append('BUILDING')
        matlab = _matlab_binary(); script_dir = os.path.join(PROJECT_ROOT, 'matlab_scripts')
        command = [matlab, '-nodisplay', '-nosplash', '-nodesktop', '-r',
                   "addpath('{}');build_script('{}','{}');exit;".format(script_dir, task_path, result_path)]
        with open(log_path, 'w') as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        if process.returncode != 0 or not os.path.isfile(result_path):
            raise PackageError('MATLAB build did not complete successfully')
        with open(result_path, 'r') as result_file: result = json.load(result_file)
        if result.get('code') != 0: raise PackageError(result.get('message', 'ERT/GCC build failed'))
        executable = result.get('exe_path')
        transitions.append('VERIFYING')
        if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise PackageError('verified executable missing')
        response['executable_sha256'] = sha256_file(executable)
        response['executable_path'] = executable
        if request['operation'] == 'build':
            response['status'] = 'READY'; transitions.append('READY')
            _write_json(os.path.join(evidence_path, 'build-result.json'), response)
            return response
        if request['operation'] != 'deploy': raise PackageError('operation must be build or deploy')
        # One active core only: stop before starting the fully verified new binary.
        if ACTIVE_CORE and ACTIVE_CORE.poll() is None:
            ACTIVE_CORE.terminate()
            try: ACTIVE_CORE.wait(timeout=10)
            except subprocess.TimeoutExpired: ACTIVE_CORE.kill(); ACTIVE_CORE.wait(timeout=5)
        runtime_log = open(os.path.join(work_dir, 'runtime.log'), 'w')
        ACTIVE_CORE = subprocess.Popen([executable], stdout=runtime_log, stderr=subprocess.STDOUT,
                                       close_fds=True)
        if ACTIVE_CORE.poll() is not None: raise PackageError('new core exited during deployment verification')
        response['status'] = 'DEPLOYED'; transitions.extend(['READY', 'DEPLOYED'])
        _write_json(os.path.join(evidence_path, 'build-result.json'), response)
        return response
    except Exception as exc:
        response['failed_stage'] = transitions[-1]
        response['message'] = str(exc)
        _write_json(os.path.join(evidence_path, 'build-result.json'), response)
        return response


async def _handle_core_command(cmd, params, writer, lifecycle_event=None):
    request_id = params.pop('request_id', secrets.token_hex(12))
    receipt = _core_request({'request_id': request_id, 'cmd': cmd, 'params': params})
    if lifecycle_event and receipt.get('accepted') and bridge.is_connected():
        bridge.send_simulation_event(lifecycle_event, params.get('mission_id', ''))
    await ws_send(writer, json.dumps(receipt))


async def command_loop(reader, writer):
    while True:
        try: raw = await ws_recv(reader)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError): return
        if raw == '__PING__': await ws_pong(writer, b''); continue
        if raw == '__CLOSE__': return
        try: request = json.loads(raw)
        except ValueError: await ws_send(writer, json.dumps({'status': 'error', 'message': 'invalid JSON'})); continue
        cmd, params = request.get('cmd'), request.get('params', {})
        if not isinstance(params, dict): await ws_send(writer, json.dumps({'status': 'error', 'message': 'params must be object'})); continue
        if cmd in ('build_package', 'deploy_package'):
            request_body = dict(params); request_body['operation'] = 'deploy' if cmd == 'deploy_package' else 'build'
            await ws_send(writer, json.dumps(_build_or_deploy(request_body)))
        elif cmd == 'tune': await _handle_core_command('tune', dict(params), writer)
        elif cmd in ('pause', 'resume', 'reset', 'mission_end'):
            await _handle_core_command(cmd, dict(params), writer, cmd)
        elif cmd == 'get_state':
            state = state_cache.get_state_dict(); await ws_send(writer, json.dumps(state or {'status': 'error', 'message': 'no state available'}))
        else:
            await ws_send(writer, json.dumps({'status': 'error', 'message': 'unsupported command'}))


def start_ws_server():
    host, port = CONFIG['spring_boot'].get('host', '127.0.0.1'), CONFIG['spring_boot']['websocket_port']
    path = CONFIG['spring_boot'].get('path', '/ws/hil')
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    async def run_client():
        while True:
            try:
                reader, writer = await asyncio.open_connection(host, port)
                key = base64.b64encode(secrets.token_bytes(16)).decode('ascii')
                writer.write(('GET {} HTTP/1.1\r\nHost: {}:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n'.format(path, host, port, key)).encode('ascii'))
                await writer.drain()
                if '101' in (await asyncio.wait_for(reader.read(4096), timeout=5)).decode('utf-8'):
                    await command_loop(reader, writer)
                writer.close()
            except Exception as exc: logger.warning('WebSocket connection: {}'.format(exc))
            await asyncio.sleep(3)
    loop.run_until_complete(run_client())
