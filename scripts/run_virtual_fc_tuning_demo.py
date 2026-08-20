#!/usr/bin/env python3
"""Run a local evidence demo for virtual FC closed loop plus live tuning.

UE4 is intentionally not a prerequisite: the test proves the control path at
the C-core boundary (sensor snapshot -> virtual controller -> physical_uut
actuators) and proves a live parameter took effect at a C model-step sequence.
UE4 can be run separately to observe the same C-core state visually.
"""
from __future__ import print_function

import argparse
import base64
import datetime
import json
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python_services'))

from shared.ws_framing import FrameError, decode_frame, encode_frame


class DemoError(RuntimeError):
    pass


class HilWebSocketClient(object):
    """Tiny synchronous client for the project-owned WebSocket endpoint."""
    def __init__(self, host, port, timeout_s=3.0):
        self.socket = socket.create_connection((host, port), timeout_s)
        self.socket.settimeout(timeout_s)
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = ('GET / HTTP/1.1\r\nHost: {}:{}\r\nUpgrade: websocket\r\n'
                   'Connection: Upgrade\r\nSec-WebSocket-Key: {}\r\n'
                   'Sec-WebSocket-Version: 13\r\n\r\n').format(host, port, key)
        self.socket.sendall(request.encode('ascii'))
        response = self._receive_headers()
        if not response.startswith('HTTP/1.1 101 '):
            self.socket.close(); raise DemoError('WebSocket handshake failed: {}'.format(response.split('\r\n')[0]))
        self.stream = self.socket.makefile('rb')

    def _receive_headers(self):
        data = bytearray()
        while b'\r\n\r\n' not in data:
            chunk = self.socket.recv(1)
            if not chunk: raise DemoError('WebSocket closed during handshake')
            data.extend(chunk)
            if len(data) > 16384: raise DemoError('WebSocket response headers too large')
        return bytes(data).decode('ascii', 'replace')

    def command(self, cmd, params=None):
        request = {'cmd': cmd, 'params': params or {}}
        payload = json.dumps(request, separators=(',', ':')).encode('utf-8')
        self.socket.sendall(encode_frame(0x1, payload, masked=True, mask=os.urandom(4)))
        while True:
            try:
                opcode, response = decode_frame(self.stream, require_masked=False)
            except (FrameError, OSError) as exc:
                raise DemoError('WebSocket response failed: {}'.format(exc))
            if opcode == 0x9:
                self.socket.sendall(encode_frame(0xA, response, masked=True, mask=os.urandom(4))); continue
            if opcode != 0x1: raise DemoError('unexpected WebSocket opcode {}'.format(opcode))
            try: return json.loads(response.decode('utf-8'))
            except (UnicodeDecodeError, ValueError) as exc: raise DemoError('invalid JSON response: {}'.format(exc))

    def close(self):
        try:
            self.socket.sendall(encode_frame(0x8, b'', masked=True, mask=os.urandom(4)))
        except OSError:
            pass
        try: self.stream.close()
        except (AttributeError, OSError): pass
        self.socket.close()


def choose_live_parameter(registry, requested=None):
    parameters = registry.get('fields', {}).get('parameters')
    if not isinstance(parameters, list): raise DemoError('parameter registry response is malformed')
    approved = [item for item in parameters if item.get('class') == 'live' and
                item.get('review_status') == 'approved' and item.get('type') == 'double']
    if requested:
        approved = [item for item in approved if item.get('name') == requested]
        if not approved: raise DemoError('requested parameter is not an approved live double: {}'.format(requested))
    preferred = ('thrust_coefficient_n', 'mass_kg', 'motor_efficiency')
    approved.sort(key=lambda item: preferred.index(item['name']) if item.get('name') in preferred else len(preferred))
    if not approved: raise DemoError('no approved live double parameter is available')
    return approved[0]


def changed_value(parameter, scale):
    current = float(parameter['current']); minimum = float(parameter['min']); maximum = float(parameter['max'])
    candidate = current * scale if current else (minimum + maximum) * 0.5
    candidate = min(maximum, max(minimum, candidate))
    if candidate == current:
        candidate = minimum if current != minimum else maximum
    if candidate == current: raise DemoError('parameter {} has no alternate in-range value'.format(parameter['name']))
    return candidate


