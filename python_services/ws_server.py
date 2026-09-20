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
import threading
import time

from config_loader import CONFIG
from shared import state_cache
from shared.logger import get_logger
from shared.gitlab_release import GitLabReleaseClient, GitLabReleaseError
from shared.gitlab_stage import GitLabStageError, stage_release
from shared.model_package import PackageError, controlled_path, sha256_file, validate_package
from shared.ws_framing import FrameError, read_frame, write_frame
from shared.flight_state import parse_flight_state
import bridge_tcp_client as bridge
from fixed_wing_v3_bridge import get_hud_state as get_v3_hud_state
from core_client import core_request as _core_request
import dev_runner
from hil_adapters import virtual_quad_fc

logger = get_logger('ws_v2')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLED_PACKAGE_ROOT = os.environ.get('HIL_CONTROLLED_PACKAGE_ROOT',
                                         os.path.join(PROJECT_ROOT, 'packages'))
WORK_ROOT = os.environ.get('HIL_WORK_ROOT', os.path.join(PROJECT_ROOT, 'runtime', 'work'))
ACCEPTANCE_ROOT = os.environ.get('HIL_ACCEPTANCE_ROOT',
                                 os.path.join(PROJECT_ROOT, 'artifacts', 'acceptance'))
ACTIVE_CORE = None
DEPLOY_MODE = os.environ.get('HIL_DEPLOY_MODE', 'development')
ACTIVE_VEHICLE_CONTRACT_PATH = os.environ.get(
    'HIL_ACTIVE_CONTRACT_PATH', os.path.join(PROJECT_ROOT, 'runtime', 'active_vehicle_contract.json'))
GITLAB_AUDIT_ROOT = os.environ.get(
    'HIL_GITLAB_AUDIT_ROOT', os.path.join(PROJECT_ROOT, 'artifacts', 'gitlab-audit'))
GITLAB_RECEIPT_ROOT = os.environ.get(
    'HIL_GITLAB_RECEIPT_ROOT', os.path.join(PROJECT_ROOT, 'runtime', 'gitlab-stage-receipts'))
GITLAB_CLIENT = GitLabReleaseClient.from_config(
    CONFIG.get('gitlab_release', {}), os.environ.get('HIL_GITLAB_TOKEN', ''))
BUILD_DEPLOY_LOCK = threading.Lock()
GITLAB_RECEIPT_LOCK = threading.Lock()


def _utc_id(request_id):
    clean = ''.join(c for c in request_id if c.isalnum() or c in '-_')[:48]
    return '{}-{}'.format(datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'), clean or secrets.token_hex(4))


async def ws_pong(writer, data):
    await write_frame(writer, 0xA, data, masked=False)


async def ws_send(writer, payload):
    await write_frame(writer, 0x1, payload.encode('utf-8'), masked=False)


def _matlab_binary():
    for candidate in ('/usr/local/MATLAB/R2018b/bin/matlab', '/usr/local/bin/matlab'):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK): return candidate
    raise PackageError('MATLAB R2018b executable is unavailable')


def _write_json(path, value):
    with open(path, 'w') as output:
        json.dump(value, output, indent=2, sort_keys=True); output.write('\n')


def _publish_active_vehicle_contract(contract, contract_sha256):
    """Publish the exact verified V3 contract for optional virtual UUTs."""
    directory = os.path.dirname(ACTIVE_VEHICLE_CONTRACT_PATH)
    if not os.path.isdir(directory): os.makedirs(directory)
    pending = ACTIVE_VEHICLE_CONTRACT_PATH + '.pending'
    _write_json(pending, {'contract': contract, 'contract_sha256': contract_sha256})
    os.replace(pending, ACTIVE_VEHICLE_CONTRACT_PATH)
    return ACTIVE_VEHICLE_CONTRACT_PATH


