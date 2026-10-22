"""First-circle HIL preparation using the same actual configuration backend.

This is an internal HIL coordination boundary, not a replacement management
API.  It accepts the frozen RunConfigure business message, drives the installed
``ModelConfigurationBackend`` once, and records only a result backed by actual
post-write readback.  No default backend is provided here.
"""

import hashlib
import threading
import time
from dataclasses import dataclass

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .configuration_service import (
    ModelConfigurationBackend,
    ModelConfigurationContext,
    ModelConfigurationReceipt,
)
from .semantic_guards import SemanticGuards


MAX_TIME = 2**64 - 1


@dataclass(frozen=True, slots=True)
class PreparationResult:
    prepare_id: str
    model_id: str
    config_id: str
    config_sha256: str
    baseline_sha256: str
    configuration_json: bytes
    initial_state_json: bytes
    initial_inputs_json: bytes
    model_revision: int
    model_step: int
    state: str
    control_source: str
    sampled_ns: int

    @property
    def configured(self):
        return self.state == "CONFIGURED" and self.control_source == "NONE"


class PreparationService:
    """Serialises actual first-circle preparation and proves its readback."""

    def __init__(self, contract, backend, *, clock=time.monotonic_ns, max_results=64):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError("HASH", "verified formal contract required for preparation")
        if not isinstance(backend, ModelConfigurationBackend) or backend.contract is not contract:
            raise ICDError("TARGET_MISSING", "same-contract actual configuration backend required")
        if not callable(clock) or type(max_results) is not int or not 1 <= max_results <= 4096:
            raise ICDError("CAPACITY", "bounded preparation history and clock required")
        self.contract = contract
        self.backend = backend
        self._clock = clock
        self._max_results = max_results
        self._by_prepare_id = {}
        self._by_snapshot = {}
        self._lock = threading.Lock()

    def _now(self):
        value = self._clock()
        if type(value) is not int or not 0 <= value <= MAX_TIME:
            raise ICDError("CLOCK_UNSYNC", "preparation clock must return uint64 nanoseconds")
        return value

    def _verify_context(self, context, identity, original, now):
        if type(context) is not ModelConfigurationContext:
            raise ICDError("STATE", "actual configuration context is required")
        if (loads(context.identity_json) != identity or canonicalize(loads(context.request_json)) != original
                or context.view.model_id != identity["model_id"]):
            raise ICDError("MODEL", "actual configuration context does not match preparation request")
        if not context.sampled_ns <= now < min(context.deadline_ns, context.sampled_ns + 240_000_000):
            raise ICDError("EXPIRED", "actual configuration context is stale")

    def _verify_receipt(self, receipt, identity, original, context, started, now):
        if type(receipt) is not ModelConfigurationReceipt:
            raise ICDError("STATE", "actual configuration receipt is required")
        if (loads(receipt.identity_json) != identity or canonicalize(loads(receipt.request_json)) != original
                or receipt.view.model_id != identity["model_id"]):
            raise ICDError("MODEL", "actual configuration receipt does not match preparation request")
        if not started <= receipt.sampled_ns <= now < min(receipt.deadline_ns, receipt.sampled_ns + 240_000_000):
            raise ICDError("EXPIRED", "actual configuration readback is stale")
        expected = loads(original)["payload"]
        configuration = loads(receipt.configuration_json)
        if (canonicalize(configuration) != canonicalize(expected)
                or canonicalize(loads(receipt.initial_state_json)) != canonicalize(expected["initial_state"])
                or canonicalize(loads(receipt.initial_inputs_json)) != canonicalize(expected["initial_inputs"])):
            raise ICDError("BUSINESS_FAILED", "complete actual preparation readback differs")
        view = receipt.view
        if (view.state != "CONFIGURED" or not view.configured_once or view.control_source != "NONE"
                or view.model_step != context.view.model_step
                or view.max_duration_steps != configuration["max_duration_steps"]):
            raise ICDError("STATE", "actual HIL is not at the configured safe boundary")

    def prepare(self, prepare_id, identity, request):
        """Prepare once; equal snapshots replay the verified original result.

        ``request`` is a complete frozen ID3 RunConfigure message with a
        nonzero session header supplied by the HIL coordinator.  It is never
        put on the formal data transport by this service.
        """
        if type(prepare_id) is not str or not 1 <= len(prepare_id) <= 128:
            raise ICDError("SCHEMA", "bounded preparation ID required")
        if type(identity) is not dict:
            raise ICDError("SCHEMA", "Run identity object required")
        self.contract.validate_message(request, direction="TO_36")
        if request["message_id"] != 3:
            raise ICDError("UNSUPPORTED", "preparation accepts only frozen RunConfigure")
        if identity.get("model_id") not in self.backend.model_ids:
            raise ICDError("TARGET_MISSING", "requested model has no actual configuration backend")
        if request["payload"]["model_id"] != identity["model_id"]:
            raise ICDError("MODEL", "RunConfigure and preparation identity select different models")
        original = canonicalize(request)
        config_json = canonicalize(request["payload"])
        snapshot = hashlib.sha256(config_json).hexdigest()
        with self._lock:
            previous = self._by_prepare_id.get(prepare_id)
            if previous is not None:
                if previous.config_sha256 != snapshot:
                    raise ICDError("DUPLICATE", "prepare_id names another configuration snapshot")
                return previous
            previous = self._by_snapshot.get(snapshot)
            if previous is not None:
                return previous
            if len(self._by_prepare_id) >= self._max_results:
                raise ICDError("CAPACITY", "preparation history capacity is exhausted")
            now = self._now()
            context = self.backend.read_context(dict(identity), original, now_ns=now)
            completed = self._now()
            self._verify_context(context, identity, original, completed)
            # An already CONFIGURED target is admissible only when the actual
            # backend has just proved that its retained full snapshot is
            # canonically equal to this request.  This makes a first-circle
            # call after a service restart a readback-only reconciliation; it
            # never grants permission to overwrite another configuration.
            SemanticGuards(self.contract).run_configure(
                request, context.view, terrain_ground_down=context.ground_down,
                allow_configured_existing=context.idempotent_existing)
            started = completed
            receipt = self.backend.apply_configuration(original, context, now_ns=started)
            completed = self._now()
            self._verify_receipt(receipt, identity, original, context, started, completed)
            result = PreparationResult(
                prepare_id=prepare_id, model_id=identity["model_id"], config_id=snapshot,
                config_sha256=snapshot, baseline_sha256=self.contract.baseline_sha256,
                configuration_json=receipt.configuration_json,
                initial_state_json=receipt.initial_state_json,
                initial_inputs_json=receipt.initial_inputs_json,
                model_revision=receipt.model_revision, model_step=receipt.view.model_step,
                state=receipt.view.state, control_source=receipt.view.control_source,
                sampled_ns=receipt.sampled_ns)
            self._by_prepare_id[prepare_id] = result
            self._by_snapshot[snapshot] = result
            return result

    @property
    def results(self):
        with self._lock:
            return tuple(self._by_prepare_id.values())
