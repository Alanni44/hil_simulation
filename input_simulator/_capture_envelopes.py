"""Bounded container checks for metadata that the original reader can discard."""

from dataclasses import dataclass
from fractions import Fraction
import struct

from icd_runtime.errors import ICDError


NS_PER_SECOND = 1_000_000_000
UINT64_MAX = (1 << 64) - 1
MAX_PACKET_BYTES = 65535
MAX_NG_SECTIONS = 100
MAX_NG_BLOCKS = 200000
MAX_NG_OPTIONS = 1024
MAX_NG_OPTION_BYTES = 65536
LINK_TYPES = frozenset({1, 227})
PCAP_MAGICS = {b"\xd4\xc3\xb2\xa1": ("<", 1000000), b"\xa1\xb2\xc3\xd4": (">", 1000000),
               b"\x4d\x3c\xb2\xa1": ("<", NS_PER_SECOND), b"\xa1\xb2\x3c\x4d": (">", NS_PER_SECOND)}


@dataclass(frozen=True)
class Envelope:
    data: bytes
    ticks: int
    rate: int
    offset_seconds: int
    interface: str
    clock_domain: str
    linktype: int | None
    wirelen: int
    direction: str = "UNSPECIFIED"
    flags: int = 0
    drops: int = 0

    @property
    def timestamp_ns(self):
        value, residue = divmod(self.ticks * NS_PER_SECOND, self.rate)
        value += self.offset_seconds * NS_PER_SECOND
        if residue or not 0 <= value <= UINT64_MAX:
            raise ICDError("RESOURCE", "capture time cannot be represented as exact uint64 nanoseconds")
        return value

    @property
    def resolution_ns(self):
        return Fraction(NS_PER_SECOND, self.rate)


def _linktype(value):
    if value not in LINK_TYPES:
        raise ICDError("UNSUPPORTED", "capture linktype is not Ethernet or SocketCAN")


def _lengths(caplen, wirelen, snaplen):
    if not (0 <= caplen <= min(snaplen, MAX_PACKET_BYTES) and caplen <= wirelen <= MAX_PACKET_BYTES and wirelen > 0):
        raise ICDError("RESOURCE", "capture packet lengths/snaplen are inconsistent")


def pcap_envelopes(raw, max_packets):
    if len(raw) < 24 or raw[:4] not in PCAP_MAGICS:
        raise ICDError("RESOURCE", "invalid PCAP header or magic")
    endian, rate = PCAP_MAGICS[raw[:4]]
    major, minor, zone, accuracy, snaplen, linktype = struct.unpack_from(endian + "HHIIII", raw, 4)
    if (major, minor, zone, accuracy) != (2, 4, 0, 0) or not 1 <= snaplen <= MAX_PACKET_BYTES:
        raise ICDError("RESOURCE", "unsupported or inconsistent PCAP version/time/snaplen")
    _linktype(linktype)
    offset, packets = 24, []
    while offset < len(raw):
        if len(raw) - offset < 16:
            raise ICDError("RESOURCE", "trailing or truncated PCAP packet header")
        seconds, subsecond, caplen, wirelen = struct.unpack_from(endian + "IIII", raw, offset)
        _lengths(caplen, wirelen, snaplen)
        if subsecond >= rate or offset + 16 + caplen > len(raw):
            raise ICDError("RESOURCE", "PCAP timestamp or packet body is inconsistent")
        if len(packets) >= max_packets:
            raise ICDError("CAPACITY", "capture packet count capacity exceeded")
        packets.append(Envelope(raw[offset + 16:offset + 16 + caplen], seconds * rate + subsecond, rate, 0,
                                "interface-0", "PCAP:0:0", linktype, wirelen))
        offset += 16 + caplen
    return tuple(packets)


def _options(raw, endian, allowed):
    if len(raw) > MAX_NG_OPTION_BYTES:
        raise ICDError("CAPACITY", "PCAPNG option byte capacity exceeded")
    offset, count, result = 0, 0, {}
    while offset < len(raw):
        if len(raw) - offset < 4:
            raise ICDError("RESOURCE", "truncated PCAPNG option header")
        code, size = struct.unpack_from(endian + "HH", raw, offset)
        stop = offset + 4 + size
        padded = stop + (-size % 4)
        if padded > len(raw):
            raise ICDError("RESOURCE", "truncated PCAPNG option value")
        if code == 0:
            if size or padded != len(raw):
                raise ICDError("RESOURCE", "invalid PCAPNG end-of-options or trailing data")
            return result
        if count >= MAX_NG_OPTIONS:
            raise ICDError("CAPACITY", "PCAPNG option count capacity exceeded")
        count += 1
        if code not in allowed:
            raise ICDError("UNSUPPORTED", "PCAPNG option is outside the supported capture profile")
        if code in result and code != 1:
            raise ICDError("RESOURCE", "ambiguous duplicate PCAPNG option")
        result[code] = raw[offset + 4:stop]
        offset = padded
    return result


def _size(options, code, size):
    if code in options and len(options[code]) != size:
        raise ICDError("RESOURCE", "PCAPNG numeric option length differs")


