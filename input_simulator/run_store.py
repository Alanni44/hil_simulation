"""Bounded in-process storage for simulator management Runs.

This deliberately owns no transport, HIL session or worker.  Keeping the
pre-START registry side-effect free makes CREATE/GET safe to deploy before the
execution chain is connected.
"""

import base64
import copy
import datetime
from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


TERMINAL_STATES = frozenset({"COMPLETED", "FAILED"})
_STATE_VERSION = 1
_STATE_FILE = "run-store-v1.json"
_MAX_STATE_BYTES = 128 * 1024 * 1024


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _b64_encode(value):
    return base64.b64encode(value).decode("ascii")


def _b64_decode(value):
    if type(value) is not str:
        raise ICDError("RESOURCE", "persistent Run state contains an invalid byte field")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ICDError("RESOURCE", "persistent Run state contains invalid base64") from error
    return raw


@dataclass(frozen=True, slots=True)
class StoredRun:
    run: dict
    create_snapshot: bytes
    source_snapshot: bytes
    resource_evidence: tuple


class RunStore:
    """A small, lock-protected registry with request-id replay protection."""

    def __init__(self, *, max_runs=64, max_requests=512, max_records_per_run=4096,
                 state_directory=None):
        if (type(max_runs) is not int or not 1 <= max_runs <= 4096
                or type(max_requests) is not int or not 1 <= max_requests <= 65536
                or type(max_records_per_run) is not int or not 1 <= max_records_per_run <= 65536):
            raise ICDError("CAPACITY", "finite Run and request capacities required")
        self._max_runs = max_runs
        self._max_requests = max_requests
        self._max_records_per_run = max_records_per_run
        self._runs = {}
        self._requests = {}
        self._records = {}
        self._next_record_cursor = {}
        self._first_retained_cursor = {}
        self._record_reserved = {}
        self._lock = threading.RLock()
        self._state_dir = None
        self._state_path = None
        if state_directory is not None:
            self._configure_persistence(state_directory)

    def _configure_persistence(self, value):
        path = Path(value)
        try:
            if path.is_symlink():
                raise OSError("state directory must not be a symlink")
            path = path.resolve(strict=True)
        except OSError as error:
            raise ICDError("RESOURCE", "persistent Run state directory is unavailable") from error
        if not path.is_dir():
            raise ICDError("RESOURCE", "persistent Run state path is not a directory")
        self._state_dir, self._state_path = path, path / _STATE_FILE
        with self._lock:
            if self._state_path.exists() or self._state_path.is_symlink():
                self._load_locked()
                recovered = self._recover_unfinished_locked()
                if recovered:
                    self._persist_locked()
            else:
                self._persist_locked()

    def _state_document_locked(self):
        runs = []
        for run_id, stored in self._runs.items():
            evidence = []
            for item in stored.resource_evidence:
                if is_dataclass(item):
                    evidence.append(asdict(item))
                elif type(item) is dict:
                    evidence.append(copy.deepcopy(item))
                else:
                    raise ICDError("STATE", "Run resource evidence is not persistable")
            runs.append({
                "run_id": run_id, "run": stored.run,
                "create_snapshot_b64": _b64_encode(stored.create_snapshot),
                "source_snapshot_b64": _b64_encode(stored.source_snapshot),
                "resource_evidence": evidence,
            })
        return {
            "version": _STATE_VERSION,
            "runs": runs,
            "requests": [{"request_id": key, "request_b64": _b64_encode(request),
                          "response": response}
                         for key, (request, response) in self._requests.items()],
            "records": self._records,
            "next_record_cursor": self._next_record_cursor,
            "first_retained_cursor": self._first_retained_cursor,
        }

    def _persist_locked(self):
        if self._state_path is None:
            return
        raw = canonicalize(self._state_document_locked())
        if len(raw) > _MAX_STATE_BYTES:
            raise ICDError("CAPACITY", "persistent Run state exceeds the configured safety bound")
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".run-store-", suffix=".tmp", dir=self._state_dir)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._state_path)
                directory_fd = os.open(self._state_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary is not None and os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as error:
            raise ICDError("RESOURCE", "persistent Run state cannot be written") from error

    def _load_locked(self):
        try:
            if self._state_path.is_symlink() or not self._state_path.is_file():
                raise OSError("state file must be a regular file")
            raw = self._state_path.read_bytes()
        except OSError as error:
            raise ICDError("RESOURCE", "persistent Run state cannot be read") from error
        if len(raw) > _MAX_STATE_BYTES:
            raise ICDError("CAPACITY", "persistent Run state exceeds the configured safety bound")
        try:
            value = loads(raw)
            if type(value) is not dict or set(value) != {
                    "version", "runs", "requests", "records", "next_record_cursor", "first_retained_cursor"}:
                raise ValueError("state keys differ")
            if value["version"] != _STATE_VERSION or type(value["runs"]) is not list or type(value["requests"]) is not list:
                raise ValueError("state version or collection differs")
            if len(value["runs"]) > self._max_runs or len(value["requests"]) > self._max_requests:
                raise ICDError("CAPACITY", "persistent Run state exceeds configured item capacity")
            from input_simulator.source_inputs import ResourceEvidence
            runs, requests, records = {}, {}, {}
            next_cursor, first_cursor, reserved = {}, {}, {}
            for item in value["runs"]:
                if type(item) is not dict or set(item) != {
                        "run_id", "run", "create_snapshot_b64", "source_snapshot_b64", "resource_evidence"}:
                    raise ValueError("stored Run differs")
                run_id, run = item["run_id"], item["run"]
                if (type(run_id) is not str or type(run) is not dict or run.get("run_id") != run_id
                        or run_id in runs or type(item["resource_evidence"]) is not list):
                    raise ValueError("stored Run identity differs")
                evidence = tuple(ResourceEvidence(**entry) for entry in item["resource_evidence"])
                runs[run_id] = StoredRun(copy.deepcopy(run), _b64_decode(item["create_snapshot_b64"]),
                                         _b64_decode(item["source_snapshot_b64"]), evidence)
                reserved[run_id] = 0
            for item in value["requests"]:
                if type(item) is not dict or set(item) != {"request_id", "request_b64", "response"}:
                    raise ValueError("stored request differs")
                key, request, response = item["request_id"], _b64_decode(item["request_b64"]), item["response"]
                if type(key) is not str or key in requests or type(response) is not dict or canonicalize(loads(request)) != request:
                    raise ValueError("stored request is invalid")
                requests[key] = (request, copy.deepcopy(response))
            if set(value["records"]) != set(runs) or set(value["next_record_cursor"]) != set(runs) or set(value["first_retained_cursor"]) != set(runs):
                raise ValueError("stored record owner differs")
            for run_id, rows in value["records"].items():
                if type(rows) is not list or len(rows) > self._max_records_per_run:
                    raise ValueError("stored record capacity differs")
                expected_next, expected_first = value["next_record_cursor"][run_id], value["first_retained_cursor"][run_id]
                if (type(expected_next) is not int or type(expected_first) is not int
                        or not 1 <= expected_first <= expected_next):
                    raise ValueError("stored record cursor differs")
                cursor = expected_first
                for row in rows:
                    if (type(row) is not dict or row.get("run_id") != run_id or row.get("cursor") != str(cursor)
                            or row.get("record_id") != "record-" + str(cursor)):
                        raise ValueError("stored record sequence differs")
                    cursor += 1
                if expected_next != cursor:
                    raise ValueError("stored record cursor differs")
                records[run_id], next_cursor[run_id], first_cursor[run_id] = copy.deepcopy(rows), expected_next, expected_first
            self._runs, self._requests, self._records = runs, requests, records
            self._next_record_cursor, self._first_retained_cursor = next_cursor, first_cursor
            self._record_reserved = reserved
        except ICDError:
            raise
        except (TypeError, ValueError, KeyError) as error:
            raise ICDError("RESOURCE", "persistent Run state is invalid") from error

    def _recover_unfinished_locked(self):
        """Never resume prior effects after a process restart.

        The retained snapshot/records remain queryable, while any active Run
        is made explicitly incomplete.  A new process has no owned Session or
        worker, so treating it as still RUNNING or STOPPED would be false.
        """
        recovered = False
        for run_id, stored in tuple(self._runs.items()):
            # READY/VALIDATING/BLOCKED own no execution worker or target-side
            # effect and are therefore safe to retain across a service restart.
            # Only an active execution must become explicitly incomplete.
            if stored.run["state"] not in {"WAITING", "RUNNING", "PAUSED", "STOPPING"}:
                continue
            run = copy.deepcopy(stored.run)
            revision = int(run["revision"])
            if revision >= 2**64 - 1:
                raise ICDError("CAPACITY", "recovered Run revision has reached uint64 capacity")
            run.update(state="COMPLETED", result="INCOMPLETE", available_actions=[], evidence_complete=False,
                       last_error={"code": "EVIDENCE_INCOMPLETE", "retryable": False, "details": []},
                       revision=str(revision + 1), updated_at=_utc_now())
            self._runs[run_id] = StoredRun(run, stored.create_snapshot, stored.source_snapshot,
                                           stored.resource_evidence)
            fact = {
                "record_id": "record-" + str(self._next_record_cursor[run_id]),
                "cursor": str(self._next_record_cursor[run_id]), "run_id": run_id,
                "input_event_id": None,
                "operation_id": "recovery-" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32],
                "kind": "OPERATION_RESULT",
                "timestamp": run["updated_at"], "clock_domain": run["clock_domain_id"],
                "monotonic_us": "0", "message_id": None, "reason_code": "RECOVERY_INCOMPLETE",
                "evidence_refs": [], "event_id": None, "link_id": None, "operation_result": "FAILED",
            }
            rows = self._records[run_id]
            rows.append(fact)
            self._next_record_cursor[run_id] += 1
            if len(rows) > self._max_records_per_run:
                rows.pop(0)
                self._first_retained_cursor[run_id] += 1
            recovered = True
        return recovered

    def replay(self, request_id, request):
        request_json = canonicalize(request)
        with self._lock:
            existing = self._requests.get(request_id)
            if existing is None:
                return None
            if existing[0] != request_json:
                raise ICDError("IDEMPOTENCY_CONFLICT", "request_id was already used for another command")
            return copy.deepcopy(existing[1])

    def remember(self, request_id, request, response):
        request_json = canonicalize(request)
        response_copy = copy.deepcopy(response)
        with self._lock:
            existing = self._requests.get(request_id)
            if existing is not None:
                if existing[0] != request_json:
                    raise ICDError("IDEMPOTENCY_CONFLICT", "request_id was already used for another command")
                return copy.deepcopy(existing[1])
            if len(self._requests) >= self._max_requests:
                raise ICDError("CAPACITY", "request-id registry capacity is exhausted")
            self._requests[request_id] = (request_json, response_copy)
            self._persist_locked()
            return copy.deepcopy(response_copy)

    def create(self, run, *, create_snapshot, source_snapshot, resource_evidence):
        run_copy = copy.deepcopy(run)
        run_id = run_copy["run_id"]
        with self._lock:
            if any(item.run["state"] not in TERMINAL_STATES for item in self._runs.values()):
                raise ICDError("CONTROL_CONFLICT", "one non-terminal simulator Run is already registered")
            if run_id in self._runs:
                raise ICDError("STATE", "generated Run ID already exists")
            if len(self._runs) >= self._max_runs:
                raise ICDError("CAPACITY", "Run registry capacity is exhausted")
            self._runs[run_id] = StoredRun(
                run=run_copy, create_snapshot=bytes(create_snapshot),
                source_snapshot=bytes(source_snapshot), resource_evidence=tuple(resource_evidence))
            self._records[run_id] = []
            self._next_record_cursor[run_id] = 1
            self._first_retained_cursor[run_id] = 1
            self._record_reserved[run_id] = 0
            self._persist_locked()
            return copy.deepcopy(run_copy)

    def get(self, run_id):
        with self._lock:
            stored = self._runs.get(run_id)
            if stored is None:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            return copy.deepcopy(stored.run)

    def execution_snapshot(self, run_id):
        """Return the immutable CREATE evidence needed by an actual executor."""
        with self._lock:
            stored = self._runs.get(run_id)
            if stored is None:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            return StoredRun(copy.deepcopy(stored.run), bytes(stored.create_snapshot),
                             bytes(stored.source_snapshot), tuple(stored.resource_evidence))

    def replace_run(self, run_id, expected_revision, replacement):
        """Atomically replace a validated Run after a caller-owned CAS check."""
        replacement = copy.deepcopy(replacement)
        with self._lock:
            stored = self._runs.get(run_id)
            if stored is None:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            if stored.run["revision"] != expected_revision:
                raise ICDError("VERSION_CONFLICT", "Run revision differs from the control request")
            if replacement.get("run_id") != run_id:
                raise ICDError("STATE", "replacement Run identity differs")
            self._runs[run_id] = StoredRun(
                replacement, stored.create_snapshot, stored.source_snapshot, stored.resource_evidence)
            self._persist_locked()
            return copy.deepcopy(replacement)

    def append_record(self, run_id, record):
        """Store one already schema-validated fact at its server cursor."""
        record_copy = copy.deepcopy(record)
        with self._lock:
            if run_id not in self._runs:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            expected = str(self._next_record_cursor[run_id])
            if (record_copy.get("run_id") != run_id or record_copy.get("cursor") != expected
                    or type(record_copy.get("record_id")) is not str):
                raise ICDError("STATE", "Record identity or cursor differs from the original Run sequence")
            rows = self._records[run_id]
            rows.append(record_copy)
            if self._record_reserved[run_id]:
                self._record_reserved[run_id] -= 1
            self._next_record_cursor[run_id] += 1
            if len(rows) > self._max_records_per_run:
                rows.pop(0)
                self._first_retained_cursor[run_id] += 1
            self._persist_locked()
            return copy.deepcopy(record_copy)

    def reserve_records(self, run_id, count):
        """Reserve finite evidence slots before a worker can cause effects."""
        if type(count) is not int or not 1 <= count <= self._max_records_per_run:
            raise ICDError("CAPACITY", "bounded positive evidence reservation required")
        with self._lock:
            if run_id not in self._runs:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            if len(self._records[run_id]) + self._record_reserved[run_id] + count > self._max_records_per_run:
                raise ICDError("CAPACITY", "Run evidence capacity is insufficient before execution")
            self._record_reserved[run_id] += count
            self._persist_locked()

    def release_reserved_records(self, run_id):
        with self._lock:
            if run_id not in self._runs:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            self._record_reserved[run_id] = 0
            self._persist_locked()

    def append_fact(self, run_id, fact):
        """Allocate the next cursor atomically for one management evidence fact."""
        if type(fact) is not dict:
            raise ICDError("SCHEMA", "record fact object required")
        with self._lock:
            if run_id not in self._runs:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            cursor = str(self._next_record_cursor[run_id])
            record = copy.deepcopy(fact)
            record.update(run_id=run_id, cursor=cursor, record_id="record-" + cursor)
            return self.append_record(run_id, record)

    def list_records(self, run_id, *, after_cursor=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ICDError("SCHEMA", "bounded RecordPage limit required")
        if after_cursor is not None and (type(after_cursor) is not str or not after_cursor.isdecimal()):
            raise ICDError("SCHEMA", "RecordPage cursor must be a decimal server cursor")
        with self._lock:
            if run_id not in self._runs:
                raise ICDError("NOT_FOUND", "simulator Run does not exist")
            after = 0 if after_cursor is None else int(after_cursor)
            first = self._first_retained_cursor[run_id]
            rows = [copy.deepcopy(row) for row in self._records[run_id]
                    if int(row["cursor"]) > after]
            items = rows[:limit]
            more = len(rows) > len(items)
            return {
                "run_id": run_id, "items": items,
                "next_cursor": items[-1]["cursor"] if more else None,
                "complete": not more,
                "retention_gap": after < first - 1,
            }

    @property
    def run_count(self):
        with self._lock:
            return len(self._runs)
