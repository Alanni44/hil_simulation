import copy
import hashlib
import socket
import time

from common import GatewayTest, message
from test_resources import chunk
from icd_runtime.errors import ICDError


class ResourceExchangeTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        self.binding = PeerBinding("ETH_0", "UDP", "127.0.0.1:36102")
        grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (self.binding,))
        self.registry = SessionRegistry(self.contract, [grant])
        self.sid = self.registry.accept(message(1), self.binding, now_ns=0).session_id
        self.request = chunk(b"actual", sid=self.sid, sequence=2)
        self.registry.accept(self.request, self.binding, now_ns=0)

    def received(self, request=None):
        request = request or self.request
        reply = message(130)
        reply["header"].update(session_id=self.sid, sequence=1,
                               transaction_id=request["header"]["transaction_id"])
        reply["payload"].update(request_sequence=request["header"]["sequence"], request_message_id=34,
                                stage="RECEIVED", error="OK", applied_step=0, model_revision=0, probe_id=0)
        return reply

    def resource_ack(self, request=None, *, error="OK"):
        request = request or self.request
        reply = message(141)
        reply["header"].update(session_id=self.sid, sequence=2,
                               transaction_id=request["header"]["transaction_id"])
        size = request["payload"]["size_bytes"]
        reply["payload"].update(resource_sha256=request["payload"]["resource_sha256"],
                                next_offset=size if error == "OK" else 0,
                                stored_bytes=size if error == "OK" else 0,
                                complete=error == "OK", error=error)
        return reply

    def defer(self):
        self.registry.claim_admitted(self.request, now_ns=0)
        self.registry.defer_resource_response(self.request, (self.received(),), now_ns=0)

    def test_resource_specific_pending_api_exists(self):
        self.assertTrue(hasattr(self.registry, "defer_resource_response"), "pending resource stages missing")
        self.assertTrue(hasattr(self.registry, "finish_resource_response"))

    def test_pending_duplicate_and_real_terminal_append_are_immutable(self):
        self.defer()
        self.assertEqual(self.registry.accept(self.request, self.binding, now_ns=1).replay, (self.received(),))
        ack = self.resource_ack()
        self.registry.finish_resource_response(self.request, ack, now_ns=2)
        ack["payload"]["resource_sha256"] = "0" * 64
        self.assertEqual(self.registry.accept(self.request, self.binding, now_ns=3).replay,
                         (self.received(), self.resource_ack()))
        self.rejects("STATE", lambda: self.registry.finish_resource_response(self.request, self.resource_ack(), now_ns=3))

    def test_wrong_resource_id_hash_session_transaction_and_progress_rejected(self):
        self.defer()
        variants = []
        for section, field, value in (("payload", "resource_sha256", "0" * 64),
                                       ("header", "session_id", self.sid + 1),
                                       ("header", "transaction_id", 123),
                                       ("payload", "stored_bytes", 5),
                                       ("payload", "next_offset", 7),
                                       ("payload", "complete", False)):
            reply = self.resource_ack()
            reply[section][field] = value
            variants.append(reply)
        variants.append(self.received())
        for reply in variants:
            self.rejects("STATE", lambda: self.registry.finish_resource_response(self.request, reply, now_ns=1))
        self.registry.finish_resource_response(self.request, self.resource_ack(error="HASH"), now_ns=2)

    def test_only_claimed_resource_received_prefix_can_be_deferred(self):
        self.rejects("STATE", lambda: self.registry.defer_resource_response(self.request, (self.received(),), now_ns=0))
        self.registry.claim_admitted(self.request, now_ns=0)
        bad = self.received()
        bad["payload"].update(stage="FAILED", error="RESOURCE")
        self.rejects("STATE", lambda: self.registry.defer_resource_response(self.request, (bad,), now_ns=0))
        self.registry.defer_resource_response(self.request, (self.received(),), now_ns=0)
        self.rejects("STATE", lambda: self.registry.defer_resource_response(self.request, (self.received(),), now_ns=0))

    def test_ordinary_terminal_feedback_stays_immutable(self):
        self.registry.record_response(self.request, (self.resource_ack(),), now_ns=0)
        self.rejects("STATE", lambda: self.registry.finish_resource_response(self.request, self.resource_ack(), now_ns=1))
        self.rejects("STATE", lambda: self.registry.record_response(self.request, (self.resource_ack(),), now_ns=1))

    def renew_until(self, end, start_sequence=3):
        for index, now in enumerate(range(900_000_000, end + 1, 900_000_000), start_sequence):
            heartbeat = message(2)
            heartbeat["header"].update(session_id=self.sid, sequence=index, transaction_id=index)
            self.registry.accept(heartbeat, self.binding, now_ns=now)

    def test_final_pin_preserves_actual_prefix_after_five_seconds(self):
        self.defer()
        self.renew_until(6_300_000_000)
        self.assertEqual(self.registry.accept(self.request, self.binding, now_ns=6_300_000_001).replay, (self.received(),))
        self.registry.finish_resource_response(self.request, self.resource_ack(), now_ns=6_300_000_002)
        self.assertEqual(self.registry.accept(self.request, self.binding, now_ns=6_300_000_003).replay,
                         (self.received(), self.resource_ack()))

    def test_pin_never_renews_session_or_allows_success_after_timeout(self):
        self.defer()
        self.rejects("STALE_SESSION", lambda: self.registry.accept(self.request, self.binding, now_ns=1_000_000_000))

    def test_final_pin_is_removed_at_ten_seconds_under_fresh_heartbeats(self):
        self.defer()
        self.renew_until(9_900_000_000)
        self.registry.expire(now_ns=10_000_000_000)
        self.rejects("OUT_OF_ORDER", lambda: self.registry.accept(self.request, self.binding, now_ns=10_000_000_000))
        self.rejects("STATE", lambda: self.registry.finish_resource_response(self.request, self.resource_ack(), now_ns=10_000_000_000))

    def test_direct_terminal_resource_ack_cannot_name_another_request(self):
        reply = self.resource_ack()
        reply["payload"]["resource_sha256"] = "0" * 64
        self.rejects("STATE", lambda: self.registry.record_response(self.request, (reply,), now_ns=0))

    def test_nonfinal_pin_never_allows_success_after_one_second(self):
        value = chunk(b"abcdef", offset=0, length=3, sid=self.sid, sequence=3)
        self.registry.accept(value, self.binding, now_ns=0)
        self.registry.claim_admitted(value, now_ns=0)
        self.registry.defer_resource_response(value, (self.received(value),), now_ns=0)
        self.renew_until(900_000_000, start_sequence=4)
        good = self.resource_ack(value)
        self.rejects("TIMEOUT", lambda: self.registry.finish_resource_response(value, good, now_ns=1_000_000_000))
        bad = self.resource_ack(value, error="TIMEOUT")
        self.registry.finish_resource_response(value, bad, now_ns=1_000_000_001)
        self.assertEqual(self.registry.accept(value, self.binding, now_ns=1_000_000_002).replay,
                         (self.received(value), bad))

    def test_deferral_capacity_preflight_never_claims_the_65th_original(self):
        for seq in range(2, 66):
            value = self.request if seq == 2 else chunk(b"actual", sid=self.sid, sequence=seq)
            if seq != 2:
                self.registry.accept(value, self.binding, now_ns=0)
            self.registry.claim_admitted(value, now_ns=0)
            self.registry.defer_resource_response(value, (self.received(value),), now_ns=0)
        overflow = chunk(b"actual", sid=self.sid, sequence=66)
        self.registry.accept(overflow, self.binding, now_ns=0)
        self.rejects("BUFFER_FULL", lambda: self.registry.check_resource_deferral(overflow, self.received(overflow), now_ns=0))
        self.assertEqual(self.registry.require_admitted(overflow, now_ns=0), 0)

    def test_malformed_deferred_feedback_is_schema_error_not_python_exception(self):
        self.registry.claim_admitted(self.request, now_ns=0)
        for replies in ((None,), ({"message_id": 130, "payload": None},)):
            self.rejects("SCHEMA", lambda: self.registry.defer_resource_response(self.request, replies, now_ns=0))
        self.registry.defer_resource_response(self.request, (self.received(),), now_ns=0)


