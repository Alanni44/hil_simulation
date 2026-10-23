"""Actual model-boundary consumer for the first sequential input: ID10.

Reception and schema validation are deliberately insufficient here.  The
backend must stage the complete Environment snapshot and return a readback
from the generated model's target step before this service emits APPLIED.
"""

from dataclasses import dataclass
import copy
import hashlib
import json
import math
import socket
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from icd_runtime.json_codec import loads
from .configuration_service import (
    ModelConfigurationBackend,
    ModelConfigurationBoundary,
    ModelConfigurationContext,
    ModelConfigurationReceipt,
)
from .lifecycle_service import ModelLifecycleBackend
from .status_service import ModelStatusBackend, ModelStatusSample
from .model_bindings import ModelBindings
from .semantic_guards import ModelView
from .session import SessionRegistry


MAX_RECORDS = 4096
MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ResolvedRunConfigurationResources:
    """Immutable resource fact sampled before a RunConfigure write.

    ``ground_down`` is in the model's NED frame.  It is intentionally a
    resource-read fact rather than a value copied from ``initial_inputs``.
    """

    terrain_sha256: str
    obstacle_sha256: str
    ground_down: float


class StoredRunConfigurationResourceResolver:
    """Resolve frozen Terrain/Obstacles bytes from the owned HIL store.

    This class proves that the named, completed bytes still hash to the
    requested SHA-256 and that the Terrain origin covers the configured
    initial N/E point.  It does *not* claim the C model has applied a terrain
    or obstacle; that remains part of the C-core atomic configuration ABI.
    """

    def __init__(self, contract, store):
        from icd_runtime.contract import Contract
        from .resources import ResourceStore
        if (not isinstance(contract, Contract) or not contract.component_hashes
                or type(store) is not ResourceStore or store.contract is not contract):
            raise ICDError("STATE", "same-contract owned resource store required")
        self.contract, self.store = contract, store

    @staticmethod
    def _read(resource, expected_sha256):
        try:
            raw = resource.path.read_bytes()
        except OSError as error:
            raise ICDError("RESOURCE", "configured resource bytes are unavailable") from error
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ICDError("HASH", "configured resource bytes changed after resolution")
        return loads(raw)

    @staticmethod
    def _terrain_height(terrain, north_m, east_m):
        rows, columns = terrain["rows"], terrain["columns"]
        spacing_n, spacing_e = terrain["spacing_n_m"], terrain["spacing_e_m"]
        if (type(north_m) not in (int, float) or type(east_m) not in (int, float)
                or not math.isfinite(north_m) or not math.isfinite(east_m)):
            raise ICDError("RESOURCE", "finite initial N/E point required for terrain resolution")
        row, column = north_m / spacing_n, east_m / spacing_e
        if row < 0 or column < 0 or row > rows - 1 or column > columns - 1:
            raise ICDError("RESOURCE", "initial point lies outside configured terrain grid")
        low_row, low_column = int(math.floor(row)), int(math.floor(column))
        high_row, high_column = min(low_row + 1, rows - 1), min(low_column + 1, columns - 1)
        row_fraction, column_fraction = row - low_row, column - low_column
        heights = terrain["heights_m"]
        def value(r, c):
            return heights[r * columns + c]
        north_low = value(low_row, low_column) * (1.0 - column_fraction) + value(low_row, high_column) * column_fraction
        north_high = value(high_row, low_column) * (1.0 - column_fraction) + value(high_row, high_column) * column_fraction
        return north_low * (1.0 - row_fraction) + north_high * row_fraction

    def resolve(self, payload):
        if type(payload) is not dict:
            raise ICDError("SCHEMA", "complete RunConfigure payload required for resource resolution")
        terrain_sha = payload.get("terrain_resource_sha256")
        obstacle_sha = payload.get("obstacle_resource_sha256")
        initial = payload.get("initial_state")
        if type(initial) is not dict or type(initial.get("position")) is not dict:
            raise ICDError("SCHEMA", "RunConfigure initial position is required for resource resolution")
        if terrain_sha is None:
            ground_down = -float(payload["initial_inputs"]["environment"]["ground_height_m"])
        else:
            terrain_resource = self.store.resolve(terrain_sha, kind="TERRAIN")
            if terrain_resource.content_status != "DEFINED_JSON":
                raise ICDError("RESOURCE", "configured Terrain bytes lack frozen content validation")
            terrain = self._read(terrain_resource, terrain_sha)
            self.contract.validate_resource("TERRAIN", terrain)
            if canonicalize(terrain["origin"]) != canonicalize(payload["origin"]):
                raise ICDError("RESOURCE", "configured Terrain origin differs from RunConfigure origin")
            height_up = self._terrain_height(terrain, initial["position"]["north_m"],
                                             initial["position"]["east_m"])
            if not math.isfinite(height_up):
                raise ICDError("RESOURCE", "configured Terrain produced a non-finite height")
            ground_down = -height_up
        if obstacle_sha is not None:
            obstacle_resource = self.store.resolve(obstacle_sha, kind="OBSTACLES")
            if obstacle_resource.content_status != "DEFINED_JSON":
                raise ICDError("RESOURCE", "configured Obstacles bytes lack frozen content validation")
            obstacles = self._read(obstacle_resource, obstacle_sha)
            self.contract.validate_resource("OBSTACLES", obstacles)
        return ResolvedRunConfigurationResources(terrain_sha, obstacle_sha, ground_down)


