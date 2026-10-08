"""Actual captured transport bytes, not history authorization or replay."""

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import io
import re

from can import CanutilsLogReader
from scapy.layers.can import CAN, CANFD
from scapy.layers.inet import IP, TCP, UDP, in4_chksum
from scapy.layers.l2 import Dot1Q, Ether
from scapy.utils import RawPcapReader, RawPcapNgReader, checksum

from icd_runtime.errors import ICDError
from ._capture_envelopes import Envelope, MAX_PACKET_BYTES, pcap_envelopes, pcapng_envelopes


MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_CAN_LINE_BYTES = 512
FD_LENGTHS = frozenset(range(9)) | {12, 16, 20, 24, 32, 48, 64}
CAN_LOG_LINE = re.compile(
    r"\(([0-9]{1,20}(?:\.[0-9]{1,9})?)\)[ \t]+([A-Za-z0-9_.:-]{1,128})[ \t]+"
    r"([0-9A-Fa-f]{3}|[0-9A-Fa-f]{8})#(#[0-7](?:[0-9A-Fa-f]{2})*|[rR][0-8]?|(?:[0-9A-Fa-f]{2})*)"
    r"(?:[ \t]+([rRtT]))?")


@dataclass(frozen=True)
class CapturedCAN:
    arbitration_id: int
    data: bytes
    dlc: int
    is_fd: bool
    bitrate_switch: bool
    error_state_indicator: bool
    is_extended_id: bool
    is_remote_frame: bool
    is_error_frame: bool


@dataclass(frozen=True)
class CapturedPacket:
    raw_bytes: bytes
    timestamp_ns: int
    timestamp_ticks: int
    ticks_per_second: int
    time_offset_seconds: int
    time_resolution_ns: Fraction
    clock_domain: str
    capture_interface: str
    capture_direction: str
    linktype: int | None
    wire_bytes: int
    reported_drop_count: int
    transport: str = "UNDECODED_TRUNCATED"
    payload: bytes = b""
    can: CapturedCAN | None = None
    source_ipv4: str | None = None
    destination_ipv4: str | None = None
    source_port: int | None = None
    destination_port: int | None = None
    vlan_id: int | None = None
    ip_ttl: int | None = None
    transport_checksum_verified: bool = False


@dataclass(frozen=True)
class Capture:
    format: str
    source_sha256: str
    packets: tuple[CapturedPacket, ...]
    observed_truncated_packets: int
    observed_lost_packets: int

    @property
    def loss_count_is_lower_bound(self):
        return True

    @property
    def execution_ready(self):
        return False

    @property
    def history_decoded(self):
        return False


