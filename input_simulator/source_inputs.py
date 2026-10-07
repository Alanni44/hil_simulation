"""Offline source integrity audit. Never starts a session, tool or model."""

import argparse
from collections.abc import Mapping
import copy
from dataclasses import asdict, dataclass
import hashlib
import io
import json
from pathlib import Path
import re

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from input_simulator.protocol import ProtocolDescriptor, ProtocolParser
from input_simulator.capture import Capture, CaptureParser
from input_simulator.history import CaptureBinding, DecodedHistory, HistoryDecoder, HistoryRecord
from input_simulator.waveform import WaveformSampler
from input_simulator.scenario import ScenarioPlan


MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_LINE_BYTES = 131072
UINT64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class ResourceEvidence:
    resource_id: str
    sha256: str
    size_bytes: int
    format: str


@dataclass(frozen=True)
class EngineeringRecord:
    offset_ns: int
    stream_id: str
    stimulus_json: bytes

    @property
    def stimulus(self):
        return loads(self.stimulus_json)


@dataclass(frozen=True)
class SourceInputAudit:
    input_json: bytes
    resources: tuple[ResourceEvidence, ...]
    protocol: ProtocolDescriptor
    history_records: tuple[EngineeringRecord | HistoryRecord, ...]
    history_decoded: bool
    complete_capture: bool | None
    capture: Capture | None
    decoded_capture: DecodedHistory | None
    capture_bindings_json: bytes | None
    pending_checks: tuple[str, ...]
    input_snapshot_json: bytes | None = None
    waveforms: tuple[WaveformSampler, ...] = ()
    scenario_plan: ScenarioPlan | None = None

    @property
    def status(self):
        return "SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE"

    @property
    def execution_ready(self):
        return False

    @property
    def input_document(self):
        return loads(self.input_json if self.input_snapshot_json is None else self.input_snapshot_json)

    def report(self):
        return {"status": self.status, "execution_ready": self.execution_ready,
                "input_sha256": hashlib.sha256(self.input_json).hexdigest(),
                "input_snapshot_sha256": None if self.input_snapshot_json is None else hashlib.sha256(self.input_snapshot_json).hexdigest(),
                "compiled_waveform_count": len(self.waveforms),
                "scenario_compiled": self.scenario_plan is not None,
                "compiled_assertion_count": 0 if self.scenario_plan is None else len(self.scenario_plan.assertions),
                "scenario_pending_checks": [] if self.scenario_plan is None else list(self.scenario_plan.pending_checks),
                "resources": [asdict(resource) for resource in self.resources],
                "protocol": {"baseline_sha256": self.protocol.baseline_sha256,
                             "parsed_formats": list(self.protocol.parsed_formats),
                             "pending_formats": list(self.protocol.pending_formats),
                             "frame_count": len(self.protocol.frames),
                             "signal_count": sum(len(frame.signals) for frame in self.protocol.frames)},
                "history_decoded": self.history_decoded, "history_record_count": len(self.history_records),
                "complete_capture": self.complete_capture, "pending_checks": list(self.pending_checks),
                "capture_container": None if self.capture is None else {
                    "format": self.capture.format, "source_sha256": self.capture.source_sha256,
                    "packet_count": len(self.capture.packets),
                    "observed_truncated_packets": self.capture.observed_truncated_packets,
                    "observed_lost_packets": self.capture.observed_lost_packets,
                    "loss_count_is_lower_bound": self.capture.loss_count_is_lower_bound,
                    "clock_domains": sorted({p.clock_domain for p in self.capture.packets}),
                    "history_decoded": self.decoded_capture is not None, "execution_ready": False},
                "capture_bindings_sha256": None if self.capture_bindings_json is None else hashlib.sha256(
                    self.capture_bindings_json).hexdigest(),
                "decoded_capture": None if self.decoded_capture is None else {
                    "clock_ids": list(self.decoded_capture.clock_ids), "clock_measured": False,
                    "input_records": sum(r.direction == "TO_36" for r in self.decoded_capture.records),
                    "feedback_records": sum(r.direction == "FROM_36" for r in self.decoded_capture.records),
                    "raw_auxiliary_records": sum(r.message_json is None for r in self.decoded_capture.records),
                    "execution_ready": False},
                "model_hardware_replacement": "NOT_EXECUTED"}


