#!/usr/bin/env python3
"""经标准 Receiver/ModelLifecycleService 验证本地 C 模型生命周期闭环。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/interfaces/baseline"
BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_gateway.lifecycle_service import ModelLifecycleService
from icd_gateway.model_consumer import CcoreLifecycleBackend
from icd_gateway.receiver import Receiver
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from scripts.verify_l007_canplayer_session_vcan import LocalCcore, fixture


def deliver(receiver, message: dict, link: PeerBinding, now_ns: int) -> tuple[dict, ...]:
    replies: tuple[dict, ...] = ()
    for packet in receiver.wire.encode(message, link.transport):
        replies = receiver.receive(packet, link, now_ns=now_ns)
    return replies


def ccore_step(ccore) -> int:
    reply = ccore.client.status()
    fields = reply.get("fields", {})
    step = fields.get("sequence")
    if not reply.get("accepted") or type(step) is not int:
        raise ICDError("MODEL", "C 核心没有返回实际生命周期步")
    return step


def lifecycle_message(template: dict, *, session_id: int, sequence: int,
                      action: str, expected_state: str, target_step: int,
                      step_count: int | None = None) -> dict:
    request = json.loads(json.dumps(template))
    request["header"].update(session_id=session_id, sequence=sequence,
                             transaction_id=sequence, target_step=target_step)
    request["payload"] = {"action": action, "expected_state": expected_state,
                          "reset_policy": "NOT_APPLICABLE"}
    if step_count is not None:
        request["payload"]["step_count"] = step_count
    return request


def run(output: Path, executable: Path, model_contract: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    contract = Contract.load(BASELINE, expected_sha256=BASELINE_SHA256)
    identity = fixture(BASELINE, 1)["payload"]["identity"]
    link = PeerBinding("ETH_0", "UDP", "127.0.0.1:36602")
    registry = SessionRegistry(contract, [SourceGrant(identity, ("STIMULUS",), (link,))])
    ccore = LocalCcore(executable.resolve(strict=True), model_contract.resolve(strict=True),
                       fixture(BASELINE, 3), output)
    try:
        ccore.start()
        backend = CcoreLifecycleBackend(contract, {"quadrotor_hil": ccore.client.endpoint})
        service = ModelLifecycleService(contract, registry, backend)
        receiver = Receiver(contract, registry, lifecycle_service=service)
        opening = fixture(BASELINE, 1)
        opened = deliver(receiver, opening, link, time.monotonic_ns())
        if len(opened) != 1 or opened[0].get("message_id") != 129:
            raise ICDError("SESSION", "标准 Receiver 没有建立生命周期会话: %s" % opened)
        session_id = opened[0]["payload"]["session_id"]
        session_ids = [session_id]
        template = fixture(BASELINE, 4)
        requests, replies = [], []
        for sequence, action, expected, step_count in (
                (2, "PAUSE", "RUNNING", None), (2, "STEP", "PAUSED", 1000),
                (2, "STOP", "PAUSED", None)):
            # A paused model no longer advances its C step, but an original
            # source session still has its frozen 1000ms lease.  Open an
            # explicit fresh source session before each later operation rather
            # than treating an old lease as renewable.
            if action in ("STEP", "STOP"):
                reopening = json.loads(json.dumps(opening))
                reopening["payload"]["nonce_hex"] = ("b" if action == "STEP" else "c") * 32
                renewed = deliver(receiver, reopening, link, time.monotonic_ns())
                if len(renewed) != 1 or renewed[0].get("message_id") != 129:
                    raise ICDError("SESSION", "STEP 前没有建立新的标准源会话: %s" % renewed)
                session_id = renewed[0]["payload"]["session_id"]
                session_ids.append(session_id)
            current = ccore_step(ccore)
            # Receiver admission and complete C snapshot reads occur before
            # staging.  Leave a bounded 500ms C-step margin so the formal
            # service never asks C to apply an already-started boundary.
            target = current + 500 if expected == "RUNNING" else current
            request = lifecycle_message(template, session_id=session_id, sequence=sequence,
                                        action=action, expected_state=expected, target_step=target,
                                        step_count=step_count)
            result = deliver(receiver, request, link, time.monotonic_ns())
            if ([item["payload"].get("stage") for item in result] != ["RECEIVED", "APPLIED"] or
                    result[-1]["payload"].get("probe_id") != 1004 or
                    result[-1]["payload"].get("applied_step") != target + (step_count or 0)):
                record = service.records[-1] if service.records else None
                error = record.error if record else None
                elapsed_ms = ((record.completed_ns - record.received_ns) / 1_000_000
                              if record else None)
                raise ICDError("BUSINESS_FAILED", "标准生命周期服务没有发布相关 C 模型应用反馈: %s / %s / %.3fms" %
                               (result, error, elapsed_ms if elapsed_ms is not None else -1.0))
            actual = ccore.client.status()["fields"]
            expected_c_state = "PAUSED" if action in ("PAUSE", "STEP") else "STOPPED"
            expected_step = target + (step_count or 0)
            if (actual.get("lifecycle") != expected_c_state or actual.get("sequence") != expected_step or
                    actual.get("control_source") != "none" or actual.get("actuator_output") != [0, 0, 0, 0]):
                raise ICDError("MODEL", "标准生命周期服务后的 C 状态/安全输出读回不一致")
            requests.append(request)
            replies.append(result)
        return {
            "format": "HIL_L010_FORMAL_LIFECYCLE_SERVICE_1",
            "status": "SOFTWARE_FORMAL_LIFECYCLE_SERVICE_VALIDATED",
            "execution_scope": "LOCAL_GENERATED_CCORE_NON_RT",
            "session_ids": session_ids,
            "requests": requests,
            "replies": replies,
            "records": [{"error": record.error, "write_attempted": record.write_attempted,
                         "receipt_state": record.receipt.view.state if record.receipt else None,
                         "step_count": len(record.receipt.steps) if record.receipt else None,
                         "actuators_json": record.receipt.actuators_json.decode("utf-8") if record.receipt else None}
                        for record in service.records],
            "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "model_contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest(),
            "not_verified": ["PHYSICAL_ACTUATOR_OR_ESC_READBACK", "RT_DEADLINE_AND_HARDWARE_SAFETY"],
        }
    finally:
        ccore.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-executable", type=Path, required=True)
    parser.add_argument("--model-contract", type=Path,
                        default=ROOT / "artifacts/z_mission/model/hil_contract.json")
    args = parser.parse_args()
    try:
        outcome = run(args.output.resolve(), args.model_executable, args.model_contract)
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        outcome = {"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                   "detail": str(error)}
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
        print(json.dumps(outcome, ensure_ascii=False), flush=True)
        return 1
    (args.output / "result.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    print(json.dumps(outcome, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