class ResourceSourceTests(GatewayTest):
    def network(self):
        from input_simulator.udp_source import UDPSource
        self.peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.peer.bind(("127.0.0.1", 0))
        self.addCleanup(self.peer.close)
        self.source = UDPSource(self.contract, source_bind=("127.0.0.1", 0),
                                feedback_bind=("127.0.0.1", 0), receiver_endpoint=self.peer.getsockname(), channel="ETH_0")
        self.addCleanup(self.source.close)
        self.request = chunk(b"actual", sid=10, sequence=2)

    def reply(self):
        value = message(141)
        value["header"].update(session_id=10, sequence=1, transaction_id=2)
        value["payload"].update(resource_sha256=hashlib.sha256(b"actual").hexdigest(),
                                next_offset=6, stored_bytes=6, complete=True, error="OK")
        return value

    def send_reply(self, reply):
        for packet in self.source.wire.encode(reply, "UDP"):
            self.peer.sendto(packet, self.source.feedback_endpoint)

    def test_actual_source_accepts_only_matching_resource_ack(self):
        self.network()
        bad = self.reply()
        bad["payload"]["resource_sha256"] = "0" * 64
        self.send_reply(bad)
        good = self.reply()
        good["header"]["sequence"] = 2
        self.send_reply(good)
        self.assertEqual(self.source.receive_for(self.request, timeout=0.1), good)
        self.assertEqual(self.source.dropped_feedback, 1)

    def test_inconsistent_progress_is_dropped_before_feedback_high_water(self):
        self.network()
        bad = self.reply()
        bad["payload"]["stored_bytes"] = 5
        self.send_reply(bad)
        good = self.reply()
        self.send_reply(good)
        self.assertEqual(self.source.receive_for(self.request, timeout=0.1), good)
        self.assertEqual(self.source.dropped_feedback, 1)

    def test_resource_error_can_report_zero_remaining_stored_bytes(self):
        self.network()
        reply = self.reply()
        reply["payload"].update(next_offset=0, stored_bytes=0, complete=False, error="HASH")
        self.send_reply(reply)
        self.assertEqual(self.source.receive_for(self.request, timeout=0.1), reply)
