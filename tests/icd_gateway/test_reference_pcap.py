import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from common import EXPECTED, INTERFACES, message
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.wire import WireCodec
from input_simulator.capture import CaptureParser
from input_simulator.reference_pcap import (
    DEFAULT_REFERENCE_PROFILE,
    build_reference_pcap,
    validate_reference_pcap,
    write_reference_artifacts,
)


class ReferencePcapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)

    def test_repeat_generation_is_byte_and_hash_deterministic(self):
        first = build_reference_pcap(self.contract)
        second = build_reference_pcap(self.contract)
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())

    def test_capture_parser_and_wire_codec_read_the_exact_generated_frame(self):
        raw = build_reference_pcap(self.contract)
        capture = CaptureParser().parse(raw, "PCAP")
        expected_wire = WireCodec(self.contract).encode(message(7), "UDP")
        self.assertEqual(capture.format, "PCAP")
        self.assertEqual(len(capture.packets), 1)
        packet = capture.packets[0]
        self.assertEqual(packet.linktype, 1)
        self.assertEqual(packet.timestamp_ns, 1_760_000_000_000_000_000)
        self.assertEqual((packet.source_ipv4, packet.source_port), ("10.36.0.10", 36102))
        self.assertEqual((packet.destination_ipv4, packet.destination_port), ("10.36.0.20", 36100))
        self.assertIsNone(packet.vlan_id)
        self.assertEqual(packet.transport, "UDP")
        self.assertEqual(packet.payload, expected_wire[0])
        self.assertEqual(Ether(packet.raw_bytes).src, "02:00:00:00:00:01")
        self.assertEqual(Ether(packet.raw_bytes).dst, "02:00:00:00:00:02")
        self.assertEqual(bytes(Ether(packet.raw_bytes)[IP][UDP].payload), expected_wire[0])
        fragment = WireCodec(self.contract).decode(packet.payload, "UDP", direction="TO_36")
        self.assertEqual((fragment.message_id, fragment.index, fragment.count), (7, 0, 1))

    def test_history_and_replay_round_trip_keep_non_executable_boundary(self):
        manifest, validation = validate_reference_pcap(self.contract, build_reference_pcap(self.contract))
        self.assertEqual(manifest["channel"], "ETH_0")
        self.assertEqual(manifest["direction"], "TO_36")
        self.assertEqual(manifest["message_id"], 7)
        self.assertIs(validation["claims"]["generated"], True)
        self.assertIs(validation["claims"]["parsed"], True)
        self.assertIs(validation["claims"]["decoded"], True)
        self.assertIs(validation["claims"]["prepared"], True)
        wire = validation["stages"]["wire_decoded"]["packets"][0]
        self.assertEqual(wire["magic"], "HIL1")
        self.assertEqual(wire["message_id"], 7)
        self.assertEqual(wire["direction"], "TO_36")
        self.assertEqual((wire["fragment_index"], wire["fragment_count"]), (0, 1))
        self.assertIs(wire["crc_verified"], True)
        self.assertIs(validation["claims"]["transmitted"], False)
        self.assertIs(validation["claims"]["applied"], False)
        self.assertIs(validation["claims"]["consumed"], False)
        self.assertIs(validation["stages"]["prepared"]["execution_ready"], False)
        self.assertGreater(validation["stages"]["prepared"]["packet_count"], 0)
        self.assertEqual(validation["stages"]["prepared"]["selected_directions"], ["TO_36"])

    def test_persisted_manifest_hashes_match_the_final_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "round1"
            result = write_reference_artifacts(self.contract, target)
            pcap = (target / "reference.pcap").read_bytes()
            manifest = json.loads((target / "reference_manifest.json").read_text(encoding="utf-8"))
            validation = json.loads((target / "round1_validation.json").read_text(encoding="utf-8"))
            parsed = CaptureParser().parse(pcap, "PCAP").packets[0]
        self.assertEqual(result["manifest"], manifest)
        self.assertEqual(hashlib.sha256(pcap).hexdigest(), manifest["pcap_sha256"])
        self.assertEqual(hashlib.sha256(parsed.raw_bytes).hexdigest(), manifest["frames"][0]["ethernet_frame_sha256"])
        self.assertEqual(hashlib.sha256(parsed.payload).hexdigest(), manifest["frames"][0]["udp_payload_sha256"])
        self.assertIs(validation["claims"]["execution_ready"], False)
        self.assertIs(manifest["actual_network_tx"], False)
        self.assertIn("not a deployed hardware MAC", manifest["mac_identity_note"])

    def test_loopback_cannot_be_mislabeled_as_frozen_eth0(self):
        profile = replace(DEFAULT_REFERENCE_PROFILE, source_ipv4="127.0.0.1", receiver_ipv4="127.0.0.1")
        with self.assertRaises(ICDError):
            build_reference_pcap(self.contract, profile=profile)

    def test_invalid_profile_and_malformed_capture_fail_explicitly(self):
        with self.assertRaises(ICDError):
            build_reference_pcap(self.contract, profile=object())
        with self.assertRaises(ICDError):
            build_reference_pcap(self.contract, profile=replace(DEFAULT_REFERENCE_PROFILE, source_mac="00:00:00:00:00:00"))
        with self.assertRaises(ICDError):
            validate_reference_pcap(self.contract, b"not a PCAP")


if __name__ == "__main__":
    unittest.main()