class CaptureParser:
    def __init__(self, *, max_bytes=MAX_CAPTURE_BYTES, max_packets=100000):
        if any(type(value) is not int or value <= 0 for value in (max_bytes, max_packets)):
            raise ICDError("CAPACITY", "capture capacities must be positive integers")
        self.max_bytes = max_bytes
        self.max_packets = max_packets

    def parse(self, raw, format):
        if type(raw) is not bytes or not raw:
            raise ICDError("RESOURCE", "capture requires actual nonempty immutable bytes")
        if len(raw) > self.max_bytes:
            raise ICDError("CAPACITY", "capture byte capacity exceeded")
        try:
            if format == "CAN_LOG":
                packets, losses = self._can_log(raw), 0
            elif format == "PCAP":
                envelopes = pcap_envelopes(raw, self.max_packets)
                packets, losses = self._scapy_packets(raw, envelopes, False), 0
            elif format == "PCAPNG":
                sections, losses = pcapng_envelopes(raw, self.max_packets)
                packets = tuple(packet for section_raw, envelopes in sections
                                for packet in self._scapy_packets(section_raw, envelopes, True))
            else:
                raise ICDError("UNSUPPORTED", "format is not a supported capture container")
            if not packets:
                raise ICDError("RESOURCE", "capture has no timestamped packets")
            return Capture(format, hashlib.sha256(raw).hexdigest(), packets,
                           sum(p.wire_bytes > len(p.raw_bytes) for p in packets) if format != "CAN_LOG" else 0, losses)
        except ICDError:
            raise
        except Exception as error:
            raise ICDError("RESOURCE", "original capture/packet parser rejected the supplied bytes") from error

    def _can_log(self, raw):
        packets = []
        lines = io.BytesIO(raw)
        while True:
            line = lines.readline(MAX_CAN_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_CAN_LINE_BYTES or len(packets) >= self.max_packets:
                raise ICDError("CAPACITY", "CAN capture line/packet capacity exceeded")
            text = line.removesuffix(b"\n").removesuffix(b"\r").decode("utf-8", errors="strict")
            match = CAN_LOG_LINE.fullmatch(text)
            if match is None:
                if re.fullmatch(r"\([0-9]{1,20}(?:\.[0-9]{1,9})?\)[ \t]+[A-Za-z0-9_.:-]{1,128}[ \t]+"
                                r"(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{8})#[0-9A-Fa-f]{16}_[9A-Fa-f]"
                                r"(?:[ \t]+[rRtT])?", text):
                    raise ICDError("UNSUPPORTED", "classic CAN raw len8_dlc requires a qualified decoder")
                raise ICDError("RESOURCE", "CAN_LOG must use strict timestamped candump -L records")
            timestamp, interface, id_hex, encoded, rx_tx = match.groups()
            seconds, _, decimal = timestamp.partition(".")
            rate = 10 ** len(decimal)
            ticks = int(seconds) * rate + int(decimal or "0")
            envelope = Envelope(line, ticks, rate, 0, interface, f"CAN_LOG:{interface}", None, len(line))
            raw_id = int(id_hex, 16)
            is_fd = encoded.startswith("#")
            fd_flags = int(encoded[1]) if is_fd else 0
            data_hex = encoded[2:] if is_fd else encoded
            encoded_remote = data_hex[:1].lower() == "r"
            remote = encoded_remote or bool(raw_id & 0x40000000)
            is_error = bool(raw_id & 0x20000000)
            data = b"" if encoded_remote else bytes.fromhex(data_hex)
            dlc = int(data_hex[1:] or "0") if encoded_remote else len(data)
            extended = bool(raw_id & 0x80000000) or (len(id_hex) == 8 and not raw_id & 0x20000000)
            if ((not extended and not is_error and raw_id & 0x1fffffff > 0x7ff)
                    or dlc not in (FD_LENGTHS if is_fd else range(9)) or remote and bool(data)
                    or is_fd and remote or is_error and (is_fd or remote or dlc != 8)):
                raise ICDError("RESOURCE", "CAN capture ID/flags/data length is inconsistent")
            with CanutilsLogReader(io.StringIO(text)) as reader:
                native = tuple(reader)
            if len(native) != 1:
                raise ICDError("RESOURCE", "original CAN log reader did not produce exactly one frame")
            message = native[0]
            # The original reader collapses error frames; retain the original
            # error ID/data in the immutable analysis record, never as input.
            if not is_error and (message.arbitration_id != raw_id & 0x1fffffff or bytes(message.data) != data
                                 or message.dlc != dlc or message.is_fd != is_fd):
                raise ICDError("RESOURCE", "original CAN reader projection differs from capture bytes")
            can = CapturedCAN(raw_id & 0x1fffffff, data, dlc, is_fd, bool(fd_flags & 1), bool(fd_flags & 2),
                              extended, remote, is_error)
            direction = "UNSPECIFIED" if rx_tx is None else "INBOUND" if rx_tx.upper() == "R" else "OUTBOUND"
            packets.append(self._record(envelope, None, direction, transport="CANFD" if is_fd else "CAN",
                                        payload=data, can=can))
        return tuple(packets)

    def _record(self, envelope, linktype=None, direction=None, **details):
        return CapturedPacket(envelope.data, envelope.timestamp_ns, envelope.ticks, envelope.rate,
                              envelope.offset_seconds, envelope.resolution_ns, envelope.clock_domain,
                              envelope.interface, envelope.direction if direction is None else direction,
                              envelope.linktype if linktype is None else linktype, envelope.wirelen,
                              envelope.drops, **details)

    def _scapy_packets(self, raw, envelopes, ng):
        reader_type = RawPcapNgReader if ng else RawPcapReader
        result = []
        with reader_type(io.BytesIO(raw)) as reader:
            for envelope in envelopes:
                packet, metadata = reader._read_packet(size=MAX_PACKET_BYTES)
                if packet != envelope.data or metadata.wirelen != envelope.wirelen:
                    raise ICDError("RESOURCE", "original Scapy reader differs from checked container packet")
                if ng:
                    if (metadata.linktype, metadata.tsresol, (metadata.tshigh << 32) | metadata.tslow) != (
                            envelope.linktype, envelope.rate, envelope.ticks):
                        raise ICDError("RESOURCE", "original PCAPNG metadata differs from checked container")
                elif (reader.linktype, metadata.sec * envelope.rate + metadata.usec) != (envelope.linktype, envelope.ticks):
                    raise ICDError("RESOURCE", "original PCAP metadata differs from checked container")
                record = self._record(envelope)
                if len(packet) == envelope.wirelen:
                    record = self._socketcan(record) if envelope.linktype == 227 else self._ethernet(record)
                result.append(record)
            try:
                reader._read_packet(size=MAX_PACKET_BYTES)
            except EOFError:
                pass
            else:
                raise ICDError("RESOURCE", "original reader found unchecked additional packets")
        return tuple(result)

    def _socketcan(self, record):
        raw = record.raw_bytes
        if len(raw) not in (16, 72):
            raise ICDError("RESOURCE", "SocketCAN capture must contain complete fixed CAN or CANFD structure")
        fd = len(raw) == 72
        if not fd and raw[4] == 8 and 9 <= raw[7] <= 15:
            raise ICDError("UNSUPPORTED", "classic CAN raw len8_dlc requires a qualified decoder")
        if raw[4] not in (FD_LENGTHS if fd else range(9)) or any(raw[6:8]) or (raw[5] & ~7 if fd else raw[5]):
            raise ICDError("RESOURCE", "SocketCAN capture has invalid length/flags/reserved fields")
        native = CANFD(raw) if fd else CAN(raw)
        raw_id = int.from_bytes(raw[:4], "big")
        extended, remote, error = bool(raw_id & 0x80000000), bool(raw_id & 0x40000000), bool(raw_id & 0x20000000)
        if native.identifier != raw_id & 0x1fffffff or (not extended and not error and native.identifier > 0x7ff):
            raise ICDError("RESOURCE", "SocketCAN decoder ID/endian projection differs")
        if fd and remote or error and (fd or remote or raw[4] != 8):
            raise ICDError("RESOURCE", "SocketCAN error/RTR/FD flags or error length are inconsistent")
        data = b"" if remote else bytes(native.data)
        if not remote and data != raw[8:8 + raw[4]]:
            raise ICDError("RESOURCE", "SocketCAN decoder payload projection differs")
        can = CapturedCAN(int(native.identifier), data, raw[4], fd, bool(raw[5] & 1) if fd else False,
                          bool(raw[5] & 2) if fd else False, extended, remote, error)
        return replace(record, transport="CANFD" if fd else "CAN", payload=data, can=can)

    def _ethernet(self, record):
        raw = record.raw_bytes
        if len(raw) < 14:
            raise ICDError("RESOURCE", "Ethernet header is truncated")
        native = Ether(raw)
        layer, offset, vlan = native.payload, 14, None
        if int(native.type) == 0x8100 and len(raw) < 18:
            raise ICDError("RESOURCE", "Ethernet VLAN header is truncated")
        if isinstance(layer, Dot1Q):
            vlan, layer, offset = int(layer.vlan), layer.payload, 18
            if vlan == 4095 or len(raw) < offset:
                raise ICDError("RESOURCE", "Ethernet VLAN is invalid")
        if not isinstance(layer, IP):
            ether_type = int.from_bytes(raw[offset - 2:offset], "big")
            if ether_type == 0x0800:
                raise ICDError("RESOURCE", "declared IPv4 packet header is malformed or truncated")
            raise ICDError("UNSUPPORTED", "capture Ethernet network layer is not supported IPv4")
        ip = layer
        header_bytes, total = int(ip.ihl) * 4, int(ip.len)
        if ip.version != 4 or not 20 <= header_bytes <= 60 or not header_bytes <= total <= len(raw) - offset:
            raise ICDError("RESOURCE", "IPv4 header/total length is inconsistent")
        ip_bytes = raw[offset:offset + total]
        padding = raw[offset + total:]
        if len(raw) > max(offset + total, 64) or any(padding) or checksum(ip_bytes[:header_bytes]) != 0:
            raise ICDError("RESOURCE", "IPv4 checksum or Ethernet padding differs")
        if int(ip.flags) & 1 or int(ip.frag):
            raise ICDError("UNSUPPORTED", "fragmented IP capture requires qualified reassembly before import")
        segment = ip_bytes[header_bytes:]
        if int(ip.proto) == 17 and isinstance(ip.payload, UDP):
            udp = ip.payload
            if len(segment) < 8 or int(udp.len) != len(segment):
                raise ICDError("RESOURCE", "captured UDP length differs from IPv4 payload")
            verified = int(udp.chksum) != 0
            if verified and in4_chksum(17, ip, segment) != 0:
                raise ICDError("RESOURCE", "captured UDP checksum differs")
            transport, payload, src, dst = "UDP", segment[8:], int(udp.sport), int(udp.dport)
        elif int(ip.proto) == 6 and isinstance(ip.payload, TCP):
            tcp = ip.payload
            tcp_bytes = int(tcp.dataofs) * 4
            if not 20 <= tcp_bytes <= len(segment) or in4_chksum(6, ip, segment) != 0:
                raise ICDError("RESOURCE", "captured TCP header/length/checksum differs")
            transport, payload, src, dst, verified = "TCP_ANALYSIS_ONLY", segment[tcp_bytes:], int(tcp.sport), int(tcp.dport), True
        else:
            raise ICDError("UNSUPPORTED", "captured IPv4 transport is not UDP or analysis-only TCP")
        return replace(record, transport=transport, payload=payload, source_ipv4=str(ip.src), destination_ipv4=str(ip.dst),
                       source_port=src, destination_port=dst, vlan_id=vlan, ip_ttl=int(ip.ttl),
                       transport_checksum_verified=verified)