class CcoreConfigurationBackend(ModelConfigurationBackend):
    """RunConfigure backend for a separately supervised C-core HIL process.

    The process boundary is real UDP, not an in-memory mirror.  A runtime is
    eligible only when its generated bridge explicitly advertises both a
    complete initial-state ABI and atomic configuration/readback support.
    Current ExtU/ExtY-only artifacts therefore fail closed before *any*
    configuration write; an echo from a management caller is never evidence.
    """

    _SOURCES = {
        "none": "NONE",
        "demo_mission": "DEMO_MISSION",
        "px4_sitl": "PX4_SITL",
        "physical_uut": "PHYSICAL_UUT",
    }

    def __init__(self, contract, endpoints, *, resource_resolver=None, timeout_s=0.05, poll_s=0.001,
                 socket_factory=socket.socket, clock=time.monotonic_ns,
                 require_prepared_existing=False):
        if (type(endpoints) is not dict or not endpoints or not callable(clock)
                or type(timeout_s) not in (int, float) or not 0 < timeout_s <= 1
                or type(poll_s) not in (int, float) or not 0 < poll_s <= .1
                or type(require_prepared_existing) is not bool):
            raise ICDError("SCHEMA", "bounded C-core endpoints and clock required")
        model_ids = tuple(endpoints)
        if any(type(model_id) is not str or type(endpoint) is not tuple or len(endpoint) != 2
               or type(endpoint[0]) is not str or type(endpoint[1]) is not int
               or not 1 <= endpoint[1] <= 65535 for model_id, endpoint in endpoints.items()):
            raise ICDError("SCHEMA", "each C-core model endpoint must be a host/port pair")
        super().__init__(contract, model_ids)
        if resource_resolver is not None and not callable(getattr(resource_resolver, "resolve", None)):
            raise ICDError("SCHEMA", "configured resource resolver must expose resolve(payload)")
        self._resource_resolver = resource_resolver
        # The formal gateway is a second-circle consumer.  It must never turn
        # an unprepared STOPPED target into CONFIGURED merely because a source
        # sent RunConfigure.  The dedicated PreparationService is the only
        # first-circle writer and deliberately creates this backend with the
        # default (False) setting.
        self._require_prepared_existing = require_prepared_existing
        self._clock = clock
        self._bridges = {
            model_id: QuadrotorEnvironmentBridge(endpoint, timeout_s=timeout_s,
                                                   poll_s=poll_s,
                                                   socket_factory=socket_factory,
                                                   clock=lambda: self._clock() / 1_000_000_000)
            for model_id, endpoint in endpoints.items()
        }

    def _status(self, model_id):
        reply = self._bridges[model_id]._exchange({
            "request_id": "run-configure-status", "cmd": "get_hil_status"})
        fields = reply.get("fields")
        if not reply.get("accepted") or type(fields) is not dict:
            raise ICDError("MODEL", "C-core did not return a HIL status receipt")
        return fields

    @classmethod
    def _boundary_values(cls, fields):
        lifecycle = fields.get("lifecycle")
        source = fields.get("control_source")
        sequence = fields.get("sequence")
        revision = fields.get("model_revision")
        model_state = fields.get("model_state")
        if (type(lifecycle) is not str or lifecycle not in ("STOPPED", "CONFIGURED", "RUNNING", "PAUSED", "FAILED")
                or source not in cls._SOURCES or type(sequence) is not int or not 0 <= sequence <= 0xffffffff
                or type(revision) is not int or not 0 <= revision <= 0xffffffff
                or type(model_state) is not dict or type(model_state.get("model_step")) is not int
                or model_state["model_step"] != sequence):
            raise ICDError("MODEL", "C-core status lacks coherent lifecycle/step/revision readback")
        return lifecycle, sequence, revision, cls._SOURCES[source]

    def read_boundary(self, identity, *, now_ns):
        if type(identity) is not dict or type(now_ns) is not int:
            raise ICDError("SCHEMA", "strict identity and C-core boundary sample time required")
        model_id = identity.get("model_id")
        if model_id not in self._bridges:
            raise ICDError("MODEL", "configuration identity has no C-core endpoint")
        fields = self._status(model_id)
        self._require_configuration_abi(fields)
        lifecycle, sequence, revision, source = self._boundary_values(fields)
        sampled = self._clock()
        if type(sampled) is not int or sampled < now_ns:
            raise ICDError("CLOCK_UNSYNC", "C-core boundary clock regressed")
        return ModelConfigurationBoundary(lifecycle, sequence, revision, source,
                                          sampled, sampled + 240_000_000)

    def _view(self, model_id, fields, request):
        lifecycle, sequence, _revision, source = self._boundary_values(fields)
        payload = request["payload"]
        return ModelView(model_id, lifecycle, sequence, payload["max_duration_steps"],
                         source, payload["controller"] == "PHYSICAL_UUT",
                         lifecycle in ("CONFIGURED", "RUNNING", "PAUSED"))

    def _require_configuration_abi(self, fields):
        if (fields.get("model_loaded") is not True
                or fields.get("initial_state_abi") is not True
                or fields.get("full_configuration_abi") is not True):
            raise ICDError("TARGET_MISSING",
                           "C-core generated bridge lacks verified initial-state/configuration ABI")

    def _configuration(self, model_id):
        reply = self._bridges[model_id]._exchange({
            "request_id": "run-configure-snapshot", "cmd": "get_configuration_snapshot"})
        fields = reply.get("fields")
        if (not reply.get("accepted") or type(fields) is not dict
                or type(fields.get("configuration")) is not dict
                or type(fields.get("model_revision")) is not int):
            raise ICDError("STATE", "C-core has no complete applied configuration")
        return fields["configuration"], fields["model_revision"]

    def _initial_readback(self, model_id, request):
        after = self._status(model_id)
        self._require_configuration_abi(after)
        state = after.get("initial_state")
        if type(state) is not dict:
            raise ICDError("MODEL", "C-core lacks direct configured initial-state readback")
        inputs_reply = self._bridges[model_id]._exchange({
            "request_id": "run-configure-input-readback", "cmd": "get_icd_snapshot",
            "params": {"snapshot": "initial"}})
        input_fields = inputs_reply.get("fields")
        if (not inputs_reply.get("accepted") or type(input_fields) is not dict
                or type(input_fields.get("inputs")) is not dict
                or type(input_fields.get("parameters")) is not dict):
            raise ICDError("MODEL", "C-core lacks direct configured input readback")
        initial_inputs = copy.deepcopy(request["payload"]["initial_inputs"])
        initial_inputs.update(input_fields["inputs"])
        initial_inputs["parameters"] = input_fields["parameters"]
        return after, state, initial_inputs

    def _resources(self, payload):
        if payload["terrain_resource_sha256"] is None and payload["obstacle_resource_sha256"] is None:
            return ResolvedRunConfigurationResources(
                None, None, -float(payload["initial_inputs"]["environment"]["ground_height_m"]))
        if self._resource_resolver is None:
            raise ICDError("TARGET_MISSING", "C-core terrain/obstacle resource resolver is not installed")
        value = self._resource_resolver.resolve(payload)
        if type(value) is not ResolvedRunConfigurationResources:
            raise ICDError("MODEL", "resource resolver did not return an immutable actual resource fact")
        if (value.terrain_sha256 != payload["terrain_resource_sha256"]
                or value.obstacle_sha256 != payload["obstacle_resource_sha256"]
                or not math.isfinite(value.ground_down)):
            raise ICDError("MODEL", "actual resource fact differs from RunConfigure")
        return value

    def read_context(self, identity, request_json, *, now_ns):
        if type(identity) is not dict or type(request_json) is not bytes or type(now_ns) is not int:
            raise ICDError("SCHEMA", "strict actual RunConfigure context inputs required")
        request = loads(request_json)
        model_id = identity.get("model_id")
        if model_id not in self._bridges or request.get("payload", {}).get("model_id") != model_id:
            raise ICDError("MODEL", "configuration identity and C-core endpoint differ")
        fields = self._status(model_id)
        self._require_configuration_abi(fields)
        _lifecycle, _sequence, status_revision, _source = self._boundary_values(fields)
        payload = request["payload"]
        existing = fields.get("lifecycle") == "CONFIGURED"
        if self._require_prepared_existing and not existing:
            raise ICDError("STATE", "second-circle RunConfigure requires a first-circle CONFIGURED target")
        if existing:
            configuration, revision = self._configuration(model_id)
            if (canonicalize(configuration) != canonicalize(payload)
                    or revision != status_revision):
                raise ICDError("STATE", "C-core configuration or revision differs from its status boundary")
        resources = self._resources(payload)
        sampled = self._clock()
        if type(sampled) is not int or sampled < now_ns:
            raise ICDError("CLOCK_UNSYNC", "C-core context clock regressed")
        return ModelConfigurationContext(
            canonicalize(identity), request_json, self._view(model_id, fields, request),
            status_revision, resources.ground_down,
            sampled, sampled + 240_000_000, existing)

    def apply_configuration(self, request_json, context, *, now_ns):
        if type(context) is not ModelConfigurationContext or type(request_json) is not bytes or type(now_ns) is not int:
            raise ICDError("SCHEMA", "strict actual configuration write inputs required")
        request = loads(request_json)
        identity = loads(context.identity_json)
        model_id = identity.get("model_id")
        if model_id not in self._bridges or canonicalize(loads(context.request_json)) != canonicalize(request):
            raise ICDError("STATE", "configuration write does not name its actual context")
        resources = self._resources(request["payload"])
        if abs(resources.ground_down - context.ground_down) > 1e-9:
            raise ICDError("RESOURCE", "configured resource ground sample changed before model write")

        # Recheck the complete C-core boundary immediately before configuration;
        # C repeats this tuple under its command lock before the model write.
        before = self._status(model_id)
        self._require_configuration_abi(before)
        lifecycle, sequence, revision, source = self._boundary_values(before)
        expected = (context.view.state, context.view.model_step, context.model_revision,
                    context.view.control_source)
        if (lifecycle, sequence, revision, source) != expected:
            raise ICDError("STATE", "C-core lifecycle, step, revision or control source changed before configuration write")
        if context.idempotent_existing:
            configuration, stored_revision = self._configuration(model_id)
            if (canonicalize(configuration) != canonicalize(request["payload"])
                    or stored_revision != context.model_revision
                    or lifecycle != "CONFIGURED"):
                raise ICDError("STATE", "C-core configured boundary changed before idempotent readback")
            fields = {"configuration": configuration, "model_revision": stored_revision}
        else:
            command = {
                "request_id": "run-configure-apply", "cmd": "configure",
                "params": {
                    "configuration": request["payload"],
                    "resource_context": {
                        "terrain_sha256": resources.terrain_sha256,
                        "obstacle_sha256": resources.obstacle_sha256,
                        "ground_down": resources.ground_down,
                    },
                    "expected_boundary": {
                        "lifecycle": context.view.state,
                        "model_step": context.view.model_step,
                        "model_revision": context.model_revision,
                        "control_source": context.view.control_source.lower(),
                    },
                }}
            # Log immutable structure/digest only; never log full initial state
            # or inputs when diagnosing a C-core ABI mismatch.
            print(json.dumps({
                "event": "ccore_run_configure_dispatch",
                "model_id": model_id,
                "configuration_sha256": hashlib.sha256(
                    canonicalize(request["payload"])).hexdigest(),
                "params_keys": sorted(command["params"]),
                "configuration_keys": sorted(request["payload"]),
                "step_us": request["payload"].get("step_us"),
                "step_us_type": type(request["payload"].get("step_us")).__name__,
                "initial_inputs_model_id": request["payload"].get("initial_inputs", {}).get("model_id"),
                "initial_state_is_object": type(request["payload"].get("initial_state")) is dict,
                "resource_context": command["params"]["resource_context"],
                "expected_boundary": command["params"]["expected_boundary"],
            }, sort_keys=True), flush=True)
            reply = self._bridges[model_id]._exchange(command)
            print(json.dumps({
                "event": "ccore_run_configure_receipt",
                "model_id": model_id,
                "accepted": reply.get("accepted") if type(reply) is dict else None,
                "reason": reply.get("reason") if type(reply) is dict else None,
                "effective_sequence": reply.get("effective_sequence") if type(reply) is dict else None,
                "lifecycle": reply.get("lifecycle") if type(reply) is dict else None,
            }, sort_keys=True), flush=True)
            if type(reply) is not dict:
                raise ICDError("BUSINESS_FAILED", "C-core returned malformed atomic RunConfigure receipt: response must be an object")
            accepted = reply.get("accepted")
            if accepted is False:
                reason = reply.get("reason")
                if "reason" not in reply:
                    detail = "C-core rejected atomic RunConfigure without a reason field"
                elif type(reason) is not str:
                    detail = "C-core rejected atomic RunConfigure with a non-string reason field"
                elif not reason.strip():
                    detail = "C-core rejected atomic RunConfigure with an empty reason field"
                else:
                    detail = "C-core refused atomic RunConfigure: {}".format(reason.strip())
                raise ICDError("BUSINESS_FAILED", detail)
            if accepted is not True:
                raise ICDError("BUSINESS_FAILED", "C-core returned malformed atomic RunConfigure receipt: accepted must be a boolean")
            fields = reply.get("fields")
            if type(fields) is not dict:
                raise ICDError("BUSINESS_FAILED", "C-core accepted atomic RunConfigure but returned malformed receipt: fields must be an object")
            if (type(fields.get("configuration")) is not dict
                    or canonicalize(fields["configuration"]) != canonicalize(request["payload"])
                    or type(fields.get("model_revision")) is not int):
                raise ICDError("MODEL", "C-core configuration receipt is incomplete")
        final_resources = self._resources(request["payload"])
        if final_resources != resources:
            raise ICDError("RESOURCE", "configured resource changed during model write")
        after, state, initial_inputs = self._initial_readback(model_id, request)
        _lifecycle, _sequence, readback_revision, _source = self._boundary_values(after)
        if readback_revision != fields["model_revision"]:
            raise ICDError("STATE", "C-core revision changed between configuration receipt and readback")
        sampled = self._clock()
        if type(sampled) is not int or sampled < now_ns:
            raise ICDError("CLOCK_UNSYNC", "C-core configuration clock regressed")
        return ModelConfigurationReceipt(
            canonicalize(identity), request_json, canonicalize(fields["configuration"]),
            canonicalize(state), canonicalize(initial_inputs),
            self._view(model_id, after, request), fields["model_revision"], sampled,
            sampled + 240_000_000)


