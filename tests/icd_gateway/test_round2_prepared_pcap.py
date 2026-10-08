import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from icd_runtime.contract import Contract
from input_simulator.reference_pcap import BASELINE_SHA256
from prepare_history_round2 import REFERENCE_PATH, prepare_round2_artifacts


class Round2PreparedPcapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(ROOT / "docs" / "interfaces" / "baseline",
                                     expected_sha256=BASELINE_SHA256)

    def test_reference_to_prepared_pcap_and_command_offline_closure(self):
        original_hash = hashlib.sha256(REFERENCE_PATH.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "round2"
            result = prepare_round2_artifacts(self.contract, output)
            manifest = result["manifest"]
            command = result["command"]
            persisted_hash = hashlib.sha256((output / "prepared.pcap").read_bytes()).hexdigest()
            saved_manifest = json.loads((output / "prepared_manifest.json").read_text(encoding="utf-8"))
            saved_command = json.loads((output / "tcpreplay_command.json").read_text(encoding="utf-8"))

            self.assertEqual(original_hash, "c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3")
            self.assertEqual(hashlib.sha256(REFERENCE_PATH.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(manifest["source_reference_pcap_sha256"], original_hash)
            self.assertEqual(manifest["baseline_sha256"], BASELINE_SHA256)
            self.assertEqual(manifest["replay_mode"], "REENCODE")
            self.assertEqual(manifest["input_message_id"], 7)
            self.assertEqual(manifest["input_channel"], "ETH_0")
            self.assertEqual(manifest["output_channel"], "ETH_0")
            self.assertEqual(manifest["original_header"], {
                "sequence": 7, "session_id": 1, "target_step": 1000,
                "transaction_id": 7, "valid_for_ms": 100,
            })
            self.assertEqual(manifest["allocated_header"], {
                "sequence": 102, "session_id": 92, "target_step": 201,
                "transaction_id": 302, "valid_for_ms": 100,
            })
            self.assertEqual(set(manifest["changed_fields"]),
                             {"SESSION", "SEQUENCE", "TARGET_STEP", "TRANSACTION", "CRC"})
            self.assertEqual(manifest["source_endpoint"], {"ipv4": "10.36.0.10", "udp_port": 36102})
            self.assertEqual(manifest["destination_endpoint"], {"ipv4": "10.36.0.20", "udp_port": 36100})
            self.assertEqual(manifest["source_mac"], "02:00:00:00:00:01")
            self.assertEqual(manifest["destination_mac"], "02:00:00:00:00:02")
            self.assertEqual(manifest["packet_count"], 1)
            self.assertEqual(manifest["prepared_pcap_sha256"], persisted_hash)
            self.assertEqual(saved_manifest["prepared_pcap_sha256"], persisted_hash)
            self.assertTrue(manifest["synthetic_reference"])
            self.assertTrue(manifest["offline_prepared"])
            for key in ("actual_network_tx", "process_started", "received", "applied", "consumed",
                        "execution_ready"):
                self.assertIs(manifest[key], False)

            argv = command["argv"]
            self.assertEqual(argv[:4], ["tcpreplay", "--intf1=eth0", "--loop=1", "--multiplier=1.0"])
            self.assertEqual(Path(argv[-1]).resolve(), (output / "prepared.pcap").resolve())
            self.assertEqual(command["resource_sha256"], persisted_hash)
            self.assertEqual(saved_command["argv"], argv)
            self.assertTrue(command["command_built"])
            self.assertIs(command["process_started"], False)
            self.assertIs(command["actual_network_tx"], False)
            self.assertEqual(result["validation"]["claims"], {
                "prepared": True, "exported": True, "command_built": True,
                "process_started": False, "actual_network_tx": False, "received": False,
                "applied": False, "consumed": False, "execution_ready": False,
            })

    def test_existing_output_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "round2"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                prepare_round2_artifacts(self.contract, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
