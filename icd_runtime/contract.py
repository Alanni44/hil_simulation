"""Read-only verified contract and structural validation, not a session service."""

import copy
import datetime
import hashlib
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

from .errors import ICDError
from .json_codec import canonicalize, check_json_domain, loads

COMPONENTS = {
    "business_schema_sha256": "input-simulator-business-v0.3.schema.json",
    "wire_catalog_sha256": "input-simulator-icd-v0.3.json",
    "canfd_dbc_sha256": "input-simulator-canfd-v0.3.dbc",
    "contract_doc_sha256": "input-simulator-data-contract-v0.3.md",
}

SOURCE_DEFINITIONS = frozenset({
    "SourceInputs", "ProtocolSource", "ScenarioSource", "HistorySource", "ResourceRef",
    "ReplayPolicy", "HistoryStream", "Event", "Assertion", "Cleanup",
})


def _decimal_maximum(validator, maximum, instance, schema):
    if isinstance(instance, str):
        if re.fullmatch(r"0|[1-9][0-9]{0,19}", instance) is None:
            yield ValidationError("decimal string must be canonical ASCII uint64")
        elif int(instance) > int(maximum):
            yield ValidationError("decimal string exceeds uint64 range")


ICDValidator = validators.extend(Draft202012Validator, {"x-decimal-maximum": _decimal_maximum})
UTC_CHECKER = FormatChecker()


