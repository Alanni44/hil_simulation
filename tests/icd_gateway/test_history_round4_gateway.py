"""Round 4 evidence gates in the project's common unittest runner."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_history_round4_gateway.py"
SPEC = importlib.util.spec_from_file_location("round4_gateway_validator", SCRIPT)
round4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(round4)


def ack(sequence, sid=7331, transaction=2, request_sequence=2, stage="RECEIVED", error="OK",
        message_id=7, probe_id=0):
    return {
        "message_id": 130,
        "header": {"session_id": sid, "sequence": sequence, "transaction_id": transaction},
        "payload": {"request_sequence": request_sequence, "request_message_id": message_id,
                    "stage": stage, "error": error, "probe_id": probe_id},
    }


class Round4GatewayTests(unittest.TestCase):
    def test_round1_is_reencoded_for_fresh_session_without_changing_payload(self):
        contract = round4.load_contract()
        pcap, manifest = round4.prepare_current_session(contract, round4.REFERENCE.read_bytes(), 7331)
        capture = round4.CaptureParser().parse(pcap, "PCAP")
        fragment = round4.WireCodec(contract).decode(capture.packets[0].payload, "UDP", direction="TO_36")
        payload = round4.WireCodec(contract).payload_codec.decode(7, fragment.payload)
        self.assertEqual(manifest["replay_mode"], "REENCODE")
        self.assertEqual(manifest["header"], {"session_id": 7331, "sequence": 2, "target_step": 201,
                                            "transaction_id": 2, "valid_for_ms": 100})
        self.assertEqual(payload, round4.EXPECTED_PAYLOAD)
        self.assertFalse(manifest["source_capability_authorized"])
        self.assertFalse(manifest["target_step_semantically_qualified"])

    def test_received_then_target_missing_is_the_only_passing_ack_pair(self):
        pair = [ack(1), ack(2, stage="FAILED", error="TARGET_MISSING")]
        self.assertTrue(round4.validate_ack_sequence(pair, {"sequence": 2, "transaction_id": 2}, 7331))

    def test_evidence_write_is_idempotent_only_for_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "evidence.json"
            round4.write_new(target, b"{}\n")
            round4.write_new(target, b"{}\n")
            with self.assertRaises(FileExistsError):
                round4.write_new(target, b'{"changed":true}\n')

    def test_ack_mismatch_or_execution_claim_fails_closed(self):
        pairs = [
            [ack(1, stage="FAILED", error="AUTHORIZATION"), ack(2, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(1, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(2, sid=7332, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(2, transaction=3, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(2, request_sequence=3, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(2, message_id=34, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(2, probe_id=1, stage="FAILED", error="TARGET_MISSING")],
            [ack(1), ack(2, stage="APPLIED", error="OK")],
            [ack(1), ack(2, stage="CONSUMED", error="OK")],
        ]
        for pair in pairs:
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                round4.validate_ack_sequence(pair, {"sequence": 2, "transaction_id": 2}, 7331)
