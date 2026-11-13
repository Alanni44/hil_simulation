#!/usr/bin/env python3
"""Verify raw can-utils CAN-FD/BRS capability on a non-formal vcan fixture.

This verifies the original ``cansend`` binary, but deliberately uses raw ID
0x123, which is outside the project's formal-message filters.  It is not an
application source session or a production wire-authorization test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from input_simulator.tool_process import ProcessSupervisor


def require_existing_can_interface(interface: str) -> str:
    probe = subprocess.run(("ip", "-details", "link", "show", "dev", interface),
                           text=True, capture_output=True, check=False)
    if probe.returncode != 0 or "UP" not in probe.stdout:
        raise RuntimeError("an existing UP Linux CAN interface is required: %s" % interface)
    return probe.stdout


def require_executable(value: Path) -> Path:
    path = value.resolve(strict=True)
    if not path.is_file() or not path.stat().st_mode & 0o111:
        raise RuntimeError("an executable path is required")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def wait_terminal(worker: ProcessSupervisor, *, timeout_s: float) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = worker.poll()
        if snapshot.state != "RUNNING":
            return snapshot
        time.sleep(.005)
    return worker.stop()


def run(interface: str, candump: Path, cansend: Path, output: Path) -> Path:
    interface_details = require_existing_can_interface(interface)
    candump, cansend = require_executable(candump), require_executable(cansend)
    frame_id, payload = 0x123, bytes(range(64))
    receiver_argv = (str(candump), "-L", "-N", "-x", "-n", "1",
                     "%s,%03X:C00007FF" % (interface, frame_id))
    receiver = ProcessSupervisor(receiver_argv, cwd=ROOT, timeout_ms=3000, stop_timeout_ms=1000)
    receiver.start()
    time.sleep(.05)
    sender_argv = (str(cansend), interface, "%03X##1%s" % (frame_id, payload.hex().upper()))
    sender = ProcessSupervisor(sender_argv, cwd=ROOT, timeout_ms=1000, stop_timeout_ms=1000)
    sender.start()
    sender_snapshot = wait_terminal(sender, timeout_s=1)
    sender.close()
    receive_snapshot = wait_terminal(receiver, timeout_s=2)
    receiver.close()
    text = receive_snapshot.stdout.decode("ascii", errors="strict")
    if (sender_snapshot.state != "EXITED" or sender_snapshot.returncode != 0
            or receive_snapshot.state != "EXITED" or receive_snapshot.returncode != 0
            or "%03X##5" % frame_id not in text.upper()
            or payload.hex().upper() not in text.upper()):
        raise RuntimeError("original cansend/candump did not complete the expected CAN-FD/BRS fixture")
    report = {
        "format": "HIL_L006_CUTIL_VCAN_SENDER_1",
        "status": "SOFTWARE_CUTIL_SENDER_CAPABILITY_VERIFIED",
        "execution_host": "Linux %s (%s)" % (platform.release(), platform.machine()),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interface": interface,
        "interface_details": interface_details,
        "candump": {"path": str(candump), "sha256": sha256_file(candump)},
        "cansend": {"path": str(cansend), "sha256": sha256_file(cansend)},
        "receiver_argv": list(receiver_argv),
        "sender_argv": list(sender_argv),
        "sender": {"state": sender_snapshot.state, "returncode": sender_snapshot.returncode},
        "observation": {"state": receive_snapshot.state, "returncode": receive_snapshot.returncode,
                        "stdout": text, "is_fd": True, "bitrate_switch": True,
                        "timestamp_format": "candump -L -N"},
        "authorization": {
            "fixture_can_id": "0x123 (outside formal-message filters)",
            "product_send_authorization": "NOT_GRANTED",
            "meaning": "raw original-tool capability fixture only; it cannot authorize a formal application message",
        },
        "hardware_qualification": "NOT_EVALUATED: vcan cannot qualify a physical controller, bus arbitration/load, hardware timestamps, or electrical behaviour.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="can2")
    parser.add_argument("--candump", type=Path, required=True)
    parser.add_argument("--cansend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.interface, args.candump, args.cansend, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
