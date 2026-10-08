"""Frozen model-step waveform values, not a clock, sender or model consumer."""

import copy
from dataclasses import dataclass
import json
import math
import re

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads


FIELD = re.compile(r'([a-z][a-z0-9_]*)(?:\[(0|[1-9][0-9]*)\])?')
MAX_STEP = 0xffffffff


def _phase(wave, elapsed):
    t = elapsed * 0.001
    if wave['kind'] == 'SINE':
        cycles = wave['frequency_hz'] * t
    else:
        duration = wave['duration_steps'] * 0.001
        t = min(t, duration)
        cycles = wave['start_frequency_hz']*t + (wave['end_frequency_hz']-wave['start_frequency_hz'])*t*t/(2*duration)
    return math.tau * cycles + wave['phase_rad']


def _value(wave, elapsed):
    kind = wave['kind']
    if kind == 'CONSTANT':
        return wave['value']
    if kind == 'STEP':
        return wave['before'] if elapsed < wave['change_step'] else wave['after']
    if kind == 'RAMP':
        if elapsed == 0:
            return wave['start_value']
        if elapsed >= wave['duration_steps']:
            return wave['end_value']
        fraction = min(elapsed, wave['duration_steps']) / wave['duration_steps']
        return wave['start_value'] + (wave['end_value']-wave['start_value'])*fraction
    return wave['offset'] + wave['amplitude'] * math.sin(_phase(wave, elapsed))


def _extrema(wave, duration):
    kind = wave['kind']
    values = [_value(wave, 0), _value(wave, duration)]
    if kind in ('SINE', 'CHIRP'):
        # Both declared frequencies are positive: chirp phase is monotone.
        # Check analytical stationary phases, not only discrete samples.
        first, last = _phase(wave, 0), _phase(wave, duration)
        for phase, sign in ((math.pi/2, 1), (3*math.pi/2, -1)):
            if math.ceil((first-phase)/math.tau) <= math.floor((last-phase)/math.tau):
                values.append(wave['offset'] + sign*wave['amplitude'])
    return min(values), max(values)


def _replace(stimulus, name, index, value):
    if index is None:
        stimulus['payload'][name] = value
    else:
        stimulus['payload'][name][index] = value
    return stimulus


@dataclass(frozen=True, slots=True)
class WaveformSampler:
    _contract: object
    _event_json: bytes
    model_id: str
    _name: str
    _index: int | None
    target_path: str
    unit: str
    extrema: tuple[float, float]

    @classmethod
    def compile(cls, contract, event, *, model_id):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError('HASH', 'verified frozen contract required for waveform targets')
        if type(model_id) is not str or model_id not in {r['model_id'] for r in contract.catalogue['model_bindings']}:
            raise ICDError('MODEL', 'explicit frozen model identity required')
        event = copy.deepcopy(event)
        contract.validate_source_definition('Event', event)
        if event['type'] != 'WAVEFORM':
            raise ICDError('SCHEMA', 'frozen WAVEFORM event required')
        contract.validate_stimulus(event['stimulus'], model_id=model_id)
        for key in ('at_step', 'priority', 'duration_steps', 'sample_period_steps'):
            if type(event[key]) is not int:
                raise ICDError('SCHEMA', 'waveform scheduling fields require exact integers')
        wave = event['waveform']
        for key in ('change_step', 'duration_steps'):
            if key in wave and type(wave[key]) is not int:
                raise ICDError('SCHEMA', 'waveform timing fields require exact integers')
        if event['at_step'] + event['duration_steps'] > MAX_STEP:
            raise ICDError('RANGE', 'waveform end exceeds uint32 model steps')
        mid = event['stimulus']['message_id']
        if mid not in range(7, 20):
            raise ICDError('TARGET_MISSING', 'message has no frozen root input/parameter waveform binding')
        group = ('flight_control' if mid in (7,8,9,14,15,16) else 'environment' if mid == 10
                 else 'fault' if mid in (11,12,13) else 'parameters')
        field = FIELD.fullmatch(event['field_path'])
        if field is None:
            raise ICDError('SCHEMA', 'registered payload scalar or explicit zero-based fixed array index required')
        name, index = field[1], None if field[2] is None else int(field[2])
        rows = [r for r in contract.catalogue['model_bindings']
                if r['model_id'] == model_id and r['path'] == group+'.'+name]
        payload = event['stimulus']['payload']
        if len(rows) != 1 or name not in payload or rows[0]['type'] != 'double':
            raise ICDError('SCHEMA', 'waveform target must be one registered writable numeric field')
        row = rows[0]
        actual = payload[name]
        if ((row['dimension'] == 1 and (index is not None or type(actual) not in (int,float)))
                or (row['dimension'] != 1 and (type(actual) is not list or index is None
                    or len(actual) != row['dimension'] or not 0 <= index < row['dimension']))):
            raise ICDError('SCHEMA', 'waveform fixed dimension/index differs from frozen target')
        duration = event['duration_steps']
        frequency = 0
        if wave['kind'] == 'SINE':
            frequency = wave['frequency_hz']
        elif wave['kind'] == 'CHIRP':
            fraction = min(duration, wave['duration_steps']) / wave['duration_steps']
            frequency = max(wave['start_frequency_hz'], wave['start_frequency_hz'] +
                            (wave['end_frequency_hz']-wave['start_frequency_hz'])*fraction)
        if 1000/event['sample_period_steps'] < 10*frequency:
            raise ICDError('RANGE', 'waveform sample frequency must be at least ten times its highest frequency')
        bounds = _extrema(wave, duration)
        if bounds[0] < row['min'] or bounds[1] > row['max']:
            raise ICDError('RANGE', 'continuous waveform extrema exceed the frozen target; no clamp')
        for value in bounds:
            contract.validate_stimulus(_replace(copy.deepcopy(event['stimulus']),name,index,value), model_id=model_id)
        raw = json.dumps(event,ensure_ascii=True,allow_nan=False,separators=(',', ':')).encode('ascii')
        target = row['path'] + ('' if index is None else f'[{index}]')
        return cls(contract,raw,model_id,name,index,target,row['unit'],bounds)

    @property
    def execution_ready(self):
        return False

    def sample(self, step):
        if type(step) is not int or not 0 <= step <= MAX_STEP:
            raise ICDError('SCHEMA', 'explicit uint32 model step required, not a wall clock')
        event = loads(self._event_json)
        if step < event['at_step']:
            raise ICDError('STATE', 'waveform has not started at this model step')
        elapsed = min(step-event['at_step'],event['duration_steps'])
        result = _replace(event['stimulus'],self._name,self._index,_value(event['waveform'],elapsed))
        self._contract.validate_stimulus(result,model_id=self.model_id)
        return result