def _validate_bridge_contract_compatibility(contract):
    """Reject a V3 bridge selection before an incompatible model is built."""
    if CONFIG.get('bridge', {}).get('protocol_version', '2.0') != '3.0':
        return
    if contract.get('vehicle_kind') != 'fixed_wing' or not contract.get('protocol_v3'):
        raise PackageError('bridge.protocol_version=3.0 requires a fixed-wing package with protocol_v3')


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
        _validate_bridge_contract_compatibility(package['contract'])
        manifest = package['manifest']
        if manifest['model_ref'] != request['model_ref'] or manifest['model_revision_ref'] != request['model_revision_ref']:
            raise PackageError('request model_ref/model_revision_ref does not match manifest')
        response.update({'model_sha256': manifest['files'][manifest['top_model']],
                         'package_sha256': package['package_sha256'],
                         'contract_sha256': package['contract_sha256']})
        # In production the verified old core continues while MATLAB/GCC build
        # runs.  The privileged deploy unit stops it only after the replacement
        # executable has been copied and hash-verified.  This avoids granting
        # the Python service permission to manipulate the core unit directly.
        if request['operation'] == 'deploy' and DEPLOY_MODE == 'systemd':
            response['previous_core_running_before_deploy'] = (
                subprocess.call(['systemctl', 'is-active', '--quiet',
                                 'hil-core@current.service']) == 0)
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
            pending = pending_path + '.pending'
            _write_json(pending, {'format_version': 1, 'request_id': request_id,
                                  'package_sha256': response['package_sha256'],
                                  'executable_path': executable,
                                  'executable_sha256': response['executable_sha256']})
            os.replace(pending, pending_path)
            # hil-deploy.path observes this atomically published descriptor and
            # starts the privileged deploy helper. The Python executor never
            # receives general systemd-management permission.
            response['health_state'] = _wait_for_healthy_core()
            response['status'] = 'DEPLOYED'; transitions.extend(['READY', 'DEPLOYED'])
        elif DEPLOY_MODE == 'development':
            ACTIVE_CORE = dev_runner.start(executable, runtime_log)
            if ACTIVE_CORE.poll() is not None: raise PackageError('new core exited during deployment verification')
            response['status'] = 'DEV_DEPLOYED'; transitions.extend(['READY', 'DEV_DEPLOYED'])
        else:
            raise PackageError('HIL_DEPLOY_MODE must be development or systemd')
        if package['contract'].get('contract_version') == 3:
            response['active_vehicle_contract_path'] = _publish_active_vehicle_contract(
                package['contract'], response['contract_sha256'])
            virtual_result = virtual_quad_fc.activate_deployed_contract(
                response['active_vehicle_contract_path'])
            if virtual_result is not None:
                response['virtual_fc_contract_reload'] = virtual_result
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


def _write_gitlab_audit(event):
    """Persist only non-secret release provenance for local traceability."""
    if not os.path.isdir(GITLAB_AUDIT_ROOT):
        os.makedirs(GITLAB_AUDIT_ROOT)
    audit_event = {
        'timestamp_utc': datetime.datetime.utcnow().isoformat() + 'Z',
        'action': event['action'],
        'outcome': event.get('outcome', 'SUCCEEDED'),
        'request_id': event.get('request_id', ''),
        'operator_id': event.get('operator_id'),
        'project': event.get('project'),
        'tag_name': event.get('tag_name'),
        'package_sha256': event.get('package_sha256'),
        'model_ref': event.get('model_ref'),
        'model_revision_ref': event.get('model_revision_ref'),
        'commit_id': event.get('commit_id'),
        'contract_sha256': event.get('contract_sha256'),
    }
    filename = '{}-{}.json'.format(_utc_id(event.get('request_id', 'gitlab')), secrets.token_hex(4))
    _write_json(os.path.join(GITLAB_AUDIT_ROOT, filename), audit_event)
    return audit_event


