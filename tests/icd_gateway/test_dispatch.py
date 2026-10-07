import copy
import importlib.util
import threading
import time
import unittest
from unittest.mock import patch

from common import message
from icd_runtime.errors import ICDError
import test_udp
import test_resource_udp
import test_source_session


class MatchingTests(test_udp.UDPTests):
    def matcher(self):
        method=getattr(self.source,"receive_matching",None)
        self.assertTrue(callable(method),"bounded multi-request UDP matching missing")
        return method

    def emit(self, reply):
        for packet in self.source.wire.encode(reply,"UDP"):
            self.gateway.socket.sendto(packet,self.source.feedback_endpoint)

    def test_interleaved_same_transaction_ack_matches_original_sequence(self):
        self.create_network()
        a=message(7)
        b=copy.deepcopy(a)
        b["header"]["sequence"]+=1
        for sequence,request in enumerate((b,a),1):
            reply=message(130)
            reply["header"].update(session_id=a["header"]["session_id"],sequence=sequence,
                                     transaction_id=a["header"]["transaction_id"])
            reply["payload"].update(request_sequence=request["header"]["sequence"],
                                      request_message_id=7,stage="FAILED",error="TARGET_MISSING")
            self.emit(reply)
        receive=self.matcher()
        self.assertEqual(receive((a,b),timeout=0.1)[0],1)
        self.assertEqual(receive((a,b),timeout=0.1)[0],0)

    def test_nonblocking_typed_feedback_does_not_drop_other_pending_request(self):
        self.create_network()
        a=message(2)
        b=message(33)
        b["header"].update(session_id=a["header"]["session_id"],transaction_id=a["header"]["transaction_id"]+1)
        reply=message(142)
        reply["header"].update(session_id=b["header"]["session_id"],transaction_id=b["header"]["transaction_id"])
        reply["payload"]["nonce"]=b["payload"]["nonce"]
        self.emit(reply)
        self.assertEqual(self.matcher()((a,b),timeout=0),(1,reply))
        self.rejects("TIMEOUT",lambda:self.matcher()((a,b),timeout=0))
        self.assertEqual(self.source.dropped_feedback,0)

    def test_matching_list_is_bounded_strict_and_unique(self):
        self.create_network()
        receive=self.matcher()
        for requests in ([],(),(message(7),)*65,(message(7),message(7))):
            self.rejects("SCHEMA",lambda:receive(requests,timeout=0))

    def test_matured_resource_reservations_do_not_burst_after_delayed_poll(self):
        from test_resource_udp import chunk
        from icd_runtime.resource_budget import ResourceBudget
        self.create_network()
        a=chunk(b"a"*1000)
        b=chunk(b"b"*1000,sequence=3)
        first=self.source.prepare_transmission(a)
        second=self.source.prepare_transmission(b)
        clock=test_source_session.LocalClock()
        with patch("input_simulator.udp_source.time.perf_counter_ns",clock):
            self.assertFalse(self.source.transmit_fragment(first,0))
            self.assertFalse(self.source.transmit_fragment(second,0))
            clock.value+=10_000_000
            self.assertTrue(self.source.transmit_fragment(first,0))
            self.assertFalse(self.source.transmit_fragment(second,0),"matured reservations bypass actual rate")
            packet=self.source.wire.encode(b,"UDP")[0]
            duration=(ResourceBudget.wire_bits((packet,))*1_000_000_000+19_999_999)//20_000_000
            clock.value+=duration
            self.assertTrue(self.source.transmit_fragment(second,0))


for _name in list(test_udp.UDPTests.__dict__):
    if _name.startswith("test_"):
        setattr(MatchingTests,_name,None)


