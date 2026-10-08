import importlib.util
from pathlib import Path
import tempfile
import threading
import time

from common import GatewayTest, message
from test_resources import chunk as resource_chunk
from icd_runtime.json_codec import loads


def chunk(*args, **kwargs):
    kwargs.setdefault("kind", "VIDEO")
    return resource_chunk(*args, **kwargs)


class ResourceWorkerTests(GatewayTest):
    def setup_worker(self, **limits):
        from icd_gateway.resources import ResourceStore
        from icd_gateway.resource_worker import ResourceWorker
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        self.binding = PeerBinding("ETH_0", "UDP", "127.0.0.1:36102")
        grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (self.binding,))
        self.registry = SessionRegistry(self.contract, [grant])
        self.sid = self.registry.accept(message(1), self.binding, now_ns=time.monotonic_ns()).session_id
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = ResourceStore(self.contract, directory.name, min_free_bytes=0)
        self.worker = ResourceWorker(self.contract, self.registry, self.store, **limits)
        self.addCleanup(self.worker.close)

    def submit(self, data=b"actual", sequence=2, **kwargs):
        value = chunk(data, sid=self.sid, sequence=sequence, **kwargs)
        now = time.monotonic_ns()
        self.registry.accept(value, self.binding, now_ns=now)
        self.worker.submit(value, self.binding, now_ns=now)
        return value

    def result(self):
        deadline = time.monotonic() + 2
        while not self.worker.peek_results() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(self.worker.peek_results(), "actual resource worker did not produce an outcome")
        return self.worker.peek_results()[0]

    def test_actual_background_worker_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.resource_worker"))

    def test_actual_background_file_and_original_outcome(self):
        self.setup_worker()
        original = self.submit()
        outcome = self.result()
        self.assertEqual(loads(outcome.request_bytes), original)
        payload = loads(outcome.payload_bytes)
        self.assertTrue(payload["complete"])
        self.assertEqual(payload["error"], "OK")
        path = self.store.root / "objects" / payload["resource_sha256"] / "data.bin"
        self.assertEqual(path.read_bytes(), b"actual")
        self.assertEqual(outcome.binding, self.binding)
        self.worker.release_result(outcome.key)
        self.assertEqual(self.worker.peek_results(), ())

    def test_result_capacity_is_reserved_until_released(self):
        self.setup_worker(capacity=1)
        self.submit()
        outcome = self.result()
        second = chunk(b"next", sid=self.sid, sequence=3)
        now = time.monotonic_ns()
        self.registry.accept(second, self.binding, now_ns=now)
        self.rejects("BUFFER_FULL", lambda: self.worker.submit(second, self.binding, now_ns=now))
        self.worker.release_result(outcome.key)
        self.worker.submit(second, self.binding, now_ns=time.monotonic_ns())
        self.assertTrue(loads(self.result().payload_bytes)["complete"])

    def test_original_request_cannot_be_claimed_twice(self):
        self.setup_worker()
        original = self.submit()
        self.rejects("DUPLICATE", lambda: self.worker.submit(original, self.binding, now_ns=time.monotonic_ns()))
        self.assertEqual(len(self.worker.peek_results()) or self.worker.pending_count, 1)

    def test_store_has_one_worker_lifetime_and_no_caller_file_io(self):
        from icd_gateway.resource_worker import ResourceWorker
        self.setup_worker()
        self.rejects("STATE", lambda: ResourceWorker(self.contract, self.registry, self.store))
        value = chunk(b"bypass", sid=self.sid)
        self.rejects("STATE", lambda: self.store.accept(value, now_ns=time.monotonic_ns()))
        self.worker.close()
        self.rejects("STATE", lambda: self.worker.submit(value, self.binding, now_ns=time.monotonic_ns()))

    def test_cancelled_session_cleans_actual_staging_and_keeps_originals(self):
        self.setup_worker()
        value = self.submit(b"abcdef", offset=0, length=3)
        outcome = self.result()
        self.assertFalse(loads(outcome.payload_bytes)["complete"])
        self.worker.release_result(outcome.key)
        self.registry.retire(self.sid)
        self.worker.synchronize_sessions((), now_ns=time.monotonic_ns())
        aborted = self.worker.drain_abort_records(timeout=2)
        self.assertEqual(len(aborted), 1)
        self.assertEqual(loads(aborted[0].requests[0]), value)
        self.assertEqual(list((self.store.root / "incoming").iterdir()), [])

    def test_original_message_byte_capacity_and_invalid_limits(self):
        from icd_gateway.resource_worker import ResourceWorker
        self.setup_worker(max_pending_bytes=1)
        value = chunk(b"actual", sid=self.sid, sequence=2)
        now = time.monotonic_ns()
        self.registry.accept(value, self.binding, now_ns=now)
        self.rejects("BUFFER_FULL", lambda: self.worker.submit(value, self.binding, now_ns=now))
        self.assertEqual(self.worker.pending_count, 0)

    def test_registry_retire_cancels_owned_upload_without_manual_worker_sync(self):
        self.setup_worker()
        value = self.submit(b"abcdef", offset=0, length=3)
        outcome = self.result()
        self.worker.release_result(outcome.key)
        self.registry.retire(self.sid)
        aborted = self.worker.drain_abort_records(timeout=2)
        self.assertEqual(len(aborted), 1)
        self.assertEqual(loads(aborted[0].requests[0]), value)

    def test_registry_close_waits_for_owned_worker_and_retains_shutdown(self):
        self.setup_worker()
        value = self.submit(b"abcdef", offset=0, length=3)
        self.result()
        self.registry.close()
        self.assertFalse(self.worker.available)
        self.assertFalse(self.worker._thread.is_alive())
        self.assertEqual(loads(self.registry.resource_shutdown.aborted_resources[0].requests[0]), value)

    def test_failed_thread_start_releases_owned_root_and_does_not_attach_worker(self):
        from icd_gateway.resources import ResourceStore
        from icd_gateway.resource_worker import ResourceWorker
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from unittest.mock import patch
        binding = PeerBinding("ETH_0", "UDP", "127.0.0.1:36102")
        grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (binding,))
        registry = SessionRegistry(self.contract, [grant])
        with tempfile.TemporaryDirectory() as root:
            store = ResourceStore(self.contract, root, min_free_bytes=0)
            with patch("icd_gateway.resource_worker.threading.Thread.start", side_effect=RuntimeError("injected start failure")):
                self.rejects("STATE", lambda: ResourceWorker(self.contract, registry, store))
            self.assertFalse((Path(root) / ".lock").exists())
            self.assertIsNone(registry._resource_worker)

    def test_timed_out_abort_drain_can_be_retried_without_losing_originals(self):
        from icd_gateway.resources import ResourceStore
        from unittest.mock import patch
        self.setup_worker()
        entered, release = threading.Event(), threading.Event()
        original = ResourceStore.accept
        def blocked(store, value, **kwargs):
            receipt = original(store, value, **kwargs)
            entered.set()
            if not release.wait(2):
                raise AssertionError("test I/O gate not released")
            return receipt
        with patch.object(ResourceStore, "accept", blocked):
            value = self.submit(b"abcdef", offset=0, length=3)
            try:
                self.assertTrue(entered.wait(1))
                self.registry.retire(self.sid)
                self.rejects("TIMEOUT", lambda: self.worker.drain_abort_records(timeout=0.01))
            finally:
                release.set()
            self.result()
            aborted = self.worker.drain_abort_records(timeout=2)
            self.assertEqual(loads(aborted[0].requests[0]), value)
            self.assertEqual(self.worker.drain_abort_records(timeout=2), ())

    def test_expired_nonfinal_write_aborts_only_its_owned_resource(self):
        from icd_gateway.resources import ResourceStore
        from unittest.mock import patch
        self.setup_worker()
        earlier = self.submit(b"different", offset=0, length=3)
        first = self.result()
        self.worker.release_result(first.key)
        entered, release = threading.Event(), threading.Event()
        original = ResourceStore.accept
        def blocked(store, value, **kwargs):
            receipt = original(store, value, **kwargs)
            entered.set()
            if not release.wait(2):
                raise AssertionError("test I/O gate not released")
            return receipt
        with patch.object(ResourceStore, "accept", blocked):
            value = self.submit(b"abcdef", sequence=3, offset=0, length=3)
            try:
                self.assertTrue(entered.wait(1))
                time.sleep(1.02)
            finally:
                release.set()
            outcome = self.result()
        self.assertEqual(loads(outcome.payload_bytes)["error"], "TIMEOUT")
        self.assertEqual(loads(outcome.payload_bytes)["stored_bytes"], 0)
        aborted = self.worker.drain_abort_records(timeout=2)
        self.assertEqual(len(aborted), 1)
        self.assertEqual(loads(aborted[0].requests[0]), value)
        self.assertEqual(self.store.active_count, 1, "must not abort the other resource in this session")
        self.registry.retire(self.sid)
        self.assertEqual(loads(self.worker.drain_abort_records(timeout=2)[0].requests[0]), earlier)

    def test_cleanup_failure_shutdown_preserves_aborted_and_unfinished_originals(self):
        self.setup_worker()
        first = self.submit(b"abcdef", offset=0, length=3)
        outcome = self.result()
        self.worker.release_result(outcome.key)
        self.registry.retire(self.sid)
        deadline = time.monotonic() + 1
        while self.store.active_count and time.monotonic() < deadline:
            time.sleep(0.002)
        self.assertEqual(self.store.active_count, 0)
        opening = message(1)
        opening["payload"]["nonce_hex"] = "e" * 32
        self.sid = self.registry.accept(opening, self.binding, now_ns=time.monotonic_ns()).session_id
        second = self.submit(b"different", sequence=2, offset=0, length=3)
        self.worker.release_result(self.result().key)
        directory = next((self.store.root / "incoming").iterdir())
        (directory / "unexpected").mkdir()
        shutdown = self.worker.close()
        self.assertEqual(shutdown.error, "RESOURCE")
        self.assertEqual(len(shutdown.aborted_resources), 1, "cleanup failure must not hide earlier abort records")
        self.assertEqual(loads(shutdown.aborted_resources[0].requests[0]), first)
        self.assertEqual(loads(shutdown.unfinished_resources[0].requests[0]), second)
        self.assertTrue((self.store.root / ".lock").exists())
        self.assertTrue((directory / "unexpected").exists())

    def test_foreign_expired_same_hash_job_does_not_kill_worker_or_abort_owner(self):
        from icd_gateway.resources import ResourceStore
        from unittest.mock import patch
        self.setup_worker()
        owner = self.submit(b"abcdef", offset=0, length=3)
        self.worker.release_result(self.result().key)
        opening = message(1)
        opening["payload"]["nonce_hex"] = "f" * 32
        foreign_sid = self.registry.accept(opening, self.binding, now_ns=time.monotonic_ns()).session_id
        entered, release = threading.Event(), threading.Event()
        original = ResourceStore.accept
        def blocked(store, value, **kwargs):
            receipt = original(store, value, **kwargs)
            entered.set()
            if not release.wait(2):
                raise AssertionError("test I/O gate not released")
            return receipt
        with patch.object(ResourceStore, "accept", blocked):
            try:
                self.submit(b"blocker", sequence=3)
                self.assertTrue(entered.wait(1))
                foreign = chunk(b"abcdef", offset=3, length=3, sid=foreign_sid, sequence=2)
                now = time.monotonic_ns()
                self.registry.accept(foreign, self.binding, now_ns=now)
                self.worker.submit(foreign, self.binding, now_ns=now)
                time.sleep(1.02)
            finally:
                release.set()
            deadline = time.monotonic() + 1
            while len(self.worker.peek_results()) < 2 and time.monotonic() < deadline:
                time.sleep(0.002)
        self.assertTrue(self.worker.available, "foreign stale job must not terminate other owners' storage service")
        self.assertEqual(self.store.active_count, 1)
        stale = next(r for r in self.worker.peek_results() if loads(r.request_bytes) == foreign)
        self.assertEqual(loads(stale.payload_bytes)["error"], "EXPIRED")
        self.registry.retire(self.sid)
        self.assertEqual(loads(self.worker.drain_abort_records(timeout=2)[0].requests[0]), owner)

    def test_future_wire_budget_rejection_never_claims_or_mutates_original(self):
        from icd_runtime.resource_budget import ResourceBudget
        self.setup_worker()
        self.worker._budget = ResourceBudget(self.contract, bits_per_second=1)
        value = chunk(b"actual", sid=self.sid, sequence=2)
        now = time.monotonic_ns()
        self.registry.accept(value, self.binding, now_ns=now)
        self.rejects("CAPACITY", lambda: self.worker.submit(value, self.binding, now_ns=now))
        self.assertEqual(self.registry.require_admitted(value, now_ns=now), now)
        self.assertEqual(self.worker.pending_count, 0)
        self.assertEqual(self.worker._budget._next_ns, 0)
        self.assertEqual(self.worker._last_now, -1)
        self.assertEqual(list((self.store.root / "incoming").iterdir()), [])

    def test_invalid_worker_limits_are_rejected_before_lifetime_claim(self):
        from icd_gateway.resource_worker import ResourceWorker
        self.setup_worker()
        for limits in ({"capacity": True}, {"capacity": 0}, {"capacity": 65},
                       {"max_pending_bytes": True}, {"max_pending_bytes": 0},
                       {"max_pending_bytes": 4194305}):
            self.rejects("CAPACITY", lambda: ResourceWorker(self.contract, self.registry, self.store, **limits))
        self.assertTrue(self.worker.available)

    def test_restricted_resource_submit_requires_actual_model_state_before_claim(self):
        self.setup_worker()
        for sequence, kind in enumerate(("MODEL", "TERRAIN"), 2):
            value = chunk(b"actual", kind=kind, sid=self.sid, sequence=sequence)
            now = time.monotonic_ns()
            self.registry.accept(value, self.binding, now_ns=now)
            self.rejects("TARGET_MISSING", lambda: self.worker.submit(value, self.binding, now_ns=now))
            self.assertEqual(self.registry.require_admitted(value, now_ns=now), now)
        self.assertEqual(self.worker.pending_count, 0)
        self.assertEqual(self.store.completed_count, 0)
        self.assertEqual(self.store.active_count, 0)


class ResourceBudgetTests(GatewayTest):
    def test_background_wire_budget_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_runtime.resource_budget"))

    def test_actual_udp_overhead_and_no_burst_reservations(self):
        from icd_runtime.resource_budget import ResourceBudget
        budget = ResourceBudget(self.contract)
        packets = (b"x" * 1200, b"x" * 40)
        bits = ((1200 + 66) + (40 + 66)) * 8
        self.assertEqual(budget.wire_bits(packets), bits)
        first = budget.preview(packets, now_ns=0)
        self.assertEqual(first, (bits * 1_000_000_000 + 19_999_999) // 20_000_000)
        budget.reserve(packets, now_ns=0)
        self.assertEqual(budget.preview(packets, now_ns=0), 2 * first)
        self.rejects("SCHEMA", lambda: budget.preview(packets, now_ns=-1))

    def test_background_rate_cannot_exceed_frozen_policy(self):
        from icd_runtime.resource_budget import ResourceBudget
        for value in (True, 0, -1, 20_000_001, 1.5):
            self.rejects("CAPACITY", lambda: ResourceBudget(self.contract, bits_per_second=value))
