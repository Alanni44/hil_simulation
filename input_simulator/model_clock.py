"""Read-only standard Status provenance, not a synchronized model scheduler."""

from contextlib import ExitStack
from dataclasses import dataclass, replace
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


STATES = frozenset(('CONFIGURED', 'RUNNING', 'PAUSED', 'STOPPED', 'FAILED'))
CONTROL_SOURCES = frozenset(('DEMO_MISSION', 'PX4_SITL', 'PHYSICAL_UUT'))
CONTROL_LANES = frozenset(('INTERNAL_CONTROLLER', 'FLIGHT_CONTROL', 'ACTUATOR'))


@dataclass(frozen=True, slots=True)
class ModelEpochRetirement:
    session_id: int
    model_id: str
    identity_json: bytes
    request_json: bytes
    reply_json: bytes
    started_ns: int
    completed_ns: int
    transport: str
    channel: str


@dataclass(frozen=True, slots=True)
class ModelClockSnapshot:
    session_id: int
    model_id: str
    model_step: int
    state: str
    transport: str
    channel: str
    started_ns: int
    completed_ns: int
    deadline_ns: int
    request_json: bytes
    status_json: bytes

    @property
    def status(self):
        return loads(self.status_json)

    @property
    def request(self):
        return loads(self.request_json)

    @property
    def execution_ready(self):
        return False

    @property
    def synchronized(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


def _remember_feedback(session, request, reply, started, completed, *, transport, channel, fresh):
    if session._operation_thread != threading.get_ident():
        raise ICDError('STATE', 'standard model feedback requires the actual source operation owner')
    if (fresh is not True or session._state != 'LIVE' or session._sid is None
            or not 0 <= started <= completed < session._deadline_ns
            or request['header']['session_id'] != session._sid
            or reply['header']['session_id'] != session._sid):
        return
    if reply['message_id'] == 131 and request['message_id'] == 2:
        header = request['header']
        payload = reply['payload']
        # Receiver sequence orders observations, while request order controls
        # cache replacement. An interleaved older request still raises the floor.
        session._model_step_floor = max(session._model_step_floor, payload['model_step'])
        if (session._model_clock_retired or header['sequence'] <= session._model_status_request_sequence
                or header['transaction_id'] <= session._model_status_transaction):
            return
        session._model_status = ModelClockSnapshot(
            session._sid, loads(session._identity_json)['model_id'], payload['model_step'], payload['state'],
            transport, channel, started, completed,
            started + session.contract.entry(131)['valid_for_ms'] * 1_000_000,
            canonicalize(request), canonicalize(reply))
        session._model_status_request_sequence = header['sequence']
        session._model_status_transaction = header['transaction_id']
    elif (reply['message_id'] == 130 and request['message_id'] == 4
          and request['payload']['action'] in ('RESET', 'RESUME')):
        payload = reply['payload']
        probes = session.contract.catalogue['probe_catalog']
        lifecycle_probe = next(p['id'] for p in probes if p['name'] == 'consumer.Lifecycle')
        if (payload['stage'] == 'APPLIED' and payload['error'] == 'OK'
                and payload['probe_id'] == lifecycle_probe
                and 4 in session.capabilities['implemented_message_ids']
                and 'consumer.Lifecycle' in session.capabilities['available_probes']):
            # The frozen lifecycle policy requires retiring the old SID and
            # reauthorizing after RESET/RESUME; never permit same-SID rewind.
            if not session._model_clock_retired:
                session._model_epoch_retirement = ModelEpochRetirement(
                    session._sid, loads(session._identity_json)['model_id'], session._identity_json,
                    canonicalize(request), canonicalize(reply), started, completed, transport, channel)
                session._model_clock_retired = True
                session._model_status = None
                guard=session._runtime_target_guards.get(request['header']['sequence'])
                if guard is not None:
                    from .runtime_targets import RuntimeTargetGuard
                    if type(guard) is not RuntimeTargetGuard:
                        raise ICDError('STATE','original target guard required for epoch evidence')
                    guard.authorizer._remember_epoch(guard,session._model_epoch_retirement)


class ObservedModelClock:
    def __init__(self, session):
        from .session import SourceSession
        if not isinstance(session, SourceSession):
            raise ICDError('STATE', 'actual original SourceSession required')
        self.session = session

    def snapshot(self):
        session = self.session
        with ExitStack() as stack:
            dispatcher = session._dispatcher
            if dispatcher is not None:
                stack.enter_context(dispatcher._operation())
            stack.enter_context(session._operation(owner=dispatcher))
            now = session._now()
            if (session._state != 'LIVE' or session._sid is None or now >= session._deadline_ns
                    or session._model_clock_retired):
                raise ICDError('STALE_SESSION', 'current grant and fresh post-lifecycle session required')
            snapshot = session._model_status
            if snapshot is None:
                raise ICDError('TARGET_MISSING', 'no actual correlated standard Status model step')
            if (snapshot.session_id != session._sid
                    or snapshot.model_id != loads(session._identity_json)['model_id']):
                raise ICDError('STALE_SESSION', 'model observation belongs to another grant')
            if now >= snapshot.deadline_ns:
                raise ICDError('EXPIRED', 'standard Status expired from original Heartbeat start')
            if snapshot.model_step < session._model_step_floor:
                raise ICDError('CLOCK_UNSYNC', 'reported model step regressed within the same SID')
            return snapshot

    def require_step(self, step, *, required_state=None):
        if type(step) is not int or not 0 <= step <= 0xffffffff:
            raise ICDError('SCHEMA', 'explicit uint32 reported model step required')
        if required_state is not None and (type(required_state) is not str or required_state not in STATES):
            raise ICDError('SCHEMA', 'standard model state required')
        snapshot = self.snapshot()
        if snapshot.model_step != step:
            raise ICDError('CLOCK_UNSYNC', 'requested step differs from actual standard Status')
        if required_state is not None and snapshot.state != required_state:
            raise ICDError('STATE', 'reported model state differs from required state')
        return snapshot


@dataclass(frozen=True, slots=True)
class ControlLeaseSnapshot:
    """Observed standard lease only; Status cannot identify a unique owner SID."""
    session_id: int
    model_id: str
    source: str
    role: str
    input_lane: str
    mode: str
    owner_started_ns: int
    owner_completed_ns: int
    deadline_ns: int
    owner_request_json: bytes
    owner_reply_json: bytes
    lease_started_ns: int
    lease_completed_ns: int
    lease_request_json: bytes
    lease_reply_json: bytes
    transport: str
    channel: str

    @property
    def execution_ready(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


def _applied_consumer(session, mid, payload):
    probe = next(p for p in session.contract.catalogue['probe_catalog'] if p.get('message_id') == mid)
    return (payload['stage'] == 'APPLIED' and payload['error'] == 'OK'
            and payload['probe_id'] == probe['id']
            and probe['name'] in session.capabilities['available_probes'])


def _remember_control_feedback(session, request, reply, started, completed, *, transport, channel, fresh):
    if session._operation_thread != threading.get_ident():
        raise ICDError('STATE', 'control feedback requires the actual source operation owner')
    if (fresh is not True or session._state != 'LIVE' or session._sid is None
            or not 0 <= started <= completed < session._deadline_ns
            or session._model_clock_retired
            or request['header']['session_id'] != session._sid
            or reply['header']['session_id'] != session._sid):
        return
    lease = session._control_lease
    sequence = request['header']['sequence']
    if reply['message_id'] == 131 and request['message_id'] == 2:
        if session._control_requested_source is not None:
            payload = reply['payload']
            if (payload['control_source'] != session._control_requested_source or payload['safety_active']
                or payload['state'] not in ('PAUSED', 'RUNNING')):
                session._control_lease = None
                # Retain revocation even for an older request's fresh Status:
                # later ordinary heartbeats and pending owner ACKs cannot undo it.
                session._control_requested_source = None
                session._control_boundary_sequence = max(session._control_boundary_sequence, sequence)
        return
    if reply['message_id'] != 130:
        return
    mid, payload = request['message_id'], reply['payload']
    if mid not in session.capabilities['implemented_message_ids']:
        return
    if (mid in (6, 7, 8, 9, 14, 15, 16) and payload['stage'] == 'FAILED'
            and payload['error'] in ('CONTROL_OWNER', 'AUTHORIZATION', 'STALE_SESSION', 'SAFETY')):
        session._control_lease = None
        session._control_requested_source = None
        session._control_boundary_sequence = max(session._control_boundary_sequence, sequence)
        return
    duration = session.contract.catalogue['policy']['control_timeout_ms']*1_000_000
    if mid == 6:
        status = session._model_status
        definition = request['payload']
        if (sequence != session._control_boundary_sequence
                or session._control_requested_source != definition['source']
                or not _applied_consumer(session, mid, payload)
                or payload['applied_step'] != request['header']['target_step']
                or completed >= started+duration
                or status is None or status.state != 'PAUSED' or completed >= status.deadline_ns
                or status.status['payload']['safety_active']
                or status.model_step != request['header']['target_step']
                or definition['source'] not in CONTROL_SOURCES or definition['role'] != 'CONTROLLER'
                or definition['source'] == 'DEMO_MISSION' and status.model_id != 'quadrotor_hil'):
            return
        raw, feedback = canonicalize(request), canonicalize(reply)
        session._control_lease = ControlLeaseSnapshot(session._sid, status.model_id,
            definition['source'], definition['role'], definition['input_lane'], definition['mode'],
            started, completed, started+duration, raw, feedback,
            started, completed, raw, feedback, transport, channel)
    elif mid in (7, 8, 9, 14, 15, 16) and lease is not None:
        lane = 'FLIGHT_CONTROL' if mid in (7, 8, 9) else 'ACTUATOR'
        if (lane != lease.input_lane or completed >= lease.deadline_ns
                or started < lease.lease_started_ns
                or sequence <= loads(lease.lease_request_json)['header']['sequence']
                or payload['error'] != 'OK'
                or payload['stage'] != 'VALIDATED' and not _applied_consumer(session, mid, payload)
                or payload['stage'] == 'APPLIED' and payload['applied_step'] != request['header']['target_step']):
            return
        session._control_lease = replace(lease, deadline_ns=started+duration,
            lease_started_ns=started, lease_completed_ns=completed,
            lease_request_json=canonicalize(request), lease_reply_json=canonicalize(reply),
            transport=transport, channel=channel)


class ObservedControlLease:
    """Read-only necessary lease signal, never complete producer authorization."""
    def __init__(self, session):
        self.clock = ObservedModelClock(session)
        self.session = session

    def snapshot(self, *, model_step):
        status = self.clock.require_step(model_step)
        session = self.session
        with ExitStack() as stack:
            dispatcher = session._dispatcher
            if dispatcher is not None:
                stack.enter_context(dispatcher._operation())
            stack.enter_context(session._operation(owner=dispatcher))
            now = session._now()
            if (session._state != 'LIVE' or session._sid != status.session_id
                    or now >= session._deadline_ns or session._model_clock_retired):
                raise ICDError('STALE_SESSION', 'original current model grant required for control observation')
            if session._model_status is not status or now >= status.deadline_ns:
                raise ICDError('CLOCK_UNSYNC', 'model Status changed while reading the control observation')
            lease = session._control_lease
            if (lease is None or lease.session_id != session._sid or lease.model_id != status.model_id
                    or now >= lease.deadline_ns or status.state not in ('PAUSED', 'RUNNING')
                    or status.status['payload']['control_source'] != lease.source
                    or status.status['payload']['safety_active']):
                raise ICDError('CONTROL_OWNER', 'actual matching control lease is missing or expired')
            if 'CONTROLLER' not in session.roles:
                raise ICDError('AUTHORIZATION', 'original source has no actual CONTROLLER grant')
            return lease

    def require(self, *, model_step, source, input_lane):
        if (type(source) is not str or source not in CONTROL_SOURCES
                or type(input_lane) is not str or input_lane not in CONTROL_LANES):
            raise ICDError('SCHEMA', 'explicit frozen control source and input lane required')
        snapshot = self.snapshot(model_step=model_step)
        if snapshot.source != source or snapshot.input_lane != input_lane:
            raise ICDError('CONTROL_OWNER', 'observed control differs from the configured producer/lane')
        return snapshot