def _accepted(response, label):
    if response.get('accepted') is not True:
        raise DemoError('{} rejected: {}'.format(label, response.get('reason', response)))
    return response


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _vector(values, count=3):
    if not isinstance(values, (list, tuple)):
        values = []
    return ' '.join('{:.2f}'.format(_number(values[index] if index < len(values) else 0.0))
                    for index in range(count))


PHASES = {
    'preflight': ('阶段 1/5：启动前检查', '确认虚拟飞控、物理 UUT 控制源和 C 核心状态可用。'),
    'baseline': ('阶段 2/5：基线稳定（尚未调参）', '维持当前场景，采集调参前的控制与状态基线。'),
    'tune_pending': ('阶段 3/5：实时调参已下发', '参数写入已受理；等待 C 核心到达指定生效序号。'),
    'observing': ('阶段 4/5：调参后的闭环观测', '确认参数生效，同时检查飞控命令链路没有中断。'),
    'verified': ('阶段 4/5：调参结果已确认', '已核验参数值、C 核心生效边界和控制命令连续性。'),
    'restoring': ('阶段 5/5：恢复原始参数', '将演示用的临时参数恢复为开始前的值。'),
    'stopped': ('阶段 5/5：安全停止', '虚拟飞控场景已停止，演示完成。'),
}


def _phase_details(phase):
    return PHASES.get(phase, (str(phase), '正在采集实时状态。'))


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_dashboard(phase, virtual_fc, state=None, parameter=None, baseline=None):
    """Return an operator-oriented status page for the local demo."""
    closed_loop = virtual_fc.get('closed_loop') or {}
    stats = virtual_fc.get('stats') or {}
    estimate = closed_loop.get('estimate') or closed_loop.get('estimated_state') or {}
    sensors = virtual_fc.get('sensors') or closed_loop.get('sensors') or {}
    sensor_ages = (sensors.get('age_ms') or sensors.get('ages_ms') or
                   closed_loop.get('sensor_age_ms') or {})
    state = state if isinstance(state, dict) else {}
    position = (estimate.get('position_m') or estimate.get('position_ned_m') or
                estimate.get('position') or state.get('position_m', []))
    velocity = (estimate.get('velocity_mps') or estimate.get('velocity_ned_mps') or
                estimate.get('velocity') or state.get('velocity_mps', []))
    title, purpose = _phase_details(phase)
    parameter_text = '未开始；当前只采集基线。'
    effect_text = '尚未产生实时调参影响。'
    if parameter:
        original = parameter.get('original')
        current = _number(parameter.get('current'))
        effective = _as_int(parameter.get('effective_sequence'))
        if original is None:
            parameter_text = '{}={:.8g}；生效序号 {}。'.format(
                parameter.get('name', '?'), current, effective if effective is not None else '待确认')
        else:
            original = _number(original)
            change = 0.0 if original == 0.0 else (current - original) / abs(original) * 100.0
            parameter_text = '{}：{:.8g} → {:.8g}（{:+.2f}%）；生效序号 {}。'.format(
                parameter.get('name', '?'), original, current, change,
                effective if effective is not None else '待确认')
        if effective is None:
            effect_text = '写入回执未提供生效序号，不能确认模型步边界。'
        elif _as_int(state.get('sequence')) is not None and _as_int(state.get('sequence')) > effective:
            effect_text = '已生效：C 核心已跨越生效序号，在新参数下运行 {} 个模型步。'.format(
                _as_int(state.get('sequence')) - effective)
        else:
            effect_text = '等待生效：当前 C 核心序号尚未到达 {}。'.format(effective)
    age_text = ', '.join('{}={:.1f}ms'.format(name, _number(age))
                         for name, age in sorted(sensor_ages.items())) or 'not reported'
    sequence = state.get('sequence', 'not reported') if isinstance(state, dict) else 'not reported'
    command_delta = None
    if baseline:
        command_delta = int(stats.get('commands_sent', 0)) - int(baseline.get('commands_sent', 0))
    if phase == 'baseline':
        continuity = ('基线阶段新增 {} 条飞控命令。'.format(command_delta)
                      if command_delta is not None else '正在建立基线。')
    else:
        continuity = '基线尚未建立。' if command_delta is None else (
        '调参观测期间新增 {} 条飞控命令；{}。'.format(
            command_delta, '链路连续' if command_delta > 0 else '未观察到新增命令'))
    return ('\n' + '=' * 72 + '\n{title}\n'
            '目的：{purpose}\n'
            '运行状态：virtual_fc={running} | 机型={vehicle} | 场景={scenario}\n'
            '飞行估计：位置 NED[m]=({position}) | 速度 NED[m/s]=({velocity})\n'
            '传感器新鲜度：{ages}\n'
            '控制链路：已发送={sent} | 拒绝={rejected} | 失效保护={failsafe}\n'
            'C 核心状态序号：{sequence}\n'
            '实时调参：{parameter}\n'
            '调参影响：{effect}\n'
            '连续性结论：{continuity}\n' + '=' * 72).format(
                title=title, purpose=purpose, running=virtual_fc.get('running', False),
                vehicle=(virtual_fc.get('vehicle') or {}).get('vehicle_kind',
                    virtual_fc.get('vehicle_kind', virtual_fc.get('model', 'unknown'))),
                scenario=virtual_fc.get('scenario', 'none'), position=_vector(position), velocity=_vector(velocity),
                ages=age_text, sent=stats.get('commands_sent', 0),
                rejected=stats.get('commands_rejected', 0), failsafe=stats.get('failsafe_events', 0),
                parameter=parameter_text, sequence=sequence, effect=effect_text,
                continuity=continuity)


