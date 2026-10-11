import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ROOT
from icd_runtime.errors import ICDError


class ScenarioReceptionDemoTests(unittest.TestCase):
    def load_module(self):
        path = ROOT / "scripts" / "run_scenario_reception_demo.py"
        spec = importlib.util.spec_from_file_location("scenario_reception_demo", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_scenario_waveform_uses_scapy_and_is_decoded_without_model_application(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "scenario-chain.jsonl"
            result = self.load_module().run(INTERFACES, EXPECTED, evidence)
            self.assertEqual(result["status"], "RECEPTION_VALIDATED")
            rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
        received = [row for row in rows if row["format"] == "HIL_RECEPTION_RX_1"]
        self.assertEqual([row["message"]["payload"]["wind_n_mps"] for row in received], [0, 8, 16])
        self.assertTrue(all(row["binding"]["transport"] == "UDP" for row in received))
        self.assertTrue(all(row["model_applied"] is False for row in received))
        self.assertEqual(rows[0]["transport"], "ETHERNET_VIRTUAL")
        self.assertGreaterEqual(rows[-1]["scapy_l2_frames"], 3)

    def test_cli_runs_from_repository_root(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "scenario-chain.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_scenario_reception_demo.py",
                                     "--output", str(evidence)], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "RECEPTION_VALIDATED")

    def test_model_application_mode_requires_an_explicit_generated_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "scenario-chain.jsonl"
            with self.assertRaises(ICDError) as error:
                self.load_module().run(INTERFACES, EXPECTED, evidence,
                                       model_endpoint="127.0.0.1:19997")
        self.assertEqual(error.exception.code, "SCHEMA")
