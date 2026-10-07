from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from common import message
from icd_runtime.errors import ICDError
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import Header
from input_simulator.capture import CaptureParser
from input_simulator.history import CaptureBinding
import test_replay
from test_history import history


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_replay.ReplayTests.setUpClass()
        cls.contract = test_replay.ReplayTests.contract
        cls.wire = test_replay.ReplayTests.wire

    def setUp(self):
        self.helper = test_replay.ReplayTests()

    def exporter(self, **limits):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.replay_export"), "complete original tool export missing")
        from input_simulator.replay_export import ReplayExporter
        return ReplayExporter(self.contract, **limits)

    def binding(self, channel="ETH_0", interface="eth0", **kw):
        self.exporter()
        from input_simulator.replay_export import ExportBinding
        return ExportBinding(channel, interface, **kw)

    def prepared(self, **kw):
        raw, h = self.helper.input(**kw)
        headers = () if h["policy"]["mode"] == "RAW_VALIDATED" else self.helper.headers()
        return self.helper.prepare(raw, h, headers=headers)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as error:
            action()
        self.assertEqual(error.exception.code, code)

    def test_complete_pcap_three_modes_original_frame_payload_and_exact_time(self):
        epoch = 1770000000000000001
        for mode in ("RAW_VALIDATED", "REENCODE", "SESSION_REBUILD"):
            prepared = self.prepared(mode=mode)
            bundle = self.exporter().export(prepared, (self.binding(),), epoch_ns=epoch)
            self.assertEqual(len(bundle.files), 1)
            item = bundle.files[0]
            actual = CaptureParser().parse(item.data, "PCAP")
            self.assertEqual(actual.packets[0].timestamp_ns, epoch)
            self.assertEqual(actual.packets[0].payload, prepared.packets[0].wire_data)
            self.assertEqual(actual.packets[0].raw_bytes, prepared.packets[0].capture_bytes)
            self.assertTrue(actual.packets[0].transport_checksum_verified)
            self.assertEqual(item.sha256, hashlib.sha256(item.data).hexdigest())
            self.assertEqual(item.channel_id, "ETH_0")
            self.assertEqual(item.interface, "eth0")
            self.assertFalse(bundle.execution_ready)
            self.assertIsNone(item.tool_timing_compatible)
            with self.assertRaises(FrozenInstanceError):
                item.data = b"changed"

    def test_all_11_can_input_frames_reassemble_after_full_log_export(self):
        tested = 0
        for mid, entry in self.contract.messages.items():
            if entry["direction"] != "TO_36" or "CANFD" not in entry["transports"]:
                continue
            tested += 1
            frames = self.wire.encode(message(mid), "CANFD")
            raw = b"".join(f"(1.{i*1000:09d}) canfd0 {f.arbitration_id:03X}##5{f.data.hex()}\n".encode() for i, f in enumerate(frames))
            h = history(raw, [mid], fmt="CAN_LOG", medium="CANFD", end=str((len(frames)-1)*1000))
            h["policy"]["mode"] = "SESSION_REBUILD"
            h["policy"]["rewrite_fields"] = ["SESSION", "SEQUENCE", "TARGET_STEP", "TRANSACTION", "CRC"]
            prepared = self.helper.prepare(raw, h, bindings=(CaptureBinding("env", "CANFD_0", "CAN_LOG:canfd0", "canfd0", "clock-0"),),
                                            headers=self.helper.headers(Header(91, 101, 200, 301, entry["valid_for_ms"])), model_id=entry["model_ids"][0])
            bundle = self.exporter().export(prepared, (self.binding("CANFD_0", "canfd0"),), epoch_ns=1000000000)
            actual = CaptureParser().parse(bundle.files[0].data, "CAN_LOG")
            self.assertTrue(bundle.files[0].tool_timing_compatible)
            self.assertEqual(len(actual.packets), len(frames))
            assembler = Reassembler(self.contract)
            result = None
            for i, packet in enumerate(actual.packets):
                from icd_runtime.wire import CANFrame
                c = packet.can
                frame = CANFrame(c.arbitration_id, c.data, c.is_fd, c.bitrate_switch, c.is_extended_id, c.is_remote_frame)
                result = assembler.push(self.wire.decode(frame, "CANFD"), channel="CANFD_0", direction="TO_36", authorized=True, now_ns=i) or result
            self.assertEqual(result.message["payload"], message(mid)["payload"])
        self.assertEqual(tested, 11)

    def test_can_duplicate_fragment_order_and_ns_timing_are_not_rounded(self):
        frames = self.wire.encode(message(10), "CANFD")[::-1]
        frames.insert(1, frames[0])
        raw = b"".join(f"(1.{i:09d}) canfd0 {f.arbitration_id:03X}##7{f.data.hex()}\n".encode() for i, f in enumerate(frames))
        h = history(raw, [10], fmt="CAN_LOG", medium="CANFD", end=str(len(frames)-1))
        h["policy"].update(mode="RAW_VALIDATED", session_policy="CURRENT_VALID_SESSION", rewrite_fields=[])
        prepared = self.helper.prepare(raw, h, bindings=(CaptureBinding("env", "CANFD_0", "CAN_LOG:canfd0", "canfd0", "clock-0"),))
        item = self.exporter().export(prepared, (self.binding("CANFD_0", "canfd0"),), epoch_ns=1770000000000000000).files[0]
        parsed = CaptureParser().parse(item.data, "CAN_LOG")
        self.assertEqual([p.can.data for p in parsed.packets], [f.data for f in frames])
        self.assertEqual([p.timestamp_ns for p in parsed.packets], [1770000000000000000+i for i in range(len(frames))])
        self.assertTrue(all(p.can.bitrate_switch and p.can.error_state_indicator for p in parsed.packets))
        self.assertFalse(item.tool_timing_compatible)

    def test_feedback_not_exported_and_exact_packet_manifest_indices(self):
        raw, h = self.helper.input(values=[message(7), message(130)])
        h["streams"][0].update(message_ids=[7], records=1)
        import copy
        fb = copy.deepcopy(h["streams"][0])
        fb.update(stream_id="feedback", message_ids=[130], records=1, direction="FROM_36")
        h["streams"].append(fb)
        prepared = self.helper.prepare(raw, h, bindings=(self.helper.binding(), self.helper.binding(stream_id="feedback")), headers=self.helper.headers())
        bundle = self.exporter().export(prepared, (self.binding(),), epoch_ns=1000000000)
        self.assertEqual(len(CaptureParser().parse(bundle.files[0].data, "PCAP").packets), 1)
        report = bundle.report()
        self.assertEqual(report["feedback_records_not_transmitted"], 1)
        self.assertEqual(report["files"][0]["packets"][0]["original_packet_index"], 0)
        self.assertEqual(report["files"][0]["packets"][0]["original_wire_sha256"], prepared.packets[0].original_wire_sha256)
        self.assertEqual(report["mode"], "REENCODE")
        self.assertEqual(report.get("policy"), json.loads(prepared.policy_json))
        self.assertFalse(report["execution_ready"])
        report["files"].clear()
        self.assertEqual(len(bundle.report()["files"]), 1)

    def test_strict_bindings_epoch_capacity_and_noninteger_time(self):
        prepared = self.prepared()
        for epoch in (-1, True, 1.5, (1 << 32)*1000000000):
            self.rejects("SCHEMA", lambda: self.exporter().export(prepared, (self.binding(),), epoch_ns=epoch))
        for bindings in ((), [self.binding()], (self.binding(), self.binding()), (self.binding("ETH_1"),), (self.binding(interface="../eth0"),)):
            self.rejects("RESOURCE", lambda: self.exporter().export(prepared, bindings, epoch_ns=0))
        self.rejects("CAPACITY", lambda: self.exporter(max_bytes=100).export(prepared, (self.binding(),), epoch_ns=0))
        self.rejects("UNSUPPORTED", lambda: self.exporter().export(replace(prepared, packets=(replace(prepared.packets[0], relative_offset_ns=Fraction(1, 2)),)), (self.binding(),), epoch_ns=0))

    def test_corrupted_wire_frame_hash_or_feedback_identity_rejected(self):
        prepared = self.prepared()
        packet = prepared.packets[0]
        for changed in (replace(packet, wire_data=packet.wire_data[:-1]+bytes([packet.wire_data[-1]^1])),
                        replace(packet, rebuilt_sha256="0"*64), replace(packet, channel_id="ETH_1"),
                        replace(packet, capture_bytes=bytes(Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02")/IP(src="10.36.0.10", dst="10.36.0.20")/UDP()/b"fake")),
                        replace(packet, record_index=99)):
            self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding(),), epoch_ns=0))

    def test_auxiliary_can_to_udp_requires_explicit_real_l2_identity(self):
        from input_simulator.replay import ReplayDestination
        raw = b"(1) can0 600#0102 R\n"
        h = history(raw, [44], fmt="CAN_LOG", medium="CAN")
        prepared = self.helper.prepare(raw, h, bindings=(CaptureBinding("env", "CAN_0", "CAN_LOG:can0", "can0", "clock-0", "INBOUND"),),
                                      headers=self.helper.headers(Header(91, 101, 200, 301, 1000)), destinations=(ReplayDestination("CAN_0", "ETH_0"),))
        self.rejects("RESOURCE", lambda: self.exporter().export(prepared, (self.binding(),), epoch_ns=0))
        binding = self.binding(source_mac="02:00:00:00:00:01", destination_mac="02:00:00:00:00:02")
        item = self.exporter().export(prepared, (binding,), epoch_ns=0).files[0]
        parsed = CaptureParser().parse(item.data, "PCAP")
        self.assertEqual(parsed.packets[0].payload, prepared.packets[0].wire_data)
        self.assertEqual(Ether(parsed.packets[0].raw_bytes).src, binding.source_mac)
        self.assertEqual(Ether(parsed.packets[0].raw_bytes).dst, binding.destination_mac)
        for mac in ("ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:01", "00:00:00:00:00:00", "bad"):
            self.rejects("RESOURCE", lambda: self.exporter().export(prepared, (self.binding(source_mac=mac, destination_mac=binding.destination_mac),), epoch_ns=0))

    def test_real_new_directory_package_and_existing_path_never_overwritten(self):
        bundle = self.exporter().export(self.prepared(), (self.binding(),), epoch_ns=1770000000000000001)
        self.assertTrue(callable(getattr(bundle, "write_new_directory", None)), "persistent complete resource package missing")
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "bundle"
            manifest = bundle.write_new_directory(target)
            self.assertEqual(manifest, target / "manifest.json")
            report = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(report["execution_ready"])
            for item in report["files"]:
                raw = (target / item["name"]).read_bytes()
                self.assertEqual(len(raw), item["size_bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
            marker = target / "user-owned.txt"
            marker.write_text("keep", encoding="utf-8")
            self.rejects("RESOURCE", lambda: bundle.write_new_directory(target))
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            existing = Path(root) / "existing-file"
            existing.write_bytes(b"original")
            self.rejects("RESOURCE", lambda: bundle.write_new_directory(existing))
            self.assertEqual(existing.read_bytes(), b"original")

    def test_failed_actual_persistence_has_no_complete_manifest_or_silent_cleanup(self):
        bundle = self.exporter().export(self.prepared(), (self.binding(),), epoch_ns=0)
        self.assertTrue(callable(getattr(bundle, "write_new_directory", None)), "persistent complete resource package missing")
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "interrupted"
            with patch("input_simulator.replay_export.os.fsync", side_effect=OSError("injected fsync failure")):
                self.rejects("RESOURCE", lambda: bundle.write_new_directory(target))
            self.assertTrue(target.is_dir())
            self.assertFalse((target / "manifest.json").exists())
            self.assertTrue((target / bundle.files[0].name).exists())
            self.rejects("RESOURCE", lambda: bundle.write_new_directory(target))

    def test_modified_complete_group_cannot_export_mixed_headers_or_partial_payload(self):
        from test_resources import chunk
        content = b"x" * 2000
        value = chunk(content, 0, len(content), kind="VIDEO")
        raw, h = self.helper.input(34, values=[value])
        prepared = self.helper.prepare(raw, h, headers=self.helper.headers(Header(91, 101, 200, 301, 1000)))
        self.assertGreater(len(prepared.packets), 1)
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=prepared.packets[:-1]), (self.binding(),), epoch_ns=0))
        p = prepared.packets[1]
        f = self.wire.decode(p.wire_data, "UDP")
        new = self.wire.rewrite(p.wire_data, "UDP", replace(f.header, sequence=f.header.sequence+1))
        frame = Ether(p.capture_bytes)
        frame[UDP].remove_payload()
        frame[UDP].add_payload(new)
        for obj, fields in ((frame[IP], ("len", "chksum")), (frame[UDP], ("len", "chksum"))):
            for field in fields:
                delattr(obj, field)
        capture = bytes(frame)
        changed = replace(p, wire_data=new, rebuilt_wire_sha256=hashlib.sha256(new).hexdigest(),
                          capture_bytes=capture, rebuilt_sha256=hashlib.sha256(capture).hexdigest())
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(prepared.packets[0], changed)+prepared.packets[2:]), (self.binding(),), epoch_ns=0))

    def test_exact_integer_time_cannot_be_rewritten_without_original_policy(self):
        prepared = self.prepared()
        changed = replace(prepared.packets[0], relative_offset_ns=Fraction(1000))
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding(),), epoch_ns=0))

    def test_selected_whole_record_cannot_be_omitted(self):
        first, second = message(7), message(7)
        second["header"]["sequence"] += 1
        raw, h = self.helper.input(values=[first, second], times=[0, 1000])
        prepared = self.helper.prepare(raw, h, headers=self.helper.headers()+self.helper.headers(Header(91, 102, 201, 301, 100), index=1))
        self.assertEqual(len(prepared.packets), 2)
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=prepared.packets[:1]), (self.binding(),), epoch_ns=0))

    def test_raw_ethernet_l2_or_ttl_cannot_change_by_rehashing(self):
        prepared = self.prepared(mode="RAW_VALIDATED")
        p = prepared.packets[0]
        frame = Ether(p.capture_bytes)
        frame.src = "02:AA:BB:CC:DD:EE"
        frame[IP].ttl = 19
        del frame[IP].chksum
        capture = bytes(frame)
        changed = replace(p, capture_bytes=capture, rebuilt_sha256=hashlib.sha256(capture).hexdigest())
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding(),), epoch_ns=0))

    def test_raw_channel_cannot_be_relabelled(self):
        prepared = self.prepared(mode="RAW_VALIDATED")
        changed = replace(prepared.packets[0], channel_id="ETH_1")
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding("ETH_1", "eth1"),), epoch_ns=0))

    def test_session_rebuild_cannot_revert_to_captured_session_or_false_changes(self):
        prepared = self.prepared(mode="SESSION_REBUILD")
        p = prepared.packets[0]
        old = prepared.decoded.capture.packets[p.original_packet_index]
        changed = replace(p, wire_data=old.payload, rebuilt_wire_sha256=hashlib.sha256(old.payload).hexdigest(),
                          capture_bytes=old.raw_bytes, rebuilt_sha256=hashlib.sha256(old.raw_bytes).hexdigest(), changed_fields=())
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding(),), epoch_ns=0))
        changed = replace(p, changed_fields=())
        self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding(),), epoch_ns=0))

    def test_rehashed_reencode_cannot_target_invalid_udp_endpoint(self):
        prepared = self.prepared()
        p = prepared.packets[0]
        for receiver in (("224.1.2.3", 36100), ("127.0.0.1", 0), ("0.0.0.0", 36100), ("255.255.255.255", 36100)):
            frame = Ether(p.capture_bytes)
            frame[IP].dst, frame[UDP].dport = receiver
            del frame[IP].chksum
            del frame[UDP].chksum
            capture = bytes(frame)
            changes = tuple(x for x in p.changed_fields if x != "CRC") + ("SOURCE_ENDPOINT", "CRC")
            changed = replace(p, receiver_endpoint=receiver, capture_bytes=capture,
                              rebuilt_sha256=hashlib.sha256(capture).hexdigest(), changed_fields=changes)
            self.rejects("RESOURCE", lambda: self.exporter().export(replace(prepared, packets=(changed,)), (self.binding(),), epoch_ns=0))

    def test_all_44_granted_udp_inputs_export_in_all_three_modes(self):
        tested = 0
        for mid, entry in self.contract.messages.items():
            if entry["direction"] != "TO_36" or mid == 1:
                continue
            tested += 1
            for mode in ("RAW_VALIDATED", "REENCODE", "SESSION_REBUILD"):
                raw, h = self.helper.input(mid, mode=mode)
                headers = () if mode == "RAW_VALIDATED" else self.helper.headers(Header(91, 101, 200, 301, entry["valid_for_ms"]))
                prepared = self.helper.prepare(raw, h, headers=headers, model_id=entry["model_ids"][0])
                exported = self.exporter().export(prepared, (self.binding(),), epoch_ns=0)
                packets = CaptureParser().parse(exported.files[0].data, "PCAP").packets
                self.assertEqual([p.payload for p in packets], [p.wire_data for p in prepared.packets])
        self.assertEqual(tested, 44)

    def test_multichannel_pcapng_export_keeps_each_interface_and_file_order(self):
        from test_capture import shb, idb, epb
        from test_history import udp_packet
        value = message(7)
        first = udp_packet(self.wire.encode(value, "UDP")[0])
        value["header"]["sequence"] += 1
        second = Ether(udp_packet(self.wire.encode(value, "UDP")[0]))
        channel = next(c for c in self.contract.catalogue["channels"] if c["id"] == "ETH_1")
        second[IP].src, second[IP].dst = channel["source_ipv4"], channel["receiver_ipv4"]
        second[UDP].sport, second[UDP].dport = channel["source_udp_port"], channel["business_udp_port"]
        del second[IP].chksum
        del second[UDP].chksum
        raw = shb()+idb(1, name=b"eth0")+idb(1, name=b"eth1")+epb(first, interface=0, ticks=1000000000)+epb(bytes(second), interface=1, ticks=1000001000)
        h = history(raw, [7], fmt="PCAPNG", records=2, end="1000")
        h["policy"].update(mode="RAW_VALIDATED", session_policy="CURRENT_VALID_SESSION", rewrite_fields=[])
        bindings = tuple(CaptureBinding("env", f"ETH_{i}", f"PCAPNG:0:{i}", f"eth{i}", "clock-0") for i in range(2))
        prepared = self.helper.prepare(raw, h, bindings=bindings)
        exported = self.exporter().export(prepared, (self.binding(), self.binding("ETH_1", "eth1")), epoch_ns=0)
        self.assertEqual([f.channel_id for f in exported.files], ["ETH_0", "ETH_1"])
        for item, p in zip(exported.files, prepared.packets):
            self.assertEqual(CaptureParser().parse(item.data, "PCAP").packets[0].payload, p.wire_data)
        self.rejects("RESOURCE", lambda: self.exporter().export(prepared, (self.binding(), self.binding("ETH_1", "eth0")), epoch_ns=0))

    def test_backward_merged_can_timeline_preserved_but_not_tool_compatible(self):
        first, second = message(2), message(2)
        second["header"]["sequence"] += 1
        frames = [self.wire.encode(v, "CANFD")[0] for v in (first, second)]
        raw = b"".join(f"(1.{t:09d}) can{i} {f.arbitration_id:03X}##5{f.data.hex()}\n".encode()
                       for i, (t, f) in enumerate(zip((2000, 1000), frames)))
        h = history(raw, [2], fmt="CAN_LOG", medium="CANFD", records=2, end="2000")
        h["policy"].update(mode="RAW_VALIDATED", session_policy="CURRENT_VALID_SESSION", rewrite_fields=[], start_offset_ns="1000")
        bindings = tuple(CaptureBinding("env", "CANFD_0", f"CAN_LOG:can{i}", f"can{i}", "clock-0") for i in range(2))
        prepared = self.helper.prepare(raw, h, bindings=bindings)
        item = self.exporter().export(prepared, (self.binding("CANFD_0", "canfd0"),), epoch_ns=0).files[0]
        actual = CaptureParser().parse(item.data, "CAN_LOG")
        self.assertEqual([p.timestamp_ns for p in actual.packets], [1000, 0])
        self.assertFalse(item.tool_timing_compatible)


if __name__ == "__main__":
    unittest.main()
