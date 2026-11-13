#!/usr/bin/env python3
"""生成 L-014 Robot/目标验收的唯一、不可跳项证据包。

此入口只汇集已存在的原始软件/目标证据，不发送报文、不启动模型，也不把
某一子项的软件成功提升为目标验收。每个 L01--L09、T01--T13 都必须拥有
原始 TX/RX、E1/E2/E3、业务和安全结果才能通过；缺任意一项即明确失败。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "docs/interfaces/baseline/input-simulator-coverage-v0.3.json"

CASES = tuple(["L%02d" % number for number in range(1, 10)] +
              ["T%02d" % number for number in range(1, 14)])

# 仅作为可追溯的既有材料，不是对相应 L/T 用例的替代或通过判定。
RELATED_EVIDENCE = {
    "L01": ("artifacts/linux_target/l002-icd-runtime-20261012.json",),
    "L02": ("artifacts/linux_target/l006-savvycan-authorized-20261112T191000Z/result.json",),
    "L03": ("artifacts/linux_target/l005-socketcan-vcan-20261029T115446Z.json",
            "artifacts/linux_target/l012-video-software-20261112T193000Z/result.json"),
    "L04": ("artifacts/linux_target/l007-ccore-applied-20261111T121840Z/result.json",),
    "L05": ("artifacts/linux_target/l010-ccore-lifecycle-20261111T123538Z/result.json",),
    "L06": (),
    "L07": ("artifacts/linux_target/l004-three-model-boundary-20261029T114827Z.json",
            "artifacts/linux_target/l012-video-software-20261112T193000Z/result.json"),
    "L08": ("artifacts/linux_target/l010-step-candidate-20261112T100000Z/lifecycle/result.json",),
    "L09": ("artifacts/linux_target/l007-ccore-applied-20261111T121840Z/result.json",),
    "T01": ("artifacts/linux_target/l013-rt-affinity-probe-r2-20261112/result.json",),
    "T02": ("artifacts/linux_target/l010-step-candidate-20261112T100000Z/lifecycle/result.json",),
    "T03": ("artifacts/linux_target/l004-three-model-boundary-20261029T114827Z.json",),
    "T04": (), "T05": (), "T06": (), "T07": (), "T08": (), "T09": (),
    "T10": (),
    "T11": ("artifacts/linux_target/l012-video-software-20261112T193000Z/result.json",),
    "T12": ("artifacts/linux_target/l013-rt-affinity-probe-r2-20261112/result.json",),
    "T13": ("artifacts/linux_target/l013-rt-affinity-probe-r2-20261112/result.json",),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_paths(case_id: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for relative in RELATED_EVIDENCE[case_id]:
        path = ROOT / relative
        if path.is_file():
            result.append({"path": relative, "sha256": sha256(path)})
    return result


def requirements_by_case() -> dict[str, list[str]]:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    if coverage.get("status") != "DESIGN_COVERAGE_ONLY":
        raise ValueError("unexpected coverage baseline state")
    mapping = {case_id: [] for case_id in CASES}
    for requirement in coverage["requirements"]:
        for case_id in requirement["acceptance"]:
            if case_id in mapping:
                mapping[case_id].append(requirement["id"])
    return mapping


def case_result(case_id: str, requirements: list[str]) -> dict[str, Any]:
    evidence = evidence_paths(case_id)
    required_missing = [
        "raw_tx", "raw_rx", "E1_RECEIVE_OR_VALIDATION", "E2_REAL_CONSUMER_OR_MODEL_EFFECT",
        "E3_BUSINESS_OR_SAFETY_RESPONSE", "business_assertion", "safety_assertion",
    ]
    return {
        "case_id": case_id,
        "required": True,
        "requirements": requirements,
        "status": "FAILED_REQUIRED_EVIDENCE",
        "related_prior_evidence": evidence,
        "evidence_stage": {"E1": "NOT_EVALUATED", "E2": "NOT_EVALUATED", "E3": "NOT_EVALUATED"},
        "business": "NOT_EVALUATED",
        "safety": "NOT_EVALUATED",
        "missing": required_missing,
        "reason": "L-014 has no dedicated Robot/API execution with complete target TX/RX and E1/E2/E3 evidence",
    }


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("output evidence directory already exists")
    mapping = requirements_by_case()
    cases = [case_result(case_id, mapping[case_id]) for case_id in CASES]
    output.mkdir(parents=True)
    manifest = {
        "format": "HIL_L014_TARGET_ACCEPTANCE_1",
        "status": "FAILED_REQUIRED_EVIDENCE",
        "execution_host": "Linux %s (%s)" % (platform.release(), platform.machine()),
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "coverage": {"path": str(COVERAGE.relative_to(ROOT)), "sha256": sha256(COVERAGE)},
        "cases": cases,
        "summary": {"required": len(cases), "passed": 0, "failed": len(cases), "skipped": 0},
        "global_blockers": [
            "L-013 realtime gate failed on the current QEMU target",
            "no dedicated Robot/API target execution is installed",
            "complete raw TX/RX and E1/E2/E3 evidence is absent for every required case",
        ],
    }
    (output / "result.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.output.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        result = {"format": "HIL_L014_TARGET_ACCEPTANCE_1", "status": "FAILED",
                  "error": type(error).__name__, "detail": str(error)}
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
