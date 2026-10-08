"""Build a deterministic software reference PCAP using the frozen ICD.

This module serializes Ethernet frames and a PCAP container only. Business
payloads and HIL1 datagrams always come from the verified contract and
``WireCodec``. It never opens a socket or a raw network interface.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import re
import struct

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether
from scapy.packet import Raw

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import Header, WireCodec
from .capture import CaptureParser
from .history import CaptureBinding, HistoryDecoder
from .replay import ReplayHeader, ReplayProcessor


BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
MESSAGE_ID = 7
MODEL_ID = "quadrotor_hil"
CHANNEL_ID = "ETH_0"
SOURCE_IPV4 = "10.36.0.10"
SOURCE_UDP_PORT = 36102
RECEIVER_IPV4 = "10.36.0.20"
BUSINESS_UDP_PORT = 36100
SOURCE_MAC = "02:00:00:00:00:01"
DESTINATION_MAC = "02:00:00:00:00:02"
REFERENCE_EPOCH_UNIX_SECONDS = 1_760_000_000
RELATIVE_OFFSETS_NS = (0,)
_PCAP_GLOBAL_HEADER = struct.pack("<IHHIIII", 0xA1B23C4D, 2, 4, 0, 0, 65535, 1)
_EXPECTED_PROFILE = (CHANNEL_ID, SOURCE_IPV4, SOURCE_UDP_PORT,
                     RECEIVER_IPV4, BUSINESS_UDP_PORT)


@dataclass(frozen=True, slots=True)
class ReferenceProfile:
    channel_id: str = CHANNEL_ID
    source_ipv4: str = SOURCE_IPV4
    source_udp_port: int = SOURCE_UDP_PORT
    receiver_ipv4: str = RECEIVER_IPV4
    business_udp_port: int = BUSINESS_UDP_PORT
    source_mac: str = SOURCE_MAC
    destination_mac: str = DESTINATION_MAC


DEFAULT_REFERENCE_PROFILE = ReferenceProfile()


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _verified_example(contract, profile):
    if type(profile) is not ReferenceProfile:
        raise ICDError("SCHEMA", "reference capture requires the explicit frozen ETH_0 profile type")
    path = Path(__file__).resolve().parents[1] / "docs" / "interfaces" / "baseline"
    document = loads((path / "input-simulator-v0.3.examples.json").read_bytes())
    matches = [item["value"] for item in document["fixtures"]
               if item.get("value", {}).get("message_id") == MESSAGE_ID]
    if len(matches) != 1:
        raise ICDError("RESOURCE", "frozen v0.3 reference fixture is absent or ambiguous")
    message = deepcopy(matches[0])
    entry = contract.entry(MESSAGE_ID)
    channel = next((item for item in contract.catalogue["channels"] if item["id"] == CHANNEL_ID), None)
    actual = (profile.channel_id, profile.source_ipv4, profile.source_udp_port,
              profile.receiver_ipv4, profile.business_udp_port)
    catalogue_profile = (CHANNEL_ID, None if channel is None else channel.get("source_ipv4"),
                         None if channel is None else channel.get("source_udp_port"),
                         None if channel is None else channel.get("receiver_ipv4"),
                         None if channel is None else channel.get("business_udp_port"))
    macs_valid = True
    for value in (profile.source_mac, profile.destination_mac):
        if type(value) is not str or re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value) is None:
            macs_valid = False
            break
        try:
            octets = bytes.fromhex(value.replace(":", ""))
        except ValueError:
            macs_valid = False
            break
        if len(octets) != 6 or octets == bytes(6) or octets[0] & 1:
            macs_valid = False
            break
    if (contract.baseline_sha256 != BASELINE_SHA256 or channel is None
            or channel.get("type") != "ETH"
            or actual != _EXPECTED_PROFILE or catalogue_profile != _EXPECTED_PROFILE
            or not macs_valid
            or entry["direction"] != "TO_36" or "UDP" not in entry["transports"]):
        raise ICDError("HASH", "verified contract does not contain the frozen ETH_0/TO_36/UDP profile")
    contract.validate_message(message, direction="TO_36", model_id=MODEL_ID)
    return message


def _pcap_bytes(frames, timestamps_ns):
    if (type(frames) is not tuple or type(timestamps_ns) is not tuple
            or not frames or len(frames) != len(timestamps_ns)):
        raise ICDError("RESOURCE", "PCAP writer requires matching immutable frames and timestamps")
    output = bytearray(_PCAP_GLOBAL_HEADER)
    for frame, timestamp_ns in zip(frames, timestamps_ns):
        if type(frame) is not bytes or not 1 <= len(frame) <= 65535:
            raise ICDError("RESOURCE", "PCAP frame must be complete bounded Ethernet bytes")
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise ICDError("SCHEMA", "PCAP timestamps must be nonnegative integer Unix nanoseconds")
        seconds, nanoseconds = divmod(timestamp_ns, 1_000_000_000)
        if seconds >= 1 << 32:
            raise ICDError("SCHEMA", "PCAP Unix timestamp exceeds the frozen container range")
        output.extend(struct.pack("<IIII", seconds, nanoseconds, len(frame), len(frame)))
        output.extend(frame)
    return bytes(output)


def _sample(contract, profile=DEFAULT_REFERENCE_PROFILE):
    message = _verified_example(contract, profile)
    wire = WireCodec(contract)
    encoded = tuple(wire.encode(message, "UDP"))
    if not encoded:
        raise ICDError("RESOURCE", "WireCodec produced no formal UDP fragments")
    frames = tuple(bytes(Ether(src=profile.source_mac, dst=profile.destination_mac) /
                         IP(src=profile.source_ipv4, dst=profile.receiver_ipv4, ttl=64, id=index + 1) /
                         UDP(sport=profile.source_udp_port, dport=profile.business_udp_port) /
                         Raw(datagram)) for index, datagram in enumerate(encoded))
    timestamps = tuple(REFERENCE_EPOCH_UNIX_SECONDS * 1_000_000_000 + offset
                       for offset in RELATIVE_OFFSETS_NS)
    if len(frames) != len(timestamps):
        raise ICDError("RESOURCE", "frozen software reference currently requires one timestamp per frame")
    return message, encoded, frames, timestamps, _pcap_bytes(frames, timestamps)


def build_reference_pcap(contract, *, profile=DEFAULT_REFERENCE_PROFILE):
    """Return deterministic PCAP bytes for the one frozen software sample."""
    return _sample(contract, profile)[-1]


def _history(raw):
    return {
        "source_type": "HISTORY",
        "history_id": "reference-round1-eth0",
        "resource": {
            "resource_id": "reference-round1",
            "sha256": _sha256(raw),
            "size_bytes": len(raw),
            "format": "PCAP",
            "encoding": "BINARY",
            "media_type": "application/vnd.tcpdump.pcap",
            "file_name": "reference.pcap",
        },
        "streams": [{
            "stream_id": "reference-eth0",
            "direction": "TO_36",
            "original_channel": "ETHERNET",
            "message_ids": [MESSAGE_ID],
            "records": 1,
            "clock": "UTC",
            "epoch_ns": str(REFERENCE_EPOCH_UNIX_SECONDS * 1_000_000_000),
            "uncertainty_us": 0,
            "truncated_packets": 0,
            "lost_packets": 0,
        }],
        "policy": {
            "mode": "REENCODE",
            "start_offset_ns": "0",
            "end_offset_ns": "0",
            "rate": "1X",
            "execution_mode": "OFFLINE",
            "repeat_count": 1,
            "repeat_gap_steps": 100,
            "session_policy": "NEW_SESSION_PER_REPEAT",
            "rewrite_fields": [],
            "filter_direction": "TO_36_ONLY",
            "seek_policy": "OFFLINE_ONLY",
            "restore_policy": "RESET_MODEL_AND_CLEAR_QUEUES",
            "incomplete_capture_policy": "REJECT_ONLINE",
            "feedback_policy": "COLLECT_NOT_INJECT",
        },
        "integrity_verified": True,
        "decoder_baseline_sha256": BASELINE_SHA256,
    }


def validate_reference_pcap(contract, raw):
    """Round-trip final PCAP bytes through the production capture/history/replay path."""
    if type(raw) is not bytes or not raw:
        raise ICDError("RESOURCE", "reference PCAP validation requires immutable bytes")
    message, encoded, expected_frames, timestamps, expected_raw = _sample(contract)
    if raw != expected_raw:
        raise ICDError("RESOURCE", "reference PCAP bytes differ from the deterministic frozen sample")

    capture = CaptureParser().parse(raw, "PCAP")
    if len(capture.packets) != len(expected_frames):
        raise ICDError("RESOURCE", "CaptureParser packet count differs from generated frames")
    for index, packet in enumerate(capture.packets):
        if (packet.linktype != 1 or packet.timestamp_ns != timestamps[index]
                or packet.raw_bytes != expected_frames[index] or packet.transport != "UDP"
                or packet.source_ipv4 != SOURCE_IPV4 or packet.destination_ipv4 != RECEIVER_IPV4
                or packet.source_port != SOURCE_UDP_PORT or packet.destination_port != BUSINESS_UDP_PORT
                or packet.vlan_id is not None or packet.payload != encoded[index]
                or not packet.transport_checksum_verified):
            raise ICDError("RESOURCE", "CaptureParser projection differs from the deterministic ETH_0 sample")

    wire = WireCodec(contract)
    fragments, completed = [], None
    reassembler = Reassembler(contract, retain_completed=False)
    for packet in capture.packets:
        fragment = wire.decode(packet.payload, "UDP", direction="TO_36")
        fragments.append(fragment)
        completed = reassembler.push(fragment, channel=CHANNEL_ID, direction="TO_36",
                                     authorized=True, now_ns=packet.timestamp_ns) or completed
    if (len(fragments) != len(encoded) or any(fragment.message_id != MESSAGE_ID
            or fragment.index != index or fragment.count != len(encoded)
            for index, fragment in enumerate(fragments)) or completed is None
            or completed.message != message):
        raise ICDError("RESOURCE", "WireCodec/Reassembler did not restore the frozen business message")

    history = _history(raw)
    binding = CaptureBinding("reference-eth0", CHANNEL_ID, "PCAP:0:0", "interface-0", "clock-0")
    decoded = HistoryDecoder(contract).decode(raw, history, (binding,), model_id=MODEL_ID,
                                               declared_ids=(MESSAGE_ID,))
    if (len(decoded.records) != 1 or decoded.records[0].direction != "TO_36"
            or decoded.records[0].channel_id != CHANNEL_ID or decoded.records[0].message != message
            or decoded.records[0].stimulus != {"message_id": MESSAGE_ID, "payload": message["payload"]}
            or decoded.records[0].offset_ns != 0):
        raise ICDError("RESOURCE", "HistoryDecoder did not restore the expected ETH_0 TO_36 record")

    replay_header = Header(session_id=91, sequence=101, target_step=200,
                           transaction_id=301, valid_for_ms=100)
    prepared = ReplayProcessor(contract).prepare(
        raw, history, (binding,), model_id=MODEL_ID, declared_ids=(MESSAGE_ID,),
        headers=(ReplayHeader(0, replay_header),))
    if (not prepared.packets or prepared.execution_ready is not False
            or any(packet.transport != "UDP" or packet.channel_id != CHANNEL_ID
                   for packet in prepared.packets)
            or any(record.direction != "TO_36" for record in decoded.records)):
        raise ICDError("RESOURCE", "ReplayProcessor did not prepare nonempty offline TO_36 output")

    manifest = {
        "manifest_version": "1.0",
        "baseline_version": contract.catalogue["baseline_version"],
        "baseline_sha256": contract.baseline_sha256,
        "generator": "input_simulator.reference_pcap:write_reference_artifacts",
        "message_id": MESSAGE_ID,
        "direction": "TO_36",
        "channel": CHANNEL_ID,
        "transport": "Ethernet/IPv4/UDP",
        "linktype": 1,
        "vlan": None,
        "source_endpoint": {"ipv4": SOURCE_IPV4, "udp_port": SOURCE_UDP_PORT},
        "destination_endpoint": {"ipv4": RECEIVER_IPV4, "udp_port": BUSINESS_UDP_PORT},
        "source_mac": SOURCE_MAC,
        "destination_mac": DESTINATION_MAC,
        "mac_identity_note": "Deterministic software reference L2 identity; not a deployed hardware MAC.",
        "packet_count": len(capture.packets),
        "logical_message_count": len(decoded.records),
        "timestamp": {
            "kind": "software reference fixture epoch, not real capture time",
            "epoch_unix_seconds": REFERENCE_EPOCH_UNIX_SECONDS,
            "relative_offsets_ns": list(RELATIVE_OFFSETS_NS),
        },
        "pcap_sha256": _sha256(raw),
        "frames": [{
            "index": index,
            "timestamp_unix_ns": packet.timestamp_ns,
            "ethernet_frame_sha256": _sha256(packet.raw_bytes),
            "udp_payload_sha256": _sha256(packet.payload),
        } for index, packet in enumerate(capture.packets)],
        "synthetic_reference": True,
        "actual_network_tx": False,
        "model_applied": False,
        "execution_ready": False,
    }
    validation = {
        "status": "ROUND_TRIP_VALIDATED_SOFTWARE_REFERENCE",
        "stages": {
            "generated": {"status": "PASS", "formal_wire_codec": "WireCodec", "frame_count": len(encoded)},
            "parsed": {"status": "PASS", "parser": "CaptureParser", "format": capture.format,
                       "linktype": capture.packets[0].linktype, "packet_count": len(capture.packets),
                       "timestamp_ns": [packet.timestamp_ns for packet in capture.packets],
                       "frames": [{
                           "source_mac": Ether(packet.raw_bytes).src,
                           "destination_mac": Ether(packet.raw_bytes).dst,
                           "source_ipv4": packet.source_ipv4,
                           "destination_ipv4": packet.destination_ipv4,
                           "source_udp_port": packet.source_port,
                           "destination_udp_port": packet.destination_port,
                           "transport": packet.transport,
                           "vlan": packet.vlan_id,
                           "ethernet_frame_sha256": _sha256(packet.raw_bytes),
                       } for packet in capture.packets],
                       "udp_payload_sha256": [_sha256(packet.payload) for packet in capture.packets]},
            "wire_decoded": {"status": "PASS", "decoder": "WireCodec", "packets": [{
                "magic": "HIL1",
                "message_id": fragment.message_id,
                "direction": fragment.direction,
                "header": asdict(fragment.header),
                "fragment_index": fragment.index,
                "fragment_count": fragment.count,
                "crc_verified": True,
                "payload_length_bytes": len(fragment.payload),
                "payload_sha256": _sha256(fragment.payload),
            } for fragment in fragments]},
            "decoded": {"status": "PASS", "decoder": "HistoryDecoder", "channel": CHANNEL_ID,
                        "direction": "TO_36", "message_id": MESSAGE_ID,
                        "logical_message_count": len(decoded.records),
                        "message": decoded.records[0].message,
                        "stimulus": decoded.records[0].stimulus,
                        "record_payload_sha256": decoded.records[0].payload_sha256},
            "prepared": {"status": "PASS", "processor": "ReplayProcessor", "mode": prepared.mode,
                         "packet_count": len(prepared.packets), "execution_ready": False,
                         "selected_directions": [record.direction for record in decoded.records]},
        },
        "claims": {"generated": True, "parsed": True, "decoded": True, "prepared": True,
                   "transmitted": False, "received": False, "applied": False,
                   "consumed": False, "execution_ready": False},
    }
    return manifest, validation


def write_reference_artifacts(contract, output_directory):
    """Create a new artifact directory without replacing prior user data."""
    target = Path(output_directory)
    message, encoded, frames, timestamps, raw = _sample(contract)
    try:
        target.mkdir(parents=True, exist_ok=False)
        pcap_path = target / "reference.pcap"
        with pcap_path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        readback = pcap_path.read_bytes()
        if readback != raw:
            raise OSError("persisted reference PCAP differs from generated bytes")
        manifest, validation = validate_reference_pcap(contract, readback)
        for name, document in (("reference_manifest.json", manifest),
                               ("round1_validation.json", validation)):
            data = canonicalize(document) + b"\n"
            with (target / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if (target / name).read_bytes() != data:
                raise OSError(f"persisted {name} differs from its generated bytes")
        final_readback = pcap_path.read_bytes()
        if final_readback != raw:
            raise OSError("final reference PCAP readback changed during manifest persistence")
        final_manifest = loads((target / "reference_manifest.json").read_bytes())
        if final_manifest["pcap_sha256"] != _sha256(final_readback):
            raise OSError("manifest PCAP SHA256 differs from final persisted reference.pcap")
        validate_reference_pcap(contract, final_readback)
        return {"manifest": manifest, "validation": validation, "message": message,
                "frame_count": len(frames), "wire_packet_count": len(encoded),
                "timestamp_ns": list(timestamps), "output_directory": str(target)}
    except (OSError, TypeError, ValueError) as error:
        raise ICDError("RESOURCE", "exclusive reference artifact persistence failed; owned partial directory retained") from error
