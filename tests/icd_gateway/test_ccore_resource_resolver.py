import base64
import copy
import hashlib
from pathlib import Path
import tempfile

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize


def chunk(data, *, kind, sequence):
    value = message(34)
    value["header"].update(session_id=1, sequence=sequence, transaction_id=sequence)
    value["payload"] = {
        "resource_sha256": hashlib.sha256(data).hexdigest(), "resource_kind": kind,
        "size_bytes": len(data), "offset_bytes": 0, "chunk_length": len(data),
        "data_base64": base64.b64encode(data).decode("ascii"),
        "chunk_sha256": hashlib.sha256(data).hexdigest(), "final": True,
    }
    return value


class StoredRunConfigurationResourceResolverTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.resources import ResourceStore
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ResourceStore(self.contract, Path(temporary.name), min_free_bytes=0)
        self.addCleanup(self.store.close)
        from icd_gateway.model_consumer import StoredRunConfigurationResourceResolver
        self.resolver = StoredRunConfigurationResourceResolver(self.contract, self.store)

    def _configuration(self):
        return message(3)["payload"]

    def _put(self, document, *, kind, sequence):
        raw = canonicalize(document)
        receipt = self.store.accept(chunk(raw, kind=kind, sequence=sequence), now_ns=sequence)
        self.assertTrue(receipt.complete)
        return receipt.resource_sha256

    def test_resolves_owned_terrain_and_obstacles_at_the_initial_point(self):
        configuration = self._configuration()
        terrain = {
            "resource_id": "terrain-1", "origin": configuration["origin"],
            "rows": 2, "columns": 2, "spacing_n_m": 10, "spacing_e_m": 10,
            "height_datum": "ELLIPSOID", "heights_m": [10, 20, 30, 40],
            "nodata_policy": "REJECT_ROUTE_OUTSIDE_GRID",
        }
        obstacles = {"revision": 1, "obstacles": []}
        configuration["terrain_resource_sha256"] = self._put(terrain, kind="TERRAIN", sequence=1)
        configuration["obstacle_resource_sha256"] = self._put(obstacles, kind="OBSTACLES", sequence=2)
        configuration["initial_state"]["position"].update(north_m=5, east_m=5, down_m=-25)
        configuration["initial_state"]["airborne"] = True

        resolved = self.resolver.resolve(configuration)

        self.assertEqual(resolved.terrain_sha256, configuration["terrain_resource_sha256"])
        self.assertEqual(resolved.obstacle_sha256, configuration["obstacle_resource_sha256"])
        self.assertEqual(resolved.ground_down, -25.0)

    def test_origin_and_grid_coverage_are_checked_before_configuration_write(self):
        configuration = self._configuration()
        terrain = {
            "resource_id": "terrain-1", "origin": copy.deepcopy(configuration["origin"]),
            "rows": 2, "columns": 2, "spacing_n_m": 1, "spacing_e_m": 1,
            "height_datum": "ELLIPSOID", "heights_m": [0, 0, 0, 0],
            "nodata_policy": "REJECT_ROUTE_OUTSIDE_GRID",
        }
        terrain["origin"]["latitude_deg"] = 1
        configuration["terrain_resource_sha256"] = self._put(terrain, kind="TERRAIN", sequence=1)
        configuration["obstacle_resource_sha256"] = None
        self.rejects("RESOURCE", lambda: self.resolver.resolve(configuration))

        terrain["origin"] = copy.deepcopy(configuration["origin"])
        configuration["terrain_resource_sha256"] = self._put(terrain, kind="TERRAIN", sequence=2)
        configuration["initial_state"]["position"]["north_m"] = 3
        self.rejects("RESOURCE", lambda: self.resolver.resolve(configuration))

    def test_tampered_completed_resource_is_not_reused(self):
        configuration = self._configuration()
        terrain = {
            "resource_id": "terrain-1", "origin": configuration["origin"],
            "rows": 2, "columns": 2, "spacing_n_m": 1, "spacing_e_m": 1,
            "height_datum": "ELLIPSOID", "heights_m": [0, 0, 0, 0],
            "nodata_policy": "REJECT_ROUTE_OUTSIDE_GRID",
        }
        sha = self._put(terrain, kind="TERRAIN", sequence=1)
        configuration["terrain_resource_sha256"] = sha
        configuration["obstacle_resource_sha256"] = None
        stored = self.store.resolve(sha, kind="TERRAIN")
        stored.path.write_bytes(b"{}")
        self.rejects("HASH", lambda: self.resolver.resolve(configuration))