def pcapng_envelopes(raw, max_packets):
    if raw[:4] != b"\x0a\x0d\x0d\x0a":
        raise ICDError("RESOURCE", "PCAPNG must begin with a section header")
    offset, section, start, header_end, declared_section_length = 0, -1, 0, 0, -1
    interfaces, packets, sections, all_drops = [], [], [], 0
    per_interface_drops = {}
    endian = None
    total_packets = 0
    total_blocks = 0

    def close_section(stop):
        nonlocal all_drops
        if section < 0:
            return
        if declared_section_length != -1 and stop - header_end != declared_section_length:
            raise ICDError("RESOURCE", "PCAPNG declared section length differs from actual blocks")
        sections.append((raw[start:stop], tuple(packets)))
        all_drops += sum(max(values[0], values[1] + values[2]) for values in per_interface_drops.values())

    while offset < len(raw):
        if total_blocks >= MAX_NG_BLOCKS:
            raise ICDError("CAPACITY", "PCAPNG metadata block capacity exceeded")
        total_blocks += 1
        if len(raw) - offset < 12:
            raise ICDError("RESOURCE", "trailing or truncated PCAPNG block header")
        is_section = raw[offset:offset + 4] == b"\x0a\x0d\x0d\x0a"
        if is_section:
            if section + 1 >= MAX_NG_SECTIONS:
                raise ICDError("CAPACITY", "PCAPNG section capacity exceeded")
            close_section(offset)
            magic = raw[offset + 8:offset + 12]
            endian = {b"\x4d\x3c\x2b\x1a": "<", b"\x1a\x2b\x3c\x4d": ">"}.get(magic)
            if endian is None:
                raise ICDError("RESOURCE", "PCAPNG section byte-order magic differs")
            section += 1
            start, interfaces, packets, per_interface_drops = offset, [], [], {}
        kind, length = struct.unpack_from(endian + "II", raw, offset)
        if length < 12 or length % 4 or offset + length > len(raw):
            raise ICDError("RESOURCE", "PCAPNG block length/body is inconsistent")
        if struct.unpack_from(endian + "I", raw, offset + length - 4)[0] != length:
            raise ICDError("RESOURCE", "PCAPNG trailing block length differs")
        body = raw[offset + 8:offset + length - 4]
        if is_section:
            if len(body) < 16:
                raise ICDError("RESOURCE", "PCAPNG section is too short")
            _, major, minor, declared_section_length = struct.unpack_from(endian + "IHHq", body)
            if (major, minor) != (1, 0) or declared_section_length < -1:
                raise ICDError("RESOURCE", "unsupported PCAPNG section version/length")
            _options(body[16:], endian, {1, 2, 3, 4})
            header_end = offset + length
        elif kind == 1:
            if len(body) < 8:
                raise ICDError("RESOURCE", "PCAPNG interface block is too short")
            linktype, reserved, snaplen = struct.unpack_from(endian + "HHI", body)
            _linktype(linktype)
            if reserved or not 1 <= snaplen <= MAX_PACKET_BYTES:
                raise ICDError("RESOURCE", "PCAPNG interface fields differ")
            if len(interfaces) >= 100:
                raise ICDError("CAPACITY", "PCAPNG interface capacity exceeded")
            options = _options(body[8:], endian, {1, 2, 9, 14})
            _size(options, 9, 1)
            _size(options, 14, 8)
            exponent = options.get(9, b"\x06")[0]
            rate = (2 if exponent & 128 else 10) ** (exponent & 127)
            shift = struct.unpack(endian + "q", options[14])[0] if 14 in options else 0
            try:
                name = options.get(2, f"interface-{len(interfaces)}".encode()).decode("utf-8", errors="strict")
            except UnicodeError as error:
                raise ICDError("RESOURCE", "PCAPNG interface name is not UTF8") from error
            if not 1 <= len(name) <= 128 or any(ord(char) < 32 for char in name):
                raise ICDError("RESOURCE", "PCAPNG interface name is not bounded printable text")
            interfaces.append((linktype, snaplen, rate, shift, name))
            per_interface_drops[len(interfaces) - 1] = [0, 0, 0]
        elif kind in (5, 6):
            minimum = 20 if kind == 6 else 12
            if len(body) < minimum:
                raise ICDError("RESOURCE", "PCAPNG packet/statistics block is too short")
            interface, high, low = struct.unpack_from(endian + "III", body)
            if interface >= len(interfaces):
                raise ICDError("RESOURCE", "PCAPNG packet has no declared interface")
            linktype, snaplen, rate, shift, name = interfaces[interface]
            if kind == 5:
                options = _options(body[12:], endian, set(range(1, 9)))
                for code in range(2, 9):
                    _size(options, code, 8)
                for code, slot in ((5, 1), (7, 2)):
                    if code in options:
                        value = struct.unpack(endian + "Q", options[code])[0]
                        if value < per_interface_drops[interface][slot]:
                            raise ICDError("RESOURCE", "PCAPNG cumulative loss counter decreases")
                        per_interface_drops[interface][slot] = value
            else:
                caplen, wirelen = struct.unpack_from(endian + "II", body, 12)
                _lengths(caplen, wirelen, snaplen)
                data_end = 20 + caplen
                options_start = data_end + (-caplen % 4)
                if options_start > len(body):
                    raise ICDError("RESOURCE", "PCAPNG packet body is truncated")
                options = _options(body[options_start:], endian, {1, 2, 4})
                _size(options, 2, 4)
                _size(options, 4, 8)
                flags = struct.unpack(endian + "I", options[2])[0] if 2 in options else 0
                if flags > 2:
                    raise ICDError("UNSUPPORTED", "PCAPNG flags beyond known capture direction need qualification")
                drops = struct.unpack(endian + "Q", options[4])[0] if 4 in options else 0
                per_interface_drops[interface][0] += drops
                if total_packets >= max_packets:
                    raise ICDError("CAPACITY", "capture packet count capacity exceeded")
                total_packets += 1
                packets.append(Envelope(body[20:data_end], (high << 32) | low, rate, shift, name,
                                        f"PCAPNG:{section}:{interface}", linktype, wirelen,
                                        ("UNSPECIFIED", "INBOUND", "OUTBOUND")[flags], flags, drops))
        else:
            raise ICDError("UNSUPPORTED", "PCAPNG block is outside the timestamped capture profile")
        offset += length
    close_section(offset)
    return tuple(sections), all_drops
