"""Bounded direct-child supervision for trusted adapters, not a public exec API."""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
import time

from icd_runtime.errors import ICDError


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    state: str
    pid: int | None
    returncode: int | None
    started_ns: int | None
    completed_ns: int | None
    stdout: bytes
    stderr: bytes
    stdout_observed: int
    stderr_observed: int
    error: str | None
    direct_child_terminal: bool
    output_complete: bool

    @property
    def tree_cleanup_verified(self):
        return False

    @property
    def execution_ready(self):
        return False


class ProcessSupervisor:
    def __init__(self, argv, *, cwd, timeout_ms=10000, output_limit=1024 * 1024, stop_timeout_ms=1000):
        if (type(argv) is not tuple or not 1 <= len(argv) <= 256
                or any(type(a) is not str or '\0' in a or len(a) > 32768 for a in argv)
                or not Path(argv[0]).is_absolute() or not isinstance(cwd, Path) or not cwd.is_absolute()
                or Path(argv[0]).suffix.lower() in ('.bat', '.cmd', '.ps1', '.sh')):
            raise ICDError('SCHEMA', 'trusted literal argv with absolute native executable and cwd required')
        if not Path(argv[0]).is_file() or not cwd.is_dir():
            raise ICDError('RESOURCE', 'configured executable and working directory must exist')
        for value, maximum in ((timeout_ms, 3600000), (output_limit, 64 * 1024 * 1024), (stop_timeout_ms, 10000)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ICDError('CAPACITY', 'finite integral process deadlines and byte limits required')
        self._argv, self._cwd = argv, cwd
        self._timeout_ns = timeout_ms * 1000000
        self._stop_seconds = stop_timeout_ms / 1000
        self._limit = output_limit
        self._operation_lock = threading.Lock()
        self._data_lock = threading.Lock()
        self._process = None
        self._threads = []
        self._buffers = [bytearray(), bytearray()]
        self._observed = [0, 0]
        self._eof = [False, False]
        self._failure = None
        self._state = 'NEW'
        self._started = self._completed = None
        self._closed = False

    def _reader(self, pipe, stream):
        try:
            while chunk := pipe.read(4096):
                with self._data_lock:
                    self._observed[stream] += len(chunk)
                    remaining = self._limit - sum(len(b) for b in self._buffers)
                    self._buffers[stream].extend(chunk[:remaining])
                    overflow = len(chunk) > remaining
                    if overflow and self._failure is None:
                        self._failure = 'BUFFER_FULL'
                if overflow:
                    self._kill_direct()
            with self._data_lock:
                self._eof[stream] = True
        except OSError:
            with self._data_lock:
                self._failure = self._failure or 'RESOURCE'
            self._kill_direct()
        finally:
            pipe.close()

    def _kill_direct(self):
        try:
            if self._process.poll() is None:
                self._process.kill()
        except OSError:
            with self._data_lock:
                self._failure = self._failure or 'STATE'

    def _snapshot(self):
        process = self._process
        with self._data_lock:
            return ProcessSnapshot(self._state, None if process is None else process.pid,
                                   None if process is None else process.returncode,
                                   self._started, self._completed,
                                   bytes(self._buffers[0]), bytes(self._buffers[1]),
                                   self._observed[0], self._observed[1], self._failure,
                                   process is not None and process.returncode is not None,
                                   all(self._eof) and self._failure not in ('BUFFER_FULL', 'RESOURCE', 'TIMEOUT'))

    @property
    def snapshot(self):
        with self._operation_lock:
            return self._snapshot()

    def start(self):
        with self._operation_lock:
            if self._closed or self._state != 'NEW':
                raise ICDError('STATE', 'process supervisor starts once and cannot reopen after close')
            self._started = time.monotonic_ns()
            try:
                self._process = subprocess.Popen(self._argv, cwd=self._cwd, shell=False,
                                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                 stderr=subprocess.PIPE, close_fds=True, bufsize=0)
            except OSError:
                self._state, self._failure = 'FAILED', 'RESOURCE'
                self._completed = time.monotonic_ns()
                return self._snapshot()
            self._state = 'RUNNING'
            try:
                for stream, pipe in enumerate((self._process.stdout, self._process.stderr)):
                    thread = threading.Thread(target=self._reader, args=(pipe, stream), daemon=True)
                    thread.start()
                    self._threads.append(thread)
            except RuntimeError:
                with self._data_lock:
                    self._failure = 'RESOURCE'
                for unopened in (self._process.stdout, self._process.stderr)[len(self._threads):]:
                    unopened.close()
                return self._stop('FAILED')
            return self._snapshot()

    def _stop(self, wanted):
        if self._process is None:
            return self._snapshot()
        deadline = time.monotonic() + self._stop_seconds
        code = self._process.poll()
        if code is not None and wanted == 'STOPPED':
            wanted = 'EXITED'
            if code != 0:
                with self._data_lock:
                    self._failure = self._failure or 'STATE'
        if code is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=max(0, deadline - time.monotonic()))
            except (OSError, subprocess.TimeoutExpired):
                self._kill_direct()
                try:
                    self._process.wait(timeout=self._stop_seconds)
                except (OSError, subprocess.TimeoutExpired):
                    with self._data_lock:
                        self._failure = self._failure or 'STATE'
        deadline_ns = time.monotonic_ns() + int(self._stop_seconds * 1000000000)
        if wanted == 'EXITED':
            deadline_ns = min(deadline_ns, self._started + self._timeout_ns)
        for thread in self._threads:
            thread.join(timeout=max(0, deadline_ns - time.monotonic_ns()) / 1000000000)
        with self._data_lock:
            if wanted == 'EXITED' and time.monotonic_ns() >= self._started + self._timeout_ns:
                self._failure = self._failure or 'TIMEOUT'
            if self._process.returncode is None or not all(self._eof):
                self._failure = self._failure or 'STATE'
            self._state = 'FAILED' if self._failure else wanted
        self._completed = self._completed or time.monotonic_ns()
        return self._snapshot()

    def _poll(self):
        if self._state != 'RUNNING':
            return self._snapshot()
        now = time.monotonic_ns()
        code = self._process.poll()
        with self._data_lock:
            eof, failure = all(self._eof), self._failure
        if failure:
            return self._stop('FAILED')
        if now >= self._started + self._timeout_ns:
            with self._data_lock:
                self._failure = 'TIMEOUT'
            return self._stop('FAILED')
        if code is not None and eof:
            with self._data_lock:
                self._failure = self._failure or ('STATE' if code != 0 else None)
                self._state = 'FAILED' if self._failure else 'EXITED'
            self._completed = now
        return self._snapshot()

    def poll(self):
        with self._operation_lock:
            return self._poll()

    def stop(self):
        with self._operation_lock:
            self._poll()
            if self._state == 'RUNNING':
                return self._stop('STOPPED')
            if self._process is not None and self._process.poll() is None:
                return self._stop('FAILED')
            return self._snapshot()

    def close(self):
        with self._operation_lock:
            self._closed = True
            self._poll()
            if self._state == 'RUNNING':
                self._stop('STOPPED')
            elif self._process is not None and self._process.poll() is None:
                self._stop('FAILED')
