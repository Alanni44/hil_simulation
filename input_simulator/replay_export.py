"""Complete original-tool capture resources, never an execution authorization."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import io
import ipaddress
import os
from pathlib import Path
import re

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether
from scapy.utils import RawPcapWriter

from icd_gateway.config import endpoint
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import CANFrame, WireCodec
from .capture import CaptureParser, MAX_CAPTURE_BYTES
from .replay import HEADER_FIELDS, PreparedReplay, ReplayHeader, ReplayPacket, ReplayProcessor, RATES, _wire_bytes


NS = 1_000_000_000
INTERFACE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}")
MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ExportBinding:
    channel_id: str
    interface: str
    source_mac: str | None = None
    destination_mac: str | None = None


@dataclass(frozen=True, slots=True)
class ExportFile:
    name: str
    channel_id: str
    interface: str
    format: str
    data: bytes
    sha256: str
    tool_timing_compatible: bool | None


@dataclass(frozen=True, slots=True)
class ReplayExport:
    files: tuple[ExportFile, ...]
    report_json: bytes

    @property
    def execution_ready(self):
        return False

    def report(self):
        return loads(self.report_json)

    def write_new_directory(self, path):
        if (type(self.files) is not tuple or not 1 <= len(self.files) <= 56
                or type(self.report_json) is not bytes or len(self.report_json) > MAX_CAPTURE_BYTES):
            raise ICDError("RESOURCE", "bounded immutable export package required")
        report = self.report()
        if (report.get("execution_ready") is not False
                or report.get("status") != "REPLAY_RESOURCES_EXPORTED_NOT_EXECUTABLE"
                or type(report.get("files")) is not list or len(report["files"]) != len(self.files)):
            raise ICDError("RESOURCE", "export manifest cannot claim execution or omit files")
        names, size = set(), len(self.report_json)
        for item, descriptor in zip(self.files, report["files"]):
            if (type(item) is not ExportFile or type(item.name) is not str
                    or re.fullmatch(r"(?:ETH_[0-3]\.pcap|CANFD_[0-3]\.log)", item.name) is None
                    or item.name in names or type(item.data) is not bytes
                    or descriptor.get("name") != item.name or descriptor.get("channel_id") != item.channel_id
                    or descriptor.get("interface") != item.interface or descriptor.get("format") != item.format
                    or descriptor.get("sha256") != item.sha256 or item.sha256 != _hash(item.data)
                    or descriptor.get("size_bytes") != len(item.data)):
                raise ICDError("RESOURCE", "export file/manifest identity, path or content differs")
            names.add(item.name)
            size += len(item.data)
        if size > MAX_CAPTURE_BYTES:
            raise ICDError("CAPACITY", "export package exceeds persistent byte bound")
        try:
            target = Path(path)
            target.mkdir(parents=False, exist_ok=False)
            for item in self.files:
                destination = target / item.name
                with destination.open("xb") as stream:
                    stream.write(item.data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if destination.read_bytes() != item.data:
                    raise OSError("export file readback differs from frozen resource")
            pending = target / "manifest.pending.json"
            with pending.open("xb") as stream:
                stream.write(self.report_json)
                stream.flush()
                os.fsync(stream.fileno())
            if pending.read_bytes() != self.report_json:
                raise OSError("export manifest readback differs")
            manifest = target / "manifest.json"
            # No-overwrite publication after durable file/manifest readback.
            # Retain the pending link so no failing cleanup follows publication.
            os.link(pending, manifest)
            return manifest
        except (OSError, TypeError, ValueError) as error:
            raise ICDError("RESOURCE", "exclusive export persistence failed; incomplete owned directory retained") from error


class ReplayExporter:
    def __init__(self, contract, *, max_packets=100000, max_bytes=MAX_CAPTURE_BYTES):
        if (type(max_packets) is not int or not 1 <= max_packets <= 100000
                or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CAPTURE_BYTES):
            raise ICDError("CAPACITY", "bounded export packet and byte limits required")
        self.contract = contract
        self.wire = WireCodec(contract)
        self.channels = {c["id"]: c for c in contract.catalogue["channels"]}
        self.max_packets, self.max_bytes = max_packets, max_bytes

    def _bindings(self, prepared, bindings):
        if type(bindings) is not tuple or not 1 <= len(bindings) <= 56:
            raise ICDError("RESOURCE", "explicit immutable per-channel output bindings required")
        result, interfaces = {}, set()
        for b in bindings:
            if (type(b) is not ExportBinding or type(b.channel_id) is not str
                    or b.channel_id not in self.channels or b.channel_id in result
                    or type(b.interface) is not str or INTERFACE.fullmatch(b.interface) is None
                    or b.interface in interfaces):
                raise ICDError("RESOURCE", "unknown/duplicate channel or unsafe/duplicate output interface")
            if (b.source_mac is None) != (b.destination_mac is None):
                raise ICDError("RESOURCE", "both Ethernet MAC identities must be explicitly provided")
            if b.source_mac is not None:
                for value in (b.source_mac, b.destination_mac):
                    if type(value) is not str or MAC.fullmatch(value) is None:
                        raise ICDError("RESOURCE", "explicit Ethernet MAC identity is invalid")
                    raw = bytes.fromhex(value.replace(":", ""))
                    if raw == b"\x00" * 6 or raw[0] & 1:
                        raise ICDError("RESOURCE", "output Ethernet identity must be nonzero unicast")
            result[b.channel_id] = b
            interfaces.add(b.interface)
        if set(result) != {p.channel_id for p in prepared.packets}:
            raise ICDError("RESOURCE", "bindings must cover exactly the prepared output channels")
        return result

    def _packet(self, prepared, p, policy):
        if (type(p) is not ReplayPacket or type(p.record_index) is not int or type(p.original_packet_index) is not int
                or type(p.generated_index) is not int or p.generated_index < 0
                or not 0 <= p.record_index < len(prepared.decoded.records)
                or not 0 <= p.original_packet_index < len(prepared.decoded.capture.packets)):
            raise ICDError("RESOURCE", "invalid original record/packet identity")
        record = prepared.decoded.records[p.record_index]
        original = prepared.decoded.capture.packets[p.original_packet_index]
        if record.direction != "TO_36" or p.original_packet_index not in record.packet_indices:
            raise ICDError("RESOURCE", "feedback or unrelated original packet cannot be exported")
        medium = self.channels.get(p.channel_id, {}).get("type")
        if ((p.transport, medium) not in (("UDP", "ETH"), ("CANFD", "CANFD"))
                or type(p.wire_data) is not (bytes if p.transport == "UDP" else CANFrame)):
            raise ICDError("RESOURCE", "export transport differs from formal output channel")
        old = ReplayProcessor._original_wire(original)
        if p.transport == "UDP":
            try:
                source, receiver = endpoint(p.source_endpoint), endpoint(p.receiver_endpoint)
                if source == receiver or any(ipaddress.IPv4Address(v[0]).is_unspecified
                        or int(ipaddress.IPv4Address(v[0])) == 0xffffffff for v in (source, receiver)):
                    raise ICDError("RESOURCE", "actual distinct unicast UDP endpoints required")
            except ICDError as error:
                raise ICDError("RESOURCE", "export deployment endpoint differs from approved route rules") from error
        elif p.source_endpoint is not None or p.receiver_endpoint is not None:
            raise ICDError("RESOURCE", "CAN export cannot have UDP endpoint identity")
        if prepared.mode == "RAW_VALIDATED" and (p.channel_id != record.channel_id
                or (p.transport == "UDP" and (p.source_endpoint != (original.source_ipv4, original.source_port)
                    or p.receiver_endpoint != (original.destination_ipv4, original.destination_port)))):
            raise ICDError("RESOURCE", "RAW replay cannot relabel channels or rewrite original endpoints")
        if (p.original_capture_bytes != original.raw_bytes or p.original_sha256 != _hash(original.raw_bytes)
                or p.original_wire_sha256 != _hash(_wire_bytes(old))
                or p.rebuilt_wire_sha256 != _hash(_wire_bytes(p.wire_data))
                or p.original_payload_sha256 != record.payload_sha256):
            raise ICDError("RESOURCE", "prepared source or original/wire hashes differ")
        try:
            f = self.wire.decode(p.wire_data, p.transport)
            mid = record.stimulus["message_id"]
            if f.message_id != mid or f.direction != "TO_36":
                raise ICDError("RESOURCE", "exported business identity/direction differs")
            if prepared.mode == "RAW_VALIDATED":
                expected = old
                digest = record.payload_sha256
            elif prepared.mode == "SESSION_REBUILD":
                expected = self.wire.rewrite(old, p.transport, f.header, direction="TO_36")
                digest = record.payload_sha256
            else:
                value = {**record.stimulus, "header": asdict(f.header)}
                self.contract.validate_message(value, direction="TO_36")
                generated = self.wire.encode(value, p.transport)
                expected = generated[p.generated_index]
                if p.generated_index != f.index:
                    raise ICDError("RESOURCE", "generated fragment index differs from actual wire")
                digest = _hash(self.wire.payload_codec.encode(mid, record.stimulus["payload"]))
            if expected != p.wire_data or digest != p.payload_sha256:
                raise ICDError("RESOURCE", "exported original business bytes differ from selected replay mode")
        except (ICDError, IndexError, TypeError, ValueError) as error:
            raise ICDError("RESOURCE", "invalid or modified prepared business packet") from error
        if p.capture_bytes is not None:
            if type(p.capture_bytes) is not bytes or p.rebuilt_sha256 != _hash(p.capture_bytes):
                raise ICDError("RESOURCE", "prepared capture frame hash differs")
            if p.transport == "CANFD" and (prepared.mode != "RAW_VALIDATED" or p.capture_bytes != original.raw_bytes):
                raise ICDError("RESOURCE", "only RAW CAN carries unchanged original capture bytes")
            if p.transport == "UDP" and p.capture_bytes != ReplayProcessor._ethernet(original, p.wire_data, p.source_endpoint, p.receiver_endpoint):
                raise ICDError("RESOURCE", "Ethernet bytes must be the original or permitted upstream reconstruction")
        elif p.rebuilt_sha256 is not None:
            raise ICDError("RESOURCE", "absent Ethernet frame has inconsistent hash")
        elif original.transport == "UDP" and p.transport == "UDP":
            raise ICDError("RESOURCE", "original Ethernet capture cannot be discarded and replaced by invented L2")
        changed = []
        if record.message is not None and prepared.mode != "RAW_VALIDATED":
            changed.extend(label for field, label in HEADER_FIELDS.items() if getattr(f.header, field) != record.message["header"][field])
        if p.channel_id != record.channel_id or (p.transport == "UDP" and (
                p.source_endpoint != (original.source_ipv4, original.source_port)
                or p.receiver_endpoint != (original.destination_ipv4, original.destination_port))):
            changed.append("SOURCE_ENDPOINT")
        if _wire_bytes(p.wire_data) != _wire_bytes(old) or (p.capture_bytes is not None and p.capture_bytes != original.raw_bytes):
            changed.append("CRC")
        if p.changed_fields != tuple(changed) or (prepared.mode == "SESSION_REBUILD" and not set(changed) <= set(policy["rewrite_fields"])):
            raise ICDError("RESOURCE", "actual changes differ from evidence or allowed rewrite fields")
        return record, original

    @staticmethod
    def _time(p, epoch):
        value = p.relative_offset_ns
        if type(value) is not Fraction or value < 0:
            raise ICDError("RESOURCE", "nonnegative exact Fraction replay time required")
        if value.denominator != 1:
            raise ICDError("UNSUPPORTED", "capture files cannot represent fractional nanoseconds exactly")
        timestamp = epoch + value.numerator
        if timestamp // NS >= 1 << 32:
            raise ICDError("SCHEMA", "capture seconds exceed uint32 file range")
        return timestamp

    def _ethernet(self, p, binding):
        if p.capture_bytes is not None:
            if binding.source_mac is not None:
                raise ICDError("RESOURCE", "existing Ethernet L2 identity cannot be silently rewritten")
            return p.capture_bytes
        if binding.source_mac is None:
            raise ICDError("RESOURCE", "auxiliary conversion requires explicit Ethernet source/destination MAC")
        try:
            source, receiver = p.source_endpoint, p.receiver_endpoint
            return bytes(Ether(src=binding.source_mac, dst=binding.destination_mac)
                         / IP(src=source[0], dst=receiver[0])
                         / UDP(sport=source[1], dport=receiver[1]) / p.wire_data)
        except (TypeError, ValueError, IndexError) as error:
            raise ICDError("RESOURCE", "explicit UDP endpoint identity is invalid") from error

    def export(self, prepared, bindings, *, epoch_ns):
        if type(prepared) is not PreparedReplay or prepared.mode not in ("RAW_VALIDATED", "REENCODE", "SESSION_REBUILD"):
            raise ICDError("RESOURCE", "original PreparedReplay required")
        if type(epoch_ns) is not int or not 0 <= epoch_ns < (1 << 32) * NS:
            raise ICDError("SCHEMA", "explicit exact nonnegative uint32-second export epoch required")
        if type(prepared.packets) is not tuple or not 1 <= len(prepared.packets) <= self.max_packets:
            raise ICDError("CAPACITY", "bounded nonempty prepared replay packet tuple required")
        if type(prepared.policy_json) is not bytes or _hash(prepared.policy_json) != prepared.policy_sha256:
            raise ICDError("RESOURCE", "original frozen replay policy evidence required")
        policy = loads(prepared.policy_json)
        self.contract.validate_source_definition("ReplayPolicy", policy)
        if (prepared.mode != policy["mode"] or prepared.repeat_gap_steps != policy["repeat_gap_steps"]
                or type(prepared.repeat_index) is not int or not 0 <= prepared.repeat_index < policy["repeat_count"]):
            raise ICDError("RESOURCE", "prepared mode/repeat differs from original replay policy")
        outputs = self._bindings(prepared, bindings)
        groups, identities, orders, logical_headers, samples = {}, defaultdict(list), [], {}, {}
        total, last = 0, None
        for p in prepared.packets:
            record, original = self._packet(prepared, p, policy)
            fragment = self.wire.decode(p.wire_data, p.transport)
            identity = (fragment.header, fragment.message_id, fragment.count, p.channel_id)
            if p.record_index in logical_headers and logical_headers[p.record_index] != identity:
                raise ICDError("RESOURCE", "one logical group cannot export mixed headers/layout/channels")
            logical_headers[p.record_index] = identity
            samples.setdefault(p.record_index, p)
            key = (p.original_packet_index, p.generated_index)
            if last is not None and key <= last:
                raise ICDError("RESOURCE", "prepared packet order/identity differs from original file")
            last = key
            identities[p.record_index].append(key)
            binding = outputs[p.channel_id]
            timestamp = self._time(p, epoch_ns)
            origin = prepared.decoded.capture.packets[record.packet_indices[0]].timestamp_ns - record.offset_ns
            expected_offset = Fraction(original.timestamp_ns - origin - int(policy["start_offset_ns"])) / RATES[policy["rate"]]
            if p.relative_offset_ns != expected_offset:
                raise ICDError("RESOURCE", "prepared time differs from actual capture and original rate/window")
            if p.channel_id not in groups:
                groups[p.channel_id] = (binding, [], [])
                orders.append(p.channel_id)
            _, packets, indices = groups[p.channel_id]
            if p.transport == "UDP":
                raw = self._ethernet(p, binding)
                encoded_size = len(raw) + 16
            else:
                if binding.source_mac is not None:
                    raise ICDError("RESOURCE", "CAN log cannot have Ethernet identity")
                c = p.wire_data
                esi = original.can.error_state_indicator if original.can is not None else False
                flags = 4 | int(c.bitrate_switch) | (int(esi) << 1)
                sec, ns = divmod(timestamp, NS)
                raw = f"({sec}.{ns:09d}) {binding.interface} {c.arbitration_id:03X}##{flags:X}{c.data.hex().upper()} T\n".encode("ascii")
                encoded_size = len(raw)
            total += encoded_size
            if total + 24 * len(groups) > self.max_bytes:
                raise ICDError("CAPACITY", "export resource byte capacity exceeded")
            packets.append((timestamp, raw, p))
            indices.append({"record_index": p.record_index, "original_packet_index": p.original_packet_index,
                            "generated_index": p.generated_index, "timestamp_ns": str(timestamp),
                            "relative_offset_ns": str(p.relative_offset_ns.numerator),
                            "original_capture_sha256": p.original_sha256, "original_wire_sha256": p.original_wire_sha256,
                            "rebuilt_wire_sha256": p.rebuilt_wire_sha256, "original_payload_sha256": p.original_payload_sha256,
                            "payload_sha256": p.payload_sha256, "changed_fields": list(p.changed_fields)})
        start, end = int(policy["start_offset_ns"]), int(policy["end_offset_ns"])
        selected = [(i, r) for i, r in enumerate(prepared.decoded.records)
                    if r.direction == "TO_36" and r.completion_offset_ns >= start and r.offset_ns <= end]
        if (set(identities) != {i for i, _ in selected}
                or any(r.offset_ns < start or r.completion_offset_ns > end for _, r in selected)):
            raise ICDError("RESOURCE", "export must include every complete selected input record and no cut group")
        if prepared.mode != "RAW_VALIDATED":
            allocations = tuple(ReplayHeader(i, logical_headers[i][0]) for i, _ in selected)
            captured_sessions = {r.message["header"]["session_id"] for r in prepared.decoded.records if r.message is not None}
            try:
                ReplayProcessor(self.contract)._headers(allocations, selected, captured_sessions)
            except ICDError as error:
                raise ICDError("RESOURCE", "export allocation differs from original replay identity rules") from error
        for index, seen in identities.items():
            record = prepared.decoded.records[index]
            if prepared.mode == "REENCODE":
                sample = samples[index]
                if record.message is None:
                    f = self.wire.decode(sample.wire_data, sample.transport)
                    expected = [(record.packet_indices[0], n) for n in range(f.count)]
                else:
                    expected = [(pi, self.wire.decode(ReplayProcessor._original_wire(prepared.decoded.capture.packets[pi]), sample.transport).index)
                                for pi in record.packet_indices]
            else:
                expected = [(pi, n) for n, pi in enumerate(record.packet_indices)]
            if seen != expected:
                raise ICDError("RESOURCE", "export would omit/duplicate part of an original logical group")
        files, file_reports = [], []
        for channel in orders:
            binding, packets, indices = groups[channel]
            udp = packets[0][2].transport == "UDP"
            if udp:
                output = io.BytesIO()
                writer = RawPcapWriter(output, linktype=1, nano=True, endianness="<", snaplen=65535)
                writer.write_header(None)
                for timestamp, raw, _ in packets:
                    seconds, nano = divmod(timestamp, NS)
                    writer.write_packet(raw, sec=seconds, usec=nano, caplen=len(raw), wirelen=len(raw))
                writer.flush()
                data = output.getvalue()
                writer.close()
                fmt, timing = "PCAP", None
            else:
                data = b"".join(raw for _, raw, _ in packets)
                fmt = "CAN_LOG"
                timing = (all((timestamp - packets[0][0]) % 1000 == 0 for timestamp, _, _ in packets)
                          and all(a[0] <= b[0] for a, b in zip(packets, packets[1:])))
            parsed = CaptureParser(max_packets=self.max_packets).parse(data, fmt)
            for actual, (timestamp, _, p) in zip(parsed.packets, packets):
                if actual.timestamp_ns != timestamp or (udp and (actual.transport != "UDP" or actual.vlan_id is not None
                        or actual.payload != p.wire_data
                        or (actual.source_ipv4, actual.source_port) != p.source_endpoint
                        or (actual.destination_ipv4, actual.destination_port) != p.receiver_endpoint)):
                    raise ICDError("RESOURCE", "exported capture differs from exact prepared bytes/endpoints/time")
                if not udp and (actual.can.data != p.wire_data.data or actual.can.arbitration_id != p.wire_data.arbitration_id
                                or not actual.can.is_fd or actual.can.bitrate_switch != p.wire_data.bitrate_switch):
                    raise ICDError("RESOURCE", "exported CAN log differs from prepared FD wire")
            name = channel + (".pcap" if udp else ".log")
            item = ExportFile(name, channel, binding.interface, fmt, data, _hash(data), timing)
            files.append(item)
            file_reports.append({"name": name, "channel_id": channel, "interface": binding.interface, "format": fmt,
                                 "sha256": item.sha256, "size_bytes": len(data), "packets": indices,
                                 "tool_timing_compatible": timing,
                                 "tool_time_resolution_ns": None if udp else 1000})
        report = {"status": "REPLAY_RESOURCES_EXPORTED_NOT_EXECUTABLE", "execution_ready": False,
                  "baseline_sha256": self.contract.baseline_sha256, "mode": prepared.mode,
                  "source_capture_sha256": prepared.decoded.capture.source_sha256,
                  "policy_sha256": prepared.policy_sha256, "policy": policy, "repeat_index": prepared.repeat_index,
                  "repeat_gap_steps": prepared.repeat_gap_steps, "epoch_ns": str(epoch_ns),
                  "feedback_records_not_transmitted": len(prepared.feedback), "files": file_reports,
                  "pending_checks": list(prepared.pending_checks) + ["ORIGINAL_TOOL_FILE_TIMING_QUALIFICATION", "ACTUAL_SEND_AUTHORIZATION_AND_PROCESS_LIFECYCLE"],
                  "produces_e1_e2_e3": False}
        encoded = canonicalize(report)
        if sum(len(f.data) for f in files) + len(encoded) > self.max_bytes:
            raise ICDError("CAPACITY", "export resources plus manifest exceed byte capacity")
        return ReplayExport(tuple(files), encoded)
