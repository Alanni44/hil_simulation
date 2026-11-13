#!/usr/bin/env python3
"""Verify the L-005 software path on an existing Linux SocketCAN vcan link.

The script deliberately does not create, configure, or remove interfaces.
It proves the shared CAN-FD wire codec and the original python-can SocketCAN
backend on an already-UP vcan interface.  A vcan result is software evidence
only: it cannot qualify a physical CAN-FD controller, bus, arbitration, or
electrical disconnect behaviour.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any

import can


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.can_ingress import CANGateway
from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame


BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"


def frame_document(frame: can.Message) -> dict[str, Any]:
    """Keep the original python-can observation, not a reconstructed frame."""
    if (frame.is_fd is not True or frame.bitrate_switch is not True
            or frame.is_extended_id is not False or frame.is_remote_frame is not False
            or frame.is_error_frame is not False or frame.error_state_indicator is not False
            or frame.dlc != 64 or len(frame.data) != 64):
        raise RuntimeError("SocketCAN did not return a standard FD/BRS 64-byte data frame")
    return {
        "arbitration_id": frame.arbitration_id,
        "data_hex": bytes(frame.data).hex(),
        "dlc": frame.dlc,
        "is_fd": frame.is_fd,
        "bitrate_switch": frame.bitrate_switch,
        "is_extended_id": frame.is_extended_id,
        "is_remote_frame": frame.is_remote_frame,
        "is_error_frame": frame.is_error_frame,
        "error_state_indicator": frame.error_state_indicator,
        "is_rx": frame.is_rx,
        "channel": frame.channel,
        "timestamp": frame.timestamp,
    }


def require_vcan(interface: str) -> str:
    probe = subprocess.run(("ip", "-details", "link", "show", "dev", interface),
                           text=True, capture_output=True, check=False)
    if probe.returncode != 0 or "vcan " not in probe.stdout:
        raise RuntimeError("an existing UP vcan interface is required: %s" % interface)
    if "UP" not in probe.stdout:
        raise RuntimeError("vcan interface is not UP: %s" % interface)
    return probe.stdout


def fixture_messages(contract_dir: Path) -> dict[int, dict[str, Any]]:
    source = json.loads((contract_dir / "input-simulator-v0.3.examples.json").read_text(encoding="utf-8"))
    return {row["value"]["message_id"]: row["value"] for row in source["fixtures"]}


def run(interface: str, output: Path, contract_dir: Path, expected_sha256: str) -> Path:
    topology = require_vcan(interface)
    contract = Contract.load(contract_dir, expected_sha256=expected_sha256)
    fixtures = fixture_messages(contract_dir)
    can_binding = PeerBinding("CANFD_0", "CANFD", interface)
    udp_binding = PeerBinding("ETH_0", "UDP", "127.0.0.1:36102")
    identity = fixtures[1]["payload"]["identity"]
    registry = SessionRegistry(contract, (
        SourceGrant(identity, ("STIMULUS",), (udp_binding, can_binding)),
    ))
    service = ReceptionService(contract, registry, (10,))
    receiver = Receiver(contract, registry, reception_service=service)
    opening = receiver.receive(receiver.wire.encode(fixtures[1], "UDP")[0], udp_binding,
                               now_ns=time.monotonic_ns())[0]
    session_id = opening["payload"]["session_id"]
    request = json.loads(json.dumps(fixtures[10]))
    request["header"].update(session_id=session_id, sequence=2, transaction_id=2, target_step=80)
    expected = receiver.wire.encode(request, "CANFD")
    observed_tx: list[dict[str, Any]] = []
    observed_reply: list[dict[str, Any]] = []
    replies: list[dict[str, Any]] = []
    with ExitStack() as stack:
        tx = can.Bus(interface="socketcan", channel=interface, fd=True,
                     receive_own_messages=False, ignore_config=True)
        observer = can.Bus(interface="socketcan", channel=interface, fd=True,
                            receive_own_messages=False, ignore_config=True)
        gateway_bus = can.Bus(interface="socketcan", channel=interface, fd=True,
                              receive_own_messages=False, ignore_config=True)
        stack.callback(tx.shutdown)
        stack.callback(observer.shutdown)
        gateway = CANGateway(receiver, channel="CANFD_0", interface=interface, bus=gateway_bus)
        stack.callback(gateway.close)
        for encoded in expected:
            result = tx.send(can.Message(arbitration_id=encoded.arbitration_id, data=encoded.data,
                                         is_extended_id=False, is_fd=True, bitrate_switch=True,
                                         check=True), timeout=.1)
            if result is not None:
                raise RuntimeError("python-can SocketCAN send returned a value")
            seen = observer.recv(.1)
            if seen is None:
                raise RuntimeError("peer SocketCAN socket did not observe the transmitted vcan frame")
            observation = frame_document(seen)
            if (observation["arbitration_id"] != encoded.arbitration_id
                    or observation["data_hex"] != encoded.data.hex()):
                raise RuntimeError("peer SocketCAN observation differs from shared wire output")
            observed_tx.append(observation)
            gateway.poll(timeout=.02)
        assembler = Reassembler(contract)
        deadline = time.monotonic() + .5
        while time.monotonic() < deadline and len(replies) < 2:
            frame = tx.recv(.02)
            if frame is None:
                continue
            observation = frame_document(frame)
            observed_reply.append(observation)
            part = receiver.wire.decode(CANFrame(frame.arbitration_id, bytes(frame.data)), "CANFD",
                                        direction="FROM_36")
            completed = assembler.push(part, channel="CANFD_0", direction="FROM_36", authorized=True,
                                       now_ns=time.monotonic_ns())
            if completed is not None:
                replies.append(completed.message)
        if loads(service.records[0].message_json) != request:
            raise RuntimeError("SocketCAN frame did not reach the standard receiver unchanged")
        if [reply["payload"]["stage"] for reply in replies] != ["RECEIVED", "VALIDATED"]:
            raise RuntimeError("standard SocketCAN feedback was incomplete")
        gateway.close()
        try:
            gateway.poll(timeout=0)
        except ICDError as error:
            if error.code != "STATE":
                raise
            shutdown_guard = error.code
        else:
            raise RuntimeError("closed SocketCAN gateway remained usable")
    receiver.close()
    report = {
        "format": "HIL_L005_SOCKETCAN_VCAN_1",
        "status": "SOFTWARE_VCAN_VERIFIED",
        "execution_host": "Linux %s (%s)" % (platform.release(), platform.machine()),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "completed_linux_items": ["L-005-software"],
        "interface": interface,
        "interface_details": topology,
        "python_can_version": can.__version__,
        "message_id": 10,
        "request_frame_count": len(observed_tx),
        "request_frames": observed_tx,
        "feedback_frames": observed_reply,
        "feedback_stages": [reply["payload"]["stage"] for reply in replies],
        "receiver_records": len(service.records),
        "closed_gateway_rejected_with": shutdown_guard,
        "verification": "Shared CAN-FD codec -> actual python-can SocketCAN/vcan peer -> CANGateway -> Receiver -> actual SocketCAN feedback.",
        "hardware_qualification": "NOT_EVALUATED: vcan has no physical controller, bus arbitration/load or electrical disconnect evidence.",
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
