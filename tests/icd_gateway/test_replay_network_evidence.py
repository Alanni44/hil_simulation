import struct
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common import EXPECTED, INTERFACES
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.wire import Header
from input_simulator.reference_pcap import build_reference_pcap
from input_simulator.replay_network_evidence import compare_replay_captures


class ReplayNetworkEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.raw = build_reference_pcap(cls.contract)
        cls.header = Header(session_id=1, sequence=7, target_step=1000,
                            transaction_id=7, valid_for_ms=100)
        cls.payload = {"motor_command": [0.1, 0.2, 0.3, 0.4]}

    def compare(self, received, **kwargs):
        return compare_replay_captures(
            self.contract,
            self.raw,
            received,
            expected_message_id=7,
            expected_header=kwargs.get("expected_header", self.header),
            expected_payload=kwargs.get("expected_payload", self.payload),
        )

    def test_identical_capture_passes(self):
        result = self.compare(self.raw)
        self.assertEqual(result["packet_count"], 1)
        self.assertIs(result["packet_order_equal"], True)
        self.assertIs(result["all_raw_frame_bytes_equal"], True)
        self.assertIs(result["frames"][0]["hil_crc_verified"], True)

    def test_capture_timestamp_may_differ_when_frame_bytes_match(self):
        changed = bytearray(self.raw)
        seconds = struct.unpack_from("<I", changed, 24)[0]
        struct.pack_into("<I", changed, 24, seconds + 1)
        result = self.compare(bytes(changed))
        self.assertIs(result["all_raw_frame_bytes_equal"], True)
        self.assertNotEqual(result["frames"][0]["tx_timestamp_ns"],
                            result["frames"][0]["rx_timestamp_ns"])

    def test_changed_ethernet_frame_fails(self):
        changed = bytearray(self.raw)
        changed[40] ^= 0x04
        with self.assertRaises(ICDError):
            self.compare(bytes(changed))

    def test_empty_received_capture_fails(self):
        with self.assertRaises(ICDError):
            self.compare(self.raw[:24])

    def test_expected_header_mismatch_fails(self):
        wrong = Header(session_id=2, sequence=7, target_step=1000,
                       transaction_id=7, valid_for_ms=100)
        with self.assertRaises(ICDError):
            self.compare(self.raw, expected_header=wrong)

    def test_expected_payload_mismatch_fails(self):
        with self.assertRaises(ICDError):
            self.compare(self.raw, expected_payload={"motor_command": [0.0, 0.0, 0.0, 0.0]})


if __name__ == "__main__":
    unittest.main()
