"""Explicit offline history association and original business decoding, not replay."""

from dataclasses import dataclass
import hashlib

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame, WireCodec
from .capture import Capture, CaptureParser, MAX_CAPTURE_BYTES


@dataclass(frozen=True)
class CaptureBinding:
    stream_id: str
    channel_id: str
    clock_domain: str
    capture_interface: str
    clock_id: str
    raw_to36_capture_direction: str | None = None

    @classmethod
    def from_document(cls, value):
        keys = {"stream_id", "channel_id", "clock_domain", "capture_interface", "clock_id",
                "raw_to36_capture_direction"}
        if type(value) is not dict or set(value) != keys:
            raise ICDError("RESOURCE", "capture binding requires exactly the closed local deployment fields")
        result = cls(**value)
        result.validate()
        return result

    def validate(self):
        for value in (self.stream_id, self.channel_id, self.clock_domain, self.capture_interface, self.clock_id):
            if type(value) is not str or not 1 <= len(value) <= 128 or any(ord(c) < 32 for c in value):
                raise ICDError("RESOURCE", "capture binding identities must be bounded printable strings")
        if self.raw_to36_capture_direction not in (None, "INBOUND", "OUTBOUND"):
            raise ICDError("RESOURCE", "raw bus capture point direction must be explicit INBOUND or OUTBOUND")


@dataclass(frozen=True)
class HistoryRecord:
    offset_ns: int
    completion_offset_ns: int
    stream_id: str
    channel_id: str
    direction: str
    clock_domain: str
    clock_id: str
    packet_indices: tuple[int, ...]
    message_json: bytes | None
    stimulus_json: bytes | None
    payload_sha256: str
    wire_sha256: str

    @property
    def message(self):
        return None if self.message_json is None else loads(self.message_json)

    @property
    def stimulus(self):
        return None if self.stimulus_json is None else loads(self.stimulus_json)


@dataclass(frozen=True)
class DecodedHistory:
    capture: Capture
    records: tuple[HistoryRecord, ...]
    clock_ids: tuple[str, ...]
    complete_capture: bool | None

    @property
    def history_decoded(self):
        return True

    @property
    def execution_ready(self):
        return False

    @property
    def clock_measured(self):
        return False


