import importlib.util

from common import GatewayTest, message


class ReceiverTests(GatewayTest):
    def setUp(self):
        super().setUp()

    def create_receiver(self):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from icd_gateway.receiver import Receiver
        from icd_runtime.wire import WireCodec
        self.link = PeerBinding("ETH_0", "UDP", "127.0.0.1:36102")
        grant = SourceGrant(message(1)["payload"]["identity"], ("STIMULUS",), (self.link,))
        self.registry = SessionRegistry(self.contract, [grant])
        self.receiver = Receiver(self.contract, self.registry)
        self.wire = WireCodec(self.contract)

    def deliver(self, value, now=0):
        replies = ()
        for packet in self.wire.encode(value, "UDP"):
            replies = self.receiver.receive(packet, self.link, now_ns=now)
        return replies

    def open(self):
        return self.deliver(message(1))[0]["payload"]["session_id"]

    def test_common_receiver_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.receiver"), "common receiver missing")

    def test_open_is_source_transparent_and_does_not_claim_model_readiness(self):
        self.create_receiver()
        reply = self.deliver(message(1))[0]
        self.assertEqual(reply["message_id"], 129)
        self.assertEqual(reply["header"]["session_id"], reply["payload"]["session_id"])
        self.assertEqual(reply["payload"]["lease_ms"], 1000)
        caps = reply["payload"]["capabilities"]
        self.assertEqual(caps["implemented_message_ids"], [1])
        self.assertEqual(caps["qualified_channels"], [])
        self.assertEqual(caps["available_probes"], [])
        self.assertFalse(caps["replacement_ready"])
        self.assertFalse(caps["system_model_ready"])

    def test_missing_consumer_has_received_then_failed_and_no_application(self):
        self.create_receiver()
        sid = self.open()
        value = message(3)
        value["header"].update(session_id=sid, sequence=2, transaction_id=9)
        replies = self.deliver(value)
        self.assertEqual([r["payload"]["stage"] for r in replies], ["RECEIVED", "FAILED"])
        self.assertEqual(replies[-1]["payload"]["error"], "TARGET_MISSING")
        for reply in replies:
            self.contract.validate_message(reply, direction="FROM_36")
            self.assertEqual(reply["payload"]["probe_id"], 0)
            self.assertEqual(reply["payload"]["request_sequence"], 2)
            self.assertEqual(reply["payload"]["request_message_id"], 3)
            self.assertEqual(reply["header"]["transaction_id"], 9)

    def test_complete_retry_reemits_same_feedback_without_second_admission(self):
        self.create_receiver()
        first = self.deliver(message(1))
        self.assertEqual(self.deliver(message(1)), first)
        value = message(10)
        value["header"].update(session_id=first[0]["payload"]["session_id"], sequence=2)
        first = self.deliver(value)
        count = self.receiver.admitted_count
        self.assertEqual(self.deliver(value, now=1), first)
        self.assertEqual(self.receiver.admitted_count, count)

    def test_different_value_reusing_sequence_is_failed_duplicate(self):
        self.create_receiver()
        value = message(10)
        value["header"].update(session_id=self.open(), sequence=2)
        first = self.deliver(value)
        value["payload"]["pressure_pa"] += 1
        reply = self.deliver(value)[0]
        self.assertEqual(reply["payload"]["error"], "DUPLICATE")
        value["payload"]["pressure_pa"] -= 1
        self.assertEqual(self.deliver(value), first)

    def test_acl_role_and_expiry_checks_precede_reassembly(self):
        self.create_receiver()
        from icd_gateway.session import PeerBinding
        sid = self.open()
        value = message(3)
        value["header"]["session_id"] = sid
        packet = self.wire.encode(value, "UDP")[0]
        unknown = PeerBinding("ETH_0", "UDP", "127.0.0.1:40000")
        self.rejects("AUTHORIZATION", lambda: self.receiver.receive(packet, unknown, now_ns=0))
        controlled = message(7)
        controlled["header"]["session_id"] = sid
        self.rejects("AUTHORIZATION", lambda: self.deliver(controlled))
        self.assertEqual(self.receiver.assembler.pending_count, 0)
        self.rejects("STALE_SESSION", lambda: self.receiver.receive(packet, self.link, now_ns=1_000_000_000))
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)

    def test_partial_groups_expire_even_without_traffic_and_session_shutdown_frees(self):
        self.create_receiver()
        value = message(3)
        value["header"]["session_id"] = self.open()
        packet = self.wire.encode(value, "UDP")[0]
        self.assertEqual(self.receiver.receive(packet, self.link, now_ns=0), ())
        self.assertEqual(self.receiver.assembler.pending_count, 1)
        self.receiver.tick(now_ns=100_000_000)
        self.assertEqual(self.receiver.assembler.pending_count, 0)
        value["header"].update(sequence=4, transaction_id=4)
        self.receiver.receive(self.wire.encode(value, "UDP")[0], self.link, now_ns=100_000_000)
        self.receiver.close()
        self.assertEqual(self.registry.active_count, 0)
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)
        self.assertEqual(self.registry.cache_count, 0)
        self.rejects("STATE", lambda: self.receiver.receive(packet, self.link, now_ns=100_000_000))

    def test_bad_open_identity_has_zero_session_failed_ack(self):
        self.create_receiver()
        value = message(1)
        value["payload"]["identity"]["source_id"] = "ungranted"
        reply = self.deliver(value)[0]
        self.assertEqual(reply["header"]["session_id"], 0)
        self.assertEqual(reply["payload"]["stage"], "FAILED")
        self.assertEqual(reply["payload"]["error"], "AUTHORIZATION")
        self.contract.validate_message(reply)

    def test_interleaved_fragmented_opens_are_isolated_by_authorized_grant(self):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from icd_gateway.receiver import Receiver
        from icd_runtime.wire import WireCodec
        first, second = message(1), message(1)
        for opening in (first, second):
            for key in ("run_id", "source_id", "vehicle_id", "scenario_id"):
                opening["payload"]["identity"][key] = "\u4e2d" * 128
        second["payload"]["identity"]["source_id"] = "\u4e59" * 128
        links = [PeerBinding("ETH_0", "UDP", f"127.0.0.1:{port}") for port in (36102, 40001)]
        registry = SessionRegistry(self.contract, [SourceGrant(value["payload"]["identity"], ("STIMULUS",), (link,))
                                                   for value, link in zip((first, second), links)])
        receiver = Receiver(self.contract, registry)
        packets = [WireCodec(self.contract).encode(value, "UDP") for value in (first, second)]
        self.assertEqual([len(p) for p in packets], [2, 2])
        self.assertEqual(receiver.receive(packets[0][0], links[0], now_ns=0), ())
        self.assertEqual(receiver.receive(packets[1][0], links[1], now_ns=0), ())
        first_reply = receiver.receive(packets[0][1], links[0], now_ns=0)[0]
        second_reply = receiver.receive(packets[1][1], links[1], now_ns=0)[0]
        self.assertEqual(first_reply["message_id"], 129)
        self.assertEqual(second_reply["message_id"], 129)
        self.assertNotEqual(first_reply["payload"]["session_id"], second_reply["payload"]["session_id"])
        self.assertEqual(registry.active_count, 2)
        self.assertEqual(receiver.assembler.reserved_bytes, 0)