def _gitlab_history():
    if not os.path.isdir(GITLAB_AUDIT_ROOT):
        return []
    events = []
    for filename in sorted(os.listdir(GITLAB_AUDIT_ROOT), reverse=True)[:50]:
        if not filename.endswith('.json'):
            continue
        try:
            with open(os.path.join(GITLAB_AUDIT_ROOT, filename), 'r') as source:
                value = json.load(source)
            if isinstance(value, dict):
                events.append(value)
        except (IOError, ValueError):
            logger.warning('Skipping unreadable GitLab audit record %s', filename)
    return events


def _gitlab_receipt_path(receipt_id):
    if not isinstance(receipt_id, str) or len(receipt_id) != 32 or \
            any(character not in '0123456789abcdef' for character in receipt_id):
        raise PackageError('GitLab stage receipt is invalid.')
    return os.path.join(GITLAB_RECEIPT_ROOT, '{}.json'.format(receipt_id))


def _gitlab_receipt_ttl_seconds():
    value = CONFIG.get('gitlab_release', {}).get('stage_receipt_ttl_seconds', 1800)
    if isinstance(value, bool) or not isinstance(value, int) or value < 60 or value > 86400:
        raise PackageError('GitLab stage receipt TTL must be an integer from 60 to 86400 seconds.')
    return value


def _create_gitlab_stage_receipt(staged):
    """Persist server-issued provenance; browsers receive only its opaque ID."""
    if not os.path.isdir(GITLAB_RECEIPT_ROOT):
        os.makedirs(GITLAB_RECEIPT_ROOT)
    receipt_id = secrets.token_hex(16)
    now = int(time.time())
    receipt = {key: staged.get(key) for key in (
        'project', 'tag_name', 'commit_id', 'package_path', 'package_sha256',
        'model_ref', 'model_revision_ref')}
    receipt.update({'created_at_unix': now,
                    'expires_at_unix': now + _gitlab_receipt_ttl_seconds(),
                    'used_operations': []})
    path = _gitlab_receipt_path(receipt_id)
    pending_path = path + '.pending'
    _write_json(pending_path, receipt)
    os.replace(pending_path, path)
    return receipt_id


def _hydrate_gitlab_stage_receipt(request, operation):
    """Consume one permitted operation and replace untrusted client fields."""
    receipt_id = request.get('gitlab_stage_receipt')
    if receipt_id is None:
        return request
    if operation not in ('build', 'deploy'):
        raise PackageError('GitLab stage receipt operation is invalid.')
    path = _gitlab_receipt_path(receipt_id)
    with GITLAB_RECEIPT_LOCK:
        try:
            with open(path, 'r') as source:
                receipt = json.load(source)
        except (IOError, ValueError):
            raise PackageError('GitLab stage receipt is unavailable.')
        required = ('package_path', 'package_sha256', 'model_ref', 'model_revision_ref',
                    'expires_at_unix', 'used_operations')
        nonempty = ('package_path', 'package_sha256', 'model_ref', 'model_revision_ref')
        if (not isinstance(receipt, dict) or any(key not in receipt for key in required)
                or any(not receipt.get(key) for key in nonempty)):
            raise PackageError('GitLab stage receipt is invalid.')
        if not isinstance(receipt['expires_at_unix'], int) or time.time() >= receipt['expires_at_unix']:
            raise PackageError('GitLab stage receipt has expired; stage the release again.')
        if (not isinstance(receipt['used_operations'], list) or
                any(item not in ('build', 'deploy') for item in receipt['used_operations'])):
            raise PackageError('GitLab stage receipt is invalid.')
        if operation in receipt['used_operations']:
            raise PackageError('GitLab stage receipt was already used for {}.'.format(operation))
        receipt['used_operations'].append(operation)
        pending_path = path + '.pending'
        _write_json(pending_path, receipt)
        os.replace(pending_path, path)
    hydrated = dict(request)
    for key in ('package_path', 'package_sha256', 'model_ref', 'model_revision_ref'):
        hydrated[key] = receipt[key]
    hydrated['gitlab_provenance'] = receipt
    hydrated['_gitlab_receipt_verified'] = True
    return hydrated