def show_dashboard(output, phase, virtual_fc, state=None, parameter=None, baseline=None, clear=False):
    page = format_dashboard(phase, virtual_fc, state, parameter, baseline)
    if clear:
        output.write('\033[2J\033[H')
    output.write(page + '\n')
    output.flush()


def wait_with_dashboard(client, duration_s, phase, parameter=None, baseline=None, interval_s=0.5,
                        sleep=time.sleep, output=None, clear=False, required_sequence=None,
                        effective_timeout_s=3.0):
    """Wait for samples and, when requested, prove the model-step boundary crossed."""
    if output is None:
        output = sys.stdout
    deadline = time.monotonic() + duration_s
    effective_deadline = time.monotonic() + max(duration_s, effective_timeout_s)
    first = True
    last_sequence = None
    while (first or time.monotonic() < deadline or
           (required_sequence is not None and (last_sequence is None or last_sequence <= required_sequence)
            and time.monotonic() < effective_deadline)):
        first = False
        virtual = _accepted(client.command('virtual_fc_status'), 'virtual FC status during {}'.format(phase))['virtual_fc']
        state = client.command('get_state')
        last_sequence = _as_int(state.get('sequence')) if isinstance(state, dict) else None
        show_dashboard(output, phase, virtual, state, parameter, baseline, clear=clear)
        active_deadline = effective_deadline if (required_sequence is not None and
            (last_sequence is None or last_sequence <= required_sequence)) else deadline
        remaining = active_deadline - time.monotonic()
        if remaining <= 0.0:
            break
        sleep(min(interval_s, remaining))
    return virtual, state


def wait_for_sequence(client, required_sequence, interval_s=0.5, sleep=time.sleep,
                      timeout_s=3.0):
    """Wait until a C-core state strictly after a command's effective sequence."""
    deadline = time.monotonic() + timeout_s
    state = client.command('get_state')
    while not isinstance(state, dict) or _as_int(state.get('sequence')) is None or \
            _as_int(state.get('sequence')) <= required_sequence:
        if time.monotonic() >= deadline:
            raise DemoError('C-core state did not cross effective sequence {}'.format(required_sequence))
        sleep(min(interval_s, max(0.0, deadline - time.monotonic())))
        state = client.command('get_state')
    return state


