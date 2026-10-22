"""Verified v0.3 simulator-management API Schema runtime.

The management API is deliberately separate from :mod:`icd_runtime.contract`:
the latter verifies the four-component formal-business baseline, while this
module verifies the frozen API asset and safely resolves its references to the
same business Schema and the retained v0.2 package metadata Schema.
"""

import copy
import hashlib
from pathlib import Path

from jsonschema import Draft202012Validator, SchemaError
from referencing import Registry, Resource

from .contract import Contract, ICDValidator, UTC_CHECKER
from .errors import ICDError
from .json_codec import check_json_domain, loads


API_FILE = "input-simulator-api-v0.3.schema.json"
BUSINESS_FILE = "input-simulator-business-v0.3.schema.json"
PACKAGE_FILE = "input-simulator-package-v0.2.schema.json"
MANIFEST_FILE = "input-simulator-v0.3.manifest.json"

API_ID = "urn:hil:input-simulator:api:0.3"
BUSINESS_ID = "urn:hil:input-simulator:business:0.3"
PACKAGE_ID = "urn:hil:input-simulator:package-contract:0.2"

# The package metadata Schema is intentionally outside the four-component
# business baseline.  Keep its original raw-byte fingerprint explicit so an
# altered compatibility Schema cannot widen management input acceptance.
PACKAGE_SHA256 = "29fcd5f39a0fbfe6744b1648fd5865cb87a7f032ad1960d57e2bd8d8f3a1c14f"


def _raw(directory, name):
    try:
        return (Path(directory) / name).read_bytes()
    except OSError as error:
        raise ICDError("HASH", "missing frozen management Schema asset") from error


def _manifest_hashes(directory):
    manifest = loads(_raw(directory, MANIFEST_FILE))
    if (type(manifest) is not dict or manifest.get("hash_basis") != "RAW_FILE_BYTES_SHA256"
            or type(manifest.get("files")) is not list):
        raise ICDError("HASH", "invalid management Schema manifest")
    result = {}
    for item in manifest["files"]:
        if (type(item) is not dict or set(item) != {"file", "sha256", "size_bytes"}
                or type(item["file"]) is not str or type(item["sha256"]) is not str
                or type(item["size_bytes"]) is not int):
            raise ICDError("HASH", "invalid management Schema manifest entry")
        if item["file"] in result:
            raise ICDError("HASH", "duplicate management Schema manifest entry")
        result[item["file"]] = (item["sha256"], item["size_bytes"])
    return result


def _verified_json(directory, name, expected_hash=None):
    raw = _raw(directory, name)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_hash is not None and digest != expected_hash:
        raise ICDError("HASH", "frozen management Schema asset hash mismatch")
    try:
        value = loads(raw)
    except ICDError as error:
        raise ICDError("HASH", "invalid frozen management Schema JSON") from error
    if type(value) is not dict:
        raise ICDError("HASH", "frozen management Schema root must be an object")
    return value


class ManagementContract:
    """Read-only validators for the frozen v0.3 management API.

    The supplied ``Contract`` must be loaded from the exact same directory.
    This prevents a valid API document from being paired with another business
    baseline at runtime.
    """

    @classmethod
    def load(cls, directory, *, contract):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError("HASH", "verified formal business Contract required")
        directory = Path(directory)
        hashes = _manifest_hashes(directory)
        for name in (API_FILE, BUSINESS_FILE):
            if name not in hashes:
                raise ICDError("HASH", "management Schema manifest omits required asset")
        api_hash, _api_size = hashes[API_FILE]
        business_hash, _business_size = hashes[BUSINESS_FILE]
        if business_hash != contract.component_hashes.get("business_schema_sha256"):
            raise ICDError("HASH", "management and formal business Schema fingerprints differ")
        api = _verified_json(directory, API_FILE, api_hash)
        business = _verified_json(directory, BUSINESS_FILE, business_hash)
        package = _verified_json(directory, PACKAGE_FILE, PACKAGE_SHA256)
        if (api.get("$id") != API_ID or business.get("$id") != BUSINESS_ID
                or package.get("$id") != PACKAGE_ID):
            raise ICDError("VERSION", "unexpected management Schema identity")
        # The public API expresses UInt64 as a JSON string.  The frozen Schema
        # carries the lexical pattern while its description assigns the numeric
        # upper bound; install that bound only in the in-memory validator.
        api = copy.deepcopy(api)
        api["$defs"]["UInt64"]["x-decimal-maximum"] = 2**64 - 1
        try:
            for value in (api, business, package):
                Draft202012Validator.check_schema(value)
            registry = Registry()
            for value in (api, business, package):
                registry = registry.with_resource(value["$id"], Resource.from_contents(value))
            return cls(api, registry, contract)
        except (SchemaError, ValueError) as error:
            raise ICDError("SCHEMA", "invalid frozen management Schema") from error

    def __init__(self, schema, registry, contract):
        self._schema = schema
        self._registry = registry
        self.contract = contract
        self._validators = {}
        self._validator("Request")
        self._validator("Response")

    @property
    def commands(self):
        return tuple(self._schema["$defs"]["Command"]["enum"])

    def _validator(self, definition):
        if type(definition) is not str or definition not in self._schema.get("$defs", {}):
            raise ICDError("UNSUPPORTED", "unknown management Schema definition")
        existing = self._validators.get(definition)
        if existing is not None:
            return existing
        root = {"$ref": "{}#/$defs/{}".format(API_ID, definition)}
        validator = ICDValidator(root, registry=self._registry,
                                 format_checker=UTC_CHECKER)
        self._validators[definition] = validator
        return validator

    @staticmethod
    def _validate(validator, value):
        check_json_domain(value)
        error = next(validator.iter_errors(value), None)
        if error is not None:
            path = ".".join(str(item) for item in error.absolute_path)
            raise ICDError("SCHEMA", "invalid management field at {}: {}".format(
                path or "<root>", error.validator))

    def validate_definition(self, definition, value):
        """Validate one public API definition without dispatching a command."""
        self._validate(self._validator(definition), value)

    def validate_request(self, value):
        self._validate(self._validator("Request"), value)

    def validate_response(self, value):
        self._validate(self._validator("Response"), value)
