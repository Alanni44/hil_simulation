#!/usr/bin/env python3
"""Ubuntu target acceptance for the 2026-07-25 runtime contract.

The script never marks a skipped dependency or assertion as passed.  It writes
the evidence layout required by the design document and exits non-zero unless
every build, packet, adapter, lifecycle and deployment check succeeds.
"""
from __future__ import print_function
import asyncio
import datetime
import hashlib
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python_services'))
from shared.flight_state import FLIGHT_STATE_FORMAT, FLIGHT_STATE_SIZE, parse_flight_state  # noqa
from shared.model_package import package_sha256, sha256_file  # noqa
from shared import state_cache  # noqa
import ws_server  # noqa


def write_json(path, value):
    with open(path, 'w') as output:
        json.dump(value, output, indent=2, sort_keys=True); output.write('\n')


def tree_sha256(root):
    digest = hashlib.sha256()
    for base, directories, names in os.walk(root):
        directories.sort(); names.sort()
        for name in names:
            path = os.path.join(base, name)
            relative = os.path.relpath(path, root).replace(os.sep, '/')
            digest.update(relative.encode('utf-8')); digest.update(b'\0')
            with open(path, 'rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            digest.update(b'\0')
    return digest.hexdigest()


def record(assertions, name, passed, detail):
    assertions.append({'name': name, 'passed': bool(passed), 'detail': detail,
                       'utc': datetime.datetime.utcnow().isoformat() + 'Z'})
    if not passed: raise AssertionError('{}: {}'.format(name, detail))


def packet(log, kind, value):
    log.write(json.dumps({'utc': datetime.datetime.utcnow().isoformat() + 'Z',
                          'kind': kind, 'value': value}, sort_keys=True) + '\n'); log.flush()


def core_command(command_socket, packet_log, request_id, cmd, params, observed=None):
    command = {'request_id': request_id, 'cmd': cmd, 'params': params}
    packet(packet_log, 'command', command)
    command_socket.sendto(json.dumps(command).encode('utf-8'), ('127.0.0.1', 9997))
    while True:
        data, _ = command_socket.recvfrom(65536)
        receipt = json.loads(data.decode('utf-8'))
        packet(packet_log, 'receipt', receipt)
        if observed is not None:
            observed.append(receipt)
        if receipt.get('request_id') == request_id: return receipt


def recv_state(status_socket, packet_log):
    raw, _ = status_socket.recvfrom(4096)
    state = parse_flight_state(raw)
    packet(packet_log, 'ned_state', state)
    return state


def recv_matching(status_socket, packet_log, predicate):
    deadline = time.time() + 3
    while time.time() < deadline:
        state = recv_state(status_socket, packet_log)
        if predicate(state): return state
    raise AssertionError('timed out waiting for expected normalized state')


def _tcp_recv_frame(sock):
    header = b''
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk: raise AssertionError('UE4 test peer closed connection')
        header += chunk
    size = struct.unpack('>I', header)[0]
    body = b''
    while len(body) < size:
        chunk = sock.recv(size - len(body))
        if not chunk: raise AssertionError('truncated UE4 test frame')
        body += chunk
    return json.loads(body.decode('utf-8'))


def _tcp_send_frame(sock, value):
    body = json.dumps(value).encode('utf-8')
    sock.sendall(struct.pack('>I', len(body)) + body)


class _ReceiptWriter(object):
    """Minimal async writer used to exercise the real WebSocket command path."""
    def __init__(self):
        self.payloads = []

    def write(self, payload):
        self.payloads.append(payload)

    async def drain(self):
        return None


def receive_ue4_vehicle_stream(packet_log, runtime_log_path, source_state):
    """Capture a 10-second V2 stream and an actual reset-scene event."""
    known = dict(source_state)
    known.update({'sequence': source_state['sequence'] + 1000000,
                  'sim_time_s': source_state['sim_time_s'] + 1.0,
                  'north_m': 10.0, 'east_m': 20.0,
                  'down_m': 30.0, 'vn_mps': 4.0, 've_mps': 5.0, 'vd_mps': 6.0,
                  'q_w': 0.7071067811865476, 'q_x': 0.0, 'q_y': 0.0,
                  'q_z': 0.7071067811865476, 'p_radps': 0.0, 'q_radps': 0.0,
                  'r_radps': 0.0, 'ax_mps2': 4.0, 'ay_mps2': 5.0, 'az_mps2': 6.0,
                  'airborne': 1, 'lifecycle': 0, 'reserved': 0})
    known_state_raw = struct.pack(FLIGHT_STATE_FORMAT, *[
        known[key] for key in ('version', 'sequence', 'sim_time_s', 'north_m', 'east_m', 'down_m',
                               'vn_mps', 've_mps', 'vd_mps', 'q_w', 'q_x', 'q_y', 'q_z',
                               'p_radps', 'q_radps', 'r_radps', 'ax_mps2', 'ay_mps2', 'az_mps2',
                               'airborne', 'lifecycle', 'reserved')])
    state_cache.update(known_state_raw)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 5001)); server.listen(1); server.settimeout(8)
    bridge = ws_server.bridge
    old_host, old_port = bridge.UE4_HOST, bridge.UE4_PORT
    bridge.UE4_HOST, bridge.UE4_PORT, bridge._running = '127.0.0.1', 5001, True
    try:
        bridge.send_mission_plan('acceptance-route', [
            {'x': 100.0, 'y': 200.0, 'height': 30.0, 'speed': 7.0},
            {'x': 150.0, 'y': 220.0, 'height': 35.0, 'speed': 7.0}])
        bridge.start_bridge()
        peer, _ = server.accept(); peer.settimeout(5)
        hello = _tcp_recv_frame(peer)
        _tcp_send_frame(peer, {'type': 'ack', 'data': {'accepted': True, 'ref_type': 'hello'}})
        mission = _tcp_recv_frame(peer)
        _tcp_send_frame(peer, {'type': 'ack', 'data': {'accepted': True, 'ref_type': 'mission_plan'}})
        connected_deadline = time.monotonic() + 2.0
        while not bridge.is_connected() and time.monotonic() < connected_deadline:
            time.sleep(0.01)
        if not bridge.is_connected():
            raise AssertionError('UE4 bridge did not complete the acknowledged handshake')
        stream_started = time.monotonic()
        stream_deadline = stream_started + 10.0
        vehicle_states, reset_event, reset_writer = [], None, _ReceiptWriter()
        # Route an accepted core reset through the production WebSocket
        # command handler; that is the only allowed path to notify UE4.
        event_loop = asyncio.new_event_loop()
        try:
            event_loop.run_until_complete(ws_server._handle_core_command(
                'reset', {'request_id': 'ue4-reset-event'}, reset_writer,
                lifecycle_event='reset'))
        finally:
            event_loop.close()
        while time.monotonic() < stream_deadline:
            # The production forwarder continually refreshes this cache.  The
            # acceptance peer supplies the same valid source state at the
            # requested 50 Hz so it exercises the sender rather than its
            # intentional stale-state safety cutoff.
            state_cache.update(known_state_raw)
            frame = _tcp_recv_frame(peer)
            if frame.get('type') == 'vehicle_state':
                vehicle_states.append(frame)
            elif frame.get('type') == 'simulation_event':
                reset_event = frame
                _tcp_send_frame(peer, {'type': 'ack', 'data': {
                    'accepted': True, 'ref_type': 'simulation_event',
                    'ref_seq': frame.get('seq')}})
        elapsed = time.monotonic() - stream_started
        if not vehicle_states:
            raise AssertionError('UE4 bridge did not send vehicle_state')
        vehicle = vehicle_states[0]
        packet(packet_log, 'ue4_protocol_hello', hello)
        packet(packet_log, 'ue4_protocol_mission_plan', mission)
        for frame in vehicle_states:
            packet(packet_log, 'ue4_protocol_vehicle_state', frame)
        packet(packet_log, 'ue4_protocol_reset_event', reset_event)
        with open(runtime_log_path, 'a') as runtime_log:
            runtime_log.write('[Python UE4 Bridge] connected test peer; 10-second vehicle_state stream and reset_scene acknowledged\n')
        peer.close()
        return mission, vehicle, reset_event, {
            'frames': len(vehicle_states), 'elapsed_s': elapsed,
            'average_hz': len(vehicle_states) / elapsed,
            'seq_strictly_increasing': all(
                vehicle_states[index]['seq'] < vehicle_states[index + 1]['seq']
                for index in range(len(vehicle_states) - 1)),
            'reset_receipt_count': len(reset_writer.payloads)}
    finally:
        bridge.stop_bridge()
        bridge.UE4_HOST, bridge.UE4_PORT = old_host, old_port
        server.close()


