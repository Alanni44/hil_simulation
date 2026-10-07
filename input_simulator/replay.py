"""Three-mode capture packet preparation, never a session or execution grant."""

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import ipaddress
import struct

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from icd_gateway.config import endpoint
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from icd_runtime.wire import CANFrame, Header, WireCodec
from .capture import MAX_CAPTURE_BYTES
from .history import HistoryDecoder


HEADER_FIELDS = {"session_id": "SESSION", "sequence": "SEQUENCE", "target_step": "TARGET_STEP",
                 "transaction_id": "TRANSACTION"}
RATES = {"0.5X": Fraction(1, 2), "1X": Fraction(1), "2X": Fraction(2), "4X": Fraction(4)}


@dataclass(frozen=True, slots=True)
class ReplayHeader:
    record_index: int
    header: Header


@dataclass(frozen=True, slots=True)
class ReplayDestination:
    input_channel: str
    output_channel: str
    source_endpoint: tuple | None = None
    receiver_endpoint: tuple | None = None


@dataclass(frozen=True, slots=True)
class ReplayPacket:
    record_index: int
    original_packet_index: int
    generated_index: int
    relative_offset_ns: Fraction
    channel_id: str
    transport: str
    wire_data: bytes | CANFrame
    source_endpoint: tuple | None
    receiver_endpoint: tuple | None
    original_capture_bytes: bytes
    capture_bytes: bytes | None
    original_sha256: str
    rebuilt_sha256: str | None
    original_wire_sha256: str
    rebuilt_wire_sha256: str
    original_payload_sha256: str
    payload_sha256: str
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedReplay:
    decoded: object
    mode: str
    policy_sha256: str
    repeat_index: int
    repeat_gap_steps: int
    packets: tuple[ReplayPacket, ...]
    feedback: tuple
    pending_checks: tuple[str, ...]
    policy_json: bytes

    @property
    def execution_ready(self):
        return False

    def require_execution_ready(self):
        raise ICDError("STATE", "prepared capture is not executable: " + ", ".join(self.pending_checks))


def _wire_bytes(value):
    return struct.pack("<H", value.arbitration_id) + value.data if type(value) is CANFrame else value


def _digest(value):
    return hashlib.sha256(value).hexdigest()


