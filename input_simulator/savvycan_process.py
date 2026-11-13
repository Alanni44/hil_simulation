"""受控 SavvyCAN CAN-FD 发送适配器，不提供通用 GUI 或命令执行入口。"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading

from icd_runtime.errors import ICDError

from .live_tool_input import LiveToolInput, LiveToolInputBuilder
from .tool_commands import ToolCommand
from .tool_process import ProcessSupervisor, ProcessSnapshot


@dataclass(frozen=True, slots=True)
class SavvyCanProcessSnapshot:
    state: str
    error: str | None
    process: ProcessSnapshot | None
    request_path: str | None
    request_sha256: str | None


class SavvyCanProcessRun:
    """将一个已分配的当前会话 CAN 输入交给项目隔离 SavvyCAN。

    SavvyCAN 自身的 GUI/script 仅支持 8 字节发送；项目隔离 V220 的
    ``--hil-authorized-send`` 入口只接收本类写出的哈希绑定请求，实际写入
    仍由 SavvyCAN 的 SerialBusConnection/SocketCAN 后端完成。
    """

    _FORMAT = "HIL_SAVVYCAN_AUTHORIZED_SEND_1"

    def __init__(self, builder, plan, *, executable: Path, directory: Path,
                 timeout_ms: int = 5000, output_limit: int = 1024 * 1024):
        if type(builder) is not LiveToolInputBuilder or type(plan) is not LiveToolInput:
            raise ICDError("STATE", "actual SavvyCAN live input builder and plan required")
        if (plan.branch_id != "SAVVY" or plan.commands !=
                (ToolCommand(("SavvyCAN", "--hil-authorized-send"), plan.binding.channel_id),)):
            raise ICDError("STATE", "exact constrained SavvyCAN command plan required")
        if (not isinstance(executable, Path) or not executable.is_absolute() or not executable.is_file()
                or not isinstance(directory, Path) or not directory.is_absolute() or not directory.is_dir()
                or directory.is_symlink()):
            raise ICDError("RESOURCE", "literal SavvyCAN executable and new evidence directory required")
        self._builder, self._plan = builder, plan
        self._executable, self._directory = executable.resolve(strict=True), directory.resolve(strict=True)
        self._timeout_ms, self._output_limit = timeout_ms, output_limit
        self._state, self._error, self._worker = "NEW", None, None
        self._request_path = self._request_sha256 = None
        self._lock = threading.Lock()

    @property
    def snapshot(self):
        worker = self._worker
        return SavvyCanProcessSnapshot(self._state, self._error,
                                       None if worker is None else worker.snapshot,
                                       None if self._request_path is None else str(self._request_path),
                                       self._request_sha256)

    def _request(self):
        self._builder.validate(self._plan)
        rows = []
        for frame in self._plan.source_input.frames:
            if (type(frame.arbitration_id) is not int or not 0 <= frame.arbitration_id <= 0x7ff
                    or type(frame.data) is not bytes or len(frame.data) != 64):
                raise ICDError("RESOURCE", "SavvyCAN only accepts exact standard 64-byte CAN-FD fragments")
            rows.append({"id": frame.arbitration_id, "data_hex": frame.data.hex().upper()})
        if not rows or len(rows) > 64:
            raise ICDError("CAPACITY", "SavvyCAN run requires one bounded nonempty input group")
        raw = json.dumps({"format": self._FORMAT, "interface": self._plan.binding.interface, "frames": rows},
                         ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        path = self._directory / "savvycan-authorized-request.json"
        try:
            with path.open("xb") as stream:
                stream.write(raw)
        except OSError as error:
            raise ICDError("RESOURCE", "SavvyCAN request file must be new and writable") from error
        self._request_path = path
        self._request_sha256 = hashlib.sha256(raw).hexdigest()

    def start(self):
        with self._lock:
            if self._state != "NEW":
                raise ICDError("STATE", "SavvyCAN run starts exactly once")
            try:
                self._request()
                # This records one actual CAN attempt only after the current
                # session, owned input and reservation were revalidated.
                self._builder.claim_can_attempt(self._plan)
                library = self._executable.parent / "lib"
                plugins = self._executable.parent / "plugins"
                env = Path("/usr/bin/env")
                if not env.is_file() or not library.is_dir() or not plugins.is_dir():
                    raise ICDError("RESOURCE", "isolated SavvyCAN runtime libraries/plugins required")
                argv = (str(env), "LD_LIBRARY_PATH=" + str(library), "QT_PLUGIN_PATH=" + str(plugins),
                        str(self._executable), "--hil-authorized-send", str(self._request_path), self._request_sha256)
                self._worker = ProcessSupervisor(argv, cwd=self._directory, timeout_ms=self._timeout_ms,
                                                 output_limit=self._output_limit)
                status = self._worker.start()
                self._state = "RUNNING" if status.state == "RUNNING" else "FAILED"
                self._error = status.error
            except ICDError as error:
                self._state, self._error = "FAILED", error.code
                raise
            return self.snapshot

    def poll(self):
        with self._lock:
            if self._worker is None:
                return self.snapshot
            status = self._worker.poll()
            if status.state == "EXITED":
                expected = b"HIL_SAVVYCAN_AUTHORIZED_SEND_OK " + str(len(self._plan.source_input.frames)).encode("ascii") + b"\n"
                # Qt SocketCAN on this Ubuntu/Qt 5.9 build logs unsupported
                # bitrate configuration keys even though the already-UP vcan
                # device accepts the FD+BRS frame.  The process exit status
                # and its exact constrained success record decide completion;
                # stderr remains retained in the ProcessSnapshot as evidence.
                if status.stdout == expected:
                    self._state = "LOCAL_EXITED"
                else:
                    self._state, self._error = "FAILED", "RESOURCE"
            elif status.state == "FAILED":
                self._state, self._error = "FAILED", status.error or "STATE"
            return self.snapshot

    def close(self):
        with self._lock:
            if self._worker is not None:
                status = self._worker.stop()
                self._worker.close()
                if self._state == "RUNNING":
                    self._state = "LOCAL_STOPPED" if status.error is None else "FAILED"
                    self._error = status.error
            return self.snapshot
