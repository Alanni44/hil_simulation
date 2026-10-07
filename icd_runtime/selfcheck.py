"""Read-only frozen-fixture checks; not a service or device acceptance runner."""

import hashlib
import json
from pathlib import Path

from .contract import Contract
from .errors import ICDError
from .reassembly import Reassembler
from .video import VideoCodec, VideoHeader
from .wire import WireCodec


# Offline evidence pins are separate from the four-component business baseline.
_FIXTURE_SHA256 = {
    "input-simulator-v0.3.examples.json": "939dfc1fd12ff6bcf246b5b39ada1a8e13b8875ddad87520e49a87cd2808659f",
    "input-simulator-v0.3.golden.json": "dfd43d6bfde6cb614b226760548e3d884d058135b2665c9313ee8d85de51d796",
}


def verify_offline(directory: Path, expected_sha256: str) -> dict:
    directory = Path(directory)
    contract = Contract.load(directory, expected_sha256=expected_sha256)
    manifest = json.loads((directory / "input-simulator-v0.3.manifest.json").read_bytes())
    declared = {item["file"]: item for item in manifest["files"]}

    def fixture(name):
        raw = (directory / name).read_bytes()
        entry = declared[name]
        digest = hashlib.sha256(raw).hexdigest()
        if digest != _FIXTURE_SHA256[name] or digest != entry["sha256"] or len(raw) != entry["size_bytes"]:
            raise ICDError("HASH", "offline fixture does not match frozen manifest")
        return json.loads(raw)

    examples = fixture("input-simulator-v0.3.examples.json")
    vectors = fixture("input-simulator-v0.3.golden.json")["vectors"]
    values = {f["value"]["message_id"]: f["value"] for f in examples["fixtures"]}
    if set(values) != set(contract.messages):
        raise ICDError("SCHEMA", "offline fixtures do not cover all business IDs")
    wire = WireCodec(contract)
    assembler = Reassembler(contract)
    encoded = {}
    completed = 0
    for mid, value in values.items():
        for transport in contract.entry(mid)["transports"]:
            packets = wire.encode(value, transport)
            encoded[mid, transport] = packets
            direction = contract.entry(mid)["direction"]
            result = None
            for packet in reversed(packets):
                result = assembler.push(wire.decode(packet, transport, direction=direction),
                                        channel="CANFD_0" if transport == "CANFD" else "ETH_0",
                                        direction=direction, authorized=True, now_ns=0)
            if result is None or result.message != value:
                raise ICDError("SCHEMA", "offline reconstructed business value differs from fixture")
            completed += 1
    video = VideoCodec(contract)
    video_header = VideoHeader(1, 1, 0, 1000, 0, "RAW")
    raw_frame = bytes(921600)
    video_packets = video.encode(raw_frame, video_header)
    identities = [(v["message_id"], v["transport"], v["fragment_index"]) for v in vectors]
    expected_identities = {(mid, transport, index) for (mid, transport), packets in encoded.items()
                           for index in range(len(packets))}
    expected_identities.update((43, "VIDEO", index) for index in (0, 400, 799))
    if len(identities) != 85 or len(set(identities)) != 85 or set(identities) != expected_identities:
        raise ICDError("SCHEMA", "offline golden set must uniquely cover all 85 frozen fragment identities")
    for vector in vectors:
        transport = vector["transport"]
        if transport == "VIDEO":
            packet = video_packets[vector["fragment_index"]]
            if hashlib.sha256(raw_frame).hexdigest() != vector["frame_sha256"]:
                raise ICDError("HASH", "video fixture frame hash differs from golden")
        else:
            packet = encoded[vector["message_id"], transport][vector["fragment_index"]]
            if transport == "CANFD":
                if packet.arbitration_id != vector["can_id"]:
                    raise ICDError("SCHEMA", "encoded CAN ID differs from golden")
                packet = packet.data
        if packet.hex() != vector["wire_hex"]:
            raise ICDError("SCHEMA", "encoded bytes differ from independent golden vector")
    result = None
    for packet in reversed(video_packets):
        result = assembler.push(video.decode(packet), channel="ETH_0", direction="TO_36", authorized=True, now_ns=0)
    if result is None or result.data != raw_frame:
        raise ICDError("SCHEMA", "offline reconstructed RAW frame differs from fixture")
    return {
        "status": "OFFLINE_CODEC_PASS",
        "baseline_sha256": contract.baseline_sha256,
        "business_messages": len(values),
        "business_transport_completions": completed,
        "golden_fragments": len(vectors),
        "video_raw_fragments": len(video_packets),
        "pending_groups": assembler.pending_count,
        "reserved_payload_bytes": assembler.reserved_bytes,
        "runtime_network_model_hardware_replacement": "NOT_EXECUTED",
    }