class ReplayProcessor:
    def __init__(self, contract, *, max_packets=100000, max_output_bytes=MAX_CAPTURE_BYTES):
        if any(type(n) is not int or n <= 0 for n in (max_packets, max_output_bytes)):
            raise ICDError("CAPACITY", "replay capacities must be positive integers")
        self.contract = contract
        self.wire = WireCodec(contract)
        self.decoder = HistoryDecoder(contract, max_records=max_packets)
        self.channels = {c["id"]: c for c in contract.catalogue["channels"]}
        self.max_packets = max_packets
        self.max_output_bytes = max_output_bytes

    def _destinations(self, values, selected):
        if type(values) is not tuple or len(values) > 56:
            raise ICDError("RESOURCE", "bounded immutable replay destinations required")
        result = {}
        used = {r.channel_id for _, r in selected}
        for value in values:
            if (type(value) is not ReplayDestination or type(value.input_channel) is not str
                    or type(value.output_channel) is not str or value.input_channel not in used
                    or value.output_channel not in self.channels or value.input_channel in result):
                raise ICDError("RESOURCE", "duplicate or unknown replay destination")
            medium = self.channels[value.output_channel]["type"]
            if medium not in ("ETH", "CANFD"):
                raise ICDError("UNSUPPORTED", "replay output requires a formal business channel")
            if (value.source_endpoint is None) != (value.receiver_endpoint is None):
                raise ICDError("SCHEMA", "both UDP endpoints must be explicitly provided together")
            if value.source_endpoint is not None:
                if medium != "ETH":
                    raise ICDError("SCHEMA", "CANFD cannot have UDP endpoints")
                source, receiver = endpoint(value.source_endpoint), endpoint(value.receiver_endpoint)
                for address, _ in (source, receiver):
                    ip = ipaddress.IPv4Address(address)
                    if ip.is_unspecified or int(ip) == 0xffffffff:
                        raise ICDError("SCHEMA", "replay deployment requires actual unicast endpoints")
                if source == receiver:
                    raise ICDError("SCHEMA", "source and receiver endpoints must differ")
            result[value.input_channel] = value
        return result

    def _headers(self, values, selected, captured_sessions):
        if type(values) is not tuple or len(values) != len(selected):
            raise ICDError("RESOURCE", "one explicit standard header per selected input record required")
        wanted = {i for i, _ in selected}
        result = {}
        session, last_sequence, originals, transactions, allocated_transactions = None, 0, {}, {}, {}
        for value in values:
            if (type(value) is not ReplayHeader or type(value.record_index) is not int
                    or value.record_index not in wanted or value.record_index in result):
                raise ICDError("RESOURCE", "header has duplicate or unselected record index")
            if type(value.header) is not Header or any(type(v) is not int for v in asdict(value.header).values()):
                raise ICDError("SCHEMA", "allocation requires strict immutable standard Header")
            result[value.record_index] = value.header
        for index, record in selected:
            header = result[index]
            self.contract.validate_header(record.stimulus["message_id"], asdict(header))
            if header.session_id == 0 or header.session_id in captured_sessions:
                raise ICDError("STALE_SESSION", "repeat allocation must not reuse a captured or zero session")
            if session is not None and session != header.session_id:
                raise ICDError("STALE_SESSION", "one repeat must use one allocated session")
            session = header.session_id
            message = record.message
            original_key = None if message is None else (message["header"]["session_id"], message["header"]["sequence"])
            if original_key in originals:
                old_message, old_payload, old_header = originals[original_key]
                if old_message != record.message_json or old_payload != record.payload_sha256 or old_header != header:
                    raise ICDError("SEQUENCE", "captured retries must preserve the same original and allocated identity")
            else:
                if header.sequence <= last_sequence:
                    raise ICDError("SEQUENCE", "new allocations require increasing distinct session sequences")
                last_sequence = header.sequence
                if original_key is not None:
                    originals[original_key] = (record.message_json, record.payload_sha256, header)
            if message is not None and message["header"]["transaction_id"]:
                key = (message["header"]["session_id"], message["header"]["transaction_id"])
                if key in transactions and transactions[key] != header.transaction_id:
                    raise ICDError("STATE", "one original transaction cannot be split by rebuilding")
                if key not in transactions and header.transaction_id in allocated_transactions:
                    raise ICDError("STATE", "distinct original transactions cannot merge by rebuilding")
                transactions[key] = header.transaction_id
                allocated_transactions[header.transaction_id] = key
        return result

    @staticmethod
    def _original_wire(packet):
        if packet.transport == "UDP":
            return packet.payload
        if packet.can is not None:
            c = packet.can
            return CANFrame(c.arbitration_id, c.data, c.is_fd, c.bitrate_switch, c.is_extended_id, c.is_remote_frame)
        raise ICDError("UNSUPPORTED", "captured transport has no formal replay bytes")

    def _route(self, record, destination, mode):
        channel = self.channels[record.channel_id] if destination is None else self.channels[destination.output_channel]
        transport = "UDP" if channel["type"] == "ETH" else "CANFD"
        original_transport = "UDP" if self.channels[record.channel_id]["type"] == "ETH" else "CANFD"
        if record.message is not None and transport != original_transport:
            raise ICDError("UNSUPPORTED", "captured formal replay cannot change transport")
        if transport not in self.contract.entry(record.stimulus["message_id"])["transports"]:
            raise ICDError("UNSUPPORTED", "selected output cannot carry the original business message")
        if record.message is None and (mode != "REENCODE" or destination is None):
            raise ICDError("UNSUPPORTED", "auxiliary RawBus needs explicit REENCODE business destination")
        source, receiver = None, None
        if transport == "UDP":
            source = (channel["source_ipv4"], channel["source_udp_port"])
            receiver = (channel["receiver_ipv4"], channel["business_udp_port"])
            if destination is not None and destination.source_endpoint is not None:
                source, receiver = destination.source_endpoint, destination.receiver_endpoint
        return channel["id"], transport, source, receiver

    @staticmethod
    def _ethernet(original, data, source, receiver):
        if original.transport != "UDP":
            return None  # A CAN/log capture has no Ethernet frame/L2 identity to invent.
        if data == original.payload and source == (original.source_ipv4, original.source_port) and receiver == (
                original.destination_ipv4, original.destination_port):
            return original.raw_bytes
        frame = Ether(original.raw_bytes)
        ip, udp = frame[IP], frame[UDP]
        ip.src, udp.sport = source
        ip.dst, udp.dport = receiver
        udp.remove_payload()
        udp.add_payload(data)
        for owner, fields in ((ip, ("len", "chksum")), (udp, ("len", "chksum"))):
            for field in fields:
                delattr(owner, field)
        return bytes(frame)

    def prepare(self, raw, history, bindings, *, model_id, declared_ids, headers=(), destinations=(), repeat_index=0):
        decoded = self.decoder.decode(raw, history, bindings, model_id=model_id, declared_ids=declared_ids)
        policy = history["policy"]
        mode = policy["mode"]
        if type(repeat_index) is not int or not 0 <= repeat_index < policy["repeat_count"]:
            raise ICDError("SCHEMA", "repeat index outside frozen repeat count")
        if mode == "RAW_VALIDATED" and (headers != () or destinations != ()):
            raise ICDError("STATE", "RAW_VALIDATED cannot allocate or rewrite headers/endpoints")
        start, end = int(policy["start_offset_ns"]), int(policy["end_offset_ns"])
        selected, feedback = [], []
        for index, record in enumerate(decoded.records):
            if record.completion_offset_ns < start or record.offset_ns > end:
                continue
            if record.offset_ns < start or record.completion_offset_ns > end:
                raise ICDError("FRAGMENT", "replay window cuts an original logical fragment group")
            if record.direction == "FROM_36":
                feedback.append(record)
            else:
                selected.append((index, record))
        if not selected:
            raise ICDError("RESOURCE", "replay window has no complete TO_36 records")
        captured_sessions = {r.message["header"]["session_id"] for r in decoded.records if r.message is not None}
        allocations = {} if mode == "RAW_VALIDATED" else self._headers(headers, selected, captured_sessions)
        routes = self._destinations(destinations, selected)
        packets, output_bytes = [], 0
        for index, record in selected:
            if mode == "RAW_VALIDATED" and record.message["header"]["session_id"] == 0:
                raise ICDError("STALE_SESSION", "session zero is not a current granted replay session")
            channel, transport, source, receiver = self._route(record, routes.get(record.channel_id), mode)
            header = allocations.get(index)
            payload_digest = (_digest(self.wire.payload_codec.encode(record.stimulus["message_id"], record.stimulus["payload"]))
                              if mode == "REENCODE" else record.payload_sha256)
            generated = None
            if mode == "REENCODE":
                value = {**record.stimulus, "header": asdict(header)}
                self.contract.validate_message(value, direction="TO_36", model_id=model_id)
                generated = self.wire.encode(value, transport)
            if generated is not None:
                # Match original fragment indices when the layout is unchanged;
                # a one-packet auxiliary stimulus may expand into formal fragments.
                formal = record.message is not None
                items = [(pi, self.wire.decode(self._original_wire(decoded.capture.packets[pi]), transport).index)
                         for pi in record.packet_indices] if formal else [(record.packet_indices[0], n) for n in range(len(generated))]
            else:
                items = [(pi, n) for n, pi in enumerate(record.packet_indices)]
            for pi, generated_index in items:
                original = decoded.capture.packets[pi]
                old_wire = self._original_wire(original)
                if mode == "RAW_VALIDATED":
                    data = old_wire
                elif mode == "SESSION_REBUILD":
                    data = self.wire.rewrite(old_wire, transport, header, direction="TO_36")
                else:
                    data = generated[generated_index]
                changed = []
                if record.message is not None and header is not None:
                    changed.extend(label for field, label in HEADER_FIELDS.items() if getattr(header, field) != record.message["header"][field])
                if channel != record.channel_id or (transport == "UDP" and (
                        source != (original.source_ipv4, original.source_port) or receiver != (original.destination_ipv4, original.destination_port))):
                    changed.append("SOURCE_ENDPOINT")
                capture_bytes = original.raw_bytes if mode == "RAW_VALIDATED" else (
                    self._ethernet(original, data, source, receiver) if transport == "UDP" else None)
                if _wire_bytes(data) != _wire_bytes(old_wire) or (capture_bytes is not None and capture_bytes != original.raw_bytes):
                    changed.append("CRC")
                if mode == "SESSION_REBUILD" and not set(changed) <= set(policy["rewrite_fields"]):
                    raise ICDError("AUTHORIZATION", "actual changes are not all permitted by rewrite_fields")
                epoch_offset = original.timestamp_ns - (decoded.capture.packets[record.packet_indices[0]].timestamp_ns - record.offset_ns)
                wire_bytes = _wire_bytes(data)
                output_bytes += len(wire_bytes) + (0 if capture_bytes is None or capture_bytes is original.raw_bytes else len(capture_bytes))
                if len(packets) >= self.max_packets or output_bytes > self.max_output_bytes:
                    raise ICDError("CAPACITY", "prepared replay output exceeds bounded packet/byte capacity")
                packets.append(ReplayPacket(index, pi, generated_index, Fraction(epoch_offset - start) / RATES[policy["rate"]],
                                            channel, transport, data, source, receiver, original.raw_bytes, capture_bytes,
                                            _digest(original.raw_bytes), None if capture_bytes is None else _digest(capture_bytes),
                                            _digest(_wire_bytes(old_wire)), _digest(wire_bytes), record.payload_sha256,
                                            payload_digest, tuple(changed)))
        packets.sort(key=lambda p: (p.original_packet_index, p.generated_index))
        pending = ["ACTUAL_CLOCK_MODEL_STEP_SCHEDULING", "ORIGINAL_TOOL_DRIVER_AND_CONSUMER_QUALIFICATION",
                   "BUSINESS_SEMANTIC_GUARDS_FEEDBACK_AND_CLEANUP"]
        pending.append("CURRENT_SESSION_SEQUENCE_TARGET_ENDPOINT_AUTHORIZATION" if mode == "RAW_VALIDATED" else
                       "RESET_MODEL_AND_CLEAR_QUEUES_NEW_SESSION")
        if mode != "RAW_VALIDATED":
            pending.append("ALLOCATED_HEADER_SESSION_ROLE_SEQUENCE_TARGET_ENDPOINT_AUTHORIZATION")
        return PreparedReplay(decoded, mode, _digest(canonicalize(policy)), repeat_index, policy["repeat_gap_steps"],
                              tuple(packets), tuple(feedback), tuple(pending), canonicalize(policy))