class CcoreLifecycleBackend(ModelLifecycleBackend):
    """Actual C-core lifecycle adapter, deliberately limited to proven actions.

    The generated C loop stages a transition at the frozen model step and
    returns its final receipt only from the 1ms model thread.  STEP is not
    installed because its required per-step state history has no C readback
    owner yet; it fails before any write rather than approximating solver time.
    """

    def __init__(self, contract, endpoints, *, timeout_s=1.0, poll_s=0.001,
                 socket_factory=socket.socket, clock=time.monotonic_ns):
        if (type(endpoints) is not dict or not endpoints or not callable(clock)
                or type(timeout_s) not in (int, float) or not 0 < timeout_s <= 1
                or type(poll_s) not in (int, float) or not 0 < poll_s <= .1):
            raise ICDError("SCHEMA", "bounded C-core lifecycle endpoints and clock required")
        model_ids = tuple(endpoints)
        if any(type(model_id) is not str or type(endpoint) is not tuple or len(endpoint) != 2
               or type(endpoint[0]) is not str or type(endpoint[1]) is not int
               or not 1 <= endpoint[1] <= 65535 for model_id, endpoint in endpoints.items()):
            raise ICDError("SCHEMA", "each C-core lifecycle endpoint must be a host/port pair")
        super().__init__(contract, model_ids)
        self._clock = clock
        self._bridges = {
            model_id: QuadrotorEnvironmentBridge(endpoint, timeout_s=timeout_s, poll_s=poll_s,
                                                   socket_factory=socket_factory,
                                                   clock=lambda: self._clock() / 1_000_000_000)
            for model_id, endpoint in endpoints.items()
        }

    def _status(self, model_id):
        reply = self._bridges[model_id]._exchange({
            "request_id": "lifecycle-status", "cmd": "get_hil_status"})
        fields = reply.get("fields")
        if not reply.get("accepted") or type(fields) is not dict:
            raise ICDError("MODEL", "C-core did not return lifecycle status")
        return fields

    def _configuration(self, model_id):
        reply = self._bridges[model_id]._exchange({
            "request_id": "lifecycle-configuration", "cmd": "get_configuration_snapshot"})
        fields = reply.get("fields")
        if (not reply.get("accepted") or type(fields) is not dict
                or type(fields.get("configuration")) is not dict
                or type(fields.get("model_revision")) is not int):
            raise ICDError("STATE", "C-core has no complete applied configuration")
        return fields["configuration"], fields["model_revision"]

    def _view(self, model_id, fields, configuration):
        lifecycle, source, sequence = fields.get("lifecycle"), fields.get("control_source"), fields.get("sequence")
        if (lifecycle not in ("CONFIGURED", "RUNNING", "PAUSED", "STOPPED", "FAILED")
                or source not in CcoreConfigurationBackend._SOURCES
                or type(sequence) is not int or sequence < 0):
            raise ICDError("MODEL", "C-core lifecycle status is incomplete")
        return ModelView(model_id, lifecycle, sequence, configuration["max_duration_steps"],
                         CcoreConfigurationBackend._SOURCES[source],
                         configuration["controller"] == "PHYSICAL_UUT", True)

    def _inputs(self, model_id, configuration):
        reply = self._bridges[model_id]._exchange({
            "request_id": "lifecycle-inputs", "cmd": "get_icd_snapshot",
            "params": {"snapshot": "active"}})
        fields = reply.get("fields")
        if (not reply.get("accepted") or type(fields) is not dict
                or type(fields.get("inputs")) is not dict
                or type(fields.get("parameters")) is not dict):
            raise ICDError("MODEL", "C-core did not return direct active input readback")
        inputs = copy.deepcopy(configuration["initial_inputs"])
        inputs.update(fields["inputs"])
        inputs["parameters"] = fields["parameters"]
        return inputs

    @staticmethod
    def _state(fields):
        source = fields.get("model_state")
        if type(source) is not dict or source.get("model_step") != fields.get("sequence"):
            raise ICDError("MODEL", "C-core lacks coherent direct State132 projection")
        return copy.deepcopy(source)

    @staticmethod
    def _actuators(inputs):
        return {"motor_command": copy.deepcopy(inputs["flight_control"]["motor_command"])}

    def _sample(self, model_id, identity, request_json, *, now_ns):
        configuration, revision = self._configuration(model_id)
        fields = self._status(model_id)
        inputs = self._inputs(model_id, configuration)
        sampled = self._clock()
        if type(sampled) is not int or sampled < now_ns:
            raise ICDError("CLOCK_UNSYNC", "C-core lifecycle clock regressed")
        return (configuration, revision, fields, inputs, sampled)

    def read_context(self, identity, request_json, *, now_ns):
        from .lifecycle_service import ModelLifecycleContext
        if type(identity) is not dict or type(request_json) is not bytes or type(now_ns) is not int:
            raise ICDError("SCHEMA", "strict C-core lifecycle context inputs required")
        request = loads(request_json)
        model_id = identity.get("model_id")
        if model_id not in self._bridges:
            raise ICDError("MODEL", "lifecycle identity has no C-core endpoint")
        configuration, _revision, fields, inputs, sampled = self._sample(
            model_id, identity, request_json, now_ns=now_ns)
        return ModelLifecycleContext(
            canonicalize(identity), request_json, canonicalize(configuration),
            canonicalize(self._state(fields)), canonicalize(inputs),
            self._view(model_id, fields, configuration), sampled, sampled + 240_000_000)

    def apply_lifecycle(self, request_json, context, decision, *, now_ns):
        from .lifecycle_service import ModelLifecycleReceipt
        if type(request_json) is not bytes or type(now_ns) is not int:
            raise ICDError("SCHEMA", "strict C-core lifecycle write inputs required")
        request, identity = loads(request_json), loads(context.identity_json)
        action, model_id = request["payload"]["action"], identity.get("model_id")
        if (model_id not in self._bridges or canonicalize(loads(context.request_json)) != canonicalize(request)
                or action == "STEP"):
            raise ICDError("UNSUPPORTED" if action == "STEP" else "STATE",
                           "C-core lifecycle context/action is not supported")
        before = self._status(model_id)
        configuration, _revision = self._configuration(model_id)
        before_view = self._view(model_id, before, configuration)
        if (canonicalize(configuration) != canonicalize(loads(context.configuration_json))
                or before_view.state != context.view.state
                or before_view.control_source != context.view.control_source
                or (before_view.state != "RUNNING" and before_view.model_step != context.view.model_step)
                or (before_view.state == "RUNNING" and before_view.model_step >= decision.target_step)):
            raise ICDError("STATE", "C-core lifecycle context changed before write")
        reply = self._bridges[model_id]._exchange({
            "request_id": "lifecycle-" + action.lower(), "cmd": "stage_lifecycle",
            "params": {"action": action, "target_step": decision.target_step}})
        if (not reply.get("accepted") or reply.get("lifecycle") != decision.next_state
                or reply.get("effective_sequence") != decision.target_step):
            raise ICDError("BUSINESS_FAILED", "C-core did not apply lifecycle at requested model boundary")
        # START/RESUME transition at the frozen boundary before the next solver
        # step.  Other actions leave the runtime stopped/paused, so obtain a
        # direct post-effect sample.  In both cases receipts describe actual C
        # state at the C command's returned effective sequence.
        if action in ("START", "RESUME"):
            state, inputs, view = loads(context.state_json), loads(context.inputs_json), context.view
            state["model_step"] = decision.target_step
            view = ModelView(view.model_id, decision.next_state, decision.target_step,
                             view.max_duration_steps, view.control_source,
                             view.physical_closed_loop, view.configured_once)
            revision = self._configuration(model_id)[1]
        else:
            configuration, revision, fields, inputs, sampled = self._sample(
                model_id, identity, request_json, now_ns=now_ns)
            state, view = self._state(fields), self._view(model_id, fields, configuration)
            expected_step = 0 if decision.restore_initial else decision.target_step
            if view.state != decision.next_state or view.model_step != expected_step:
                raise ICDError("MODEL", "C-core post-lifecycle readback differs from target boundary")
        sampled = self._clock()
        if type(sampled) is not int or sampled < now_ns:
            raise ICDError("CLOCK_UNSYNC", "C-core lifecycle completion clock regressed")
        return ModelLifecycleReceipt(
            canonicalize(identity), request_json, canonicalize(configuration), canonicalize(state),
            canonicalize(inputs), view, canonicalize(self._actuators(inputs)), 0, 0, (), revision,
            sampled, sampled + 240_000_000)


