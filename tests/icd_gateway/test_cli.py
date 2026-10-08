import importlib.util
import json
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading

from common import EXPECTED, INTERFACES, ROOT, GatewayTest, message
from test_udp import available_port


class CLITests(GatewayTest):
    def test_one_common_source_with_no_os_or_mock_real_dispatch(self):
        import ast
        for folder in ("icd_gateway", "input_simulator"):
            for path in (ROOT / folder).glob("*.py"):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    else:
                        continue
                    self.assertFalse(any(name.startswith(("win32", "msvcrt", "ctypes", "artifacts")) for name in names))
                for forbidden in ("sys.platform", "os.name", "platform.system", "mock/real", "vendor_v03"):
                    self.assertNotIn(forbidden, source, str(path))

    def test_gateway_config_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.config"), "strict deployment loader missing")

    def test_checked_in_development_config_uses_defined_endpoint_roles(self):
        from icd_gateway.config import load_deployment
        path = ROOT / "config" / "input-simulator-development.json"
        self.assertTrue(path.is_file(), "explicit common development deployment missing")
        config = load_deployment(path, self.contract)
        self.assertEqual(config.bind, ("127.0.0.1", 36100))
        self.assertEqual(config.grants[0].bindings[0].peer, "127.0.0.1:36102")
        self.assertEqual(tuple(config.feedback_routes.values()), (("127.0.0.1", 36101),))

    def deployment(self):
        ports = set()
        while len(ports) != 3:
            ports.add(available_port())
        receiver, source, feedback = sorted(ports)
        return {"mode": "DEVELOPMENT", "channel": "ETH_0", "receiver_bind": {"ip": "127.0.0.1", "port": receiver},
                "grants": [{"identity": message(1)["payload"]["identity"], "roles": ["STIMULUS"],
                            "source_endpoint": {"ip": "127.0.0.1", "port": source},
                            "feedback_endpoint": {"ip": "127.0.0.1", "port": feedback}}]}

    def test_config_rejects_unknown_fields_and_formal_mode_without_release(self):
        from icd_gateway.config import load_deployment
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deployment.json"
            for mutation, code in (("unknown", "SCHEMA"), ("formal", "STATE"), ("grant", "SCHEMA")):
                config = self.deployment()
                if mutation == "unknown":
                    config["private_windows_entry"] = True
                elif mutation == "formal":
                    config["mode"] = "FORMAL"
                else:
                    config["grants"][0]["roles"] = []
                path.write_text(json.dumps(config), encoding="utf-8")
                self.rejects(code, lambda: load_deployment(path, self.contract))

    def test_independent_gateway_and_source_processes_exchange_formal_wire(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            config = self.deployment()
            config_path = temporary / "deployment.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            opening = message(1)
            opening["payload"]["nonce_hex"] = secrets.token_hex(16)
            message_path = temporary / "business.json"
            message_path.write_text(json.dumps(opening), encoding="utf-8")
            command = [sys.executable, "-X", "utf8", "-m", "icd_gateway", "--contract-dir", str(INTERFACES),
                       "--expected-sha256", EXPECTED, "--deployment", str(config_path)]
            gateway = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8")
            lines = queue.Queue()
            reader = threading.Thread(target=lambda: lines.put(gateway.stdout.readline()), daemon=True)
            reader.start()
            try:
                ready = json.loads(lines.get(timeout=10))
                self.assertEqual(ready["status"], "DEVELOPMENT_READY")
                grant = config["grants"][0]
                endpoint = lambda value: f"{value['ip']}:{value['port']}"
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", "input_simulator",
                                         "--contract-dir", str(INTERFACES), "--expected-sha256", EXPECTED,
                                         "--source-bind", endpoint(grant["source_endpoint"]),
                                         "--feedback-bind", endpoint(grant["feedback_endpoint"]),
                                         "--receiver", endpoint(config["receiver_bind"]),
                                         "--message-file", str(message_path)], cwd=ROOT, capture_output=True,
                                        text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["feedback"]["message_id"], 129)
                self.assertFalse(report["feedback"]["payload"]["capabilities"]["replacement_ready"])
                self.assertEqual(report["model_hardware_replacement"], "NOT_EXECUTED")
            finally:
                gateway.terminate()
                gateway.communicate(timeout=5)
                reader.join(timeout=1)

    def test_wrong_hash_refuses_service_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deployment.json"
            path.write_text(json.dumps(self.deployment()), encoding="utf-8")
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "icd_gateway", "--contract-dir", str(INTERFACES),
                                     "--expected-sha256", "0" * 64, "--deployment", str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["error"], "HASH")