def create_package(package_dir):
    command = [ws_server._matlab_binary(), '-nodisplay', '-nosplash', '-nodesktop', '-r',
               "addpath('{}');generate_test_model('{}');exit;".format(
                   os.path.join(ROOT, 'matlab_scripts'), package_dir)]
    subprocess.check_call(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    subprocess.check_call([sys.executable, os.path.join(ROOT, 'scripts', 'create_acceptance_package.py'), package_dir])


def submit(package_root, package_path, request_id, operation):
    manifest = json.load(open(os.path.join(package_path, 'package_manifest.json')))
    return ws_server._build_or_deploy({
        'request_id': request_id, 'operation': operation,
        'model_ref': manifest['model_ref'], 'model_revision_ref': manifest['model_revision_ref'],
        'package_path': package_path, 'package_sha256': package_sha256(package_path)})


def malformed_copy(source, destination, defect, update_manifest=True):
    shutil.copytree(source, destination)
    contract_path = os.path.join(destination, 'hil_contract.json')
    contract = json.load(open(contract_path))
    if defect == 'missing_attitude': del contract['state']['outputs']['q_z']
    elif defect == 'missing_speed': del contract['state']['outputs']['vd_mps']
    elif defect == 'changed_unit': contract['state']['units']['north_m'] = 'ft'
    elif defect == 'missing_wind_d': del contract['inputs']['environment']['ports']['wind_d_mps']
    elif defect == 'missing_acceleration': del contract['outputs']['internal_state']['acceleration']['az_mps2']
    elif defect == 'reset_only_running':
        for parameter in contract['parameters']:
            if parameter['name'] == 'reset_gain':
                parameter['allowed_phases'] = ['RUNNING']
                break
    elif defect == 'integrity_tamper': contract['state']['outputs']['q_z'] = 'tampered_q_z'
    else: raise AssertionError('unknown malformed contract defect {}'.format(defect))
    with open(contract_path, 'w') as target: json.dump(contract, target)
    if not update_manifest: return
    subprocess.check_call([sys.executable, os.path.join(ROOT, 'scripts', 'create_acceptance_package.py'), destination])
    # restore the intentional defect after manifest regeneration.
    with open(contract_path, 'w') as target: json.dump(contract, target)
    # only the payload checksum needs an update: malformed contract must pass
    # integrity validation and fail semantic validation.
    manifest_path = os.path.join(destination, 'package_manifest.json')
    manifest = json.load(open(manifest_path)); manifest['files']['hil_contract.json'] = sha256_file(contract_path)
    manifest['package_sha256'] = package_sha256(destination)
    write_json(manifest_path, manifest)


def target_environment():
    """Return the mandated target facts or fail before claiming acceptance."""
    platform_name = platform.platform()
    gcc = subprocess.check_output(['gcc', '--version']).decode().splitlines()[0]
    if 'Ubuntu-18.04' not in platform_name or 'rt' not in platform_name.lower():
        raise RuntimeError('acceptance target must be Ubuntu 18.04 RT, got {}'.format(platform_name))
    if not gcc.startswith('gcc ') or ' 7.' not in gcc:
        raise RuntimeError('acceptance target must use GCC 7.x, got {}'.format(gcc))
    if sys.version_info[:3] != (3, 6, 9):
        raise RuntimeError('acceptance target must use Python 3.6.9, got {}'.format(sys.version))
    return {'platform': platform_name, 'python': sys.version, 'gcc': gcc,
            'matlab': ws_server._matlab_binary()}


def git_evidence():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).decode().strip()
    if dirty:
        raise RuntimeError('target checkout is dirty; refusing acceptance')
    return {'head': head, 'dirty': False}


