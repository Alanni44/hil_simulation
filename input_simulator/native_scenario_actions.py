"""Original native send handlers, not a complete scenario driver or qualification."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import threading

from icd_runtime.errors import ICDError
from icd_runtime.contract import Contract
from icd_runtime.json_codec import canonicalize, loads
from .dispatch import UDPDispatcher
from .live_tool_input import ToolPreparationError
from .native_tools import NativeToolCoordinator
from .scenario import MAX_STEP, ScenarioPlan, ScheduledAction
from .scenario_execution import ActionProgress, ScenarioExecution
from .scapy_source import ScapySource
from .session import MAX_REPLY_BYTES, _snapshot_message


SEND_KINDS = frozenset(('SEND', 'FAULT', 'WAVEFORM', 'PERIODIC_START', 'PERIODIC_SAMPLE'))
KINDS = SEND_KINDS | {'PERIODIC_STOP'}
TERMINALS = frozenset(('COMPLETE', 'FAILED', 'TIMEOUT', 'CANCEL'))


@dataclass(frozen=True, slots=True)
class NativeActionHandle:
    event_id: str
    index: int
    link_id: str
    model_step: int
    target_step: int


@dataclass(frozen=True, slots=True)
class NativeActionRecord:
    handle: NativeActionHandle
    kind: str
    header: object = None
    request_json: bytes | None = None
    reply_json: bytes | None = None
    error: str | None = None
    qualification_status: str = 'NOT_EVALUATED'


@dataclass
class _Action:
    handle: NativeActionHandle
    scheduled: ScheduledAction
    row: int
    header: object = None
    plan: object = None
    result: object = None
    reclaimed: bool = False
    failed_preparation: object = None


class NativeScenarioActions:
    def __init__(self, contract, plan, coordinator, *, can_sender=None,
                 assigned_links=None, max_pending=64, max_records=4096, max_bytes=16*1024*1024):
        if (not isinstance(contract, Contract) or type(plan) is not ScenarioPlan or not contract.component_hashes
                or plan.baseline_sha256 != contract.baseline_sha256):
            raise ICDError('HASH', 'original verified scenario plan required')
        for value, maximum in ((max_pending, 64), (max_records, 65536), (max_bytes, 128*1024*1024)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ICDError('CAPACITY', 'bounded integral native handler limits required')
        if type(coordinator) not in (NativeToolCoordinator, UDPDispatcher):
            raise ICDError('STATE', 'actual original native coordinator or standalone dispatcher required')
        self.coordinator = coordinator if type(coordinator) is NativeToolCoordinator else None
        self.dispatcher = coordinator.dispatcher if self.coordinator else coordinator
        self.session, self.contract = self.dispatcher.session, contract
        if (self.session.contract.baseline_sha256 != contract.baseline_sha256
                or self.session.contract.component_hashes != contract.component_hashes):
            raise ICDError('HASH', 'same original verified source baseline required')
        if can_sender is not None and (self.coordinator is None
                or not any(sender is can_sender for sender in self.coordinator.senders)):
            raise ICDError('STATE', 'explicit registered original CAN sender required')
        definition = plan.scenario
        if assigned_links is not None and (type(assigned_links) is not tuple or not assigned_links
                or any(type(link) is not str or link not in ('CANT', 'ETHGEN') for link in assigned_links)
                or len(set(assigned_links)) != len(assigned_links)):
            raise ICDError('SCHEMA', 'explicit distinct original native handler links required')
        self.assigned_links = assigned_links
        ids = {e['history_id'] for e in definition['events'] if e['type'] == 'REPLAY'}
        if len(ids) > 1 or ScenarioPlan.compile(contract, definition, model_id=plan.model_id,
                history_id=next(iter(ids), None)) != plan:
            raise ICDError('RESOURCE', 'scenario differs from its original compiled resource')
        count = sum(s.count for s in plan._streams if loads(s.event_json)['type'] in KINDS
                    and (assigned_links is None or loads(s.event_json)['link_id'] in assigned_links))
        largest = max((len(s.event_json) for s in plan._streams), default=0)
        if count*3 > max_records or len(plan.scenario_json)+count*(largest+MAX_REPLY_BYTES+4096) > max_bytes:
            raise ICDError('CAPACITY', 'complete finite native action history exceeds its record/byte budget')
        self.plan, self.sender = plan, can_sender
        self._actions = {(a.event_id, a.index): a for a in plan.iter_actions(max_actions=1000000)
                         if a.kind in KINDS and (assigned_links is None or a.link_id in assigned_links)}
        self._sid = self.session.session_id
        self._max_pending = max_pending
        self._entries, self._attempted, self._records = {}, {}, []
        self._anchors = {}
        self._recording_owner = None
        self._lock = threading.Lock()
        self._ready = self._closing = False
        self._last_step = None

    @property
    def execution_ready(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def records(self):
        return tuple(self._records)

    @property
    def pending_count(self):
        return sum(entry.result is None for entry in self._entries.values())

    @property
    def pending_local_cleanup(self):
        return any((entry.plan is not None or entry.failed_preparation is not None) and not entry.reclaimed or entry.header is not None
                   and entry.scheduled.link_id == 'ETHGEN' and entry.header.sequence in self.dispatcher._pending
                   for entry in self._entries.values())

    @contextmanager
    def _operation(self):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'native scenario handler requires one non-reentrant owner')
        try:
            if self._recording_owner is not None:
                from .evidence_recorder import ObservationRecorder
                if (type(self._recording_owner) is not ObservationRecorder
                        or not self._recording_owner._owns_scenario_actions(self)):
                    raise ICDError('STATE', 'native action cannot replace its recorded original owners')
            yield
        finally:
            self._lock.release()

    def _step(self, step):
        if type(step) is not int or not 0 <= step <= MAX_STEP or self._last_step is not None and step < self._last_step:
            raise ICDError('SCHEMA', 'explicit nondecreasing original model step required')

    @contextmanager
    def _root(self):
        if self.coordinator:
            with self.coordinator._operation():
                yield
        else:
            if self.session._native_tool_coordinator is not None:
                raise ICDError('STATE', 'attached native coordinator cannot be bypassed by a standalone handler')
            yield

    def _current(self):
        if (self.session.session_id != self._sid or self._sid is None or self.session._state != 'LIVE'
                or self.session._now() >= self.session._deadline_ns):
            raise ICDError('STALE_SESSION', 'original native run requires its current genuine live grant')
        model = loads(self.session._identity_json)['model_id']
        if model != self.plan.model_id or model not in self.session.capabilities['model_ids']:
            raise ICDError('MODEL', 'original run model differs from the actual published grant')
        if self.session._dispatcher is not self.dispatcher:
            raise ICDError('STATE', 'original dispatcher no longer owns this native run')
        if (self.sender is not None and type(self.session.transport) is ScapySource
                and self.session.transport.reservations is not self.sender.book):
            raise ICDError('STATE', 'original native links must use the same reservation book')

    def _validate_action_backend(self, action, target_step):
        if action.link_id == 'CANT':
            if self.coordinator is None or self.sender is None:
                raise ICDError('TARGET_MISSING', 'explicit original CANT sender is unavailable')
            with self.coordinator._delegate(self.sender, prepare=True):
                self._current()
                self.sender._check_local_operation(False)
                self.sender.builder._binding(self.sender.reservation, self.sender.binding)
                if action.stimulus is not None:
                    h = self.session._preview_header(action.stimulus['message_id'], target_step, None)
                    value = {**action.stimulus, 'header': asdict(h)}
                    frames = tuple(self.sender.wire.encode(value, 'CANFD'))
                    if self.sender.builder.protocol.encode(value) != frames:
                        raise ICDError('RESOURCE', 'original selected protocol differs from the native wire group')
        elif action.link_id == 'ETHGEN':
            with self.dispatcher._operation(), self.session._operation(owner=self.dispatcher):
                self._current()
                source = self.session.transport
                if type(source) is not ScapySource:
                    raise ICDError('TARGET_MISSING', 'ETHGEN requires original Scapy, not a plain UDP substitute')
                source.reservations.validate(source.reservation)
                if (source._closing or source._l2.closed
                        or source.socket.fileno() < 0 or source.feedback_socket.fileno() < 0):
                    raise ICDError('STATE', 'original Scapy backend is closed')
                if action.stimulus is not None:
                    self.session._preview_header(action.stimulus['message_id'], target_step, None)
        else:
            raise ICDError('TARGET_MISSING', 'no original native sending implementation for this tool branch')

    def preflight(self):
        with self._operation(), self._root():
            if self._closing or self._entries:
                raise ICDError('STATE', 'native preflight must precede any original event attempt')
            for action in self._actions.values():
                self._validate_action_backend(action, 0)
            self._ready = True

    def _owned(self, handle):
        entry = self._entries.get(id(handle))
        if type(handle) is not NativeActionHandle or entry is None or entry.handle is not handle:
            raise ICDError('STATE', 'exact original native action handle required')
        return entry

    def _check_records(self):
        for owner, (count, anchor) in self._anchors.items():
            rows = owner.records
            if len(rows) < count or count and rows[count-1] is not anchor:
                raise ICDError('STATE', 'original native records were reclaimed before handler observation')

    def _anchor(self):
        for owner in (self.dispatcher, self.sender):
            if owner is not None:
                rows = owner.records
                self._anchors[owner] = (len(rows), rows[-1] if rows else None)

    def _reclaim_can(self, entry):
        if not entry.reclaimed and (entry.plan is not None or entry.failed_preparation is not None):
            if entry.failed_preparation is not None:
                self.coordinator.discard_failed_can(self.sender, entry.failed_preparation)
            else:
                self.coordinator.retire_can(self.sender, entry.plan)
                self.coordinator.discard_can(self.sender, entry.plan)
            entry.reclaimed = True

    def _finish(self, entry, state, error=None, *, reply=None, kind=None):
        if entry.result is not None:
            return entry.result
        entry.result = ActionProgress(entry.handle, state, error)
        self._records.append(NativeActionRecord(entry.handle, kind or state, entry.header,
                                               reply_json=None if reply is None else _snapshot_message(reply), error=error))
        return entry.result

    def begin(self, action, *, model_step, target_step):
        with self._operation():
            if not self._ready or self._closing:
                raise ICDError('STATE', 'preflight the assigned native handlers before starting, and never after stop')
            if (type(action) is not ScheduledAction or type(action.kind) is not str
                    or any(type(value) is not int for value in (action.step, action.priority, action.index))
                    or any(type(value) is not str for value in (action.event_id, action.link_id))
                    or type(action.event_json) is not bytes
                    or action.stimulus_json is not None and type(action.stimulus_json) is not bytes
                    or type(action.writable_targets) is not tuple):
                raise ICDError('STATE', 'typed original action metadata required')
            if action.kind not in KINDS:
                raise ICDError('TARGET_MISSING', 'this is a native send handler, not an assertion/replay/cleanup driver')
            key = (action.event_id, action.index)
            if self._actions.get(key) != action or key in self._attempted:
                raise ICDError('STATE', 'original unattempted action from this exact compiled plan required')
            self._step(model_step)
            if model_step != action.step:
                raise ICDError('TIMEOUT', 'original scheduled step missed; no catch-up or rebasing')
            if type(target_step) is not int or not 0 <= target_step <= MAX_STEP:
                raise ICDError('SCHEMA', 'explicit uint32 target_step required, independent of sample step')
            if self.pending_count >= self._max_pending:
                raise ICDError('BUFFER_FULL', 'native action pending limit reached before input allocation')
            self._check_records()
            with self._root():
                self._validate_action_backend(action, target_step)
            self._last_step = model_step
            handle = NativeActionHandle(action.event_id, action.index, action.link_id, model_step, target_step)
            entry = _Action(handle, action, len(self._records))
            self._entries[id(handle)] = self._attempted[key] = entry
            self._records.append(NativeActionRecord(handle, 'STARTED'))
            try:
                if action.kind == 'PERIODIC_STOP':
                    self._finish(entry, 'COMPLETE', kind='LOCAL_PERIODIC_STOP')
                elif action.link_id == 'CANT':
                    entry.plan = self.coordinator.prepare_can(self.sender, action.stimulus, target_step=target_step)
                    value = entry.plan.source_input.message
                    from icd_runtime.wire import Header
                    entry.header = Header(**value['header'])
                    self._records[entry.row] = replace(self._records[entry.row], header=entry.header,
                                                       request_json=entry.plan.source_input.input_json)
                    self.coordinator.send_can(self.sender, entry.plan)
                else:
                    owner = self.coordinator or self.dispatcher
                    entry.header = owner.submit(action.stimulus, target_step=target_step)
                    self._records[entry.row] = replace(self._records[entry.row], header=entry.header,
                        request_json=_snapshot_message({**action.stimulus, 'header': asdict(entry.header)}))
                    owner.poll()
            except Exception as error:
                if isinstance(error, ToolPreparationError):
                    entry.failed_preparation = error.failure
                    item = error.failure.source_input
                    from icd_runtime.wire import Header
                    entry.header = Header(**item.message['header'])
                    self._records[entry.row] = replace(self._records[entry.row], header=entry.header,
                                                       request_json=item.input_json)
                self._finish(entry, 'FAILED', ScenarioExecution._error(error))
            finally:
                self._anchor()
            return handle

    def _udp_result(self, entry):
        rows = [row for row in self.dispatcher.records if row.header is entry.header]
        terminal = next((row for row in reversed(rows) if row.kind in TERMINALS), None)
        if terminal is None:
            return None
        reply = next((row.reply for row in reversed(rows) if row.reply_json is not None), None)
        return self._finish(entry, 'COMPLETE' if terminal.kind == 'COMPLETE' else 'FAILED',
                            terminal.error, reply=reply)

    def retired_lifecycle_result(self, handle, *, model_step):
        """Consume only the retained terminal transaction that retired this SID; no I/O."""
        from .model_clock import ModelEpochRetirement
        with self._operation(), self._root():
            entry=self._owned(handle)
            with self.dispatcher._operation(), self.session._operation(owner=self.dispatcher):
                if not self.session._model_clock_retired:
                    return None
                self._current()
                self._step(model_step)
                self._check_records()
                receipt=self.session._model_epoch_retirement
                original=self._records[entry.row]
                if (self._closing or type(receipt) is not ModelEpochRetirement
                        or receipt.session_id!=self._sid or receipt.model_id!=self.plan.model_id
                        or receipt.identity_json!=self.session._identity_json
                        or entry.scheduled.link_id!='ETHGEN' or entry.header is None
                        or entry.scheduled.stimulus['message_id']!=4
                        or entry.scheduled.stimulus['payload']['action'] not in ('RESET','RESUME')
                        or model_step!=entry.handle.model_step
                        or original.header is not entry.header or original.request_json is None
                        or canonicalize(loads(original.request_json))!=receipt.request_json):
                    raise ICDError('STALE_SESSION','only the exact original retiring lifecycle transaction may finish')
                rows=[r for r in self.dispatcher.records if r.header is entry.header]
                terminal=next((r for r in reversed(rows) if r.kind in TERMINALS),None)
                if (terminal is None or terminal.kind!='COMPLETE' or terminal.error is not None
                        or not any(r.reply_json is not None and canonicalize(r.reply)==receipt.reply_json for r in rows)):
                    raise ICDError('STALE_SESSION','retirement requires the already retained actual terminal receipt')
                self._last_step=model_step
                result=self._finish(entry,'COMPLETE',reply=loads(receipt.reply_json))
                self._anchor()
                return result

    def poll(self, handle, *, model_step):
        with self._operation():
            entry = self._owned(handle)
            self._step(model_step)
            self._last_step = model_step
            if entry.result is not None:
                return entry.result
            if self._closing:
                raise ICDError('STATE', 'native handler is stopping; retry local stop, not sends')
            self._check_records()
            try:
                if entry.scheduled.link_id == 'CANT':
                    with self._root():
                        with self.coordinator._delegate(self.sender, prepare=True):
                            self._current()
                            group = self.sender._sent(entry.plan)
                            if self.session._now() >= group.started_ns + entry.header.valid_for_ms*1_000_000:
                                raise ICDError('TIMEOUT', 'original native request validity elapsed')
                    reply = self.coordinator.poll_can(self.sender, entry.plan)
                    if reply is not None and (reply['message_id'] != 130
                            or reply['payload']['stage'] in ('APPLIED', 'CONSUMED', 'FAILED')):
                        error = reply['payload']['error'] if reply['message_id'] == 130 and reply['payload']['error'] != 'OK' else None
                        self._finish(entry, 'FAILED' if error else 'COMPLETE', error, reply=reply)
                        self._reclaim_can(entry)
                else:
                    if self._udp_result(entry) is None:
                        (self.coordinator or self.dispatcher).poll()
                        self._udp_result(entry)
            except Exception as error:
                code = ScenarioExecution._error(error)
                if entry.result is None:
                    self._finish(entry, 'FAILED', code)
                else:
                    if entry.result.state == 'COMPLETE':
                        entry.result = ActionProgress(handle, 'FAILED', code)
                    self._records.append(NativeActionRecord(handle, 'LOCAL_RECLAIM_FAILED', entry.header, error=code))
            finally:
                self._anchor()
            return entry.result or ActionProgress(handle, 'PENDING')

    def stop(self, *, model_step):
        with self._operation():
            self._step(model_step)
            self._last_step, self._closing = model_step, True
            for entry in self._entries.values():
                if entry.scheduled.link_id == 'CANT':
                    self._reclaim_can(entry)
                elif entry.header is not None:
                    if entry.header.sequence in self.dispatcher._pending:
                        (self.coordinator or self.dispatcher).cancel(entry.header)
                    elif entry.result is None:
                        self._udp_result(entry)
                if entry.result is None:
                    self._finish(entry, 'FAILED', 'STATE', kind='LOCAL_CANCELLED')
            self._anchor()
