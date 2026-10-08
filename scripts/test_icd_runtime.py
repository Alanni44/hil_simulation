"""Common offline and local-socket tests; never installs target dependencies."""

from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    commands = (
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/icd_runtime", "-p", "test_*.py", "-v"],
        [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests/icd_gateway", "-p", "test_*.py", "-v"],
        [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-p", "test_development_backlog.py", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_contract_single_file.py", "-v"],
        [sys.executable, "scripts/build_contract_single_file.py", "--check"],
    )
    for command in commands:
        result = subprocess.run(command, cwd=root)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
