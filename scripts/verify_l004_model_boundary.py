#!/usr/bin/env python3
"""Run L-004 generated-model boundary evidence on the local Linux target.

This is a development-mode verification: it starts each real ERT executable
with HIL_ALLOW_NONRT=1, writes all four complete frozen groups at a requested
model step, and preserves the raw C receipts plus observed model/sensor data.
It intentionally does not claim a physical CANFD or real-time qualification.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs/interfaces/baseline/input-simulator-v0.3.examples.json"
MODELS = (
    ("quadrotor_hil", ROOT / "artifacts/z_mission/bin/quadrotor_hil_rt",
     ROOT / "artifacts/z_mission/model/hil_contract.json", 7, 11, 17),
    ("multirotor_6_hil", ROOT / "artifacts/generic_models/multirotor_6/bin/multirotor_6_hil_rt",
     ROOT / "artifacts/generic_models/multirotor_6/hil_contract.json", 8, 12, 18),
    ("fixed_wing_hil", ROOT / "artifacts/generic_models/fixed_wing/bin/fixed_wing_hil_rt",
     ROOT / "artifacts/generic_models/fixed_wing/hil_contract.json", 9, 13, 19),
)


def load_fixtures() -> dict[int, dict[str, Any]]:
    return {item["value"]["message_id"]: item["value"]
            for item in json.loads(FIXTURES.read_text())["fixtures"]}


def number(value: Any) -> float:
    return float(value)


def equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(number(left) - number(right)) <= 1e-9
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(equivalent(left[key], right[key]) for key in left)
    return left == right


class Core:
    def __init__(self, endpoint: tuple[str, int]):
        self.endpoint = endpoint
        self.records: list[dict[str, Any]] = []

    def exchange(self, command: dict[str, Any]) -> dict[str, Any]:
        peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            deadline = time.monotonic() + 1.0
            peer.settimeout(0.1)
            peer.sendto(json.dumps(command, separators=(",", ":")).encode("utf-8"), self.endpoint)
            while time.monotonic() < deadline:
                try:
                    raw, sender = peer.recvfrom(65536)
                except socket.timeout:
                    continue
                if sender[0] != self.endpoint[0]:
                    continue
                try:
                    reply = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    # The local C process also emits binary status packets.
                    # A transient OS reuse of that UDP port is unrelated to
                    # this command; only its exact command receipt is valid.
                    continue
                if type(reply) is dict and reply.get("request_id") == command.get("request_id"):
                    self.records.append({"command": command, "receipt": reply})
                    return reply
            raise TimeoutError("timed out waiting for the matching C receipt")
        finally:
            peer.close()

    def status(self) -> dict[str, Any]:
        return self.exchange({"request_id": "l004-status", "cmd": "get_hil_status", "params": {}})

    def wait_running(self) -> int:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            reply = self.status()
            if reply["accepted"] and reply["lifecycle"] == "RUNNING" and reply["effective_sequence"] > 0:
                return int(reply["effective_sequence"])
            time.sleep(.005)
        raise RuntimeError("model did not advance after START")

    def stage(self, group: str, values: dict[str, Any]) -> dict[str, Any]:
        step = self.wait_running() + 30
        name = "l004-%s-%d" % (group, step)
        deadline_ns = time.monotonic_ns() + 2_000_000_000
        staged = self.exchange({"request_id": name, "cmd": "stage_icd_group", "params": {
            "target_step": step, "deadline_ns": deadline_ns, "group": group, "values": values}})
        if not staged.get("accepted") or staged.get("effective_sequence") != step:
            raise RuntimeError("%s was not staged at its target step: %s" % (group, staged))
        while time.monotonic_ns() < deadline_ns:
            result = self.exchange({"request_id": name + "-result", "cmd": "get_icd_group_result", "params": {
                "group": group, "stage_request_id": name}})
            fields = result.get("fields", {})
            if fields.get("state") == "STAGED":
                time.sleep(.002)
                continue
            if (not result.get("accepted") or fields.get("state") != "APPLIED"
                    or fields.get("target_step") != step or fields.get("applied_step") != step
                    or not equivalent(fields.get("readback"), values)):
                raise RuntimeError("%s C getter readback differs: %s" % (group, result))
            return result
        raise RuntimeError("%s missed its requested boundary" % group)


def port_value(descriptor: dict[str, Any], name: str, *, altered: bool) -> Any:
    if descriptor["type"] == "bool":
        return altered and name.startswith("motor_")
    if descriptor["dimension"] > 1:
        return [0.95 if altered else 0.0 for _ in range(descriptor["dimension"])]
    if not altered:
        return float(descriptor.get("default", 0.0))
    minimum, maximum = float(descriptor["min"]), float(descriptor["max"])
    if name == "pressure_pa":
        return 100000.0
    if name == "temperature_k":
        return 290.0
    if name == "ground_height_m":
        return 0.0
    if name.endswith("delay_ms"):
        return 40.0
    if name == "packet_loss_ratio":
        return 0.0
    return min(maximum, max(minimum, minimum + (maximum - minimum) * .1))


def group_values(contract: dict[str, Any], group: str, *, altered: bool) -> dict[str, Any]:
    if group == "parameters":
        result = {}
        for item in contract["parameters"]:
            default = item["default"]
            if item["type"] == "bool":
                result[item["name"]] = bool(default)
            elif altered:
                result[item["name"]] = min(float(item["max"]), float(default) * 1.05 + .001)
            else:
                result[item["name"]] = float(default)
        return result
    return {name: port_value(descriptor, name, altered=altered)
            for name, descriptor in contract["inputs"][group]["ports"].items()}


def configuration(model_id: str, contract: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(fixture["payload"])
    value["model_id"] = model_id
    initial = value["initial_inputs"]
    initial["model_id"] = model_id
    for group in ("flight_control", "environment", "fault"):
        initial[group] = group_values(contract, group, altered=False)
    initial["parameters"] = group_values(contract, "parameters", altered=False)
    value["terrain_resource_sha256"] = None
    value["obstacle_resource_sha256"] = None
    return value


def state_score(status: dict[str, Any], fixed_wing: bool) -> float:
    model = status["fields"]["model_state"]
    if fixed_wing:
        return abs(float(model["vn_mps"])) + abs(float(model["position"]["north_m"]))
    # The simplified multirotor model clamps its NED position to the ground;
    # its generated acceleration remains the observable physical response at
    # that boundary and is therefore the correct delay probe.
    return abs(float(model["az_mps2"]))


def configure_and_start(core: Core, config: dict[str, Any]) -> None:
    reply = core.exchange({"request_id": "l004-configure", "cmd": "configure", "params": {
        "configuration": config,
        "resource_context": {"terrain_sha256": None, "obstacle_sha256": None, "ground_down": 0.0},
        "expected_boundary": {"lifecycle": "STOPPED", "model_step": 0,
                              "model_revision": 0, "control_source": "none"}}})
    if not reply.get("accepted") or reply.get("lifecycle") != "CONFIGURED":
        raise RuntimeError("RunConfigure failed: %s" % reply)
    started = core.exchange({"request_id": "l004-start", "cmd": "start", "params": {}})
    if not started.get("accepted"):
        raise RuntimeError("START failed: %s" % started)
    core.wait_running()


def sensor_north(packet: bytes) -> tuple[int, float]:
    if len(packet) != 148:
        raise RuntimeError("unexpected FlightStateV3 sensor size %d" % len(packet))
    values = struct.unpack("<IQdddd13fBBH11fBBH", packet)
    return int(values[1]), float(values[3])


def run_one(index: int, model: tuple[str, Path, Path, int, int, int], fixture: dict[int, dict[str, Any]]) -> dict[str, Any]:
    model_id, executable, contract_path, flight_id, fault_id, parameter_id = model
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("missing executable %s" % executable)
    contract = json.loads(contract_path.read_text())
    command_port, status_port = 24000 + index * 10 + 7, 24000 + index * 10 + 8
    sensor_port = 26000 + index
    environment = dict(os.environ, HIL_ALLOW_NONRT="1", HIL_UDP_CMD_PORT=str(command_port),
                       HIL_UDP_STATUS_PORT=str(status_port), HIL_UDP_SENSOR_PORT=str(sensor_port),
                       HIL_V3_TCP_PORT=str(25000 + index))
    log_path = ROOT / "artifacts/linux_target" / ("l004-%s-runtime.log" % model_id)
    with log_path.open("wb") as log:
        process = subprocess.Popen([str(executable)], cwd=str(ROOT), env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        sensor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sensor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sensor.bind(("127.0.0.1", sensor_port))
        sensor.settimeout(.3)
        try:
            core = Core(("127.0.0.1", command_port))
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    status = core.status()
                    if status.get("accepted"):
                        break
                except OSError:
                    time.sleep(.01)
            else:
                raise RuntimeError("%s did not bind its model bridge" % model_id)
            config = configuration(model_id, contract, fixture[3])
            configure_and_start(core, config)
            initial = core.exchange({"request_id": "l004-initial", "cmd": "get_icd_snapshot",
                                     "params": {"snapshot": "initial"}})
            if not initial.get("accepted") or not equivalent(initial["fields"]["inputs"], {
                    key: config["initial_inputs"][key] for key in ("flight_control", "environment", "fault")
            }) or not equivalent(initial["fields"]["parameters"], config["initial_inputs"]["parameters"]):
                raise RuntimeError("initial generated getter does not match configured full snapshot")

            values = {
                "flight_control": group_values(contract, "flight_control", altered=True),
                "environment": group_values(contract, "environment", altered=True),
                "fault": group_values(contract, "fault", altered=True),
                "parameters": group_values(contract, "parameters", altered=True),
            }
            applied = {group: core.stage(group, payload) for group, payload in values.items()}
            active = core.exchange({"request_id": "l004-active", "cmd": "get_icd_snapshot",
                                    "params": {"snapshot": "active"}})
            if not active.get("accepted") or not equivalent(active["fields"]["inputs"], {
                    key: values[key] for key in ("flight_control", "environment", "fault")
            }) or not equivalent(active["fields"]["parameters"], values["parameters"]):
                raise RuntimeError("active generated getter does not match all four applied groups: %s" % active)

            malformed = dict(values["fault"])
            removed = next(iter(malformed))
            malformed.pop(removed)
            malformed["unknown_field"] = False
            rejected = core.exchange({"request_id": "l004-unknown", "cmd": "stage_icd_group", "params": {
                "target_step": core.wait_running() + 20, "deadline_ns": time.monotonic_ns() + 1_000_000_000,
                "group": "fault", "values": malformed}})
            if rejected.get("accepted"):
                raise RuntimeError("unknown fault field was accepted")

            # RESET must remove every frozen generic group before the sensor
            # check: the configured zero-flight snapshot gives one stable
            # truth position against which the sensor-only GPS bias is exact.
            reset = core.exchange({"request_id": "l004-reset", "cmd": "reset", "params": {}})
            if not reset.get("accepted"):
                raise RuntimeError("RESET failed: %s" % reset)
            restored = core.exchange({"request_id": "l004-restored", "cmd": "get_icd_snapshot",
                                      "params": {"snapshot": "active"}})
            if not equivalent(restored["fields"]["inputs"], {
                    key: config["initial_inputs"][key] for key in ("flight_control", "environment", "fault")
            }) or not equivalent(restored["fields"]["parameters"], config["initial_inputs"]["parameters"]):
                raise RuntimeError("RESET did not restore the full configured initial snapshot")
            started = core.exchange({"request_id": "l004-restart", "cmd": "start", "params": {}})
            if not started.get("accepted"):
                raise RuntimeError("START after RESET failed")
            core.wait_running()
            sensor.setblocking(False)
            try:
                while True:
                    sensor.recvfrom(512)
            except BlockingIOError:
                pass
            finally:
                sensor.settimeout(.3)

            # Sensor fault effects are applied only to the sensor stream; C
            # status stays model truth.  Bias gives a stable observable gap.
            sensor_fault = group_values(contract, "fault", altered=False)
            sensor_fault["gps_bias_n_m"] = 3.0
            sensor_fault["sensor_delay_ms"] = 0.0
            sensor_fault["packet_loss_ratio"] = 0.0
            sensor_fault_result = core.stage("fault", sensor_fault)
            sensor_min_step = sensor_fault_result["fields"]["applied_step"]
            sensor_active = core.exchange({"request_id": "l004-sensor-active", "cmd": "get_icd_snapshot",
                                           "params": {"snapshot": "active"}})
            if not equivalent(sensor_active["fields"]["inputs"]["fault"], sensor_fault):
                raise RuntimeError("sensor fault group did not remain active: %s" % sensor_active)
            while True:
                raw, _ = sensor.recvfrom(512)
                sensor_step, sensor_north_value = sensor_north(raw)
                if sensor_step >= sensor_min_step:
                    break
            truth = core.status()["fields"]["model_state"]["position"]["north_m"]
            if abs((sensor_north_value - float(truth)) - 3.0) > .05:
                raise RuntimeError("sensor GPS bias leaked into model truth or sensor stream: sensor=%s truth=%s step=%s target=%s packet=%s" % (sensor_north_value, truth, sensor_step, sensor_min_step, struct.unpack("<IQdddd13fBBH11fBBH", raw)[:6]))
            sensor_fault["packet_loss_ratio"] = 1.0
            core.stage("fault", sensor_fault)
            while True:
                try:
                    sensor.recvfrom(512)
                except socket.timeout:
                    break
            before_loss_step = core.wait_running()
            try:
                sensor.recvfrom(512)
                raise RuntimeError("packet_loss_ratio=1 still emitted a sensor datagram")
            except socket.timeout:
                pass
            if core.wait_running() <= before_loss_step:
                raise RuntimeError("truth model stopped while sensor packets were dropped")

            # E3: command delay is a real queue in generated dynamics.  The
            # same flight command has no early model effect, then produces a
            # later physical state response.
            delayed = group_values(contract, "fault", altered=False)
            delayed["command_delay_ms"] = 120.0
            core.stage("fault", delayed)
            baseline = state_score(core.status(), model_id == "fixed_wing_hil")
            high_flight = group_values(contract, "flight_control", altered=True)
            core.stage("flight_control", high_flight)
            time.sleep(.035)
            early = state_score(core.status(), model_id == "fixed_wing_hil")
            time.sleep(.20)
            late = state_score(core.status(), model_id == "fixed_wing_hil")
            if abs(early - baseline) > .02 or abs(late - baseline) < .05:
                raise RuntimeError("generated command-delay queue showed no later model response: baseline=%s early=%s late=%s" % (baseline, early, late))

            return {
                "model_id": model_id, "message_ids": {"flight": flight_id, "fault": fault_id,
                                                          "parameters": parameter_id, "environment": 10},
                "bindings_applied": sum(len(payload) for payload in values.values()),
                "group_revisions": {name: result["fields"]["model_revision"] for name, result in applied.items()},
                "sensor_truth": {"sensor_step": sensor_step, "truth_north_m": truth,
                                  "sensor_north_m": sensor_north_value, "loss_status_step": before_loss_step},
                "delay_response": {"baseline": baseline, "early": early, "late": late},
                "unknown_field_rejected": rejected["reason"],
                "records": core.records,
                "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            }
        finally:
            sensor.close()
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    fixture = load_fixtures()
    results = [run_one(index, model, fixture) for index, model in enumerate(MODELS)]
    output = args.output or ROOT / "artifacts/linux_target" / (
        "l004-three-model-boundary-%s.json" % time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"format": "HIL_L004_MODEL_BOUNDARY_EVIDENCE_2", "status": "LINUX_TARGET_VERIFIED",
              "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "execution_host": "Linux %s (%s)" % (platform.release(), platform.machine()),
              "completed_linux_items": ["L-004"],
              "verification": "Three real generated ERT executables: complete target-step C getter readback, reset, sensor/truth split, packet loss, delayed command response and unknown-field rejection.",
              "qualification": "Linux development mode only (HIL_ALLOW_NONRT=1); no RT or physical-bus claim",
              "models": results}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
