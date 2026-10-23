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
    ModelConfigurationBoundary,
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
        expected_revision = context.model_revision if context.idempotent_existing else context.model_revision + 1
        if (expected_revision > 0xffffffff or receipt.model_revision != expected_revision):
            raise ICDError("STATE", "actual model revision does not match the verified configuration boundary")
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

    @staticmethod
    def _boundary_values(boundary):
        if type(boundary) is not ModelConfigurationBoundary:
            raise ICDError("STATE", "authoritative C-core boundary is required")
        return (boundary.lifecycle, boundary.model_step, boundary.model_revision,
                boundary.control_source)

    @staticmethod
    def _context_boundary_values(context):
        return (context.view.state, context.view.model_step, context.model_revision,
                context.view.control_source)

    def _verify_boundary_fresh(self, boundary, now):
        if type(boundary) is not ModelConfigurationBoundary:
            raise ICDError("STATE", "authoritative C-core boundary is required")
        if not boundary.sampled_ns <= now < min(boundary.deadline_ns,
                                                 boundary.sampled_ns + 240_000_000):
            raise ICDError("EXPIRED", "authoritative C-core boundary is stale")

    @staticmethod
    def _run_configure_request(configuration, target_step):
        return {"message_id": 3,
                "header": {"session_id": 1, "sequence": 1, "target_step": target_step,
                           "transaction_id": 1, "valid_for_ms": 1000},
                "payload": loads(canonicalize(configuration))}

    @staticmethod
    def _same_verified_result(result, context, snapshot):
        return (context.idempotent_existing and result.config_sha256 == snapshot
                and result.model_id == context.view.model_id and result.state == context.view.state
                and result.model_step == context.view.model_step
                and result.model_revision == context.model_revision
                and result.control_source == context.view.control_source)

    def _prepare_locked(self, prepare_id, identity, configuration, snapshot, request_factory):
        previous = self._by_prepare_id.get(prepare_id)
        if previous is not None:
            if previous.config_sha256 != snapshot:
                raise ICDError("DUPLICATE", "prepare_id names another configuration snapshot")
            return previous
        previous_snapshot = self._by_snapshot.get(snapshot)
        if len(self._by_prepare_id) >= self._max_results and previous_snapshot is None:
            raise ICDError("CAPACITY", "preparation history capacity is exhausted")
        started_read = self._now()
        boundary = self.backend.read_boundary(dict(identity), now_ns=started_read)
        sampled = self._now()
        self._verify_boundary_fresh(boundary, sampled)
        request = request_factory(boundary)
        self.contract.validate_message(request, direction="TO_36")
        if request["message_id"] != 3 or canonicalize(request["payload"]) != canonicalize(configuration):
            raise ICDError("MODEL", "verified preparation request differs from the fixed RunConfigure")
        original = canonicalize(request)
        context = self.backend.read_context(dict(identity), original, now_ns=sampled)
        completed = self._now()
        self._verify_context(context, identity, original, completed)
        self._verify_boundary_fresh(boundary, completed)
        if self._context_boundary_values(context) != self._boundary_values(boundary):
            raise ICDError("STATE", "C-core lifecycle, step, revision or control source changed during preparation validation")
        SemanticGuards(self.contract).run_configure(
            request, context.view, terrain_ground_down=context.ground_down,
            allow_configured_existing=context.idempotent_existing)
        if boundary.model_step != 0:
            raise ICDError("STATE", "new Run preparation requires authoritative C-core model_step 0")
        if previous_snapshot is not None and self._same_verified_result(previous_snapshot, context, snapshot):
            return previous_snapshot
        if len(self._by_prepare_id) >= self._max_results:
            raise ICDError("CAPACITY", "preparation history capacity is exhausted")
        if not context.idempotent_existing and context.model_revision == 0xffffffff:
            raise ICDError("STATE", "C-core model revision is exhausted")
        write_started = completed
        receipt = self.backend.apply_configuration(original, context, now_ns=write_started)
        completed = self._now()
        self._verify_receipt(receipt, identity, original, context, write_started, completed)
        result = PreparationResult(prepare_id=prepare_id, model_id=identity["model_id"], config_id=snapshot,
            config_sha256=snapshot, baseline_sha256=self.contract.baseline_sha256,
            configuration_json=receipt.configuration_json, initial_state_json=receipt.initial_state_json,
            initial_inputs_json=receipt.initial_inputs_json, model_revision=receipt.model_revision,
            model_step=receipt.view.model_step, state=receipt.view.state,
            control_source=receipt.view.control_source, sampled_ns=receipt.sampled_ns)
        self._by_prepare_id[prepare_id] = result
        self._by_snapshot[snapshot] = result
        return result

    def prepare_current(self, prepare_id, identity, configuration):
        """Build RunConfigure.target_step from a fresh authoritative C-core boundary."""
        if type(prepare_id) is not str or not 1 <= len(prepare_id) <= 128:
            raise ICDError("SCHEMA", "bounded preparation ID required")
        if type(identity) is not dict:
            raise ICDError("SCHEMA", "Run identity object required")
        frozen_identity = loads(canonicalize(identity))
        if frozen_identity.get("model_id") not in self.backend.model_ids:
            raise ICDError("TARGET_MISSING", "requested model has no actual configuration backend")
        config_json = canonicalize(configuration)
        frozen_configuration = loads(config_json)
        self.contract.validate_payload(3, frozen_configuration)
        if frozen_configuration["model_id"] != frozen_identity["model_id"]:
            raise ICDError("MODEL", "RunConfigure and preparation identity select different models")
        snapshot = hashlib.sha256(config_json).hexdigest()
        with self._lock:
            return self._prepare_locked(prepare_id, frozen_identity, frozen_configuration, snapshot,
                lambda boundary: self._run_configure_request(frozen_configuration, boundary.model_step))

    def prepare(self, prepare_id, identity, request):
        """Prepare one frozen ID3 message, preserving its original idempotency key."""
        if type(prepare_id) is not str or not 1 <= len(prepare_id) <= 128:
            raise ICDError("SCHEMA", "bounded preparation ID required")
        if type(identity) is not dict:
            raise ICDError("SCHEMA", "Run identity object required")
        self.contract.validate_message(request, direction="TO_36")
        frozen_request = loads(canonicalize(request))
        self.contract.validate_message(frozen_request, direction="TO_36")
        frozen_identity = loads(canonicalize(identity))
        if frozen_request["message_id"] != 3:
            raise ICDError("UNSUPPORTED", "preparation accepts only frozen RunConfigure")
        if frozen_identity.get("model_id") not in self.backend.model_ids:
            raise ICDError("TARGET_MISSING", "requested model has no actual configuration backend")
        if frozen_request["payload"]["model_id"] != frozen_identity["model_id"]:
            raise ICDError("MODEL", "RunConfigure and preparation identity select different models")
        config_json = canonicalize(frozen_request["payload"])
        snapshot = hashlib.sha256(config_json).hexdigest()
        with self._lock:
            return self._prepare_locked(
                prepare_id, frozen_identity, frozen_request["payload"], snapshot,
                lambda _boundary: frozen_request)

    @property
    def results(self):
        with self._lock:
            return tuple(self._by_prepare_id.values())
