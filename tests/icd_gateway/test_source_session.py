import copy
from dataclasses import FrozenInstanceError
import importlib.util
import threading
import unittest

from common import EXPECTED, INTERFACES, message
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.wire import Header, WireCodec
import test_udp
import test_resource_udp


class FeedbackCorrelationTests(test_udp.UDPTests):
    # Reuse only the actual socket fixture, not the inherited test cases.
    def test_status_is_only_a_heartbeat_response(self):
        self.create_network()
        request = message(2)
        response = message(131)
        response["header"].update(session_id=request["header"]["session_id"],
                                  transaction_id=request["header"]["transaction_id"])
        self.gateway.socket.sendto(WireCodec(self.contract).encode(response, "UDP")[0], self.source.feedback_endpoint)
        self.assertEqual(self.source.receive_for(request, timeout=0.1), response)

    def test_clock_status_nonce_and_request_type_are_correlated(self):
        self.create_network()
        request = message(33)
        bad = message(142)
        bad["header"].update(session_id=request["header"]["session_id"],
                             transaction_id=request["header"]["transaction_id"])
        bad["payload"]["nonce"] = request["payload"]["nonce"] + 1
        good = copy.deepcopy(bad)
        good["payload"]["nonce"] = request["payload"]["nonce"]
        good["header"]["sequence"] += 1
        for value in (bad, good):
            self.gateway.socket.sendto(WireCodec(self.contract).encode(value, "UDP")[0], self.source.feedback_endpoint)
        self.assertEqual(self.source.receive_for(request, timeout=0.1), good)
        self.assertEqual(self.source.dropped_feedback, 1)

    def test_unrelated_status_clock_feedback_is_not_an_ack(self):
        self.create_network()
        request = message(7)
        for mid in (131, 142):
            response = message(mid)
            response["header"].update(session_id=request["header"]["session_id"],
                                      transaction_id=request["header"]["transaction_id"])
            self.gateway.socket.sendto(WireCodec(self.contract).encode(response, "UDP")[0], self.source.feedback_endpoint)
        self.rejects("TIMEOUT", lambda: self.source.receive_for(request, timeout=0.03))
        self.assertEqual(self.source.dropped_feedback, 2)


# The fixture class carries 15 existing tests; avoid duplicating those suites.
for _name in list(test_udp.UDPTests.__dict__):
    if _name.startswith("test_"):
        setattr(FeedbackCorrelationTests, _name, None)


class LocalClock:
    def __init__(self):
        self.value = 1_000_000_000

    def __call__(self):
        return self.value


class UnitPeer:
    """Protocol-only double; never registered as a real model/consumer."""
    channel = "ETH_0"

    def __init__(self, contract, clock):
        self.contract = contract
        self.clock = clock
        self.requests = []
        self.sid = 73
        self.sequence = 1
        self.delay_ns = 0
        self.modify = lambda response: response
        self.raise_error = None
        self.owner = None

    def claim_session_owner(self, owner):
        if self.owner is not None:
            raise ICDError("STATE", "unit transport already has a counter owner")
        self.owner = owner
        return 1

    def request(self, value, *, owner=None):
        self.requests.append(copy.deepcopy(value))
        self.clock.value += self.delay_ns
        if self.raise_error is not None:
            raise self.raise_error
        if value["message_id"] == 1:
            reply = message(129)
            reply["header"].update(session_id=self.sid, sequence=1, transaction_id=value["header"]["transaction_id"])
            reply["payload"].update(session_id=self.sid, accepted_roles=value["payload"]["roles"])
            reply["payload"]["capabilities"].update(model_ids=[value["payload"]["identity"]["model_id"]],
                                                       implemented_message_ids=[1, 2, 7, 10, 33, 34, 38])
        elif value["message_id"] == 2:
            reply = message(131)
        else:
            reply = message(130)
            reply["payload"].update(request_sequence=value["header"]["sequence"],
                                      request_message_id=value["message_id"], stage="FAILED", error="TARGET_MISSING")
        if value["message_id"] != 1:
            self.sequence += 1
            reply["header"].update(session_id=value["header"]["session_id"], sequence=self.sequence,
                                     transaction_id=value["header"]["transaction_id"])
        return self.modify(reply)


class SourceSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)

    def setUp(self):
        self.clock = LocalClock()
        self.peer = UnitPeer(self.contract, self.clock)

    def session(self, **kw):
        from input_simulator.session import SourceSession
        roles = kw.pop("roles", ("STIMULUS", "OBSERVER", "CONTROLLER"))
        return SourceSession(self.peer, message(1)["payload"]["identity"], roles,
                             clock=self.clock, **kw)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_session_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.session"), "live source session manager missing")

    def test_open_captures_actual_grant_and_allocates_global_fresh_headers(self):
        session = self.session()
        self.assertEqual(session.session_id, None)
        opened = session.open()
        self.assertEqual(session.session_id, opened["payload"]["session_id"])
        a = session.allocate_header(7, 100)
        b = session.allocate_header(10, 101, transaction_id=a.transaction_id)
        c = session.allocate_header(7, 102)
        self.assertEqual((a.session_id, a.sequence, b.sequence, c.sequence), (73, 2, 3, 4))
        self.assertEqual(a.transaction_id, b.transaction_id)
        self.assertGreater(c.transaction_id, b.transaction_id)
        self.assertEqual(a.valid_for_ms, 100)
        self.assertEqual(b.valid_for_ms, 240)
        self.assertEqual(session.last_rx_sequence, 1)

    def test_roles_capability_and_model_are_checked_before_allocation(self):
        session = self.session()
        session.open()
        for mid, code in ((8, "MODEL"), (17, "TARGET_MISSING"), (130, "AUTHORIZATION"), (1, "STATE")):
            self.rejects(code, lambda: session.allocate_header(mid, 100))
        self.assertEqual(session.allocate_header(7, 100).sequence, 2)
        self.peer = UnitPeer(self.contract,self.clock)
        restricted = self.session(roles=("STIMULUS", "OBSERVER"))
        restricted.open()
        self.rejects("AUTHORIZATION", lambda: restricted.allocate_header(14,100))

    def test_open_validates_both_baselines_roles_sid_and_model(self):
        def nested_hash(r):
            r["payload"]["capabilities"]["baseline_sha256"] = "0" * 64
            return r
        def extra_role(r):
            r["payload"]["accepted_roles"] = ["CONTROLLER"]
            return r
        def duplicate_role(r):
            r["payload"]["accepted_roles"] = ["STIMULUS", "STIMULUS"]
            return r
        def wrong_sid(r):
            r["payload"]["session_id"] += 1
            return r
        def wrong_model(r):
            r["payload"]["capabilities"]["model_ids"] = ["fixed_wing_hil"]
            return r
        for modify, code in ((nested_hash,"HASH"),(extra_role,"AUTHORIZATION"),(duplicate_role,"AUTHORIZATION"),
                             (wrong_sid,"STALE_SESSION"),(wrong_model,"MODEL")):
            self.peer = UnitPeer(self.contract,self.clock)
            self.peer.modify = modify
            session = self.session(roles=("STIMULUS", "OBSERVER"))
            self.rejects(code, session.open)
            self.assertIsNone(session.session_id)

    def test_conservative_lease_starts_before_exchange_not_on_late_reply(self):
        session = self.session()
        self.peer.delay_ns = 900_000_000
        session.open()
        self.clock.value += 100_000_000
        self.rejects("STALE_SESSION", lambda: session.allocate_header(7,100))

    def test_open_after_the_entire_lease_cannot_create_a_live_local_session(self):
        session = self.session()
        self.peer.delay_ns = 1_000_000_000
        self.rejects("STALE_SESSION", session.open)
        self.assertIsNone(session.session_id)

    def test_heartbeat_uses_actual_last_feedback_and_explicit_sender_step(self):
        session = self.session()
        session.open()
        self.clock.value += 600_000_000
        session.heartbeat(123, target_step=124)
        heartbeat = self.peer.requests[-1]
        self.assertEqual(heartbeat["payload"], {"last_rx_sequence":1,"sender_step":123})
        self.assertEqual(session.last_rx_sequence,2)
        self.clock.value += 600_000_000
        self.assertEqual(session.allocate_header(7,125).session_id,73)

    def test_failed_heartbeat_and_ordinary_feedback_do_not_renew_lease(self):
        session = self.session()
        session.open()
        self.clock.value += 600_000_000
        def failure(reply):
            value=message(130)
            value["header"]=reply["header"]
            value["header"]["valid_for_ms"]=self.contract.entry(130)["valid_for_ms"]
            value["payload"].update(request_sequence=2,request_message_id=2,stage="FAILED",error="TARGET_MISSING")
            return value
        self.peer.modify=failure
        reply=session.heartbeat(123,target_step=124)
        self.assertEqual(reply["payload"]["stage"],"FAILED")
        self.clock.value += 400_000_000
        self.rejects("STALE_SESSION",lambda:session.allocate_header(7,125))

    def test_request_keeps_real_failed_feedback_without_manufacturing_stage(self):
        session=self.session()
        session.open()
        reply=session.request({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        self.assertEqual(reply["payload"]["stage"],"FAILED")
        self.assertEqual(reply["payload"]["probe_id"],0)
        record=session.records[-1]
        self.assertEqual(record.reply,reply)
        self.assertEqual(record.request["header"]["sequence"],2)
        self.assertEqual(record.started_ns,record.completed_ns)

    def test_invalid_payload_does_not_consume_sequence_or_send(self):
        session=self.session()
        session.open()
        self.rejects("SCHEMA",lambda:session.request({"message_id":7,"payload":{}},target_step=100))
        self.assertEqual(len(self.peer.requests),1)
        self.assertEqual(session.allocate_header(7,100).sequence,2)

    def test_bad_target_and_counter_wrap_reject(self):
        session=self.session()
        session.open()
        for step in (True,-1,1.5,0x100000000):
            self.rejects("SCHEMA",lambda:session.allocate_header(7,step))
        session._next_sequence=0xffffffff
        self.assertEqual(session.allocate_header(7,100).sequence,0xffffffff)
        self.rejects("CAPACITY",lambda:session.allocate_header(7,101))

    def test_explicit_transaction_reservation_never_collides_with_auto_counter(self):
        session=self.session()
        session.open()
        first=session.allocate_header(7,100,transaction_id=100)
        second=session.allocate_header(10,100)
        self.assertEqual(first.transaction_id,100)
        self.assertGreater(second.transaction_id,100)
        self.rejects("SCHEMA",lambda:session.allocate_header(7,100,transaction_id=True))

    def test_reopen_requires_explicit_local_abandon_and_never_reuses_nonce_or_sid(self):
        session=self.session()
        session.open()
        first=self.peer.requests[-1]
        self.rejects("STATE",session.open)
        session.abandon()
        self.peer.sid+=1
        session.open()
        second=self.peer.requests[-1]
        self.assertNotEqual(first["payload"]["nonce_hex"],second["payload"]["nonce_hex"])
        self.assertNotEqual(first["header"]["transaction_id"],second["header"]["transaction_id"])
        self.assertEqual(session.allocate_header(7,100).sequence,2)
        session.abandon()
        self.rejects("STALE_SESSION",session.open)

    def test_local_abandon_is_not_a_remote_close_reset_or_clear_queues(self):
        session=self.session()
        session.open()
        session.abandon()
        self.assertEqual([m["message_id"] for m in self.peer.requests],[1])
        self.assertIsNone(session.session_id)
        self.rejects("STALE_SESSION",lambda:session.allocate_header(7,100))
        session.close()
        self.rejects("STATE",session.open)

    def test_record_capacity_rejects_before_send_and_drain_does_not_clear_session(self):
        session=self.session(max_records=1)
        session.open()
        self.rejects("BUFFER_FULL",lambda:session.request({"message_id":7,"payload":message(7)["payload"]},target_step=100))
        self.assertEqual(len(self.peer.requests),1)
        records=session.drain_records()
        self.assertEqual(len(records),1)
        self.assertEqual(session.session_id,73)
        reply=session.request({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        self.assertEqual(reply["payload"]["request_sequence"],2)

    def test_transport_timeout_is_recorded_without_faking_response_or_session(self):
        session=self.session()
        self.peer.raise_error=ICDError("TIMEOUT","unit-test-only missing peer")
        self.rejects("TIMEOUT",session.open)
        self.assertIsNone(session.session_id)
        self.assertIsNone(session.records[0].reply)
        self.assertEqual(session.records[0].error,"TIMEOUT")

    def test_records_and_capabilities_are_immutable_detached(self):
        session=self.session()
        session.open()
        cap=session.capabilities
        cap["implemented_message_ids"].append(17)
        self.rejects("TARGET_MISSING",lambda:session.allocate_header(17,100))
        record=session.records[0]
        record.request["payload"].clear()
        self.assertIn("nonce_hex",record.request["payload"])
        with self.assertRaises(FrozenInstanceError):
            record.started_ns=0

    def test_invalid_constructor_limits_identity_and_roles_reject(self):
        from input_simulator.session import SourceSession
        for kw in ({"max_records":True},{"max_records":0},{"max_record_bytes":True},{"max_record_bytes":0}):
            self.rejects("CAPACITY",lambda:self.session(**kw))
        self.rejects("SCHEMA",lambda:SourceSession(self.peer,{},("STIMULUS",),clock=self.clock))
        self.rejects("SCHEMA",lambda:SourceSession(self.peer,message(1)["payload"]["identity"],("STIMULUS","STIMULUS"),clock=self.clock))

    def test_backward_or_bool_source_mono_is_rejected_without_send(self):
        session=self.session()
        session.open()
        self.clock.value-=1
        self.rejects("SCHEMA",lambda:session.allocate_header(7,100))
        self.clock.value=True
        self.rejects("SCHEMA",lambda:session.allocate_header(7,100))
        self.assertEqual(len(self.peer.requests),1)

    def test_one_counter_owner_per_transport_even_after_local_close(self):
        session=self.session()
        self.rejects("STATE",self.session)
        session.close()
        self.rejects("STATE",self.session)

    def test_request_payload_detaches_from_callers_during_transport_exchange(self):
        session=self.session()
        session.open()
        stimulus={"message_id":7,"payload":message(7)["payload"]}
        original=self.peer.request
        observed=[]
        def exchange(value, **kw):
            stimulus["payload"]["motor_command"][0]=0.9
            observed.append(copy.deepcopy(value))
            return original(value, **kw)
        self.peer.request=exchange
        session.request(stimulus,target_step=100)
        self.assertEqual(observed[0]["payload"]["motor_command"][0],0.1)
        self.assertEqual(session.records[-1].request["payload"]["motor_command"][0],0.1)

    def test_clock_failure_after_reply_keeps_untrusted_exchange_record(self):
        session=self.session()
        session.open()
        def reverse(reply):
            self.clock.value-=1
            return reply
        self.peer.modify=reverse
        self.rejects("SCHEMA",lambda:session.request({"message_id":7,"payload":message(7)["payload"]},target_step=100))
        self.assertIsNone(session.records[-1].completed_ns)
        self.assertEqual(session.records[-1].error,"SCHEMA")
        self.assertIsNotNone(session.records[-1].reply)


class ActualSourceSessionTests(test_udp.UDPTests):
    def start_gateway(self):
        self.create_network()
        self.poll_gateway()

    def poll_gateway(self):
        stop=threading.Event()
        errors=[]
        def run():
            try:
                while not stop.is_set():
                    self.gateway.poll(timeout=0.01)
            except Exception as error:
                errors.append(error)
        thread=threading.Thread(target=run)
        thread.start()
        def end():
            stop.set()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[])
        self.addCleanup(end)

    def test_real_receiver_grant_used_and_missing_capability_stops_before_tx(self):
        from input_simulator.session import SourceSession
        self.start_gateway()
        session=SourceSession(self.source,message(1)["payload"]["identity"],("STIMULUS",))
        opened=session.open()
        self.assertIn(session.session_id,self.registry.session_ids)
        self.assertEqual(session.capabilities["implemented_message_ids"],[1])
        self.rejects("TARGET_MISSING",lambda:session.allocate_header(10,100))
        self.assertEqual(self.receiver.admitted_count,1)
        session.abandon()
        self.assertIn(opened["payload"]["session_id"],self.registry.session_ids)
        self.assertEqual(self.receiver.admitted_count,1)

    def test_real_receiver_rejects_wrong_identity_without_local_grant(self):
        from input_simulator.session import SourceSession
        self.start_gateway()
        identity=message(1)["payload"]["identity"]
        identity["source_id"]="other-source"
        session=SourceSession(self.source,identity,("STIMULUS",))
        self.rejects("AUTHORIZATION",session.open)
        self.assertIsNone(session.session_id)
        self.assertEqual(self.registry.active_count,0)
        self.assertEqual(session.records[0].reply["payload"]["stage"],"FAILED")

    def test_real_transport_rejects_new_manager_and_delayed_old_grant(self):
        from input_simulator.session import SourceSession
        self.start_gateway()
        session=SourceSession(self.source,message(1)["payload"]["identity"],("STIMULUS",))
        opened=session.open()
        session.close()
        for packet in self.source.wire.encode(opened,"UDP"):
            self.gateway.socket.sendto(packet,self.source.feedback_endpoint)
        identity=message(1)["payload"]["identity"]
        identity["source_id"]="other-source"
        self.rejects("STATE",lambda:SourceSession(self.source,identity,("STIMULUS",)))
        self.assertEqual(self.receiver.admitted_count,1)

    def test_opening_transaction_follows_prior_manual_transport_use(self):
        from input_simulator.session import SourceSession
        self.start_gateway()
        prior=message(1)
        prior["header"]["transaction_id"]=500
        self.source.request(prior)
        session=SourceSession(self.source,message(1)["payload"]["identity"],("STIMULUS",))
        session.open()
        self.assertGreater(session.records[0].request["header"]["transaction_id"],500)

    def test_claim_blocks_manual_tx_and_feedback_read_after_construction(self):
        from input_simulator.session import SourceSession
        self.start_gateway()
        identity=message(1)["payload"]["identity"]
        identity["source_id"]="other-source"
        session=SourceSession(self.source,identity,("STIMULUS",))
        prior=message(1)
        self.rejects("STATE",lambda:self.source.request(prior))
        self.rejects("STATE",lambda:self.source.send(prior))
        self.rejects("STATE",lambda:self.source.receive_for(prior))
        self.assertEqual(self.receiver.admitted_count,0)
        self.rejects("AUTHORIZATION",session.open)
        self.assertIsNone(session.session_id)


for _name in list(test_udp.UDPTests.__dict__):
    if _name.startswith("test_"):
        setattr(ActualSourceSessionTests, _name, None)


class ActualResourceSessionTests(test_resource_udp.ResourceUDPTests):
    def test_real_grant_header_feeds_replay_and_actual_resource_exchange(self):
        from input_simulator.history import CaptureBinding
        from input_simulator.replay import ReplayHeader, ReplayProcessor
        from input_simulator.session import SourceSession
        from test_capture import pcap
        from test_history import history, udp_packet
        from test_resources import chunk
        self.network()
        ActualSourceSessionTests.poll_gateway(self)
        session = SourceSession(self.source, message(1)["payload"]["identity"], ("STIMULUS",))
        session.open()
        self.assertEqual(session.capabilities["implemented_message_ids"], [1, 34])
        data = b"actual-standard-session-resource-not-model-application"
        original = chunk(data, kind="VIDEO")
        raw = pcap([(1, i, udp_packet(frame)) for i, frame in enumerate(self.source.wire.encode(original, "UDP"))], nano=True)
        h = history(raw, [34], end=str(len(self.source.wire.encode(original, "UDP"))-1))
        header = session.allocate_header(34, 0)
        prepared = ReplayProcessor(self.contract).prepare(
            raw, h, (CaptureBinding("env","ETH_0","PCAP:0:0","interface-0","clock-0"),),
            model_id="quadrotor_hil", declared_ids=(34,), headers=(ReplayHeader(0,header),))
        self.assertEqual(self.source.wire.decode(prepared.packets[0].wire_data,"UDP").header.session_id, session.session_id)
        self.assertFalse(prepared.execution_ready)
        reply = session.request({"message_id":34,"payload":original["payload"]},target_step=0)
        self.assertEqual(reply["message_id"],141)
        self.assertTrue(reply["payload"]["complete"])
        self.assertEqual(reply["payload"]["error"],"OK")
        path = self.store.root / "objects" / reply["payload"]["resource_sha256"] / "data.bin"
        self.assertEqual(path.read_bytes(),data)
        self.assertFalse(session.capabilities["replacement_ready"])
        self.assertEqual(session.capabilities["available_probes"],[])
        self.assertEqual(session.records[-1].reply,reply)


for _name in list(test_resource_udp.ResourceUDPTests.__dict__):
    if _name.startswith("test_"):
        setattr(ActualResourceSessionTests, _name, None)


if __name__ == "__main__":
    unittest.main()