class CcoreStatusBackend(ModelStatusBackend):
    """Read ID2 status only from the C target's current status command."""

    _SOURCES = CcoreConfigurationBackend._SOURCES

    def __init__(self, contract, endpoints, *, timeout_s=0.05, poll_s=0.001,
                 socket_factory=socket.socket, clock=time.monotonic_ns):
        if (type(endpoints) is not dict or not endpoints or not callable(clock)
                or type(timeout_s) not in (int, float) or not 0 < timeout_s <= 1
                or type(poll_s) not in (int, float) or not 0 < poll_s <= .1):
            raise ICDError("SCHEMA", "bounded C-core status endpoints and clock required")
        if any(type(model_id) is not str or type(endpoint) is not tuple or len(endpoint) != 2
               or type(endpoint[0]) is not str or type(endpoint[1]) is not int
               or not 1 <= endpoint[1] <= 65535 for model_id, endpoint in endpoints.items()):
            raise ICDError("SCHEMA", "each C-core status endpoint must be a host/port pair")
        super().__init__(contract, tuple(endpoints))
        self._clock = clock
        self._bridges = {
            model_id: QuadrotorEnvironmentBridge(endpoint, timeout_s=timeout_s, poll_s=poll_s,
                                                   socket_factory=socket_factory,
                                                   clock=lambda: self._clock() / 1_000_000_000)
            for model_id, endpoint in endpoints.items()
        }

    def read_status(self, identity, *, now_ns):
        if type(identity) is not dict or type(now_ns) is not int:
            raise ICDError("SCHEMA", "strict C-core status identity/time required")
        model_id = identity.get("model_id")
        if model_id not in self._bridges:
            raise ICDError("MODEL", "status identity has no C-core endpoint")
        reply = self._bridges[model_id]._exchange({
            "request_id": "standard-status", "cmd": "get_hil_status"})
        fields = reply.get("fields")
        lifecycle, source, sequence = (None if type(fields) is not dict else fields.get("lifecycle"),
                                       None if type(fields) is not dict else fields.get("control_source"),
                                       None if type(fields) is not dict else fields.get("sequence"))
        if (not reply.get("accepted") or lifecycle not in ("CONFIGURED", "RUNNING", "PAUSED", "STOPPED", "FAILED")
                or source not in self._SOURCES or type(sequence) is not int or sequence < 0):
            raise ICDError("MODEL", "C-core status lacks a strict actual model view")
        sampled = self._clock()
        if type(sampled) is not int or sampled < now_ns:
            raise ICDError("CLOCK_UNSYNC", "C-core status clock regressed")
        payload = {
            "state": lifecycle, "phase": "FLYING" if lifecycle in ("RUNNING", "PAUSED") else "LANDED",
            "control_source": self._SOURCES[source], "safety_active": source == "none",
            "model_step": sequence, "last_applied_sequence": sequence,
            "receive_queue_depth": 0, "missed_deadline_count": 0,
            "received_count": 0, "rejected_count": 0, "applied_count": 0, "consumed_count": 0,
        }
        return ModelStatusSample(canonicalize(identity), canonicalize(payload), sampled,
                                 sampled + 240_000_000)


