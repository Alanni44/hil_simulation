"""Common semantic decisions only; actual consumers execute and prove effects."""

from dataclasses import dataclass
import math

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from .session import RegisteredController, SessionRegistry

STATES = ("CONFIGURED", "RUNNING", "PAUSED", "STOPPED", "FAILED")
SOURCES = ("NONE", "DEMO_MISSION", "PX4_SITL", "PHYSICAL_UUT")
CLEANUP_OPERATIONS = ("stop_periodic_senders", "stop_replay", "stop_video", "safe_actuators",
                      "release_control", "flush_receive_queues", "clear_model_faults",
                      "clear_bus_faults", "close_session")


@dataclass(frozen=True, slots=True)
class ModelView:
    model_id: str
    state: str
    model_step: int
    max_duration_steps: int
    control_source: str
    physical_closed_loop: bool
    configured_once: bool

    def __post_init__(self):
        if (type(self.model_id) is not str or not self.model_id
                or self.state not in STATES or self.control_source not in SOURCES
                or type(self.model_step) is not int or type(self.max_duration_steps) is not int
                or not 1 <= self.max_duration_steps <= 86400000
                or not 0 <= self.model_step <= self.max_duration_steps
                or type(self.physical_closed_loop) is not bool or type(self.configured_once) is not bool):
            raise ICDError("SCHEMA", "complete strict actual model view required")


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    next_state: str
    target_step: int
    steps: tuple
    clear_queues: bool
    safe_outputs: bool
    revoke_control: bool
    new_session: bool
    restore_initial: bool


@dataclass(frozen=True, slots=True)
class OwnerDecision:
    source: str
    role: str
    mode: str
    input_lane: str
    lease_ms: int
    clear_queues: bool
    safe_outputs: bool
    revoke_control: bool


