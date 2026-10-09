import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ROOT


class ProtocolReceptionDemoTests(unittest.TestCase):
    def test_virtual_can_protocol_chain_generates_and_decodes_without_model_application(self):
        path = ROOT / "scripts" / "run_protocol_reception_demo.py"
        spec = importlib.util.spec_from_file_location("protocol_reception_demo", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-chain.jsonl"
            result = module.run(INTERFACES, EXPECTED, evidence, count=2, period_steps=80)
            self.assertEqual(result["status"], "RECEPTION_VALIDATED")
            self.assertEqual((result["generated_samples"], result["decoded_samples"]), (2, 2))
            self.assertFalse(result["model_application_verified"])
            rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["transport"], "CANFD_VIRTUAL")
        self.assertEqual(sum(row["format"] == "HIL_RECEPTION_TX_1" for row in rows), 2)
        received = [row for row in rows if row["format"] == "HIL_RECEPTION_RX_1"]
        self.assertEqual(len(received), 2)
        self.assertTrue(all(row["binding"]["transport"] == "CANFD" for row in received))
        self.assertTrue(all(row["model_applied"] is False for row in received))
        self.assertEqual(rows[-1]["status"], "RECEPTION_VALIDATED")

    def test_existing_evidence_is_not_overwritten(self):
        path = ROOT / "scripts" / "run_protocol_reception_demo.py"
        spec = importlib.util.spec_from_file_location("protocol_reception_demo_no_overwrite", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-chain.jsonl"
            evidence.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                module.run(INTERFACES, EXPECTED, evidence, count=1, period_steps=80)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "existing\n")

    def test_cli_runs_from_repository_root(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-chain.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_protocol_reception_demo.py",
                                     "--output", str(evidence), "--count", "1"], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "RECEPTION_VALIDATED")
