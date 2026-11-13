#!/usr/bin/env python3
"""L-013：在真实生成 C 模型上采集实时与并发负载证据。

脚本只以 C 核心退出时输出的 ``realtime`` 统计判定 1ms 调度；不会把
Python 的 sleep、vcan 或管理回执时间当作实时证据。它同时记录 C 核心每
20ms 发布的状态包，并按四个连续模型发布周期形成一个可追溯的 80ms 观测
窗口。后者不是尚未部署的 3.6 Status 服务的替代品，报告会明确标记这一
边界。

默认不设置 HIL_ALLOW_NONRT。因而在没有 SCHED_FIFO/锁内存权限的机器上，
真实验证会拒绝启动并留下失败证据。``--allow-nonrt`` 仅用于验证采集器本身，
永远不能返回 L-013 合格状态。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_l004_model_boundary import Core, configuration, configure_and_start, load_fixtures


STEP_NS = 1_000_000
STATUS_GROUP_NS = 80_000_000
RT_LINE = re.compile(
    r"\[HIL\] realtime samples=(?P<samples>\d+) "
    r"p99_abs_lateness_ns=(?P<p99>-?\d+) "
    r"max_abs_lateness_ns=(?P<maximum>-?\d+) "
    r"over_250us=(?P<over_250us>\d+) non_realtime=(?P<non_realtime>[01])"
)


def free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) * ratio + .999999) - 1)))]


def process_snapshot(pid: int) -> dict[str, int] | None:
    """读取实际模型进程的 RSS 与 CPU tick，不从 Python 估算。"""
    try:
        status = (Path("/proc") / str(pid) / "status").read_text(encoding="utf-8")
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8").split()
    except OSError:
        return None
    rss_kib = 0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            rss_kib = int(line.split()[1])
            break
    # /proc/<pid>/stat 的 utime、stime 是第 14、15 个字段，split 后为 13、14。
    return {"rss_kib": rss_kib, "cpu_ticks": int(stat[13]) + int(stat[14])}


class StatusTraffic:
    """在 C 的原 UDP 管理边界持续读状态，制造受控并发管理负载。"""

    def __init__(self, endpoint: tuple[str, int], interval_s: float = .02):
        self.endpoint, self.interval_s = endpoint, interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples_ns: list[int] = []
        self.failures: list[str] = []

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="l013-status-traffic", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        client = Core(self.endpoint)
        next_deadline = time.monotonic_ns()
        while not self._stop.is_set():
            next_deadline += 20_000_000
            started = time.monotonic_ns()
            try:
                reply = client.status()
                if not reply.get("accepted"):
                    raise RuntimeError("C core rejected status request")
                self.samples_ns.append(time.monotonic_ns() - started)
            except (OSError, TimeoutError, ValueError, RuntimeError) as error:
                self.failures.append(str(error))
            delay_ns = next_deadline - time.monotonic_ns()
            if delay_ns > 0 and self._stop.wait(delay_ns / 1_000_000_000):
                break

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def taskset_command(cpus: tuple[int, ...], command: tuple[str, ...]) -> tuple[str, ...]:
    if not cpus:
        return command
    taskset = shutil.which("taskset")
    if taskset is None:
        raise RuntimeError("taskset is required for requested CPU affinity")
    return (taskset, "--cpu-list", ",".join(str(cpu) for cpu in cpus), *command)


def start_cpu_load(worker_count: int, cpus: tuple[int, ...]) -> list[subprocess.Popen[bytes]]:
    """启动有限 CPU 竞争负载；模型进程与负载进程均保留真实 PID。"""
    code = "import hashlib\nwhile True: hashlib.sha256(b'l013-load' * 4096).digest()\n"
    processes: list[subprocess.Popen[bytes]] = []
    for index in range(worker_count):
        assigned = (cpus[index % len(cpus)],) if cpus else ()
        processes.append(subprocess.Popen(taskset_command(assigned, (sys.executable, "-c", code)),
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return processes


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def parse_rt_stats(log_path: Path) -> dict[str, int] | None:
    matches = list(RT_LINE.finditer(log_path.read_text(encoding="utf-8", errors="replace")))
    if not matches:
        return None
    return {key: int(value) for key, value in matches[-1].groupdict().items()}


def recover_interrupted_run(output: Path, log_path: Path, executable: Path,
                            model_contract: Path) -> dict[str, Any]:
    """把已正常终止的 C 原始日志封存为不合格的中断证据。

    只能恢复 C 自己已经写出的实时统计；没有采集到的 80ms、UDP 和资源数据
    必须保持未验证，不能由日志行推测出来。
    """
    stats = parse_rt_stats(log_path.resolve(strict=True))
    return {
        "format": "HIL_L013_RT_LOAD_1",
        "status": "NOT_QUALIFIED",
        "execution_scope": "INTERRUPTED_TARGET_GENERATED_CCORE_RUN",
        "reason": "collector process ended before it wrote complete evidence",
        "model": {"executable": str(executable.resolve(strict=True)),
                  "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest()},
        "realtime": stats,
        "not_verified": [
            "80MS_CYCLE_OBSERVATION", "MANAGEMENT_UDP_LOAD", "RESOURCE_USAGE",
            "LONG_STABILITY_COMPLETE_EVIDENCE", "3.6_STATUS_SERVICE_80MS_PUBLICATION",
            "PHYSICAL_CAN_OR_ETHERNET_THROUGHPUT",
        ],
    }


def receive_statuses(peer: socket.socket, deadline_ns: int) -> tuple[list[int], list[int]]:
    """以实际数据包到达时间和其模型 sequence 收集 C 的周期输出。"""
    arrivals: list[int] = []
    sequences: list[int] = []
    peer.settimeout(.05)
    while time.monotonic_ns() < deadline_ns:
        try:
            raw, _ = peer.recvfrom(4096)
        except socket.timeout:
            continue
        # 所用 quadrotor 状态 ABI 的 sequence 为 little-endian uint64，偏移 4。
        if len(raw) >= 12:
            arrivals.append(time.monotonic_ns())
            sequences.append(int.from_bytes(raw[4:12], "little"))
    return arrivals, sequences


def grouped_cycle(arrivals: list[int], sequences: list[int]) -> dict[str, Any]:
    intervals = [arrivals[index] - arrivals[index - 4] for index in range(4, len(arrivals))]
    sequence_steps = [sequences[index] - sequences[index - 4] for index in range(4, len(sequences))]
    errors = [abs(value - STATUS_GROUP_NS) for value in intervals]
    return {
        "source": "C_CORE_20MS_STATUS_PACKET_GROUP_OF_FOUR",
        "not_a_replacement_for": "3.6_STATUS_SERVICE_80MS_PUBLICATION",
        "samples": len(intervals),
        "period_ns_p99": percentile(intervals, .99),
        "period_ns_max": max(intervals, default=0),
        "absolute_error_ns_p99": percentile(errors, .99),
        "absolute_error_ns_max": max(errors, default=0),
        "model_step_delta_min": min(sequence_steps, default=0),
        "model_step_delta_max": max(sequence_steps, default=0),
        "within_plus_minus_1ms": bool(intervals) and max(errors) <= 1_000_000 and all(
            value == 80 for value in sequence_steps),
    }


def run(output: Path, executable: Path, model_contract: Path, *, duration_s: float,
        load_workers: int, allow_nonrt: bool, model_cpu: int | None,
        load_cpus: tuple[int, ...]) -> dict[str, Any]:
    if duration_s <= 0:
        raise ValueError("duration must be positive")
    if load_workers < 0:
        raise ValueError("load worker count must not be negative")
    allowed_cpus = os.sched_getaffinity(0)
    selected_cpus = (() if model_cpu is None else (model_cpu,)) + load_cpus
    if any(cpu not in allowed_cpus for cpu in selected_cpus):
        raise ValueError("requested CPU is outside this process affinity set")
    if model_cpu is not None and model_cpu in load_cpus:
        raise ValueError("model CPU must not also run the load workers")
    if load_workers and model_cpu is not None and not load_cpus:
        raise ValueError("CPU-isolated load requires --load-cpus")
    executable, model_contract = executable.resolve(strict=True), model_contract.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    command_port, status_port, sensor_port, v3_port = (free_udp_port() for _ in range(4))
    environment = dict(os.environ, HIL_UDP_CMD_PORT=str(command_port),
                       HIL_UDP_STATUS_PORT=str(status_port), HIL_UDP_SENSOR_PORT=str(sensor_port),
                       HIL_V3_TCP_PORT=str(v3_port))
    if allow_nonrt:
        environment["HIL_ALLOW_NONRT"] = "1"
    else:
        environment.pop("HIL_ALLOW_NONRT", None)
    log_path = output / "ccore-runtime.log"
    status_peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    status_peer.bind(("127.0.0.1", status_port))
    process: subprocess.Popen[bytes] | None = None
    load_processes: list[subprocess.Popen[bytes]] = []
    traffic: StatusTraffic | None = None
    before: dict[str, int] | None = None
    after: dict[str, int] | None = None
    try:
        with log_path.open("xb") as log:
            model_cpus = () if model_cpu is None else (model_cpu,)
            process = subprocess.Popen(taskset_command(model_cpus, (str(executable),)), cwd=str(ROOT), env=environment,
                                       stdout=log, stderr=subprocess.STDOUT)
        client = Core(("127.0.0.1", command_port))
        startup_deadline = time.monotonic() + 2
        while time.monotonic() < startup_deadline:
            if process.poll() is not None:
                break
            try:
                if client.status().get("accepted"):
                    break
            except (OSError, TimeoutError):
                time.sleep(.01)
        else:
            raise RuntimeError("C model did not establish the UDP management boundary")
        if process.poll() is not None:
            raise RuntimeError("C model refused startup: " + log_path.read_text(encoding="utf-8", errors="replace"))
        contract = json.loads(model_contract.read_text(encoding="utf-8"))
        configure_and_start(client, configuration("quadrotor_hil", contract, load_fixtures()[3]))
        before = process_snapshot(process.pid)
        load_processes = start_cpu_load(load_workers, load_cpus)
        traffic = StatusTraffic(("127.0.0.1", command_port))
        traffic.start()
        started_ns = time.monotonic_ns()
        arrivals, sequences = receive_statuses(status_peer, started_ns + int(duration_s * 1_000_000_000))
        after = process_snapshot(process.pid)
    finally:
        if traffic is not None:
            traffic.close()
        stop_processes(load_processes)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        status_peer.close()
    stats = parse_rt_stats(log_path)
    cycle = grouped_cycle(arrivals, sequences)
    traffic_summary = {
        "samples": len(traffic.samples_ns) if traffic else 0,
        "p99_ns": percentile(traffic.samples_ns, .99) if traffic else 0,
        "max_ns": max(traffic.samples_ns, default=0) if traffic else 0,
        "failures": traffic.failures if traffic else [],
    }
    resource_usage = {"before": before, "after": after}
    if before and after:
        resource_usage["cpu_ticks_delta"] = after["cpu_ticks"] - before["cpu_ticks"]
        resource_usage["rss_kib_max_observed"] = max(before["rss_kib"], after["rss_kib"])
    realtime_pass = bool(stats and stats["non_realtime"] == 0 and stats["samples"] >= int(duration_s * 1000)
                         and stats["maximum"] <= 10_000 and cycle["within_plus_minus_1ms"])
    return {
        "format": "HIL_L013_RT_LOAD_1",
        "status": "TARGET_RT_LOAD_VALIDATED" if realtime_pass else "NOT_QUALIFIED",
        "execution_scope": "TARGET_GENERATED_CCORE_CONCURRENT_CPU_AND_UDP_LOAD",
        "model": {"executable": str(executable),
                  "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "contract_sha256": hashlib.sha256(model_contract.read_bytes()).hexdigest()},
        "requested": {"duration_s": duration_s, "cpu_load_workers": load_workers,
                      "allow_nonrt": allow_nonrt, "model_cpu": model_cpu,
                      "load_cpus": list(load_cpus), "step_period_ns": STEP_NS,
                      "step_limit_abs_lateness_ns": 10_000,
                      "system_period_ns": STATUS_GROUP_NS, "system_limit_abs_error_ns": 1_000_000},
        "realtime": stats,
        "cycle_80ms_observation": cycle,
        "management_udp_load": traffic_summary,
        "resource_usage": resource_usage,
        "not_verified": [
            "3.6_STATUS_SERVICE_80MS_PUBLICATION_UNTIL_SERVICE_IS_DEPLOYED",
            "PHYSICAL_CAN_OR_ETHERNET_THROUGHPUT",
            "LONG_STABILITY_UNLESS_DURATION_IS_1800_SECONDS_OR_MORE",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-executable", type=Path,
                        default=ROOT / "artifacts/linux_target/l010-step-candidate-20261112T100000Z/bin/quadrotor_hil_rt")
    parser.add_argument("--model-contract", type=Path,
                        default=ROOT / "artifacts/z_mission/model/hil_contract.json")
    parser.add_argument("--duration-s", type=float, default=1800.0,
                        help="生产长稳默认 1800 秒；采集器烟测可显式缩短。")
    parser.add_argument("--load-workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--model-cpu", type=int,
                        help="将 C 模型固定到一个 CPU；与 --load-cpus 互斥。")
    parser.add_argument("--load-cpus", default="",
                        help="负载进程可使用的逗号分隔 CPU，例如 0,1,2,4,5,6,7。")
    parser.add_argument("--allow-nonrt", action="store_true", help="仅采集器烟测，结果绝不视为 L-013 合格。")
    parser.add_argument("--recover-log", type=Path,
                        help="仅把已中断运行的 C 原始日志封存为 NOT_QUALIFIED 证据。")
    args = parser.parse_args()
    try:
        load_cpus = tuple(int(value) for value in args.load_cpus.split(",") if value)
    except ValueError as error:
        parser.error("--load-cpus must be comma-separated integers: %s" % error)
    previous_handlers: dict[int, Any] = {}

    def interrupted(signum: int, _frame: Any) -> None:
        raise InterruptedError("received signal %d; C child cleanup will run" % signum)

    for signal_number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        previous_handlers[signal_number] = signal.signal(signal_number, interrupted)
    try:
        if args.recover_log is not None:
            result = recover_interrupted_run(args.output.resolve(), args.recover_log,
                                             args.model_executable, args.model_contract)
        else:
            result = run(args.output.resolve(), args.model_executable, args.model_contract,
                         duration_s=args.duration_s, load_workers=args.load_workers,
                         allow_nonrt=args.allow_nonrt, model_cpu=args.model_cpu,
                         load_cpus=load_cpus)
    except (OSError, ValueError, RuntimeError, TimeoutError, InterruptedError, json.JSONDecodeError) as error:
        result = {"format": "HIL_L013_RT_LOAD_1", "status": "NOT_QUALIFIED",
                  "error": type(error).__name__, "detail": str(error)}
    finally:
        for signal_number, previous in previous_handlers.items():
            signal.signal(signal_number, previous)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "TARGET_RT_LOAD_VALIDATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
