#!/usr/bin/env python3
"""L-008 的隔离 Scapy ETHGEN 实际 L2 软件验证端点。

本脚本必须由外层临时 netns/veth 启动：receiver 模式只提供标准 UDP
接收，source 模式只通过 ScapySource 发出原始以太网帧。两者均不代表
实体网卡、VLAN 或汽车以太网资格。
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from input_simulator.replay_export import ExportBinding
from input_simulator.scapy_source import ScapySource
from input_simulator.send_run import SendPlan, SendRun
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations


BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
SOURCE_ENDPOINT = ("10.36.0.10", 36102)
FEEDBACK_ENDPOINT = ("10.36.0.10", 36101)
RECEIVER_ENDPOINT = ("10.36.0.20", 36100)
SOURCE_MAC = "02:00:00:00:00:01"
DESTINATION_MAC = "02:00:00:00:00:02"


def _contract(directory: Path) -> Contract:
    return Contract.load(directory, expected_sha256=BASELINE_SHA256)


def _identity(directory: Path) -> dict:
    fixtures = json.loads((directory / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]
    return next(row["value"]["payload"]["identity"] for row in fixtures if row["value"]["message_id"] == 1)


def _scenario_inputs(directory: Path) -> tuple[dict, dict]:
    source = json.loads((ROOT / "config/generated-input-reception.json").read_text(encoding="utf-8"))["source_inputs"]
    resources = {}
    root = directory.resolve()
    for reference in source["protocol"]["resources"]:
        path = (root / reference["file_name"]).resolve(strict=True)
        if path.parent != root:
            raise ICDError("RESOURCE", "冻结协议资源路径越界")
        resources[reference["resource_id"]] = path.read_bytes()
    return source, resources


def _write(stream, value: dict) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()


def receiver(contract_dir: Path, output: Path, timeout_seconds: float) -> dict:
    contract = _contract(contract_dir)
    identity = _identity(contract_dir)
    binding = PeerBinding("ETH_0", "UDP", "%s:%d" % SOURCE_ENDPOINT)
    registry = SessionRegistry(contract, (SourceGrant(identity, ("STIMULUS",), (binding,)),))
    service = ReceptionService(contract, registry, (10,))
    receiver = Receiver(contract, registry, reception_service=service)
    deadline = time.monotonic() + timeout_seconds
    with ExitStack() as stack:
        stream = stack.enter_context(output.open("x", encoding="utf-8"))
        gateway = UDPGateway(receiver, bind=RECEIVER_ENDPOINT,
                             feedback_routes={binding: FEEDBACK_ENDPOINT}, channel="ETH_0")
        stack.callback(gateway.close)
        _write(stream, {"format": "HIL_L008_RECEIVER_1", "status": "READY",
                        "bind": list(RECEIVER_ENDPOINT), "expected_samples": 3})
        while len(service.records) < 3 and time.monotonic() < deadline:
            gateway.poll(timeout=0.02)
        if len(service.records) != 3:
            raise ICDError("TIMEOUT", "标准接收端没有收到完整的三个 ETHGEN 样本")
        for record in service.records:
            _write(stream, record.document())
        _write(stream, {"format": "HIL_L008_RECEIVER_1", "status": "RECEPTION_VALIDATED",
                        "received_samples": len(service.records)})
    receiver.close()
    return {"status": "RECEPTION_VALIDATED", "received_samples": 3}


def source(contract_dir: Path, output: Path, timeout_seconds: float) -> dict:
    contract = _contract(contract_dir)
    inputs, resources = _scenario_inputs(contract_dir)
    plan = SendPlan.scenario(contract, inputs, resources, model_id="quadrotor_hil")
    if {item.link_id for item in plan.actions} != {"ETHGEN"}:
        raise ICDError("STATE", "L-008 验证只接受冻结的 ETHGEN 场景")
    book = ChannelReservations()
    token = book.reserve("l008-veth", "ETHGEN", ("eth0",), mode="SEND")
    with ExitStack() as stack:
        stream = stack.enter_context(output.open("x", encoding="utf-8"))
        stack.callback(book.release, token)
        transport = ScapySource(contract, source_bind=SOURCE_ENDPOINT, feedback_bind=FEEDBACK_ENDPOINT,
                                receiver_endpoint=RECEIVER_ENDPOINT,
                                binding=ExportBinding("ETH_0", "eth0", SOURCE_MAC, DESTINATION_MAC),
                                reservations=book, reservation=token)
        stack.callback(transport.close)
        session = SourceSession(transport, _identity(contract_dir), ("STIMULUS",), max_records=4096)
        stack.callback(session.close)
        _write(stream, {"format": "HIL_L008_SOURCE_1", "status": "STARTED",
                        "source_endpoint": list(SOURCE_ENDPOINT), "receiver_endpoint": list(RECEIVER_ENDPOINT),
                        "tool": "ScapySource", "sample_count": len(plan.actions)})
        rows = SendRun(plan, session, feedback_timeout=min(timeout_seconds, 0.5)).run(
            on_record=lambda record: _write(stream, record.document()))
        l2 = [{"interface": row.interface, "ethernet_sha256": hashlib.sha256(row.ethernet_data).hexdigest(),
               "udp_sha256": hashlib.sha256(row.udp_data).hexdigest(), "sent_bytes": row.sent_bytes,
               "error": row.error} for row in transport.l2_records]
        if len(rows) != 3 or len(l2) != 4 or any(item["error"] is not None for item in l2):
            raise ICDError("STATE", "Scapy 原始会话开包和三个 ETHGEN 样本必须完整保留")
        _write(stream, {"format": "HIL_L008_SOURCE_1", "status": "RECEPTION_VALIDATED",
                        "completed_samples": len(rows), "scapy_l2_frames": l2,
                        "physical_tool_qualification": "NOT_EVALUATED"})
    return {"status": "RECEPTION_VALIDATED", "completed_samples": 3, "scapy_l2_frames": 4}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("receiver", "source"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract-dir", type=Path, default=ROOT / "docs/interfaces/baseline")
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if not 0.1 <= args.timeout_seconds <= 30:
        raise SystemExit("timeout-seconds 必须在 0.1 至 30 范围内")
    try:
        result = receiver(args.contract_dir, args.output, args.timeout_seconds) if args.mode == "receiver" else source(args.contract_dir, args.output, args.timeout_seconds)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                          "detail": str(error)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