@UTC_CHECKER.checks("date-time", raises=(ValueError, OverflowError))
def _utc_time(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
        return False
    datetime.datetime.fromisoformat(value[:-1] + "+00:00")
    return True


class Contract:
    @classmethod
    def load(cls, directory: Path, *, expected_sha256: str):
        if not isinstance(expected_sha256, str) or not re.fullmatch("[0-9a-f]{64}", expected_sha256):
            raise ICDError("HASH", "expected baseline fingerprint must be supplied externally")
        directory = Path(directory)
        try:
            raw = {key: (directory / name).read_bytes() for key, name in COMPONENTS.items()}
            actual = {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}
            fingerprint = hashlib.sha256(canonicalize(actual)).hexdigest()
            declared = loads((directory / "input-simulator-v0.3.baseline.json").read_bytes())
        except OSError as exc:
            raise ICDError("HASH", "missing baseline component") from exc
        if (fingerprint != expected_sha256 or declared.get("components") != actual
                or declared.get("baseline_sha256") != fingerprint
                or declared.get("algorithm") != "SHA256_RFC8785_CANONICAL_COMPONENT_OBJECT"):
            raise ICDError("HASH", "baseline component/fingerprint mismatch")
        schema = loads(raw["business_schema_sha256"])
        catalogue = loads(raw["wire_catalog_sha256"])
        if (catalogue.get("baseline_version") != "HIL-ICD-1.0"
                or catalogue.get("document_version") != "0.3"
                or schema.get("$id") != catalogue.get("schema_id")
                or declared.get("baseline_version") != catalogue.get("baseline_version")):
            raise ICDError("VERSION", "not the v0.3 HIL-ICD-1.0 baseline")
        contract = cls(schema, catalogue, fingerprint)
        contract._component_hashes = actual
        return contract

    def __init__(self, schema, catalogue, fingerprint):
        Draft202012Validator.check_schema(schema)
        self.baseline_sha256 = fingerprint
        self._schema = copy.deepcopy(schema)
        self._catalogue = copy.deepcopy(catalogue)
        self._messages = {m["id"]: m for m in catalogue["messages"]}
        self._payload_validators = {}
        self._message_validators = {}
        self._component_hashes = {}
        self._source_validators = {}
        self._stimulus_validators = {}
        for branch in schema["$defs"]["BusinessMessage"]["oneOf"]:
            mid = branch["properties"]["message_id"]["const"]
            root = {**branch, "$defs": self._schema["$defs"]}
            self._message_validators[mid] = ICDValidator(root, format_checker=UTC_CHECKER)
        self._header_validator = self._definition_validator("Header")
        for mid, entry in self._messages.items():
            self._payload_validators[mid] = self._definition_validator(entry["payload_definition"])
        for branch in schema["$defs"]["Stimulus"]["oneOf"]:
            mid = branch["properties"]["message_id"]["const"]
            self._stimulus_validators[mid] = ICDValidator(
                {**branch, "$defs": self._schema["$defs"]}, format_checker=UTC_CHECKER)

    def _definition_validator(self, name):
        return ICDValidator({"$ref": f"#/$defs/{name}", "$defs": self._schema["$defs"]}, format_checker=UTC_CHECKER)

    @property
    def messages(self):
        return copy.deepcopy(self._messages)

    @property
    def catalogue(self):
        return copy.deepcopy(self._catalogue)

    @property
    def component_hashes(self):
        """Only load() supplies verified original-file hashes; parsed objects are not files."""
        return self._component_hashes.copy()

    def validate_source_definition(self, name, value):
        """Frozen source structure only; not resource integrity or execution readiness."""
        if type(name) is not str or name not in SOURCE_DEFINITIONS:
            raise ICDError("UNSUPPORTED", "unknown source definition")
        if name not in self._source_validators:
            self._source_validators[name] = self._definition_validator(name)
        self._validate(self._source_validators[name], value)

    def validate_stimulus(self, value, *, model_id=None):
        if type(value) is not dict or "message_id" not in value:
            raise ICDError("SCHEMA", "Stimulus object required")
        mid = value["message_id"]
        entry = self.entry(mid)
        if entry["direction"] != "TO_36":
            raise ICDError("AUTHORIZATION", "feedback cannot become an input Stimulus")
        self._validate(self._stimulus_validators[mid], value)
        if model_id is not None and model_id not in entry["model_ids"]:
            raise ICDError("MODEL", "Stimulus is not defined for the selected model")
        self.validate_payload(mid, value["payload"])

    def entry(self, message_id):
        if type(message_id) is not int:
            raise ICDError("SCHEMA", "message_id must be an integer, not bool or float")
        if message_id not in self._messages:
            raise ICDError("UNSUPPORTED", "unknown message ID")
        return copy.deepcopy(self._messages[message_id])

    @staticmethod
    def _validate(validator, value):
        check_json_domain(value)
        error = next(validator.iter_errors(value), None)
        if error:
            path = ".".join(str(p) for p in error.absolute_path)
            raise ICDError("SCHEMA", f"invalid field at {path or '<root>'}: {error.validator}")

    def validate_payload(self, message_id, payload):
        self.entry(message_id)
        self._validate(self._payload_validators[message_id], payload)
        if message_id in (1, 129) and payload["baseline_sha256"] != self.baseline_sha256:
            raise ICDError("HASH", "session baseline differs from loaded contract")
        if message_id == 129 and payload["lease_ms"] != 1000:
            raise ICDError("SCHEMA", "granted lease must be 1000ms")

    def validate_resource(self, kind, value):
        """Validate frozen file definitions, not active origin/controller/ABI readiness."""
        definitions = {"TERRAIN": "TerrainResource", "OBSTACLES": "ObstaclesResource", "MISSION": "MissionLoad"}
        if type(kind) is not str or kind not in definitions:
            raise ICDError("UNSUPPORTED", "no defined JSON content Schema for this resource kind")
        self._validate(self._definition_validator(definitions[kind]), value)

    def validate_resource_feedback(self, request, reply):
        """Correlate byte-storage progress, not model activation or consumer evidence."""
        self.validate_message(request, direction="TO_36")
        self.validate_message(reply, direction="FROM_36")
        if request["message_id"] != 34 or reply["message_id"] != 141:
            raise ICDError("STATE", "ResourceAck must identify ResourceChunk34")
        sent, progress = request["payload"], reply["payload"]
        if (reply["header"]["session_id"] != request["header"]["session_id"]
                or reply["header"]["transaction_id"] != request["header"]["transaction_id"]
                or progress["resource_sha256"] != sent["resource_sha256"]
                or progress["stored_bytes"] != progress["next_offset"]
                or progress["next_offset"] > sent["size_bytes"]):
            raise ICDError("STATE", "resource progress differs from original request/session/hash")
        if progress["error"] != "OK":
            if progress["complete"]:
                raise ICDError("STATE", "failed resource cannot report successful completion")
        elif (progress["next_offset"] < sent["offset_bytes"] + sent["chunk_length"]
                or progress["complete"] != (progress["next_offset"] == sent["size_bytes"])):
            raise ICDError("STATE", "successful resource progress does not cover the accepted chunk")

    def validate_header(self, message_id, header):
        entry = self.entry(message_id)
        self._validate(self._header_validator, header)
        if header["valid_for_ms"] != entry["valid_for_ms"]:
            raise ICDError("SCHEMA", "valid_for_ms differs from immutable catalogue timing")
        if message_id == 1:
            if (header["session_id"], header["sequence"], header["target_step"]) != (0, 1, 0):
                raise ICDError("SCHEMA", "SessionOpen requires session=0, sequence=1, target_step=0")
        elif header["session_id"] == 0 and message_id != 130:
            raise ICDError("STALE_SESSION", "nonzero session required")

    def validate_message(self, message, *, direction=None, model_id=None):
        if type(message) is not dict or "message_id" not in message:
            raise ICDError("SCHEMA", "business message object required")
        mid = message["message_id"]
        entry = self.entry(mid)
        self._validate(self._message_validators[mid], message)
        if direction is not None and direction != entry["direction"]:
            raise ICDError("AUTHORIZATION", "message direction mismatch")
        if model_id is not None and model_id not in entry["model_ids"]:
            raise ICDError("MODEL", "message is not defined for the selected model")
        self.validate_header(mid, message["header"])
        self.validate_payload(mid, message["payload"])
        if mid == 130 and message["header"]["session_id"] == 0:
            payload = message["payload"]
            if not (payload["request_message_id"] == 1 and payload["stage"] == "FAILED"
                    and payload["error"] != "OK"):
                raise ICDError("STALE_SESSION", "zero-session ACK only rejects SessionOpen")
