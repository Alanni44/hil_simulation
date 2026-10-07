"""Candidate-value comparisons only. This module cannot qualify or produce evidence."""

import copy
from dataclasses import dataclass
import json
import re

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import check_json_domain, loads


MAX_STEP = (1 << 32) - 1
MODELS = ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil')
PATH = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\[(?:0|[1-9][0-9]*)\])?'
                  r'(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[(?:0|[1-9][0-9]*)\])?)*\Z')
ROOT_PATH = re.compile(r'([a-z_]+\.[a-z0-9_]+)(?:\[(0|[1-9][0-9]*)\])?\Z')


def _snapshot(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')


@dataclass(frozen=True, slots=True)
class AssertionSpec:
    assertion_json: bytes
    baseline_sha256: str
    model_id: str
    probe_numeric_id: int
    reader_path_pending: bool

    @classmethod
    def compile(cls, contract, assertion, *, model_id):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError('HASH', 'assertion needs the verified original contract')
        if type(model_id) is not str or model_id not in MODELS:
            raise ICDError('MODEL', 'assertion needs an explicit frozen model')
        assertion = copy.deepcopy(assertion)
        contract.validate_source_definition('Assertion', assertion)
        for name in ('message_id','timeout_steps','sample_count'):
            if type(assertion[name]) is not int:
                raise ICDError('SCHEMA', 'assertion integers cannot be bool or float')
        entry = contract.entry(assertion['message_id'])
        if model_id not in entry['model_ids']:
            raise ICDError('MODEL', 'assertion message is not applicable to this model')
        expected = assertion['expected']
        if type(expected) in (bool,str) and (assertion['tolerance'] != 0 or
                assertion['operator'] not in ('EQ','NE','EVENTUALLY')):
            raise ICDError('RESOURCE', 'non-numeric assertion cannot use tolerance or ordering')
        catalog = contract.catalogue
        probe = next((p for p in catalog['probe_catalog'] if p['name'] == assertion['probe_id']), None)
        if probe is None:
            raise ICDError('TARGET_MISSING', 'assertion probe is not in the frozen catalogue')
        if assertion['stage'] == 'E2' and probe['id'] == 0:
            raise ICDError('TARGET_MISSING', 'NO_PROBE cannot stand for actual application')
        path = assertion['field_path']
        if PATH.fullmatch(path) is None:
            raise ICDError('SCHEMA', 'assertion path must identify a scalar without expressions')
        pending = True
        if 'model_id' in probe:
            if probe['model_id'] != model_id:
                raise ICDError('MODEL', 'assertion probe belongs to another model')
            match = ROOT_PATH.fullmatch(path)
            if match is None or match[1] != probe['target']:
                raise ICDError('SCHEMA', 'assertion path differs from its frozen model probe')
            row = next(r for r in catalog['model_bindings'] if r['model_id'] == model_id and r['path'] == match[1])
            index = match[2]
            if (row['dimension'] == 1 and index is not None or row['dimension'] != 1 and
                    (index is None or int(index) >= row['dimension'])):
                raise ICDError('SCHEMA', 'fixed array assertion needs its explicit valid element')
            mid = assertion['message_id']
            group = ('flight_control' if mid in (7,8,9,14,15,16) else 'environment' if mid == 10 else
                     'fault' if mid in (11,12,13) else 'parameters' if mid in (17,18,19) else None)
            if group != row['path'].split('.')[0]:
                raise ICDError('SCHEMA', 'assertion message does not write the probe group')
            if ((row['type'] == 'bool' and type(expected) is not bool) or
                    (row['type'] == 'double' and type(expected) not in (int,float))):
                raise ICDError('SCHEMA', 'assertion expected type differs from the frozen target')
            pending = False
        elif 'message_id' in probe and probe['message_id'] != assertion['message_id']:
            raise ICDError('SCHEMA', 'consumer probe belongs to another message')
        return cls(_snapshot(assertion), contract.baseline_sha256, model_id, probe['id'], pending)

    @property
    def assertion(self):
        return loads(self.assertion_json)

    @property
    def execution_ready(self):
        return False

    def compare(self, value):
        check_json_domain(value)
        spec = self.assertion
        expected = spec['expected']
        numeric = type(expected) in (int,float)
        if (numeric and type(value) not in (int,float) or
                not numeric and type(value) is not type(expected)):
            raise ICDError('SCHEMA', 'candidate sample type differs from assertion expected value')
        op = spec['operator']
        if op in ('WITHIN','EVENTUALLY'):
            return abs(value - expected) <= spec['tolerance'] if numeric else value == expected
        if op == 'EQ':
            return value == expected
        if op == 'NE':
            return value != expected
        if op == 'LT':
            return value < expected
        if op == 'LE':
            return value <= expected
        if op == 'GT':
            return value > expected
        return value >= expected


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    model_step: int
    sample_sequence: int
    value_json: bytes
    comparison_matched: bool

    @property
    def value(self):
        return loads(self.value_json)

    @property
    def stored_bytes(self):
        return len(self.value_json) + 17


class AssertionWindow:
    def __init__(self, spec, *, start_step, mode, max_records=4096, max_bytes=4*1024*1024):
        if not isinstance(spec, AssertionSpec):
            raise ICDError('SCHEMA', 'compiled assertion specification required')
        if (type(start_step) is not int or not 0 <= start_step <= MAX_STEP or
                type(mode) is not str or mode not in ('WAIT','ASSERT')):
            raise ICDError('SCHEMA', 'explicit uint32 start and WAIT/ASSERT mode required')
        if (type(max_records) is not int or not 1 <= max_records <= 1000000 or
                type(max_bytes) is not int or not 1 <= max_bytes <= 64*1024*1024):
            raise ICDError('CAPACITY', 'bounded positive record and byte limits required')
        definition = spec.assertion
        deadline = start_step + definition['timeout_steps']
        if deadline > MAX_STEP:
            raise ICDError('RANGE', 'assertion window deadline exceeds uint32')
        self._spec, self._start_step, self._mode, self._deadline_step = spec, start_step, mode, deadline
        self._max_records, self._max_bytes = max_records, max_bytes
        self._records, self._stored_bytes = [], 0
        self._last_step, self._last_sequence = None, 0
        self._consecutive, self._status = 0, 'PENDING'

    @property
    def spec(self):
        return self._spec

    @property
    def start_step(self):
        return self._start_step

    @property
    def mode(self):
        return self._mode

    @property
    def deadline_step(self):
        return self._deadline_step

    @property
    def status(self):
        return self._status

    @property
    def evidence_status(self):
        return 'NOT_EVALUATED'

    @property
    def execution_ready(self):
        return False

    @property
    def records(self):
        return tuple(self._records)

    @property
    def stored_bytes(self):
        return self._stored_bytes

    @property
    def consecutive_count(self):
        return self._consecutive

    def _check_step(self, step):
        if type(step) is not int or not 0 <= step <= MAX_STEP:
            raise ICDError('SCHEMA', 'explicit uint32 model step required')
        if self._last_step is not None and step < self._last_step:
            raise ICDError('SCHEMA', 'candidate model steps cannot go backwards')
        if step < self.start_step:
            raise ICDError('STATE', 'candidate arrived before the assertion window')

    def poll(self, *, model_step):
        self._check_step(model_step)
        self._last_step = model_step
        if self._status == 'PENDING' and model_step >= self.deadline_step:
            self._status = 'TIMED_OUT'
        return self._status

    def observe(self, *, model_step, sample_sequence, value):
        self._check_step(model_step)
        if self._status != 'PENDING':
            raise ICDError('STATE', 'terminal comparison window cannot accept more samples')
        if type(sample_sequence) is not int or not 1 <= sample_sequence <= MAX_STEP:
            raise ICDError('SCHEMA', 'explicit new uint32 sample sequence required')
        if sample_sequence <= self._last_sequence:
            raise ICDError('DUPLICATE', 'old candidate sample cannot count twice')
        matched = self.spec.compare(value)
        if model_step >= self.deadline_step:
            return self.poll(model_step=model_step)
        record = CandidateObservation(model_step, sample_sequence, _snapshot(value), matched)
        if len(self._records) >= self._max_records or self._stored_bytes + record.stored_bytes > self._max_bytes:
            raise ICDError('BUFFER_FULL', 'drain candidate records before accepting another sample')
        self._records.append(record)
        self._stored_bytes += record.stored_bytes
        self._last_step, self._last_sequence = model_step, sample_sequence
        self._consecutive = self._consecutive + 1 if matched else 0
        definition = self.spec.assertion
        if not matched and self.mode == 'ASSERT' and definition['operator'] != 'EVENTUALLY':
            self._status = 'MISMATCH'
        elif self._consecutive >= definition['sample_count']:
            self._status = 'MATCHED'
        return self._status

    def drain_records(self):
        records = tuple(self._records)
        self._records.clear()
        self._stored_bytes = 0
        return records
