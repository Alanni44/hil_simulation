import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ROOT


class HistoryReceptionDemoTests(unittest.TestCase):
    def load_module(self):
        path = ROOT / "scripts" / "run_history_reception_demo.py"
        spec = importlib.util.spec_from_file_location("history_reception_demo", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_history_pcap_replay_is_reprepared_and_decoded_without_model_application(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "history-chain.jsonl"
            result = self.load_module().run(INTERFACES, EXPECTED, evidence)
            self.assertEqual(result["status"], "RECEPTION_VALIDATED")
            rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
        replay = next(row for row in rows if row["format"] == "HIL_HISTORY_REPLAY_1")
        received = next(row for row in rows if row["format"] == "HIL_RECEPTION_RX_1")
        self.assertEqual(replay["prepared_packets"], 1)
        self.assertFalse(replay["prepared_execution_ready"])
        self.assertEqual(replay["prepared_wire_sha256"], replay["source_wire_sha256"])
        self.assertEqual(received["message"]["message_id"], 7)
        self.assertFalse(received["model_applied"])
        self.assertEqual(rows[-1]["tcpreplay_qualification"], "NOT_EVALUATED")

    def test_cli_runs_from_repository_root(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "history-chain.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_history_reception_demo.py",
                                     "--output", str(evidence)], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "RECEPTION_VALIDATED")