def _required_gitlab_string(params, name):
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError('missing {}'.format(name))
    return value


def _public_gitlab_release(release):
    """Return only browser-safe release metadata; asset URLs stay server-side."""
    return {key: release.get(key) for key in
            ('tag_name', 'released_at', 'commit_id', 'asset_name')}


def _public_staged_release(staged):
    """Keep server package paths inside the service boundary."""
    return {key: staged.get(key) for key in
            ('project', 'tag_name', 'asset_name', 'package_sha256', 'model_ref',
             'model_revision_ref', 'model_name', 'commit_id')}


def _finish_gitlab_command(cmd, params, response, staged=None):
    """Audit every GitLab read/stage outcome without retaining error details."""
    if cmd == 'gitlab_history':
        return response
    action = {
        'gitlab_status': 'status',
        'gitlab_list_releases': 'list_releases',
        'gitlab_stage_release': 'stage_release',
    }.get(cmd, 'unknown')
    staged = staged or {}
    _write_gitlab_audit({
        'action': action,
        'outcome': 'SUCCEEDED' if response.get('status') in ('OK', 'READY') else 'FAILED',
        'request_id': params.get('request_id', ''),
        'operator_id': params.get('operator_id') if isinstance(params.get('operator_id'), str) else None,
        'project': staged.get('project', params.get('project')),
        'tag_name': staged.get('tag_name', params.get('tag_name')),
        'package_sha256': staged.get('package_sha256'),
        'model_ref': staged.get('model_ref'),
        'model_revision_ref': staged.get('model_revision_ref'),
        'commit_id': staged.get('commit_id'),
    })
    return response


def _audit_gitlab_build_or_deploy(request, response):
    """Attach build/deploy evidence to the release selected by the console."""
    provenance = request.get('gitlab_provenance')
    if not request.get('_gitlab_receipt_verified') or not isinstance(provenance, dict) or \
            request.get('operation') not in ('build', 'deploy'):
        return
    action = '{}_package'.format(request['operation'])
    _write_gitlab_audit({
        'action': action,
        'outcome': 'SUCCEEDED' if response.get('status') in ('READY', 'DEPLOYED', 'DEV_DEPLOYED') else 'FAILED',
        'request_id': request.get('request_id', ''),
        'project': provenance.get('project'),
        'tag_name': provenance.get('tag_name'),
        'package_sha256': provenance.get('package_sha256'),
        'commit_id': provenance.get('commit_id'),
        'model_ref': request.get('model_ref'),
        'model_revision_ref': request.get('model_revision_ref'),
        'contract_sha256': response.get('contract_sha256'),
    })


def _handle_gitlab_command(cmd, params):
    """Handle the read-only release workflow without exposing credentials."""
    try:
        if cmd == 'gitlab_status':
            return _finish_gitlab_command(cmd, params,
                                          {'status': 'OK', 'gitlab': GITLAB_CLIENT.status()})
        if cmd == 'gitlab_history':
            return {'status': 'OK', 'events': _gitlab_history()}
        project = _required_gitlab_string(params, 'project')
        if cmd == 'gitlab_list_releases':
            return _finish_gitlab_command(cmd, params, {
                'status': 'OK', 'project': project,
                'releases': [_public_gitlab_release(release)
                             for release in GITLAB_CLIENT.list_releases(project)]})
        if cmd == 'gitlab_stage_release':
            tag_name = _required_gitlab_string(params, 'tag_name')
            staged = stage_release(GITLAB_CLIENT, project, tag_name, CONTROLLED_PACKAGE_ROOT)
            receipt_id = _create_gitlab_stage_receipt(staged)
            return _finish_gitlab_command(cmd, params, {
                'status': 'READY', 'staged': _public_staged_release(staged),
                'build_request': {
                    'request_id': params.get('request_id', secrets.token_hex(12)),
                    'gitlab_stage_receipt': receipt_id,
                },
            }, staged)
        return _finish_gitlab_command(cmd, params,
                                      {'status': 'FAILED', 'message': 'unsupported GitLab command'})
    except (GitLabReleaseError, GitLabStageError, ValueError) as exc:
        return _finish_gitlab_command(cmd, params, {'status': 'FAILED', 'message': str(exc)})
    except Exception as exc:
        logger.exception('GitLab command failed: %s', exc.__class__.__name__)
        return _finish_gitlab_command(cmd, params,
                                      {'status': 'FAILED', 'message': 'GitLab operation failed; inspect server logs.'})


