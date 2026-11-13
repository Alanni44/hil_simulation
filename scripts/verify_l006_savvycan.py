#!/usr/bin/env python3
"""Verify a pinned SavvyCAN AppImage starts and stops without CAN transmit.

SavvyCAN is a GUI.  The check extracts its already-verified AppImage into a
fresh temporary directory, starts it using either the active desktop or an
explicit Qt platform plugin, and stops the direct child.  It deliberately does
not open a CAN connection or invoke a GUI send action, so the default run
retains no transmit authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from input_simulator.tool_process import ProcessSupervisor


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def require_appimage(path: Path, expected_sha256: str) -> Path:
    value = path.resolve(strict=True)
    if not value.is_file() or not value.stat().st_mode & 0o111:
        raise RuntimeError("an executable SavvyCAN AppImage is required")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise RuntimeError("a lowercase 64-character pinned SHA-256 is required")
    actual = sha256_file(value)
    if actual != expected_sha256:
        raise RuntimeError("SavvyCAN AppImage SHA-256 differs from the pinned package")
    return value


def wait_terminal(worker: ProcessSupervisor, *, timeout_s: float) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = worker.poll()
        if snapshot.state != "RUNNING":
            return snapshot
        time.sleep(.01)
    return worker.stop()


def run(appimage: Path, expected_sha256: str, output: Path, *, platform_plugin: str | None) -> Path:
    appimage = require_appimage(appimage, expected_sha256)
    with tempfile.TemporaryDirectory(prefix="hil-l006-savvycan-", dir="/tmp") as directory:
        workdir = Path(directory)
        extractor = ProcessSupervisor((str(appimage), "--appimage-extract"), cwd=workdir,
                                      timeout_ms=30000, output_limit=1024 * 1024)
        extractor.start()
        extraction = wait_terminal(extractor, timeout_s=30)
        extractor.close()
        app_run = workdir / "squashfs-root" / "AppRun"
        if extraction.state != "EXITED" or extraction.returncode != 0 or not app_run.is_file():
            raise RuntimeError("SavvyCAN AppImage extraction failed")
        viewer_argv = (str(app_run),) if platform_plugin is None else (str(app_run), "-platform", platform_plugin)
        viewer = ProcessSupervisor(viewer_argv, cwd=workdir,
                                   timeout_ms=10000, output_limit=1024 * 1024)
        viewer.start()
        time.sleep(.5)
        running = viewer.snapshot
        if running.state != "RUNNING":
            viewer.close()
            raise RuntimeError("SavvyCAN did not remain running: %s" % running.stderr.decode("utf-8", "replace"))
        stopped = viewer.stop()
        viewer.close()
        if stopped.state != "STOPPED" or not stopped.direct_child_terminal:
            raise RuntimeError("SavvyCAN stop failed: state=%s terminal=%s error=%s stderr=%s" % (
                stopped.state, stopped.direct_child_terminal, stopped.error,
                stopped.stderr.decode("utf-8", "replace")))
    report = {
        "format": "HIL_L006_SAVVYCAN_START_STOP_1",
        "status": "SOFTWARE_SAVVYCAN_START_STOP_VERIFIED",
        "execution_host": "Linux %s (%s)" % (platform.release(), platform.machine()),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "appimage": str(appimage),
        "appimage_sha256": expected_sha256,
        "extraction": {"state": extraction.state, "returncode": extraction.returncode},
        "viewer": {"state": stopped.state, "direct_child_terminal": stopped.direct_child_terminal,
                   "argv": list(viewer_argv),
                   "stdout": stopped.stdout.decode("utf-8", "replace"),
                   "stderr": stopped.stderr.decode("utf-8", "replace")},
        "authorization": {
            "can_connection_opened": False,
            "gui_send_invoked": False,
            "meaning": "default GUI start/stop only; no transmit authority acquired",
        },
        "pending": ["SAVVYCAN_SOCKETCAN_CONNECTION_AND_FD_BRS_OBSERVATION",
                    "SAVVYCAN_FORMAL_SEND_AUTHORIZATION", "PHYSICAL_CANFD_QUALIFICATION"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimage", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--platform", default=None,
                        help="optional Qt platform plugin; omit to use the active desktop display")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.appimage, args.expected_sha256, args.output, platform_plugin=args.platform))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