def run_demo(client, scenario='hover', parameter_name=None, scale=1.02, settle_s=1.0,
             sleep=time.sleep, dashboard_interval_s=0.5, output=None, dashboard=True,
             effective_timeout_s=3.0):
    evidence = {'started_at': datetime.datetime.utcnow().isoformat() + 'Z',
                'ue4_required': False, 'scenario': scenario, 'steps': []}
    virtual = _accepted(client.command('virtual_fc_status'), 'virtual FC status')['virtual_fc']
    evidence['steps'].append({'virtual_fc_before': virtual})
    if not virtual.get('running'):
        raise DemoError('virtual_quad_fc is not enabled/running')
    if dashboard:
        show_dashboard(output or sys.stdout, 'preflight', virtual, clear=False)
    _accepted(client.command('select_control_source', {'source': 'physical_uut'}), 'select physical_uut')
    started = _accepted(client.command('virtual_fc_start', {'scenario': scenario}), 'start virtual FC scenario')
    evidence['steps'].append({'scenario_started': started})
    if dashboard:
        virtual, before_state = wait_with_dashboard(client, settle_s, 'baseline',
            baseline={'commands_sent': virtual.get('stats', {}).get('commands_sent', 0)},
            interval_s=dashboard_interval_s, sleep=sleep, output=output,
            clear=getattr(output or sys.stdout, 'isatty', lambda: False)())
    else:
        sleep(settle_s); before_state = client.command('get_state')
    registry = _accepted(client.command('get_parameter_registry'), 'get parameter registry')
    parameter = choose_live_parameter(registry, parameter_name)
    original = float(parameter['current']); tuned = changed_value(parameter, scale)
    tune = _accepted(client.command('tune', {parameter['name']: tuned}), 'live tune')
    effective_sequence = tune.get('effective_sequence')
    if not isinstance(effective_sequence, int): raise DemoError('tune receipt lacks effective_sequence')
    live_parameter = {'name': parameter['name'], 'original': original, 'current': tuned,
                      'effective_sequence': effective_sequence}
    baseline = {'commands_sent': virtual.get('stats', {}).get('commands_sent', 0)}
    if dashboard:
        show_dashboard(output or sys.stdout, 'tune_pending', virtual, before_state, live_parameter,
                       baseline=baseline, clear=False)
    if dashboard:
        virtual_after, after_state = wait_with_dashboard(client, settle_s, 'observing',
            live_parameter, baseline, dashboard_interval_s, sleep, output,
            getattr(output or sys.stdout, 'isatty', lambda: False)(), effective_sequence,
            effective_timeout_s)
    else:
        sleep(settle_s); after_state = client.command('get_state')
    after_registry = _accepted(client.command('get_parameter_registry'), 'verify parameter registry')
    matching = [item for item in after_registry['fields']['parameters'] if item.get('name') == parameter['name']]
    if len(matching) != 1 or abs(float(matching[0]['current']) - tuned) > 1.0e-9 * max(1.0, abs(tuned)):
        raise DemoError('live parameter current value did not update')
    if not isinstance(after_state, dict) or after_state.get('sequence', -1) <= effective_sequence:
        raise DemoError('no C-core state observed after live tune effective sequence')
    if not dashboard:
        virtual_after = _accepted(client.command('virtual_fc_status'), 'virtual FC status after tune')['virtual_fc']
    command_count = virtual_after.get('stats', {}).get('commands_sent', 0)
    if command_count <= virtual.get('stats', {}).get('commands_sent', 0):
        raise DemoError('virtual FC did not continue sending actuator commands during tune')
    evidence['parameter'] = {'name': parameter['name'], 'original': original, 'tuned': tuned,
                             'effective_sequence': effective_sequence}
    evidence['state_before'] = before_state; evidence['state_after'] = after_state
    evidence['virtual_fc_after'] = virtual_after
    if dashboard:
        show_dashboard(output or sys.stdout, 'verified', virtual_after, after_state, live_parameter,
                       baseline=baseline, clear=False)
    restore = client.command('tune', {parameter['name']: original})
    evidence['restore'] = restore
    if restore.get('accepted') is not True:
        raise DemoError('parameter restore rejected: {}'.format(restore.get('reason')))
    restore_sequence = restore.get('effective_sequence')
    restore_parameter = {'name': parameter['name'], 'original': tuned, 'current': original,
                         'effective_sequence': restore_sequence}
    if isinstance(restore_sequence, int):
        if dashboard:
            _restore_virtual, restore_state = wait_with_dashboard(
                client, 0.0, 'restoring', restore_parameter, baseline, dashboard_interval_s,
                sleep, output, getattr(output or sys.stdout, 'isatty', lambda: False)(), restore_sequence,
                effective_timeout_s)
        else:
            restore_state = wait_for_sequence(client, restore_sequence, dashboard_interval_s,
                                              sleep, effective_timeout_s)
    else:
        restore_state = client.command('get_state')
    evidence['restore_state'] = restore_state
    if isinstance(restore_sequence, int) and restore_state.get('sequence', -1) < restore_sequence:
        raise DemoError('parameter restore has not reached its C-core effective sequence')
    if dashboard and not isinstance(restore_sequence, int):
        show_dashboard(output or sys.stdout, 'restoring', virtual_after, restore_state,
                       restore_parameter, baseline=baseline, clear=False)
    stopped = client.command('virtual_fc_stop')
    evidence['stop'] = stopped
    if stopped.get('accepted') is not True:
        raise DemoError('virtual FC stop rejected: {}'.format(stopped.get('reason')))
    if dashboard:
        show_dashboard(output or sys.stdout, 'stopped', dict(virtual_after, running=False), restore_state,
                       restore_parameter, baseline=baseline, clear=False)
    evidence['completed_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
    return evidence


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Virtual FC + live parameter tuning evidence demo (UE4 not required)')
    parser.add_argument('--ws-host', default='127.0.0.1')
    parser.add_argument('--ws-port', type=int, default=8080)
    parser.add_argument('--scenario', default='hover')
    parser.add_argument('--parameter', help='approved live double parameter; auto-select when omitted')
    parser.add_argument('--scale', type=float, default=1.02, help='temporary multiplicative parameter adjustment')
    parser.add_argument('--settle-s', type=float, default=1.0)
    parser.add_argument('--dashboard-interval-s', type=float, default=0.5,
                        help='terminal dashboard refresh interval during each settle period')
    parser.add_argument('--effective-timeout-s', type=float, default=3.0,
                        help='maximum wait for C core to cross the tune effective sequence')
    parser.add_argument('--no-dashboard', action='store_true', help='suppress periodic terminal dashboard')
    parser.add_argument('--report', help='JSON evidence path (default runtime/virtual_fc_tuning_demo/<UTC>.json)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if (not 1 <= args.ws_port <= 65535 or args.scale <= 0.0 or args.settle_s < 0.0 or
            args.dashboard_interval_s <= 0.0 or args.effective_timeout_s < 0.0):
        print('invalid command-line argument', file=sys.stderr); return 2
    client = None; failed = True
    try:
        client = HilWebSocketClient(args.ws_host, args.ws_port)
        evidence = run_demo(client, args.scenario, args.parameter, args.scale, args.settle_s,
                            dashboard_interval_s=args.dashboard_interval_s,
                            dashboard=not args.no_dashboard,
                            effective_timeout_s=args.effective_timeout_s)
        report = args.report or os.path.join(ROOT, 'runtime', 'virtual_fc_tuning_demo',
                                             datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ') + '.json')
        parent = os.path.dirname(os.path.abspath(report))
        if not os.path.isdir(parent): os.makedirs(parent)
        with open(report, 'w') as output: json.dump(evidence, output, indent=2, sort_keys=True); output.write('\n')
        print('DEMO PASSED: live parameter {} applied at sequence {} while virtual FC remained active.'.format(
            evidence['parameter']['name'], evidence['parameter']['effective_sequence']))
        print('UE4 was not required. Evidence: {}'.format(report))
        failed = False
        return 0
    except (DemoError, OSError, ValueError) as exc:
        print('DEMO FAILED: {}'.format(exc), file=sys.stderr); return 1
    finally:
        if client is not None:
            if failed:
                # A failed demo must not leave an armed scripted/closed-loop
                # command running.  This is best effort because the original
                # failure is the primary diagnostic.
                try: client.command('virtual_fc_stop')
                except (DemoError, OSError, ValueError): pass
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
