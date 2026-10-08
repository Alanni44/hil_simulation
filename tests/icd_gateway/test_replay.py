import copy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import hashlib
import importlib.util
import unittest

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from common import EXPECTED, INTERFACES, message
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import Header, WireCodec
from test_capture import epb, idb, pcap, shb
from test_history import history, udp_packet


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.wire = WireCodec(cls.contract)

    def binding(self, **kw):
        from input_simulator.history import CaptureBinding
        fields = dict(stream_id="env", channel_id="ETH_0", clock_domain="PCAP:0:0",
                      capture_interface="interface-0", clock_id="clock-0")
        fields.update(kw)
        return CaptureBinding(**fields)

    def input(self, mid=7, *, mode="REENCODE", times=None, values=None):
        values = [message(mid)] if values is None else values
        packets = [udp_packet(f, feedback=value["message_id"] >= 128)
                   for value in values for f in self.wire.encode(value, "UDP")]
        times = list(range(len(packets))) if times is None else times
        raw = pcap([(1, t, p) for t, p in zip(times, packets)], nano=True)
        h = history(raw, sorted({v["message_id"] for v in values}), records=len(values), end=str(max(times)))
        h["policy"].update(mode=mode)
        if mode == "SESSION_REBUILD":
            h["policy"]["rewrite_fields"] = ["SESSION", "SEQUENCE", "TARGET_STEP", "TRANSACTION", "SOURCE_ENDPOINT", "CRC"]
        if mode == "RAW_VALIDATED":
            h["policy"].update(session_policy="CURRENT_VALID_SESSION", repeat_count=1, rewrite_fields=[])
        return raw, h

    def headers(self, h=Header(91, 101, 200, 301, 100), index=0):
        from input_simulator.replay import ReplayHeader
        return (ReplayHeader(index, h),)

    def prepare(self, raw, h, **kw):
        from input_simulator.replay import ReplayProcessor
        bindings = kw.pop("bindings", (self.binding(),))
        model_id = kw.pop("model_id", "quadrotor_hil")
        return ReplayProcessor(self.contract).prepare(raw, h, bindings, model_id=model_id,
                                                      declared_ids=tuple(self.contract.messages), **kw)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_replay_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.replay"), "three-mode processing missing")

    def test_raw_keeps_full_capture_and_application_bytes_without_authorizing(self):
        raw, h = self.input(mode="RAW_VALIDATED", times=[0, 100], values=[message(7), message(7)])
        result = self.prepare(raw, h)
        packet = result.packets[0]
        self.assertEqual(packet.original_capture_bytes, result.decoded.capture.packets[0].raw_bytes)
        self.assertEqual(packet.capture_bytes, packet.original_capture_bytes)
        self.assertEqual(packet.wire_data, result.decoded.capture.packets[0].payload)
        self.assertEqual(packet.changed_fields, ())
        self.assertEqual(result.packets[-1].relative_offset_ns, Fraction(100))
        self.assertFalse(result.execution_ready)
        self.assertIn("CURRENT_SESSION_SEQUENCE_TARGET_ENDPOINT_AUTHORIZATION", result.pending_checks)
        self.assertEqual(result.repeat_index, 0)
        self.rejects("STATE", result.require_execution_ready)

    def test_session_rebuild_retains_payload_and_recomputes_outer_checksums(self):
        raw, h = self.input(mode="SESSION_REBUILD")
        result = self.prepare(raw, h, headers=self.headers())
        packet = result.packets[0]
        fragment = self.wire.decode(packet.wire_data, "UDP")
        self.assertEqual(fragment.header, self.headers()[0].header)
        self.assertEqual(fragment.payload, self.wire.decode(result.decoded.capture.packets[0].payload, "UDP").payload)
        self.assertNotEqual(packet.original_sha256, packet.rebuilt_sha256)
        self.assertEqual(hashlib.sha256(packet.capture_bytes).hexdigest(), packet.rebuilt_sha256)
        ip = Ether(packet.capture_bytes)[IP]
        self.assertEqual(bytes(ip[UDP].payload), packet.wire_data)
        self.assertIsNotNone(ip.chksum)
        self.assertIsNotNone(ip[UDP].chksum)
        from input_simulator.capture import CaptureParser
        checked=CaptureParser().parse(pcap([(1,0,packet.capture_bytes)]),"PCAP")
        self.assertTrue(checked.packets[0].transport_checksum_verified)
        self.assertIn("CRC", packet.changed_fields)
        self.assertIn("RESET_MODEL_AND_CLEAR_QUEUES_NEW_SESSION", result.pending_checks)

    def test_reencode_generates_current_icd_and_payload_hash(self):
        raw, h = self.input()
        result = self.prepare(raw, h, headers=self.headers())
        packet = result.packets[0]
        fresh = message(7)
        fresh["header"] = self.headers()[0].header.__dict__ if hasattr(self.headers()[0].header, "__dict__") else {
            name: getattr(self.headers()[0].header, name) for name in fresh["header"]}
        self.assertEqual(packet.wire_data, self.wire.encode(fresh, "UDP")[0])
        self.assertEqual(packet.payload_sha256, result.decoded.records[0].payload_sha256)
        self.assertFalse(result.execution_ready)

    def test_raw_rejects_allocations_and_destinations_and_session_zero(self):
        from input_simulator.replay import ReplayDestination
        raw, h = self.input(mode="RAW_VALIDATED")
        self.rejects("STATE", lambda: self.prepare(raw, h, headers=self.headers()))
        self.rejects("STATE", lambda: self.prepare(raw, h, destinations=(ReplayDestination("ETH_0", "ETH_0"),)))
        raw, h = self.input(1, mode="RAW_VALIDATED")
        self.rejects("STALE_SESSION", lambda: self.prepare(raw, h))

    def test_rewrite_permissions_exactly_cover_real_changes(self):
        raw, h = self.input(mode="SESSION_REBUILD")
        for field in ("SESSION", "SEQUENCE", "TARGET_STEP", "TRANSACTION", "CRC"):
            altered = copy.deepcopy(h)
            altered["policy"]["rewrite_fields"].remove(field)
            self.rejects("AUTHORIZATION", lambda: self.prepare(raw, altered, headers=self.headers()))
        h["policy"]["rewrite_fields"] = []
        self.rejects("STALE_SESSION", lambda: self.prepare(raw, h, headers=self.headers(Header(**message(7)["header"]))))

    def test_explicit_endpoint_and_channel_changes_require_permission(self):
        from input_simulator.replay import ReplayDestination
        raw, h = self.input(mode="SESSION_REBUILD")
        dest = ReplayDestination("ETH_0", "ETH_1", ("127.0.0.1", 40002), ("127.0.0.1", 40000))
        result = self.prepare(raw, h, headers=self.headers(), destinations=(dest,))
        packet = result.packets[0]
        self.assertEqual(packet.channel_id, "ETH_1")
        ip = Ether(packet.capture_bytes)[IP]
        self.assertEqual((ip.src, ip.dst, ip[UDP].sport, ip[UDP].dport), ("127.0.0.1", "127.0.0.1", 40002, 40000))
        self.assertIn("SOURCE_ENDPOINT", packet.changed_fields)
        h["policy"]["rewrite_fields"].remove("SOURCE_ENDPOINT")
        self.rejects("AUTHORIZATION", lambda: self.prepare(raw, h, headers=self.headers(), destinations=(dest,)))

    def test_feedback_is_collected_not_injected_and_no_header_for_feedback(self):
        raw, h = self.input(values=[message(7), message(130)])
        h["streams"][0].update(message_ids=[7], records=1)
        fb = copy.deepcopy(h["streams"][0])
        fb.update(stream_id="feedback", message_ids=[130], records=1, direction="FROM_36")
        h["streams"].append(fb)
        bindings = (self.binding(), self.binding(stream_id="feedback"))
        result = self.prepare(raw, h, bindings=bindings, headers=self.headers())
        self.assertEqual(len(result.feedback), 1)
        self.assertEqual(len(result.packets), 1)
        self.assertEqual(result.feedback[0].message, message(130))

    def test_reversed_can_fragments_and_duplicates_keep_original_packet_order(self):
        from input_simulator.history import CaptureBinding
        frames = self.wire.encode(message(10), "CANFD")[::-1]
        frames.insert(1, frames[0])
        raw = b"".join(f"(1.{i:09d}) canfd0 {f.arbitration_id:03x}##5{f.data.hex()}\n".encode() for i, f in enumerate(frames))
        h = history(raw, [10], fmt="CAN_LOG", medium="CANFD", end=str(len(frames)-1))
        h["policy"]["mode"] = "SESSION_REBUILD"
        h["policy"]["rewrite_fields"] = ["SESSION", "SEQUENCE", "TARGET_STEP", "TRANSACTION", "CRC"]
        b = CaptureBinding("env", "CANFD_0", "CAN_LOG:canfd0", "canfd0", "clock-0")
        result = self.prepare(raw, h, bindings=(b,), headers=self.headers(Header(91, 101, 200, 301, 240)))
        self.assertEqual([p.original_packet_index for p in result.packets], list(range(len(frames))))
        assembler = Reassembler(self.contract)
        completed = None
        for i, packet in enumerate(result.packets):
            item = assembler.push(self.wire.decode(packet.wire_data, "CANFD"), channel="CANFD_0",
                                  direction="TO_36", authorized=True, now_ns=i)
            completed = item or completed
        self.assertEqual(completed.message["payload"], message(10)["payload"])

    def test_window_cannot_cut_a_logical_group(self):
        raw, h = self.input(10)
        # UDP environment is one frame; use two full records and select one.
        raw, h = self.input(values=[message(7), {**message(7), "header": {**message(7)["header"], "sequence": 3}}], times=[0, 100])
        h["policy"]["start_offset_ns"] = "50"
        result = self.prepare(raw, h, headers=self.headers(index=1))
        self.assertEqual(result.packets[0].relative_offset_ns, Fraction(50))
        from input_simulator.history import CaptureBinding
        frames = self.wire.encode(message(10), "CANFD")
        raw = b"".join(f"(1.{i:09d}) canfd0 {f.arbitration_id:03x}##5{f.data.hex()}\n".encode() for i, f in enumerate(frames))
        h = history(raw, [10], fmt="CAN_LOG", medium="CANFD", end=str(len(frames)-1))
        h["policy"]["start_offset_ns"] = "1"
        b = CaptureBinding("env", "CANFD_0", "CAN_LOG:canfd0", "canfd0", "clock-0")
        self.rejects("FRAGMENT", lambda: self.prepare(raw, h, bindings=(b,), headers=self.headers()))

    def test_exact_rates_and_repeat_metadata_no_timing_claim(self):
        for rate, expected in (("0.5X", Fraction(202)), ("1X", Fraction(101)), ("2X", Fraction(101,2)), ("4X", Fraction(101,4))):
            raw, h = self.input(times=[0, 101], values=[message(7), message(7)])
            h["policy"].update(execution_mode="OFFLINE", rate=rate, repeat_count=10000, repeat_gap_steps=7)
            headers = self.headers() + self.headers(index=1)
            result = self.prepare(raw, h, headers=headers, repeat_index=9999)
            self.assertEqual(result.packets[-1].relative_offset_ns, expected)
            self.assertEqual(result.repeat_gap_steps, 7)
            self.assertEqual(result.repeat_index, 9999)
            self.assertFalse(result.execution_ready)
        for index in (-1, 10000, True):
            self.rejects("SCHEMA", lambda: self.prepare(raw, h, headers=self.headers(), repeat_index=index))

    def test_allocations_strict_complete_and_standard_header_immutable(self):
        from input_simulator.replay import ReplayHeader
        raw, h = self.input()
        for headers, code in (((), "RESOURCE"), (self.headers(index=1), "RESOURCE"),
                              (self.headers()+self.headers(), "RESOURCE"),
                              (self.headers(Header(91, 1, 2, 3, 999)), "SCHEMA"),
                              ((ReplayHeader(True, self.headers()[0].header),), "RESOURCE")):
            self.rejects(code, lambda: self.prepare(raw, h, headers=headers))
        result = self.prepare(raw, h, headers=self.headers())
        with self.assertRaises(FrozenInstanceError):
            result.packets[0].channel_id = "ETH_3"

    def test_original_retry_preserves_new_identity_and_transaction_mapping(self):
        from input_simulator.replay import ReplayHeader
        raw, h = self.input(values=[message(7), message(7)], times=[0, 100])
        a = self.headers()[0].header
        result = self.prepare(raw, h, headers=(ReplayHeader(0,a), ReplayHeader(1,a)))
        self.assertEqual(result.packets[0].wire_data, result.packets[1].wire_data)
        self.rejects("SEQUENCE", lambda: self.prepare(raw, h, headers=(ReplayHeader(0,a), ReplayHeader(1,replace(a,sequence=102)))))
        second = message(7)
        second["header"]["sequence"] += 1
        raw, h = self.input(values=[message(7), second])
        self.rejects("SEQUENCE", lambda: self.prepare(raw, h, headers=(ReplayHeader(0,a), ReplayHeader(1,a))))
        self.rejects("STATE", lambda: self.prepare(raw, h, headers=(ReplayHeader(0,a), ReplayHeader(1,replace(a,sequence=102,transaction_id=302)))))
        self.rejects("STALE_SESSION", lambda: self.prepare(raw, h, headers=(ReplayHeader(0,a), ReplayHeader(1,replace(a,sequence=102,session_id=92)))))

    def test_auxiliary_rawbus_requires_explicit_udp_destination(self):
        from input_simulator.history import CaptureBinding
        from input_simulator.replay import ReplayDestination
        raw = b"(1) can0 600#0102 R\n"
        h = history(raw,[44],fmt="CAN_LOG",medium="CAN")
        b = CaptureBinding("env","CAN_0","CAN_LOG:can0","can0","clock-0","INBOUND")
        hdr = self.headers(Header(91,101,200,301,self.contract.entry(44)["valid_for_ms"]))
        self.rejects("UNSUPPORTED", lambda: self.prepare(raw,h,bindings=(b,),headers=hdr))
        result = self.prepare(raw,h,bindings=(b,),headers=hdr,destinations=(ReplayDestination("CAN_0","ETH_0"),))
        assembled = Reassembler(self.contract).push(self.wire.decode(result.packets[0].wire_data, "UDP"), channel="ETH_0",
                                                    direction="TO_36",authorized=True,now_ns=0)
        self.assertEqual(assembled.message["message_id"],44)
        self.assertEqual(assembled.message["payload"]["data_hex"],"0102")
        self.assertIsNone(result.packets[0].capture_bytes)

    def test_destinations_are_closed_unique_and_unicast(self):
        from input_simulator.replay import ReplayDestination, ReplayProcessor
        raw,h=self.input()
        for destinations, code in (((ReplayDestination("ETH_0","ETH_0"),)*2,"RESOURCE"),
                                    ((ReplayDestination("ETH_1","ETH_1"),),"RESOURCE"),
                                    ((ReplayDestination("ETH_0","CANFD_0"),),"UNSUPPORTED"),
                                    ((ReplayDestination("ETH_0","ETH_0",("224.1.2.3",1),("127.0.0.1",2)),),"SCHEMA")):
            self.rejects(code,lambda:self.prepare(raw,h,headers=self.headers(),destinations=destinations))
        self.rejects("CAPACITY", lambda: ReplayProcessor(self.contract,max_packets=True))
        self.rejects("CAPACITY", lambda: ReplayProcessor(self.contract,max_packets=0))

    def test_endpoint_only_rebuild_requires_outer_crc_permission(self):
        from input_simulator.replay import ReplayDestination
        raw,h=self.input(mode="SESSION_REBUILD")
        old=Header(**message(7)["header"])
        # A changed session is mandatory; keep every other field unchanged.
        headers=self.headers(replace(old,session_id=91))
        h["policy"]["rewrite_fields"]=["SESSION","SOURCE_ENDPOINT"]
        dest=(ReplayDestination("ETH_0","ETH_0",("127.0.0.1",40002),("127.0.0.1",40000)),)
        self.rejects("AUTHORIZATION",lambda:self.prepare(raw,h,headers=headers,destinations=dest))

    def test_repeat_headers_must_not_reuse_any_captured_session(self):
        raw,h=self.input()
        self.rejects("STALE_SESSION",lambda:self.prepare(raw,h,headers=self.headers(Header(**message(7)["header"]))))

    def test_every_replayable_formal_input_all_modes_payload_unchanged(self):
        for mid,entry in self.contract.messages.items():
            if entry["direction"]!="TO_36" or mid==1:
                continue
            for mode in ("RAW_VALIDATED","REENCODE","SESSION_REBUILD"):
                raw,h=self.input(mid,mode=mode)
                allocation=() if mode=="RAW_VALIDATED" else self.headers(Header(91,101,200,301,entry["valid_for_ms"]))
                result=self.prepare(raw,h,headers=allocation,model_id=entry["model_ids"][0])
                assembler=Reassembler(self.contract)
                completed=None
                for i,p in enumerate(result.packets):
                    completed=assembler.push(self.wire.decode(p.wire_data,"UDP"),channel=p.channel_id,
                                             direction="TO_36",authorized=True,now_ns=i) or completed
                with self.subTest(mid=mid,mode=mode):
                    self.assertEqual(completed.message["payload"],message(mid)["payload"])
                    self.assertFalse(result.execution_ready)

    def test_small_output_budget_is_enforced(self):
        from input_simulator.replay import ReplayProcessor
        raw,h=self.input()
        self.rejects("CAPACITY",lambda:ReplayProcessor(self.contract,max_output_bytes=1).prepare(
            raw,h,(self.binding(),),model_id="quadrotor_hil",declared_ids=(7,),headers=self.headers()))

    def test_all_13_canfd_inputs_each_mode_and_payload_hash(self):
        from input_simulator.history import CaptureBinding
        for mid,entry in self.contract.messages.items():
            if entry["direction"]!="TO_36" or "CANFD" not in entry["transports"]:
                continue
            frames=self.wire.encode(message(mid),"CANFD")[::-1]
            raw=b"".join(f"(1.{i:09d}) canfd0 {f.arbitration_id:03x}##5{f.data.hex()}\n".encode() for i,f in enumerate(frames))
            for mode in ("RAW_VALIDATED","REENCODE","SESSION_REBUILD"):
                h=history(raw,[mid],fmt="CAN_LOG",medium="CANFD",end=str(len(frames)-1))
                h["policy"]["mode"]=mode
                if mode=="RAW_VALIDATED":
                    h["policy"].update(session_policy="CURRENT_VALID_SESSION",rewrite_fields=[])
                else:
                    h["policy"]["rewrite_fields"]=["SESSION","SEQUENCE","TARGET_STEP","TRANSACTION","CRC"]
                b=CaptureBinding("env","CANFD_0","CAN_LOG:canfd0","canfd0","clock-0")
                allocation=() if mode=="RAW_VALIDATED" else self.headers(Header(91,101,200,301,entry["valid_for_ms"]))
                result=self.prepare(raw,h,bindings=(b,),headers=allocation,model_id=entry["model_ids"][0])
                assembler=Reassembler(self.contract)
                completed=None
                for i,p in enumerate(result.packets):
                    completed=assembler.push(self.wire.decode(p.wire_data,"CANFD"),channel=p.channel_id,
                                             direction="TO_36",authorized=True,now_ns=i) or completed
                self.assertEqual(completed.message["payload"],message(mid)["payload"])
                self.assertEqual([p.original_packet_index for p in result.packets],list(range(len(frames))))

    def test_three_auxiliary_media_use_original_rawbus_payload(self):
        from input_simulator.history import CaptureBinding
        from input_simulator.replay import ReplayDestination
        for medium,raw,channel,domain,interface in (
                ("CAN",b"(1) can0 600#0102 R\n","CAN_0","CAN_LOG:can0","can0"),
                ("CANFD",b"(1) canfd0 600##50102 R\n","CANFD_0","CAN_LOG:canfd0","canfd0"),
                ("ETHERNET",pcap([(1,0,udp_packet(b"\x01\x02",port=36150))]),"ETH_0","PCAP:0:0","interface-0")):
            fmt="PCAP" if medium=="ETHERNET" else "CAN_LOG"
            h=history(raw,[44],fmt=fmt,medium=medium)
            b=CaptureBinding("env",channel,domain,interface,"clock-0","INBOUND")
            result=self.prepare(raw,h,bindings=(b,),headers=self.headers(Header(91,101,200,301,1000)),
                                destinations=(ReplayDestination(channel,"ETH_0"),))
            assembler=Reassembler(self.contract)
            completed=None
            for i,p in enumerate(result.packets):
                completed=assembler.push(self.wire.decode(p.wire_data,"UDP"),channel=p.channel_id,
                                         direction="TO_36",authorized=True,now_ns=i) or completed
            self.assertEqual(completed.message["payload"],result.decoded.records[0].stimulus["payload"])

    def test_cross_domain_interleaving_keeps_file_order_not_time_sort(self):
        from input_simulator.history import CaptureBinding
        frame=udp_packet(self.wire.encode(message(7),"UDP")[0])
        raw=shb()+idb(1,name=b"eth0")+idb(1,name=b"eth1")
        raw+=epb(frame,interface=0,ticks=1000000100)+epb(frame,interface=1,ticks=1000000000)
        h=history(raw,[7],fmt="PCAPNG",records=2,end="100")
        bindings=tuple(CaptureBinding("env","ETH_0",f"PCAPNG:0:{i}",f"eth{i}","clock-0") for i in range(2))
        result=self.prepare(raw,h,bindings=bindings,headers=self.headers()+self.headers(index=1))
        self.assertEqual([p.original_packet_index for p in result.packets],[0,1])
        self.assertEqual([p.relative_offset_ns for p in result.packets],[100,0])
        self.assertFalse(result.execution_ready)

    def test_deployment_route_rejects_unspecified_and_broadcast_addresses(self):
        from input_simulator.replay import ReplayDestination
        raw,h=self.input()
        for source,receiver in ((("0.0.0.0",40002),("127.0.0.1",40000)),
                                (("127.0.0.1",40002),("255.255.255.255",40000)),
                                (("255.255.255.255",40002),("127.0.0.1",40000))):
            self.rejects("SCHEMA",lambda:self.prepare(raw,h,headers=self.headers(),destinations=(
                ReplayDestination("ETH_0","ETH_0",source,receiver),)))

    def test_signed_zero_conflict_is_not_an_identical_original_retry(self):
        negative=message(10)
        positive=message(10)
        negative["payload"]["wind_n_mps"]=-0.0
        positive["payload"]["wind_n_mps"]=0.0
        raw,h=self.input(10,mode="SESSION_REBUILD",values=[negative,positive])
        headers=self.headers(Header(91,101,200,301,240))+self.headers(Header(91,101,200,301,240),index=1)
        self.rejects("SEQUENCE",lambda:self.prepare(raw,h,headers=headers))

    def test_auxiliary_output_hash_describes_formal_payload_not_raw_bus_bytes(self):
        from input_simulator.history import CaptureBinding
        from input_simulator.replay import ReplayDestination
        raw=b"(1) can0 600#0102 R\n"
        h=history(raw,[44],fmt="CAN_LOG",medium="CAN")
        b=CaptureBinding("env","CAN_0","CAN_LOG:can0","can0","clock-0","INBOUND")
        result=self.prepare(raw,h,bindings=(b,),headers=self.headers(Header(91,101,200,301,1000)),
                            destinations=(ReplayDestination("CAN_0","ETH_0"),))
        packet=result.packets[0]
        self.assertEqual(packet.original_payload_sha256,hashlib.sha256(b"\x01\x02").hexdigest())
        encoded=self.wire.payload_codec.encode(44,result.decoded.records[0].stimulus["payload"])
        self.assertEqual(packet.payload_sha256,hashlib.sha256(encoded).hexdigest())

    def test_preserved_signed_zero_payload_hash_is_actual_wire_hash(self):
        value=message(10)
        value["payload"]["wind_n_mps"]=-0.0
        for mode in ("RAW_VALIDATED","SESSION_REBUILD"):
            raw,h=self.input(10,mode=mode,values=[value])
            headers=() if mode=="RAW_VALIDATED" else self.headers(Header(91,101,200,301,240))
            result=self.prepare(raw,h,headers=headers)
            packet=result.packets[0]
            payload=self.wire.decode(packet.wire_data,"UDP").payload
            self.assertEqual(packet.payload_sha256,hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
