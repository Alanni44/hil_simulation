#!/usr/bin/env python3
"""在已部署目标机上经正式 UDP 生命周期链路验证 L-010。

本工具只供本机受控验收使用：它复用部署授权的 UDP 源端口和既有
Receiver/ModelLifecycleService，不直接写 C 核心。STEP 历史只在动作
已得到正式 APPLIED 回执后作本机只读核验。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from input_simulator.session import SourceSession
from input_simulator.udp_source import UDPSource


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if type(value) is not dict:
        raise ICDError("SCHEMA", "JSON object required: {}".format(path))
    return value


def _preparation_request(url: str, document: dict) -> dict:
    request = Request(url, data=json.dumps(document, separators=(",", ":")).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            reply = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ICDError("STATE", "preparation HTTP {}".format(error.code)) from error
    if reply.get("status") != "SUCCESS":
        raise ICDError(str(reply.get("code", "STATE")), str(reply.get("message", "preparation rejected")))
    return reply


def _prepare(url: str, configuration: dict, run_id: str) -> dict:
    document = {"cmd": "hil_prepare", "params": {
        "api_version": "1.0", "request_id": "l010-target-prepare-" + run_id,
        "prepare_id": "l010-target-prepare-" + run_id, "run_id": run_id,
        "run_configuration": configuration,
    }}
    reply = _preparation_request(url, document)
    if reply.get("status") != "SUCCESS" or reply.get("data", {}).get("state") != "CONFIGURED":
        raise ICDError("STATE", "first-circle preparation was not CONFIGURED: {}".format(reply))
    return reply


def _reset(url: str, run_id: str) -> dict:
    reply = _preparation_request(url, {"cmd": "hil_reset", "params": {
        "api_version": "1.0", "request_id": "l010-target-reset-" + run_id,
        "reset_id": "l010-target-reset-" + run_id, "run_id": run_id,
    }})
    data = reply.get("data", {})
    if data.get("state") != "STOPPED" or data.get("model_step") != "0":
        raise ICDError("STATE", "first-circle reset did not restore STOPPED/step=0: {}".format(reply))
    return reply


def _preparation_status(url: str, request_id: str) -> dict:
    return _preparation_request(url, {"cmd": "hil_status_get", "params": {
        "api_version": "1.0", "request_id": request_id,
    }})


def _status(session: SourceSession, sender_step: int) -> dict:
    reply = session.heartbeat(sender_step, target_step=sender_step, emergency=True)
    if reply.get("message_id") != 131:
        raise ICDError("MODEL", "formal Status response required")
    return reply["payload"]


def _ccore_status() -> dict:
    request = {"request_id": "l010-target-live-status", "cmd": "get_hil_status"}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(2.0)
        client.sendto(json.dumps(request, separators=(",", ":")).encode("utf-8"), ("127.0.0.1", 9997))
        reply = json.loads(client.recvfrom(65535)[0].decode("utf-8"))
    fields = reply.get("fields") if type(reply) is dict else None
    if not reply.get("accepted") or type(fields) is not dict or type(fields.get("sequence")) is not int:
        raise ICDError("MODEL", "C-core live status is unavailable")
    return fields


def _lifecycle(session: SourceSession, action: str, expected_state: str, target_step: int,
               *, step_count: int | None = None) -> tuple[dict, dict]:
    payload = {"action": action, "expected_state": expected_state, "reset_policy": "NOT_APPLICABLE"}
    if step_count is not None:
        payload["step_count"] = step_count
    reply = session.request({"message_id": 4, "payload": payload}, target_step=target_step, emergency=True)
    if (reply.get("message_id") != 130 or reply.get("payload", {}).get("stage") != "APPLIED"
            or reply["payload"].get("error") != "OK"):
        raise ICDError("BUSINESS_FAILED", "{} lacks formal APPLIED receipt: {}".format(action, reply))
    return session.records[-1].request, reply


def _step_history(stage_request_id: str, count: int) -> list[dict]:
    request = {"request_id": "l010-target-step-history", "cmd": "get_lifecycle_step_result",
               "params": {"stage_request_id": stage_request_id, "start_index": 0, "count": count}}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(2.0)
        client.sendto(json.dumps(request, separators=(",", ":")).encode("utf-8"), ("127.0.0.1", 9997))
        reply = json.loads(client.recvfrom(65535)[0].decode("utf-8"))
    fields = reply.get("fields") if type(reply) is dict else None
    samples = fields.get("samples") if type(fields) is dict else None
    if (not reply.get("accepted") or fields.get("stage_request_id") != stage_request_id
            or fields.get("total_count") != count or type(samples) is not list or len(samples) != count):
        raise ICDError("MODEL", "C-core STEP history is incomplete: {}".format(reply))
    if any(sample.get("actuator_output") != [0, 0, 0, 0] for sample in samples):
        raise ICDError("MODEL", "STEP history contains a non-safe actuator output")
    return samples


def _new_session(contract: Contract, grant: dict, receiver: tuple[str, int]) -> tuple[UDPSource, SourceSession]:
    source_endpoint = grant["source_endpoint"]
    feedback_endpoint = grant["feedback_endpoint"]
    source = UDPSource(contract, source_bind=(source_endpoint["ip"], source_endpoint["port"]),
                       feedback_bind=(feedback_endpoint["ip"], feedback_endpoint["port"]),
                       receiver_endpoint=receiver, channel="ETH_0")
    return source, SourceSession(source, grant["identity"], tuple(grant["roles"]))


def run(args: argparse.Namespace) -> dict:
    contract = Contract.load(args.contract_dir, expected_sha256=args.expected_sha256)
    deployment = _read_json(args.deployment)
    grant = deployment["grants"][0]
    receiver_config = deployment["receiver_bind"]
    receiver = (receiver_config["ip"], receiver_config["port"])
    external = _read_json(args.external)
    configuration = external["run_configuration"]
    run_id = args.run_id
    before = _preparation_status(args.preparation_url, "l010-target-before-" + run_id)
    state = before["data"]["state"]
    step = before["data"]["model_step"]
    reset = None
    preparation = None
    if state == "STOPPED" and step != "0":
        reset = _reset(args.preparation_url, run_id)
        state, step = "STOPPED", "0"
    if state == "STOPPED" and step == "0":
        preparation = _prepare(args.preparation_url, configuration, run_id)
    elif state != "CONFIGURED" or step != "0":
        raise ICDError("STATE", "L-010 validation requires STOPPED/0 or CONFIGURED/0: {}".format(before))
    source, session = _new_session(contract, grant, receiver)
    actions: list[dict] = []
    started = False
    try:
        opened = session.open()
        initial = _ccore_status()
        request, reply = _lifecycle(session, "START", "CONFIGURED", initial["sequence"])
        actions.append({"action": "START", "request": request, "reply": reply})
        started = True
        time.sleep(0.05)
        running = _ccore_status()
        pause_target = running["sequence"] + 200
        request, reply = _lifecycle(session, "PAUSE", "RUNNING", pause_target)
        actions.append({"action": "PAUSE", "request": request, "reply": reply})

        session.abandon(); opened = session.open()
        paused = _ccore_status()
        request, reply = _lifecycle(session, "STEP", "PAUSED", paused["sequence"], step_count=args.step_count)
        # 与 CcoreLifecycleBackend 生成的请求标识完全一致；C 核按该标识
        # 保留并查询这一次 STEP 的逐步历史。
        stage_id = "lifecycle-step-{}-{}".format(request["header"]["session_id"], request["header"]["sequence"])
        history = _step_history(stage_id, args.step_count)
        actions.append({"action": "STEP", "request": request, "reply": reply,
                        "stage_request_id": stage_id, "samples": history})

        session.abandon(); opened = session.open()
        paused = _ccore_status()
        request, reply = _lifecycle(session, "RESUME", "PAUSED", paused["sequence"])
        actions.append({"action": "RESUME", "request": request, "reply": reply})
        time.sleep(0.03)

        session.abandon(); opened = session.open()
        running = _ccore_status()
        request, reply = _lifecycle(session, "PAUSE", "RUNNING", running["sequence"] + 200)
        actions.append({"action": "PAUSE_AFTER_RESUME", "request": request, "reply": reply})
        session.abandon(); opened = session.open()
        paused = _ccore_status()
        request, reply = _lifecycle(session, "STOP", "PAUSED", paused["sequence"])
        actions.append({"action": "STOP", "request": request, "reply": reply})
        started = False
        final = _ccore_status()
        if final.get("lifecycle") != "STOPPED" or final.get("control_source") != "none":
            raise ICDError("MODEL", "final formal Status is not STOPPED/NONE: {}".format(final))
        return {"format": "HIL_L010_FORMAL_TARGET_VALIDATION_1", "status": "PASSED",
                "scope": "DEPLOYED_FORMAL_UDP_LIFECYCLE_AND_CCORE", "before": before, "reset": reset,
                "preparation": preparation,
                "actions": actions, "final_status": final,
                "not_verified": ["PHYSICAL_ACTUATOR_OR_ESC_READBACK", "RT_DEADLINE_AND_HARDWARE_SAFETY"]}
    finally:
        if started:
            try:
                current = _ccore_status()
                state, step = current.get("lifecycle"), current.get("sequence", 0)
                if state in ("RUNNING", "PAUSED"):
                    _lifecycle(session, "STOP", state, step + (200 if state == "RUNNING" else 0))
            except Exception:
                pass
        session.close()
        source.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, default=ROOT / "docs/interfaces/baseline")
    parser.add_argument("--expected-sha256", default="22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27")
    parser.add_argument("--deployment", type=Path, default=ROOT / "config/minimal-integration-gateway.json")
    parser.add_argument("--external", type=Path, default=ROOT / "config/quadrotor_hil.external.json")
    parser.add_argument("--preparation-url", default="http://127.0.0.1:18081/api/hil/preparation/commands")
    parser.add_argument("--run-id", default="l010-formal-target-validation")
    parser.add_argument("--step-count", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.step_count <= 1000:
        parser.error("--step-count 必须为 1..1000")
    try:
        result = run(args)
    except (ICDError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        result = {"format": "HIL_L010_FORMAL_TARGET_VALIDATION_1", "status": "FAILED",
                  "error": error.code if isinstance(error, ICDError) else "STATE", "detail": str(error)}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
