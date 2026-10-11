"""Immutable file gate for a formal 3.6 gateway deployment.

The gateway's formal mode is deliberately unavailable unless the deployment
names a release root and pins the manifest bytes that describe it.  This is a
local release-integrity gate; it does not claim that a target, a model, or a
physical interface has been qualified.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

from icd_runtime.errors import ICDError


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 256 * 1024
_FORMAT = "HIL_FORMAL_RELEASE_1"
_REQUIRED_COMPONENTS = frozenset(("gateway_entry", "runtime_library", "contract_manifest",
                                  "model_contract", "runtime_executable"))


@dataclass(frozen=True, slots=True)
class FormalRelease:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    component_sha256: tuple


def _fail(detail):
    raise ICDError("NOT_RELEASED", detail)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _regular_file(path, *, label, maximum):
    try:
        details = path.lstat()
    except OSError as error:
        _fail("formal release {} is unavailable".format(label))
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode)
            or details.st_size < 1 or details.st_size > maximum):
        _fail("formal release {} is not a bounded regular file".format(label))
    try:
        return path.read_bytes()
    except OSError as error:
        _fail("formal release {} cannot be read".format(label))


def _relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        _fail("formal release component path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        _fail("formal release component path is invalid")
    return path


def _release_root(value):
    if not isinstance(value, str) or not value:
        _fail("formal release root is required")
    root = Path(value)
    try:
        details = root.lstat()
    except OSError:
        _fail("formal release root is unavailable")
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        _fail("formal release root must be a directory, not a symlink")
    return root.resolve(strict=True)


def verify_formal_release(release, contract):
    """Verify the manifest and every required component before formal start."""
    if not isinstance(release, dict):
        _fail("formal release declaration is required")
    root = _release_root(release.get("root"))
    manifest_name = release.get("manifest")
    expected_sha256 = release.get("manifest_sha256")
    if (not isinstance(manifest_name, str) or manifest_name != "release-manifest.json"
            or not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256)):
        _fail("formal release manifest pin is invalid")
    manifest_path = root / manifest_name
    raw = _regular_file(manifest_path, label="manifest", maximum=_MAX_MANIFEST_BYTES)
    if _sha256(raw) != expected_sha256:
        _fail("formal release manifest hash does not match deployment")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _fail("formal release manifest is invalid JSON")
    if (not isinstance(value, dict) or value.get("format") != _FORMAT
            or value.get("baseline_sha256") != contract.baseline_sha256):
        _fail("formal release manifest does not match the frozen ICD baseline")
    components = value.get("components")
    if not isinstance(components, dict) or set(components) != _REQUIRED_COMPONENTS:
        _fail("formal release manifest has an incomplete component set")
    verified, paths = [], set()
    for name in sorted(_REQUIRED_COMPONENTS):
        item = components[name]
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            _fail("formal release component declaration is invalid")
        relative = _relative_path(item["path"])
        expected = item["sha256"]
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            _fail("formal release component hash is invalid")
        if relative in paths:
            _fail("formal release manifest reuses a component path")
        paths.add(relative)
        component_path = root.joinpath(*relative.parts)
        raw_component = _regular_file(component_path, label=name, maximum=512 * 1024 * 1024)
        if _sha256(raw_component) != expected:
            _fail("formal release component {} hash does not match".format(name))
        verified.append((name, expected))
    return FormalRelease(root, manifest_path, expected_sha256, tuple(verified))