def _unique(values, label):
    if len(values) != len(set(values)):
        raise ICDError("RESOURCE", f"duplicate {label}")


class SourceInputAuditor:
    def __init__(self, contract, *, max_resource_bytes=MAX_RESOURCE_BYTES,
                 max_total_bytes=MAX_TOTAL_BYTES, max_records=100000):
        for limit in (max_resource_bytes, max_total_bytes, max_records):
            if type(limit) is not int or limit <= 0:
                raise ICDError("CAPACITY", "audit limits must be positive integers")
        self.contract = contract
        self.max_resource_bytes = max_resource_bytes
        self.max_total_bytes = max_total_bytes
        self.max_records = max_records
        self._model_ids = frozenset(model for entry in contract.messages.values() for model in entry["model_ids"])

    def _message_ids(self, ids, declared=None, direction=None):
        _unique(ids, "message ID")
        for mid in ids:
            entry = self.contract.entry(mid)
            if declared is not None and mid not in declared:
                raise ICDError("RESOURCE", "message is not declared by ProtocolSource")
            if direction is not None and entry["direction"] != direction:
                raise ICDError("AUTHORIZATION", "history message direction differs from its stream")

    def _policy(self, policy, streams):
        if int(policy["start_offset_ns"]) > int(policy["end_offset_ns"]):
            raise ICDError("RESOURCE", "replay start exceeds end")
        _unique(policy["rewrite_fields"], "replay rewrite field")
        if policy["execution_mode"] == "ONLINE" and any(
                s["truncated_packets"] or s["lost_packets"] for s in streams):
            raise ICDError("RESOURCE", "incomplete capture cannot run ONLINE")

    def _assertion(self, assertion, declared):
        self._message_ids([assertion["message_id"]], declared)
        if type(assertion["expected"]) in (bool, str) and (
                assertion["tolerance"] != 0 or assertion["operator"] not in ("EQ", "NE", "EVENTUALLY")):
            raise ICDError("RESOURCE", "non-numeric assertion cannot use tolerance or ordered comparison")

    def _scenario(self, scenario, history, declared, model_id):
        if scenario is None:
            return None
        _unique([e["event_id"] for e in scenario["events"]], "event ID")
        assertions = list(scenario["assertions"])
        senders = {}
        events = sorted(scenario["events"], key=lambda e: (e["at_step"], e["priority"], e["event_id"]))
        for event in events:
            kind = event["type"]
            if "stimulus" in event:
                self.contract.validate_stimulus(event["stimulus"], model_id=model_id)
                self._message_ids([event["stimulus"]["message_id"]], declared)
                if kind == "FAULT" and event["stimulus"]["message_id"] not in (11, 12, 13, 26, 45):
                    raise ICDError("RESOURCE", "FAULT requires a defined fault message")
            if "assertion" in event:
                assertions.append(event["assertion"])
            if kind == "PERIODIC_START":
                sender = event["sender_id"]
                if sender in senders:
                    raise ICDError("RESOURCE", "sender IDs must have exactly one start")
                senders[sender] = (event["link_id"], False)
            elif kind == "PERIODIC_STOP":
                sender = event["sender_id"]
                if sender not in senders or senders[sender] != (event["link_id"], False):
                    raise ICDError("RESOURCE", "PERIODIC_STOP requires its prior start on the same tool")
                senders[sender] = (event["link_id"], True)
            elif kind == "REPLAY":
                if history is None or event["history_id"] != history["history_id"]:
                    raise ICDError("RESOURCE", "REPLAY does not reference this HistorySource")
                self._policy(event["policy"], history["streams"])
        _unique([a["assertion_id"] for a in assertions], "assertion ID")
        for assertion in assertions:
            self._assertion(assertion, declared)
        return ScenarioPlan.compile(self.contract, scenario, model_id=model_id,
                                    history_id=None if history is None else history["history_id"])

    def _resources(self, refs, blobs, pins):
        if not isinstance(blobs, Mapping):
            raise ICDError("RESOURCE", "explicit resource ID to bytes mapping required")
        _unique([r["resource_id"] for r in refs], "resource ID")
        total = 0
        verified = {}
        evidence = []
        for ref in refs:
            size = int(ref["size_bytes"])
            total += size
            if size > self.max_resource_bytes or total > self.max_total_bytes:
                raise ICDError("CAPACITY", "source resources exceed deployment audit capacity")
            raw = blobs.get(ref["resource_id"])
            if type(raw) is not bytes or len(raw) != size:
                raise ICDError("RESOURCE", "actual resource bytes are missing or size differs")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != ref["sha256"]:
                raise ICDError("HASH", "actual resource hash differs")
            fmt = ref["format"]
            expected = {"ICD_JSON": "wire_catalog_sha256", "DBC": "canfd_dbc_sha256"}.get(fmt)
            if expected is not None and digest != pins[expected]:
                raise ICDError("HASH", "protocol artifact is not the frozen original component")
            if fmt in ("ICD_JSON", "DBC", "ENGINEERING_JSONL", "CAN_LOG") and ref["encoding"] != "UTF8":
                raise ICDError("RESOURCE", "defined text resource must use UTF8 encoding")
            if fmt in ("PCAP", "PCAPNG") and ref["encoding"] != "BINARY":
                raise ICDError("RESOURCE", "capture container must use BINARY encoding")
            if ref["encoding"] == "UTF8":
                try:
                    raw.decode("utf-8", errors="strict")
                except UnicodeError as error:
                    raise ICDError("RESOURCE", "text resource has invalid UTF8 bytes") from error
            if fmt == "ICD_JSON":
                loads(raw)
            verified[ref["resource_id"]] = raw
            evidence.append(ResourceEvidence(ref["resource_id"], digest, size, fmt))
        return tuple(evidence), verified

    def _engineering(self, raw, history, declared, model_id):
        if history["policy"]["mode"] != "REENCODE":
            raise ICDError("UNSUPPORTED", "engineering values cannot prove captured raw headers or rewrites")
        stream_by_mid = {}
        counts = {}
        observed = {}
        for stream in history["streams"]:
            if stream["direction"] != "TO_36":
                raise ICDError("AUTHORIZATION", "ENGINEERING_JSONL cannot contain feedback streams")
            counts[stream["stream_id"]] = 0
            observed[stream["stream_id"]] = set()
            for mid in stream["message_ids"]:
                if mid in stream_by_mid:
                    raise ICDError("RESOURCE", "engineering row cannot be uniquely assigned to a stream")
                stream_by_mid[mid] = stream
        records = []
        previous = -1
        lines = io.BytesIO(raw)
        while True:
            line = lines.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_LINE_BYTES or len(records) >= self.max_records:
                raise ICDError("CAPACITY", "engineering history exceeds bounded line/record capacity")
            value = loads(line)
            if type(value) is not dict or set(value) != {"offset_ns", "stimulus"}:
                raise ICDError("SCHEMA", "engineering row must contain exactly offset_ns and stimulus")
            offset = value["offset_ns"]
            if type(offset) is not str or not re.fullmatch(r"0|[1-9][0-9]{0,19}", offset) or int(offset) > UINT64_MAX:
                raise ICDError("SCHEMA", "engineering offset must be a decimal uint64 string")
            offset = int(offset)
            if offset < previous:
                raise ICDError("RESOURCE", "engineering offsets decrease")
            previous = offset
            stimulus = value["stimulus"]
            self.contract.validate_stimulus(stimulus, model_id=model_id)
            mid = stimulus["message_id"]
            self._message_ids([mid], declared)
            if mid not in stream_by_mid:
                raise ICDError("RESOURCE", "engineering message has no declared history stream")
            stream = stream_by_mid[mid]
            if int(stream["epoch_ns"]) + offset > UINT64_MAX:
                raise ICDError("RESOURCE", "history epoch plus offset exceeds uint64")
            sid = stream["stream_id"]
            counts[sid] += 1
            observed[sid].add(mid)
            records.append(EngineeringRecord(offset, sid, canonicalize(stimulus)))
        if not records:
            raise ICDError("RESOURCE", "engineering history is empty")
        for stream in history["streams"]:
            sid = stream["stream_id"]
            if counts[sid] != stream["records"] or observed[sid] != set(stream["message_ids"]):
                raise ICDError("RESOURCE", "actual history count/message IDs differ from declared stream")
        policy = history["policy"]
        if not (records[0].offset_ns <= int(policy["start_offset_ns"]) <=
                int(policy["end_offset_ns"]) <= records[-1].offset_ns):
            raise ICDError("RESOURCE", "replay interval is outside actual capture range")
        return tuple(records)

    def audit(self, inputs, resources, *, model_id, capture_bindings=None):
        if type(model_id) is not str or model_id not in self._model_ids:
            raise ICDError("MODEL", "source audit requires a model defined by the frozen catalogue")
        self.contract.validate_source_definition("SourceInputs", inputs)
        inputs = copy.deepcopy(inputs)
        input_json = canonicalize(inputs)
        snapshot = json.dumps(inputs,ensure_ascii=True,allow_nan=False,separators=(',', ':')).encode('ascii')
        if len(input_json) + len(snapshot) > MAX_INPUT_BYTES:
            raise ICDError("CAPACITY", "canonical and original source snapshots exceed bounded audit input")
        pins = self.contract.component_hashes
        if not pins or inputs["baseline_sha256"] != self.contract.baseline_sha256:
            raise ICDError("HASH", "source audit requires the externally pinned original contract")
        protocol = inputs["protocol"]
        if any(protocol[key] != pins[key] for key in ("business_schema_sha256", "wire_catalog_sha256")):
            raise ICDError("HASH", "ProtocolSource differs from verified baseline components")
        refs = list(protocol["resources"])
        for fmt in ("ICD_JSON", "DBC"):
            if not any(ref["format"] == fmt for ref in refs):
                raise ICDError("RESOURCE", "ProtocolSource must include the frozen ICD_JSON and DBC")
        declared = set(protocol["message_ids"])
        self._message_ids(protocol["message_ids"])
        history = inputs["history"]
        if capture_bindings is not None and (history is None or history["resource"]["format"] not in ("CAN_LOG", "PCAP", "PCAPNG")):
            raise ICDError("RESOURCE", "capture bindings only apply to actual capture HistorySource")
        if history is not None:
            if history["decoder_baseline_sha256"] != self.contract.baseline_sha256:
                raise ICDError("HASH", "history decoder baseline differs")
            _unique([s["stream_id"] for s in history["streams"]], "history stream ID")
            for stream in history["streams"]:
                self._message_ids(stream["message_ids"], declared, stream["direction"])
            self._policy(history["policy"], history["streams"])
            refs.append(history["resource"])
        scenario_plan = self._scenario(inputs["scenario"], history, declared, model_id)
        waveforms = () if scenario_plan is None else scenario_plan.waveforms
        evidence, blobs = self._resources(refs, resources, pins)
        parsed_protocol = ProtocolParser(self.contract).parse(protocol, blobs)
        pending = [f"PROTOCOL_PARSER:{fmt}" for fmt in parsed_protocol.pending_formats]
        pending.extend(("TOOL_AND_CONSUMER_QUALIFICATION", "RUN_CONFIGURATION_AND_BINDINGS"))
        if inputs["scenario"] is not None:
            pending.append("SCENARIO_EXECUTION_SEMANTICS")
        decoded = False
        records = ()
        complete = None
        capture = None
        decoded_capture = None
        bindings_json = None
        if history is not None:
            fmt = history["resource"]["format"]
            if fmt == "ENGINEERING_JSONL":
                records = self._engineering(blobs[history["resource"]["resource_id"]], history, declared, model_id)
                decoded = True
                complete = not any(s["lost_packets"] or s["truncated_packets"] for s in history["streams"])
                if inputs["scenario"] is not None:
                    for event in inputs["scenario"]["events"]:
                        if event["type"] == "REPLAY":
                            policy = event["policy"]
                            if policy["mode"] != "REENCODE":
                                raise ICDError("UNSUPPORTED", "engineering replay cannot prove raw header rewrites")
                            if not (records[0].offset_ns <= int(policy["start_offset_ns"]) <=
                                    int(policy["end_offset_ns"]) <= records[-1].offset_ns):
                                raise ICDError("RESOURCE", "event replay interval is outside actual capture range")
            elif fmt in ("CAN_LOG", "PCAP", "PCAPNG"):
                raw = blobs[history["resource"]["resource_id"]]
                if capture_bindings is None:
                    capture = CaptureParser(max_bytes=self.max_resource_bytes, max_packets=self.max_records).parse(raw, fmt)
                else:
                    decoder = HistoryDecoder(self.contract, max_bytes=self.max_resource_bytes, max_records=self.max_records)
                    decoded_capture = decoder.decode(raw, history, capture_bindings, model_id=model_id,
                                                     declared_ids=tuple(protocol["message_ids"]))
                    capture = decoded_capture.capture
                    records = decoded_capture.records
                    decoded = True
                    complete = decoded_capture.complete_capture
                    bindings_json = canonicalize([asdict(b) for b in capture_bindings])
                    if inputs["scenario"] is not None:
                        for event in inputs["scenario"]["events"]:
                            if event["type"] == "REPLAY":
                                decoder.check_policy(event["policy"], decoded_capture)
                incomplete = bool(capture.observed_truncated_packets or capture.observed_lost_packets or any(
                    stream["lost_packets"] or stream["truncated_packets"] for stream in history["streams"]))
                online = history["policy"]["execution_mode"] == "ONLINE" or bool(inputs["scenario"] and any(
                    event["type"] == "REPLAY" and event["policy"]["execution_mode"] == "ONLINE"
                    for event in inputs["scenario"]["events"]))
                if incomplete and online:
                    raise ICDError("RESOURCE", "actual incomplete capture cannot run ONLINE")
                if incomplete:
                    complete = False
                pending.append("HISTORY_STREAM_CLOCK_AND_FORMAL_WIRE_DECODING" if decoded_capture is None else
                               "HISTORY_CLOCK_MEASUREMENT_AND_REPLAY_AUTHORIZATION")
            else:
                pending.append(f"HISTORY_PARSER:{fmt}")
            pending.append("HISTORY_SESSION_CLOCK_RESTORE_AND_REPLAY")
        return SourceInputAudit(input_json, evidence, parsed_protocol, records, decoded, complete, capture,
                                decoded_capture, bindings_json, tuple(pending), snapshot, waveforms, scenario_plan)


