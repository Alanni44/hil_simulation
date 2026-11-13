#!/usr/bin/env python3
"""Record the real Linux readiness of the L-006 can-utils/SavvyCAN branches.

This is deliberately an inventory and observation-safety check, not a
replacement CAN implementation.  In particular, it never substitutes
python-can or UDP for a missing can-utils or SavvyCAN executable, and it never
launches a sender.  It can therefore be run safely before a tool installation
or a physical CAN-FD device is made available.
"""
from __future__ import annotations

import argparse
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

from icd_runtime.contract import Contract
from input_simulator.replay_export import ExportBinding
from input_simulator.tool_commands import ToolCommandBuilder
from input_simulator.tools import ChannelReservations, ToolInventory


BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"


def require_existing_can_interface(interface: str) -> str:
    """Return kernel details without creating, configuring, or removing it."""
    probe = subprocess.run(("ip", "-details", "link", "show", "dev", interface),
                           text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise RuntimeError("an existing Linux CAN interface is required: %s" % interface)
    if "UP" not in probe.stdout:
        raise RuntimeError("CAN interface is not UP: %s" % interface)
    return probe.stdout


def evidence_document(item: Any) -> dict[str, Any]:
    return {
        "catalogue_id": item.catalogue_id,
        "branch_id": item.branch_id,
        "status": item.status,
        "reason": item.reason,
        "executables": [
            {"name": value.name, "present": value.present, "location": value.location,
             "sha256": value.sha256}
            for value in item.evidence
        ],
        "pending_checks": list(item.pending_checks),
    }


def run(interface: str, output: Path, contract_dir: Path, expected_sha256: str) -> Path:
    interface_details = require_existing_can_interface(interface)
    contract = Contract.load(contract_dir, expected_sha256=expected_sha256)
    inventory = {item.catalogue_id: item for item in ToolInventory(contract).inspect()}
    cutil, savvy = inventory["CUTIL"], inventory["SAVVY"]

    reservations = ChannelReservations()
    observer = reservations.reserve("l006-observer", "CUTIL", (interface,), mode="OBSERVE")
    try:
        plan = ToolCommandBuilder(contract, reservations).observe(
            observer, (ExportBinding("CANFD_0", interface),))
        command = plan.commands[0].argv
        if (command[0] != "candump" or "cansend" in command or observer.authorized_to_transmit
                or plan.authorized_to_transmit):
            raise RuntimeError("default CUTIL observer unexpectedly has send authority")
    finally:
        reservations.release(observer)

    missing = [item.catalogue_id for item in (cutil, savvy) if item.status == "UNAVAILABLE"]
    status = "TOOL_DEPENDENCIES_UNAVAILABLE" if missing else "TOOL_DEPENDENCIES_PRESENT_UNEXECUTED"
    report = {
        "format": "HIL_L006_CAN_TOOL_READINESS_1",
        "status": status,
        "execution_host": "Linux %s (%s)" % (platform.release(), platform.machine()),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interface": interface,
        "interface_details": interface_details,
        "branches": {"CUTIL": evidence_document(cutil), "SAVVY": evidence_document(savvy)},
        "default_observation": {
            "argv": list(command),
            "reservation_mode": observer.mode,
            "reservation_authorized_to_transmit": observer.authorized_to_transmit,
            "plan_authorized_to_transmit": plan.authorized_to_transmit,
            "result": "CANDUMP_ONLY_NO_SEND_AUTHORITY",
        },
        "not_executed": [
            "No can-utils or SavvyCAN executable was launched by this readiness check.",
            "Start/stop, actual CAN-FD/BRS/timestamp/channel evidence and any transmission require the original installed tool, a separately granted sender session, and a qualified target device.",
        ],
        "hardware_qualification": "NOT_EVALUATED: interface inspection does not qualify a physical CAN-FD controller, bus arbitration/load, hardware timestamps, or electrical behaviour.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--contract-dir", type=Path, default=ROOT / "docs/interfaces/baseline")
    parser.add_argument("--expected-sha256", default=BASELINE_SHA256)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.interface, args.output, args.contract_dir, args.expected_sha256))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
