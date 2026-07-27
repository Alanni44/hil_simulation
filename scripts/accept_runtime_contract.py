#!/usr/bin/env python3
"""Ubuntu target acceptance for the 2026-07-25 runtime contract.

The script never marks a skipped dependency or assertion as passed.  It writes
the evidence layout required by the design document and exits non-zero unless
every build, packet, adapter, lifecycle and deployment check succeeds.
"""
from __future__ import print_function
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


def core_command(command_socket, packet_log, request_id, cmd, params):
    command = {'request_id': request_id, 'cmd': cmd, 'params': params}
    packet(packet_log, 'command', command)
    command_socket.sendto(json.dumps(command).encode('utf-8'), ('127.0.0.1', 9997))
    while True:
        data, _ = command_socket.recvfrom(65536)
        receipt = json.loads(data.decode('utf-8'))
        packet(packet_log, 'receipt', receipt)
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


def receive_ue4_vehicle_packet(packet_log, source_state):
    """Run a TCP UE4 protocol peer and capture an actual bridge vehicle_state."""
    known = dict(source_state)
    known.update({'sequence': 999, 'sim_time_s': 1.0, 'north_m': 10.0, 'east_m': 20.0,
                  'down_m': 30.0, 'vn_mps': 4.0, 've_mps': 5.0, 'vd_mps': 6.0,
                  'q_w': 0.7071067811865476, 'q_x': 0.0, 'q_y': 0.0,
                  'q_z': 0.7071067811865476, 'p_radps': 0.0, 'q_radps': 0.0,
                  'r_radps': 0.0, 'airborne': 1, 'lifecycle': 0, 'reserved': 0})
    state_cache.update(struct.pack(FLIGHT_STATE_FORMAT, *[
        known[key] for key in ('version', 'sequence', 'sim_time_s', 'north_m', 'east_m', 'down_m',
                               'vn_mps', 've_mps', 'vd_mps', 'q_w', 'q_x', 'q_y', 'q_z',
                               'p_radps', 'q_radps', 'r_radps', 'airborne', 'lifecycle', 'reserved')]))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 5001)); server.listen(1); server.settimeout(8)
    bridge = ws_server.bridge
    old_host, old_port = bridge.UE4_HOST, bridge.UE4_PORT
    bridge.UE4_HOST, bridge.UE4_PORT, bridge._running = '127.0.0.1', 5001, True
    try:
        bridge.start_bridge()
        peer, _ = server.accept(); peer.settimeout(5)
        hello = _tcp_recv_frame(peer)
        _tcp_send_frame(peer, {'type': 'ack', 'data': {'accepted': True, 'ref_type': 'hello'}})
        mission = _tcp_recv_frame(peer)
        _tcp_send_frame(peer, {'type': 'ack', 'data': {'accepted': True, 'ref_type': 'mission_plan'}})
        vehicle = _tcp_recv_frame(peer)
        packet(packet_log, 'ue4_protocol_hello', hello)
        packet(packet_log, 'ue4_protocol_mission_plan', mission)
        packet(packet_log, 'ue4_protocol_vehicle_state', vehicle)
        peer.close()
        return vehicle
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


def malformed_copy(source, destination, output_to_remove=None, unit_to_remove=None):
    shutil.copytree(source, destination)
    contract_path = os.path.join(destination, 'hil_contract.json')
    contract = json.load(open(contract_path))
    if output_to_remove: del contract['state']['outputs'][output_to_remove]
    if unit_to_remove: del contract['state']['units'][unit_to_remove]
    with open(contract_path, 'w') as target: json.dump(contract, target)
    subprocess.check_call([sys.executable, os.path.join(ROOT, 'scripts', 'create_acceptance_package.py'), destination])
    # restore the intentional defect after manifest regeneration.
    with open(contract_path, 'w') as target: json.dump(contract, target)
    # only the payload checksum needs an update: malformed contract must pass
    # integrity validation and fail semantic validation.
    manifest_path = os.path.join(destination, 'package_manifest.json')
    manifest = json.load(open(manifest_path)); manifest['files']['hil_contract.json'] = sha256_file(contract_path)
    manifest['package_sha256'] = package_sha256(destination)
    write_json(manifest_path, manifest)


