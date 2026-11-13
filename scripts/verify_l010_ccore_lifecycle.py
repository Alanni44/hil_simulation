#!/usr/bin/env python3
"""L-010 当前 C 核心生命周期边界的软件验证。

仅覆盖生成 C 模型已经提供的 target-step lifecycle 命令和状态读回。它
明确不把 C 中的单槽 pending_live/staging 当作 4096 输入队列，也不把
本地非 RT 进程或状态字段当作实体安全输出证据。
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
from scripts.verify_l004_model_boundary import Core as CcoreClient
from scripts.verify_l007_canplayer_session_vcan import LocalCcore, fixture


def status(client: CcoreClient) -> dict:
    reply = client.status()
    fields = reply.get("fields")
    if not reply.get("accepted") or not isinstance(fields, dict):
        raise ICDError("MODEL", "C 核心没有提供完整状态读回")
    return reply


def wait_status(client: CcoreClient, lifecycle: str, *, after_step: int | None = None) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        reply = status(client)
        fields = reply["fields"]
        if (fields.get("lifecycle") == lifecycle and
                (after_step is None or fields.get("sequence", -1) > after_step)):
            return reply
        time.sleep(0.002)
    raise ICDError("TIMEOUT", "C 核心没有到达请求的生命周期/步边界")


def stage(client: CcoreClient, action: str, target_step: int, records: list[dict]) -> dict:
    request_id = "l010-%s-%d" % (action.lower(), target_step)
    reply = client.exchange({"request_id": request_id, "cmd": "stage_lifecycle",
                             "params": {"action": action, "target_step": target_step}})
    records.append({"request": {"request_id": request_id, "action": action, "target_step": target_step},
                    "reply": reply})
    if not reply.get("accepted") or reply.get("reason") != "applied":
        raise ICDError("BUSINESS_FAILED", "C 核心拒绝生命周期目标边界")
    return reply


def run(output: Path, executable: Path, model_contract: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    ccore = LocalCcore(executable.resolve(strict=True), model_contract.resolve(strict=True),
                       fixture(ROOT / "docs/interfaces/baseline", 3), output)
    records: list[dict] = []
    try:
        ccore.start()
        running = wait_status(ccore.client, "RUNNING")
        first_step = int(running["fields"]["sequence"])

        pause = stage(ccore.client, "PAUSE", first_step + 40, records)
        paused = wait_status(ccore.client, "PAUSED")
        paused_step = int(paused["fields"]["sequence"])
        if paused_step != int(pause["effective_sequence"]):
            raise ICDError("STATE", "PAUSE 收据与 C 状态步不一致")
        time.sleep(0.03)
        frozen = status(ccore.client)
        if int(frozen["fields"]["sequence"]) != paused_step:
            raise ICDError("STATE", "PAUSED 期间 C 模型步仍在推进")

        resume = stage(ccore.client, "RESUME", paused_step, records)
        resumed = wait_status(ccore.client, "RUNNING", after_step=paused_step)
        if int(resume["effective_sequence"]) != paused_step:
            raise ICDError("STATE", "RESUME 未在冻结的实际边界执行")

        stop_target = int(resumed["fields"]["sequence"]) + 40
        stop = stage(ccore.client, "STOP", stop_target, records)
        stopped = wait_status(ccore.client, "STOPPED")
        if (int(stopped["fields"]["sequence"]) != int(stop["effective_sequence"])
                or stopped["fields"].get("control_source") != "none"):
            raise ICDError("STATE", "STOP 没有在 C 边界撤销控制源")

        reset = stage(ccore.client, "RESET", int(stopped["fields"]["sequence"]), records)
        reset_state = wait_status(ccore.client, "STOPPED")
        if int(reset["effective_sequence"]) != 0 or int(reset_state["fields"]["sequence"]) != 0:
            raise ICDError("STATE", "RESET 没有恢复 C 模型初始步边界")
        return {"format": "HIL_L010_CCORE_LIFECYCLE_1", "status": "SOFTWARE_LIFECYCLE_BOUNDARY_VALIDATED",
                "execution_scope": "LOCAL_GENERATED_CCORE_NON_RT", "records": records,
                "final_status": reset_state, "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "model_contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest(),
                "not_verified": ["4096_ACTUAL_C_QUEUE", "PER_INPUT_NO_OVERWRITE_OR_CATCHUP",
                                 "SAFE_ACTUATOR_OUTPUT_READBACK", "FORMAL_3_6_LIFECYCLE_SERVICE",
                                 "RT_DEADLINE_AND_HARDWARE_SAFETY"]}
    finally:
        ccore.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-executable", type=Path,
                        default=ROOT / "artifacts/z_mission/bin/quadrotor_hil_rt")
    parser.add_argument("--model-contract", type=Path,
                        default=ROOT / "artifacts/z_mission/model/hil_contract.json")
    args = parser.parse_args()
    try:
        result = run(args.output.resolve(), args.model_executable, args.model_contract)
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        result = {"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                  "detail": str(error)}
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
