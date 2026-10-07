"""Original native integration; concrete model services are required, not supplied here."""

from abc import abstractmethod
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, field, replace
import threading

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from .assertion import AssertionSpec
from .model_clock import ObservedModelClock
from .native_scenario_actions import NativeScenarioActions, KINDS
from .scenario import MAX_STEP, ScenarioPlan, ScheduledAction
from .scenario_execution import ActionProgress, CleanupProgress, CLEANUP_FIELDS, ScenarioDriver, ScenarioExecution
from .session import SourceSession
from .scenario_assertions import StatusScenarioAssertions


_UNSET = object()


class ScenarioRuntimeServices(ScenarioDriver):
    """Same-session actual authorization/readers/replay/negative/cleanup boundary.

    A concrete implementation must preflight the complete original plan and
    recheck real control ownership and model timing before approving a target.
    There is deliberately no default or successful test implementation.
    """
    def __init__(self, session, *, assertions=None, targets=None):
        if not isinstance(session, SourceSession):
            raise ICDError('STATE', 'actual original source session required')
        if assertions is not None and (type(assertions) is not StatusScenarioAssertions
                or assertions._reader._source is not session):
            raise ICDError('STATE', 'assertions must use this actual original source')
        self.session = session
        self._assertions = assertions
        if targets is not None:
            from .runtime_targets import RuntimeTargetAuthorizer
            if type(targets) is not RuntimeTargetAuthorizer or targets.session is not session:
                raise ICDError('STATE','target authorization must use this original source')
        self._targets = targets

    def _assertion_service(self):
        if self._assertions is None:
            raise ICDError('TARGET_MISSING', 'actual assertion reader/handler required')
        if self._assertions._reader._source is not self.session:
            raise ICDError('STALE_SESSION', 'assertion service cannot adopt another source')
        return self._assertions

    def preflight_assertions(self, plan):
        self._assertion_service().preflight(plan)

    def begin_assertions(self, assertions, *, model_step):
        return self._assertion_service().begin_assertions(assertions, model_step=model_step)

    def begin(self, action, *, model_step):
        if type(action) is not ScheduledAction or action.kind not in ('WAIT','ASSERT'):
            raise ICDError('TARGET_MISSING', 'actual original non-assertion handler required')
        return self._assertion_service().begin(action, model_step=model_step)

    def poll(self, handle, *, model_step):
        return self._assertion_service().poll(handle, model_step=model_step)

    @abstractmethod
    def native_target(self, action, *, model_step):
        pass


@dataclass(frozen=True, slots=True)
class DriverHandle:
    ordinal: int
    kind: str


@dataclass
class _Entry:
    handle: DriverHandle
    owner: object
    delegate: object = None
    result: object = None
    deadline_ns: int | None = None
    begin_error: str | None = None
    local_error: str | None = None
    cleanup_fields: set = field(default_factory=set)
    remote_terminal: CleanupProgress | None = None


