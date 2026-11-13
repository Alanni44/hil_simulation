#!/usr/bin/env python3
"""L-006：当前 SourceSession 经 SavvyCAN 发送到本地 C 模型的验证。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

import can


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.can_ingress import CANGateway
from icd_gateway.model_bindings import ModelBindings
from icd_gateway.model_consumer import EnvironmentModelConsumerService
from icd_gateway.receiver import Receiver
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from input_simulator.live_tool_input import LiveToolInputBuilder
from input_simulator.protocol import ProtocolParser
from input_simulator.replay_export import ExportBinding
from input_simulator.savvycan_process import SavvyCanProcessRun
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations
from input_simulator.udp_source import UDPSource
from scripts.verify_l007_canplayer_session_vcan import (
    BASELINE_SHA256, LocalCcore, RecordingEnvironmentBridge, _free_udp_port,
    can_worker, feedback, fixture, gateway_worker,
)


def _resources(contract_dir: Path) -> tuple[dict, dict]:
    source = json.loads((ROOT / "config/generated-input-reception.json").read_text(encoding="utf-8"))["source_inputs"]
    resources = {}
    root = contract_dir.resolve()
    for reference in source["protocol"]["resources"]:
        path = (root / reference["file_name"]).resolve(strict=True)
        if path.parent != root:
            raise ICDError("RESOURCE", "冻结协议资源路径越界")
        resources[reference["resource_id"]] = path.read_bytes()
    return source, resources


def run(contract_dir: Path, output: Path, interface: str, savvycan: Path,
        model_executable: Path, model_contract: Path) -> dict:
    contract = Contract.load(contract_dir, expected_sha256=BASELINE_SHA256)
    identity = fixture(contract_dir, 1)["payload"]["identity"]
    stimulus = fixture(contract_dir, 10)
    inputs, resources = _resources(contract_dir)
    parser = ProtocolParser(contract)
    parser.parse(inputs["protocol"], resources)
    output.mkdir(parents=True, exist_ok=False)
    ccore = LocalCcore(model_executable.resolve(strict=True), model_contract.resolve(strict=True),
                       fixture(contract_dir, 3), output)
    source = UDPSource(contract, source_bind=("127.0.0.1", 0), feedback_bind=("127.0.0.1", 0),
                       receiver_endpoint=("127.0.0.1", _free_udp_port()), channel="ETH_0")
    udp_binding = PeerBinding("ETH_0", "UDP", "%s:%d" % source.source_endpoint)
    can_binding = PeerBinding("CANFD_0", "CANFD", interface)
    registry = SessionRegistry(contract, (SourceGrant(identity, ("STIMULUS",), (udp_binding, can_binding)),))
    udp_gateway = None
    receiver = None
    can_gateway = None
    observer = None
    runner = None
    reservation = None
    udp_stop, can_stop = threading.Event(), threading.Event()
    udp_errors, can_errors = [], []
    udp_thread = can_thread = None
    try:
        ccore.start()
        bindings = ModelBindings(contract, "quadrotor_hil", json.loads(model_contract.read_text(encoding="utf-8")))
        bridge = RecordingEnvironmentBridge(("127.0.0.1", ccore.command_port))
        consumer = EnvironmentModelConsumerService(contract, registry, bindings, bridge, clock=time.monotonic_ns)
        receiver = Receiver(contract, registry, model_consumer_service=consumer)
        udp_gateway = UDPGateway(receiver, bind=source.receiver_endpoint,
                                 feedback_routes={udp_binding: source.feedback_endpoint}, channel="ETH_0")
        udp_thread = threading.Thread(target=gateway_worker, args=(udp_gateway, udp_stop, udp_errors), daemon=True)
        udp_thread.start()
        session = SourceSession(source, identity, ("STIMULUS",), max_records=64)
        session.open()
        if udp_errors:
            raise udp_errors[0]
        udp_stop.set()
        udp_thread.join(timeout=1)
        # 会话仅经 UDP 开立；后续由 CAN 网关复用同一 Receiver。不能调用
        # UDPGateway.close()，它会连带关闭共享 Receiver，导致 CAN 帧不再
        # 进入模型应用链。
        udp_gateway.socket.close()
        udp_gateway._closed = True
        # 与 L-007 相同，ID10 的 240 步前视窗口覆盖本机 SavvyCAN 的
        # SocketCAN 启动延迟，同时确保 C 模型能在应用等待窗口内到达边界。
        target_step = consumer.backend.current_step() + 240
        book = ChannelReservations()
        reservation = book.reserve("l006-savvy-current-session", "SAVVY", (interface,), mode="SEND")
        builder = LiveToolInputBuilder(book, session, protocol=parser)
        plan = builder.prepare(
            reservation, {"message_id": 10, "payload": stimulus["payload"]},
            ExportBinding("CANFD_0", interface), target_step=target_step)
        can_bus = can.Bus(interface="socketcan", channel=interface, fd=True, receive_own_messages=False,
                          ignore_config=True)
        observer = can.Bus(interface="socketcan", channel=interface, fd=True, receive_own_messages=False,
                           ignore_config=True)
        can_gateway = CANGateway(receiver, channel="CANFD_0", interface=interface, bus=can_bus)
        can_thread = threading.Thread(target=can_worker, args=(can_gateway, can_stop, can_errors), daemon=True)
        can_thread.start()
        runner = SavvyCanProcessRun(builder, plan,
                                    executable=savvycan.resolve(strict=True), directory=output)
        runner.start()
        deadline = time.monotonic() + 3
        while runner.snapshot.state == "RUNNING" and time.monotonic() < deadline:
            time.sleep(0.01)
            runner.poll()
        if runner.snapshot.state != "LOCAL_EXITED":
            raise ICDError("STATE", "SavvyCAN 未正常完成受控发送：%s" % runner.snapshot.state)
        try:
            replies = feedback(observer, contract, timeout=2)
        except ICDError as error:
            raise ICDError(error.code, "%s; receiver_errors=%s details=%s" %
                           (error.detail, dict(receiver.errors), list(receiver.error_details))) from error
        if can_errors:
            raise can_errors[0]
        stages = [reply["payload"]["stage"] for reply in replies]
        if len(consumer.records) != 1:
            raise ICDError("STATE", "SavvyCAN CAN 输入未得到唯一模型应用记录: stages=%s errors=%s details=%s exchanges=%s" %
                           (stages, dict(receiver.errors), list(receiver.error_details), bridge.exchanges))
        if stages != ["RECEIVED", "APPLIED"]:
            raise ICDError("STATE", "SavvyCAN 标准反馈未到达 RECEIVED→APPLIED")
        snapshot = runner.snapshot
        return {
            "format": "HIL_L006_SAVVYCAN_AUTHORIZED_CLOSED_LOOP_1",
            "status": "SOFTWARE_SAVVYCAN_AUTHORIZED_SEND_APPLIED",
            "interface": interface,
            "session_id": session.session_id,
            "current_header": loads(plan.source_input.message_json)["header"],
            "savvycan": {
                "executable_sha256": hashlib.sha256(savvycan.read_bytes()).hexdigest(),
                "request_path": snapshot.request_path,
                "request_sha256": snapshot.request_sha256,
                "process": None if snapshot.process is None else {
                    "state": snapshot.process.state,
                    "returncode": snapshot.process.returncode,
                    "stdout": snapshot.process.stdout.decode("utf-8", "replace"),
                    "stderr": snapshot.process.stderr.decode("utf-8", "replace"),
                },
            },
            "feedback_stages": stages,
            "model_application": {
                "applied_step": consumer.records[0].applied_step,
                "model_revision": consumer.records[0].model_revision,
                "readback": loads(consumer.records[0].readback_json),
                "ccore_exchanges": bridge.exchanges,
                "ccore_binary_sha256": hashlib.sha256(model_executable.read_bytes()).hexdigest(),
                "ccore_contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest(),
            },
            "physical_hardware_qualified": False,
            "limits": ["Linux vcan software verification only; no physical CAN-FD qualification."],
        }
    finally:
        if runner is not None:
            runner.close()
        can_stop.set()
        if can_thread is not None and can_thread.is_alive():
            can_thread.join(timeout=1)
        if can_gateway is not None:
            can_gateway.close()
        if observer is not None:
            observer.shutdown()
        if reservation is not None:
            book.release(reservation)
        source.close()
        if receiver is not None:
            receiver.close()
        ccore.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interface", default="can2")
    parser.add_argument("--contract-dir", type=Path, default=ROOT / "docs/interfaces/baseline")
    parser.add_argument("--savvycan", type=Path,
                        default=ROOT / "tools/SavvyCAN/V220-socketcan/SavvyCAN-hil-authorized")
    parser.add_argument("--model-executable", type=Path,
                        default=ROOT / "artifacts/linux_target/l010-step-candidate-20261112T100000Z/bin/quadrotor_hil_rt")
    parser.add_argument("--model-contract", type=Path, default=ROOT / "artifacts/z_mission/model/hil_contract.json")
    args = parser.parse_args()
    try:
        result = run(args.contract_dir, args.output.resolve(), args.interface, args.savvycan,
                     args.model_executable, args.model_contract)
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError, can.CanError) as error:
        result = {"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                  "detail": str(error)}
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
