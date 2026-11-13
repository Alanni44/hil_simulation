#!/usr/bin/env python3
"""验证本地生成 C 核心的最终执行器软件读回与 100ms 超时撤权。"""
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
from scripts.verify_l007_canplayer_session_vcan import LocalCcore, fixture


def status(ccore) -> dict:
    reply = ccore.client.status()
    fields = reply.get("fields")
    if not reply.get("accepted") or not isinstance(fields, dict):
        raise ICDError("MODEL", "C 核心没有返回状态读回")
    return reply


def wait_output(ccore, expected: list[float], source: str, *, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        reply = status(ccore)
        fields = reply["fields"]
        output = fields.get("actuator_output")
        sequence = fields.get("sequence")
        output_sequence = fields.get("actuator_output_sequence")
        output_matches = (type(output) is list and len(output) == len(expected) and
                          all(type(actual) in (int, float) and abs(actual - wanted) <= 1e-6
                              for actual, wanted in zip(output, expected)))
        if (fields.get("control_source") == source and output_matches and
                type(sequence) is int and type(output_sequence) is int and
                0 <= output_sequence <= sequence):
            return reply
        time.sleep(.001)
    raise ICDError("TIMEOUT", "C 核心没有返回预期的最终执行器输出/控制源")


def run(output: Path, executable: Path, model_contract: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    ccore = LocalCcore(executable.resolve(strict=True), model_contract.resolve(strict=True),
                       fixture(ROOT / "docs/interfaces/baseline", 3), output)
    command = [0.25, 0.35, 0.45, 0.55]
    safe = [0.0, 0.0, 0.0, 0.0]
    try:
        ccore.start()
        selected = ccore.client.exchange({"request_id": "l010-safety-source", "cmd": "select_control_source",
                                          "params": {"source": "physical_uut"}})
        if not selected.get("accepted"):
            raise ICDError("BUSINESS_FAILED", "C 核心拒绝物理控制源软件模拟")
        submitted = ccore.client.exchange({"request_id": "l010-safety-command", "cmd": "actuator_command",
                                           "params": {"source": "physical_uut", "values": command}})
        if not submitted.get("accepted"):
            raise ICDError("BUSINESS_FAILED", "C 核心拒绝范围内执行器命令")
        active = wait_output(ccore, command, "physical_uut", timeout_s=.08)
        # The timer is measured by C's CLOCK_MONOTONIC at command reception;
        # wait beyond its 100ms lease and require both safe output and owner
        # revocation from the same C status command.
        time.sleep(.13)
        safe_status = wait_output(ccore, safe, "none", timeout_s=.3)
        return {
            "format": "HIL_L010_CCORE_SAFETY_1",
            "status": "SOFTWARE_CCORE_FINAL_ACTUATOR_READBACK_VALIDATED",
            "execution_scope": "LOCAL_GENERATED_CCORE_NON_RT",
            "selected": selected,
            "submitted": submitted,
            "active_status": active,
            "timeout_safe_status": safe_status,
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