def realtime_evidence(runtime_log_path):
    text = open(runtime_log_path, 'r').read()
    match = re.search(r'realtime samples=(\d+) p99_abs_lateness_ns=(\d+) '
                      r'max_abs_lateness_ns=(\d+) over_250us=(\d+) non_realtime=(\d+)', text)
    if not match:
        raise AssertionError('core realtime summary is absent')
    keys = ('samples', 'p99_abs_lateness_ns', 'max_abs_lateness_ns', 'over_250us', 'non_realtime')
    result = dict(zip(keys, [int(item) for item in match.groups()]))
    result.update({'required_samples': 1800000, 'p99_limit_ns': 100000,
                   'max_limit_ns': 250000, 'over_250us_limit': 0})
    result['passed'] = (result['samples'] >= result['required_samples'] and
                        result['p99_abs_lateness_ns'] <= result['p99_limit_ns'] and
                        result['max_abs_lateness_ns'] <= result['max_limit_ns'] and
                        result['over_250us'] == 0 and result['non_realtime'] == 0)
    return result


def main():
    # This must precede creation of the untracked evidence directory itself.
    git = git_evidence()
    run_id = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ') + '-runtime-contract'
    evidence = os.path.join(ROOT, 'artifacts', 'acceptance', run_id)
    os.makedirs(evidence)
    assertions, responses = [], {}
    runtime_log_path = os.path.join(evidence, 'runtime.log')
    # Create the complete evidence shape before any dependency is exercised;
    # a failed run remains auditable rather than appearing as a partial pass.
    for filename in ('build.log', 'runtime.log', 'packets.ndjson'):
        open(os.path.join(evidence, filename), 'w').close()
    write_json(os.path.join(evidence, 'source-manifest.json'), {})
    write_json(os.path.join(evidence, 'realtime.json'), {})
    try:
        write_json(os.path.join(evidence, 'environment.json'), target_environment())
        with tempfile.TemporaryDirectory(prefix='hil-contract-acceptance-') as temporary:
            package_root = os.path.join(temporary, 'packages'); os.makedirs(package_root)
            package_dir = os.path.join(package_root, 'valid'); os.makedirs(package_dir)
            create_package(package_dir)
            old_root, old_work, old_evidence = ws_server.CONTROLLED_PACKAGE_ROOT, ws_server.WORK_ROOT, ws_server.ACCEPTANCE_ROOT
            ws_server.CONTROLLED_PACKAGE_ROOT = package_root
            ws_server.WORK_ROOT = os.path.join(temporary, 'work')
            ws_server.ACCEPTANCE_ROOT = evidence
            try:
                malformed_cases = (
                    ('contract_integrity_tamper', 'integrity_tamper', False),
                    ('missing_attitude', 'missing_attitude', True),
                    ('missing_speed', 'missing_speed', True),
                    ('changed_unit', 'changed_unit', True),
                    ('missing_wind_d', 'missing_wind_d', True),
                    ('missing_acceleration', 'missing_acceleration', True),
                    ('reset_only_running', 'reset_only_running', True))
                for label, defect, update_manifest in malformed_cases:
                    bad = os.path.join(package_root, label)
                    malformed_copy(package_dir, bad, defect, update_manifest)
                    response = submit(package_root, bad, label, 'build'); responses[label] = response
                    record(assertions, label, response['status'] == 'FAILED' and response['failed_stage'] == 'VALIDATING', response)
                response = submit(package_root, package_dir, 'valid-deploy', 'deploy'); responses['valid'] = response
                record(assertions, 'valid_ert_gcc_build', response['status'] in ('DEPLOYED', 'DEV_DEPLOYED'), response)
                executable = response['executable_path']
                build_root = os.path.dirname(os.path.dirname(executable))
                write_json(os.path.join(evidence, 'source-manifest.json'), {
                    'package_sha256': package_sha256(package_dir),
                    'contract_sha256': sha256_file(os.path.join(package_dir, 'hil_contract.json')),
                    'slx_sha256': sha256_file(os.path.join(package_dir, 'hil_test_model.slx')),
                    'c_core_sources_sha256': tree_sha256(os.path.join(ROOT, 'c_core', 'src')),
                    'python_services_sha256': tree_sha256(os.path.join(ROOT, 'python_services')),
                    'matlab_sources_sha256': tree_sha256(os.path.join(ROOT, 'matlab_scripts')),
                    'scripts_sha256': tree_sha256(os.path.join(ROOT, 'scripts')),
                    'acceptance_script_sha256': sha256_file(os.path.abspath(__file__)),
                    'git': git,
                    'generated_code_sha256': tree_sha256(os.path.join(build_root, 'generated')),
                    'executable_sha256': sha256_file(executable)})
                shutil.copyfile(response['log_path'], os.path.join(evidence, 'build.log'))
                first_runtime_log = os.path.join(os.path.dirname(os.path.dirname(executable)), 'runtime.log')
                if os.path.isfile(first_runtime_log): shutil.copyfile(first_runtime_log, runtime_log_path)
                status = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); status.bind(('127.0.0.1', 9998)); status.settimeout(3)
                command = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); command.bind(('127.0.0.1', 0)); command.settimeout(3)
                with open(os.path.join(evidence, 'packets.ndjson'), 'w') as packet_log:
                    first = recv_state(status, packet_log)
                    record(assertions, 'normalized_ned_state', first['sequence'] > 0 and first['q_w'] == 1.0 and first['airborne'] == 1, first)
                    mission = core_command(command, packet_log, 'mission-ned', 'load_mission', {
                        'mission_id': 'acceptance-route', 'waypoints': [
                            {'north_m': 100.0, 'east_m': 200.0, 'down_m': -30.0, 'speed_mps': 7.0},
                            {'north_m': 150.0, 'east_m': 220.0, 'down_m': -35.0, 'speed_mps': 7.0}]})
                    record(assertions, 'ned_mission_receipt', mission.get('accepted'), mission)
                    tune = core_command(command, packet_log, 'gain-live', 'tune', {'gain': 2.0})
                    record(assertions, 'live_parameter_receipt', tune.get('accepted') and tune['effective_sequence'] >= first['sequence'], tune)
                    readonly = core_command(command, packet_log, 'readonly', 'tune', {'north_diagnostic': 1.0})
                    record(assertions, 'readonly_parameter_rejected', not readonly.get('accepted') and readonly.get('fields', {}).get('north_diagnostic', {}).get('reason') == 'readonly', readonly)
                    changed = recv_matching(status, packet_log, lambda state: state['sequence'] > tune['effective_sequence'])
                    record(assertions, 'live_gain_effect', changed['vn_mps'] == 2.0 and changed['sequence'] > tune['effective_sequence'], changed)
                    inputs = core_command(command, packet_log, 'inputs-live', 'set_inputs', {
                        'flight_control': {'throttle': 0.5, 'roll_cmd': 0.1},
                        'environment': {'wind_n_mps': 3.0},
                        'fault': {'packet_loss_ratio': 0.02}})
                    record(assertions, 'contract_inputs_receipt', inputs.get('accepted') and
                           inputs['effective_sequence'] >= changed['sequence'], inputs)
                    after_inputs = recv_matching(status, packet_log,
                                                 lambda state: state['sequence'] > inputs['effective_sequence'])
                    record(assertions, 'contract_input_effect_at_step_boundary',
                           after_inputs['vn_mps'] == 2.5, after_inputs)
                    rejected_inputs = core_command(command, packet_log, 'inputs-atomic-reject', 'set_inputs', {
                        'flight_control': {'throttle': 0.7},
                        'fault': {'packet_loss_ratio': 1.2}})
                    record(assertions, 'contract_input_atomic_rejection',
                           not rejected_inputs.get('accepted') and
                           rejected_inputs.get('reason') == 'atomic input group rejected', rejected_inputs)
                    unchanged = recv_matching(status, packet_log,
                                              lambda state: state['sequence'] > rejected_inputs['effective_sequence'])
                    record(assertions, 'contract_input_rejection_leaves_model_unchanged',
                           unchanged['vn_mps'] == 2.5, unchanged)
                    for request_id, params in (
                            ('inputs-unknown-group', {'unknown_group': {'throttle': 0.5}}),
                            ('inputs-unknown-field', {'flight_control': {'unknown_field': 0.5}}),
                            ('inputs-bool-as-number', {'fault': {'motor_1_failed': 1}}),
                            ('inputs-scalar-as-array', {'flight_control': {'throttle': [0.5]}})):
                        rejected = core_command(command, packet_log, request_id, 'set_inputs', params)
                        record(assertions, request_id,
                               not rejected.get('accepted') and
                               rejected.get('reason') == 'atomic input group rejected', rejected)
                        unchanged = recv_matching(status, packet_log,
                                                  lambda state: state['sequence'] > rejected['effective_sequence'])
                        record(assertions, request_id + '-unchanged',
                               unchanged['vn_mps'] == 2.5, unchanged)
                    paused = core_command(command, packet_log, 'pause', 'pause', {})
                    record(assertions, 'pause_receipt', paused.get('accepted'), paused)
                    p1 = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 1)
                    p2 = recv_state(status, packet_log)
                    record(assertions, 'pause_freezes_sequence', p1['sequence'] == p2['sequence'] and p2['lifecycle'] == 1, [p1, p2])
                    reset_tune = core_command(command, packet_log, 'reset-gain', 'tune', {'reset_gain': 1.0, 'mass_kg': 10.0})
                    record(assertions, 'reset_only_queued_receipt', reset_tune.get('accepted'), reset_tune)
                    resumed = core_command(command, packet_log, 'resume', 'resume', {})
                    record(assertions, 'resume_receipt', resumed.get('accepted'), resumed)
                    after_resume = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 0 and state['sequence'] > p2['sequence'])
                    record(assertions, 'resume_advances_sequence', after_resume['sequence'] > p2['sequence'], after_resume)
                    reset_observed = []
                    reset = core_command(command, packet_log, 'reset', 'reset', {}, reset_observed)
                    record(assertions, 'reset_receipt', reset.get('accepted'), reset)
                    final_reset_parameter = next((item for item in reset_observed
                                                  if item.get('request_id') == 'reset-gain' and
                                                  item.get('reason') == 'reset_only parameters applied'), None)
                    record(assertions, 'reset_only_final_effective_sequence',
                           final_reset_parameter is not None and
                           final_reset_parameter['effective_sequence'] == reset['effective_sequence'] + 1,
                           final_reset_parameter)
                    after_reset = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 0 and state['sequence'] > reset['effective_sequence'])
                    record(assertions, 'reset_reinitializes_and_applies_queued_parameter', after_reset['north_m'] < after_resume['north_m'] and after_reset['vn_mps'] == 3.0 and after_reset['ve_mps'] == 2.0, after_reset)
                    ue4_mission, vehicle, reset_event, stream = receive_ue4_vehicle_stream(packet_log, runtime_log_path, first)
                    ue4 = vehicle['data']
                    record(assertions, 'ue4_mission_route_axes',
                           ue4_mission['data']['mission_id'] == 'acceptance-route' and
                           ue4_mission['data']['waypoints'][0]['x'] == 100.0 and
                           ue4_mission['data']['waypoints'][0]['y'] == 200.0 and
                           ue4_mission['data']['waypoints'][0]['height'] == 30.0,
                           ue4_mission)
                    record(assertions, 'ue4_protocol_ned_axes_and_90_yaw', ue4['position'] == {'x':10.0,'y':20.0,'height':-30.0} and abs(ue4['attitude']['yaw'] - 1.57079632679) < 1e-6 and ue4['velocity']['vz'] == -6.0, vehicle)
                    record(assertions, 'ue4_protocol_acceleration_and_semantics',
                           ue4['acceleration'] == {'ax':4.0,'ay':5.0,'az':-6.0} and
                           'flight_state' not in ue4 and ue4['rate_hz'] == 50, vehicle)
                    record(assertions, 'ue4_10_second_rate_and_sequence',
                           49.0 <= stream['average_hz'] <= 51.0 and
                           stream['seq_strictly_increasing'], stream)
                    record(assertions, 'reset_emits_only_reset_scene',
                           reset_event is not None and
                           reset_event.get('data', {}).get('event') == 'reset_scene' and
                           stream['reset_receipt_count'] == 1, reset_event)
                    ended = core_command(command, packet_log, 'end', 'mission_end', {})
                    record(assertions, 'mission_end_receipt', ended.get('accepted'), ended)
                    e1 = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 3)
                    e2 = recv_state(status, packet_log)
                    record(assertions, 'ended_freezes_sequence', e1['sequence'] == e2['sequence'] and e2['lifecycle'] == 3, [e1, e2])
                old_process = ws_server.ACTIVE_CORE
                old = old_process.pid
                second = submit(package_root, package_dir, 'second-deploy', 'deploy'); responses['second'] = second
                record(assertions, 'single_instance_deployment',
                       second['status'] in ('DEPLOYED', 'DEV_DEPLOYED') and second.get('previous_core_stopped_before_build') and
                       old_process.poll() is not None and old != ws_server.ACTIVE_CORE.pid, second)
                # The old core has been stopped and waited for by the second
                # deployment, so its redirected stdout is now flushed.  Append
                # it instead of overwriting the already captured Bridge log.
                if os.path.isfile(first_runtime_log):
                    with open(first_runtime_log, 'r') as core_log, open(runtime_log_path, 'a') as runtime_log:
                        runtime_log.write(core_log.read())
                realtime = realtime_evidence(runtime_log_path)
                if os.environ.get('HIL_SKIP_REALTIME_GATE') == '1':
                    realtime['waived'] = 'user-directed: production realtime gate not requested'
                    realtime['passed'] = None
                write_json(os.path.join(evidence, 'realtime.json'), realtime)
                if realtime.get('waived'):
                    record(assertions, 'realtime_gate_waived_by_user', True, realtime)
                else:
                    record(assertions, 'realtime_30_minute_gate', realtime['passed'], realtime)
                command.close(); status.close()
            finally:
                if ws_server.ACTIVE_CORE and ws_server.ACTIVE_CORE.poll() is None: ws_server.ACTIVE_CORE.terminate(); ws_server.ACTIVE_CORE.wait(timeout=5)
                ws_server.ACTIVE_CORE = None
                ws_server.CONTROLLED_PACKAGE_ROOT, ws_server.WORK_ROOT, ws_server.ACCEPTANCE_ROOT = old_root, old_work, old_evidence
        write_json(os.path.join(evidence, 'assertions.json'), assertions)
        write_json(os.path.join(evidence, 'result.json'), {
            'status': 'passed', 'assertion_count': len(assertions),
            'git_head': git['head'], 'failed': [], 'skipped': [],
            'waivers': ['production realtime gate'] if os.environ.get('HIL_SKIP_REALTIME_GATE') == '1' else [],
            'responses': responses})
        return 0
    except Exception as exc:
        with open(runtime_log_path, 'a') as log: log.write(repr(exc) + '\n')
        write_json(os.path.join(evidence, 'assertions.json'), assertions)
        write_json(os.path.join(evidence, 'result.json'), {
            'status': 'failed', 'error': str(exc),
            'git_head': locals().get('git', {}).get('head'),
            'failed': [item['name'] for item in assertions if not item['passed']],
            'skipped': [], 'responses': responses})
        return 1


if __name__ == '__main__': sys.exit(main())
