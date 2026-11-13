import tempfile
from pathlib import Path

from common import GatewayTest, message


class CcoreHILServiceTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.session import PeerBinding, SourceGrant
        self.identity = message(1)["payload"]["identity"]
        self.grants = (SourceGrant(self.identity, ("STIMULUS",),
                                   (PeerBinding("ETH_0", "UDP", "127.0.0.1:36602"),)),)

    def test_service_requires_explicit_actual_owners_and_closes_them(self):
        from icd_gateway.hil_service import CcoreHILService
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        service = CcoreHILService(
            self.contract, self.grants, {"quadrotor_hil": ("127.0.0.1", 9997)},
            temporary.name, clock=lambda: 100)
        self.addCleanup(service.close)
        self.assertIs(service.receiver.configuration_service, service.configuration_service)
        self.assertIs(service.configuration_service.backend, service.backend)
        self.assertIs(service.preparation.backend, service.preparation_backend)
        self.assertIsNot(service.preparation.backend, service.backend)
        self.assertTrue(service.backend._require_prepared_existing)
        self.assertFalse(service.preparation_backend._require_prepared_existing)
        self.assertIs(service.receiver.status_service, service.status_service)
        self.assertIs(service.receiver.lifecycle_service, service.lifecycle_service)
        self.assertIs(service.lifecycle_service.backend, service.lifecycle_backend)
        self.assertEqual(service.backend.model_ids, ("quadrotor_hil",))
        service.close()
        self.rejects("STATE", lambda: service.target_status("quadrotor_hil"))

    def test_service_rejects_missing_explicit_resource_root(self):
        from icd_gateway.hil_service import CcoreHILService
        self.rejects("SCHEMA", lambda: CcoreHILService(
            self.contract, self.grants, {"quadrotor_hil": ("127.0.0.1", 9997)}, None))

    def test_status_archive_is_outside_resource_store_and_restart_is_allowed(self):
        from icd_gateway.hil_service import CcoreHILService
        with tempfile.TemporaryDirectory() as parent:
            resource_root = Path(parent) / "resources"
            service = CcoreHILService(
                self.contract, self.grants, {"quadrotor_hil": ("127.0.0.1", 9997)},
                resource_root, clock=lambda: 100)
            archive_root = Path(parent) / "resources-status-evidence"
            self.assertEqual(service.status_service._archive_root, archive_root)
            self.assertTrue(archive_root.is_dir())
            self.assertFalse((resource_root / "status-evidence").exists())
            service.close()

            restarted = CcoreHILService(
                self.contract, self.grants, {"quadrotor_hil": ("127.0.0.1", 9997)},
                resource_root, clock=lambda: 200)
            self.addCleanup(restarted.close)