def _read_bounded(path, limit, *, oversize_code="CAPACITY"):
    with Path(path).open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ICDError(oversize_code, "input file exceeds the supplied byte limit")
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--inputs-file", type=Path, required=True)
    parser.add_argument("--resource-map", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--capture-bindings", type=Path)
    args = parser.parse_args()
    try:
        contract = Contract.load(args.contract_dir, expected_sha256=args.expected_sha256)
        inputs = loads(_read_bounded(args.inputs_file, MAX_INPUT_BYTES))
        bindings = None
        if args.capture_bindings is not None:
            document = loads(_read_bounded(args.capture_bindings, 128 * 1024))
            if type(document) is not list or not 1 <= len(document) <= 100:
                raise ICDError("RESOURCE", "capture bindings file must be a bounded nonempty array")
            bindings = tuple(CaptureBinding.from_document(value) for value in document)
        paths = loads(_read_bounded(args.resource_map, 1024 * 1024))
        if type(paths) is not dict or any(type(path) is not str or not path for path in paths.values()):
            raise ICDError("RESOURCE", "resource map must contain explicit ID to path strings")
        contract.validate_source_definition("SourceInputs", inputs)
        refs = list(inputs["protocol"]["resources"])
        if inputs["history"] is not None:
            refs.append(inputs["history"]["resource"])
        blobs = {}
        total = 0
        for ref in refs:
            key = ref["resource_id"]
            if key not in paths:
                raise ICDError("RESOURCE", "resource is absent from explicit path mapping")
            size = int(ref["size_bytes"])
            total += size
            if size > MAX_RESOURCE_BYTES or total > MAX_TOTAL_BYTES:
                raise ICDError("CAPACITY", "source files exceed deployment read capacity")
            path = Path(paths[key])
            if not path.is_absolute():
                path = args.resource_map.parent / path
            blobs[key] = _read_bounded(path, size, oversize_code="RESOURCE")
        report = SourceInputAuditor(contract).audit(inputs, blobs, model_id=args.model_id, capture_bindings=bindings).report()
        print(json.dumps(report))
        return 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "execution_ready": False,
                          "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                          "detail": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