class OriginalScenarioDriver(ScenarioDriver):
    def __init__(self, contract, plan, native_actions, services, *, max_handles=4096):
        if (not isinstance(contract, Contract) or not contract.component_hashes
                or type(plan) is not ScenarioPlan or plan.baseline_sha256 != contract.baseline_sha256):
            raise ICDError('HASH', 'same verified original scenario contract required')
        if type(native_actions) is not NativeScenarioActions or native_actions.plan is not plan:
            raise ICDError('STATE', 'actual native actions must retain this complete original plan')
        if not isinstance(services, ScenarioRuntimeServices):
            raise ICDError('TARGET_MISSING', 'explicit actual scenario runtime services required')
        if (services.session is not native_actions.session
                or native_actions.contract.component_hashes != contract.component_hashes):
            raise ICDError('STATE', 'native and runtime services must share the actual original session')
        if (type(max_handles) is not int or not 1 <= max_handles <= 65536
                or plan.action_count + len(plan.assertions) + 1 > max_handles):
            raise ICDError('CAPACITY', 'whole finite driver handle history must fit before preflight')
        if native_actions.assigned_links != ('CANT', 'ETHGEN'):
            raise ICDError('STATE', 'composed native actions must explicitly own CANT and ETHGEN only')
        self.contract, self.plan, self.native, self.services = contract, plan, native_actions, services
        self.session = native_actions.session
        self._source = self.session
        self._target_authorizer = services._targets
        if self._target_authorizer is not None:
            from .runtime_targets import RuntimeTargetAuthorizer
            if (type(self._target_authorizer) is not RuntimeTargetAuthorizer
                    or self._target_authorizer.plan is not plan or self._target_authorizer.session is not self._source
                    or self._target_authorizer._can_sender is not None
                        and self._target_authorizer._can_sender is not native_actions.sender):
                raise ICDError('STATE','target authorization must retain original plan/source/CAN sender')
        self.clock = ObservedModelClock(self.session)
        self._sid = self.session.session_id
        self._max_handles = max_handles
        self._actions = {(a.event_id, a.index): a for a in plan.iter_actions(max_actions=max_handles)}
        self._entries, self._delegates, self._attempted, self._asserted = {}, {}, set(), set()
        self._cleanup_handle = None
        self._cleanup_errors = []
        self._ready = self._closing = False
        self._last_step = None
        self._lock = threading.Lock()

    @property
    def execution_ready(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    @property
    def cleanup_errors(self):
        return tuple(self._cleanup_errors)

    @contextmanager
    def _operation(self, step=_UNSET):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'original driver requires one non-reentrant owner')
        try:
            if step is not _UNSET:
                if (type(step) is not int or not 0 <= step <= MAX_STEP
                        or self._last_step is not None and step < self._last_step):
                    raise ICDError('SCHEMA', 'explicit nondecreasing original model step required')
            yield
        finally:
            self._lock.release()

    def _identity(self, *, allow_closed=False):
        if self.services._targets is not self._target_authorizer:
            raise ICDError('STATE','original target authorization cannot be replaced')
        if (self._target_authorizer is not None and self._target_authorizer._can_sender is not None
                and self.native.sender is not self._target_authorizer._can_sender):
            raise ICDError('STATE','original approved native CAN sender cannot be replaced')
        original_closed = (allow_closed and self._source._closed
                           and self._source._state == 'ABANDONED' and self._source.session_id is None
                           and self._source._closed_sid == self._sid)
        if (self.session is not self._source or self.services.session is not self._source
                or self.native.session is not self._source
                or self._source.session_id != self._sid and not original_closed):
            raise ICDError('STALE_SESSION', 'original driver cannot adopt another session or runtime owner')

    def _observe(self, step=None):
        self._identity()
        snapshot = self.clock.snapshot() if step is None else self.clock.require_step(step)
        if snapshot.model_id != self.plan.model_id:
            raise ICDError('MODEL', 'actual observed model differs from the original plan')
        return snapshot

    def _now(self):
        with ExitStack() as stack:
            owner = self.session._dispatcher
            if owner is None and self.session._native_tool_coordinator is not None:
                owner = self.session._native_tool_coordinator.dispatcher
            if owner is not None:
                stack.enter_context(owner._operation(closed_ok=True))
            stack.enter_context(self.session._operation(owner=owner, closed_ok=True))
            return self.session._now()

    def _new(self, kind, owner, delegate=_UNSET):
        if len(self._entries) >= self._max_handles:
            raise ICDError('BUFFER_FULL', 'retained driver handle capacity exhausted')
        handle = DriverHandle(len(self._entries), kind)
        entry = _Entry(handle, owner)
        if delegate is not _UNSET:
            self._attach(entry, delegate)
        self._entries[id(handle)] = entry
        return entry

    def _attach(self, entry, delegate):
        key = (id(entry.owner), id(delegate))
        if delegate is None or key in self._delegates:
            raise ICDError('STATE', 'nonempty distinct original provider handle required')
        self._delegates[key] = delegate
        entry.delegate = delegate

    def _owned(self, handle, *, cleanup=False):
        entry = self._entries.get(id(handle))
        if (type(handle) is not DriverHandle or entry is None or entry.handle is not handle
                or (handle.kind == 'CLEANUP') != cleanup):
            raise ICDError('STATE', 'exact original driver handle and operation kind required')
        return entry

    def _running(self):
        if not self._ready or self._closing:
            raise ICDError('STATE', 'preflight the original driver before actions, never after cleanup begins')

    def preflight(self, plan):
        with self._operation():
            if plan is not self.plan or self._ready or self._entries or self._closing:
                raise ICDError('STATE', 'preflight this complete original plan before the first attempt')
            self._observe()
            self.services.preflight(plan)
            if self._target_authorizer is not None:
                self._target_authorizer.preflight(plan)
            self._observe()
            self.native.preflight()
            self._ready = True

    def begin_assertions(self, assertions, *, model_step):
        with self._operation(model_step):
            self._running()
            self._observe(model_step)
            if (type(assertions) is not tuple or not assertions
                    or any(type(a) is not AssertionSpec or type(a.reader_path_pending) is not bool
                           or type(a.probe_numeric_id) is not int or a not in self.plan.assertions for a in assertions)):
                raise ICDError('STATE', 'original root assertions required')
            ids = [a.assertion['assertion_id'] for a in assertions]
            if len(set(ids)) != len(ids) or any(i in self._asserted for i in ids):
                raise ICDError('STATE', 'root assertion begin may not be repeated')
            self._asserted.update(ids)
            self._last_step = model_step
            delegate = self.services.begin_assertions(assertions, model_step=model_step)
            entry = self._new('ASSERTIONS', self.services, delegate)
            self._identity()
            return entry.handle

    def begin(self, action, *, model_step):
        with self._operation(model_step):
            self._running()
            self._observe(model_step)
            if (type(action) is not ScheduledAction
                    or any(type(v) is not int for v in (action.step, action.index, action.priority))
                    or any(type(v) is not str for v in (action.event_id, action.link_id, action.kind))
                    or type(action.event_json) is not bytes
                    or action.stimulus_json is not None and type(action.stimulus_json) is not bytes
                    or type(action.writable_targets) is not tuple):
                raise ICDError('STATE', 'typed original scheduled action required')
            key = (action.event_id, action.index)
            if self._actions.get(key) != action or key in self._attempted or action.kind == 'END_CLEANUP':
                raise ICDError('STATE', 'unattempted original action required; cleanup uses its own entry')
            if action.step != model_step:
                raise ICDError('TIMEOUT', 'original action step missed; no rebasing')
            native = action.link_id in ('CANT','ETHGEN') and action.kind in KINDS
            if native:
                target = (self._target_authorizer.approve(action,model_step=model_step)
                          if self._target_authorizer is not None else self.services.native_target(action, model_step=model_step))
                snapshot = self._observe(model_step)
                if type(target) is not int or not 0 <= target <= MAX_STEP:
                    raise ICDError('SCHEMA', 'explicit approved uint32 native target required')
                if snapshot.state == 'RUNNING':
                    if target <= model_step:
                        raise ICDError('LATE', 'running native target must precede its actual future model boundary')
                    if target-model_step > self.session.capabilities['max_target_ahead_steps']:
                        raise ICDError('RANGE', 'native target exceeds the frozen ahead range')
                elif target != model_step:
                    raise ICDError('STATE', 'frozen native target must equal the actual current model step')
            self._attempted.add(key)
            self._last_step = model_step
            owner = self.native if native else self.services
            if native and self._target_authorizer is not None:
                with self._target_authorizer.allocation_scope(action,target,self.native):
                    delegate=self.native.begin(action,model_step=model_step,target_step=target)
            else:
                delegate = (self.native.begin(action, model_step=model_step, target_step=target) if native
                            else self.services.begin(action, model_step=model_step))
            entry = self._new(action.kind, owner, delegate)
            self._identity()
            return entry.handle

    def poll(self, handle, *, model_step):
        with self._operation(model_step):
            entry = self._owned(handle)
            if entry.result is not None:
                return entry.result
            self._running()
            self._identity()
            result=(self.native.retired_lifecycle_result(entry.delegate,model_step=model_step)
                    if entry.owner is self.native else None)
            if result is None:
                self._observe(model_step)
                result = entry.owner.poll(entry.delegate, model_step=model_step)
            self._last_step = model_step
            self._identity()
            ScenarioExecution._progress(result, entry.delegate, ActionProgress)
            wrapped = replace(result, handle=handle)
            if wrapped.state != 'PENDING':
                entry.result = wrapped
            return wrapped

    def _stop_native(self, model_step):
        try:
            self.native.stop(model_step=model_step)
            return True
        except Exception as error:
            code = ScenarioExecution._error(error)
            self._cleanup_error('LOCAL', code)
            return False

    def _cleanup_error(self, kind, code):
        # Closed error vocabulary and distinct roles bound this history even
        # when a stopped model cannot advance while cleanup is retried.
        if (kind, code) not in self._cleanup_errors:
            self._cleanup_errors.append((kind, code))

    def begin_cleanup(self, cleanup, *, model_step):
        with self._operation(model_step):
            if not self._ready or self._cleanup_handle is not None:
                raise ICDError('STATE', 'original cleanup begins once after driver preflight')
            self.contract.validate_source_definition('Cleanup', cleanup)
            self._closing, self._last_step = True, model_step
            entry = self._new('CLEANUP', self.services)
            self._cleanup_handle = entry.handle
            try:
                entry.deadline_ns = self._now() + self.contract.entry(37)['valid_for_ms']*1_000_000
            except Exception as error:
                entry.local_error = ScenarioExecution._error(error)
                self._cleanup_error('LOCAL_CLOCK', entry.local_error)
            self._stop_native(model_step)
            try:
                self._identity()
                self._attach(entry, self.services.begin_cleanup(cleanup, model_step=model_step))
                self._identity(allow_closed=True)
            except Exception as error:
                entry.begin_error = ScenarioExecution._error(error)
                self._cleanup_error('REMOTE_BEGIN', entry.begin_error)
            return entry.handle

    def poll_cleanup(self, handle, *, model_step):
        with self._operation(model_step):
            entry = self._owned(handle, cleanup=True)
            self._last_step = model_step
            # Local ownership must remain recoverable even after a terminal
            # timeout; historical failure is never replaced with success.
            stopped = self._stop_native(model_step)
            if entry.result is not None:
                return entry.result
            if entry.begin_error is not None:
                result = CleanupProgress(handle, 'FAILED', error=entry.begin_error)
            else:
                try:
                    remote = entry.remote_terminal
                    if remote is None:
                        self._identity(allow_closed=True)
                        remote = self.services.poll_cleanup(entry.delegate, model_step=model_step)
                    ScenarioExecution._progress(remote, entry.delegate, CleanupProgress)
                    fields = remote.completed_fields
                    if (type(fields) is not tuple
                            or any(type(f) is not str or f not in CLEANUP_FIELDS for f in fields)
                            or len(set(fields)) != len(fields)):
                        raise ICDError('SCHEMA', 'distinct original cleanup receipt fields required')
                    if entry.remote_terminal is None:
                        self._identity(allow_closed=remote.state == 'COMPLETE'
                            and entry.cleanup_fields.union(fields) == set(CLEANUP_FIELDS))
                    entry.cleanup_fields.update(fields)
                    if remote.state != 'PENDING':
                        entry.remote_terminal = remote
                    fields = tuple(f for f in CLEANUP_FIELDS if f in entry.cleanup_fields)
                    if remote.state == 'COMPLETE' and set(fields) != set(CLEANUP_FIELDS):
                        result = CleanupProgress(handle, 'FAILED', fields, 'SAFETY')
                    elif remote.state == 'FAILED':
                        self._cleanup_error('REMOTE_RESULT', remote.error)
                        result = replace(remote, handle=handle, completed_fields=fields)
                    elif entry.local_error is not None:
                        result = CleanupProgress(handle, 'FAILED', fields, entry.local_error)
                    elif not stopped or self.native.pending_local_cleanup:
                        try:
                            now = self._now()
                        except Exception as error:
                            entry.local_error = ScenarioExecution._error(error)
                            self._cleanup_error('LOCAL_CLOCK', entry.local_error)
                            result = CleanupProgress(handle, 'FAILED', fields, entry.local_error)
                        else:
                            result = (CleanupProgress(handle, 'FAILED', fields, 'TIMEOUT')
                                      if now >= entry.deadline_ns else CleanupProgress(handle, 'PENDING', fields))
                    else:
                        result = replace(remote, handle=handle, completed_fields=fields)
                except Exception as error:
                    code = ScenarioExecution._error(error)
                    self._cleanup_error('REMOTE_POLL', code)
                    fields = tuple(f for f in CLEANUP_FIELDS if f in entry.cleanup_fields)
                    result = CleanupProgress(handle, 'FAILED', fields, code)
            if result.state != 'PENDING':
                entry.result = result
            return result
