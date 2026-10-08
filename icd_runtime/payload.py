"""Catalogue-ordered engineering payload serialization."""

import re
import struct

from .errors import ICDError
from .json_codec import canonicalize, loads

FORMATS = {"f64le": "d", "u32le": "I", "u16le": "H", "u8bool": "B", "u8enum": "B"}


def _format(field):
    match = re.fullmatch(r"([a-z0-9]+)(?:\[([0-9]+)\])?", field["type"])
    if not match or match[1] not in FORMATS:
        raise ICDError("VERSION", "unsupported frozen field encoding")
    count = int(match[2] or "1")
    return "<" + str(count) + FORMATS[match[1]], bool(match[2])


class PayloadCodec:
    def __init__(self, contract):
        self.contract = contract

    def encode(self, message_id: int, payload: dict) -> bytes:
        entry = self.contract.entry(message_id)
        self.contract.validate_payload(message_id, payload)
        if entry["encoding"] == "RFC8785_JSON_UTF8":
            raw = canonicalize(payload)
        else:
            raw = bytearray(entry["payload_bytes"])
            for field in entry["fields"]:
                value = payload[field["name"]]
                fmt, array = _format(field)
                if field["type"] == "u8enum":
                    value = field["enum_codes"][value]
                elif field["type"] == "u8bool":
                    value = int(value)
                elif field["type"] in ("u16le", "u32le"):
                    value = int(value)
                struct.pack_into(fmt, raw, field["offset"], *(value if array else [value]))
            raw = bytes(raw)
        if len(raw) > entry["max_logical_payload_bytes"]:
            raise ICDError("CAPACITY", "logical payload exceeds frozen message limit")
        return raw

    def decode(self, message_id: int, raw: bytes) -> dict:
        entry = self.contract.entry(message_id)
        if type(raw) is not bytes or not 0 < len(raw) <= entry["max_logical_payload_bytes"]:
            raise ICDError("SCHEMA", "invalid logical payload length")
        if entry["encoding"] == "RFC8785_JSON_UTF8":
            payload = loads(raw)
            if canonicalize(payload) != raw:
                raise ICDError("SCHEMA", "wire JSON is not RFC8785 canonical")
        else:
            if len(raw) != entry["payload_bytes"]:
                raise ICDError("SCHEMA", "packed payload requires exact length")
            payload = {}
            for field in entry["fields"]:
                fmt, array = _format(field)
                values = struct.unpack_from(fmt, raw, field["offset"])
                value = list(values) if array else values[0]
                if field["type"] == "u8bool":
                    if value not in (0, 1):
                        raise ICDError("SCHEMA", "boolean byte must be 0 or 1")
                    value = bool(value)
                elif field["type"] == "u8enum":
                    reverse = {v: k for k, v in field["enum_codes"].items()}
                    if value not in reverse:
                        raise ICDError("SCHEMA", "unknown enum code")
                    value = reverse[value]
                payload[field["name"]] = value
        self.contract.validate_payload(message_id, payload)
        return payload
