import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ROOT
from icd_runtime.errors import ICDError


class ProtocolReceptionDemoTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts" / "run_protocol_reception_demo.py"
        spec = importlib.util.spec_from_file_location("protocol_reception_demo_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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

    def test_controller_and_stimulus_inputs_decode_for_their_model(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-controller.jsonl"
            result = self.module().run(INTERFACES, EXPECTED, evidence, count=1, period_steps=80,
                                       model_id="quadrotor_hil", message_ids=(7, 10, 11, 14))
            rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(result["message_ids"], [7, 10, 11, 14])
        received = [row for row in rows if row["format"] == "HIL_RECEPTION_RX_1"]
        self.assertEqual([row["message"]["message_id"] for row in received], [7, 10, 11, 14])
        self.assertTrue(all(row["model_applied"] is False for row in received))

    def test_model_application_requires_contract_and_only_supports_one_quadrotor_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-model.jsonl"
            with self.assertRaises(ICDError) as missing_contract:
                self.module().run(INTERFACES, EXPECTED, evidence, model_endpoint="127.0.0.1:19997")
            self.assertEqual(missing_contract.exception.code, "SCHEMA")
            with self.assertRaises(ICDError) as unsupported:
                self.module().run(INTERFACES, EXPECTED, evidence, model_endpoint="127.0.0.1:19997",
                                  model_id="quadrotor_hil", message_ids=(7,))
        self.assertEqual(unsupported.exception.code, "UNSUPPORTED")

    def test_fault_model_application_is_admitted_by_the_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-model-fault.jsonl"
            with self.assertRaises(ICDError) as missing_contract:
                self.module().run(INTERFACES, EXPECTED, evidence, model_endpoint="127.0.0.1:19997",
                                  model_id="quadrotor_hil", message_ids=(11,))
        self.assertEqual(missing_contract.exception.code, "SCHEMA")

    def test_cli_runs_from_repository_root(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "protocol-chain.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_protocol_reception_demo.py",
                                     "--output", str(evidence), "--count", "1"], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "RECEPTION_VALIDATED")