class DispatcherTests(MatchingTests):
    """Actual UDP protocol peer only; not a C/model/clock qualified consumer."""
    def setup_peer(self, **kw):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.dispatch"),"async dispatcher missing")
        from input_simulator.dispatch import UDPDispatcher
        from input_simulator.session import SourceSession
        from icd_runtime.reassembly import Reassembler
        self.create_network()
        self.clock=test_source_session.LocalClock()
        self.session=SourceSession(self.source,message(1)["payload"]["identity"],
                                   ("STIMULUS","CONTROLLER","OBSERVER"),clock=self.clock)
        self.peer_assembler=Reassembler(self.contract,retain_completed=False)
        errors=[]
        def open_source():
            try:
                self.session.open()
            except Exception as error:
                errors.append(error)
        thread=threading.Thread(target=open_source)
        thread.start()
        self.gateway.socket.settimeout(1)
        opening=None
        while opening is None:
            packet,_=self.gateway.socket.recvfrom(1201)
            opening=self.peer_assembler.push(self.source.wire.decode(packet,"UDP",direction="TO_36"),
                                               channel="ETH_0",direction="TO_36",authorized=True,now_ns=time.monotonic_ns())
        self.reply_sequence=1
        reply=message(129)
        reply["header"].update(session_id=73,transaction_id=opening.message["header"]["transaction_id"],sequence=1)
        reply["payload"].update(session_id=73,accepted_roles=opening.message["payload"]["roles"])
        reply["payload"]["capabilities"]["implemented_message_ids"]=[1,2,7,33,34]
        self.emit(reply)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
        self.dispatch=UDPDispatcher(self.session,**kw)
        self.addCleanup(self.dispatch.close)

    def collect(self):
        self.gateway.socket.settimeout(0)
        packets=[]
        messages=[]
        while True:
            try:
                packet,_=self.gateway.socket.recvfrom(1201)
            except BlockingIOError:
                break
            packets.append(packet)
            complete=self.peer_assembler.push(self.source.wire.decode(packet,"UDP",direction="TO_36"),
                                               channel="ETH_0",direction="TO_36",authorized=True,now_ns=time.monotonic_ns())
            if complete is not None:
                messages.append(complete.message)
        return packets,messages

    def response(self,request,mid=130,stage="FAILED"):
        self.reply_sequence+=1
        reply=message(mid)
        reply["header"].update(session_id=73,transaction_id=request["header"]["transaction_id"],sequence=self.reply_sequence)
        if mid==130:
            reply["payload"].update(request_sequence=request["header"]["sequence"],request_message_id=request["message_id"],
                                      stage=stage,error="TARGET_MISSING" if stage=="FAILED" else "OK")
        elif mid==142:
            reply["payload"]["nonce"]=request["payload"]["nonce"]
        self.emit(reply)
        return reply

    def test_actual_multi_inflight_out_of_order_feedback_and_terminal_records(self):
        self.setup_peer()
        a=self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        b=self.dispatch.submit({"message_id":33,"payload":message(33)["payload"]},target_step=100)
        self.assertEqual((a.sequence,b.sequence),(2,3))
        self.dispatch.poll()
        _,requests=self.collect()
        for request in reversed(requests):
            self.response(request,142 if request["message_id"]==33 else 130)
        self.dispatch.poll()
        self.assertEqual(self.dispatch.pending_count,0)
        records=self.dispatch.drain_records()
        rx=[r for r in records if r.kind=="RX"]
        self.assertEqual(len(rx),2)
        self.assertEqual({r.error for r in rx},{None,"TARGET_MISSING"})
        self.assertEqual(sum(r.kind=="TX" for r in records),2)

    def test_reliable_four_original_attempts_periodic_one_and_timeout(self):
        self.setup_peer()
        self.dispatch.submit({"message_id":33,"payload":message(33)["payload"]},target_step=100)
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        sent=[]
        for _ in range(5):
            self.dispatch.poll()
            packets,_=self.collect()
            sent.extend(packets)
            self.clock.value+=200_000_000
        by_mid={mid:[p for p in sent if self.source.wire.decode(p,"UDP").message_id==mid] for mid in (7,33)}
        self.assertEqual(len(by_mid[7]),1)
        self.assertEqual(len(by_mid[33]),4)
        self.assertTrue(all(p==by_mid[33][0] for p in by_mid[33]))
        self.assertEqual(self.dispatch.pending_count,0)
        self.assertEqual(sum(r.kind=="TIMEOUT" for r in self.dispatch.records),2)

    def test_received_is_not_terminal_and_unrelated_heartbeat_can_complete(self):
        from test_resource_udp import chunk
        self.setup_peer()
        self.dispatch.submit({"message_id":34,"payload":chunk(b"actual-resource")["payload"]},target_step=0)
        resource=None
        for _ in range(20):
            self.dispatch.poll()
            _,requests=self.collect()
            if requests:
                resource=requests[0]
                break
            time.sleep(0.001)
        self.assertIsNotNone(resource)
        self.response(resource,stage="RECEIVED")
        self.dispatch.poll()
        self.assertEqual(self.dispatch.pending_count,1)
        self.dispatch.submit({"message_id":2,"payload":{"last_rx_sequence":self.session.last_rx_sequence,"sender_step":0}},target_step=0)
        self.dispatch.poll()
        _,requests=self.collect()
        self.response(requests[0],131)
        self.dispatch.poll()
        self.assertEqual(self.dispatch.pending_count,1)
        self.assertEqual(self.session.last_rx_sequence,self.reply_sequence)

    def test_heartbeat_keeps_conservative_session_live_during_resource_wait(self):
        from test_resource_udp import chunk
        self.setup_peer(max_records=4096)
        self.dispatch.submit({"message_id":34,"payload":chunk(b"waiting-for-real-progress")["payload"]},target_step=0)
        self.dispatch.enable_heartbeat(lambda:(123,124))
        heartbeats=[]
        for cycle in range(70):
            deadline=time.monotonic()+0.1
            while len(heartbeats)<cycle+1 and time.monotonic()<deadline:
                self.dispatch.poll()
                _,requests=self.collect()
                for request in requests:
                    if request["message_id"]==2:
                        heartbeats.append(request)
                        self.response(request,131)
                    elif request["message_id"]==34:
                        self.response(request,stage="RECEIVED")
                self.dispatch.poll()
                time.sleep(0.001)
            self.assertEqual(len(heartbeats),cycle+1)
            self.clock.value+=20_000_000
        self.assertEqual(len(heartbeats),70)
        self.assertTrue(all(r["payload"]["sender_step"]==123 for r in heartbeats))
        self.assertGreater(self.session._deadline_ns,self.clock.value)
        self.assertEqual(self.dispatch.pending_count,1)

    def test_capacity_before_allocation_and_local_close_releases_binding_not_remote_session(self):
        self.setup_peer(capacity=1)
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        self.rejects("BUFFER_FULL",lambda:self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100))
        self.rejects("STATE",lambda:self.session.allocate_header(7,100))
        self.rejects("STATE",self.session.abandon)
        self.dispatch.close()
        self.assertEqual(self.collect()[0],[])
        self.assertEqual(self.session.allocate_header(7,100).sequence,3)
        self.assertEqual(self.session.session_id,73)
        self.assertEqual(self.dispatch.records[-1].kind,"CANCEL")
        self.assertTrue(self.dispatch.drain_records())

    def test_record_capacity_preserves_existing_and_rejects_before_sequence(self):
        self.setup_peer(max_records=11)
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        self.rejects("BUFFER_FULL",lambda:self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100))
        self.dispatch.close()
        self.assertEqual(self.session.allocate_header(7,100).sequence,3)

    def test_auto_heartbeat_late_tick_rejected_not_catchup_and_records_are_immutable(self):
        self.setup_peer()
        self.dispatch.enable_heartbeat(lambda:(0,0))
        self.dispatch.poll()
        self.collect()
        self.clock.value+=22_000_000
        self.rejects("TIMEOUT",self.dispatch.poll)
        records=self.dispatch.records
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            records[0].kind="FAKE"

    def test_deferred_heartbeat_checks_actual_tx_deadline(self):
        from test_resource_udp import chunk
        self.setup_peer()
        self.dispatch.submit({"message_id":34,"payload":chunk(b"x"*32768)["payload"]},target_step=0)
        self.dispatch.enable_heartbeat(lambda:(0,0))
        self.dispatch.poll()
        self.clock.value+=2_000_000
        self.rejects("TIMEOUT",self.dispatch.poll)
        self.assertTrue(any(r.kind=="TIMEOUT" and r.error=="TIMEOUT" for r in self.dispatch.records))

    def test_clock_failure_still_cancels_locally_without_inventing_timestamp(self):
        self.setup_peer()
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        self.clock.value-=1
        self.dispatch.close()
        self.assertEqual(self.dispatch.pending_count,0)
        self.assertIsNone(self.session._dispatcher)
        self.assertIsNone(self.dispatch.records[-1].at_ns)
        self.assertEqual(self.dispatch.records[-1].error,"SCHEMA")

    def test_clock_failure_after_actual_tx_keeps_wire_and_progress(self):
        self.setup_peer()
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        value=self.clock.value
        values=iter((value,value,value,value-1))
        self.session._clock=lambda:next(values,value-1)
        self.rejects("SCHEMA",self.dispatch.poll)
        self.assertEqual(len(self.collect()[0]),1)
        tx=[r for r in self.dispatch.records if r.kind=="TX"]
        self.assertEqual(len(tx),1)
        self.assertIsNone(tx[0].at_ns)
        self.assertEqual(tx[0].error,"SCHEMA")
        self.assertEqual(tx[0].attempt,1)
        self.assertIsNotNone(tx[0].wire_data)

    def test_final_resource_late_actual_feedback_is_retained_but_not_complete(self):
        from test_resource_udp import chunk
        self.setup_peer()
        resource=chunk(b"late-resource")
        header=self.dispatch.submit({"message_id":34,"payload":resource["payload"]},target_step=0)
        request=None
        for _ in range(20):
            self.dispatch.poll()
            _,requests=self.collect()
            if requests:
                request=requests[0]
                break
            time.sleep(0.001)
        self.assertIsNotNone(request)
        self.response(request,stage="RECEIVED")
        self.dispatch.poll()
        for _ in range(49):
            self.clock.value+=200_000_000
            self.dispatch.submit({"message_id":2,"payload":{"last_rx_sequence":self.session.last_rx_sequence,"sender_step":0}},target_step=0)
            self.dispatch.poll()
            _,requests=self.collect()
            for heartbeat in requests:
                if heartbeat["message_id"]==2:
                    self.response(heartbeat,131)
            self.dispatch.poll()
            time.sleep(0.001)
        self.clock.value+=200_000_000
        reply=message(141)
        self.reply_sequence+=1
        reply["header"].update(session_id=73,sequence=self.reply_sequence,transaction_id=header.transaction_id)
        reply["payload"].update(resource_sha256=resource["payload"]["resource_sha256"],stored_bytes=13,next_offset=13,complete=True,error="OK")
        self.emit(reply)
        self.dispatch.poll()
        records=[r for r in self.dispatch.records if r.header.sequence==header.sequence]
        self.assertEqual(records[-1].kind,"TIMEOUT")
        self.assertEqual(records[-2].kind,"RX")
        self.assertEqual(records[-2].reply,reply)
        self.assertEqual(records[-2].error,"TIMEOUT")

    def test_nonfinal_resource_feedback_during_paced_retry_is_not_lost(self):
        from test_resource_udp import chunk
        self.setup_peer()
        resource=chunk(b"a"*2000,0,1000)
        header=self.dispatch.submit({"message_id":34,"payload":resource["payload"]},target_step=0)
        for _ in range(20):
            self.dispatch.poll()
            _,requests=self.collect()
            if requests:
                break
            time.sleep(0.001)
        self.assertTrue(self.dispatch._pending[header.sequence].sent_once)
        self.clock.value+=200_000_000
        self.dispatch.poll()
        self.assertIsNone(self.dispatch._pending[header.sequence].deadline_ns)
        reply=message(141)
        self.reply_sequence+=1
        reply["header"].update(session_id=73,sequence=self.reply_sequence,transaction_id=header.transaction_id)
        reply["payload"].update(resource_sha256=resource["payload"]["resource_sha256"],stored_bytes=1000,next_offset=1000,complete=False,error="OK")
        self.emit(reply)
        self.dispatch.poll()
        self.assertEqual(self.dispatch.pending_count,0)
        self.assertEqual(self.dispatch.records[-2].reply,reply)
        self.assertEqual(self.dispatch.records[-1].kind,"COMPLETE")

    def test_lease_expiry_inside_poll_stops_before_actual_tx(self):
        self.setup_peer()
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        value=self.clock.value
        deadline=self.session._deadline_ns
        values=iter((value,value,deadline))
        self.session._clock=lambda:next(values,deadline)
        self.rejects("STALE_SESSION",self.dispatch.poll)
        self.assertEqual(self.collect()[0],[])
        self.assertEqual(self.dispatch.pending_count,0)
        self.assertEqual(self.dispatch.records[-1].error,"STALE_SESSION")

    def test_lease_expiry_after_actual_tx_keeps_wire_but_fails_run(self):
        self.setup_peer()
        self.dispatch.submit({"message_id":7,"payload":message(7)["payload"]},target_step=100)
        value=self.clock.value
        deadline=self.session._deadline_ns
        values=iter((value,value,value,deadline))
        self.session._clock=lambda:next(values,deadline)
        self.rejects("STALE_SESSION",self.dispatch.poll)
        self.assertEqual(len(self.collect()[0]),1)
        tx=[r for r in self.dispatch.records if r.kind=="TX"]
        self.assertEqual(tx[0].error,"STALE_SESSION")
        self.assertEqual(self.dispatch.pending_count,0)