def _run_gitlab_build_or_deploy(params, operation):
    """Serialize receipt consumption with the disruptive build/deploy action."""
    request_body = dict(params)
    request_body['operation'] = operation
    if not BUILD_DEPLOY_LOCK.acquire(False):
        return request_body, {'status': 'FAILED', 'failed_stage': 'RECEIVED',
                              'message': 'another build or deployment is already running'}
    try:
        try:
            request_body = _hydrate_gitlab_stage_receipt(request_body, operation)
            request_body['operation'] = operation
            response = _build_or_deploy(request_body)
        except PackageError as exc:
            response = {'status': 'FAILED', 'failed_stage': 'RECEIVED',
                        'message': str(exc)}
        return request_body, response
    finally:
        BUILD_DEPLOY_LOCK.release()


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
            operation = 'deploy' if cmd == 'deploy_package' else 'build'
            request_body, build_response = _run_gitlab_build_or_deploy(
                dict(params), operation)
            _audit_gitlab_build_or_deploy(request_body, build_response)
            await ws_send(writer, json.dumps(build_response))
        elif cmd in ('gitlab_status', 'gitlab_list_releases', 'gitlab_stage_release', 'gitlab_history'):
            await ws_send(writer, json.dumps(_handle_gitlab_command(cmd, dict(params))))
        elif cmd in ('tune', 'get_parameter_registry'):
            await _handle_core_command(cmd, dict(params), writer)
        elif cmd == 'set_inputs': await _handle_core_command('set_inputs', dict(params), writer)
        elif cmd in ('select_control_source', 'actuator_command'):
            await _handle_core_command(cmd, dict(params), writer)
        elif cmd in ('virtual_fc_start', 'virtual_fc_stop', 'virtual_fc_status', 'virtual_fc_inject_fault',
                     'virtual_fc_set_target', 'virtual_fc_load_route', 'virtual_fc_reload_contract'):
            await ws_send(writer, json.dumps(virtual_quad_fc.handle_command(cmd, dict(params))))
        elif cmd == 'load_mission': await _handle_load_mission(dict(params), writer)
        elif cmd in ('pause', 'resume', 'reset', 'mission_end'):
            await _handle_core_command(cmd, dict(params), writer, cmd)
        elif cmd == 'get_state':
            state = (get_v3_hud_state() if CONFIG.get('bridge', {}).get('protocol_version') == '3.0'
                     else state_cache.get_state_dict())
            await ws_send(writer, json.dumps(state or {'status': 'error', 'message': 'no state available'}))
        else:
            await ws_send(writer, json.dumps({'status': 'error', 'message': 'unsupported command'}))


def _ws_listen_host():
    configured_host = os.environ.get('HIL_WS_LISTEN_HOST')
    if CONFIG.get('gitlab_release', {}).get('enabled') is True:
        host = configured_host or '127.0.0.1'
        if host not in ('127.0.0.1', '::1', 'localhost'):
            raise PackageError('GitLab-enabled WebSocket management must bind to loopback; use an authenticated reverse proxy.')
        return host
    return configured_host or '0.0.0.0'


def start_ws_server():
    host = _ws_listen_host()
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
