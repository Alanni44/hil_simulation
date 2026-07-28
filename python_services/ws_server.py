#!/usr/bin/env python3
"""HIL execution boundary: local verified packages and C-core receipts only."""
from __future__ import print_function

import asyncio
import base64
import datetime
import hashlib
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
from shared.model_package import PackageError, controlled_path, sha256_file, validate_package
from shared.ws_framing import FrameError, read_frame, write_frame
from shared.flight_state import parse_flight_state
import bridge_tcp_client as bridge
import dev_runner

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
DEPLOY_MODE = os.environ.get('HIL_DEPLOY_MODE', 'development')


def _utc_id(request_id):
    clean = ''.join(c for c in request_id if c.isalnum() or c in '-_')[:48]
    return '{}-{}'.format(datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'), clean or secrets.token_hex(4))


async def ws_pong(writer, data):
    await write_frame(writer, 0xA, data, masked=False)


async def ws_send(writer, payload):
    await write_frame(writer, 0x1, payload.encode('utf-8'), masked=False)


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


def _wait_for_healthy_core(timeout_seconds=10):
    """The first valid RUNNING normalized state is the deployment health gate."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('127.0.0.1', 9999))  # C monitor copy; avoids forwarder ownership of 9998.
        sock.settimeout(0.25)
        deadline = datetime.datetime.utcnow() + datetime.timedelta(seconds=timeout_seconds)
        while datetime.datetime.utcnow() < deadline:
            try:
                raw, _ = sock.recvfrom(4096)
                state = parse_flight_state(raw)
                if state['sequence'] > 0 and state['lifecycle'] == 0:
                    return state
            except (socket.timeout, ValueError):
                continue
    finally:
        sock.close()
    raise PackageError('timed out waiting for valid RUNNING NED state')


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
                'model_sha256': None, 'contract_sha256': None,
                'package_sha256': request['package_sha256'],
                'log_path': log_path, 'evidence_path': evidence_path, 'transitions': transitions}
    try:
        # Preserve forensic hashes even for a semantically invalid package;
        # this read is still confined to the same controlled root.
        candidate_path = controlled_path(request['package_path'], CONTROLLED_PACKAGE_ROOT)
        candidate_contract = os.path.join(candidate_path, 'hil_contract.json')
        if os.path.isfile(candidate_contract):
            response['contract_sha256'] = sha256_file(candidate_contract)
        candidate_manifest = os.path.join(candidate_path, 'package_manifest.json')
        if os.path.isfile(candidate_manifest):
            with open(candidate_manifest, 'r') as source:
                manifest_hint = json.load(source)
            top_model_hint = manifest_hint.get('top_model') if isinstance(manifest_hint, dict) else None
            if isinstance(top_model_hint, str) and top_model_hint.endswith('.slx') and \
                    '/' not in top_model_hint and '\\' not in top_model_hint:
                candidate_model = os.path.join(candidate_path, top_model_hint)
                if os.path.isfile(candidate_model): response['model_sha256'] = sha256_file(candidate_model)
        if request['operation'] not in ('build', 'deploy'):
            raise PackageError('operation must be build or deploy')
        transitions.append('VALIDATING')
        package = validate_package(request['package_path'], CONTROLLED_PACKAGE_ROOT,
                                   request['package_sha256'])
        manifest = package['manifest']
        if manifest['model_ref'] != request['model_ref'] or manifest['model_revision_ref'] != request['model_revision_ref']:
            raise PackageError('request model_ref/model_revision_ref does not match manifest')
        response.update({'model_sha256': manifest['files'][manifest['top_model']],
                         'package_sha256': package['package_sha256'],
                         'contract_sha256': package['contract_sha256']})
        # A deploy request is deliberately disruptive: the existing core is
        # stopped before importing/building the next package, so there is no
        # overlap, hot switch, rollback target or second active instance.
        if request['operation'] == 'deploy' and DEPLOY_MODE == 'systemd':
            active = subprocess.call(['systemctl', 'is-active', '--quiet', 'hil-core@current.service']) == 0
            if active: subprocess.check_call(['systemctl', 'stop', 'hil-core@current.service'], timeout=30)
            response['previous_core_stopped_before_build'] = active
        elif request['operation'] == 'deploy' and ACTIVE_CORE and ACTIVE_CORE.poll() is None:
            ACTIVE_CORE.terminate()
            try: ACTIVE_CORE.wait(timeout=10)
            except subprocess.TimeoutExpired: ACTIVE_CORE.kill(); ACTIVE_CORE.wait(timeout=5)
            response['previous_core_stopped_before_build'] = True
        elif request['operation'] == 'deploy':
            response['previous_core_stopped_before_build'] = False
        source_dir = os.path.join(work_dir, 'package')
        shutil.copytree(package['path'], source_dir)
        top_model = manifest['top_model']; model_name = package['contract']['model_name']
        artifact_dir = os.path.join(work_dir, 'generated'); executable_dir = os.path.join(work_dir, 'executable')
        task = {'model_name': model_name, 'slx_path': os.path.join(source_dir, top_model),
                'contract_path': os.path.join(source_dir, 'hil_contract.json'),
                'output_dir': artifact_dir, 'executable_dir': executable_dir,
                'matlab_version': manifest['matlab_version'], 'package_root': source_dir,
                'dependency_paths': [os.path.join(source_dir, *relative.split('/'))
                                     for relative in package['dependency_relpaths']]}
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
        # The old core was stopped before BUILDING above.  Only one verified
        # executable is now started after full ERT/GCC verification.
        runtime_log = open(os.path.join(work_dir, 'runtime.log'), 'w')
        if DEPLOY_MODE == 'systemd':
            pending_dir = '/opt/hil/runtime/pending'
            pending_path = os.path.join(pending_dir, 'current.json')
            if not os.path.isdir(pending_dir): raise PackageError('production pending directory is unavailable')
            _write_json(pending_path, {'executable_path': executable,
                                       'executable_sha256': response['executable_sha256']})
            subprocess.check_call(['systemctl', 'restart', 'hil-deploy@current.service'], timeout=30)
            response['health_state'] = _wait_for_healthy_core()
            response['status'] = 'DEPLOYED'; transitions.extend(['READY', 'DEPLOYED'])
        elif DEPLOY_MODE == 'development':
            ACTIVE_CORE = dev_runner.start(executable, runtime_log)
            if ACTIVE_CORE.poll() is not None: raise PackageError('new core exited during deployment verification')
            response['status'] = 'DEV_DEPLOYED'; transitions.extend(['READY', 'DEV_DEPLOYED'])
        else:
            raise PackageError('HIL_DEPLOY_MODE must be development or systemd')
        _write_json(os.path.join(evidence_path, 'build-result.json'), response)
        return response
    except Exception as exc:
        response['failed_stage'] = transitions[-1]
        response['message'] = str(exc)
        _write_json(os.path.join(evidence_path, 'build-result.json'), response)
        return response


async def _handle_core_command(cmd, params, writer, lifecycle_event=None):
    request_id = params.pop('request_id', secrets.token_hex(12))
    reservation = None
    if lifecycle_event and bridge.is_connected():
        reservation = bridge.reserve_simulation_event(
            lifecycle_event, params.get('mission_id', ''))
    try:
        receipt = _core_request(
            {'request_id': request_id, 'cmd': cmd, 'params': params})
    except Exception:
        if reservation is not None:
            bridge.resolve_simulation_event(reservation, accepted=False)
        raise
    if lifecycle_event and receipt.get('accepted'):
        if reservation is not None:
            bridge.resolve_simulation_event(reservation, accepted=True)
    elif reservation is not None:
        bridge.resolve_simulation_event(reservation, accepted=False)
    await ws_send(writer, json.dumps(receipt))


async def _handle_load_mission(params, writer):
    request_id = params.pop('request_id', secrets.token_hex(12))
    receipt = _core_request({'request_id': request_id, 'cmd': 'load_mission', 'params': params})
    if receipt.get('accepted') and bridge.is_connected():
        waypoints = []
        for waypoint in params['waypoints']:
            waypoints.append({'x': waypoint['north_m'], 'y': waypoint['east_m'],
                              'height': -waypoint['down_m'], 'speed': waypoint['speed_mps']})
        bridge.send_mission_plan(params['mission_id'], waypoints)
    await ws_send(writer, json.dumps(receipt))


async def command_loop(reader, writer):
    while True:
        try:
            opcode, payload = await read_frame(reader, require_masked=True)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, FrameError):
            return
        if opcode == 0x9:
            await ws_pong(writer, payload); continue
        if opcode == 0x8:
            await write_frame(writer, 0x8, payload, masked=False); return
        if opcode != 0x1:
            await ws_send(writer, json.dumps({'status': 'error', 'message': 'text frame required'})); continue
        try:
            raw = payload.decode('utf-8')
        except UnicodeDecodeError:
            await ws_send(writer, json.dumps({'status': 'error', 'message': 'invalid UTF-8'})); continue
        try: request = json.loads(raw)
        except ValueError: await ws_send(writer, json.dumps({'status': 'error', 'message': 'invalid JSON'})); continue
        cmd, params = request.get('cmd'), request.get('params', {})
        if not isinstance(params, dict): await ws_send(writer, json.dumps({'status': 'error', 'message': 'params must be object'})); continue
        if cmd in ('build_package', 'deploy_package'):
            request_body = dict(params); request_body['operation'] = 'deploy' if cmd == 'deploy_package' else 'build'
            await ws_send(writer, json.dumps(_build_or_deploy(request_body)))
        elif cmd == 'tune': await _handle_core_command('tune', dict(params), writer)
        elif cmd == 'set_inputs': await _handle_core_command('set_inputs', dict(params), writer)
        elif cmd == 'load_mission': await _handle_load_mission(dict(params), writer)
        elif cmd in ('pause', 'resume', 'reset', 'mission_end'):
            await _handle_core_command(cmd, dict(params), writer, cmd)
        elif cmd == 'get_state':
            state = state_cache.get_state_dict(); await ws_send(writer, json.dumps(state or {'status': 'error', 'message': 'no state available'}))
        else:
            await ws_send(writer, json.dumps({'status': 'error', 'message': 'unsupported command'}))


def start_ws_server():
    host = os.environ.get('HIL_WS_LISTEN_HOST', '0.0.0.0')
    port = int(os.environ.get('HIL_WS_LISTEN_PORT', CONFIG['spring_boot']['websocket_port']))
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    async def websocket_client(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=5.0)
            lines = request.decode('ascii').split('\r\n')
            headers = {}
            for line in lines[1:]:
                if ':' in line:
                    key, value = line.split(':', 1); headers[key.strip().lower()] = value.strip()
            key = headers.get('sec-websocket-key')
            if not lines[0].startswith('GET ') or headers.get('upgrade', '').lower() != 'websocket' or not key:
                writer.close(); return
            accept = base64.b64encode(hashlib.sha1((key +
                '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
            writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                          'Sec-WebSocket-Accept: {}\r\n\r\n'.format(accept)).encode('ascii'))
            await writer.drain()
            await command_loop(reader, writer)
        except Exception as exc:
            logger.warning('WebSocket client: {}'.format(exc))
        finally:
            writer.close()
    server = loop.run_until_complete(asyncio.start_server(websocket_client, host, port))
    logger.info('WebSocket server listening on {}:{}'.format(host, port))
    try:
        loop.run_forever()
    finally:
        server.close(); loop.run_until_complete(server.wait_closed()); loop.close()
