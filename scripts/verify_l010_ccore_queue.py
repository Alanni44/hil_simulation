#!/usr/bin/env python3
"""在本地生成 C 模型验证 L-010 的实际通用绑定队列。

验证对象是 ``stage_icd_group`` 到 C 模型 1ms 写入点的队列，而不是 Python
ModelQueue。它保留 4096 条已完成事务，以便逐请求查询实际读回；PAUSE/RESUME
会清理该运行的队列，随后可重新接收请求。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_runtime.errors import ICDError
from scripts.verify_l004_model_boundary import group_values
from scripts.verify_l007_canplayer_session_vcan import LocalCcore, fixture


GROUPS = ("flight_control", "environment", "fault", "parameters")
CAPACITY = 4096


def current_step(core) -> int:
    reply = core.client.status()
    if not reply.get("accepted") or reply.get("lifecycle") != "RUNNING":
        raise ICDError("MODEL", "C 核心没有处于 RUNNING 状态")
    step = reply.get("fields", {}).get("sequence")
    if type(step) is not int or step < 0:
        raise ICDError("MODEL", "C 核心没有返回实际 sequence")
    return step


def wait_step(core, target: int) -> None:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if current_step(core) >= target:
            return
        time.sleep(.001)
    raise ICDError("TIMEOUT", "C 核心没有到达已接受事务的目标步")


def stage(core, *, request_id: str, group: str, target: int, values: dict) -> dict:
    reply = core.client.exchange({"request_id": request_id, "cmd": "stage_icd_group", "params": {
        "target_step": target, "deadline_ns": time.monotonic_ns() + 3_000_000_000,
        "group": group, "values": values}})
    if (not reply.get("accepted") or reply.get("reason") != "staged" or
            reply.get("effective_sequence") != target):
        raise ICDError("BUSINESS_FAILED", "C 核心未保留完整通用绑定事务: %s" % reply)
    return reply


def result(core, *, request_id: str, group: str, target: int, values: dict) -> dict:
    reply = core.client.exchange({"request_id": request_id + "-result", "cmd": "get_icd_group_result",
                                  "params": {"group": group, "stage_request_id": request_id}})
    fields = reply.get("fields", {})
    if (not reply.get("accepted") or fields.get("state") != "APPLIED" or
            fields.get("target_step") != target or fields.get("applied_step") != target or
            fields.get("readback") != values):
        raise ICDError("MODEL", "C 核心保留的事务结果不等于实际分组读回")
    return reply


def lifecycle(core, action: str, target: int) -> dict:
    reply = core.client.exchange({"request_id": "l010-queue-" + action.lower(),
                                  "cmd": "stage_lifecycle",
                                  "params": {"action": action, "target_step": target}})
    if not reply.get("accepted") or reply.get("reason") != "applied":
        raise ICDError("BUSINESS_FAILED", "C 核心拒绝队列验证中的生命周期边界")
    return reply


def run(output: Path, executable: Path, model_contract: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    contract = json.loads(model_contract.read_text(encoding="utf-8"))
    values = {group: group_values(contract, group, altered=False) for group in GROUPS}
    ccore = LocalCcore(executable.resolve(strict=True), model_contract.resolve(strict=True),
                       fixture(ROOT / "docs/interfaces/baseline", 3), output)
    try:
        ccore.start()
        # Two different targets for environment prove that a later request
        # cannot overwrite an earlier staged request from the same group.
        first_target = current_step(ccore) + 35
        staged_ids = []
        for group in GROUPS:
            request_id = "l010-order-%s" % group
            stage(ccore, request_id=request_id, group=group, target=first_target, values=values[group])
            staged_ids.append((request_id, group, first_target))
        second_target = first_target + 20
        stage(ccore, request_id="l010-order-environment-2", group="environment",
              target=second_target, values=values["environment"])
        duplicate = ccore.client.exchange({"request_id": "l010-overlap", "cmd": "stage_icd_group", "params": {
            "target_step": second_target, "deadline_ns": time.monotonic_ns() + 3_000_000_000,
            "group": "environment", "values": values["environment"]}})
        if duplicate.get("accepted"):
            raise ICDError("STATE", "同组同目标步覆盖请求没有被 C 核心拒绝")
        wait_step(ccore, second_target)
        ordered_results = [result(ccore, request_id=request_id, group=group,
                                  target=target, values=values[group])
                           for request_id, group, target in staged_ids]
        ordered_results.append(result(ccore, request_id="l010-order-environment-2",
                                      group="environment", target=second_target,
                                      values=values["environment"]))

        # Fill the actual C queue over successive future 1ms boundaries.  All
        # records remain queryable, so the final request must be rejected by
        # C's own 4096-entry bound rather than by a test-side counter.
        capacity_first_target = None
        capacity_last_target = None
        full_batches, remainder = divmod(CAPACITY - len(ordered_results), len(GROUPS))
        for batch in range(full_batches):
            target = current_step(ccore) + 25
            if capacity_first_target is None:
                capacity_first_target = target
            capacity_last_target = target
            for group in GROUPS:
                stage(ccore, request_id="l010-cap-%04d-%s" % (batch, group),
                      group=group, target=target, values=values[group])
            wait_step(ccore, target)
        if remainder:
            target = current_step(ccore) + 25
            capacity_last_target = target
            for group in GROUPS[:remainder]:
                stage(ccore, request_id="l010-cap-%04d-%s" % (full_batches, group),
                      group=group, target=target, values=values[group])
            wait_step(ccore, target)
        capacity_target = current_step(ccore) + 25
        full = ccore.client.exchange({"request_id": "l010-capacity-full", "cmd": "stage_icd_group", "params": {
            "target_step": capacity_target, "deadline_ns": time.monotonic_ns() + 3_000_000_000,
            "group": "environment", "values": values["environment"]}})
        if full.get("accepted") or "4096" not in full.get("reason", ""):
            raise ICDError("STATE", "C 核心没有在第 4097 条事务拒绝入队")
        retained_first = result(ccore, request_id="l010-cap-0000-environment", group="environment",
                                target=capacity_first_target, values=values["environment"])
        retained_last_group = GROUPS[remainder - 1]
        retained_last = result(ccore, request_id="l010-cap-%04d-%s" %
                               (full_batches, retained_last_group), group=retained_last_group,
                               target=capacity_last_target, values=values[retained_last_group])

        paused = lifecycle(ccore, "PAUSE", current_step(ccore) + 25)
        paused_step = paused["effective_sequence"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = ccore.client.status()
            if status.get("lifecycle") == "PAUSED":
                break
            time.sleep(.002)
        else:
            raise ICDError("TIMEOUT", "PAUSE 未在 C 边界完成")
        resumed = lifecycle(ccore, "RESUME", paused_step)
        wait_step(ccore, paused_step + 1)
        fresh_target = current_step(ccore) + 25
        stage(ccore, request_id="l010-after-resume", group="environment",
              target=fresh_target, values=values["environment"])
        wait_step(ccore, fresh_target)
        fresh = result(ccore, request_id="l010-after-resume", group="environment",
                       target=fresh_target, values=values["environment"])
        return {
            "format": "HIL_L010_CCORE_QUEUE_1",
            "status": "SOFTWARE_CCORE_QUEUE_VALIDATED",
            "execution_scope": "LOCAL_GENERATED_CCORE_NON_RT",
            "capacity": CAPACITY,
            "ordered_applied": [{"request_id": item["request_id"], "effective_sequence": item["effective_sequence"]}
                                for item in ordered_results],
            "overlap_rejection": duplicate,
            "capacity_rejection": full,
            "retained_first": retained_first,
            "retained_last": retained_last,
            "pause": paused,
            "resume": resumed,
            "post_resume_application": fresh,
            "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "model_contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest(),
            "not_verified": ["FORMAL_3_6_LIFECYCLE_SERVICE", "SAFE_ACTUATOR_OUTPUT_READBACK",
                             "RT_DEADLINE_AND_HARDWARE_SAFETY"],
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
