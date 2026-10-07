"""Common business framing. Device/socket ownership is outside this module."""

import binascii
from dataclasses import asdict, dataclass
import struct

from .errors import ICDError
from .payload import PayloadCodec

CAN_HEADER = struct.Struct("<BBBBIIIIBBH")
UDP_HEADER = struct.Struct("<4sBBHIIIIHHHHHH")


def crc16(raw: bytes) -> int:
    return binascii.crc_hqx(raw, 0xffff)


def crc32(raw: bytes) -> int:
    return binascii.crc32(raw) & 0xffffffff


@dataclass(frozen=True, slots=True)
class Header:
    session_id: int
    sequence: int
    target_step: int
    transaction_id: int
    valid_for_ms: int


@dataclass(frozen=True, slots=True)
class CANFrame:
    arbitration_id: int
    data: bytes
    is_fd: bool = True
    bitrate_switch: bool = True
    is_extended_id: bool = False
    is_remote_frame: bool = False


@dataclass(frozen=True, slots=True)
class Fragment:
    transport: str
    direction: str
    message_id: int
    header: Header
    index: int
    count: int
    payload: bytes
    reservation_bytes: int


class WireCodec:
    def __init__(self, contract):
        self.contract = contract
        self.payload_codec = PayloadCodec(contract)
        self._rules = contract.catalogue["codecs"]
        self._can_ids = {m["can_id"]: m["id"] for m in contract.messages.values() if m["can_id"] is not None}

    def _entry(self, mid, transport, direction=None):
        entry = self.contract.entry(mid)
        if transport not in entry["transports"]:
            raise ICDError("UNSUPPORTED", "message not defined for this transport")
        if direction is not None and direction != entry["direction"]:
            raise ICDError("AUTHORIZATION", "wire message direction mismatch")
        return entry

    def encode(self, message: dict, transport: str):
        self.contract.validate_message(message)
        entry = self._entry(message["message_id"], transport)
        raw = self.payload_codec.encode(entry["id"], message["payload"])
        rules = self._rules[transport]
        chunk_bytes = rules["chunk_bytes"]
        chunks = [raw[i:i + chunk_bytes] for i in range(0, len(raw), chunk_bytes)]
        if len(chunks) > rules["max_fragments"]:
            raise ICDError("CAPACITY", "fragment limit exceeded")
        header = Header(**{key: int(value) for key, value in message["header"].items()})
        frames = []
        for index, chunk in enumerate(chunks):
            if transport == "CANFD":
                prefix = CAN_HEADER.pack(1, 0, 0, len(chunk), header.session_id, header.sequence,
                                         header.target_step, header.transaction_id, index, len(chunks), header.valid_for_ms)
                body = prefix + chunk + bytes(chunk_bytes - len(chunk))
                checksum = crc16(struct.pack("<H", entry["can_id"]) + body)
                frames.append(CANFrame(entry["can_id"], body + struct.pack("<H", checksum)))
            else:
                prefix = UDP_HEADER.pack(b"HIL1", 1, 0, 0, header.session_id, header.sequence,
                                         header.target_step, header.transaction_id, index, len(chunks), len(chunk),
                                         header.valid_for_ms, entry["id"], 0)
                frames.append(prefix + struct.pack("<I", crc32(prefix + chunk)) + chunk)
        return frames

    def _fragment(self, transport, entry, header, index, count, payload):
        rules = self._rules[transport]
        size = rules["chunk_bytes"]
        maximum = entry["max_logical_payload_bytes"]
        if not (1 <= count <= rules["max_fragments"] and 0 <= index < count and 1 <= len(payload) <= size):
            raise ICDError("FRAGMENT", "invalid fragment bounds")
        if (count - 1) * size + 1 > maximum:
            raise ICDError("FRAGMENT", "fragment count exceeds logical capacity")
        if index < count - 1 and len(payload) != size:
            raise ICDError("FRAGMENT", "short non-final fragment")
        if index == count - 1 and (count - 1) * size + len(payload) > maximum:
            raise ICDError("FRAGMENT", "final fragment exceeds logical capacity")
        if entry["encoding"] == "PACKED_LE":
            exact = entry["payload_bytes"]
            expected_count = (exact + size - 1) // size
            expected_size = min(size, exact - index * size)
            if count != expected_count or len(payload) != expected_size:
                raise ICDError("FRAGMENT", "packed fragment layout differs from exact catalogue size")
        self.contract.validate_header(entry["id"], asdict(header))
        reservation = min(count * size, maximum)
        return Fragment(transport, entry["direction"], entry["id"], header, index, count, payload, reservation)

    def rewrite(self, raw, transport: str, header: Header, *, direction=None):
        """Reframe validated fragments without touching captured business bytes.

        Header validity is structural only, not permission to send or use a session.
        """
        fragment = self.decode(raw, transport, direction=direction)
        if type(header) is not Header or any(type(v) is not int for v in asdict(header).values()):
            raise ICDError("SCHEMA", "rewrite requires a strict integer Header")
        self.contract.validate_header(fragment.message_id, asdict(header))
        data = bytearray(raw.data if transport == "CANFD" else raw)
        struct.pack_into("<IIII", data, 4 if transport == "CANFD" else 8,
                         header.session_id, header.sequence, header.target_step, header.transaction_id)
        if transport == "CANFD":
            struct.pack_into("<H", data, 62, crc16(struct.pack("<H", raw.arbitration_id) + data[:62]))
            return CANFrame(raw.arbitration_id, bytes(data))
        struct.pack_into("<I", data, 36, crc32(data[:36] + data[40:]))
        return bytes(data)

    def decode(self, raw, transport: str, *, direction=None) -> Fragment:
        if transport == "CANFD":
            if not isinstance(raw, CANFrame):
                raise ICDError("SCHEMA", "CANFrame metadata required")
            if (raw.is_fd is not True or raw.bitrate_switch is not True or raw.is_extended_id is not False
                    or raw.is_remote_frame is not False or type(raw.arbitration_id) is not int
                    or not 0 <= raw.arbitration_id <= 0x7ff):
                raise ICDError("SCHEMA", "expected standard FD+BRS data frame")
            if raw.arbitration_id not in self._can_ids:
                raise ICDError("UNSUPPORTED", "unknown formal CAN ID")
            entry = self._entry(self._can_ids[raw.arbitration_id], transport, direction)
            data = raw.data
            if type(data) is not bytes or len(data) != 64:
                raise ICDError("FRAGMENT", "CAN FD frame must contain exactly 64 bytes")
            if crc16(struct.pack("<H", raw.arbitration_id) + data[:62]) != struct.unpack_from("<H", data, 62)[0]:
                raise ICDError("CRC", "CAN application CRC mismatch")
            major, minor, flags, length, session, sequence, step, transaction, index, count, valid = CAN_HEADER.unpack_from(data)
            if (major, minor, flags) != (1, 0, 0):
                raise ICDError("VERSION", "CAN version or flags mismatch")
            if not 1 <= length <= 38 or any(data[24 + length:62]):
                raise ICDError("FRAGMENT", "CAN chunk length or zero padding invalid")
            payload = data[24:24 + length]
        elif transport == "UDP":
            if type(raw) is not bytes or not 41 <= len(raw) <= 1200:
                raise ICDError("FRAGMENT", "invalid UDP datagram length")
            (magic, major, minor, flags, session, sequence, step, transaction, index, count,
             length, valid, mid, reserved) = UDP_HEADER.unpack_from(raw)
            if (magic, major, minor, flags, reserved) != (b"HIL1", 1, 0, 0, 0):
                raise ICDError("VERSION", "UDP magic/version/flags/reserved mismatch")
            if len(raw) != 40 + length:
                raise ICDError("FRAGMENT", "UDP size differs from payload_length")
            payload = raw[40:]
            if crc32(raw[:36] + payload) != struct.unpack_from("<I", raw, 36)[0]:
                raise ICDError("CRC", "UDP application CRC mismatch")
            entry = self._entry(mid, transport, direction)
        else:
            raise ICDError("UNSUPPORTED", "unknown business transport")
        header = Header(session, sequence, step, transaction, valid)
        return self._fragment(transport, entry, header, index, count, payload)
