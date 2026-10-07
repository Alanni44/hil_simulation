import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from common import EXPECTED, INTERFACES, ICDTest


class CLITests(ICDTest):
    def run_cli(self, fingerprint=EXPECTED, directory=INTERFACES):
        return subprocess.run([sys.executable, "-m", "icd_runtime", "--contract-dir", str(directory),
                               "--expected-sha256", fingerprint], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[2], timeout=30)

    def test_offline_common_cli_checks_all_goldens_and_no_runtime_claim(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "OFFLINE_CODEC_PASS")
        self.assertEqual(report["business_messages"], 59)
        self.assertEqual(report["golden_fragments"], 85)
        self.assertEqual(report["video_raw_fragments"], 800)
        self.assertEqual(report["baseline_sha256"], EXPECTED)
        self.assertEqual(report["runtime_network_model_hardware_replacement"], "NOT_EXECUTED")

    def test_wrong_pinned_baseline_exits_nonzero(self):
        result = self.run_cli("0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["error"], "HASH")

    def test_mutated_fixtures_cannot_pass_by_rewriting_local_manifest(self):
        for mutation in ("empty", "missing", "duplicate", "examples"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "baseline"
                shutil.copytree(INTERFACES, directory)
                name = "input-simulator-v0.3.examples.json" if mutation == "examples" else "input-simulator-v0.3.golden.json"
                path = directory / name
                value = json.loads(path.read_bytes())
                if mutation == "empty":
                    value["vectors"] = []
                elif mutation == "missing":
                    value["vectors"].pop()
                elif mutation == "duplicate":
                    value["vectors"][-1] = value["vectors"][0]
                else:
                    value["fixtures"][0]["value"]["payload"]["nonce_hex"] = "0" * 32
                raw = json.dumps(value).encode("utf-8")
                path.write_bytes(raw)
                manifest_path = directory / "input-simulator-v0.3.manifest.json"
                manifest = json.loads(manifest_path.read_bytes())
                entry = next(item for item in manifest["files"] if item["file"] == name)
                entry.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                result = self.run_cli(directory=directory)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(json.loads(result.stdout)["error"], "HASH")

    def test_no_platform_specific_behavior_or_qa_imports(self):
        import ast
        root = Path(__file__).resolve().parents[2] / "icd_runtime"
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            imports = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))]
            for node in imports:
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                self.assertFalse(any(name.startswith(("artifacts", "win32", "ctypes", "msvcrt")) for name in names), path.name)
            for forbidden in ("sys.platform", "os.name", "platform.system", "mock/real", "vendor_v03", "sys.path.insert"):
                self.assertNotIn(forbidden, source, path.name)
