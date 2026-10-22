"""Owned first-circle HIL service composition for a C-core target.

There is intentionally no implicit/default backend: construction requires an
explicit C-core endpoint and an owned persistent resource root.  The same
Contract and SessionRegistry are shared by the formal Receiver and the
internal PreparationService, so first-circle preparation and second-circle
RunConfigure cannot disagree about identity or frozen schema.
"""

from pathlib import Path

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError

from .configuration_service import ModelConfigurationService
from .lifecycle_service import ModelLifecycleService
from .status_service import ModelStatusService
from .model_consumer import (
    BindingModelConsumerService,
    CcoreConfigurationBackend,
    CcoreLifecycleBackend,
    CcoreStatusBackend,
    ContractModelBridge,
    StoredRunConfigurationResourceResolver,
)
from .preparation_service import PreparationService
from .receiver import Receiver
from .resources import ResourceStore
from .model_bindings import ModelBindings
from .session import SessionRegistry
from .udp import UDPGateway


class CcoreHILService:
    """One explicit C-core configuration/receiver owner.

    RunConfigure/first-circle preparation and the target-step C lifecycle
    owner share one contract, registry and C endpoint.  STEP remains a safe
    `UNSUPPORTED` rejection until C retains the required per-step history.
    """

    def __init__(self, contract, grants, endpoints, resource_root, *,
                 timeout_s=0.05, poll_s=0.001, clock=None, runtime_contracts=None):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError("HASH", "verified contract required for C-core HIL service")
        if type(grants) is not tuple or not grants:
            raise ICDError("AUTHORIZATION", "explicit source grants required for C-core HIL service")
        if not isinstance(resource_root, (str, Path)):
            raise ICDError("SCHEMA", "owned C-core resource root path required")
        self.contract = contract
        self.registry = SessionRegistry(contract, grants)
        self.resources = ResourceStore(contract, Path(resource_root))
        try:
            self.resource_resolver = StoredRunConfigurationResourceResolver(contract, self.resources)
            kwargs = {"resource_resolver": self.resource_resolver,
                      "timeout_s": timeout_s, "poll_s": poll_s,
                      "require_prepared_existing": True}
            if clock is not None:
                kwargs["clock"] = clock
            # Keep the two circles on the same C-core target and the same
            # immutable resource resolver, but do not give the formal
            # receiver first-circle write authority.  In particular, sharing
            # ``self.backend`` with PreparationService would make preparation
            # inherit ``require_prepared_existing=True`` and reject the only
            # legal STOPPED -> CONFIGURED transition.  Conversely, giving the
            # receiver the preparation backend would let a second-circle ID3
            # configure an unprepared target.  These are separate internal
            # owners, not additional network interfaces.
            self.backend = CcoreConfigurationBackend(contract, endpoints, **kwargs)
            preparation_kwargs = {"resource_resolver": self.resource_resolver,
                                  "timeout_s": timeout_s, "poll_s": poll_s,
                                  "require_prepared_existing": False}
            if clock is not None:
                preparation_kwargs["clock"] = clock
            self.preparation_backend = CcoreConfigurationBackend(
                contract, endpoints, **preparation_kwargs)
            self.configuration_service = ModelConfigurationService(
                contract, self.registry, self.backend, **({"clock": clock} if clock is not None else {}))
            lifecycle_kwargs = {"timeout_s": 1.0, "poll_s": poll_s}
            if clock is not None:
                lifecycle_kwargs["clock"] = clock
            self.lifecycle_backend = CcoreLifecycleBackend(contract, endpoints, **lifecycle_kwargs)
            self.lifecycle_service = ModelLifecycleService(
                contract, self.registry, self.lifecycle_backend,
                **({"clock": clock} if clock is not None else {}))
            status_kwargs = {"timeout_s": timeout_s, "poll_s": poll_s}
            if clock is not None:
                status_kwargs["clock"] = clock
            self.status_backend = CcoreStatusBackend(contract, endpoints, **status_kwargs)
            self.status_service = ModelStatusService(
                contract, self.registry, self.status_backend,
                **({"clock": clock} if clock is not None else {}))
            self.model_consumer = None
            if runtime_contracts is not None:
                if (type(runtime_contracts) is not dict or set(runtime_contracts) != set(endpoints)
                        or len(runtime_contracts) != 1):
                    raise ICDError("MODEL", "one complete generated runtime contract is required for C-core input consumption")
                model_id, runtime_contract = next(iter(runtime_contracts.items()))
                bindings = ModelBindings(contract, model_id, runtime_contract)
                self.model_consumer = BindingModelConsumerService(
                    contract, self.registry, bindings,
                    ContractModelBridge(endpoints[model_id], timeout_s=timeout_s, poll_s=poll_s),
                    **({"clock": clock} if clock is not None else {}))
            self.receiver = Receiver(contract, self.registry,
                                     configuration_service=self.configuration_service,
                                     lifecycle_service=self.lifecycle_service,
                                     status_service=self.status_service,
                                     model_consumer_service=self.model_consumer)
            self.preparation = PreparationService(
                contract, self.preparation_backend,
                **({"clock": clock} if clock is not None else {}))
            self._closed = False
        except Exception:
            self.resources.close()
            raise

    def target_status(self, model_id):
        """Read the real C target capability without changing model state."""
        if self._closed:
            raise ICDError("STATE", "C-core HIL service is closed")
        if model_id not in self.backend.model_ids:
            raise ICDError("MODEL", "model has no configured C-core endpoint")
        fields = self.backend._status(model_id)
        self.backend._require_configuration_abi(fields)
        return fields

    def udp_gateway(self, *, bind, feedback_routes, channel):
        if self._closed:
            raise ICDError("STATE", "C-core HIL service is closed")
        return UDPGateway(self.receiver, bind=bind, feedback_routes=feedback_routes, channel=channel)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.receiver.close()
        finally:
            self.resources.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
