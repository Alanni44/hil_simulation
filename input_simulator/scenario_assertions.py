"""Original Status sampling and assertion handlers, not complete model services."""

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import threading

from icd_runtime.errors import ICDError
from icd_runtime.contract import Contract
from icd_runtime.json_codec import canonicalize, loads
from .assertion import AssertionSpec, AssertionWindow
from .model_clock import ModelClockSnapshot, ObservedModelClock
from .scenario import ScenarioPlan, ScheduledAction
from .scenario_execution import ActionProgress
from .session import SourceSession


@dataclass(frozen=True, slots=True)
class StatusReaderFailure:
    session_id: int
    model_id: str
    error: str
    sample_sequence: int
    received_ns: int


class StatusObservationReader:
    """Every fresh correlated Status, retained under the original source owner."""
    def __init__(self, session, *, max_records=4096, max_bytes=16*1024*1024):
        if not isinstance(session, SourceSession):
            raise ICDError('STATE', 'actual original source required')
        if (type(max_records) is not int or not 1 <= max_records <= 65536
                or type(max_bytes) is not int or not 1 <= max_bytes <= 128*1024*1024):
            raise ICDError('CAPACITY', 'finite Status history required')
        self.session = self._source = session
        self.clock = ObservedModelClock(session)
        self._sid = session.session_id
        self._model = loads(session._identity_json)['model_id']
        self._records, self._bytes, self._sequence = [], 0, 0
        self._max_records, self._max_bytes = max_records, max_bytes
        self._failure, self._closed = None, False
        self._failure_record = None
        with self._operation():
            self._current()
            if session._status_assertion_reader is not None:
                raise ICDError('STATE', 'one original Status assertion reader per source')
            session._status_assertion_reader = self

    @contextmanager
    def _operation(self, *, closed_ok=False):
        source = self._source
        with ExitStack() as stack:
            owner = source._dispatcher
            if owner is None and source._native_tool_coordinator is not None:
                owner = source._native_tool_coordinator.dispatcher
            if owner is not None:
                stack.enter_context(owner._operation(closed_ok=closed_ok))
            stack.enter_context(source._operation(owner=owner, closed_ok=closed_ok))
            yield

    def _current(self):
        source = self._source
        now = source._now()
        if (self.session is not source or self.clock.session is not source
                or self._closed or source._state != 'LIVE' or self._sid is None
                or source.session_id != self._sid or now >= source._deadline_ns
                or source._model_clock_retired):
            raise ICDError('STALE_SESSION', 'original current grant required for Status samples')
        return now

    @property
    def records(self):
        return tuple(self._records)

    @property
    def failure(self):
        return self._failure

    @property
    def failure_records(self):
        return () if self._failure_record is None else (self._failure_record,)

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    def _capture(self, request, reply, started, completed, *, transport, channel, fresh):
        source = self._source
        if source._operation_thread != threading.get_ident():
            raise ICDError('STATE', 'Status capture requires actual source operation owner')
        if (fresh is not True or request['message_id'] != 2 or reply['message_id'] != 131
                or self._closed or self._failure is not None
                or source._status_assertion_reader is not self
                or source._state != 'LIVE' or source.session_id != self._sid
                or request['header']['session_id'] != self._sid or reply['header']['session_id'] != self._sid
                or source._model_clock_retired or not 0 <= started <= completed < source._deadline_ns
                or reply['header']['sequence'] <= self._sequence):
            return
        raw, feedback = canonicalize(request), canonicalize(reply)
        size = 128 + len(raw) + len(feedback)
        if len(self._records) >= self._max_records or self._bytes + size > self._max_bytes:
            # A bounded permanent failure retains the known prefix. Do not throw
            # from this passive hook and hide the original transport's RX record.
            self._failure = ('BUFFER_FULL', reply['header']['sequence'], completed)
            self._failure_record = StatusReaderFailure(self._sid,self._model,'BUFFER_FULL',
                reply['header']['sequence'],completed)
            return
        self._records.append(ModelClockSnapshot(self._sid, self._model,
            reply['payload']['model_step'], reply['payload']['state'], transport, channel,
            started, completed, started+source.contract.entry(131)['valid_for_ms']*1_000_000,
            raw, feedback))
        self._bytes += size
        self._sequence = reply['header']['sequence']

    def snapshot(self, *, model_step):
        status = self.clock.require_step(model_step)
        with self._operation():
            now = self._current()
            if self._source._status_assertion_reader is not self:
                raise ICDError('STATE', 'original Status reader attachment changed')
            if self._source._model_status is not status or now >= status.deadline_ns:
                raise ICDError('CLOCK_UNSYNC', 'Status changed while reading assertion samples')
            if self._failure is not None:
                raise ICDError(self._failure[0], 'Status sampling history overflowed; prefix retained')
            if 'consumer.Status' not in self._source.capabilities['available_probes']:
                raise ICDError('TARGET_MISSING', 'actual grant has no published Status producer')
            return now, self._sequence, tuple(self._records)

    def close(self):
        with self._operation(closed_ok=True):
            source = self._source
            recorder = source._observation_recorder
            if (recorder is not None and getattr(recorder, '_reader', None) is self
                    and source._state == 'LIVE' and not source._closed):
                raise ICDError('STATE', 'detach recorder before stopping live Status sampling')
            if self._source._status_assertion_reader is self:
                self._source._status_assertion_reader = None
            self._closed = True


