"""Pinned protocol import and original CAN tool frame layout, not a bus driver."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import hashlib

import cantools
from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import WireCodec


MAX_PROTOCOL_BYTES = 4 * 1024 * 1024
MAX_TOTAL_PROTOCOL_BYTES = 16 * 1024 * 1024
ARXML_NS = "http://autosar.org/schema/r4.0"


@dataclass(frozen=True)
class SignalDefinition:
    name: str
    start: int
    length: int
    byte_order: str = "little_endian"
    is_signed: bool = False
    scale: int = 1
    offset: int = 0
    minimum: int = 0

    @property
    def maximum(self):
        return (1 << self.length) - 1


@dataclass(frozen=True)
class FrameDefinition:
    message_id: int
    name: str
    can_id: int
    period_ms: int
    length: int
    is_fd: bool
    is_extended_id: bool
    signals: tuple[SignalDefinition, ...]


@dataclass(frozen=True)
class ProtocolResource:
    resource_id: str
    sha256: str
    format: str


@dataclass(frozen=True)
class ProtocolDescriptor:
    baseline_sha256: str
    resources: tuple[ProtocolResource, ...]
    frames: tuple[FrameDefinition, ...]
    parsed_formats: tuple[str, ...]
    pending_formats: tuple[str, ...]


def _unique(values, label):
    if len(values) != len(set(values)):
        raise ICDError("RESOURCE", f"duplicate {label}")


class ProtocolParser:
    def __init__(self, contract):
        self.contract = contract
        self._wire = WireCodec(contract)
        self._database = None
        self._descriptor = None
        self._declared = frozenset()
        self._expected = self._expected_frames()

    def _expected_frames(self):
        codec = self.contract.catalogue["codecs"]["CANFD"]
        signals = []
        for name, offset, size, kind, _ in codec["fields"]:
            if kind == "bytes":
                signals.extend(SignalDefinition(f"chunk_{index:02d}", (offset + index) * 8, 8)
                               for index in range(size))
            else:
                signals.append(SignalDefinition("crc16" if name == "crc" else name, offset * 8, size * 8))
        return tuple(FrameDefinition(entry["id"], entry["name"], entry["can_id"], entry["period_ms"],
                                     codec["frame_bytes"], codec["fd"], False, tuple(signals))
                     for entry in self.contract.messages.values() if "CANFD" in entry["transports"])

    def _describe_database(self, database):
        # Validate the real library objects before they can be used for any frame.
        actual = database.messages
        _unique([frame.frame_id for frame in actual], "CAN ID")
        _unique([frame.name for frame in actual], "CAN frame name")
        if len(actual) != len(self._expected):
            raise ICDError("RESOURCE", "protocol does not contain all original CAN frames")
        by_id = {frame.frame_id: frame for frame in actual}
        for expected in self._expected:
            frame = by_id.get(expected.can_id)
            if frame is None or (frame.name, frame.length, frame.is_fd, frame.is_extended_frame,
                                 frame.cycle_time or 0) != (
                    expected.name, expected.length, expected.is_fd, expected.is_extended_id, expected.period_ms):
                raise ICDError("RESOURCE", "CAN frame identity, length, FD or period differs from frozen catalogue")
            if frame.is_container or frame.is_multiplexed() or frame.unused_bit_pattern != 255:
                raise ICDError("RESOURCE", "unsupported container, multiplexing or unused-bit convention")
            _unique([signal.name for signal in frame.signals], "CAN signal name")
            if len(frame.signals) != len(expected.signals):
                raise ICDError("RESOURCE", "CAN frame signal set differs")
            signals = {signal.name: signal for signal in frame.signals}
            for definition in expected.signals:
                signal = signals.get(definition.name)
                if signal is None or (signal.start, signal.length, signal.byte_order, signal.is_signed,
                                      signal.scale, signal.offset, signal.minimum, signal.maximum) != (
                        definition.start, definition.length, definition.byte_order, definition.is_signed,
                        definition.scale, definition.offset, definition.minimum, definition.maximum):
                    raise ICDError("RESOURCE", "CAN signal layout, conversion or range differs")
                if (signal.is_float or signal.choices is not None or signal.is_multiplexer
                        or signal.multiplexer_ids is not None or signal.multiplexer_signal is not None
                        or signal.unit is not None or signal.initial is not None or signal.invalid is not None):
                    raise ICDError("RESOURCE", "unsupported signal semantics in transport-frame protocol")
        return self._expected

    def _arxml_preflight(self, raw):
        try:
            tree = SafeXML.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
            if tree.tag != f"{{{ARXML_NS}}}AUTOSAR":
                raise ValueError("only the supported AUTOSAR R4 CAN profile is accepted")
            tag = lambda name: f"{{{ARXML_NS}}}{name}"

            def one(parent, name):
                nodes = parent.findall(tag(name))
                if len(nodes) != 1:
                    raise ValueError(f"ARXML {name} must be explicit and unique")
                return nodes[0]

            def number(node):
                if node.text is None or len(node.text) > 64:
                    raise ValueError("ARXML numeric text exceeds bounded decimal length")
                value = Decimal(node.text)
                if not value.is_finite():
                    raise ValueError("ARXML numeric text must be finite")
                return value

            for name in ("UPDATE-INDICATION-BIT-POSITION", "COMPU-PHYS-TO-INTERNAL", "UNIT-REF"):
                if tree.find(f".//{tag(name)}") is not None:
                    raise ValueError(f"ARXML {name} is not supported by the frozen frame profile")
            mappings = tree.findall(f".//{tag('PDU-TO-FRAME-MAPPING')}")
            pdus = tree.findall(f".//{tag('I-SIGNAL-I-PDU')}")
            if len(mappings) != len(self._expected) or len(pdus) != len(self._expected):
                raise ValueError("ARXML requires one original PDU per CAN frame")
            for mapping in mappings:
                positions = mapping.findall(tag("START-POSITION"))
                if len(positions) > 1 or any(node.text != "0" for node in positions):
                    raise ValueError("ARXML PDU must begin at frame bit zero")
                one(mapping, "PDU-REF")
            for pdu in pdus:
                if one(pdu, "LENGTH").text != str(self.contract.catalogue["codecs"]["CANFD"]["frame_bytes"]):
                    raise ValueError("ARXML PDU length differs from complete transport frame")
            for method in tree.findall(f".//{tag('COMPU-METHOD')}"):
                if one(method, "CATEGORY").text != "LINEAR":
                    raise ValueError("ARXML requires explicit identity conversions")
                scales = one(one(method, "COMPU-INTERNAL-TO-PHYS"), "COMPU-SCALES")
                scale = one(scales, "COMPU-SCALE")
                lower, upper = one(scale, "LOWER-LIMIT"), one(scale, "UPPER-LIMIT")
                if any(node.get("INTERVAL-TYPE", "CLOSED") != "CLOSED" for node in (lower, upper)):
                    raise ValueError("ARXML transport signal ranges must be closed")
                if number(lower) != 0 or number(upper) not in {Decimal(255), Decimal(65535), Decimal(4294967295)}:
                    raise ValueError("ARXML signal range must be exact unsigned full-width integers")
                coeffs = one(scale, "COMPU-RATIONAL-COEFFS")
                numerator = one(coeffs, "COMPU-NUMERATOR").findall(tag("V"))
                denominator = one(coeffs, "COMPU-DENOMINATOR").findall(tag("V"))
                if ([number(node) for node in numerator] != [Decimal(0), Decimal(1)]
                        or [number(node) for node in denominator] != [Decimal(1)]):
                    raise ValueError("ARXML signal conversion must be exactly identity before float projection")
            # cantools defaults some unknown enums and truncates sub-ms periods;
            # reject those lossy projections instead of comparing the rounded result.
            allowed = {"PACKING-BYTE-ORDER": "MOST-SIGNIFICANT-BYTE-LAST", "CAN-ADDRESSING-MODE": "STANDARD",
                       "CAN-FRAME-RX-BEHAVIOR": "CAN-FD", "CAN-FRAME-TX-BEHAVIOR": "CAN-FD"}
            for name, value in allowed.items():
                nodes = tree.findall(f".//{{{ARXML_NS}}}{name}")
                expected_count = sum(len(f.signals) for f in self._expected) if name == "PACKING-BYTE-ORDER" else len(self._expected)
                if len(nodes) != expected_count or any(node.text != value for node in nodes):
                    raise ValueError(f"ARXML {name} is missing, ambiguous or differs")
            periods = tree.findall(f".//{{{ARXML_NS}}}TIME-PERIOD/{{{ARXML_NS}}}VALUE")
            values = [number(node) for node in periods]
            expected_periods = [Decimal(f.period_ms) / 1000 for f in self._expected if f.period_ms]
            if any(not value.is_finite() for value in values) or sorted(values) != sorted(expected_periods):
                raise ValueError("ARXML timing must exactly represent original integer-ms periods")
        except (SafeXML.ParseError, DefusedXmlException, ValueError, TypeError, InvalidOperation) as exc:
            raise ICDError("RESOURCE", "unsafe, unsupported or non-equivalent ARXML profile") from exc

    def _load_database(self, raw, fmt):
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ICDError("RESOURCE", "protocol text is not UTF8") from exc
        if fmt == "ARXML":
            self._arxml_preflight(raw)
        try:
            database = cantools.database.load_string(text, database_format=fmt.lower(), strict=True)
            self._describe_database(database)
            return database
        except ICDError:
            raise
        except Exception as exc:
            raise ICDError("RESOURCE", f"original cantools cannot parse equivalent {fmt}") from exc

    def parse(self, protocol_source, resources):
        self._database = self._descriptor = None
        self._declared = frozenset()
        self.contract.validate_source_definition("ProtocolSource", protocol_source)
        source = loads(canonicalize(protocol_source))
        pins = self.contract.component_hashes
        if not pins or any(source[key] != pins[key] for key in ("business_schema_sha256", "wire_catalog_sha256")):
            raise ICDError("HASH", "protocol requires verified original baseline components")
        _unique(source["message_ids"], "protocol message ID")
        for mid in source["message_ids"]:
            self.contract.entry(mid)
        if not isinstance(resources, Mapping):
            raise ICDError("RESOURCE", "explicit resource ID to original bytes mapping required")
        refs = source["resources"]
        _unique([ref["resource_id"] for ref in refs], "protocol resource ID")
        if any(not any(ref["format"] == fmt for ref in refs) for fmt in ("ICD_JSON", "DBC")):
            raise ICDError("RESOURCE", "original ICD_JSON and DBC are mandatory")
        total = 0
        verified = []
        for ref in refs:
            size = int(ref["size_bytes"])
            total += size
            if size > MAX_PROTOCOL_BYTES or total > MAX_TOTAL_PROTOCOL_BYTES:
                raise ICDError("CAPACITY", "protocol parser byte capacity exceeded")
            raw = resources.get(ref["resource_id"])
            if type(raw) is not bytes or len(raw) != size:
                raise ICDError("RESOURCE", "actual protocol resource missing or size differs")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != ref["sha256"]:
                raise ICDError("HASH", "protocol resource hash differs")
            pin = {"ICD_JSON": "wire_catalog_sha256", "DBC": "canfd_dbc_sha256"}.get(ref["format"])
            if pin is not None and digest != pins[pin]:
                raise ICDError("HASH", "protocol resource is not the original frozen component")
            if ref["format"] in ("ICD_JSON", "DBC", "ARXML") and ref["encoding"] != "UTF8":
                raise ICDError("RESOURCE", "protocol text requires UTF8 encoding")
            verified.append((ref, raw, digest))
        database = None
        parsed, pending, evidence = [], [], []
        for ref, raw, digest in verified:
            fmt = ref["format"]
            evidence.append(ProtocolResource(ref["resource_id"], digest, fmt))
            if fmt == "ICD_JSON":
                if loads(raw) != self.contract.catalogue:
                    raise ICDError("HASH", "actual parsed catalogue differs from original")
            elif fmt in ("DBC", "ARXML"):
                candidate = self._load_database(raw, fmt)
                if fmt == "DBC":
                    database = candidate
            else:
                if fmt not in pending:
                    pending.append(fmt)
                continue
            if fmt not in parsed:
                parsed.append(fmt)
        descriptor = ProtocolDescriptor(self.contract.baseline_sha256, tuple(evidence), self._expected,
                                        tuple(parsed), tuple(pending))
        self._descriptor = descriptor
        self._declared = frozenset(source["message_ids"])
        if not pending:
            self._database = database
        return descriptor

    def _require_parsed(self):
        if self._database is None:
            raise ICDError("STATE", "all protocol resources must be parsed before frame codec use")

    def _layout_check(self, frame):
        definition = next(f for f in self._expected if f.can_id == frame.arbitration_id)
        raw_int = int.from_bytes(frame.data, "little")
        expected = {signal.name: (raw_int >> signal.start) & signal.maximum for signal in definition.signals}
        try:
            tool_frame = self._database.get_message_by_frame_id(frame.arbitration_id)
            actual = tool_frame.decode(frame.data, decode_choices=False, scaling=False, allow_truncated=False)
            encoded = tool_frame.encode(expected, scaling=False, strict=True, padding=False)
        except Exception as exc:
            raise ICDError("RESOURCE", "original cantools frame codec failed") from exc
        if actual != expected or encoded != frame.data:
            raise ICDError("RESOURCE", "cantools bit layout differs from formal wire codec")
        return replace(frame, data=encoded)

    def encode(self, message):
        self._require_parsed()
        frames = self._wire.encode(message, "CANFD")
        if message["message_id"] not in self._declared:
            raise ICDError("RESOURCE", "message not declared by this ProtocolSource")
        return tuple(self._layout_check(frame) for frame in frames)

    def decode_frame(self, frame, *, direction=None):
        self._require_parsed()
        fragment = self._wire.decode(frame, "CANFD", direction=direction)
        if fragment.message_id not in self._declared:
            raise ICDError("RESOURCE", "message not declared by this ProtocolSource")
        self._layout_check(frame)
        return fragment