@dataclass(frozen=True)
class EnvironmentApplication:
    applied_step: int
    model_revision: int
    readback_json: bytes


@dataclass(frozen=True)
class EnvironmentConsumerRecord:
    request_json: bytes
    readback_json: bytes
    received_ns: int
    completed_ns: int
    applied_step: int
    model_revision: int

    @property
    def stored_bytes(self):
        return 256 + len(self.request_json) + len(self.readback_json)


class QuadrotorEnvironmentBridge:
    """Small UDP adapter for the real C runtime's target-step bridge.

    The adapter does not accept a UDP "staged" reply as application evidence;
    it polls the C runtime result and validates target step plus all six values.
    """

    def __init__(self, endpoint=("127.0.0.1", 9997), *, timeout_s=0.05,
                 poll_s=0.001, socket_factory=socket.socket, clock=time.monotonic):
        if (type(endpoint) is not tuple or len(endpoint) != 2 or type(endpoint[0]) is not str
                or type(endpoint[1]) is not int or not 1 <= endpoint[1] <= 65535
                or type(timeout_s) not in (int, float) or not 0 < timeout_s <= 1
                or type(poll_s) not in (int, float) or not 0 < poll_s <= .1 or not callable(clock)):
            raise ICDError("SCHEMA", "bounded UDP bridge endpoint and clock required")
        self.endpoint, self.timeout_s, self.poll_s = endpoint, float(timeout_s), float(poll_s)
        self._socket_factory, self._clock = socket_factory, clock

    def _exchange(self, command):
        encoded = json.dumps(command, ensure_ascii=True, allow_nan=False,
                             separators=(",", ":")).encode("ascii")
        try:
            peer = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                peer.settimeout(self.timeout_s)
                peer.sendto(encoded, self.endpoint)
                raw, sender = peer.recvfrom(65536)
            finally:
                peer.close()
        except (OSError, socket.timeout) as error:
            raise ICDError("TARGET_MISSING", "real C model bridge is unavailable") from error
        if sender[0] != self.endpoint[0]:
            raise ICDError("AUTHORIZATION", "model bridge reply came from another peer")
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ICDError("MODEL", "real C model bridge returned invalid JSON") from error
        if type(reply) is not dict or type(reply.get("accepted")) is not bool:
            raise ICDError("MODEL", "real C model bridge returned an invalid receipt")
        return reply

    def current_step(self):
        """Read the runtime's actual sequence without staging any input."""
        reply = self._exchange({"request_id": "icd10-step-probe",
                                "cmd": "get_icd_environment_result",
                                "params": {"stage_request_id": "__step_probe__"}})
        step = reply.get("effective_sequence")
        if reply.get("accepted") or type(step) is not int or step < 0:
            raise ICDError("MODEL", "real C model bridge did not expose its current sequence")
        return step

    def apply_environment(self, request, bindings, *, now_ns):
        if type(bindings) is not ModelBindings or bindings.model_id != "quadrotor_hil":
            raise ICDError("MODEL", "quadrotor Environment bindings required")
        if request["message_id"] != 10:
            raise ICDError("TARGET_MISSING", "only Environment ID10 is installed")
        environment = request["payload"]
        target_step = request["header"]["target_step"]
        valid_for_ms = request["header"]["valid_for_ms"]
        if type(target_step) is not int or target_step < 1 or type(now_ns) is not int:
            raise ICDError("SCHEMA", "actual target step and receiver time required")
        # Validate the frozen binding before any real-process message is sent.
        mapped = bindings.map_message(request)
        if {value.path for value in mapped} != {"environment." + name for name in environment}:
            raise ICDError("MODEL", "Environment binding order or field set differs")
        stage_id = "icd10-%d-%d-%d" % (request["header"]["session_id"],
                                        request["header"]["sequence"],
                                        request["header"]["transaction_id"])
        deadline_ns = now_ns + valid_for_ms * 1000000
        staged = self._exchange({"request_id": stage_id, "cmd": "stage_icd_environment",
                                 "params": {"target_step": target_step, "deadline_ns": deadline_ns,
                                            "environment": environment}})
        if (not staged["accepted"] or staged.get("reason") != "staged"
                or staged.get("effective_sequence") != target_step):
            raise ICDError("BUSINESS_FAILED", "real model did not stage Environment at its requested step")
        while self._clock() * 1000000000 < deadline_ns:
            result = self._exchange({"request_id": stage_id + "-result",
                                     "cmd": "get_icd_environment_result",
                                     "params": {"stage_request_id": stage_id}})
            fields = result.get("fields")
            if type(fields) is not dict or fields.get("stage_request_id") != stage_id:
                raise ICDError("MODEL", "real model result does not identify the staged Environment")
            state = fields.get("state")
            if state == "STAGED":
                time.sleep(self.poll_s)
                continue
            if (state != "APPLIED" or not result["accepted"]
                    or fields.get("target_step") != target_step
                    or fields.get("applied_step") != target_step
                    or type(fields.get("model_revision")) is not int
                    or fields["model_revision"] < 1
                    or canonicalize(fields.get("readback")) != canonicalize(environment)):
                raise ICDError("BUSINESS_FAILED", "real model did not apply the exact Environment snapshot")
            return EnvironmentApplication(target_step, fields["model_revision"],
                                          canonicalize(fields["readback"]))
        raise ICDError("EXPIRED", "real model did not reach the requested Environment boundary in time")

    def apply_flight_control(self, request, bindings, *, now_ns):
        if type(bindings) is not ModelBindings or bindings.model_id != "quadrotor_hil":
            raise ICDError("MODEL", "quadrotor flight-control bindings required")
        if request["message_id"] != 7:
            raise ICDError("TARGET_MISSING", "only FlightQuad ID7 is installed")
        flight_control = request["payload"]
        target_step, valid_for_ms = request["header"]["target_step"], request["header"]["valid_for_ms"]
        if type(target_step) is not int or target_step < 1 or type(now_ns) is not int:
            raise ICDError("SCHEMA", "actual target step and receiver time required")
        mapped = bindings.map_message(request)
        if {value.path for value in mapped} != {"flight_control.motor_command"}:
            raise ICDError("MODEL", "FlightQuad binding differs from the frozen motor command")
        stage_id = "icd7-%d-%d-%d" % (request["header"]["session_id"],
                                      request["header"]["sequence"], request["header"]["transaction_id"])
        deadline_ns = now_ns + valid_for_ms * 1000000
        staged = self._exchange({"request_id": stage_id, "cmd": "stage_icd_flight_control",
                                 "params": {"target_step": target_step, "deadline_ns": deadline_ns,
                                            "flight_control": flight_control}})
        if (not staged["accepted"] or staged.get("reason") != "staged"
                or staged.get("effective_sequence") != target_step):
            raise ICDError("BUSINESS_FAILED", "real model did not stage FlightQuad at its requested step")
        while self._clock() * 1000000000 < deadline_ns:
            result = self._exchange({"request_id": stage_id + "-result",
                                     "cmd": "get_icd_flight_control_result",
                                     "params": {"stage_request_id": stage_id}})
            fields = result.get("fields")
            if type(fields) is not dict or fields.get("stage_request_id") != stage_id:
                raise ICDError("MODEL", "real model result does not identify the staged FlightQuad")
            if fields.get("state") == "STAGED":
                time.sleep(self.poll_s)
                continue
            if (fields.get("state") != "APPLIED" or not result["accepted"]
                    or fields.get("target_step") != target_step
                    or fields.get("applied_step") != target_step
                    or type(fields.get("model_revision")) is not int
                    or fields["model_revision"] < 1
                    or canonicalize(fields.get("readback")) != canonicalize(flight_control["motor_command"])):
                raise ICDError("BUSINESS_FAILED", "real model did not apply the exact FlightQuad motor snapshot")
            return EnvironmentApplication(target_step, fields["model_revision"],
                                          canonicalize(fields["readback"]))
        raise ICDError("EXPIRED", "real model did not reach the requested FlightQuad boundary in time")

    def apply_fault(self, request, bindings, *, now_ns):
        """Stage the complete ID11 fault snapshot and require target-step readback."""
        if type(bindings) is not ModelBindings or bindings.model_id != "quadrotor_hil":
            raise ICDError("MODEL", "quadrotor fault bindings required")
        if request["message_id"] != 11:
            raise ICDError("TARGET_MISSING", "only FaultQuad ID11 is installed")
        fault = request["payload"]
        target_step, valid_for_ms = request["header"]["target_step"], request["header"]["valid_for_ms"]
        if type(target_step) is not int or target_step < 1 or type(now_ns) is not int:
            raise ICDError("SCHEMA", "actual target step and receiver time required")
        mapped = bindings.map_message(request)
        if {value.path for value in mapped} != {"fault." + name for name in fault}:
            raise ICDError("MODEL", "FaultQuad binding differs from the frozen fault snapshot")
        stage_id = "icd11-%d-%d-%d" % (request["header"]["session_id"],
                                        request["header"]["sequence"], request["header"]["transaction_id"])
        deadline_ns = now_ns + valid_for_ms * 1000000
        staged = self._exchange({"request_id": stage_id, "cmd": "stage_icd_fault",
                                 "params": {"target_step": target_step, "deadline_ns": deadline_ns,
                                            "fault": fault}})
        if (not staged["accepted"] or staged.get("reason") != "staged"
                or staged.get("effective_sequence") != target_step):
            raise ICDError("BUSINESS_FAILED", "real model did not stage FaultQuad at its requested step")
        while self._clock() * 1000000000 < deadline_ns:
            result = self._exchange({"request_id": stage_id + "-result", "cmd": "get_icd_fault_result",
                                     "params": {"stage_request_id": stage_id}})
            fields = result.get("fields")
            if type(fields) is not dict or fields.get("stage_request_id") != stage_id:
                raise ICDError("MODEL", "real model result does not identify the staged FaultQuad")
            if fields.get("state") == "STAGED":
                time.sleep(self.poll_s)
                continue
            if (fields.get("state") != "APPLIED" or not result["accepted"]
                    or fields.get("target_step") != target_step
                    or fields.get("applied_step") != target_step
                    or type(fields.get("model_revision")) is not int
                    or fields["model_revision"] < 1
                    or canonicalize(fields.get("readback")) != canonicalize(fault)):
                raise ICDError("BUSINESS_FAILED", "real model did not apply the exact FaultQuad snapshot")
            return EnvironmentApplication(target_step, fields["model_revision"],
                                          canonicalize(fields["readback"]))
        raise ICDError("EXPIRED", "real model did not reach the requested FaultQuad boundary in time")


