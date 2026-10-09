import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ROOT


class ProtocolCoverageDemoTests(unittest.TestCase):
    def test_all_frozen_canfd_input_models_are_generated_and_decoded(self):
        path = ROOT / "scripts" / "run_protocol_coverage_demo.py"
        spec = importlib.util.spec_from_file_location("protocol_coverage_demo", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            result = module.run(INTERFACES, EXPECTED, Path(folder) / "coverage")
            manifest = json.loads((Path(folder) / "coverage" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "RECEPTION_VALIDATED")
        self.assertEqual(manifest["unique_message_ids"], list(range(7, 17)))
        self.assertEqual((manifest["generated_samples"], manifest["decoded_samples"]), (12, 12))
        self.assertFalse(manifest["model_application_verified"])
        self.assertTrue(all(row["generated_samples"] == row["decoded_samples"] == 4 for row in manifest["models"]))
