import importlib.util
import socket
import threading
import time

from common import GatewayTest, message


def available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class UDPTests(GatewayTest):
    def create_network(self, ports=(0, 0, 0)):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from icd_gateway.receiver import Receiver
        from icd_gateway.udp import UDPGateway
        from input_simulator.udp_source import UDPSource
        endpoint = ("127.0.0.1", ports[0] or available_port())
        self.source = UDPSource(self.contract, source_bind=("127.0.0.1", ports[1]),
                                feedback_bind=("127.0.0.1", ports[2]), receiver_endpoint=endpoint, channel="ETH_0")
        self.addCleanup(self.source.close)
        binding = PeerBinding("ETH_0", "UDP", f"127.0.0.1:{self.source.source_endpoint[1]}")
        grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (binding,))
        self.registry = SessionRegistry(self.contract, [grant])
        self.receiver = Receiver(self.contract, self.registry)
        self.gateway = UDPGateway(self.receiver, bind=endpoint,
                                  feedback_routes={binding: self.source.feedback_endpoint}, channel="ETH_0")
        self.addCleanup(self.gateway.close)

    def roundtrip(self, request):
        count = self.source.send(request)
        for _ in range(count):
            self.gateway.poll(timeout=0.1)
        return self.source.receive_for(request, timeout=0.5)

    def test_common_udp_and_source_packages_exist(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.udp"), "actual common UDP service missing")
        self.assertIsNotNone(importlib.util.find_spec("input_simulator"), "independent source missing")

    def test_storage_library_does_not_enable_wire_resource_consumer(self):
        from test_resources import chunk
        self.create_network()
        opening = self.roundtrip(message(1))
        self.assertEqual(opening["payload"]["capabilities"]["implemented_message_ids"], [1])
        value = chunk(b"actual-resource-bytes", sid=opening["payload"]["session_id"], sequence=2)
        received = self.roundtrip(value)
        failed = self.source.receive_for(value, timeout=0.5)
        self.assertEqual(received["message_id"], 130)
        self.assertEqual(received["payload"]["stage"], "RECEIVED")
        self.assertEqual(failed["payload"]["stage"], "FAILED")
        self.assertEqual(failed["payload"]["error"], "TARGET_MISSING")
        self.assertEqual(failed["payload"]["probe_id"], 0)

    def test_actual_socket_open_fragmented_input_and_cached_failure_feedback(self):
        self.create_network()
        opening = message(1)
        reply = self.roundtrip(opening)
        self.assertEqual(reply["message_id"], 129)
        self.assertEqual(self.roundtrip(opening), reply)
        value = message(3)
        value["header"].update(session_id=reply["payload"]["session_id"], sequence=2, transaction_id=20)
        received = self.roundtrip(value)
        failed = self.source.receive_for(value, timeout=0.5)
        self.assertEqual(received["payload"]["stage"], "RECEIVED")
        self.assertEqual(failed["payload"]["error"], "TARGET_MISSING")
        self.assertEqual(self.roundtrip(value), received)
        self.assertEqual(self.source.receive_for(value, timeout=0.5), failed)
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)

    def test_actual_wire_cleanup_remains_failure_until_all_real_consumers_exist(self):
        self.create_network()
        opening = self.roundtrip(message(1))
        self.assertEqual(opening["payload"]["capabilities"]["implemented_message_ids"], [1])
        sid = opening["payload"]["session_id"]
        for mid in (37, 38):
            value = message(mid)
            value["header"].update(session_id=sid, sequence=mid, transaction_id=mid)
            received = self.roundtrip(value)
            terminal = self.source.receive_for(value, timeout=0.5)
            self.assertEqual(received["payload"]["stage"], "RECEIVED")
            self.assertEqual(terminal["payload"]["stage"], "FAILED")
            self.assertEqual(terminal["payload"]["error"], "TARGET_MISSING" if mid == 37 else "UNSUPPORTED")
            self.assertEqual(terminal["payload"]["probe_id"], 0)
            self.assertIn(sid, self.registry.session_ids)
            self.assertEqual(self.roundtrip(value), received)
            self.assertEqual(self.source.receive_for(value, timeout=0.5), terminal)

    def test_actual_udp_idle_poll_releases_owned_queue_without_model_execution(self):
        self.create_network()
        opening = self.roundtrip(message(1))
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        from icd_gateway.session import PeerBinding
        from test_model_bindings import declared_runtime
        mapping = ModelBindings(self.contract, "quadrotor_hil", declared_runtime(self.contract, "quadrotor_hil"))
        queue = ModelQueue(self.contract, self.registry, [mapping])
        value = message(10)
        value["header"].update(session_id=opening["payload"]["session_id"], sequence=2, target_step=5)
        binding = PeerBinding("ETH_0", "UDP", f"127.0.0.1:{self.source.source_endpoint[1]}")
        now = time.monotonic_ns()
        self.registry.accept(value, binding, now_ns=now)
        pending = queue.enqueue(value, state="RUNNING", now_ns=now)
        self.assertEqual(queue.count, 1)
        time.sleep(1.05)
        self.gateway.poll(timeout=0)
        self.assertEqual(self.registry.active_count, 0)
        self.assertEqual(queue.count, 0)
        self.assertEqual(queue.stored_bytes, 0)
        maintenance = self.receiver.drain_maintenance()
        self.assertEqual([(r.pending, r.error) for r in maintenance.rejected_inputs], [(pending, "STALE_SESSION")])

    def test_udp_close_preserves_receiver_shutdown_records_after_socket_release(self):
        self.create_network()
        opened = self.roundtrip(message(1))
        sid = opened["payload"]["session_id"]
        self.assertEqual(self.gateway.close(), ())
        self.assertEqual(self.gateway.socket.fileno(), -1)
        self.assertEqual(self.receiver.drain_shutdown().closed_sessions, (sid,))
        self.assertEqual(self.gateway.close(), ())

    def test_reverse_acl_and_transaction_filter_ignore_foreign_feedback(self):
        self.create_network()
        opening = message(1)
        self.source.send(opening)
        from icd_runtime.wire import WireCodec
        bad = message(130)
        bad["header"].update(session_id=0, sequence=1, transaction_id=1)
        bad["payload"].update(request_message_id=1, stage="FAILED", error="SCHEMA")
        packet = WireCodec(self.contract).encode(bad, "UDP")[0]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as foreign:
            foreign.bind(("127.0.0.1", 0))
            foreign.sendto(packet, self.source.feedback_endpoint)
        bad["header"]["transaction_id"] = 999
        self.gateway.socket.sendto(WireCodec(self.contract).encode(bad, "UDP")[0], self.source.feedback_endpoint)
        self.gateway.poll(timeout=0.1)
        reply = self.source.receive_for(opening, timeout=0.5)
        self.assertEqual(reply["message_id"], 129)
        self.assertEqual(self.source.dropped_feedback, 2)

    def test_forward_acl_bad_crc_and_oversize_do_not_allocate(self):
        self.create_network()
        from icd_runtime.wire import WireCodec
        packet = WireCodec(self.contract).encode(message(1), "UDP")[0]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as foreign:
            foreign.sendto(packet, self.gateway.address)
        self.gateway.poll(timeout=0.1)
        self.source.socket.sendto(bytes(1201), self.gateway.address)
        self.gateway.poll(timeout=0.1)
        self.source.socket.sendto(packet[:-1] + bytes([packet[-1] ^ 1]), self.gateway.address)
        self.gateway.poll(timeout=0.1)
        self.assertEqual(self.registry.active_count, 0)
        self.assertEqual(self.receiver.assembler.pending_count, 0)
        self.assertGreaterEqual(sum(self.receiver.errors.values()), 3)

    def test_source_request_waits_for_terminal_and_gateway_idle_expires_session(self):
        self.create_network()
        stop = threading.Event()
        errors = []
        def run():
            try:
                while not stop.is_set():
                    self.gateway.poll(timeout=0.02)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            opening = self.source.request(message(1))
            value = message(10)
            value["header"].update(session_id=opening["payload"]["session_id"], sequence=2)
            terminal = self.source.request(value)
            self.assertEqual(terminal["payload"]["stage"], "FAILED")
            self.assertEqual(terminal["payload"]["error"], "TARGET_MISSING")
            time.sleep(1.1)
        finally:
            stop.set()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.registry.active_count, 0)
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)

    def test_feedback_sequence_reuse_for_a_different_reply_is_rejected(self):
        self.create_network()
        opening = self.roundtrip(message(1))
        value = message(10)
        value["header"].update(session_id=opening["payload"]["session_id"], sequence=2, transaction_id=2)
        forged = message(130)
        forged["header"].update(session_id=value["header"]["session_id"], sequence=1, transaction_id=2)
        forged["payload"].update(request_sequence=2, request_message_id=10, stage="FAILED", error="DUPLICATE")
        from icd_runtime.wire import WireCodec
        self.gateway.socket.sendto(WireCodec(self.contract).encode(forged, "UDP")[0], self.source.feedback_endpoint)
        reply = self.roundtrip(value)
        self.assertEqual(reply["payload"]["stage"], "RECEIVED")
        self.assertEqual(self.source.receive_for(value, timeout=0.5)["payload"]["error"], "TARGET_MISSING")
        self.assertEqual(self.source.dropped_feedback, 1)

    def test_defined_port_roles_36100_36101_36102_use_actual_sockets(self):
        self.create_network(ports=(36100, 36102, 36101))
        self.assertEqual(self.gateway.address, ("127.0.0.1", 36100))
        self.assertEqual(self.source.source_endpoint, ("127.0.0.1", 36102))
        self.assertEqual(self.source.feedback_endpoint, ("127.0.0.1", 36101))
        self.assertEqual(self.roundtrip(message(1))["message_id"], 129)

    def test_reliable_retries_are_identical_and_periodic_control_is_not_retried(self):
        self.create_network()
        opening = message(1)
        self.rejects("TIMEOUT", lambda: self.source.request(opening))
        self.gateway.socket.settimeout(0.1)
        packets = [self.gateway.socket.recvfrom(1201)[0] for _ in range(4)]
        self.assertTrue(all(packet == packets[0] for packet in packets))
        control = message(7)
        self.rejects("TIMEOUT", lambda: self.source.request(control))
        self.assertEqual(self.gateway.socket.recvfrom(1201)[0], self.source.wire.encode(control, "UDP")[0])
        with self.assertRaises(socket.timeout):
            self.gateway.socket.recvfrom(1201)

    def test_feedback_cache_expiry_cannot_rollback_highwater(self):
        self.create_network()
        reply = message(130)
        self.source._check_feedback_sequence(reply, 0)
        self.source._check_feedback_sequence(reply, 1)
        self.rejects("OUT_OF_ORDER", lambda: self.source._check_feedback_sequence(reply, 5_000_000_000))

    def test_source_tracking_capacity_is_explicit_not_misreported_as_timeout(self):
        self.create_network()
        opening = message(1)
        self.source.send(opening)
        self.gateway.poll(timeout=0.1)
        assigned = self.registry.session_ids[0]
        tracked = [sid for sid in range(1, 66) if sid != assigned][:64]
        for sid in tracked:
            reply = message(130)
            reply["header"]["session_id"] = sid
            self.source._check_feedback_sequence(reply, 0)
        self.rejects("BUFFER_FULL", lambda: self.source.receive_for(opening, timeout=0.1))