class EnvironmentModelConsumerService:
    """Receiver-owned ID10 consumer that is permitted to create APPLIED."""

    def __init__(self, contract, registry, bindings, backend, *, max_records=MAX_RECORDS,
                 max_bytes=MAX_BYTES, clock=time.monotonic_ns):
        if (type(registry) is not SessionRegistry or registry.contract is not contract
                or type(bindings) is not ModelBindings or bindings.contract is not contract
                or bindings.model_id != "quadrotor_hil" or not isinstance(backend, QuadrotorEnvironmentBridge)
                or type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS
                or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES or not callable(clock)):
            raise ICDError("STATE", "same-contract quadrotor Environment consumer required")
        self.contract, self.registry, self.bindings, self.backend = contract, registry, bindings, backend
        self._contract, self._registry, self._bindings, self._backend = contract, registry, bindings, backend
        self._max_records, self._max_bytes, self._clock = max_records, max_bytes, clock
        self._receiver, self._closed, self._records, self._bytes = None, False, [], 0
        self._completion = None
        self._last_observed_ns = None

    @property
    def records(self):
        return tuple(self._records)

    @property
    def last_observed_ns(self):
        return self._last_observed_ns

    def supports(self, message_id, model_id):
        self._check()
        return message_id == 10 and model_id == "quadrotor_hil"

    def _check(self, *, closed_ok=False):
        if (self.contract is not self._contract or self.registry is not self._registry
                or self.bindings is not self._bindings or self.backend is not self._backend
                or self._receiver is not None and (self._receiver.contract is not self._contract
                    or self._receiver.registry is not self._registry
                    or self._receiver.model_consumer_service is not self)):
            raise ICDError("STATE", "original Environment consumer owners cannot be replaced")
        if self._closed and not closed_ok:
            raise ICDError("STATE", "Environment consumer is closed")

    def _bind(self, receiver):
        self._check()
        if self._receiver is not None and self._receiver is not receiver:
            raise ICDError("STATE", "one receiver owns the Environment consumer")
        self._receiver = receiver

    def _owns_completed_reply(self, request, responses, now_ns):
        return self._completion == (canonicalize(request), tuple(canonicalize(reply) for reply in responses), now_ns)

    def respond(self, request, received, *, now_ns):
        self._check()
        if self._receiver is None or not self.supports(request["message_id"],
                                                        self.registry.identity(request["header"]["session_id"])["model_id"]):
            raise ICDError("TARGET_MISSING", "Environment consumer is not installed for this model")
        if self._completion is not None:
            raise ICDError("STATE", "one Environment completion at a time")
        if len(self._records) >= self._max_records:
            raise ICDError("BUFFER_FULL", "retain Environment evidence before another application")
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual Environment consumer clock differs from receiver")
        app = self.backend.apply_environment(request, self.bindings, now_ns=completed)
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual Environment completion clock differs from receiver")
        terminal = self._receiver._ack(10, request["header"], stage="APPLIED", error="OK",
                                       applied_step=app.applied_step, model_revision=app.model_revision,
                                       probe_id=1010)
        replies = (received, terminal)
        record = EnvironmentConsumerRecord(canonicalize(request), app.readback_json, now_ns, completed,
                                           app.applied_step, app.model_revision)
        if self._bytes + record.stored_bytes > self._max_bytes:
            raise ICDError("BUFFER_FULL", "Environment evidence storage is full")
        self._completion = (canonicalize(request), tuple(canonicalize(reply) for reply in replies), completed)
        try:
            self.registry._record_environment_response(request, replies, self, now_ns=completed)
        finally:
            self._completion = None
        self._records.append(record)
        self._bytes += record.stored_bytes
        self._last_observed_ns = completed
        return replies

    def close(self):
        self._check(closed_ok=True)
        self._closed = True


