"""Exercise cleanup with fake shell functions, never real network commands."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/validate_history_round4_linux.sh"


class Round4CleanupTests(unittest.TestCase):
    def run_shell(self, body):
        git = shutil.which("git")
        bundled = Path(git).resolve().parents[1] / "usr/bin/bash.exe" if git else None
        bash = str(bundled) if bundled and bundled.is_file() else shutil.which("bash")
        if not bash:
            self.skipTest("Bash unavailable for isolated shell-function tests")
        with tempfile.TemporaryDirectory() as directory:
            setup = '''
set -Eeuo pipefail
export PATH="/usr/bin:$PATH"
OUTPUT_DIR="$1"
OUTPUT_CREATED=0
SRC_CREATED=0; GW_CREATED=0
SRC_NS=test-src; GW_NS=test-gw
TXCAP_PID=""; RXCAP_PID=""; GW_PID=""
HOST_ROUTES_BEFORE=""; FAILURE=""
fail() { FAILURE="$*"; echo "ROUND4_ERROR: $FAILURE" >&2; exit 1; }
ip() {
  if [[ "$1 $2" == "netns del" ]]; then return 1; fi
  if [[ "$1 $2" == "netns list" ]]; then printf 'test-src\ntest-gw\n'; return 0; fi
  printf 'unchanged-route\n'
}
mock_python() { return 0; }
PYTHON=mock_python
SCRIPT_DIR=unused
'''
            result = subprocess.run(
                [bash, "-c", setup + body, "cleanup-test", Path(directory).as_posix()],
                capture_output=True, text=True, timeout=10,
            )
            status = Path(directory, "cleanup_status.json")
            return result, status.read_text() if status.exists() else None

    def test_failed_namespace_delete_cannot_report_success(self):
        source = SCRIPT.read_text(encoding="utf-8")
        tail = source[source.index("# Cleanup occurs") :]
        result, status = self.run_shell('''
OUTPUT_CREATED=1; SRC_CREATED=1; GW_CREATED=1
printf 'unchanged-route\n' > "$OUTPUT_DIR/host_route_before.txt"
''' + tail)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("source namespace cleanup failed", result.stderr)
        self.assertTrue(status is None or '"cleanup_complete":true' not in status)

    def test_rejected_existing_output_is_never_modified(self):
        source = SCRIPT.read_text(encoding="utf-8")
        cleanup = source[source.index("cleanup() {") : source.index("trap cleanup EXIT INT TERM")]
        result, status = self.run_shell(cleanup + "\ntrue\ncleanup\n")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIsNone(status)


if __name__ == "__main__":
    unittest.main()