@dataclass(frozen=True, slots=True)
class RegisteredOwnerDecision:
    decision: OwnerDecision
    producer: RegisteredController | None

    @property
    def execution_ready(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'


@dataclass(frozen=True, slots=True)
class CleanupDecision:
    session_id: int
    target_step: int
    reason: str | None
    operations: tuple


class SemanticGuards:
    def __init__(self, contract):
        self.contract = contract
        self._policy = contract.catalogue["policy"]
        self._models = set(contract.entry(3)["model_ids"])

    def _message(self, message, view, mid):
        if type(view) is not ModelView:
            raise ICDError("TARGET_MISSING", "actual consumer must supply a complete immutable model view")
        if view.model_id not in self._models:
            raise ICDError("MODEL", "actual model has no frozen contract")
        self.contract.validate_message(message, direction="TO_36", model_id=view.model_id)
        if message["message_id"] != mid:
            raise ICDError("UNSUPPORTED", "wrong message for this semantic gate")

    def _target(self, message, view):
        target = int(message["header"]["target_step"])
        if target > view.max_duration_steps:
            raise ICDError("RANGE", "target exceeds the configured run duration")
        if view.state == "RUNNING":
            if target <= view.model_step:
                raise ICDError("LATE", "running model boundary already began")
            if target - view.model_step > self._policy["max_ahead_steps"]:
                raise ICDError("RANGE", "target exceeds1000-step ahead limit")
        elif target != view.model_step:
            raise ICDError("STATE", "frozen safety boundary must name exactly the actual current step")
        return target

    def lifecycle(self, message, view):
        self._message(message, view, 4)
        payload = message["payload"]
        action = payload["action"]
        transitions = {"START": {"CONFIGURED": "RUNNING"}, "PAUSE": {"RUNNING": "PAUSED"},
                       "RESUME": {"PAUSED": "RUNNING"},
                       "STOP": {"CONFIGURED": "STOPPED", "RUNNING": "STOPPED", "PAUSED": "STOPPED"},
                       "RESET": {"PAUSED": "CONFIGURED", "STOPPED": "CONFIGURED"},
                       "STEP": {"PAUSED": "PAUSED"}}
        if payload["expected_state"] != view.state or view.state not in transitions[action]:
            raise ICDError("STATE", "lifecycle expected state or transition does not match the actual model")
        if action in ("START", "RESUME", "RESET", "STEP") and not view.configured_once:
            raise ICDError("STATE", "complete initial configuration has not been applied")
        target = self._target(message, view)
        steps = ()
        if action == "STEP":
            if view.physical_closed_loop:
                raise ICDError("UNSUPPORTED", "physical closed loop cannot compress model time using STEP")
            if view.control_source != "NONE":
                raise ICDError("CONTROL_OWNER", "offline STEP requires control source NONE")
            end = view.model_step + int(payload["step_count"])
            if end > view.max_duration_steps:
                raise ICDError("RANGE", "sequentialSTEP would exceed the run duration")
            steps = tuple(range(view.model_step + 1, end + 1))
        safety = action != "START"
        return LifecycleDecision(transitions[action][view.state], target, steps,
                                 action != "START", safety, safety,
                                 action in ("RESET", "RESUME"), action == "RESET")

    def control_owner(self, message, view, *, declared_controller, controller_session_roles,
                      internal_controller_ready):
        self._message(message, view, 6)
        if (declared_controller not in SOURCES or type(controller_session_roles) is not tuple
                or any(role not in ("STIMULUS", "CONTROLLER", "OBSERVER") for role in controller_session_roles)
                or type(internal_controller_ready) is not bool):
            raise ICDError("SCHEMA", "actual configured producer capabilities required")
        payload = message["payload"]
        source = payload["source"]
        if view.state == "FAILED":
            raise ICDError("STATE", "failed model must recover at its actual safety boundary")
        if source != "NONE":
            if view.state != "PAUSED":
                raise ICDError("STATE", "grant or switch control source requires PAUSED")
            if source == "DEMO_MISSION" and view.model_id != "quadrotor_hil":
                raise ICDError("UNSUPPORTED", "demo mission is only defined for quadrotor")
            if source != declared_controller or payload["role"] != "CONTROLLER":
                raise ICDError("CONTROL_OWNER", "producer source and actual control role do not match configuration")
            if payload["input_lane"] == "INTERNAL_CONTROLLER":
                if not internal_controller_ready:
                    raise ICDError("TARGET_MISSING", "declared internal controller has no actual output consumer")
            elif "CONTROLLER" not in controller_session_roles:
                raise ICDError("AUTHORIZATION", "selected external producer has no CONTROLLER session role")
        self._target(message, view)
        return OwnerDecision(source, payload["role"], payload["mode"], payload["input_lane"],
                             0 if source == "NONE" else self._policy["control_timeout_ms"], True, True, True)

    def external_control_owner(self, message, view, *, registry, producer_identity,
                               declared_controller, now_ns):
        """Resolve real receiver roles before deciding; effects remain mandatory."""
        self._message(message,view,6)
        if (type(registry) is not SessionRegistry or not self.contract.component_hashes
                or registry.contract.component_hashes != self.contract.component_hashes
                or registry.contract.baseline_sha256 != self.contract.baseline_sha256):
            raise ICDError('HASH', 'actual registry with the same verified contract required')
        registry.observe_admitted(message,now_ns=now_ns)
        sid = message['header']['session_id']
        selector = registry.identity(sid)
        if 'STIMULUS' not in registry.roles(sid):
            raise ICDError('AUTHORIZATION', 'actual control selector has no STIMULUS grant')
        if selector['model_id'] != view.model_id:
            raise ICDError('MODEL', 'actual selector and model view differ')
        payload = message['payload']
        if payload['source'] == 'NONE' or payload['input_lane'] == 'INTERNAL_CONTROLLER':
            decision = self.control_owner(message,view,declared_controller=declared_controller,
                controller_session_roles=(),internal_controller_ready=False)
            return RegisteredOwnerDecision(decision,None)
        producer = registry.registered_controller(producer_identity,now_ns=now_ns)
        identity = producer.identity
        if any(identity[k] != selector[k] for k in
               ('run_id','vehicle_id','scenario_id','model_id','definition_version')):
            raise ICDError('AUTHORIZATION', 'producer and selector belong to different run contexts')
        decision = self.control_owner(message,view,declared_controller=declared_controller,
            controller_session_roles=producer.roles,internal_controller_ready=False)
        return RegisteredOwnerDecision(decision,producer)

    @staticmethod
    def _ground(ground_down):
        try:
            valid = type(ground_down) in (int, float) and math.isfinite(ground_down)
        except OverflowError:
            valid = False
        if not valid:
            raise ICDError("RESOURCE", "actual ground sample at the requested point required")
        return ground_down

    def _initial(self, state, model_id, ground_down):
        ground = self._ground(ground_down)
        orientation = state["orientation"]
        norm = math.sqrt(sum(orientation[key] ** 2 for key in ("q_w", "q_x", "q_y", "q_z")))
        if abs(norm - 1) > 1e-6:
            raise ICDError("RANGE", "initial quaternion is not unit length; no normalization")
        down = state["position"]["down_m"]
        if down > ground + 1e-6:
            raise ICDError("RANGE", "initial point is below terrain")
        on_ground = abs(down - ground) <= 1e-6
        if state["airborne"] == on_ground:
            raise ICDError("RANGE", "airborne flag and terrain-relative height disagree")
        if model_id != "fixed_wing_hil" and (state["airborne"] or any(
                state[field] != 0 for field in ("velocity_n_mps", "velocity_e_mps", "velocity_d_mps",
                                                "p_radps", "q_radps", "r_radps"))):
            raise ICDError("RANGE", "quad/hex initial state must be stationary on ground")

    def run_configure(self, message, view, *, terrain_ground_down=None):
        self._message(message, view, 3)
        if view.state != "STOPPED" and not (view.state == "CONFIGURED" and not view.configured_once):
            raise ICDError("STATE", "RunConfigure requires STOPPED or initial CONFIGURED")
        self._target(message, view)
        payload = message["payload"]
        initial = payload["initial_inputs"]
        if payload["model_id"] != view.model_id or initial["model_id"] != payload["model_id"]:
            raise ICDError("MODEL", "configured model and complete initial branch must match actual selection")
        if payload["controller"] == "DEMO_MISSION" and view.model_id != "quadrotor_hil":
            raise ICDError("UNSUPPORTED", "nonquad model has no demo mission controller")
        for value in initial["flight_control"].values():
            if any(element != 0 for element in (value if type(value) is list else (value,))):
                raise ICDError("SAFETY", "all explicit initial control values must be safe zero")
        root_ground = -initial["environment"]["ground_height_m"]
        if terrain_ground_down is None:
            if payload["terrain_resource_sha256"] is not None:
                raise ICDError("RESOURCE", "configured terrain must be resolved at the initial point")
            ground = root_ground
        else:
            ground = self._ground(terrain_ground_down)
            if abs(ground - root_ground) > 1e-6:
                raise ICDError("RANGE", "terrain and explicit root ground height disagree")
        self._initial(payload["initial_state"], view.model_id, ground)
        sensor = initial["sensor_fault"]
        if not sensor["gps_valid"] and sensor["gps_fix_type"] != "NO_FIX":
            raise ICDError("BUSINESS_FAILED", "invalid initialGPS requires NO_FIX")
        return canonicalize(payload)

    def initial_state(self, message, view, *, ground_down):
        self._message(message, view, 5)
        if view.state not in ("CONFIGURED", "PAUSED"):
            raise ICDError("STATE", "InitialState is a frozen initialization input pending actual RESET")
        self._target(message, view)
        self._initial(message["payload"], view.model_id, ground_down)
        return canonicalize(message["payload"])

    def cleanup(self, message, view):
        mid = message.get("message_id") if type(message) is dict else None
        self._message(message, view, mid)
        if mid not in (37, 38):
            raise ICDError("UNSUPPORTED", "complete Cleanup or SessionClose required")
        target = self._target(message, view) if mid == 37 else view.model_step
        return CleanupDecision(message["header"]["session_id"], target,
                               message["payload"]["reason"] if mid == 38 else None,
                               CLEANUP_OPERATIONS)
