import base64
import copy
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
from pathlib import Path
import tempfile

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize


def chunk(data, offset=0, length=None, *, kind="MODEL", sid=1, sequence=1):
    length = len(data) - offset if length is None else length
    part = data[offset:offset + length]
    value = message(34)
    value["header"].update(session_id=sid, sequence=sequence, transaction_id=sequence)
    value["payload"] = {
        "resource_sha256": hashlib.sha256(data).hexdigest(), "resource_kind": kind,
        "size_bytes": len(data), "offset_bytes": offset, "chunk_length": length,
        "data_base64": base64.b64encode(part).decode("ascii"),
        "chunk_sha256": hashlib.sha256(part).hexdigest(), "final": offset + length == len(data),
    }
    return value


class ResourceTests(GatewayTest):
    def store(self, **limits):
        from icd_gateway.resources import ResourceStore
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = ResourceStore(self.contract, Path(temporary.name), min_free_bytes=0, **limits)
        self.addCleanup(store.close)
        return store

    def test_common_actual_storage_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.resources"),
                             "common actual ResourceChunk file store is missing")

    def test_actual_multichunk_bytes_and_exact_duplicate(self):
        store = self.store()
        data = bytes(range(256)) * 300
        first = store.accept(chunk(data, 0, 32768), now_ns=0)
        self.assertFalse(first.complete)
        self.assertEqual(first.next_offset, 32768)
        self.assertEqual(store.accept(chunk(data, 0, 32768, sequence=2), now_ns=1), first)
        store.accept(chunk(data, 32768, 32768, sequence=3), now_ns=2)
        final = store.accept(chunk(data, 65536, sequence=4), now_ns=3)
        self.assertTrue(final.complete)
        self.assertEqual(final.stored_bytes, len(data))
        stored = store.resolve(final.resource_sha256, kind="MODEL")
        self.assertEqual(stored.path.read_bytes(), data)
        self.assertEqual(stored.content_status, "OPAQUE_BYTES")
        self.contract.validate_payload(141, final.payload())
        self.assertEqual(store.active_count, 0)
        self.assertEqual(store.completed_count, 1)
        with self.assertRaises(FrozenInstanceError):
            final.complete = False

    def test_bad_base64_length_and_final_never_allocate(self):
        cases = [("data_base64", "!!!!", "SCHEMA"), ("data_base64", "AB==", "SCHEMA"),
                 ("chunk_length", 2, "SCHEMA"), ("final", False, "FRAGMENT")]
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                store = self.store()
                request = chunk(b"\x00")
                request["payload"][field] = value
                self.rejects(code, lambda: store.accept(request, now_ns=0))
                self.assertEqual(store.active_count, 0)
                self.assertEqual(store.completed_count, 0)

    def test_early_final_gap_overlap_and_changed_chunk_rejected(self):
        store = self.store()
        data = b"abcdef"
        request = chunk(data, 0, 2)
        early = copy.deepcopy(request)
        early["payload"]["final"] = True
        self.rejects("FRAGMENT", lambda: store.accept(early, now_ns=0))
        store.accept(request, now_ns=0)
        for offset in (1, 3):
            self.rejects("OUT_OF_ORDER", lambda: store.accept(chunk(data, offset, 1), now_ns=1))
        changed = chunk(data, 0, 2)
        changed["payload"].update(data_base64="eno=", chunk_sha256=hashlib.sha256(b"zz").hexdigest())
        self.rejects("DUPLICATE", lambda: store.accept(changed, now_ns=1))
        self.assertEqual(store.active_count, 1)

    def test_actual_chunk_hash_rejected_before_write(self):
        store = self.store()
        value = chunk(b"ok")
        value["payload"]["chunk_sha256"] = "0" * 64
        self.rejects("HASH", lambda: store.accept(value, now_ns=0))
        self.assertEqual(store.reserved_bytes, 0)

    def test_wrong_whole_hash_aborts_and_retains_original_requests(self):
        store = self.store()
        data = b"abcdef"
        first, last = chunk(data, 0, 3), chunk(data, 3, sequence=2)
        first["payload"]["resource_sha256"] = last["payload"]["resource_sha256"] = "0" * 64
        store.accept(first, now_ns=0)
        self.rejects("HASH", lambda: store.accept(last, now_ns=1))
        self.assertEqual(store.completed_count, 0)
        self.assertEqual(store.active_count, 0)
        aborted = store.drain_aborted()
        self.assertEqual(len(aborted), 1)
        self.assertEqual(aborted[0].error, "HASH")
        self.assertEqual(aborted[0].requests, (canonicalize(first), canonicalize(last)))
        self.assertEqual(store.drain_aborted(), ())

    def test_changed_declaration_and_other_session_cannot_take_upload(self):
        store = self.store()
        data = b"abcdef"
        store.accept(chunk(data, 0, 3), now_ns=0)
        self.rejects("AUTHORIZATION", lambda: store.accept(chunk(data, 3, sid=2), now_ns=1))
        value = chunk(data, 3)
        value["payload"]["resource_kind"] = "VIDEO"
        self.rejects("DUPLICATE", lambda: store.accept(value, now_ns=1))
        self.assertEqual(store.reserved_bytes, len(data))

    def test_session_abort_is_scoped_and_preserves_completed_objects(self):
        store = self.store()
        one = chunk(b"abcdef", 0, 3, sid=1)
        two = chunk(b"ghijkl", 0, 3, sid=2)
        store.accept(one, now_ns=0)
        store.accept(two, now_ns=1)
        complete = store.accept(chunk(b"done", sid=1), now_ns=2)
        aborted = store.abort_session(1)
        self.assertEqual(len(aborted), 1)
        self.assertEqual(aborted[0].requests, (canonicalize(one),))
        self.assertEqual(store.active_count, 1)
        self.assertEqual(store.abort_session(1), ())
        self.assertEqual(store.resolve(complete.resource_sha256, kind="MODEL").size_bytes, 4)
        self.assertEqual(store.drain_aborted(), aborted)

    def test_clock_and_session_types_reject_before_state_change(self):
        store = self.store()
        data = b"abcdef"
        store.accept(chunk(data, 0, 3), now_ns=10)
        for now in (9, -1, True, 1.5):
            self.rejects("SCHEMA", lambda: store.accept(chunk(data, 3), now_ns=now))
        for sid in (True, 0, 1.5, -1, 2**32):
            self.rejects("SCHEMA", lambda: store.abort_session(sid))
        self.assertEqual(store.active_count, 1)
        self.assertEqual(store.accept(chunk(data, 3), now_ns=10).stored_bytes, 6)

    def test_limits_enforced_without_eviction(self):
        store = self.store(max_resource_bytes=6, max_total_bytes=10, max_uploads=1, max_objects=2)
        self.rejects("CAPACITY", lambda: store.accept(chunk(b"1234567"), now_ns=0))
        store.accept(chunk(b"abcdef", 0, 3), now_ns=0)
        self.rejects("BUFFER_FULL", lambda: store.accept(chunk(b"xy", 0, 1), now_ns=1))
        store.accept(chunk(b"abcdef", 3), now_ns=1)
        self.rejects("CAPACITY", lambda: store.accept(chunk(b"12345"), now_ns=2))
        store.accept(chunk(b"xy"), now_ns=2)
        self.rejects("BUFFER_FULL", lambda: store.accept(chunk(b"z"), now_ns=3))
        self.assertEqual(store.reserved_bytes, 8)

    def test_chunk_limit_does_not_drop_existing_data(self):
        store = self.store(max_chunks=2)
        data = b"abc"
        store.accept(chunk(data, 0, 1), now_ns=0)
        store.accept(chunk(data, 1, 1), now_ns=1)
        self.rejects("CAPACITY", lambda: store.accept(chunk(data, 2, 1), now_ns=2))
        self.assertEqual(store.active_count, 1)
        self.assertEqual(store.reserved_bytes, 3)

    def test_low_disk_margin_rejected_with_actual_disk(self):
        import shutil
        store = self.store()
        store.min_free_bytes = shutil.disk_usage(store.root).free + 1
        self.rejects("CAPACITY", lambda: store.accept(chunk(b"data"), now_ns=0))
        self.assertEqual(store.active_count, 0)

    def test_close_is_terminal_returns_originals_and_is_idempotent(self):
        store = self.store()
        value = chunk(b"abcdef", 0, 3)
        store.accept(value, now_ns=0)
        removed = store.close()
        self.assertEqual(removed[0].requests, (canonicalize(value),))
        self.assertEqual(removed[0].error, "STATE")
        self.assertEqual(store.close(), ())
        self.assertEqual(store.drain_aborted(), removed)
        self.rejects("STATE", lambda: store.accept(chunk(b"z"), now_ns=1))
        self.rejects("STATE", lambda: store.resolve(hashlib.sha256(b"z").hexdigest(), kind="MODEL"))

    def test_frozen_message_closed_fields_and_wrong_message_id(self):
        store = self.store()
        value = chunk(b"data")
        value["payload"]["file_name"] = "../escape"
        self.rejects("SCHEMA", lambda: store.accept(value, now_ns=0))
        self.rejects("UNSUPPORTED", lambda: store.accept(message(41), now_ns=0))
        self.assertEqual(store.active_count, 0)

    def test_mutating_caller_message_cannot_change_abort_evidence(self):
        store = self.store()
        value = chunk(b"abcdef", 0, 3)
        original = canonicalize(value)
        store.accept(value, now_ns=0)
        value["payload"]["data_base64"] = "eA=="
        self.assertEqual(store.abort_session(1)[0].requests, (original,))

    def terrain(self):
        return {"resource_id": "terrain-01", "origin": message(3)["payload"]["origin"],
                "rows": 2, "columns": 2, "spacing_n_m": 1, "spacing_e_m": 1,
                "height_datum": "ELLIPSOID", "heights_m": [1, 2, 3, 4],
                "nodata_policy": "REJECT_ROUTE_OUTSIDE_GRID"}

    def test_defined_resource_validator_uses_frozen_definitions(self):
        self.assertTrue(hasattr(self.contract, "validate_resource"), "resource definition validation missing")
        self.contract.validate_resource("TERRAIN", self.terrain())
        for kind in ("MODEL", "VIDEO", "OTHER", None, []):
            self.rejects("UNSUPPORTED", lambda: self.contract.validate_resource(kind, {}))
        value = self.terrain()
        value["unapproved"] = 1
        self.rejects("SCHEMA", lambda: self.contract.validate_resource("TERRAIN", value))

    def test_all_five_resource_kinds_preserve_actual_bytes(self):
        resources = {"MODEL": b"actual-model-binary", "VIDEO": b"actual-video-bytes",
                     "TERRAIN": canonicalize(self.terrain()),
                     "OBSTACLES": canonicalize({"revision": 1, "obstacles": []}),
                     "MISSION": canonicalize(message(20)["payload"])}
        store = self.store()
        for index, (kind, data) in enumerate(resources.items()):
            receipt = store.accept(chunk(data, kind=kind), now_ns=index)
            stored = store.resolve(receipt.resource_sha256, kind=kind)
            self.assertEqual(stored.path.read_bytes(), data)
            self.assertEqual(stored.content_status, "OPAQUE_BYTES" if kind in ("MODEL", "VIDEO") else "DEFINED_JSON")
        self.assertEqual(store.completed_count, 5)

    def test_terrain_grid_length_rejects_before_completion(self):
        store = self.store()
        terrain = self.terrain()
        terrain["heights_m"].append(5)
        self.rejects("RESOURCE", lambda: store.accept(chunk(canonicalize(terrain), kind="TERRAIN"), now_ns=0))
        self.assertEqual(store.completed_count, 0)
        self.assertEqual(store.drain_aborted()[0].error, "RESOURCE")

    def test_resource_json_is_strict_and_closed(self):
        invalid = [b'{"revision":1,"revision":2,"obstacles":[]}',
                   b'\xef\xbb\xbf{"revision":1,"obstacles":[]}',
                   b'{"revision":1,"obstacles":[],"extra":0}',
                   b'{"revision":NaN,"obstacles":[]}']
        for data in invalid:
            with self.subTest(data=data):
                store = self.store()
                self.rejects("SCHEMA", lambda: store.accept(chunk(data, kind="OBSTACLES"), now_ns=0))
                self.assertEqual(store.completed_count, 0)

    def test_duplicate_obstacle_ids_reject_before_completion(self):
        store = self.store()
        obstacle = {"obstacle_id": "obstacle-1", "center": message(20)["payload"]["landing_point"],
                    "geometry": "CYLINDER", "radius_m": 1, "width_m": 1, "length_m": 1,
                    "height_m": 1, "heading_rad": 0, "clearance_m": 1, "active": True}
        data = canonicalize({"revision": 1, "obstacles": [obstacle, obstacle]})
        self.rejects("RESOURCE", lambda: store.accept(chunk(data, kind="OBSTACLES"), now_ns=0))

    def test_mission_execute_index_rejects_before_completion(self):
        store = self.store()
        mission = message(20)["payload"]
        mission["execute_from_index"] = 1
        self.rejects("RESOURCE", lambda: store.accept(chunk(canonicalize(mission), kind="MISSION"), now_ns=0))

    def test_original_noncanonical_json_bytes_not_rewritten(self):
        store = self.store()
        data = b'{ "obstacles": [], "revision": 1 }\n'
        receipt = store.accept(chunk(data, kind="OBSTACLES"), now_ns=0)
        self.assertEqual(store.resolve(receipt.resource_sha256, kind="OBSTACLES").path.read_bytes(), data)

    def test_persisted_objects_reopen_with_actual_integrity_validation(self):
        from icd_gateway.resources import ResourceStore
        store = self.store()
        data = canonicalize(self.terrain())
        receipt = store.accept(chunk(data, kind="TERRAIN"), now_ns=0)
        root = store.root
        store.close()
        reopened = ResourceStore(self.contract, root, min_free_bytes=0)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.completed_count, 1)
        self.assertEqual(reopened.resolve(receipt.resource_sha256, kind="TERRAIN").path.read_bytes(), data)
        self.assertEqual(reopened.reserved_bytes, len(data))

    def test_resolve_detects_actual_file_tamper(self):
        store = self.store()
        receipt = store.accept(chunk(b"actual"), now_ns=0)
        resource = store.resolve(receipt.resource_sha256, kind="MODEL")
        resource.path.write_bytes(b"forged")
        self.rejects("HASH", lambda: store.resolve(receipt.resource_sha256, kind="MODEL"))

    def test_startup_detects_tamper_without_removing_objects(self):
        from icd_gateway.resources import ResourceStore
        store = self.store()
        receipt = store.accept(chunk(b"actual"), now_ns=0)
        resource = store.resolve(receipt.resource_sha256, kind="MODEL")
        root = store.root
        store.close()
        resource.path.write_bytes(b"forged")
        self.rejects("HASH", lambda: ResourceStore(self.contract, root, min_free_bytes=0))
        self.assertEqual(resource.path.read_bytes(), b"forged")
        self.assertFalse((root / ".lock").exists())

    def test_manifest_tamper_and_untrusted_types_fail_closed(self):
        from icd_gateway.resources import ResourceStore
        for field, value in (("size", True), ("kind", []), ("version", True), ("chunks", {})):
            with self.subTest(field=field):
                store = self.store()
                receipt = store.accept(chunk(b"actual"), now_ns=0)
                path = store.resolve(receipt.resource_sha256, kind="MODEL").path.parent / "metadata.json"
                from icd_runtime.json_codec import loads
                metadata = loads(path.read_bytes())
                metadata[field] = value
                path.write_bytes(canonicalize(metadata))
                root = store.root
                store.close()
                self.rejects("RESOURCE", lambda: ResourceStore(self.contract, root, min_free_bytes=0))

    def test_busy_and_stale_lock_are_not_deleted(self):
        from icd_gateway.resources import ResourceStore
        store = self.store()
        self.rejects("STATE", lambda: ResourceStore(self.contract, store.root, min_free_bytes=0))
        self.assertTrue((store.root / ".lock").exists())
        store.close()
        (store.root / ".lock").write_bytes(b"stale")
        self.rejects("STATE", lambda: ResourceStore(self.contract, store.root, min_free_bytes=0))
        self.assertEqual((store.root / ".lock").read_bytes(), b"stale")

    def test_abandoned_staging_requires_explicit_recovery(self):
        from icd_gateway.resources import ResourceStore
        store = self.store()
        root = store.root
        store.close()
        staging = root / "incoming" / "abandoned"
        staging.mkdir()
        (staging / "data.bin").write_bytes(b"keep")
        self.rejects("RESOURCE", lambda: ResourceStore(self.contract, root, min_free_bytes=0))
        self.assertEqual((staging / "data.bin").read_bytes(), b"keep")

    def test_completed_retry_cannot_change_chunk_boundaries_or_kind(self):
        store = self.store()
        data = b"abcdef"
        store.accept(chunk(data, 0, 3), now_ns=0)
        receipt = store.accept(chunk(data, 3), now_ns=1)
        self.assertEqual(store.accept(chunk(data, 0, 3), now_ns=2), receipt)
        self.rejects("DUPLICATE", lambda: store.accept(chunk(data, 0, 2), now_ns=3))
        self.rejects("RESOURCE", lambda: store.accept(chunk(data, kind="VIDEO"), now_ns=3))

    def test_abort_outbox_reserves_space_and_never_evicts(self):
        store = self.store(max_abort_records=1)
        value = chunk(b"abcdef", 0, 3)
        store.accept(value, now_ns=0)
        original = store.abort_session(1)
        self.rejects("BUFFER_FULL", lambda: store.accept(chunk(b"new"), now_ns=1))
        self.assertEqual(store.drain_aborted(), original)
        self.assertTrue(store.accept(chunk(b"new"), now_ns=1).complete)

    def test_evidence_capacity_rejects_before_writes_and_clock_change(self):
        first = chunk(b"abcdef", 0, 3)
        store = self.store(max_evidence_bytes=len(canonicalize(first)))
        store.accept(first, now_ns=0)
        self.rejects("BUFFER_FULL", lambda: store.accept(chunk(b"abcdef", 3), now_ns=100))
        self.assertEqual(store.accept(first, now_ns=1).stored_bytes, 3)
        self.assertEqual(store.active_count, 1)

    def test_staging_unexpected_nested_directory_is_never_deleted(self):
        store = self.store()
        value = chunk(b"abcdef", 0, 3)
        store.accept(value, now_ns=0)
        path = next((store.root / "incoming").iterdir()) / "data.bin"
        path.unlink()
        path.mkdir()
        sentinel = path / "unowned.txt"
        sentinel.write_bytes(b"keep")
        try:
            self.rejects("RESOURCE", lambda: store.abort_session(1))
            self.assertEqual(sentinel.read_bytes(), b"keep")
            self.assertEqual(store.active_count, 1)
        finally:
            if sentinel.exists():
                sentinel.unlink()
                path.rmdir()
            if path.parent.exists():
                path.write_bytes(b"abc")

    def test_unregistered_completed_destination_is_never_overwritten(self):
        store = self.store()
        value = chunk(b"new")
        destination = store.root / "objects" / value["payload"]["resource_sha256"]
        destination.mkdir()
        sentinel = destination / "unowned.txt"
        sentinel.write_bytes(b"keep")
        self.rejects("RESOURCE", lambda: store.accept(value, now_ns=0))
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(store.completed_count, 0)
        self.assertEqual(store.drain_aborted()[0].requests, (canonicalize(value),))

    def test_staging_byte_tamper_detected_by_final_full_hash(self):
        store = self.store()
        store.accept(chunk(b"abcdef", 0, 3), now_ns=0)
        path = next((store.root / "incoming").iterdir()) / "data.bin"
        path.write_bytes(b"xxx")
        self.rejects("HASH", lambda: store.accept(chunk(b"abcdef", 3), now_ns=1))
        self.assertEqual(store.completed_count, 0)
        self.assertEqual(store.active_count, 0)

    def test_metadata_size_limit_before_parse(self):
        store = self.store()
        receipt = store.accept(chunk(b"actual"), now_ns=0)
        path = store.resolve(receipt.resource_sha256, kind="MODEL").path.parent / "metadata.json"
        original = path.read_bytes()
        path.write_bytes(b" " * (2 * 1024**2 + 1))
        self.rejects("CAPACITY", lambda: store.resolve(receipt.resource_sha256, kind="MODEL"))
        path.write_bytes(original)

    def test_resolve_requires_exact_kind_and_actual_completed_hash(self):
        store = self.store()
        receipt = store.accept(chunk(b"actual"), now_ns=0)
        for kind in (None, [], "UNKNOWN"):
            self.rejects("UNSUPPORTED", lambda: store.resolve(receipt.resource_sha256, kind=kind))
        self.rejects("RESOURCE", lambda: store.resolve(receipt.resource_sha256, kind="VIDEO"))
        self.rejects("SCHEMA", lambda: store.resolve("../escape", kind="MODEL"))
        self.rejects("RESOURCE", lambda: store.resolve("0" * 64, kind="MODEL"))

    def test_bounded_constructor_rejects_noninteger_and_outside_limits(self):
        from icd_gateway.resources import ResourceStore
        with tempfile.TemporaryDirectory() as root:
            for name in ("max_resource_bytes", "max_total_bytes", "max_uploads", "max_objects",
                         "max_chunks", "max_abort_records", "max_evidence_bytes"):
                for value in (True, 0, 1.5, -1, 2**32):
                    with self.subTest(name=name, value=value):
                        self.rejects("CAPACITY", lambda: ResourceStore(self.contract, root, **{name: value}))
            for value in (True, -1, 1.5, 2**32):
                self.rejects("CAPACITY", lambda: ResourceStore(self.contract, root, min_free_bytes=value))
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_unknown_root_entries_are_never_removed(self):
        from icd_gateway.resources import ResourceStore
        with tempfile.TemporaryDirectory() as root:
            sentinel = Path(root) / "user-file.txt"
            sentinel.write_bytes(b"keep")
            self.rejects("RESOURCE", lambda: ResourceStore(self.contract, root, min_free_bytes=0))
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_staging_hard_link_cannot_modify_unowned_file(self):
        import os
        store = self.store()
        store.accept(chunk(b"abcdef", 0, 3), now_ns=0)
        path = next((store.root / "incoming").iterdir()) / "data.bin"
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "user-file.bin"
            target.write_bytes(b"abc")
            path.unlink()
            os.link(target, path)
            self.rejects("RESOURCE", lambda: store.accept(chunk(b"abcdef", 3), now_ns=1))
            self.assertEqual(target.read_bytes(), b"abc")
            store.abort_session(1)
            self.assertEqual(target.read_bytes(), b"abc")

    def test_invalid_storage_root_rejects_before_allocation(self):
        store = self.store()
        value = chunk(b"data")
        objects = store.root / "objects"
        objects.rmdir()
        objects.write_bytes(b"unowned")
        try:
            self.rejects("RESOURCE", lambda: store.accept(value, now_ns=0))
            self.assertEqual(objects.read_bytes(), b"unowned")
            self.assertEqual(store.active_count, 0)
        finally:
            objects.unlink()
            objects.mkdir()

    def test_file_creation_failure_aborts_with_original_request(self):
        from unittest.mock import patch
        store = self.store()
        value = chunk(b"data")
        original_open = Path.open

        def fail_data_creation(path, mode="r", *args, **kwargs):
            if path.name == "data.bin" and mode == "xb":
                raise PermissionError("injected file creation failure")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", fail_data_creation):
            self.rejects("RESOURCE", lambda: store.accept(value, now_ns=0))
        self.assertEqual(store.active_count, 0)
        self.assertEqual(store.drain_aborted()[0].requests, (canonicalize(value),))
        self.assertEqual(list((store.root / "incoming").iterdir()), [])

    def test_flush_failure_aborts_without_publishing_completion(self):
        from unittest.mock import patch
        store = self.store()
        value = chunk(b"data")
        with patch("icd_gateway.resources.os.fsync", side_effect=OSError("injected fsync failure")):
            self.rejects("RESOURCE", lambda: store.accept(value, now_ns=0))
        self.assertEqual(store.completed_count, 0)
        self.assertEqual(store.active_count, 0)
        self.assertEqual(store.drain_aborted()[0].requests, (canonicalize(value),))

    def test_metadata_disk_margin_checked_before_publication(self):
        import shutil
        from types import SimpleNamespace
        from unittest.mock import patch
        store = self.store()
        value = chunk(b"data")
        actual = shutil.disk_usage(store.root)
        with patch("icd_gateway.resources.shutil.disk_usage", side_effect=[actual, SimpleNamespace(free=0)]):
            self.rejects("CAPACITY", lambda: store.accept(value, now_ns=0))
        self.assertEqual(store.completed_count, 0)
        self.assertEqual(store.drain_aborted()[0].requests, (canonicalize(value),))

    def test_integral_json_numbers_preserve_integer_storage_offsets(self):
        store = self.store()
        first = chunk(b"abcdef", 0, 3)
        for key in ("size_bytes", "offset_bytes", "chunk_length"):
            first["payload"][key] = float(first["payload"][key])
        store.accept(first, now_ns=0)
        last = chunk(b"abcdef", 3)
        for key in ("size_bytes", "offset_bytes", "chunk_length"):
            last["payload"][key] = float(last["payload"][key])
        receipt = store.accept(last, now_ns=1)
        self.assertTrue(receipt.complete)
        self.assertIs(type(receipt.next_offset), int)
        self.assertIs(type(store.resolve(receipt.resource_sha256, kind="MODEL").size_bytes), int)
