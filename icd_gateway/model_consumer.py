"""Actual model-boundary consumer for the first sequential input: ID10.

Reception and schema validation are deliberately insufficient here.  The
backend must stage the complete Environment snapshot and return a readback
from the generated model's target step before this service emits APPLIED.
"""

from dataclasses import dataclass
import json
import socket
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from .model_bindings import ModelBindings
from .session import SessionRegistry


MAX_RECORDS = 4096
MAX_BYTES = 16 * 1024 * 1024


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
