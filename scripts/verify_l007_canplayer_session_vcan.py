#!/usr/bin/env python3
"""L-007：canplayer 经当前 SourceSession 回放到 vcan 的软件闭环验证。

本脚本使用本机 SocketCAN ``can2`` 和临时 loopback UDP 开启会话。它验证：
捕获解码、重新分配当前 SID、canplayer 子进程、CANGateway 接收和标准反馈。
结果不代表实体 CAN 设备、模型消费者或现场发送资格。
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import can


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.can_ingress import CANGateway
from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame, Header, WireCodec
from input_simulator.history import CaptureBinding
from input_simulator.replay import ReplayDestination, ReplayHeader, ReplayProcessor
from input_simulator.replay_export import ExportBinding
from input_simulator.replay_process import ReplayProcessAuthority, ReplayProcessRun
from input_simulator.session import SourceSession
from input_simulator.tool_commands import ToolCommandBuilder
from input_simulator.tools import ChannelReservations
from input_simulator.udp_source import UDPSource
from scripts.verify_l004_model_boundary import Core as CcoreClient
from scripts.verify_l004_model_boundary import configuration as ccore_configuration
from scripts.verify_l004_model_boundary import configure_and_start
from icd_gateway.model_bindings import ModelBindings
from icd_gateway.model_consumer import EnvironmentModelConsumerService, QuadrotorEnvironmentBridge


BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"


def fixture(directory: Path, message_id: int) -> dict:
    rows = json.loads((directory / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]
    for row in rows:
        value = row["value"]
        if value.get("message_id") == message_id:
            return value
    raise ICDError("RESOURCE", f"缺少消息 {message_id} 的冻结示例")


def can_log(wire: WireCodec, original: dict) -> bytes:
    """用一个已捕获的旧会话消息构造严格 CAN_LOG，不作为可发送输入。"""
    frames = wire.encode(original, "CANFD")
    return b"".join(
        f"(1.{index * 1000:09d}) can2 {frame.arbitration_id:03X}##5{frame.data.hex()} T\n".encode("ascii")
        for index, frame in enumerate(frames)
    )


def history(raw: bytes, frame_count: int, directory: Path) -> tuple[dict, dict]:
    source = json.loads((directory / "input-simulator-v0.3.examples.json").read_bytes())["source_inputs"]
    source["history"] = {
        "source_type": "HISTORY", "history_id": "l007-current-session-can-log",
        "resource": {"resource_id": "l007-can-log", "sha256": hashlib.sha256(raw).hexdigest(),
                     "size_bytes": len(raw), "format": "CAN_LOG", "encoding": "UTF8",
                     "media_type": "text/plain", "file_name": "CANFD_0.log"},
        "streams": [{"stream_id": "environment", "direction": "TO_36", "original_channel": "CANFD",
                     "message_ids": [10], "records": 1, "clock": "CAPTURE_MONOTONIC", "epoch_ns": "1000000000",
                     "uncertainty_us": 0, "truncated_packets": 0, "lost_packets": 0}],
        "policy": {"mode": "REENCODE", "start_offset_ns": "0",
                   "end_offset_ns": str((frame_count - 1) * 1000), "rate": "1X",
                   "execution_mode": "ONLINE", "repeat_count": 1, "repeat_gap_steps": 100,
                   "session_policy": "NEW_SESSION_PER_REPEAT", "rewrite_fields": [],
                   "filter_direction": "TO_36_ONLY", "seek_policy": "OFFLINE_ONLY",
                   "restore_policy": "RESET_MODEL_AND_CLEAR_QUEUES",
                   "incomplete_capture_policy": "REJECT_ONLINE", "feedback_policy": "COLLECT_NOT_INJECT"},
        "integrity_verified": True, "decoder_baseline_sha256": BASELINE_SHA256,
    }
    resources = {ref["resource_id"]: (directory / ref["file_name"]).read_bytes()
                 for ref in source["protocol"]["resources"]}
    resources["l007-can-log"] = raw
    return source["history"], resources


class CurrentSessionAuthority(ReplayProcessAuthority):
    """把唯一的 canplayer 启动绑定到已打开的会话和已分配的 CAN 输入。"""

    def __init__(self, session: SourceSession, item, gateway: CANGateway):
        super().__init__(session)
        self.item, self.gateway, self.claimed = item, gateway, False

    def preflight(self, prepared, plan):
        if self.gateway._closed or self.gateway.bus._is_shutdown:
            raise ICDError("STATE", "CAN 网关在重放启动前不可用")
        self.session.verify_input(self.item)

    def check(self, prepared, plan, *, channel_id=None):
        if self.gateway._closed or self.gateway.bus._is_shutdown:
            raise ICDError("STATE", "CAN 网关在重放期间已关闭")
        self.session.verify_input(self.item)
        if channel_id is not None and not self.claimed:
            with self.session._operation():
                self.session._verify_input(self.item)
                self.session._claim_can_attempt(self.item)
            self.claimed = True


def gateway_worker(gateway: UDPGateway, stop: threading.Event, errors: list[Exception]) -> None:
    while not stop.is_set():
        try:
            gateway.poll(timeout=0.01)
        except Exception as error:  # 线程错误由主流程变成失败证据。
            errors.append(error)
            return


def can_worker(gateway: CANGateway, stop: threading.Event, errors: list[Exception]) -> None:
    while not stop.is_set():
        try:
            gateway.poll(timeout=0.01)
        except Exception as error:
            errors.append(error)
            return


def feedback(observer, contract: Contract, *, timeout: float) -> list[dict]:
    assembler, replies = Reassembler(contract), []
    deadline = time.monotonic() + timeout
    while len(replies) < 2 and time.monotonic() < deadline:
        frame = observer.recv(timeout=0.02)
        if frame is None:
            continue
        if frame.is_fd is not True or frame.bitrate_switch is not True:
            continue
        fragment = WireCodec(contract).decode(CANFrame(frame.arbitration_id, bytes(frame.data), frame.is_fd,
            frame.bitrate_switch, frame.is_extended_id, frame.is_remote_frame), "CANFD")
        # 同一 vcan 观察者也会看到 canplayer 的 TO_36 帧；它们不是反馈。
        if fragment.direction != "FROM_36":
            continue
        result = assembler.push(fragment, channel="CANFD_0", direction="FROM_36", authorized=True,
                                now_ns=time.monotonic_ns())
        if result is not None:
            replies.append(result.message)
    if len(replies) != 2:
        raise ICDError("TIMEOUT", "未在 vcan 上收到两条标准重放反馈")
    return replies


def _free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


class LocalCcore:
    """仅启动本仓库的生成 C 模型，并通过其原 UDP 管理边界完成配置。"""

    def __init__(self, executable: Path, model_contract: Path, fixture_configuration: dict, output: Path):
        self.executable, self.model_contract = executable, model_contract
        self.fixture_configuration, self.output = fixture_configuration, output
        self.command_port, self.status_port, self.sensor_port, self.v3_port = (_free_udp_port() for _ in range(4))
        self.process = None
        self.client = CcoreClient(("127.0.0.1", self.command_port))

    def start(self) -> None:
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise ICDError("TARGET_MISSING", "本地生成 C 模型可执行文件不可用")
        if not self.model_contract.is_file():
            raise ICDError("TARGET_MISSING", "本地生成 C 模型契约不可用")
        environment = dict(os.environ, HIL_ALLOW_NONRT="1", HIL_UDP_CMD_PORT=str(self.command_port),
                           HIL_UDP_STATUS_PORT=str(self.status_port), HIL_UDP_SENSOR_PORT=str(self.sensor_port),
                           HIL_V3_TCP_PORT=str(self.v3_port))
        log = (self.output / "ccore-runtime.log").open("xb")
        try:
            self.process = subprocess.Popen((str(self.executable),), cwd=str(ROOT), env=environment,
                                            stdout=log, stderr=subprocess.STDOUT)
        finally:
            log.close()
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    if self.client.status().get("accepted"):
                        break
                except OSError:
                    time.sleep(0.01)
            else:
                raise ICDError("TARGET_MISSING", "本地 C 模型没有建立原管理边界")
            contract = json.loads(self.model_contract.read_text(encoding="utf-8"))
            configure_and_start(self.client, ccore_configuration("quadrotor_hil", contract, self.fixture_configuration))
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


class RecordingEnvironmentBridge(QuadrotorEnvironmentBridge):
    """为本次证据保留 C 边界原始收据，不改变桥接判定。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exchanges = []

    def _exchange(self, command):
        reply = super()._exchange(command)
        self.exchanges.append({"command": command, "reply": reply})
        return reply