class HistoryDecoder:
    def __init__(self, contract, *, max_bytes=MAX_CAPTURE_BYTES, max_records=100000):
        if type(max_records) is not int or max_records <= 0:
            raise ICDError("CAPACITY", "history record capacity must be a positive integer")
        self.contract = contract
        self.parser = CaptureParser(max_bytes=max_bytes, max_packets=max_records)
        self.max_records = max_records
        self.wire = WireCodec(contract)
        self.channels = {c["id"]: c for c in contract.catalogue["channels"]}

    def _bindings(self, bindings, streams, capture):
        if type(bindings) is not tuple or not 1 <= len(bindings) <= 100:
            raise ICDError("RESOURCE", "explicit bounded immutable capture bindings required")
        stream_map = {s["stream_id"]: s for s in streams}
        if len(stream_map) != len(streams):
            raise ICDError("RESOURCE", "duplicate history stream ID")
        domains = {(p.clock_domain, p.capture_interface) for p in capture.packets}
        by_domain, seen, clocks = {}, set(), {}
        for b in bindings:
            if type(b) is not CaptureBinding:
                raise ICDError("RESOURCE", "capture binding must use the explicit local deployment type")
            b.validate()
            key = (b.clock_domain, b.capture_interface)
            identity = (key, b.stream_id)
            if b.stream_id not in stream_map or b.channel_id not in self.channels or key not in domains or identity in seen:
                raise ICDError("RESOURCE", "capture binding has unknown, absent or duplicate stream/channel/domain")
            seen.add(identity)
            stream = stream_map[b.stream_id]
            medium = self.channels[b.channel_id]["type"]
            if stream["original_channel"] != ("ETHERNET" if medium == "ETH" else medium):
                raise ICDError("RESOURCE", "capture binding medium differs from declared original channel")
            if medium not in ("CAN", "CANFD", "ETH"):
                raise ICDError("UNSUPPORTED", "capture history has no decoder for this physical medium")
            clock = (stream["clock"], int(stream["epoch_ns"]))
            if b.clock_id in clocks and clocks[b.clock_id] != clock:
                raise ICDError("CLOCK_UNSYNC", "same clock identity has conflicting kind or epoch")
            clocks[b.clock_id] = clock
            peers = by_domain.setdefault(key, [])
            if peers and (peers[0].channel_id, peers[0].clock_id) != (b.channel_id, b.clock_id):
                raise ICDError("RESOURCE", "one capture domain cannot ambiguously name different channels or clocks")
            peers.append(b)
        if set(by_domain) != domains or {b.stream_id for b in bindings} != set(stream_map):
            raise ICDError("RESOURCE", "all observed capture domains and declared streams require bindings")
        if len(clocks) != 1:
            raise ICDError("CLOCK_UNSYNC", "independent clocks need an explicit qualified common timeline before replay-window decoding")
        return stream_map, by_domain, tuple(clocks)

    def _select(self, candidates, streams, mid, direction):
        matching = [b for b in candidates if mid in streams[b.stream_id]["message_ids"]]
        if len(matching) != 1:
            raise ICDError("RESOURCE", "decoded message has absent or ambiguous history stream")
        b = matching[0]
        if streams[b.stream_id]["direction"] != direction:
            raise ICDError("AUTHORIZATION", "decoded direction differs from declared history stream")
        return b

    def _udp_direction(self, packet, channel, *, raw=False):
        if packet.vlan_id is not None:
            raise ICDError("AUTHORIZATION", "frozen deployment requires untagged Ethernet business/raw capture")
        endpoint = (packet.source_ipv4, packet.destination_ipv4, packet.source_port, packet.destination_port)
        forward = (channel["source_ipv4"], channel["receiver_ipv4"], channel["source_udp_port"],
                   36150 if raw else channel["business_udp_port"])
        reverse = (channel["receiver_ipv4"], channel["source_ipv4"], channel["business_udp_port"], channel["feedback_udp_port"])
        if endpoint == forward:
            return "TO_36"
        if not raw and endpoint == reverse:
            return "FROM_36"
        raise ICDError("AUTHORIZATION", "captured UDP endpoints/ports differ from the frozen channel direction")

    def _packet(self, packet, candidates, streams, policy):
        channel = self.channels[candidates[0].channel_id]
        medium = channel["type"]
        if packet.transport == "UNDECODED_TRUNCATED":
            raise ICDError("FRAGMENT", "truncated packet is only container analysis, not complete logical history")
        if packet.transport == "TCP_ANALYSIS_ONLY":
            raise ICDError("UNSUPPORTED", "TCP needs its explicit business extractor, never UDP wire interpretation")
        if medium == "ETH":
            if packet.transport != "UDP":
                raise ICDError("RESOURCE", "Ethernet capture binding cannot contain CAN transport")
            raw_bus = packet.destination_port == 36150
            direction = self._udp_direction(packet, channel, raw=raw_bus)
            if not raw_bus:
                return self.wire.decode(packet.payload, "UDP", direction=direction), None, direction
            payload = {"medium": "ETHERNET", "channel_id": channel["id"], "destination_udp_port": 36150,
                       "payload_hex": packet.payload.hex(), "ttl": packet.ip_ttl}
        else:
            if packet.transport != medium or packet.can is None:
                raise ICDError("RESOURCE", "capture CAN frame medium differs from channel binding")
            can = packet.can
            if can.is_error_frame:
                raise ICDError("UNSUPPORTED", "CAN error observation is not a business input")
            raw_bus = 0x600 <= can.arbitration_id <= 0x6ff
            if not raw_bus:
                if medium != "CANFD":
                    raise ICDError("UNSUPPORTED", "classic CAN does not carry formal business messages")
                frame = CANFrame(can.arbitration_id, can.data, can.is_fd, can.bitrate_switch,
                                 can.is_extended_id, can.is_remote_frame)
                fragment = self.wire.decode(frame, "CANFD")
                return fragment, None, fragment.direction
            direction = "TO_36"
            b = self._select(candidates, streams, 44, direction)
            if b.raw_to36_capture_direction is None or packet.capture_direction != b.raw_to36_capture_direction:
                raise ICDError("AUTHORIZATION", "auxiliary CAN needs recognized capture-point direction evidence")
            if can.is_remote_frame:
                raise ICDError("AUTHORIZATION", "auxiliary CAN RTR cannot become RawBus stimulus")
            payload = {"medium": medium, "channel_id": channel["id"], "can_id": can.arbitration_id,
                       "extended": can.is_extended_id, "data_hex": can.data.hex()}
            if medium == "CAN":
                payload.update(rtr=False, dlc=can.dlc)
            else:
                payload.update(brs=can.bitrate_switch, data_length=can.dlc)
        if policy["mode"] != "REENCODE":
            raise ICDError("UNSUPPORTED", "auxiliary capture has no formal session header for raw/session-rebuild replay")
        stimulus = {"message_id": 44, "payload": payload}
        return None, stimulus, direction

    def _record(self, capture, indices, binding, stream, *, message=None, stimulus=None, payload):
        if message is not None and stream["clock"] == "MODEL_STEP":
            expected = message["header"]["target_step"] * self.contract.catalogue["policy"]["model_step_us"] * 1000
            if capture.packets[indices[0]].timestamp_ns - int(stream["epoch_ns"]) != expected:
                raise ICDError("CLOCK_UNSYNC", "declared model-step capture time differs from actual target step")
        if stimulus is not None and message is None and stream["clock"] == "MODEL_STEP":
            raise ICDError("CLOCK_UNSYNC", "auxiliary capture has no model-step provenance")
        digest = hashlib.sha256()
        for i in indices:
            raw = capture.packets[i].raw_bytes
            digest.update(len(raw).to_bytes(4, "little"))
            digest.update(raw)
        epoch = int(stream["epoch_ns"])
        return HistoryRecord(capture.packets[indices[0]].timestamp_ns - epoch,
                             capture.packets[indices[-1]].timestamp_ns - epoch, binding.stream_id,
                             binding.channel_id, stream["direction"], binding.clock_domain, binding.clock_id,
                             tuple(indices), None if message is None else canonicalize(message),
                             None if stimulus is None else canonicalize(stimulus),
                             hashlib.sha256(payload).hexdigest(), digest.hexdigest())

    def check_policy(self, policy, result):
        self.contract.validate_source_definition("ReplayPolicy", policy)
        if len(set(policy["rewrite_fields"])) != len(policy["rewrite_fields"]):
            raise ICDError("RESOURCE", "replay rewrite fields must be unique")
        start, end = int(policy["start_offset_ns"]), int(policy["end_offset_ns"])
        first, last = min(r.offset_ns for r in result.records), max(r.completion_offset_ns for r in result.records)
        if not first <= start <= end <= last:
            raise ICDError("RESOURCE", "replay window is outside actual decoded capture range")
        if policy["execution_mode"] == "ONLINE" and result.complete_capture is False:
            raise ICDError("RESOURCE", "incomplete capture cannot run any ONLINE replay policy")
        if policy["mode"] != "REENCODE" and any(r.message_json is None for r in result.records):
            raise ICDError("UNSUPPORTED", "auxiliary history only supports engineering re-encoding")

    def decode(self, raw, history, bindings, *, model_id, declared_ids):
        models = {model for entry in self.contract.messages.values() for model in entry["model_ids"]}
        if type(model_id) is not str or model_id not in models:
            raise ICDError("MODEL", "history requires a model from the verified catalogue")
        self.contract.validate_source_definition("HistorySource", history)
        if (not self.contract.component_hashes or history["decoder_baseline_sha256"] != self.contract.baseline_sha256):
            raise ICDError("HASH", "history requires the externally verified original decoder baseline")
        ref = history["resource"]
        if type(raw) is bytes and len(raw) > self.parser.max_bytes:
            raise ICDError("CAPACITY", "capture byte capacity exceeded")
        if type(raw) is not bytes or len(raw) != int(ref["size_bytes"]) or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ICDError("HASH", "actual capture bytes differ from the declared resource")
        if ref["encoding"] != ("UTF8" if ref["format"] == "CAN_LOG" else "BINARY"):
            raise ICDError("RESOURCE", "capture encoding differs from its actual format")
        if type(declared_ids) is not tuple:
            raise ICDError("RESOURCE", "explicit unique declared protocol IDs required")
        for mid in declared_ids:
            self.contract.entry(mid)
        if len(set(declared_ids)) != len(declared_ids):
            raise ICDError("RESOURCE", "declared protocol IDs must be unique")
        capture = self.parser.parse(raw, ref["format"])
        streams, domain_bindings, clocks = self._bindings(bindings, history["streams"], capture)
        for stream in streams.values():
            mids = stream["message_ids"]
            if len(set(mids)) != len(mids) or not set(mids) <= set(declared_ids):
                raise ICDError("RESOURCE", "history stream messages differ from unique declared protocol scope")
            for mid in mids:
                if self.contract.entry(mid)["direction"] != stream["direction"]:
                    raise ICDError("AUTHORIZATION", "declared stream message direction is inconsistent")
        incomplete = bool(capture.observed_lost_packets or capture.observed_truncated_packets or any(
            s["lost_packets"] or s["truncated_packets"] for s in streams.values()))
        if incomplete and history["policy"]["execution_mode"] == "ONLINE":
            raise ICDError("RESOURCE", "actual or declared incomplete history cannot run ONLINE")
        by_domain, previous = {}, {}
        for index, packet in enumerate(capture.packets):
            domain = (packet.clock_domain, packet.capture_interface)
            epoch = int(streams[domain_bindings[domain][0].stream_id]["epoch_ns"])
            if packet.timestamp_ns < epoch or packet.timestamp_ns < previous.get(domain, -1):
                raise ICDError("CLOCK_UNSYNC", "capture domain clock goes backwards or precedes epoch")
            previous[domain] = packet.timestamp_ns
            by_domain.setdefault(domain, []).append(index)
        records = []
        counts = {sid: 0 for sid in streams}
        observed_ids = {sid: set() for sid in streams}
        for domain, indices in by_domain.items():
            # Only one domain allocates at a time; never splice clocks or multiply
            # the frozen reassembly memory/slot budgets by the interface count.
            assembler = Reassembler(self.contract, retain_completed=False)
            groups = {}
            candidates = domain_bindings[domain]
            for index in indices:
                packet = capture.packets[index]
                fragment, stimulus, direction = self._packet(packet, candidates, streams, history["policy"])
                mid = fragment.message_id if fragment is not None else 44
                binding = self._select(candidates, streams, mid, direction)
                stream = streams[binding.stream_id]
                if assembler.expire(now_ns=packet.timestamp_ns):
                    raise ICDError("TIMEOUT", "captured logical fragment group exceeded the original timeout")
                if fragment is None:
                    self.contract.validate_stimulus(stimulus, model_id=model_id)
                    record = self._record(capture, [index], binding, stream, stimulus=stimulus, payload=packet.payload)
                else:
                    key = (binding.channel_id, direction, mid, fragment.header.session_id,
                           fragment.header.sequence, fragment.header.transaction_id)
                    group = groups.setdefault(key, [])
                    group.append(index)
                    completed = assembler.push(fragment, channel=binding.channel_id, direction=direction,
                                               authorized=True, now_ns=packet.timestamp_ns)
                    if completed is None:
                        continue
                    self.contract.validate_message(completed.message, direction=direction, model_id=model_id)
                    stimulus = None if direction == "FROM_36" else {"message_id": mid, "payload": completed.message["payload"]}
                    record = self._record(capture, group, binding, stream, message=completed.message,
                                          stimulus=stimulus, payload=completed.data)
                    del groups[key]
                if len(records) >= self.max_records:
                    raise ICDError("CAPACITY", "history logical record capacity exceeded")
                records.append(record)
                counts[binding.stream_id] += 1
                observed_ids[binding.stream_id].add(mid)
            if assembler.pending_count or groups:
                raise ICDError("FRAGMENT", "capture ended with incomplete logical messages")
        if not records:
            raise ICDError("RESOURCE", "capture has no complete history records")
        records.sort(key=lambda r: r.packet_indices[0])
        for sid, stream in streams.items():
            if counts[sid] != stream["records"] or observed_ids[sid] != set(stream["message_ids"]):
                raise ICDError("RESOURCE", "actual logical count/message IDs differ from declared HistoryStream")
        result = DecodedHistory(capture, tuple(records), clocks, False if incomplete else None)
        self.check_policy(history["policy"], result)
        return result
