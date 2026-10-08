import dataclasses
import importlib.util

from common import GatewayTest, message


class AvailabilityTests(GatewayTest):
    def test_common_gateway_package_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway"), "common W2 session package missing")


class SessionTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        self.link = PeerBinding("ETH_0", "UDP", "127.0.0.1:36102")
        self.other = PeerBinding("CANFD_0", "CANFD", "test-peer-not-qualified-hardware")
        self.grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (self.link, self.other))
        self.registry = SessionRegistry(self.contract, [self.grant])
        self.opening = message(1)

    def open(self, now=0):
        return self.registry.accept(self.opening, self.link, now_ns=now).session_id

    def value(self, mid, sid, sequence=2):
        value = message(mid)
        value["header"].update(session_id=sid, sequence=sequence, transaction_id=sequence)
        return value

    def feedback(self, request):
        reply = message(130)
        reply["header"].update(session_id=request["header"]["session_id"],
                               transaction_id=request["header"]["transaction_id"], sequence=1)
        reply["payload"].update(request_sequence=request["header"]["sequence"],
                                request_message_id=request["message_id"], stage="FAILED", error="TARGET_MISSING")
        return reply

    def test_open_requires_exact_identity_and_granted_roles(self):
        for key in self.opening["payload"]["identity"]:
            bad = message(1)
            bad["payload"]["identity"][key] = "foreign" if key != "model_id" else "fixed_wing_hil"
            code = "SCHEMA" if key == "definition_version" else "AUTHORIZATION"
            self.rejects(code, lambda: self.registry.accept(bad, self.link, now_ns=0))
        bad = message(1)
        bad["payload"]["roles"] = ["CONTROLLER"]
        self.rejects("AUTHORIZATION", lambda: self.registry.accept(bad, self.link, now_ns=0))
        self.assertEqual(self.registry.active_count, 0)

    def test_unregistered_link_and_role_rejected_before_fragment_allocation(self):
        from icd_gateway.session import PeerBinding
        unknown = dataclasses.replace(self.link, peer="127.0.0.1:40000")
        self.rejects("AUTHORIZATION", lambda: self.registry.preauthorize(1, 0, unknown, now_ns=0))
        sid = self.open()
        self.rejects("AUTHORIZATION", lambda: self.registry.preauthorize(7, sid, self.link, now_ns=0))
        self.rejects("AUTHORIZATION", lambda: self.registry.preauthorize(2, sid, PeerBinding("ETH_1", "UDP", self.link.peer), now_ns=0))

    def test_fixed_lease_and_only_fresh_heartbeat_renewal(self):
        sid = self.open()
        self.registry.accept(self.value(10, sid), self.link, now_ns=500_000_000)
        self.assertEqual(self.registry.expire(now_ns=1_000_000_000), [sid])
        self.opening["payload"]["nonce_hex"] = "1" * 32
        sid = self.open(now=1_000_000_000)
        heartbeat = self.value(2, sid)
        self.registry.accept(heartbeat, self.link, now_ns=1_020_000_000)
        self.registry.record_response(heartbeat, [self.feedback(heartbeat)], now_ns=1_020_000_000)
        self.registry.accept(heartbeat, self.link, now_ns=1_500_000_000)
        self.assertEqual(self.registry.expire(now_ns=2_019_999_999), [])
        self.assertEqual(self.registry.expire(now_ns=2_020_000_000), [sid])

    def test_grants_and_request_identity_are_not_mutable_aliases(self):
        sid = self.open()
        self.opening["payload"]["identity"]["source_id"] = "changed"
        self.grant.identity["source_id"] = "changed"
        self.assertEqual(self.registry.identity(sid)["source_id"], "item-01")
        view = self.registry.identity(sid)
        view["source_id"] = "changed-again"
        self.assertEqual(self.registry.identity(sid)["source_id"], "item-01")

    def test_cross_link_complete_duplicate_replays_original_failure_once(self):
        sid = self.open()
        value = self.value(10, sid)
        self.assertIsNone(self.registry.accept(value, self.link, now_ns=0).replay)
        reply = self.feedback(value)
        self.registry.record_response(value, [reply], now_ns=0)
        reply["payload"]["error"] = "OK"
        replay = self.registry.accept(value, self.other, now_ns=1).replay
        self.assertEqual(replay[0]["payload"]["error"], "TARGET_MISSING")
        replay[0]["payload"]["error"] = "OK"
        self.assertEqual(self.registry.accept(value, self.link, now_ns=2).replay[0]["payload"]["error"], "TARGET_MISSING")

    def test_same_sequence_different_value_or_transaction_is_rejected(self):
        sid = self.open()
        value = self.value(10, sid)
        self.registry.accept(value, self.link, now_ns=0)
        for changed in ("payload", "transaction"):
            bad = self.value(10, sid)
            if changed == "payload":
                bad["payload"]["pressure_pa"] += 1
            else:
                bad["header"]["transaction_id"] += 1
            self.rejects("DUPLICATE", lambda: self.registry.accept(bad, self.other, now_ns=0))

    def test_cache_expiry_does_not_reset_session_sequence(self):
        sid = self.open()
        value = self.value(10, sid)
        self.registry.accept(value, self.link, now_ns=0)
        self.registry.record_response(value, [self.feedback(value)], now_ns=0)
        for sequence in range(3, 10):
            self.registry.accept(self.value(2, sid, sequence), self.link, now_ns=(sequence - 2) * 900_000_000)
        self.rejects("OUT_OF_ORDER", lambda: self.registry.accept(value, self.other, now_ns=6_300_000_001))

    def test_expired_or_revoked_session_cannot_write_and_ids_are_not_reused(self):
        first = self.open()
        self.registry.revoke(first)
        self.rejects("STALE_SESSION", lambda: self.registry.preauthorize(10, first, self.link, now_ns=0))
        self.opening["payload"]["nonce_hex"] = "2" * 32
        second = self.open()
        self.assertNotEqual(first, second)
        self.rejects("STALE_SESSION", lambda: self.registry.preauthorize(10, second, self.link, now_ns=1_000_000_000))

    def test_capacity_and_pending_duplicate_never_allocate_second_session(self):
        from icd_gateway.session import SessionRegistry
        self.registry = SessionRegistry(self.contract, [self.grant], max_sessions=1)
        self.open()
        self.rejects("STATE", lambda: self.open())
        self.opening["payload"]["nonce_hex"] = "3" * 32
        self.rejects("BUFFER_FULL", lambda: self.open())
        self.assertEqual(self.registry.active_count, 1)

    def test_feedback_counter_and_response_bounds(self):
        sid = self.open()
        self.assertEqual(self.registry.next_feedback_sequence(sid), 1)
        self.assertEqual(self.registry.next_feedback_sequence(sid), 2)
        value = self.value(10, sid)
        self.registry.accept(value, self.link, now_ns=0)
        reply = self.feedback(value)
        self.rejects("CAPACITY", lambda: self.registry.record_response(value, [reply] * 4, now_ns=0))
        reply["payload"].update(stage="APPLIED", error="OK", probe_id=1010)
        self.rejects("STATE", lambda: self.registry.record_response(value, [reply], now_ns=0))

    def test_duplicate_complete_grant_identity_cannot_split_session_ownership(self):
        from icd_gateway.session import SessionRegistry, SourceGrant
        other_link = dataclasses.replace(self.link, peer="127.0.0.1:40001")
        duplicate = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (other_link,))
        self.rejects("AUTHORIZATION", lambda: SessionRegistry(self.contract, [self.grant, duplicate]))

    def test_actual_8192_retry_cache_eviction_preserves_high_water_mark(self):
        sid = self.open()
        first = self.value(2, sid, 2)
        self.registry.accept(first, self.link, now_ns=0)
        self.registry.record_response(first, [self.feedback(first)], now_ns=0)
        for sequence in range(3, 8195):
            self.registry.accept(self.value(2, sid, sequence), self.link, now_ns=0)
            self.assertLessEqual(self.registry.cache_count, 8192)
        self.assertEqual(self.registry.cache_count, 8192)
        self.rejects("OUT_OF_ORDER", lambda: self.registry.accept(first, self.other, now_ns=0))