def run(contract_dir: Path, output: Path, interface: str, executable: Path, *,
        model_executable: Path | None = None, model_contract: Path | None = None) -> dict:
    contract = Contract.load(contract_dir, expected_sha256=BASELINE_SHA256)
    identity = fixture(contract_dir, 1)["payload"]["identity"]
    original = fixture(contract_dir, 10)
    model_application = model_executable is not None
    if model_application != (model_contract is not None):
        raise ICDError("SCHEMA", "C 模型可执行文件与模型契约必须同时指定")
    wire = WireCodec(contract)
    raw = can_log(wire, original)
    historical, resources = history(raw, len(wire.encode(original, "CANFD")), contract_dir)
    output.mkdir(parents=True, exist_ok=False)
    export_directory = output / "replay_export"
    # SourceSession 的 UDP 入口要求冻结的非零目标端口；该 loopback 端口仅
    # 用于本次开会话，不参与随后的 CAN 重放。
    udp_endpoint = ("127.0.0.1", 37600)
    source = UDPSource(contract, source_bind=("127.0.0.1", 0), feedback_bind=("127.0.0.1", 0),
                       receiver_endpoint=udp_endpoint, channel="ETH_0")
    udp_binding = PeerBinding("ETH_0", "UDP", f"{source.source_endpoint[0]}:{source.source_endpoint[1]}")
    can_binding = PeerBinding("CANFD_0", "CANFD", interface)
    registry = SessionRegistry(contract, (SourceGrant(identity, ("STIMULUS",), (udp_binding, can_binding)),))
    ccore, consumer = None, None
    if model_application:
        ccore = LocalCcore(model_executable.resolve(strict=True), model_contract.resolve(strict=True),
                           fixture(contract_dir, 3), output)
        ccore.start()
        bindings = ModelBindings(contract, "quadrotor_hil", json.loads(model_contract.read_text(encoding="utf-8")))
        bridge = RecordingEnvironmentBridge(("127.0.0.1", ccore.command_port))
        consumer = EnvironmentModelConsumerService(contract, registry, bindings, bridge, clock=time.monotonic_ns)
        service = None
        receiver = Receiver(contract, registry, model_consumer_service=consumer)
    else:
        service = ReceptionService(contract, registry, (10,))
        receiver = Receiver(contract, registry, reception_service=service)
    udp_gateway = UDPGateway(receiver, bind=udp_endpoint,
                             feedback_routes={udp_binding: source.feedback_endpoint}, channel="ETH_0")
    udp_stop, can_stop = threading.Event(), threading.Event()
    udp_errors, can_errors = [], []
    udp_thread = threading.Thread(target=gateway_worker, args=(udp_gateway, udp_stop, udp_errors), daemon=True)
    can_bus = can.Bus(interface="socketcan", channel=interface, fd=True, receive_own_messages=False,
                      ignore_config=True)
    observer = can.Bus(interface="socketcan", channel=interface, fd=True, receive_own_messages=False,
                       ignore_config=True)
    can_gateway = CANGateway(receiver, channel="CANFD_0", interface=interface, bus=can_bus)
    can_thread = threading.Thread(target=can_worker, args=(can_gateway, can_stop, can_errors), daemon=True)
    book = ChannelReservations()
    replay = None
    try:
        udp_thread.start()
        session = SourceSession(source, identity, ("STIMULUS",), max_records=64)
        opened = session.open()
        if udp_errors:
            raise udp_errors[0]
        # 会话已经建立；停掉 UDP 轮询，避免无关 UDP tick 与 CAN 接收并发。
        udp_stop.set()
        udp_thread.join(timeout=1)
        udp_gateway.socket.close()
        udp_gateway._closed = True
        target_step = 80
        if model_application:
            # C 目标以 1 ms 步推进。ID10 的 240 ms 有效期同时是可用前视
            # 窗口；此处保留其完整窗口给导出与原工具启动，C 边界仍会拒绝
            # 已经过期或超过 1000 步前视的请求。
            target_step = consumer.backend.current_step() + 240
        item = session.prepare_input({"message_id": 10, "payload": original["payload"]}, "CANFD", target_step=target_step)
        current = Header(**item.message["header"])
        prepared = ReplayProcessor(contract).prepare(
            raw, historical, (CaptureBinding("environment", "CANFD_0", "CAN_LOG:can2", "can2", "clock-0"),),
            model_id=identity["model_id"], declared_ids=(10,), headers=(ReplayHeader(0, current),),
            destinations=(ReplayDestination("CANFD_0", "CANFD_0"),))
        reservation = book.reserve("l007-current-session", "CANREPLAY", (interface,), mode="SEND")
        plan = ToolCommandBuilder(contract, book).replay(
            reservation, prepared, (ExportBinding("CANFD_0", interface),), directory=export_directory)
        authority = CurrentSessionAuthority(session, item, can_gateway)
        can_thread.start()
        replay = ReplayProcessRun(contract, prepared, plan, (ExportBinding("CANFD_0", interface),), book, reservation,
                                  authority=authority, executables={"canplayer": executable.resolve(strict=True)},
                                  start_lateness_ns=100_000_000, timeout_ms=10_000)
        replay.start()
        deadline = time.monotonic() + 3
        while replay.snapshot.state == "RUNNING" and time.monotonic() < deadline:
            time.sleep(0.01)
            replay.poll()
        if replay.snapshot.state != "LOCAL_EXITED":
            raise ICDError("STATE", f"canplayer 未正常本地退出：{replay.snapshot.state}")
        replies = feedback(observer, contract, timeout=2)
        if can_errors:
            raise can_errors[0]
        terminal_records = consumer.records if model_application else service.records
        if len(terminal_records) != 1:
            raise ICDError("STATE", "CAN 网关未保留当前会话的完整标准接收记录：%s %s" %
                           (dict(receiver.errors), list(receiver.error_details) if not model_application else
                            list(receiver.error_details) + [bridge.exchanges]))
        if not model_application and loads(service.records[0].message_json) != item.message:
            raise ICDError("STATE", "CAN 网关接收记录的当前会话消息不一致")
        stages = [reply["payload"]["stage"] for reply in replies]
        expected_stages = ["RECEIVED", "APPLIED"] if model_application else ["RECEIVED", "VALIDATED"]
        if stages != expected_stages:
            raise ICDError("STATE", "CAN 反馈阶段与接收/模型应用边界不一致")
        return {"format": "HIL_L007_CANPLAYER_SESSION_VCAN_1", "status": "SOFTWARE_CLOSED_LOOP_VALIDATED",
                "interface": interface, "session_id": session.session_id, "source_capture_sha256": hashlib.sha256(raw).hexdigest(),
                "export_sha256": plan.export.files[0].sha256, "current_header": asdict(current),
                "received_records": len(terminal_records), "feedback_stages": stages,
                "process_records": [{"kind": record.kind, "at_ns": record.at_ns,
                                     "scheduled_ns": record.scheduled_ns, "error": record.error}
                                    for record in replay.records],
                "physical_hardware_qualified": False, "model_consumer_verified": model_application,
                "model_application": None if not model_application else {
                    "applied_step": consumer.records[0].applied_step,
                    "model_revision": consumer.records[0].model_revision,
                    "readback": loads(consumer.records[0].readback_json),
                    "ccore_exchanges": bridge.exchanges,
                    "ccore_binary_sha256": hashlib.sha256(model_executable.read_bytes()).hexdigest(),
                    "ccore_contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest()}}
    finally:
        if replay is not None:
            replay.close()
        can_stop.set()
        if can_thread.is_alive():
            can_thread.join(timeout=1)
        can_gateway.close()
        observer.shutdown()
        book.release(reservation) if "reservation" in locals() else None
        source.close()
        receiver.close()
        if ccore is not None:
            ccore.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="必须不存在的本次证据目录")
    parser.add_argument("--interface", default="can2")
    parser.add_argument("--contract-dir", type=Path, default=ROOT / "docs/interfaces/baseline")
    parser.add_argument("--canplayer", type=Path, default=ROOT / "tools/can-utils/current/canplayer")
    parser.add_argument("--model-executable", type=Path,
                        help="可选：本仓库 quadrotor_hil_rt，启用真实 C 模型 APPLIED 验证")
    parser.add_argument("--model-contract", type=Path,
                        help="--model-executable 对应的 hil_contract.json")
    args = parser.parse_args()
    try:
        result = run(args.contract_dir, args.output.resolve(), args.interface, args.canplayer,
                     model_executable=args.model_executable, model_contract=args.model_contract)
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
