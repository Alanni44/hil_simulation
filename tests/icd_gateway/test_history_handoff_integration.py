"""Current shared receiver compatibility and read-only external evidence checks."""

from pathlib import Path
import unittest
from unittest.mock import patch

from common import GatewayTest, ROOT, message
from icd_gateway.config import load_deployment
from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_runtime.json_codec import loads
from icd_runtime.wire import Header, WireCodec
from input_simulator.capture import CaptureParser
from input_simulator.replay_network_evidence import compare_replay_captures
from test_history_round4_gateway import round4


class HistoryHandoffIntegrationTests(GatewayTest):
    def receiver(self, *, receive_only=False):
        opening = message(1)
        opening["payload"]["roles"] = ["CONTROLLER"]
        binding = PeerBinding("ETH_0", "UDP", "10.36.0.10:36102")
        grant = SourceGrant(opening["payload"]["identity"], ("CONTROLLER",), (binding,))
        with patch("icd_gateway.session.secrets.randbelow", return_value=901):
            registry = SessionRegistry(self.contract, (grant,))
        reception = ReceptionService(self.contract, registry, (7,)) if receive_only else None
        receiver = Receiver(self.contract, registry, reception_service=reception)
        wire = WireCodec(self.contract)
        replies = ()
        for frame in wire.encode(opening, "UDP"):
            replies = receiver.receive(frame, binding, now_ns=1000)
        self.assertEqual(len(replies), 1)
        sid = replies[0]["payload"]["session_id"]
        raw, manifest = round4.prepare_current_session(self.contract, round4.REFERENCE.read_bytes(), sid)
        return receiver, reception, binding, replies[0], CaptureParser().parse(raw, "PCAP"), manifest

    def test_default_current_gateway_keeps_honest_admission_only_boundary(self):
        receiver, _, binding, opened, capture, manifest = self.receiver()
        self.assertEqual(opened["payload"]["capabilities"]["implemented_message_ids"], [1])
        replies = ()
        for packet in capture.packets:
            replies = receiver.receive(packet.payload, binding, now_ns=2000)
        self.assertTrue(round4.validate_ack_sequence(replies, manifest["header"], opened["payload"]["session_id"]))
        self.assertEqual(receiver.admitted_count, 2)
        self.assertFalse(any(reply["payload"]["stage"] in ("APPLIED", "CONSUMED") for reply in replies))
        receiver.close()

    def test_same_history_wire_uses_current_standard_receive_only_path_and_dedup(self):
        receiver, reception, binding, opened, capture, manifest = self.receiver(receive_only=True)
        self.assertEqual(opened["payload"]["capabilities"]["implemented_message_ids"], [1, 7])
        replies = ()
        for packet in capture.packets:
            replies = receiver.receive(packet.payload, binding, now_ns=2000)
        self.assertEqual([(reply["payload"]["stage"], reply["payload"]["error"]) for reply in replies],
                         [("RECEIVED", "OK"), ("VALIDATED", "OK")])
        self.assertTrue(all(reply["payload"]["probe_id"] == 0 for reply in replies))
        self.assertEqual(len(reception.records), 1)
        received = reception.records[0].document()
        self.assertEqual(received["message"]["payload"], round4.EXPECTED_PAYLOAD)
        self.assertEqual(received["message"]["header"], manifest["header"])
        again = receiver.receive(capture.packets[0].payload, binding, now_ns=3000)
        self.assertEqual(again, replies)
        self.assertEqual(len(reception.records), 1)
        receiver.close()

    def test_current_development_can_binding_and_external_controller_config_coexist(self):
        own = load_deployment(ROOT / "config/input-simulator-development.json", self.contract)
        external = load_deployment(ROOT / "config/input-simulator-round4-development.json", self.contract)
        self.assertTrue(own.can_bindings)
        self.assertEqual(own.grants[0].roles, ("STIMULUS",))
        self.assertEqual(external.grants[0].roles, ("CONTROLLER",))
        self.assertEqual(external.bind, ("10.36.0.20", 36100))

    def test_final_round3_captures_still_match_exact_frames_header_and_payload(self):
        root = ROOT / "artifacts/history"
        prepared = (root / "round2/prepared.pcap").read_bytes()
        received = (root / "round3/retry_2/received.pcap").read_bytes()
        manifest = loads((root / "round2/prepared_manifest.json").read_bytes())
        result = compare_replay_captures(self.contract, prepared, received, expected_message_id=7,
                                        expected_header=Header(**manifest["allocated_header"]),
                                        expected_payload=round4.EXPECTED_PAYLOAD)
        self.assertTrue(result["all_raw_frame_bytes_equal"])
        self.assertEqual(result["packet_count"], 1)

    def test_final_round4_full_evidence_readback_does_not_rewrite_history(self):
        writes = []

        def verify_existing(path, raw):
            path = Path(path)
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.read_bytes(), raw, path)
            writes.append(path)

        with patch.object(round4, "write_new", side_effect=verify_existing):
            result = round4.validate_evidence(ROOT / "artifacts/history/round4/retry_4")
        self.assertEqual(len(writes), 4)
        self.assertEqual(result["status"], "ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED")
        self.assertTrue(result["claims"]["gateway_session_admitted"])
        for claim in ("source_capability_authorized", "applied", "consumed", "execution_ready",
                      "target_step_semantically_qualified", "target_kylin_qualified"):
            self.assertFalse(result["claims"][claim], claim)


if __name__ == "__main__":
    unittest.main()