@dataclass(frozen=True, slots=True)
class AssertionHandle:
    ordinal: int


@dataclass(frozen=True, slots=True)
class RuntimeAssertionRecord:
    handle: AssertionHandle
    assertion_id: str
    sample: ModelClockSnapshot
    comparison_matched: bool

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


@dataclass(frozen=True, slots=True)
class RuntimeAssertionLifecycle:
    handle: AssertionHandle
    kind: str
    mode: str
    model_step: int | None
    specs: tuple
    initial_sequence: int
    state: str
    error: str | None = None


@dataclass
class _AssertionEntry:
    handle: AssertionHandle
    windows: tuple
    sequence: int
    result: ActionProgress | None = None
    lifecycle: RuntimeAssertionLifecycle | None = None


class StatusScenarioAssertions:
    """Concrete E1 Status handlers; other probes require their actual readers."""
    def __init__(self, contract, plan, reader, *, max_handles=4096,
                 max_records=4096, max_bytes=16*1024*1024):
        if type(reader) is not StatusObservationReader:
            raise ICDError('TARGET_MISSING', 'actual original Status reader required')
        if (not isinstance(contract, Contract) or not contract.component_hashes
                or contract.component_hashes != reader._source.contract.component_hashes
                or contract.baseline_sha256 != reader._source.contract.baseline_sha256
                or type(plan) is not ScenarioPlan or plan.baseline_sha256 != contract.baseline_sha256
                or plan.model_id != reader._model):
            raise ICDError('HASH', 'same original scenario, model and verified contract required')
        for value, limit in ((max_handles,65536),(max_records,65536),(max_bytes,128*1024*1024)):
            if type(value) is not int or not 1 <= value <= limit:
                raise ICDError('CAPACITY', 'bounded assertion handles/history required')
        history_ids = {e['history_id'] for e in plan.scenario['events'] if e['type'] == 'REPLAY'}
        if len(history_ids) > 1 or ScenarioPlan.compile(contract, plan.scenario, model_id=plan.model_id,
                history_id=next(iter(history_ids),None)) != plan:
            raise ICDError('RESOURCE', 'compiled assertions differ from the original scenario resource')
        self.contract, self.plan, self.reader = contract, plan, reader
        self._reader = reader
        self._actions = {(a.event_id,a.index):a for a in plan.iter_actions(max_actions=65536)
                         if a.kind in ('WAIT','ASSERT')}
        self._roots = {a['assertion_id'] for a in plan.scenario['assertions']}
        self._specs = {a.assertion['assertion_id']:a for a in plan.assertions}
        self._entries, self._begun, self._records = {}, set(), []
        self._lifecycle_records = []
        self._max_handles, self._max_records, self._max_bytes = max_handles,max_records,max_bytes
        self._bytes, self._ready = 0, False
        self._recording_owner = None
        self._lock = threading.Lock()

    @contextmanager
    def _operation(self):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'one non-reentrant assertion handler owner required')
        try:
            if self._recording_owner is not None:
                from .evidence_recorder import ObservationRecorder
                if (type(self._recording_owner) is not ObservationRecorder
                        or not self._recording_owner._owns_assertions(self)):
                    raise ICDError('STATE','assertion cannot replace its recorded original owners')
            if self.reader is not self._reader:
                raise ICDError('STATE', 'original assertion reader cannot be replaced')
            yield
        finally:
            self._lock.release()

    @property
    def records(self):
        return tuple(self._records)

    @property
    def lifecycle_records(self):
        return tuple(self._lifecycle_records)

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    def _spec(self, spec):
        if (type(spec) is not AssertionSpec or spec.model_id != self.plan.model_id
                or spec != AssertionSpec.compile(self.contract, spec.assertion, model_id=self.plan.model_id)
                or self._specs.get(spec.assertion['assertion_id']) != spec):
            raise ICDError('SCHEMA', 'exact original compiled assertion required')
        d = spec.assertion
        if d['stage'] != 'E1' or d['message_id'] != 131 or d['probe_id'] != 'consumer.Status':
            raise ICDError('TARGET_MISSING', 'assertion requires an actual non-Status reader and stage evidence')
        fields = self.contract._schema['$defs']['Status']['properties']
        field = fields.get(d['field_path'])
        if field is None:
            raise ICDError('SCHEMA', 'exact frozen Status scalar field required')
        kind, expected = field['type'], d['expected']
        if (kind == 'boolean' and type(expected) is not bool
                or kind == 'string' and type(expected) is not str
                or kind in ('integer','number') and type(expected) not in (int,float)):
            raise ICDError('SCHEMA', 'assertion expected type differs from frozen Status field')

    def preflight(self, plan):
        with self._operation():
            if plan is not self.plan:
                raise ICDError('STATE', 'original complete plan required')
            for spec in plan.assertions:
                self._spec(spec)
            if (len(plan.assertions) > self._max_handles
                    or len(plan.assertions)+sum(a.assertion['sample_count'] for a in plan.assertions) > self._max_records):
                raise ICDError('CAPACITY', 'minimum complete assertion history cannot fit')
            status = self._reader.clock.snapshot()
            self._reader.snapshot(model_step=status.model_step)
            self._ready = True

    def _begin(self, specs, model_step, mode):
        if not self._ready:
            raise ICDError('STATE', 'whole-plan assertion preflight required')
        if type(specs) is not tuple or not specs:
            raise ICDError('SCHEMA', 'nonempty original assertion tuple required')
        ids = tuple(s.assertion['assertion_id'] for s in specs if type(s) is AssertionSpec)
        if len(ids) != len(specs) or len(set(ids)) != len(ids):
            raise ICDError('SCHEMA', 'distinct original compiled assertions required')
        for spec in specs:
            self._spec(spec)
        if set(ids) & self._begun:
            raise ICDError('DUPLICATE', 'original assertion already begun')
        now, sequence, samples = self._reader.snapshot(model_step=model_step)
        # Reserve both finite lifecycle rows before beginning, including failures.
        size = 512 + sum(len(s.assertion_json)+256 for s in specs)
        if (len(self._entries) >= self._max_handles
                or len(self._records)+len(self._entries)+1 > self._max_records
                or self._bytes+size > self._max_bytes):
            raise ICDError('BUFFER_FULL', 'assertion history full before beginning')
        windows = tuple(AssertionWindow(s, start_step=model_step, mode=mode,
            max_records=self._max_records, max_bytes=min(self._max_bytes,64*1024*1024)) for s in specs)
        handle = AssertionHandle(len(self._entries)+1)
        lifecycle=RuntimeAssertionLifecycle(handle,'STARTED',mode,model_step,specs,sequence,'PENDING')
        self._entries[handle.ordinal] = _AssertionEntry(handle,windows,sequence,lifecycle=lifecycle)
        self._lifecycle_records.append(lifecycle)
        self._bytes += size
        self._begun.update(ids)
        return handle

    def begin_assertions(self, assertions, *, model_step):
        with self._operation():
            if (type(assertions) is not tuple or any(type(s) is not AssertionSpec
                    or s.assertion['assertion_id'] not in self._roots for s in assertions)):
                raise ICDError('SCHEMA', 'only original root assertions start through this entry')
            return self._begin(assertions,model_step,'ASSERT')

    def begin(self, action, *, model_step):
        with self._operation():
            if (type(action) is not ScheduledAction or action.kind not in ('WAIT','ASSERT')
                    or self._actions.get((action.event_id,action.index)) != action
                    or action.step != model_step):
                raise ICDError('STATE', 'exact original WAIT/ASSERT action at its scheduled step required')
            spec = self._specs[action.event['assertion']['assertion_id']]
            return self._begin((spec,),model_step,action.kind)

    def poll(self, handle, *, model_step):
        with self._operation():
            if type(handle) is not AssertionHandle or type(handle.ordinal) is not int:
                raise ICDError('STATE', 'actual original assertion handle required')
            entry = self._entries.get(handle.ordinal)
            if entry is None or entry.handle is not handle:
                raise ICDError('STATE', 'actual original assertion handle required')
            if entry.result is not None:
                return entry.result
            try:
                now, sequence, samples = self._reader.snapshot(model_step=model_step)
                for window in entry.windows:
                    if window.status == 'PENDING' and model_step >= window.deadline_step:
                        window.poll(model_step=model_step)
                        raise ICDError('TIMEOUT', 'original assertion model-step window expired')
                for sample in samples:
                    if sample.status['header']['sequence'] <= entry.sequence:
                        continue
                    if now >= sample.deadline_ns:
                        raise ICDError('EXPIRED', 'unread original Status sample expired')
                    for window in entry.windows:
                        if window.status != 'PENDING':
                            continue
                        value = sample.status['payload'][window.spec.assertion['field_path']]
                        size = len(canonicalize(value))+128
                        if len(self._records)+len(self._entries) >= self._max_records or self._bytes+size > self._max_bytes:
                            raise ICDError('BUFFER_FULL', 'assertion history exhausted; samples retained')
                        state = window.observe(model_step=sample.model_step,
                            sample_sequence=sample.status['header']['sequence'], value=value)
                        self._records.append(RuntimeAssertionRecord(handle,window.spec.assertion['assertion_id'],
                            sample,window.records[-1].comparison_matched))
                        self._bytes += size
                        if state == 'MISMATCH':
                            raise ICDError('BUSINESS_FAILED', 'actual Status assertion mismatch')
                entry.sequence = sequence
                for window in entry.windows:
                    if window.status == 'PENDING':
                        window.poll(model_step=model_step)
                if all(w.status == 'MATCHED' for w in entry.windows):
                    entry.result = ActionProgress(handle,'COMPLETE')
            except ICDError as error:
                entry.result = ActionProgress(handle,'FAILED',error.code)
            if entry.result is not None:
                from dataclasses import replace
                step=model_step if type(model_step) is int and 0 <= model_step <= 0xffffffff else None
                self._lifecycle_records.append(replace(entry.lifecycle,kind='RESULT',model_step=step,
                    state=entry.result.state,error=entry.result.error))
            return entry.result or ActionProgress(handle,'PENDING')