for _name in ("test_interleaved_same_transaction_ack_matches_original_sequence",
              "test_nonblocking_typed_feedback_does_not_drop_other_pending_request",
              "test_matching_list_is_bounded_strict_and_unique",
              "test_matured_resource_reservations_do_not_burst_after_delayed_poll"):
    setattr(DispatcherTests,_name,None)


class ActualResourceDispatchTests(test_resource_udp.ResourceUDPTests):
    def test_two_actual_worker_resources_interleaved_complete_without_model_claim(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.dispatch"),"async dispatcher missing")
        from input_simulator.dispatch import UDPDispatcher
        from input_simulator.session import SourceSession
        from test_resource_udp import chunk
        self.network()
        test_source_session.ActualSourceSessionTests.poll_gateway(self)
        session=SourceSession(self.source,message(1)["payload"]["identity"],("STIMULUS",))
        session.open()
        dispatch=UDPDispatcher(session)
        self.addCleanup(dispatch.close)
        self.rejects("TARGET_MISSING",lambda:dispatch.enable_heartbeat(lambda:(0,0)))
        for data in (b"first-actual-object",b"second-actual-object"):
            dispatch.submit({"message_id":34,"payload":chunk(data)["payload"]},target_step=0)
        deadline=time.monotonic()+0.8
        while dispatch.pending_count and time.monotonic()<deadline:
            dispatch.poll()
            time.sleep(0.001)
        self.assertEqual(dispatch.pending_count,0)
        complete=[r.reply for r in dispatch.records if r.kind=="RX" and r.reply["message_id"]==141]
        self.assertEqual(len(complete),2)
        for reply in complete:
            self.assertTrue(reply["payload"]["complete"])
            path=self.store.root/"objects"/reply["payload"]["resource_sha256"]/"data.bin"
            self.assertIn(path.read_bytes(),(b"first-actual-object",b"second-actual-object"))
        self.assertFalse(session.capabilities["replacement_ready"])

    def test_large_earlier_group_is_admitted_before_later_small_group(self):
        from input_simulator.dispatch import UDPDispatcher
        from input_simulator.session import SourceSession
        from test_resource_udp import chunk
        self.network()
        test_source_session.ActualSourceSessionTests.poll_gateway(self)
        session=SourceSession(self.source,message(1)["payload"]["identity"],("STIMULUS",))
        session.open()
        dispatch=UDPDispatcher(session)
        self.addCleanup(dispatch.close)
        for data in (b"x"*32768,b"short-object"):
            dispatch.submit({"message_id":34,"payload":chunk(data)["payload"]},target_step=0)
        deadline=time.monotonic()+0.8
        while dispatch.pending_count and time.monotonic()<deadline:
            dispatch.poll()
            time.sleep(0.0005)
        self.assertEqual(dispatch.pending_count,0)
        rx=[r.reply for r in dispatch.records if r.kind=="RX" and r.reply["message_id"]==141]
        self.assertEqual(len(rx),2,(self.receiver.error_details,dispatch.records[-5:]))
        self.assertTrue(all(r["payload"]["complete"] and r["payload"]["error"]=="OK" for r in rx))
        self.assertEqual(self.receiver.errors["OUT_OF_ORDER"],0)

    def test_lost_unadmitted_earlier_sequence_is_failed_not_silently_renumbered(self):
        from input_simulator.dispatch import UDPDispatcher
        from input_simulator.session import SourceSession
        from test_resource_udp import chunk
        self.network()
        test_source_session.ActualSourceSessionTests.poll_gateway(self)
        session=SourceSession(self.source,message(1)["payload"]["identity"],("STIMULUS",))
        session.open()
        dispatch=UDPDispatcher(session)
        self.addCleanup(dispatch.close)
        original=self.receiver.receive
        dropped=[]
        def receive(packet,binding,**kw):
            fragment=self.source.wire.decode(packet,"UDP")
            if fragment.message_id==34 and fragment.header.sequence==2 and not dropped:
                dropped.append(packet)
                return ()
            return original(packet,binding,**kw)
        self.receiver.receive=receive
        self.addCleanup(setattr,self.receiver,"receive",original)
        for data in (b"dropped-first",b"admitted-second"):
            dispatch.submit({"message_id":34,"payload":chunk(data)["payload"]},target_step=0)
        deadline=time.monotonic()+0.8
        while dispatch.pending_count and time.monotonic()<deadline:
            dispatch.poll()
            time.sleep(0.001)
        self.assertEqual(dispatch.pending_count,0)
        self.assertEqual(len(dropped),1)
        first=[r for r in dispatch.records if r.header.sequence==2]
        self.assertEqual(first[-1].kind,"FAILED")
        self.assertEqual(first[-1].error,"OUT_OF_ORDER")
        tx=[r.wire_data for r in first if r.kind=="TX"]
        self.assertEqual(tx,[dropped[0],dropped[0]])
        second=[r for r in dispatch.records if r.header.sequence==3]
        self.assertEqual(second[-1].kind,"COMPLETE")


for _name in list(test_resource_udp.ResourceUDPTests.__dict__):
    if _name.startswith("test_"):
        setattr(ActualResourceDispatchTests,_name,None)


if __name__ == "__main__":
    unittest.main()
