import copy
import tempfile
import threading
import time

from common import GatewayTest, message
from test_resources import chunk as resource_chunk
from test_udp import available_port
from icd_runtime.json_codec import loads


def chunk(*args, **kwargs):
    kwargs.setdefault("kind", "VIDEO")
    return resource_chunk(*args, **kwargs)


class ResourceUDPTests(GatewayTest):
    def network(self, *, capacity=64, record_capacity=64):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from icd_gateway.resources import ResourceStore
        from icd_gateway.resource_worker import ResourceWorker
        from icd_gateway.receiver import Receiver
        from icd_gateway.udp import UDPGateway
        from input_simulator.udp_source import UDPSource
        endpoint = ("127.0.0.1", available_port())
        self.source = UDPSource(self.contract, source_bind=("127.0.0.1", 0),
                                feedback_bind=("127.0.0.1", 0), receiver_endpoint=endpoint, channel="ETH_0")
        self.addCleanup(self.source.close)
        self.binding = PeerBinding("ETH_0", "UDP", f"127.0.0.1:{self.source.source_endpoint[1]}")
        grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (self.binding,))
        self.registry = SessionRegistry(self.contract, [grant])
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = ResourceStore(self.contract, directory.name, min_free_bytes=0)
        self.worker = ResourceWorker(self.contract, self.registry, self.store, capacity=capacity)
        self.addCleanup(self.worker.close)
        self.assertIn("resource_worker", __import__("inspect").signature(Receiver).parameters,
                      "Receiver lacks the actual resource worker integration")
        self.receiver = Receiver(self.contract, self.registry, resource_worker=self.worker,
                                 resource_record_capacity=record_capacity)
        self.gateway = UDPGateway(self.receiver, bind=endpoint,
                                  feedback_routes={self.binding: self.source.feedback_endpoint}, channel="ETH_0")
        self.addCleanup(self.gateway.close)
        self.send(message(1))
        self.opened = self.source.receive_for(message(1), timeout=0.5)
        self.sid = self.opened["payload"]["session_id"]

    def send(self, request):
        packets = self.source.wire.encode(request, "UDP")
        failures = []
        def transmit():
            try:
                self.source.send(request)
            except Exception as exc:
                failures.append(exc)
        sender = threading.Thread(target=transmit)
        sender.start()
        for _ in packets:
            self.gateway.poll(timeout=0.02)
        sender.join(2)
        self.assertFalse(sender.is_alive())
        self.assertEqual(failures, [])

    def ready(self, count=1):
        deadline = time.monotonic() + 2
        while len(self.worker.peek_results()) < count and time.monotonic() < deadline:
            time.sleep(0.002)
        self.assertGreaterEqual(len(self.worker.peek_results()), count,
                                (self.receiver.admitted_count, self.receiver.error_details,
                                 self.receiver.assembler.reserved_bytes))

    def storage_reply(self, request):
        self.send(request)
        self.ready()
        self.gateway.poll(timeout=0)
        received = self.source.receive_for(request, timeout=0.5)
        self.assertEqual(received["payload"]["stage"], "RECEIVED")
        reply = self.source.receive_for(request, timeout=0.5)
        self.assertEqual(reply["message_id"], 141)
        return reply

    def test_actual_multichunk_udp_file_and_capabilities(self):
        self.network()
        capabilities = self.opened["payload"]["capabilities"]
        self.assertEqual(capabilities["implemented_message_ids"], [1, 34])
        self.assertFalse(capabilities["replacement_ready"])
        self.assertEqual(capabilities["available_probes"], [])
        data = bytes(range(256)) * 300
        for sequence, offset in enumerate(range(0, len(data), 32768), 2):
            value = chunk(data, offset, min(32768, len(data)-offset), sid=self.sid, sequence=sequence)
            reply = self.storage_reply(value)
            self.assertEqual(reply["payload"]["error"], "OK")
            self.assertEqual(reply["payload"]["next_offset"], offset + value["payload"]["chunk_length"])
            records = self.receiver.drain_resource_records()
            self.assertEqual(loads(records[0].outcome.request_bytes), value)
            self.assertEqual(loads(records[0].reply_bytes), reply)
        path = self.store.root / "objects" / reply["payload"]["resource_sha256"] / "data.bin"
        self.assertEqual(path.read_bytes(), data)
        self.assertTrue(reply["payload"]["complete"])

    def test_idle_feedback_and_terminal_duplicate_keep_original_result(self):
        self.network()
        value = chunk(b"actual", sid=self.sid, sequence=2)
        terminal = self.storage_reply(value)
        self.assertEqual(self.worker.pending_count, 0)
        self.send(value)
        self.assertEqual(self.source.receive_for(value, timeout=0.5)["payload"]["stage"], "RECEIVED")
        self.assertEqual(self.source.receive_for(value, timeout=0.5), terminal)
        self.assertEqual(len(self.receiver.drain_resource_records()), 1)
        self.assertEqual(self.receiver.drain_resource_records(), ())
        self.assertEqual(self.worker.pending_count, 0)

    def test_actual_chunk_hash_error_is_storage_not_application_failure(self):
        self.network()
        value = chunk(b"actual", sid=self.sid, sequence=2)
        value["payload"]["chunk_sha256"] = "0" * 64
        reply = self.storage_reply(value)
        self.assertEqual(reply["payload"]["error"], "HASH")
        self.assertFalse(reply["payload"]["complete"])
        self.assertEqual(self.store.completed_count, 0)

    def test_bounded_records_leave_original_worker_results_until_drain(self):
        self.network(record_capacity=1)
        first = chunk(b"first", sid=self.sid, sequence=2)
        self.storage_reply(first)
        second = chunk(b"second", sid=self.sid, sequence=3)
        self.send(second)
        self.ready()
        self.assertEqual(self.gateway.poll(timeout=0), 0)
        self.assertEqual(self.worker.pending_count, 1)
        self.assertEqual(loads(self.worker.peek_results()[0].request_bytes), second)
        self.receiver.drain_resource_records()
        self.assertGreater(self.gateway.poll(timeout=0), 0)
        self.assertEqual(self.source.receive_for(second, timeout=0.5)["payload"]["stage"], "RECEIVED")
        self.assertTrue(self.source.receive_for(second, timeout=0.5)["payload"]["complete"])

    def test_retired_result_retained_without_live_session_feedback(self):
        self.network()
        value = chunk(b"abcdef", 0, 3, sid=self.sid, sequence=2)
        self.send(value)
        self.ready()
        self.receiver.retire_session(self.sid)
        self.assertEqual(self.receiver.resource_feedback(now_ns=time.monotonic_ns()), ())
        records = self.receiver.drain_resource_records()
        self.assertEqual(loads(records[0].outcome.request_bytes), value)
        self.assertEqual(records[0].error, "STALE_SESSION")
        self.assertIsNone(records[0].reply_bytes)
        self.gateway.close()
        self.assertEqual(len(self.receiver.drain_shutdown().resource_shutdown.aborted_resources), 1)

    def test_capacity_failure_has_no_second_original_job(self):
        self.network(capacity=1, record_capacity=1)
        self.storage_reply(chunk(b"first", sid=self.sid, sequence=2))
        self.send(chunk(b"second", sid=self.sid, sequence=3))
        self.ready()
        third = chunk(b"third", sid=self.sid, sequence=4)
        self.send(third)
        received = self.source.receive_for(third, timeout=0.5)
        failed = self.source.receive_for(third, timeout=0.5)
        self.assertEqual(received["payload"]["stage"], "RECEIVED")
        self.assertEqual(failed["payload"]["error"], "BUFFER_FULL")
        self.assertEqual(self.worker.pending_count, 1)

    def test_changed_duplicate_never_creates_a_new_job(self):
        self.network()
        value = chunk(b"actual", sid=self.sid, sequence=2)
        self.storage_reply(value)
        changed = copy.deepcopy(value)
        changed["header"]["transaction_id"] += 1
        self.send(changed)
        reply = self.source.receive_for(changed, timeout=0.5)
        self.assertEqual(reply["payload"]["error"], "DUPLICATE")
        self.assertEqual(self.worker.pending_count, 0)

    def test_pending_duplicate_and_retire_do_not_block_on_actual_file_io(self):
        from icd_gateway.resources import ResourceStore
        from unittest.mock import patch
        self.network()
        entered, release = threading.Event(), threading.Event()
        original = ResourceStore.accept
        def blocked(store, request, **kwargs):
            receipt = original(store, request, **kwargs)
            entered.set()
            if not release.wait(2):
                raise AssertionError("test I/O gate not released")
            return receipt
        value = chunk(b"abcdef", 0, 3, sid=self.sid, sequence=2)
        with patch.object(ResourceStore, "accept", blocked):
            try:
                self.send(value)
                self.assertTrue(entered.wait(1))
                received = self.source.receive_for(value, timeout=0.5)
                self.send(value)
                self.assertEqual(self.source.receive_for(value, timeout=0.5), received)
                self.assertEqual(self.worker.pending_count, 1)
                self.receiver.retire_session(self.sid)
            finally:
                release.set()
            self.ready()
        self.assertEqual(self.receiver.resource_feedback(now_ns=time.monotonic_ns()), ())
        record = self.receiver.drain_resource_records()[0]
        self.assertEqual(loads(record.outcome.payload_bytes)["error"], "STALE_SESSION")
        self.assertEqual(loads(self.worker.drain_abort_records(timeout=2)[0].requests[0]), value)

    def test_model_and_terrain_do_not_bypass_missing_actual_state_gate(self):
        self.network()
        for sequence, kind in enumerate(("MODEL", "TERRAIN"), 2):
            value = chunk(b"actual", kind=kind, sid=self.sid, sequence=sequence)
            self.send(value)
            received = self.source.receive_for(value, timeout=0.5)
            self.assertEqual(received["payload"]["stage"], "RECEIVED")
            if self.worker.pending_count:
                self.ready()
                self.gateway.poll(timeout=0)
            failed = self.source.receive_for(value, timeout=0.5)
            self.assertEqual(failed["message_id"], 130, "restricted resources must not return storage completion")
            self.assertEqual(failed["payload"]["error"], "TARGET_MISSING")
        self.assertEqual(self.worker.pending_count, 0)
        self.assertEqual(self.store.completed_count, 0)
        self.assertEqual(self.store.active_count, 0)
