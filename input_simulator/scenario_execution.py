"""Common original-scenario control, not a tool backend or model qualification."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
import threading

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from .scenario import MAX_STEP, ScenarioPlan


CLEANUP_FIELDS = ('clear_model_faults', 'clear_bus_faults', 'safe_actuators', 'stop_video',
                  'stop_periodic_senders', 'stop_replay', 'release_control',
                  'flush_receive_queues', 'close_session')
ERRORS = frozenset(('SCHEMA', 'VERSION', 'HASH', 'AUTHORIZATION', 'MODEL', 'CONTROL_OWNER',
                   'RANGE', 'STATE', 'STALE_SESSION', 'DUPLICATE', 'OUT_OF_ORDER', 'LATE',
                   'EXPIRED', 'BUFFER_FULL', 'FRAGMENT', 'CRC', 'UNSUPPORTED', 'TARGET_MISSING',
                   'TIMEOUT', 'BUSINESS_FAILED', 'SAFETY', 'RESOURCE', 'CLOCK_UNSYNC', 'CAPACITY'))


@dataclass(frozen=True, slots=True)
class ActionProgress:
    handle: object
    state: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupProgress:
    handle: object
    state: str
    completed_fields: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioRecord:
    event_id: str
    index: int
    kind: str
    model_step: int
    outcome: str
    error: str | None = None
    completed_cleanup_fields: tuple[str, ...] = ()
    handle: object = None
    assertion_id: str | None = None

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


class ScenarioDriver(ABC):
    """Trusted in-process adapter boundary. No production driver is implied.

    Preflight must verify every original link, current grant, model clock,
    root/event assertion probe, replay and negative-case authorization without
    taking counters or launching senders. Runtime methods must recheck those
    facts, preserve original handles/TX/RX and never substitute another link.
    COMPLETE is a handler result, not proof of E2/E3 or safe remote cleanup.
    """

    @abstractmethod
    def preflight(self, plan):
        pass

    @abstractmethod
    def begin_assertions(self, assertions, *, model_step):
        pass

    @abstractmethod
    def begin(self, action, *, model_step):
        pass

    @abstractmethod
    def poll(self, handle, *, model_step):
        pass

    @abstractmethod
    def begin_cleanup(self, cleanup, *, model_step):
        pass

    @abstractmethod
    def poll_cleanup(self, handle, *, model_step):
        pass


class ScenarioExecution:
    def __init__(self, contract, plan, driver, *, max_pending=64, max_records=4096,
                 max_bytes=16*1024*1024):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError('HASH', 'original verified scenario contract required')
        if type(plan) is not ScenarioPlan or plan.baseline_sha256 != contract.baseline_sha256:
            raise ICDError('HASH', 'same original scenario baseline required')
        if not isinstance(driver, ScenarioDriver):
            raise ICDError('TARGET_MISSING', 'explicit original tool/model scenario driver required')
        for value, maximum in ((max_pending,64), (max_records,65536), (max_bytes,128*1024*1024)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ICDError('CAPACITY', 'finite integral scenario limits required')
        definition = plan.scenario
        history_ids = {e['history_id'] for e in definition['events'] if e['type'] == 'REPLAY'}
        if len(history_ids) > 1:
            raise ICDError('RESOURCE', 'original plan must reference one provided history')
        expected = ScenarioPlan.compile(contract, definition, model_id=plan.model_id,
                                        history_id=next(iter(history_ids), None))
        if expected != plan:
            raise ICDError('RESOURCE', 'compiled scenario differs from its original resource')
        # Reserve the full finite run's local records up front; no old result
        # may be evicted to admit a later event. Pending snapshots are bounded.
        root_ids = {a['assertion_id'] for a in definition['assertions']}
        root_assertions = tuple(a for a in plan.assertions if a.assertion['assertion_id'] in root_ids)
        if len(root_assertions) > max_pending:
            raise ICDError('CAPACITY', 'root assertion handles exceed the explicit in-flight budget')
        record_count = 2 * (plan.action_count + len(root_assertions)) + 3 + len(CLEANUP_FIELDS)
        event_max = max((len(s.event_json) for s in plan._streams), default=0)
        required_bytes = len(plan.scenario_json) + record_count*1024 + max_pending*(2*event_max + 4096)
        if record_count > max_records or required_bytes > max_bytes:
            raise ICDError('CAPACITY', 'complete scenario record/snapshot budget exceeded before execution')
        self._plan, self._driver = plan, driver
        self._root_assertions = root_assertions
        self._max_pending = max_pending
        self._records, self._pending, self._handles = [], {}, {}
        self._iterator = plan.iter_actions(max_actions=1000000)
        self._next = next(self._iterator, None)
        self._last_step = None
        self._state, self._failure = 'READY', None
        self._wait = None
        self._cleanup_handle = None
        self._cleanup_started = False
        self._cleanup_fields = set()
        self._pending_cleanup = False
        self._end_requested = False
        self._cleanup = definition['cleanup']
        self._lock = threading.Lock()

    @property
    def state(self):
        return self._state

    @property
    def failure(self):
        return self._failure

    @property
    def records(self):
        return tuple(self._records)

    @property
    def pending_count(self):
        return len(self._pending)

    @property
    def pending_cleanup(self):
        return self._pending_cleanup

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    @property
    def safety_verified(self):
        return False

    @contextmanager
    def _operation(self, model_step):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'scenario requires one serialized non-reentrant owner')
        try:
            if (type(model_step) is not int or not 0 <= model_step <= MAX_STEP or
                    self._last_step is not None and model_step < self._last_step):
                raise ICDError('SCHEMA', 'explicit nondecreasing uint32 model step required')
            yield
        finally:
            self._lock.release()

    def _record(self, action, step, outcome, error=None, *, handle=None, assertion_id=None):
        self._records.append(ScenarioRecord('ROOT_ASSERTIONS' if action is None else action.event_id,
                            0 if action is None else action.index, 'ROOT_ASSERTIONS' if action is None else action.kind,
                            step, outcome, error, handle=handle, assertion_id=assertion_id))

    def _own(self, handle):
        if handle is None or id(handle) in self._handles:
            raise ICDError('STATE', 'distinct original runtime handle required for each operation')
        self._handles[id(handle)] = handle
        return handle

    @staticmethod
    def _error(exc):
        return exc.code if isinstance(exc, ICDError) and type(exc.code) is str and exc.code in ERRORS else 'RESOURCE'

    def _begin(self, action, step, *, assertion=None):
        if len(self._pending) >= self._max_pending:
            raise ICDError('BUFFER_FULL', 'scenario in-flight limit reached before next handler')
        timeout = (assertion.assertion['timeout_steps'] if action is None else
                   action.event['assertion']['timeout_steps'] if action.kind in ('WAIT','ASSERT') else None)
        deadline = None if timeout is None else step + timeout
        if deadline is not None and deadline > MAX_STEP:
            raise ICDError('RANGE', 'runtime assertion deadline exceeds uint32')
        assertion_id = assertion.assertion['assertion_id'] if assertion is not None else None
        try:
            handle = self._own(self._driver.begin_assertions((assertion,), model_step=step)
                               if action is None else self._driver.begin(action, model_step=step))
        except Exception as exc:
            self._record(action, step, 'FAILED', self._error(exc), assertion_id=assertion_id)
            raise
        self._pending[id(handle)] = (handle, action, deadline, assertion_id)
        self._record(action, step, 'STARTED', handle=handle, assertion_id=assertion_id)
        if action is not None and action.kind == 'WAIT':
            self._wait, self._state = handle, 'WAITING'

    @staticmethod
    def _progress(progress, handle, kind):
        if type(progress) is not kind or progress.handle is not handle:
            raise ICDError('STATE', 'result must name the original owned runtime handle')
        if (type(progress.state) is not str or progress.state not in ('PENDING', 'COMPLETE', 'FAILED') or
                progress.error is not None and (type(progress.error) is not str or progress.error not in ERRORS) or
                (progress.state == 'FAILED') != (progress.error is not None)):
            raise ICDError('SCHEMA', 'closed handler state/error required; not a model ACK')

    def _request_cleanup(self, step):
        self._state, self._pending_cleanup = 'CLEANUP_PENDING', True
        if self._cleanup_started:
            return
        self._cleanup_started = True
        self._records.append(ScenarioRecord('CLEANUP',0,'CLEANUP',step,'REQUESTED'))
        try:
            self._cleanup_handle = self._own(self._driver.begin_cleanup(dict(self._cleanup), model_step=step))
        except Exception as exc:
            code = self._error(exc)
            self._failure = self._failure or code
            self._state = 'FAILED'
            self._records.append(ScenarioRecord('CLEANUP',0,'CLEANUP',step,'FAILED',code))

    def _fail(self, step, exc):
        code = self._error(exc)
        self._failure = self._failure or code
        self._records.append(ScenarioRecord('RUN',0,'RUN',step,'FAILED',code))
        self._request_cleanup(step)

    def _poll_cleanup(self, step):
        try:
            result = self._driver.poll_cleanup(self._cleanup_handle, model_step=step)
            self._progress(result, self._cleanup_handle, CleanupProgress)
            fields = result.completed_fields
            if (type(fields) is not tuple or any(type(f) is not str or f not in CLEANUP_FIELDS for f in fields) or
                    len(set(fields)) != len(fields)):
                raise ICDError('SCHEMA', 'cleanup must name original distinct completed operations')
            new_fields = set(fields) - self._cleanup_fields
            self._cleanup_fields.update(fields)
            if result.state == 'PENDING' and new_fields:
                self._records.append(ScenarioRecord('CLEANUP',0,'CLEANUP',step,'PROGRESS',
                    completed_cleanup_fields=fields, handle=self._cleanup_handle))
            if result.state == 'FAILED':
                raise ICDError(result.error, 'original cleanup handler failed')
            if result.state == 'COMPLETE':
                if self._cleanup_fields != set(CLEANUP_FIELDS):
                    raise ICDError('SAFETY', 'cleanup ended without all nine original operations')
                self._pending_cleanup = False
                for handle, action, _, assertion_id in self._pending.values():
                    self._record(action, step, 'LOCAL_CANCELLED', handle=handle, assertion_id=assertion_id)
                self._pending.clear()
                self._wait = None
                self._state = 'FAILED' if self._failure else 'LOCAL_STOPPED'
                self._records.append(ScenarioRecord('CLEANUP',0,'CLEANUP',step,'COMPLETE',
                                     completed_cleanup_fields=CLEANUP_FIELDS, handle=self._cleanup_handle))
        except Exception as exc:
            code = self._error(exc)
            self._failure = self._failure or code
            self._state = 'FAILED'
            self._records.append(ScenarioRecord('CLEANUP',0,'CLEANUP',step,'FAILED',code,
                                 tuple(f for f in CLEANUP_FIELDS if f in self._cleanup_fields), self._cleanup_handle))

    def _advance(self, step):
        if self._state == 'CLEANUP_PENDING':
            self._poll_cleanup(step)
            return
        if self._state not in ('RUNNING', 'WAITING'):
            return
        try:
            for key, (handle, action, deadline, assertion_id) in tuple(self._pending.items()):
                try:
                    if deadline is not None and step >= deadline:
                        raise ICDError('TIMEOUT', 'original assertion model-step deadline reached')
                    result = self._driver.poll(handle, model_step=step)
                    self._progress(result, handle, ActionProgress)
                except Exception as exc:
                    self._record(action, step, 'FAILED', self._error(exc), handle=handle, assertion_id=assertion_id)
                    del self._pending[key]
                    raise
                if result.state == 'PENDING':
                    continue
                self._record(action, step, result.state, result.error, handle=handle, assertion_id=assertion_id)
                del self._pending[key]
                if result.state == 'FAILED':
                    raise ICDError(result.error, 'original scenario handler failed')
                if self._wait is handle:
                    self._wait, self._state = None, 'RUNNING'
            if self._wait is not None:
                return
            while not self._end_requested and self._next is not None and self._next.step <= step:
                action = self._next
                if action.step != step:
                    raise ICDError('TIMEOUT', 'missed absolute scenario model step; no catch-up or rebasing')
                if action.kind == 'END_CLEANUP':
                    self._cleanup = action.event['cleanup']
                    self._end_requested = True
                    self._record(action, step, 'REQUESTED')
                else:
                    self._begin(action, step)
                self._next = next(self._iterator, None)
                if self._wait is not None:
                    return
            if (self._end_requested or self._next is None) and not self._pending:
                self._request_cleanup(step)
        except Exception as exc:
            self._fail(step, exc)

    def start(self, *, model_step):
        with self._operation(model_step):
            if self._state != 'READY':
                raise ICDError('STATE', 'original scenario starts once')
            if self._next is not None and self._next.step < model_step:
                raise ICDError('TIMEOUT', 'cannot start past the original first event')
            if any(model_step + a.assertion['timeout_steps'] > MAX_STEP for a in self._root_assertions):
                raise ICDError('RANGE', 'root assertion runtime deadlines exceed uint32')
            self._driver.preflight(self._plan)
            self._last_step, self._state = model_step, 'RUNNING'
            try:
                for assertion in self._root_assertions:
                    self._begin(None, model_step, assertion=assertion)
            except Exception as exc:
                self._fail(model_step, exc)
                return
            self._advance(model_step)

    def advance(self, *, model_step):
        with self._operation(model_step):
            if self._state == 'READY':
                raise ICDError('STATE', 'start the original scenario before advancing')
            self._last_step = model_step
            self._advance(model_step)

    def stop(self, *, model_step):
        with self._operation(model_step):
            if self._state == 'READY':
                raise ICDError('STATE', 'no original running driver to stop')
            self._last_step = model_step
            if self._state in ('RUNNING', 'WAITING'):
                self._request_cleanup(model_step)
