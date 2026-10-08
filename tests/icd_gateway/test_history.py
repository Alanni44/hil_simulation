import copy
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import unittest

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from common import EXPECTED, INTERFACES, message
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.wire import WireCodec
from test_capture import epb, idb, pcap, shb, socketcan
from test_source_inputs import history_input


def udp_packet(data, *, feedback=False, channel=0, port=None):
    src = f"10.36.{channel}.20" if feedback else f"10.36.{channel}.10"
    dst = f"10.36.{channel}.10" if feedback else f"10.36.{channel}.20"
    return bytes(Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02") /
                 IP(src=src, dst=dst, ttl=32) /
                 UDP(sport=36100 if feedback else 36102,
                     dport=(36101 if feedback else 36100) if port is None else port) / data)


def history(raw, mids, *, fmt="PCAP", records=1, medium="ETHERNET", direction="TO_36", end="0"):
    value, _ = history_input(raw)
    h = value["history"]
    h["resource"].update(format=fmt, encoding="UTF8" if fmt == "CAN_LOG" else "BINARY")
    h["streams"][0].update(message_ids=mids, records=records, original_channel=medium,
                           direction=direction, clock="UTC", epoch_ns="1000000000")
    h["policy"]["end_offset_ns"] = end
    return h


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.wire = WireCodec(cls.contract)

    def binding(self, **updates):
        from input_simulator.history import CaptureBinding
        fields = dict(stream_id="env", channel_id="ETH_0", clock_domain="PCAP:0:0",
                      capture_interface="interface-0", clock_id="clock-0", raw_to36_capture_direction=None)
        fields.update(updates)
        return CaptureBinding(**fields)

    def decode(self, raw, h, bindings=None, *, model_id="quadrotor_hil", **limits):
        from input_simulator.history import HistoryDecoder
        return HistoryDecoder(self.contract, **limits).decode(
            raw, h, (self.binding(),) if bindings is None else bindings,
            model_id=model_id, declared_ids=tuple(self.contract.messages))

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_decoder_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.history"), "logical history decoder missing")

    def test_all_59_messages_decode_from_actual_udp_capture(self):
        for mid, entry in self.contract.messages.items():
            model = entry["model_ids"][0]
            raw = pcap([(1, i, udp_packet(frame, feedback=entry["direction"] == "FROM_36"))
                        for i, frame in enumerate(self.wire.encode(message(mid), "UDP"))], nano=True)
            h = history(raw, [mid], direction=entry["direction"])
            from input_simulator.history import HistoryDecoder
            result = HistoryDecoder(self.contract).decode(raw, h, (self.binding(),), model_id=model, declared_ids=(mid,))
            with self.subTest(mid=mid):
                record = result.records[0]
                self.assertEqual(record.message, message(mid))
                self.assertEqual(record.packet_indices, tuple(range(len(result.capture.packets))))
                self.assertEqual(record.offset_ns, 0)
                self.assertEqual(record.completion_offset_ns, len(result.capture.packets) - 1)
                if entry["direction"] == "TO_36":
                    self.assertEqual(record.stimulus, {"message_id": mid, "payload": message(mid)["payload"]})
                else:
                    self.assertIsNone(record.stimulus)
                self.assertTrue(result.history_decoded)
                self.assertFalse(result.execution_ready)
                self.assertIsNone(result.complete_capture)

    def test_all_13_canfd_messages_use_original_formal_codec_and_order(self):
        for mid, entry in self.contract.messages.items():
            if "CANFD" not in entry["transports"]:
                continue
            frames = self.wire.encode(message(mid), "CANFD")[::-1]
            raw = b"".join(f"(1.{i:09d}) canfd0 {f.arbitration_id:03x}##5{f.data.hex()}\n".encode()
                           for i, f in enumerate(frames))
            h = history(raw, [mid], fmt="CAN_LOG", medium="CANFD", direction=entry["direction"])
            b = self.binding(channel_id="CANFD_0", clock_domain="CAN_LOG:canfd0", capture_interface="canfd0")
            result = self.decode(raw, h, (b,), model_id=entry["model_ids"][0])
            self.assertEqual(result.records[0].message, message(mid))
            self.assertEqual(tuple(p.raw_bytes for p in result.capture.packets), tuple(raw.splitlines(keepends=True)))

    def test_binding_required_not_guessed_from_name_or_rxtx(self):
        raw = pcap([(1, 0, udp_packet(self.wire.encode(message(7), "UDP")[0]))])
        h = history(raw, [7])
        self.rejects("RESOURCE", lambda: self.decode(raw, h, ()))
        self.rejects("RESOURCE", lambda: self.decode(raw, h, (self.binding(capture_interface="eth0"),)))
        self.rejects("RESOURCE", lambda: self.decode(raw, h, (self.binding(), self.binding())))

    def test_crc_direction_endpoint_medium_and_model_gates(self):
        data = self.wire.encode(message(7), "UDP")[0]
        raw = pcap([(1, 0, udp_packet(data))])
        h = history(raw, [7])
        bad = data[:-1] + bytes([data[-1] ^ 1])
        corrupt = pcap([(1, 0, udp_packet(bad))])
        self.rejects("CRC", lambda: self.decode(corrupt, history(corrupt, [7])))
        self.rejects("AUTHORIZATION", lambda: self.decode(raw, history(raw, [7], direction="FROM_36")))
        wrong = pcap([(1, 0, udp_packet(data, feedback=True))])
        self.rejects("AUTHORIZATION", lambda: self.decode(wrong, history(wrong, [7])))
        self.rejects("RESOURCE", lambda: self.decode(raw, h, (self.binding(channel_id="CANFD_0"),)))
        fixed = message(19)
        other = pcap([(1, 0, udp_packet(self.wire.encode(fixed, "UDP")[0]))])
        self.rejects("MODEL", lambda: self.decode(other, history(other, [19])))

    def test_counts_ids_epoch_window_and_clock_reversal(self):
        frame = udp_packet(self.wire.encode(message(7), "UDP")[0])
        raw = pcap([(1, 0, frame)])
        for changes, code in (({"records": 2}, "RESOURCE"), ({"message_ids": [8]}, "RESOURCE"),
                              ({"epoch_ns": "1000000001"}, "CLOCK_UNSYNC")):
            h = history(raw, [7])
            h["streams"][0].update(changes)
            self.rejects(code, lambda: self.decode(raw, h))
        self.rejects("RESOURCE", lambda: self.decode(raw, history(raw, [7], end="1")))
        reversed_raw = pcap([(1, 100, frame), (1, 0, frame)], nano=True)
        self.rejects("CLOCK_UNSYNC", lambda: self.decode(reversed_raw, history(reversed_raw, [7], records=2)))

    def test_raw_bus_can_fd_and_ethernet_are_stimuli_without_fake_headers(self):
        for medium, raw, channel, domain, interface in (
                ("CAN", b"(1) can0 600#0102 R\n", "CAN_0", "CAN_LOG:can0", "can0"),
                ("CANFD", b"(1) canfd0 600##50102 R\n", "CANFD_0", "CAN_LOG:canfd0", "canfd0"),
                ("ETHERNET", pcap([(1, 0, udp_packet(b"\x01\x02", port=36150))]), "ETH_0", "PCAP:0:0", "interface-0")):
            fmt = "PCAP" if medium == "ETHERNET" else "CAN_LOG"
            b = self.binding(channel_id=channel, clock_domain=domain, capture_interface=interface,
                             raw_to36_capture_direction="INBOUND")
            result = self.decode(raw, history(raw, [44], medium=medium, fmt=fmt), (b,))
            record = result.records[0]
            self.assertIsNone(record.message)
            self.assertEqual(record.stimulus["message_id"], 44)
            self.assertEqual(record.stimulus["payload"]["medium"], medium)
            self.assertNotIn("header", record.stimulus)
            self.assertFalse(result.execution_ready)

    def test_raw_bus_without_direction_or_with_unsafe_frames_is_rejected(self):
        b = self.binding(channel_id="CAN_0", clock_domain="CAN_LOG:can0", capture_interface="can0")
        raw = b"(1) can0 600#01 R\n"
        self.rejects("AUTHORIZATION", lambda: self.decode(raw, history(raw, [44], fmt="CAN_LOG", medium="CAN"), (b,)))
        b = self.binding(channel_id="CAN_0", clock_domain="CAN_LOG:can0", capture_interface="can0",
                         raw_to36_capture_direction="INBOUND")
        for raw in (b"(1) can0 600#01\n", b"(1) can0 600#01 T\n", b"(1) can0 600#R8 R\n",
                    b"(1) can0 500#01 R\n", b"(1) can0 00000600#01 R\n"):
            with self.assertRaises(ICDError):
                self.decode(raw, history(raw, [44], fmt="CAN_LOG", medium="CAN"), (b,))

    def test_missing_fragment_or_timeout_cannot_be_a_complete_record(self):
        frames = self.wire.encode(message(10), "CANFD")
        def log(chosen, gap=1):
            return b"".join(f"(1.{i * gap:09d}) canfd0 {f.arbitration_id:03x}##5{f.data.hex()}\n".encode()
                            for i, f in enumerate(chosen))
        b = self.binding(channel_id="CANFD_0", clock_domain="CAN_LOG:canfd0", capture_interface="canfd0")
        raw = log(frames[:-1])
        self.rejects("FRAGMENT", lambda: self.decode(raw, history(raw, [10], fmt="CAN_LOG", medium="CANFD"), (b,)))
        raw = log(frames, gap=20_000_000)
        self.rejects("TIMEOUT", lambda: self.decode(raw, history(raw, [10], fmt="CAN_LOG", medium="CANFD"), (b,)))

    def test_capture_and_record_are_immutable_and_repeated_full_transmissions_preserved(self):
        packet = udp_packet(self.wire.encode(message(7), "UDP")[0])
        raw = pcap([(1, 0, packet), (1, 1000, packet)], nano=True)
        result = self.decode(raw, history(raw, [7], records=2, end="1000"))
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[1].offset_ns, 1000)
        record = result.records[0]
        detached = record.message
        detached["payload"].clear()
        self.assertEqual(record.message, message(7))
        with self.assertRaises(FrozenInstanceError):
            record.offset_ns = 99
        self.assertEqual(record.payload_sha256, hashlib.sha256(self.wire.payload_codec.encode(7, message(7)["payload"])).hexdigest())

    def test_different_domains_never_splice_fragments(self):
        frames = self.wire.encode(message(10), "CANFD")
        raw = shb() + idb(227, name=b"canfd0") + idb(227, name=b"canfd1")
        raw += epb(socketcan(frames[0].data, fd=True, can_id=frames[0].arbitration_id), interface=0, ticks=1000000000)
        for i, f in enumerate(frames[1:]):
            raw += epb(socketcan(f.data, fd=True, can_id=f.arbitration_id), interface=1, ticks=1000000001 + i)
        h = history(raw, [10], fmt="PCAPNG", medium="CANFD")
        bindings = tuple(self.binding(channel_id=f"CANFD_{i}", clock_domain=f"PCAPNG:0:{i}",
                                      capture_interface=f"canfd{i}") for i in range(2))
        self.rejects("FRAGMENT", lambda: self.decode(raw, h, bindings))

    def test_binding_document_is_closed_and_clock_identity_is_explicit(self):
        from input_simulator.history import CaptureBinding
        good = {"stream_id": "env", "channel_id": "ETH_0", "clock_domain": "PCAP:0:0",
                "capture_interface": "interface-0", "clock_id": "clock-0", "raw_to36_capture_direction": None}
        self.assertEqual(CaptureBinding.from_document(good), self.binding())
        for value in ({**good, "private": 1}, {k: v for k, v in good.items() if k != "clock_id"},
                      {**good, "clock_id": ""}, {**good, "raw_to36_capture_direction": "TO_36"}):
            self.rejects("RESOURCE", lambda: CaptureBinding.from_document(value))

    def test_capacity_baseline_and_unknown_or_truncated_transport(self):
        packet = udp_packet(self.wire.encode(message(7), "UDP")[0])
        raw = pcap([(1, 0, packet)])
        h = history(raw, [7])
        h["decoder_baseline_sha256"] = "0" * 64
        self.rejects("HASH", lambda: self.decode(raw, h))
        self.rejects("CAPACITY", lambda: self.decode(raw, history(raw, [7]), max_bytes=16))
        self.rejects("CAPACITY", lambda: self.decode(raw, history(raw, [7]), max_records=True))
        bad = pcap([(1, 0, packet[:20])], wirelen=100)
        h = history(bad, [7])
        self.rejects("RESOURCE", lambda: self.decode(bad, h))
        h["policy"].update(execution_mode="OFFLINE", rate="2X")
        self.rejects("FRAGMENT", lambda: self.decode(bad, h))

    def test_missing_model_cannot_bypass_original_model_gate(self):
        raw = pcap([(1, 0, udp_packet(self.wire.encode(message(7), "UDP")[0]))])
        for model in (None, "unknown", True):
            self.rejects("MODEL", lambda: self.decode(raw, history(raw, [7]), model_id=model))

    def test_multidomain_shared_clock_and_bidirectional_streams(self):
        forward, reply = message(7), message(130)
        raw = shb() + idb(name=b"eth0") + idb(227, name=b"canfd0")
        raw += epb(udp_packet(self.wire.encode(forward, "UDP")[0]), ticks=1000000000)
        for i, f in enumerate(self.wire.encode(reply, "CANFD")):
            raw += epb(socketcan(f.data, fd=True, can_id=f.arbitration_id), interface=1, ticks=1000000010 + i)
        h = history(raw, [7], fmt="PCAPNG")
        feedback = copy.deepcopy(h["streams"][0])
        feedback.update(stream_id="feedback", original_channel="CANFD", direction="FROM_36", message_ids=[130])
        h["streams"].append(feedback)
        bindings = (self.binding(clock_domain="PCAPNG:0:0", capture_interface="eth0"),
                    self.binding(stream_id="feedback", channel_id="CANFD_0", clock_domain="PCAPNG:0:1",
                                 capture_interface="canfd0"))
        result = self.decode(raw, h, bindings)
        self.assertEqual([r.direction for r in result.records], ["TO_36", "FROM_36"])
        self.assertIsNone(result.records[-1].stimulus)
        separate = (bindings[0], self.binding(stream_id="feedback", channel_id="CANFD_0", clock_domain="PCAPNG:0:1",
                                             capture_interface="canfd0", clock_id="independent-clock"))
        self.rejects("CLOCK_UNSYNC", lambda: self.decode(raw, h, separate))
        h["streams"][-1]["epoch_ns"] = "0"
        self.rejects("CLOCK_UNSYNC", lambda: self.decode(raw, h, bindings))

    def test_cross_domain_file_order_is_not_mistaken_for_domain_clock_reversal(self):
        packet = self.wire.encode(message(7), "UDP")[0]
        raw = shb() + idb(name=b"eth0") + idb(name=b"eth1")
        raw += epb(udp_packet(packet), interface=0, ticks=1000000100)
        raw += epb(udp_packet(packet, channel=1), interface=1, ticks=1000000000)
        h = history(raw, [7], fmt="PCAPNG", records=2, end="100")
        bindings = tuple(self.binding(channel_id=f"ETH_{i}", clock_domain=f"PCAPNG:0:{i}",
                                      capture_interface=f"eth{i}") for i in range(2))
        result = self.decode(raw, h, bindings)
        self.assertEqual([r.offset_ns for r in result.records], [100, 0])
        self.assertEqual([r.packet_indices for r in result.records], [(0,), (1,)])
        self.assertFalse(result.execution_ready)

    def test_model_step_clock_requires_exact_header_provenance(self):
        value = message(7)
        step_ns = value["header"]["target_step"] * 1000000
        packet = udp_packet(self.wire.encode(value, "UDP")[0])
        raw = pcap([(1 + step_ns // 1000000000, step_ns % 1000000000, packet)], nano=True)
        h = history(raw, [7], end=str(step_ns))
        h["streams"][0]["clock"] = "MODEL_STEP"
        h["policy"]["start_offset_ns"] = str(step_ns)
        self.assertEqual(self.decode(raw, h).records[0].offset_ns, step_ns)
        h["streams"][0]["epoch_ns"] = "999999999"
        self.rejects("CLOCK_UNSYNC", lambda: self.decode(raw, h))

    def test_loss_never_grants_complete_capture_and_extra_policy_is_checked(self):
        import struct
        from test_capture import option
        raw = shb() + idb(name=b"eth0") + epb(udp_packet(self.wire.encode(message(7), "UDP")[0]),
                                              ticks=1000000000, opts=option(4, struct.pack("<Q", 1)))
        h = history(raw, [7], fmt="PCAPNG")
        b = self.binding(clock_domain="PCAPNG:0:0", capture_interface="eth0")
        self.rejects("RESOURCE", lambda: self.decode(raw, h, (b,)))
        h["policy"].update(execution_mode="OFFLINE", rate="2X")
        result = self.decode(raw, h, (b,))
        self.assertFalse(result.complete_capture)
        self.assertFalse(result.clock_measured)
        self.assertFalse(result.execution_ready)
        online = copy.deepcopy(h["policy"])
        online.update(execution_mode="ONLINE", rate="1X")
        from input_simulator.history import HistoryDecoder
        self.rejects("RESOURCE", lambda: HistoryDecoder(self.contract).check_policy(online, result))

    def test_no_mutation_or_fake_headers_in_auxiliary_raw_modes(self):
        raw = b"(1) can0 600#01 R\n"
        b = self.binding(channel_id="CAN_0", clock_domain="CAN_LOG:can0", capture_interface="can0",
                         raw_to36_capture_direction="INBOUND")
        for mode in ("RAW_VALIDATED", "SESSION_REBUILD"):
            h = history(raw, [44], fmt="CAN_LOG", medium="CAN")
            h["policy"]["mode"] = mode
            if mode == "RAW_VALIDATED":
                h["policy"]["session_policy"] = "CURRENT_VALID_SESSION"
            self.rejects("UNSUPPORTED", lambda: self.decode(raw, h, (b,)))

    def test_duplicate_rewrite_fields_are_rejected_at_public_decoder_boundary(self):
        raw = pcap([(1, 0, udp_packet(self.wire.encode(message(7), "UDP")[0]))])
        h = history(raw, [7])
        h["policy"].update(mode="SESSION_REBUILD", rewrite_fields=["SESSION", "SESSION"])
        self.rejects("RESOURCE", lambda: self.decode(raw, h))

    def test_original_64_slot_capacity_not_bypassed_by_history_group_tracking(self):
        fragments = []
        for sequence in range(1, 66):
            value = message(10)
            value["header"]["sequence"] = sequence
            f = self.wire.encode(value, "CANFD")[0]
            fragments.append(f"(1) canfd0 {f.arbitration_id:03x}##5{f.data.hex()}\n".encode())
        raw = b"".join(fragments)
        b = self.binding(channel_id="CANFD_0", clock_domain="CAN_LOG:canfd0", capture_interface="canfd0")
        self.rejects("BUFFER_FULL", lambda: self.decode(raw, history(raw, [10], fmt="CAN_LOG", medium="CANFD"), (b,)))

    def test_formal_raw_and_rebuild_modes_decode_but_never_authorize_existing_session(self):
        raw = pcap([(1, 0, udp_packet(self.wire.encode(message(7), "UDP")[0]))])
        for mode in ("RAW_VALIDATED", "SESSION_REBUILD"):
            h = history(raw, [7])
            h["policy"]["mode"] = mode
            if mode == "RAW_VALIDATED":
                h["policy"]["session_policy"] = "CURRENT_VALID_SESSION"
            result = self.decode(raw, h)
            self.assertEqual(result.records[0].message, message(7))
            self.assertFalse(result.execution_ready)

    def test_unknown_tcp_and_video_do_not_become_udp_business_inputs(self):
        from test_capture import ethernet
        raw = pcap([(1, 0, ethernet(tcp=True))])
        self.rejects("UNSUPPORTED", lambda: self.decode(raw, history(raw, [7])))
        video = pcap([(1, 0, udp_packet(b"HIV1" + b"\x00" * 50, port=36110))])
        self.rejects("AUTHORIZATION", lambda: self.decode(video, history(video, [7])))
