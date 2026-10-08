"""Prepare a Round 1 HISTORY capture as an offline replay PCAP and argv plan.

This script persists offline evidence only. It never starts the generated tool.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import Header, WireCodec
from input_simulator.capture import CaptureParser
from input_simulator.history import CaptureBinding, HistoryDecoder
from input_simulator.reference_pcap import BASELINE_SHA256, _history
from input_simulator.replay import ReplayHeader, ReplayProcessor
from input_simulator.replay_export import ExportBinding
from input_simulator.tool_commands import ToolCommandBuilder
from input_simulator.tools import ChannelReservations


REFERENCE_PATH = ROOT / "artifacts" / "history" / "round1" / "reference.pcap"
REFERENCE_MANIFEST_PATH = ROOT / "artifacts" / "history" / "round1" / "reference_manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "history" / "round2"
SOURCE_MAC = "02:00:00:00:00:01"
DESTINATION_MAC = "02:00:00:00:00:02"
SOURCE_ENDPOINT = ("10.36.0.10", 36102)
DESTINATION_ENDPOINT = ("10.36.0.20", 36100)
ALLOCATED_HEADER = Header(session_id=92, sequence=102, target_step=201,
                          transaction_id=302, valid_for_ms=100)


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _write_new_json(directory, name, value):
    raw = canonicalize(value) + b"\n"
    with (directory / name).open("xb") as stream:
        stream.write(raw)
        stream.flush()
    if (directory / name).read_bytes() != raw:
        raise OSError(f"persisted {name} differs from generated evidence")


def prepare_round2_artifacts(contract, output_directory=DEFAULT_OUTPUT):
    """Run the existing offline decode, preparation, export and command builders."""
    output_directory = Path(output_directory)
    if output_directory.exists() or output_directory.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing Round 2 directory: {output_directory}")
    raw = REFERENCE_PATH.read_bytes()
    source_hash = _sha256(raw)
    reference_manifest = loads(REFERENCE_MANIFEST_PATH.read_bytes())
    if (source_hash != reference_manifest.get("pcap_sha256")
            or reference_manifest.get("synthetic_reference") is not True
            or reference_manifest.get("baseline_sha256") != contract.baseline_sha256):
        raise ValueError("Round 1 PCAP bytes or manifest do not match the verified reference baseline")

    history = _history(raw)
    binding = CaptureBinding("reference-eth0", "ETH_0", "PCAP:0:0", "interface-0", "clock-0")
    decoded = HistoryDecoder(contract).decode(raw, history, (binding,), model_id="quadrotor_hil",
                                               declared_ids=(7,))
    if len(decoded.records) != 1 or decoded.records[0].direction != "TO_36":
        raise ValueError("Round 1 reference did not decode as one TO_36 message")
    original_header = decoded.records[0].message["header"]

    processor = ReplayProcessor(contract)
    prepared = processor.prepare(raw, history, (binding,), model_id="quadrotor_hil", declared_ids=(7,),
                                 headers=(ReplayHeader(0, ALLOCATED_HEADER),))
    if prepared.mode != "REENCODE" or not prepared.packets or prepared.execution_ready is not False:
        raise ValueError("ReplayProcessor did not return the expected non-executable REENCODE preparation")

    # This source is already a complete Ethernet capture. Exporter preserves
    # its frozen L2 identity and rejects redundant binding MAC overrides.
    export_binding = ExportBinding("ETH_0", "eth0", output_name="prepared.pcap")
    reservations = ChannelReservations()
    token = reservations.reserve("history-round2", "ETHREPLAY", ("eth0",), mode="SEND")
    builder = ToolCommandBuilder(contract, reservations)
    plan = builder.replay(token, prepared, (export_binding,), directory=output_directory)
    if (len(plan.commands) != 1 or plan.commands[0].argv[0] != "tcpreplay"
            or Path(plan.commands[0].argv[-1]).resolve() != (output_directory / "prepared.pcap").resolve()
            or plan.execution_ready is not False or plan.authorized_to_transmit is not False):
        raise ValueError("ToolCommandBuilder did not produce the expected literal offline tcpreplay plan")

    exported = plan.export.files[0]
    parsed = CaptureParser().parse(exported.data, "PCAP")
    if parsed.format != "PCAP" or len(parsed.packets) != len(prepared.packets):
        raise ValueError("ReplayExporter output is not the expected PCAP packet set")
    wire = WireCodec(contract)
    frames = []
    for index, (actual, source, packet) in enumerate(zip(parsed.packets, decoded.capture.packets, prepared.packets)):
        fragment = wire.decode(actual.payload, "UDP", direction="TO_36")
        payload = wire.payload_codec.decode(fragment.message_id, fragment.payload)
        if (actual.linktype != 1 or actual.transport != "UDP" or actual.vlan_id is not None
                or actual.payload != packet.wire_data or actual.timestamp_ns != int(packet.relative_offset_ns)
                or (actual.source_ipv4, actual.source_port) != SOURCE_ENDPOINT
                or (actual.destination_ipv4, actual.destination_port) != DESTINATION_ENDPOINT
                or (actual.source_ipv4, actual.source_port) == (actual.destination_ipv4, actual.destination_port)
                or fragment.header != ALLOCATED_HEADER or fragment.message_id != 7 or fragment.index != 0
                or fragment.count != 1 or payload != decoded.records[0].message["payload"]):
            raise ValueError(f"prepared packet {index} failed endpoint, HIL1, header, CRC or business checks")
        from scapy.layers.l2 import Ether
        if (Ether(actual.raw_bytes).src != SOURCE_MAC or Ether(actual.raw_bytes).dst != DESTINATION_MAC
                or actual.raw_bytes != packet.capture_bytes):
            raise ValueError(f"prepared Ethernet frame {index} differs from the export binding")
        frames.append({
            "index": index,
            "timestamp_unix_ns": actual.timestamp_ns,
            "relative_offset_ns": str(packet.relative_offset_ns),
            "repeat_index": prepared.repeat_index,
            "repeat_count": history["policy"]["repeat_count"],
            "ethernet_frame_sha256": _sha256(actual.raw_bytes),
            "udp_payload_sha256": _sha256(actual.payload),
            "message_id": fragment.message_id,
            "direction": fragment.direction,
            "header": asdict(fragment.header),
            "crc_verified": True,
        })

    changed_fields = sorted({field for packet in prepared.packets for field in packet.changed_fields})

    output_directory_created = plan.export.write_new_directory(output_directory)
    prepared_path = output_directory / "prepared.pcap"
    prepared_bytes = prepared_path.read_bytes()
    if prepared_bytes != exported.data or _sha256(prepared_bytes) != exported.sha256:
        raise ValueError("persisted prepared.pcap differs from ReplayExporter bytes/hash")
    # Read the actual persisted file again through the existing parser.
    persisted = CaptureParser().parse(prepared_bytes, "PCAP")
    if len(persisted.packets) != len(frames):
        raise ValueError("persisted prepared.pcap failed final parser readback")

    policy_sha = _sha256(canonicalize(history["policy"]))
    manifest = {
        "manifest_version": "1.0",
        "source_reference_pcap": str(REFERENCE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "source_reference_pcap_sha256": source_hash,
        "baseline_version": contract.catalogue["baseline_version"],
        "baseline_sha256": contract.baseline_sha256,
        "replay_mode": prepared.mode,
        "replay_policy_sha256": policy_sha,
        "input_message_id": 7,
        "input_channel": "ETH_0",
        "output_channel": "ETH_0",
        "original_header": original_header,
        "allocated_header": asdict(ALLOCATED_HEADER),
        "changed_fields": changed_fields,
        "header_allocation_note": "Offline replay preparation fixture only; not authorized by online SessionOpen.",
        "source_endpoint": {"ipv4": SOURCE_ENDPOINT[0], "udp_port": SOURCE_ENDPOINT[1]},
        "destination_endpoint": {"ipv4": DESTINATION_ENDPOINT[0], "udp_port": DESTINATION_ENDPOINT[1]},
        "source_mac": SOURCE_MAC,
        "destination_mac": DESTINATION_MAC,
        "packet_count": len(persisted.packets),
        "prepared_pcap_sha256": _sha256(prepared_bytes),
        "frames": frames,
        "rate": history["policy"]["rate"],
        "execution_mode": history["policy"]["execution_mode"],
        "repeat_index": prepared.repeat_index,
        "repeat_count": history["policy"]["repeat_count"],
        "synthetic_reference": True,
        "offline_prepared": True,
        "actual_network_tx": False,
        "process_started": False,
        "received": False,
        "applied": False,
        "consumed": False,
        "execution_ready": False,
    }
    argv = list(plan.commands[0].argv)
    command = {
        "command_built": True,
        "argv": argv,
        "channel_id": plan.commands[0].channel_id,
        "resource_sha256": plan.commands[0].resource_sha256,
        "first_offset_ns": plan.commands[0].first_offset_ns,
        "execution_ready": False,
        "authorized_to_transmit": False,
        "process_started": False,
        "actual_network_tx": False,
    }
    validation = {
        "status": "ROUND2_PREPARED_AND_COMMAND_BUILT_OFFLINE",
        "stages": {
            "reference_hash_verified": {"status": "PASS", "sha256": source_hash},
            "history_decoded": {"status": "PASS", "decoder": "HistoryDecoder", "record_count": len(decoded.records)},
            "replay_prepared": {"status": "PASS", "processor": "ReplayProcessor", "mode": prepared.mode,
                                "packet_count": len(prepared.packets), "execution_ready": False},
            "exported": {"status": "PASS", "exporter": "ReplayExporter", "format": exported.format,
                         "linktype": persisted.packets[0].linktype, "sha256": exported.sha256,
                         "output_path": str(prepared_path)},
            "reparsed": {"status": "PASS", "parser": "CaptureParser", "wire_decoder": "WireCodec",
                         "packet_count": len(persisted.packets), "payload_semantics_preserved": True,
                         "header_rewritten": True, "crc_verified": True},
            "command_built": {"status": "PASS", "builder": "ToolCommandBuilder", "argv": argv},
        },
        "claims": {"prepared": True, "exported": True, "command_built": True,
                   "process_started": False, "actual_network_tx": False, "received": False,
                   "applied": False, "consumed": False, "execution_ready": False},
    }
    _write_new_json(output_directory, "prepared_manifest.json", manifest)
    _write_new_json(output_directory, "tcpreplay_command.json", command)
    _write_new_json(output_directory, "round2_validation.json", validation)
    return {"manifest": manifest, "command": command, "validation": validation,
            "output_directory": str(output_directory), "export_manifest": str(output_directory_created)}


def main():
    contract = Contract.load(ROOT / "docs" / "interfaces" / "baseline", expected_sha256=BASELINE_SHA256)
    result = prepare_round2_artifacts(contract)
    print(json.dumps({"output_directory": result["output_directory"],
                      "prepared_pcap_sha256": result["manifest"]["prepared_pcap_sha256"],
                      "source_reference_pcap_sha256": result["manifest"]["source_reference_pcap_sha256"],
                      "replay_mode": result["manifest"]["replay_mode"],
                      "argv": result["command"]["argv"],
                      "process_started": False, "actual_network_tx": False}, indent=2))


if __name__ == "__main__":
    main()