def main():
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
    try:
        write_json(os.path.join(evidence, 'environment.json'), {
            'platform': platform.platform(), 'python': sys.version,
            'gcc': subprocess.check_output(['gcc', '--version']).decode().splitlines()[0],
            'matlab': ws_server._matlab_binary()})
        with tempfile.TemporaryDirectory(prefix='hil-contract-acceptance-') as temporary:
            package_root = os.path.join(temporary, 'packages'); os.makedirs(package_root)
            package_dir = os.path.join(package_root, 'valid'); os.makedirs(package_dir)
            create_package(package_dir)
            old_root, old_work, old_evidence = ws_server.CONTROLLED_PACKAGE_ROOT, ws_server.WORK_ROOT, ws_server.ACCEPTANCE_ROOT
            ws_server.CONTROLLED_PACKAGE_ROOT = package_root
            ws_server.WORK_ROOT = os.path.join(temporary, 'work')
            ws_server.ACCEPTANCE_ROOT = evidence
            try:
                for label, output, unit in (('missing_attitude', 'q_z', None),
                                            ('missing_speed', 'vd_mps', None),
                                            ('missing_unit', None, 'north_m')):
                    bad = os.path.join(package_root, label)
                    malformed_copy(package_dir, bad, output, unit)
                    response = submit(package_root, bad, label, 'build'); responses[label] = response
                    record(assertions, label, response['status'] == 'FAILED' and response['failed_stage'] == 'VALIDATING', response)
                response = submit(package_root, package_dir, 'valid-deploy', 'deploy'); responses['valid'] = response
                record(assertions, 'valid_ert_gcc_build', response['status'] == 'DEPLOYED', response)
                executable = response['executable_path']
                build_root = os.path.dirname(os.path.dirname(executable))
                write_json(os.path.join(evidence, 'source-manifest.json'), {
                    'package_sha256': package_sha256(package_dir),
                    'contract_sha256': sha256_file(os.path.join(package_dir, 'hil_contract.json')),
                    'slx_sha256': sha256_file(os.path.join(package_dir, 'hil_test_model.slx')),
                    'c_core_sources_sha256': tree_sha256(os.path.join(ROOT, 'c_core', 'src')),
                    'matlab_sources_sha256': tree_sha256(os.path.join(ROOT, 'matlab_scripts')),
                    'generated_code_sha256': tree_sha256(os.path.join(build_root, 'generated')),
                    'executable_sha256': sha256_file(executable)})
                shutil.copyfile(response['log_path'], os.path.join(evidence, 'build.log'))
                status = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); status.bind(('127.0.0.1', 9998)); status.settimeout(3)
                command = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); command.bind(('127.0.0.1', 0)); command.settimeout(3)
                with open(os.path.join(evidence, 'packets.ndjson'), 'w') as packet_log:
                    first = recv_state(status, packet_log)
                    record(assertions, 'normalized_ned_state', first['sequence'] > 0 and first['q_w'] == 1.0 and first['airborne'] == 1, first)
                    tune = core_command(command, packet_log, 'gain-live', 'tune', {'gain': 2.0})
                    record(assertions, 'live_parameter_receipt', tune.get('accepted') and tune['effective_sequence'] >= first['sequence'], tune)
                    readonly = core_command(command, packet_log, 'readonly', 'tune', {'north_diagnostic': 1.0})
                    record(assertions, 'readonly_parameter_rejected', not readonly.get('accepted') and readonly.get('fields', {}).get('north_diagnostic', {}).get('reason') == 'readonly', readonly)
                    changed = recv_matching(status, packet_log, lambda state: state['sequence'] > tune['effective_sequence'])
                    record(assertions, 'live_gain_effect', changed['vn_mps'] == 2.0 and changed['sequence'] > tune['effective_sequence'], changed)
                    paused = core_command(command, packet_log, 'pause', 'pause', {})
                    record(assertions, 'pause_receipt', paused.get('accepted'), paused)
                    p1 = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 1)
                    p2 = recv_state(status, packet_log)
                    record(assertions, 'pause_freezes_sequence', p1['sequence'] == p2['sequence'] and p2['lifecycle'] == 1, [p1, p2])
                    reset_tune = core_command(command, packet_log, 'reset-gain', 'tune', {'reset_gain': 1.0})
                    record(assertions, 'reset_only_queued_receipt', reset_tune.get('accepted'), reset_tune)
                    resumed = core_command(command, packet_log, 'resume', 'resume', {})
                    record(assertions, 'resume_receipt', resumed.get('accepted'), resumed)
                    after_resume = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 0 and state['sequence'] > p2['sequence'])
                    record(assertions, 'resume_advances_sequence', after_resume['sequence'] > p2['sequence'], after_resume)
                    reset = core_command(command, packet_log, 'reset', 'reset', {})
                    record(assertions, 'reset_receipt', reset.get('accepted'), reset)
                    after_reset = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 0 and state['sequence'] > reset['effective_sequence'])
                    record(assertions, 'reset_reinitializes_and_applies_queued_parameter', after_reset['north_m'] < after_resume['north_m'] and after_reset['vn_mps'] == 3.0, after_reset)
                    ended = core_command(command, packet_log, 'end', 'mission_end', {})
                    record(assertions, 'mission_end_receipt', ended.get('accepted'), ended)
                    e1 = recv_matching(status, packet_log, lambda state: state['lifecycle'] == 3)
                    e2 = recv_state(status, packet_log)
                    record(assertions, 'ended_freezes_sequence', e1['sequence'] == e2['sequence'] and e2['lifecycle'] == 3, [e1, e2])
                    vehicle = receive_ue4_vehicle_packet(packet_log, first)
                    ue4 = vehicle['data']
                    record(assertions, 'ue4_protocol_ned_axes_and_90_yaw', ue4['position'] == {'x':10.0,'y':20.0,'height':-30.0} and abs(ue4['attitude']['yaw'] - 1.57079632679) < 1e-6 and ue4['velocity']['vz'] == -6.0, vehicle)
                old = ws_server.ACTIVE_CORE.pid
                second = submit(package_root, package_dir, 'second-deploy', 'deploy'); responses['second'] = second
                record(assertions, 'single_instance_deployment', second['status'] == 'DEPLOYED' and old != ws_server.ACTIVE_CORE.pid, second)
                first_runtime_log = os.path.join(os.path.dirname(os.path.dirname(executable)), 'runtime.log')
                if os.path.isfile(first_runtime_log): shutil.copyfile(first_runtime_log, runtime_log_path)
                else: open(runtime_log_path, 'w').close()
                command.close(); status.close()
            finally:
                if ws_server.ACTIVE_CORE and ws_server.ACTIVE_CORE.poll() is None: ws_server.ACTIVE_CORE.terminate(); ws_server.ACTIVE_CORE.wait(timeout=5)
                ws_server.ACTIVE_CORE = None
                ws_server.CONTROLLED_PACKAGE_ROOT, ws_server.WORK_ROOT, ws_server.ACCEPTANCE_ROOT = old_root, old_work, old_evidence
        write_json(os.path.join(evidence, 'assertions.json'), assertions)
        write_json(os.path.join(evidence, 'result.json'), {'status': 'passed', 'responses': responses})
        return 0
    except Exception as exc:
        with open(runtime_log_path, 'a') as log: log.write(repr(exc) + '\n')
        write_json(os.path.join(evidence, 'assertions.json'), assertions)
        write_json(os.path.join(evidence, 'result.json'), {'status': 'failed', 'error': str(exc), 'responses': responses})
        return 1


if __name__ == '__main__': sys.exit(main())
