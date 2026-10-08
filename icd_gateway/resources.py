"""Serialized, bounded ResourceChunk file storage; not authorization or activation."""

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


@dataclass(frozen=True, slots=True)
class ResourceReceipt:
    resource_sha256: str
    next_offset: int
    complete: bool
    stored_bytes: int

    def payload(self):
        return {"resource_sha256": self.resource_sha256, "next_offset": self.next_offset,
                "complete": self.complete, "stored_bytes": self.stored_bytes, "error": "OK"}


@dataclass(frozen=True, slots=True)
class StoredResource:
    resource_sha256: str
    resource_kind: str
    size_bytes: int
    path: Path
    content_status: str


@dataclass(frozen=True, slots=True)
class AbortedResource:
    session_id: int
    resource_sha256: str
    stored_bytes: int
    error: str
    requests: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class UnfinishedResource:
    session_id: int
    resource_sha256: str
    stored_bytes: int
    requests: tuple[bytes, ...]


@dataclass(slots=True)
class _Upload:
    session_id: int
    kind: str
    size: int
    directory: Path
    offset: int = 0
    chunks: list = field(default_factory=list)
    requests: list = field(default_factory=list)


class ResourceStore:
    def __init__(self, contract, root, *, max_resource_bytes=32 * 1024**2,
                 max_total_bytes=128 * 1024**2, max_uploads=8, max_objects=128,
                 max_chunks=8192, min_free_bytes=64 * 1024**2,
                 max_abort_records=128, max_evidence_bytes=256 * 1024**2):
        limits = {"max_resource_bytes": (max_resource_bytes, 0xffffffff),
                  "max_total_bytes": (max_total_bytes, 0xffffffff), "max_uploads": (max_uploads, 64),
                  "max_objects": (max_objects, 8192), "max_chunks": (max_chunks, 8192),
                  "max_abort_records": (max_abort_records, 8192),
                  "max_evidence_bytes": (max_evidence_bytes, 0xffffffff)}
        for name, (value, ceiling) in limits.items():
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ICDError("CAPACITY", f"invalid bounded resource limit {name}")
            setattr(self, name, value)
        if type(min_free_bytes) is not int or not 0 <= min_free_bytes <= 0xffffffff:
            raise ICDError("CAPACITY", "invalid resource free-disk margin")
        self.min_free_bytes = min_free_bytes
        self.contract = contract
        self._active = {}
        self._completed = {}
        self._aborted = []
        self._evidence_bytes = 0
        self._last_now = -1
        self._closed = False
        self._locked = False
        self._worker_claimed = False
        self._worker_thread = None
        self.root = Path(root)
        try:
            if self.root.is_symlink():
                raise ICDError("RESOURCE", "dedicated root cannot be a symbolic link")
            self.root.mkdir(parents=True, exist_ok=True)
            self.root = self.root.resolve()
            if any(p.name not in {"objects", "incoming", ".lock"} for p in self.root.iterdir()):
                raise ICDError("RESOURCE", "dedicated resource root contains unknown entries")
            self._lock = self.root / ".lock"
            try:
                with self._lock.open("xb") as lock:
                    self._locked = True
                    lock.write(b"RESOURCE_STORE_LOCK_V1\n")
                    lock.flush()
                    os.fsync(lock.fileno())
            except FileExistsError as exc:
                raise ICDError("STATE", "resource root is busy or has a stale lock") from exc
            self._objects = self.root / "objects"
            self._incoming = self.root / "incoming"
            for directory in (self._objects, self._incoming):
                directory.mkdir(exist_ok=True)
                self._check_directory(directory, self.root)
            if any(self._incoming.iterdir()):
                raise ICDError("RESOURCE", "abandoned staging requires explicit recovery")
            for directory in self._objects.iterdir():
                if len(self._completed) >= self.max_objects:
                    raise ICDError("CAPACITY", "persisted object count exceeds deployment bound")
                metadata = self._inspect(directory)
                self._completed[directory.name] = metadata
                if self.reserved_bytes > self.max_total_bytes:
                    raise ICDError("CAPACITY", "persisted bytes exceed deployment bound")
        except (OSError, ICDError) as exc:
            if self._locked:
                self._lock.unlink()
                self._locked = False
            if isinstance(exc, ICDError):
                raise
            raise ICDError("RESOURCE", "resource root could not be opened") from exc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def active_count(self):
        return len(self._active)

    @property
    def completed_count(self):
        return len(self._completed)

    @property
    def reserved_bytes(self):
        return sum(v.size for v in self._active.values()) + sum(v["size"] for v in self._completed.values())

    def _ensure_open(self):
        self._check_worker()
        if self._closed:
            raise ICDError("STATE", "resource store is permanently closed")

    def _check_worker(self):
        if self._worker_claimed and self._worker_thread != threading.get_ident():
            raise ICDError("STATE", "actual resource worker exclusively owns storage operations")

    def _claim_worker(self):
        self._ensure_open()
        if self._worker_claimed:
            raise ICDError("STATE", "one worker lifetime per resource store")
        self._worker_claimed = True

    def _bind_worker_thread(self):
        if not self._worker_claimed or self._worker_thread is not None:
            raise ICDError("STATE", "storage thread ownership cannot be replaced")
        self._worker_thread = threading.get_ident()

    def active_session_ids(self):
        self._ensure_open()
        return tuple(sorted({upload.session_id for upload in self._active.values()}))

    def progress_for(self, message):
        self._ensure_open()
        payload = message["payload"]
        sha, kind, size = payload["resource_sha256"], payload["resource_kind"], payload["size_bytes"]
        upload = self._active.get(sha)
        if upload and (upload.session_id, upload.kind, upload.size) == (message["header"]["session_id"], kind, size):
            return ResourceReceipt(sha, upload.offset, False, upload.offset)
        complete = self._completed.get(sha)
        if complete and (complete["kind"], complete["size"]) == (kind, size):
            return ResourceReceipt(sha, complete["size"], True, complete["size"])
        return ResourceReceipt(sha, 0, False, 0)

    def check_clock(self, now_ns):
        self._ensure_open()
        if type(now_ns) is not int or now_ns < 0 or now_ns < self._last_now:
            raise ICDError("SCHEMA", "nondecreasing resource monotonic nanoseconds required")

    @staticmethod
    def _session(session_id):
        if type(session_id) is not int or not 1 <= session_id <= 0xffffffff:
            raise ICDError("SCHEMA", "nonzero uint32 resource session required")

    @staticmethod
    def _sha(value):
        if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value):
            raise ICDError("SCHEMA", "actual lower-case SHA256 required")

    @staticmethod
    def _check_directory(directory, parent):
        if (directory.is_symlink() or not directory.is_dir()
                or directory.resolve().parent != parent.resolve()):
            raise ICDError("RESOURCE", "storage directory escaped its owned parent")

    def _check_roots(self):
        self._check_directory(self._objects, self.root)
        self._check_directory(self._incoming, self.root)

    @staticmethod
    def _file(directory, name):
        path = directory / name
        if (path.is_symlink() or not path.is_file() or path.resolve().parent != directory.resolve()
                or path.stat().st_nlink != 1):
            raise ICDError("RESOURCE", "missing or unsafe owned resource file")
        return path

    @staticmethod
    def _hash(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    def _content(self, kind, path):
        if kind in ("MODEL", "VIDEO"):
            return "OPAQUE_BYTES"
        value = loads(path.read_bytes())
        self.contract.validate_resource(kind, value)
        if kind == "TERRAIN" and len(value["heights_m"]) != value["rows"] * value["columns"]:
            raise ICDError("RESOURCE", "terrain height count must equal rows*columns")
        if kind == "OBSTACLES":
            ids = [obstacle["obstacle_id"] for obstacle in value["obstacles"]]
            if len(ids) != len(set(ids)):
                raise ICDError("RESOURCE", "obstacle identities must be unique")
        if kind == "MISSION" and value["execute_from_index"] >= len(value["waypoints"]):
            raise ICDError("RESOURCE", "mission execute index must name an actual waypoint")
        return "DEFINED_JSON"

    def _inspect(self, directory):
        self._check_directory(directory, self._objects)
        self._sha(directory.name)
        if {p.name for p in directory.iterdir()} != {"data.bin", "metadata.json"}:
            raise ICDError("RESOURCE", "completed object contains unknown entries")
        metadata_path = self._file(directory, "metadata.json")
        if metadata_path.stat().st_size > 2 * 1024**2:
            raise ICDError("CAPACITY", "resource metadata exceeds bounded storage")
        metadata = loads(metadata_path.read_bytes())
        keys = {"version", "sha", "kind", "size", "content_status", "chunks"}
        if (type(metadata) is not dict or set(metadata) != keys
                or type(metadata["version"]) is not int or metadata["version"] != 1
                or metadata["sha"] != directory.name
                or type(metadata["kind"]) is not str
                or metadata["kind"] not in {"MODEL", "VIDEO", "TERRAIN", "OBSTACLES", "MISSION"}
                or type(metadata["size"]) is not int or not 1 <= metadata["size"] <= self.max_resource_bytes
                or type(metadata["chunks"]) is not list or not 1 <= len(metadata["chunks"]) <= self.max_chunks):
            raise ICDError("RESOURCE", "invalid private resource manifest")
        path = self._file(directory, "data.bin")
        if path.stat().st_size != metadata["size"] or self._hash(path) != directory.name:
            raise ICDError("HASH", "completed original bytes differ from their SHA256")
        offset = 0
        with path.open("rb") as stream:
            for index, part in enumerate(metadata["chunks"]):
                if (type(part) is not list or len(part) != 4 or type(part[0]) is not int or part[0] != offset
                        or type(part[1]) is not int or not 1 <= part[1] <= 32768
                        or type(part[3]) is not bool or part[3] != (index == len(metadata["chunks"]) - 1)):
                    raise ICDError("RESOURCE", "invalid persisted chunk boundaries")
                self._sha(part[2])
                if hashlib.sha256(stream.read(part[1])).hexdigest() != part[2]:
                    raise ICDError("HASH", "persisted chunk hash differs from actual bytes")
                offset += part[1]
        if offset != metadata["size"] or self._content(metadata["kind"], path) != metadata["content_status"]:
            raise ICDError("RESOURCE", "persisted resource content/length is inconsistent")
        return metadata

    def resolve(self, resource_sha256, *, kind):
        self._ensure_open()
        self._sha(resource_sha256)
        if type(kind) is not str or kind not in {"MODEL", "VIDEO", "TERRAIN", "OBSTACLES", "MISSION"}:
            raise ICDError("UNSUPPORTED", "undefined resource kind")
        self._check_roots()
        if resource_sha256 not in self._completed:
            raise ICDError("RESOURCE", "resource has not completed validation")
        try:
            directory = self._objects / resource_sha256
            metadata = self._inspect(directory)
            if metadata != self._completed[resource_sha256]:
                raise ICDError("RESOURCE", "private manifest changed after validation")
            if metadata["kind"] != kind:
                raise ICDError("RESOURCE", "resource kind differs from requested activation type")
            return StoredResource(resource_sha256, kind, metadata["size"], directory / "data.bin",
                                  metadata["content_status"])
        except OSError as exc:
            raise ICDError("RESOURCE", "completed resource could not be read") from exc

    def _abort(self, sha, error):
        upload = self._active[sha]
        self._check_roots()
        self._check_directory(upload.directory, self._incoming)
        if any(p.name not in {"data.bin", "metadata.json"} or p.is_symlink() or not p.is_file()
               for p in upload.directory.iterdir()):
            raise ICDError("RESOURCE", "refusing to remove unexpected staging contents")
        shutil.rmtree(upload.directory)
        result = AbortedResource(upload.session_id, sha, upload.offset, error, tuple(upload.requests))
        del self._active[sha]
        self._aborted.append(result)
        return result

    def abort_session(self, session_id):
        self._ensure_open()
        self._session(session_id)
        try:
            return tuple(self._abort(sha, "STALE_SESSION") for sha, value in list(self._active.items())
                         if value.session_id == session_id)
        except OSError as exc:
            raise ICDError("RESOURCE", "session staging cleanup failed") from exc

    def abort_resource(self, session_id, sha, *, error):
        self._ensure_open()
        self._session(session_id)
        if type(sha) is not str or not re.fullmatch("[0-9a-f]{64}", sha) or error not in ("EXPIRED", "TIMEOUT"):
            raise ICDError("SCHEMA", "owned resource timeout identity required")
        upload = self._active.get(sha)
        if upload is None:
            return ()
        if upload.session_id != session_id:
            raise ICDError("AUTHORIZATION", "cannot abort another session's resource")
        try:
            return (self._abort(sha, error),)
        except OSError as exc:
            raise ICDError("RESOURCE", "resource timeout cleanup failed") from exc

    def drain_aborted(self):
        self._check_worker()
        result = tuple(self._aborted)
        self._aborted.clear()
        self._evidence_bytes -= sum(len(request) for record in result for request in record.requests)
        return result

    def pending_cleanup_records(self):
        self._check_worker()
        return tuple(UnfinishedResource(value.session_id, sha, value.offset, tuple(value.requests))
                     for sha, value in self._active.items())

    def close(self):
        if self._closed:
            return ()
        self._ensure_open()
        try:
            result = tuple(self._abort(sha, "STATE") for sha in list(self._active))
            self._lock.unlink()
            self._locked = False
            self._closed = True
            return result
        except OSError as exc:
            raise ICDError("RESOURCE", "resource store cleanup failed; lock retained") from exc

    def accept(self, message, *, now_ns):
        self.check_clock(now_ns)
        self.contract.validate_message(message, direction="TO_36")
        if message["message_id"] != 34:
            raise ICDError("UNSUPPORTED", "resource store accepts only ResourceChunk34")
        payload, sid = message["payload"], int(message["header"]["session_id"])
        self._session(sid)
        try:
            data = base64.b64decode(payload["data_base64"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ICDError("SCHEMA", "resource chunk is not legal base64") from exc
        if (base64.b64encode(data).decode("ascii") != payload["data_base64"]
                or len(data) != payload["chunk_length"]):
            raise ICDError("SCHEMA", "base64 must be canonical with the declared decoded length")
        # Schema integer values may be represented as 1.0 in a JSON file.
        offset, size = int(payload["offset_bytes"]), int(payload["size_bytes"])
        end = offset + len(data)
        if end > size or payload["final"] != (end == size):
            raise ICDError("FRAGMENT", "final chunk must end at the exact declared resource size")
        if hashlib.sha256(data).hexdigest() != payload["chunk_sha256"]:
            raise ICDError("HASH", "actual chunk SHA256 differs from declaration")
        sha, kind = payload["resource_sha256"], payload["resource_kind"]
        part = [offset, len(data), payload["chunk_sha256"], payload["final"]]
        original = canonicalize(message)
        acquired = False
        try:
            self._check_roots()
            if sha in self._completed:
                stored = self.resolve(sha, kind=kind)
                if stored.size_bytes != size or part not in self._completed[sha]["chunks"]:
                    raise ICDError("DUPLICATE", "completed resource retry changes its original chunk")
                self._last_now = now_ns
                return ResourceReceipt(sha, size, True, size)
            upload = self._active.get(sha)
            if upload:
                if upload.session_id != sid:
                    raise ICDError("AUTHORIZATION", "resource upload is owned by another session")
                if (upload.kind, upload.size) != (kind, size):
                    raise ICDError("DUPLICATE", "resource declarations changed during upload")
                if offset < upload.offset:
                    if part not in upload.chunks:
                        code = "DUPLICATE" if any(p[0] == offset for p in upload.chunks) else "OUT_OF_ORDER"
                        raise ICDError(code, "retry differs from an original chunk boundary/content")
                    path = self._file(upload.directory, "data.bin")
                    with path.open("rb") as stream:
                        stream.seek(offset)
                        if stream.read(len(data)) != data:
                            raise ICDError("HASH", "stored retry bytes differ from original chunk")
                    self._last_now = now_ns
                    return ResourceReceipt(sha, upload.offset, False, upload.offset)
            if offset != (upload.offset if upload else 0):
                raise ICDError("OUT_OF_ORDER", "resource chunks must be contiguous without overlap")
            if upload is None:
                if size > self.max_resource_bytes or self.reserved_bytes + size > self.max_total_bytes:
                    raise ICDError("CAPACITY", "resource bytes exceed deployment capacity")
                if (len(self._active) >= self.max_uploads
                        or len(self._active) + len(self._completed) >= self.max_objects
                        or len(self._active) + len(self._aborted) >= self.max_abort_records):
                    raise ICDError("BUFFER_FULL", "resource slots/abort records full; no eviction")
            if upload and len(upload.chunks) >= self.max_chunks:
                raise ICDError("CAPACITY", "resource chunk metadata capacity reached")
            if self._evidence_bytes + len(original) > self.max_evidence_bytes:
                raise ICDError("BUFFER_FULL", "drain resource abort evidence before accepting more bytes")
            if shutil.disk_usage(self.root).free < self.min_free_bytes + (size if upload is None else len(data)):
                raise ICDError("CAPACITY", "free disk is below the resource reservation margin")
            if upload is None:
                directory = Path(tempfile.mkdtemp(prefix="upload-", dir=self._incoming))
                upload = _Upload(sid, kind, size, directory)
                self._active[sha] = upload
                upload.requests.append(original)
                self._evidence_bytes += len(original)
                acquired = True
                with (directory / "data.bin").open("xb"):
                    pass
            path = self._file(upload.directory, "data.bin")
            if path.stat().st_size != upload.offset:
                raise ICDError("HASH", "staging length changed outside the resource store")
            if not acquired:
                upload.requests.append(original)
                self._evidence_bytes += len(original)
                acquired = True
            with path.open("r+b") as stream:
                stream.seek(upload.offset)
                if stream.write(data) != len(data):
                    raise ICDError("RESOURCE", "short resource write")
                stream.flush()
                os.fsync(stream.fileno())
            upload.offset = end
            upload.chunks.append(part)
            self._last_now = now_ns
            if not payload["final"]:
                return ResourceReceipt(sha, end, False, end)
            if self._hash(path) != sha:
                raise ICDError("HASH", "whole original resource SHA256 differs from declaration")
            status = self._content(kind, path)
            metadata = {"version": 1, "sha": sha, "kind": kind, "size": size,
                        "content_status": status, "chunks": upload.chunks}
            metadata_bytes = canonicalize(metadata)
            if shutil.disk_usage(self.root).free < self.min_free_bytes + len(metadata_bytes):
                raise ICDError("CAPACITY", "free disk is below the publication metadata margin")
            with (upload.directory / "metadata.json").open("xb") as stream:
                stream.write(metadata_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            destination = self._objects / sha
            if destination.exists():
                raise ICDError("RESOURCE", "refusing to overwrite an unregistered completed object")
            upload.directory.rename(destination)
            self._completed[sha] = metadata
            self._evidence_bytes -= sum(len(request) for request in upload.requests)
            del self._active[sha]
            return ResourceReceipt(sha, size, True, size)
        except (ICDError, OSError) as exc:
            error = exc if isinstance(exc, ICDError) else ICDError("RESOURCE", "resource filesystem operation failed")
            if acquired and sha in self._active:
                self._abort(sha, error.code)
            if error is exc:
                raise
            raise error from exc