class FlightModelConsumerService(EnvironmentModelConsumerService):
    """ID7 owner.  Exactly one live Controller SID may drive the C motor lane."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._flight_owner = None

    def supports(self, message_id, model_id):
        self._check()
        return message_id == 7 and model_id == "quadrotor_hil"

    def respond(self, request, received, *, now_ns):
        self._check()
        sid = request["header"]["session_id"]
        if self._receiver is None or not self.supports(request["message_id"],
                                                        self.registry.identity(sid)["model_id"]):
            raise ICDError("TARGET_MISSING", "FlightQuad consumer is not installed for this model")
        if "CONTROLLER" not in self.registry.roles(sid):
            raise ICDError("CONTROL_OWNER", "FlightQuad requires the admitted Controller role")
        if self._flight_owner not in self.registry.session_ids:
            self._flight_owner = None
        if self._flight_owner is not None and self._flight_owner != sid:
            raise ICDError("CONTROL_OWNER", "another live Controller owns the FlightQuad lane")
        if self._completion is not None:
            raise ICDError("STATE", "one FlightQuad completion at a time")
        if len(self._records) >= self._max_records:
            raise ICDError("BUFFER_FULL", "retain FlightQuad evidence before another application")
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual FlightQuad consumer clock differs from receiver")
        app = self.backend.apply_flight_control(request, self.bindings, now_ns=completed)
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual FlightQuad completion clock differs from receiver")
        terminal = self._receiver._ack(7, request["header"], stage="APPLIED", error="OK",
                                       applied_step=app.applied_step, model_revision=app.model_revision,
                                       probe_id=1007)
        replies = (received, terminal)
        record = EnvironmentConsumerRecord(canonicalize(request), app.readback_json, now_ns, completed,
                                           app.applied_step, app.model_revision)
        if self._bytes + record.stored_bytes > self._max_bytes:
            raise ICDError("BUFFER_FULL", "FlightQuad evidence storage is full")
        self._completion = (canonicalize(request), tuple(canonicalize(reply) for reply in replies), completed)
        try:
            self.registry._record_flight_response(request, replies, self, now_ns=completed)
        finally:
            self._completion = None
        self._flight_owner = sid
        self._records.append(record)
        self._bytes += record.stored_bytes
        self._last_observed_ns = completed
        return replies


class FaultModelConsumerService(EnvironmentModelConsumerService):
    """ID11 owner for the full, atomic quadrotor fault snapshot."""

    def supports(self, message_id, model_id):
        self._check()
        return message_id == 11 and model_id == "quadrotor_hil"

    def respond(self, request, received, *, now_ns):
        self._check()
        if self._receiver is None or not self.supports(
                request["message_id"], self.registry.identity(request["header"]["session_id"])["model_id"]):
            raise ICDError("TARGET_MISSING", "FaultQuad consumer is not installed for this model")
        if self._completion is not None:
            raise ICDError("STATE", "one FaultQuad completion at a time")
        if len(self._records) >= self._max_records:
            raise ICDError("BUFFER_FULL", "retain FaultQuad evidence before another application")
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual FaultQuad consumer clock differs from receiver")
        app = self.backend.apply_fault(request, self.bindings, now_ns=completed)
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual FaultQuad completion clock differs from receiver")
        terminal = self._receiver._ack(11, request["header"], stage="APPLIED", error="OK",
                                       applied_step=app.applied_step, model_revision=app.model_revision,
                                       probe_id=1011)
        replies = (received, terminal)
        record = EnvironmentConsumerRecord(canonicalize(request), app.readback_json, now_ns, completed,
                                           app.applied_step, app.model_revision)
        if self._bytes + record.stored_bytes > self._max_bytes:
            raise ICDError("BUFFER_FULL", "FaultQuad evidence storage is full")
        self._completion = (canonicalize(request), tuple(canonicalize(reply) for reply in replies), completed)
        try:
            self.registry._record_fault_response(request, replies, self, now_ns=completed)
        finally:
            self._completion = None
        self._records.append(record)
        self._bytes += record.stored_bytes
        self._last_observed_ns = completed
        return replies


_MODEL_BINDING_MESSAGES = {
    "quadrotor_hil": {7: "flight_control", 10: "environment", 11: "fault", 17: "parameters"},
    "multirotor_6_hil": {8: "flight_control", 10: "environment", 12: "fault", 18: "parameters"},
    "fixed_wing_hil": {9: "flight_control", 10: "environment", 13: "fault", 19: "parameters"},
}


class ContractModelBridge(QuadrotorEnvironmentBridge):
    """Generated-contract bridge for every root input and parameter group."""

    def current_step(self):
        reply = self._exchange({"request_id": "icd-group-step-probe",
                                "cmd": "get_icd_group_result",
                                "params": {"group": "environment",
                                           "stage_request_id": "__step_probe__"}})
        step = reply.get("effective_sequence")
        if reply.get("accepted") or type(step) is not int or step < 0:
            raise ICDError("MODEL", "real C model bridge did not expose its current sequence")
        return step

    def apply_group(self, request, bindings, *, now_ns):
        if type(bindings) is not ModelBindings:
            raise ICDError("MODEL", "actual generated model bindings required")
        message_id = request["message_id"]
        group = _MODEL_BINDING_MESSAGES.get(bindings.model_id, {}).get(message_id)
        if group is None:
            raise ICDError("TARGET_MISSING", "message is not a root binding for this model")
        payload = request["payload"]
        target_step = request["header"]["target_step"]
        valid_for_ms = request["header"]["valid_for_ms"]
        if type(target_step) is not int or target_step < 1 or type(now_ns) is not int:
            raise ICDError("SCHEMA", "actual target step and receiver time required")
        mapped = bindings.map_message(request)
        if {item.path for item in mapped} != {group + "." + name for name in payload}:
            raise ICDError("MODEL", "frozen binding differs from the complete model group")
        stage_id = "icd%d-%d-%d-%d" % (
            message_id, request["header"]["session_id"], request["header"]["sequence"],
            request["header"]["transaction_id"])
        deadline_ns = now_ns + valid_for_ms * 1000000
        staged = self._exchange({"request_id": stage_id, "cmd": "stage_icd_group",
                                 "params": {"target_step": target_step,
                                            "deadline_ns": deadline_ns,
                                            "group": group, "values": payload}})
        if (not staged["accepted"] or staged.get("reason") != "staged"
                or staged.get("effective_sequence") != target_step):
            raise ICDError("BUSINESS_FAILED", "real model did not stage the complete binding group")
        while self._clock() * 1000000000 < deadline_ns:
            result = self._exchange({"request_id": stage_id + "-result",
                                     "cmd": "get_icd_group_result",
                                     "params": {"group": group,
                                                "stage_request_id": stage_id}})
            fields = result.get("fields")
            if (type(fields) is not dict or fields.get("stage_request_id") != stage_id
                    or fields.get("group") != group):
                raise ICDError("MODEL", "real model result does not identify the staged binding group")
            if fields.get("state") == "STAGED":
                time.sleep(self.poll_s)
                continue
            if (fields.get("state") != "APPLIED" or not result["accepted"]
                    or fields.get("target_step") != target_step
                    or fields.get("applied_step") != target_step
                    or type(fields.get("model_revision")) is not int
                    or fields["model_revision"] < 1
                    or canonicalize(fields.get("readback")) != canonicalize(payload)):
                raise ICDError("BUSINESS_FAILED", "real model getter differs from the staged binding group")
            return EnvironmentApplication(target_step, fields["model_revision"],
                                          canonicalize(fields["readback"]))
        raise ICDError("EXPIRED", "real model did not reach the requested binding boundary in time")


class BindingModelConsumerService(EnvironmentModelConsumerService):
    """Single Receiver owner for all 97 frozen root bindings."""

    def __init__(self, contract, registry, bindings, backend, *, max_records=MAX_RECORDS,
                 max_bytes=MAX_BYTES, clock=time.monotonic_ns):
        if (type(registry) is not SessionRegistry or registry.contract is not contract
                or type(bindings) is not ModelBindings or bindings.contract is not contract
                or bindings.model_id not in _MODEL_BINDING_MESSAGES
                or not isinstance(backend, ContractModelBridge)
                or type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS
                or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES
                or not callable(clock)):
            raise ICDError("STATE", "same-contract generated binding consumer required")
        self.contract, self.registry, self.bindings, self.backend = contract, registry, bindings, backend
        self._contract, self._registry, self._bindings, self._backend = contract, registry, bindings, backend
        self._max_records, self._max_bytes, self._clock = max_records, max_bytes, clock
        self._receiver, self._closed, self._records, self._bytes = None, False, [], 0
        self._completion, self._last_observed_ns, self._flight_owner = None, None, None

    def supports(self, message_id, model_id):
        self._check()
        return model_id == self.bindings.model_id and message_id in _MODEL_BINDING_MESSAGES[model_id]

    def respond(self, request, received, *, now_ns):
        self._check()
        sid, message_id = request["header"]["session_id"], request["message_id"]
        model_id = self.registry.identity(sid)["model_id"]
        if self._receiver is None or not self.supports(message_id, model_id):
            raise ICDError("TARGET_MISSING", "binding consumer is not installed for this model/message")
        group = _MODEL_BINDING_MESSAGES[model_id][message_id]
        if group == "flight_control":
            if "CONTROLLER" not in self.registry.roles(sid):
                raise ICDError("CONTROL_OWNER", "flight-control binding requires the Controller role")
            if self._flight_owner not in self.registry.session_ids:
                self._flight_owner = None
            if self._flight_owner is not None and self._flight_owner != sid:
                raise ICDError("CONTROL_OWNER", "another live Controller owns the flight-control lane")
        if self._completion is not None:
            raise ICDError("STATE", "one generated binding completion at a time")
        if len(self._records) >= self._max_records:
            raise ICDError("BUFFER_FULL", "retain binding evidence before another application")
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual binding consumer clock differs from receiver")
        app = self.backend.apply_group(request, self.bindings, now_ns=completed)
        completed = self._clock()
        if type(completed) is not int or completed < now_ns:
            raise ICDError("CLOCK_UNSYNC", "actual binding completion clock differs from receiver")
        terminal = self._receiver._ack(message_id, request["header"], stage="APPLIED", error="OK",
                                       applied_step=app.applied_step,
                                       model_revision=app.model_revision,
                                       probe_id=1000 + message_id)
        replies = (received, terminal)
        record = EnvironmentConsumerRecord(canonicalize(request), app.readback_json, now_ns, completed,
                                           app.applied_step, app.model_revision)
        if self._bytes + record.stored_bytes > self._max_bytes:
            raise ICDError("BUFFER_FULL", "binding evidence storage is full")
        self._completion = (canonicalize(request), tuple(canonicalize(reply) for reply in replies), completed)
        try:
            self.registry._record_binding_response(request, replies, self, now_ns=completed)
        finally:
            self._completion = None
        if group == "flight_control":
            self._flight_owner = sid
        self._records.append(record)
        self._bytes += record.stored_bytes
        self._last_observed_ns = completed
        return replies
