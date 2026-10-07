"""Bounded offline scenario timetable, not a clock, authorization or executor."""

import copy
from dataclasses import dataclass, replace
import heapq
import json
import math

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from input_simulator.waveform import WaveformSampler
from input_simulator.assertion import AssertionSpec


MAX_STEP = (1 << 32) - 1
MAX_PLAN_BYTES = 16 * 1024 * 1024
MODELS = ('quadrotor_hil', 'multirotor_6_hil', 'fixed_wing_hil')


def _snapshot(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')


def _key(event):
    return event['at_step'], event['priority'], event['event_id']


def _unique(values, label):
    if len(values) != len(set(values)):
        raise ICDError('RESOURCE', 'duplicate scenario ' + label)


def _integer(value, label):
    if type(value) is not int:
        raise ICDError('SCHEMA', label + ' must be an integer, not bool or float')


def _targets(rows, stimulus):
    mid = stimulus['message_id']
    if mid not in range(7, 20):
        return ()
    group = ('flight_control' if mid in (7,8,9,14,15,16) else 'environment' if mid == 10 else
             'fault' if mid in (11,12,13) else 'parameters')
    binding = {r['path'].split('.')[1]: r for r in rows if r['path'].startswith(group + '.')}
    if set(binding) != set(stimulus['payload']):
        raise ICDError('MODEL', 'scenario message must be a complete frozen mapped snapshot')
    result = []
    for name, row in binding.items():
        target = row['model_id'] + '.' + row['target_field']
        value = stimulus['payload'][name]
        result.extend(target + f'[{index}]' for index in range(row['dimension'])) if type(value) is list else result.append(target)
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class ScheduledAction:
    step: int
    priority: int
    event_id: str
    link_id: str
    kind: str
    index: int
    event_json: bytes
    stimulus_json: bytes | None
    writable_targets: tuple[str, ...]

    @property
    def event(self):
        return loads(self.event_json)

    @property
    def stimulus(self):
        return None if self.stimulus_json is None else loads(self.stimulus_json)

    @property
    def execution_ready(self):
        return False

    @property
    def blocks_following_events(self):
        return self.kind in ('WAIT', 'END_CLEANUP')

    @property
    def needs_runtime_handler(self):
        return self.kind not in ('SEND', 'FAULT', 'WAVEFORM', 'PERIODIC_START', 'PERIODIC_SAMPLE')


@dataclass(frozen=True, slots=True)
class _Stream:
    first: int
    period: int
    count: int
    priority: int
    event_id: str
    event_json: bytes
    targets: tuple[str, ...]
    sampler: WaveformSampler | None = None
    index_base: int = 0

    @property
    def last(self):
        return self.first + (self.count - 1) * self.period

    def action(self, index):
        event = loads(self.event_json)
        step = self.first + index * self.period
        ordinal = self.index_base + index
        stimulus = self.sampler.sample(step) if self.sampler is not None else event.get('stimulus')
        kind = event['type']
        if kind == 'PERIODIC_START' and ordinal:
            kind = 'PERIODIC_SAMPLE'
        return ScheduledAction(step, self.priority, self.event_id, event['link_id'], kind, ordinal,
                               self.event_json, None if stimulus is None else _snapshot(stimulus), self.targets)


def _clip(stream, boundary):
    if boundary is None:
        return stream
    last = boundary[0] if (stream.priority, stream.event_id) < boundary[1:] else boundary[0] - 1
    count = min(stream.count, (last - stream.first) // stream.period + 1)
    return None if count <= 0 else replace(stream, count=count)


def _intersection(a, b):
    low, high = max(a.first, b.first), min(a.last, b.last)
    if low > high:
        return None
    # Solve the two finite arithmetic progressions without enumerating model steps.
    divisor = math.gcd(a.period, b.period)
    difference = b.first - a.first
    if difference % divisor:
        return None
    modulus = b.period // divisor
    k = 0 if modulus == 1 else (difference // divisor * pow(a.period // divisor, -1, modulus)) % modulus
    first = a.first + a.period * k
    stride = a.period * modulus
    first += max(0, (low - first + stride - 1) // stride) * stride
    return first if first <= high else None


def _collisions(streams, maximum):
    buckets = {}
    for index, stream in enumerate(streams):
        for target in stream.targets:
            buckets.setdefault(target, []).append(index)
    checked = set()
    for target, indexes in buckets.items():
        active = []
        for index in sorted(indexes, key=lambda i: streams[i].first):
            stream = streams[index]
            active = [i for i in active if streams[i].last >= stream.first]
            for previous in active:
                pair = min(index, previous), max(index, previous)
                if pair in checked:
                    continue
                if len(checked) >= maximum:
                    raise ICDError('CAPACITY', 'scenario collision comparison capacity exceeded')
                checked.add(pair)
                collision = _intersection(stream, streams[previous])
                if collision is not None:
                    raise ICDError('RESOURCE', f'same writable target {target} at step {collision}: '
                                   f'{stream.event_id} and {streams[previous].event_id}')
            active.append(index)


@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    scenario_json: bytes
    baseline_sha256: str
    model_id: str
    _streams: tuple[_Stream, ...]
    waveforms: tuple[WaveformSampler, ...]
    pending_checks: tuple[str, ...]
    assertions: tuple[AssertionSpec, ...] = ()

    @classmethod
    def compile(cls, contract, scenario, *, model_id, history_id=None, max_collision_checks=100000):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError('HASH', 'scenario needs an original verified contract')
        if type(model_id) is not str or model_id not in MODELS:
            raise ICDError('MODEL', 'scenario needs an explicit frozen model')
        if type(max_collision_checks) is not int or not 1 <= max_collision_checks <= 1000000:
            raise ICDError('CAPACITY', 'bounded positive collision comparison limit required')
        scenario = copy.deepcopy(scenario)
        contract.validate_source_definition('ScenarioSource', scenario)
        for name in ('version', 'seed'):
            _integer(scenario[name], name)
        _unique([e['event_id'] for e in scenario['events']], 'event ID')
        events = sorted(scenario['events'], key=_key)
        assertions = list(scenario['assertions'])
        senders = {}
        stops = {}
        waves = {}
        pending = {'ACTUAL_EVENT_EXECUTION_AND_WAIT_PROBES', 'CURRENT_STANDARD_AUTHORIZATION_AND_TOOLS',
                   'MODEL_STEP_CLOCK_AND_TIMING', 'NINE_PART_CLEANUP_AND_PERSISTENT_EVIDENCE'}
        end = None
        for event in events:
            for name in ('at_step', 'priority', 'period_steps', 'count', 'duration_steps', 'sample_period_steps'):
                if name in event:
                    _integer(event[name], name)
            if end is not None:
                raise ICDError('RESOURCE', 'END_CLEANUP must be the last sorted static event')
            kind = event['type']
            if 'stimulus' in event:
                contract.validate_stimulus(event['stimulus'], model_id=model_id)
            if 'assertion' in event:
                assertions.append(event['assertion'])
            if kind == 'FAULT' and event['stimulus']['message_id'] not in (11,12,13,26,45):
                raise ICDError('RESOURCE', 'FAULT requires its defined fault message')
            if kind == 'WAVEFORM':
                waves[event['event_id']] = WaveformSampler.compile(contract, event, model_id=model_id)
            elif kind == 'PERIODIC_START':
                sender = event['sender_id']
                if sender in senders:
                    raise ICDError('RESOURCE', 'sender ID must have exactly one start')
                senders[sender] = event['link_id']
                if event['at_step'] + (event['count'] - 1) * event['period_steps'] > MAX_STEP:
                    raise ICDError('RANGE', 'periodic final step exceeds uint32')
            elif kind == 'PERIODIC_STOP':
                sender = event['sender_id']
                if sender not in senders or sender in stops or senders[sender] != event['link_id']:
                    raise ICDError('RESOURCE', 'stop needs prior start on the same original tool')
                stops[sender] = _key(event)
            elif kind == 'REPLAY':
                if history_id is None or event['history_id'] != history_id:
                    raise ICDError('RESOURCE', 'replay must reference the provided history')
                policy = event['policy']
                for name in ('repeat_count', 'repeat_gap_steps'):
                    _integer(policy[name], name)
                if int(policy['start_offset_ns']) > int(policy['end_offset_ns']):
                    raise ICDError('RESOURCE', 'replay starts after its end')
                _unique(policy['rewrite_fields'], 'replay rewrite field')
                pending.add('REPLAY_WRITABLE_TARGETS_AND_EXPANSION')
            elif kind == 'NEGATIVE_SEND':
                if event['authorization_case_id'] not in ('T02','T05','T06'):
                    raise ICDError('AUTHORIZATION', 'negative case must be a defined T02/T05/T06 case')
                for name in ('xor_mask', 'sequence', 'session_id', 'target_step', 'remove_tail_bytes'):
                    if name in event['mutation']:
                        _integer(event['mutation'][name], name)
                pending.add('ENABLED_NEGATIVE_CASE_AUTHORIZATION_AND_WIRE_MUTATION')
            elif kind == 'END_CLEANUP':
                end = _key(event)
        _unique([a['assertion_id'] for a in assertions], 'assertion ID')
        for assertion in assertions:
            for name in ('message_id', 'timeout_steps', 'sample_count'):
                _integer(assertion[name], name)
            contract.entry(assertion['message_id'])
            if type(assertion['expected']) in (bool, str) and (assertion['tolerance'] != 0 or
                    assertion['operator'] not in ('EQ','NE','EVENTUALLY')):
                raise ICDError('RESOURCE', 'non-numeric assertion cannot use tolerance or order')
        compiled_assertions = tuple(AssertionSpec.compile(contract, a, model_id=model_id) for a in assertions)
        raw = _snapshot(scenario)
        events_json = {e['event_id']: _snapshot(e) for e in events}
        size = len(raw) + len(canonicalize(scenario)) + sum(map(len, events_json.values()))
        size += sum(len(w._event_json) for w in waves.values())
        size += sum(len(a.assertion_json) for a in compiled_assertions)
        if size > MAX_PLAN_BYTES:
            raise ICDError('CAPACITY', 'scenario immutable snapshots exceed bounded capacity')
        rows = [r for r in contract.catalogue['model_bindings'] if r['model_id'] == model_id]
        streams = []
        for event in events:
            kind = event['type']
            target = _targets(rows, event['stimulus']) if 'stimulus' in event else ()
            if 'stimulus' in event and not target:
                pending.add(f"WRITABLE_TARGETS:{event['stimulus']['message_id']}")
            stream = _Stream(event['at_step'], 1, 1, event['priority'], event['event_id'],
                             events_json[event['event_id']], target, waves.get(event['event_id']))
            boundary = end if kind != 'END_CLEANUP' else None
            extra = None
            if kind == 'PERIODIC_START':
                stream = replace(stream, period=event['period_steps'], count=event['count'])
                stop = stops.get(event['sender_id'])
                boundary = min(b for b in (boundary, stop) if b is not None) if stop is not None else boundary
            elif kind == 'WAVEFORM':
                period = event['sample_period_steps']
                count = event['duration_steps'] // period + 1
                stream = replace(stream, period=period, count=count)
                if event['duration_steps'] % period:
                    extra = replace(stream, first=event['at_step'] + event['duration_steps'], period=1,
                                    count=1, index_base=count)
            for candidate in (stream, extra):
                if candidate is not None:
                    clipped = _clip(candidate, boundary)
                    if clipped is not None:
                        streams.append(clipped)
        _collisions(streams, max_collision_checks)
        return cls(raw, contract.baseline_sha256, model_id, tuple(streams), tuple(waves.values()),
                   tuple(sorted(pending)), compiled_assertions)

    @property
    def scenario(self):
        return loads(self.scenario_json)

    @property
    def execution_ready(self):
        return False

    @property
    def stream_count(self):
        return len(self._streams)

    @property
    def action_count(self):
        return sum(s.count for s in self._streams)

    def iter_actions(self, *, start_step=0, end_step=MAX_STEP, max_actions=100000):
        """Inspect a bounded offline window. Never send this iterator as an executable run."""
        if (type(start_step) is not int or type(end_step) is not int or
                not 0 <= start_step <= end_step <= MAX_STEP):
            raise ICDError('SCHEMA', 'inspection interval must be ordered uint32 model steps')
        if type(max_actions) is not int or not 1 <= max_actions <= 1000000:
            raise ICDError('CAPACITY', 'bounded positive action limit required')
        heap = []
        total = 0
        for number, stream in enumerate(self._streams):
            first = max(0, (start_step - stream.first + stream.period - 1) // stream.period)
            last = min(stream.count - 1, (end_step - stream.first) // stream.period)
            if first > last:
                continue
            total += last - first + 1
            if total > max_actions:
                raise ICDError('CAPACITY', 'requested timetable exceeds action capacity; no partial output')
            heapq.heappush(heap, (stream.first + first*stream.period, stream.priority,
                                 stream.event_id, number, first, last))
        while heap:
            step, priority, event_id, number, index, last = heapq.heappop(heap)
            stream = self._streams[number]
            yield stream.action(index)
            if index < last:
                heapq.heappush(heap, (step + stream.period, priority, event_id, number, index + 1, last))
