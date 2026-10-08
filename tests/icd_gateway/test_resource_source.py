import socket
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from common import EXPECTED, INTERFACES, ROOT, GatewayTest, message
from test_resources import chunk
from test_udp import available_port
from icd_runtime.resource_budget import ResourceBudget
from icd_runtime.errors import ICDError


class ResourceSourceTests(GatewayTest):
    def network(self):
        from input_simulator.udp_source import UDPSource
        self.peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.peer.bind(("127.0.0.1", 0))
        self.addCleanup(self.peer.close)
        self.source = UDPSource(self.contract, source_bind=("127.0.0.1", 0),
                                feedback_bind=("127.0.0.1", 0), receiver_endpoint=self.peer.getsockname(),
                                channel="ETH_0")
        self.addCleanup(self.source.close)

    def test_actual_fragment_send_respects_wire_budget_without_initial_burst(self):
        self.network()
        value = chunk(bytes(range(256)) * 128, sid=10, sequence=2)
        packets = tuple(self.source.wire.encode(value, "UDP"))
        minimum = ResourceBudget(self.contract).preview(packets, now_ns=0)
        start = time.perf_counter_ns()
        self.source.send(value)
        self.assertGreaterEqual(time.perf_counter_ns() - start, minimum,
                                "source bursts ResourceChunk datagrams above the frozen wire budget")

    def test_final_wait_outlives_retry_window_without_more_than_three_retries(self):
        self.network()
        value = chunk(b"actual", sid=10, sequence=2)
        reply = message(141)
        reply["header"].update(session_id=10, sequence=1, transaction_id=2)
        reply["payload"].update(resource_sha256=value["payload"]["resource_sha256"],
                                next_offset=6, stored_bytes=6, complete=True, error="OK")
        sent = []
        failures = []
        def peer():
            try:
                deadline = time.monotonic() + 1.05
                self.peer.settimeout(0.03)
                while time.monotonic() < deadline:
                    try:
                        sent.append(self.peer.recvfrom(1201)[0])
                    except socket.timeout:
                        pass
                for packet in self.source.wire.encode(reply, "UDP"):
                    self.peer.sendto(packet, self.source.feedback_endpoint)
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=peer)
        thread.start()
        try:
            actual = self.source.request(value)
        except ICDError as exc:
            self.fail(f"final ResourceAck wait ended at the ordinary retry window: {exc.code}")
        finally:
            thread.join(2)
        self.assertEqual(failures, [])
        self.assertEqual(actual, reply)
        self.assertEqual(len(sent), 4)
        self.assertTrue(all(raw == sent[0] for raw in sent))

    def cli_resource_result(self, error):
        self.network()
        feedback_port = available_port()
        source_port = available_port()
        while source_port == feedback_port:
            source_port = available_port()
        value = chunk(b"actual", sid=10, sequence=2)
        reply = message(141)
        reply["header"].update(session_id=10, sequence=1, transaction_id=2)
        reply["payload"].update(resource_sha256=value["payload"]["resource_sha256"], error=error,
                                next_offset=6 if error == "OK" else 0,
                                stored_bytes=6 if error == "OK" else 0, complete=error == "OK")
        failures = []
        def peer():
            try:
                self.peer.settimeout(5)
                self.peer.recvfrom(1201)
                for packet in self.source.wire.encode(reply, "UDP"):
                    self.peer.sendto(packet, ("127.0.0.1", feedback_port))
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=peer)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "resource.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", "input_simulator",
                                         "--contract-dir", str(INTERFACES), "--expected-sha256", EXPECTED,
                                         "--source-bind", f"127.0.0.1:{source_port}",
                                         "--feedback-bind", f"127.0.0.1:{feedback_port}",
                                         "--receiver", f"127.0.0.1:{self.peer.getsockname()[1]}",
                                         "--message-file", str(path)], cwd=ROOT, capture_output=True,
                                        text=True, encoding="utf-8", timeout=5)
        finally:
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(json.loads(result.stdout)["feedback"], reply)
        return result

    def test_cli_resource_error_never_reports_business_success(self):
        result = self.cli_resource_result("HASH")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "BUSINESS_FAILED")

    def test_cli_stored_resource_reports_exchange_not_model_application(self):
        result = self.cli_resource_result("OK")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "NETWORK_EXCHANGE_COMPLETE")
        self.assertEqual(json.loads(result.stdout)["model_hardware_replacement"], "NOT_EXECUTED")
