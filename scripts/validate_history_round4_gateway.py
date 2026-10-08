#!/usr/bin/env python3
"""Round 4 online Session and Gateway admission evidence runner/validator.

The source mode opens one real DEVELOPMENT session, then creates and sends one
REENCODEd probe. It deliberately does not authorize ID 7 through SourceSession.
The validation mode derives claims only from the persisted PCAPs and process
records; it never infers model application from RECEIVED.
"""

import argparse
import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import Header, WireCodec
from input_simulator.capture import CaptureParser
from input_simulator.history import CaptureBinding, HistoryDecoder
from input_simulator.reference_pcap import BASELINE_SHA256, _history
from input_simulator.replay import ReplayHeader, ReplayProcessor
from input_simulator.replay_export import ExportBinding, ReplayExporter
from input_simulator.session import SourceSession
from input_simulator.udp_source import UDPSource

REFERENCE = ROOT / "artifacts" / "history" / "round1" / "reference.pcap"
REFERENCE_MANIFEST = ROOT / "artifacts" / "history" / "round1" / "reference_manifest.json"
CONFIG = ROOT / "config" / "input-simulator-round4-development.json"
SOURCE_ENDPOINT = ("10.36.0.10", 36102)
FEEDBACK_ENDPOINT = ("10.36.0.10", 36101)
GATEWAY_ENDPOINT = ("10.36.0.20", 36100)
EXPECTED_PAYLOAD = {"motor_command": [0.1, 0.2, 0.3, 0.4]}
LEASE_WINDOW_NS = 500_000_000


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, raw):
    path = Path(path)
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise FileExistsError(f"refusing to overwrite Round 4 evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_json_new(path, value):
    write_new(path, canonicalize(value) + b"\n")


def load_contract():
    return Contract.load(ROOT / "docs" / "interfaces" / "baseline", expected_sha256=BASELINE_SHA256)


def prepare_current_session(contract, raw, session_id):
    """Decode Round 1 and use the frozen replay pipeline for one current SID."""
    ref_manifest = loads(REFERENCE_MANIFEST.read_bytes())
    source_hash = sha256(raw)
    if (source_hash != ref_manifest.get("pcap_sha256")
            or ref_manifest.get("synthetic_reference") is not True
            or ref_manifest.get("baseline_sha256") != contract.baseline_sha256):
        raise ValueError("Round 1 reference bytes/manifest do not match the frozen baseline")

    history = _history(raw)
    binding = CaptureBinding("reference-eth0", "ETH_0", "PCAP:0:0", "interface-0", "clock-0")
    decoded = HistoryDecoder(contract).decode(raw, history, (binding,), model_id="quadrotor_hil",
                                               declared_ids=(7,))
    if (len(decoded.records) != 1 or decoded.records[0].direction != "TO_36"
            or decoded.records[0].stimulus["message_id"] != 7
            or decoded.records[0].message["payload"] != EXPECTED_PAYLOAD):
        raise ValueError("Round 1 did not decode as the expected ID7 payload")
    captured_sids = {record.message["header"]["session_id"] for record in decoded.records
                     if record.message is not None}
    if type(session_id) is not int or session_id == 0 or session_id in captured_sids:
        raise ICDError("STALE_SESSION", "a fresh real nonzero SessionOpened SID is required")

    header = Header(session_id=session_id, sequence=2, target_step=201,
                    transaction_id=2, valid_for_ms=100)
    processor = ReplayProcessor(contract)
    prepared = processor.prepare(raw, history, (binding,), model_id="quadrotor_hil", declared_ids=(7,),
                                 headers=(ReplayHeader(0, header),))
    if prepared.mode != "REENCODE" or prepared.execution_ready is not False or len(prepared.packets) != 1:
        raise ValueError("Round 4 requires one offline REENCODEd, non-executable packet")
    exported = ReplayExporter(contract).export(
        prepared, (ExportBinding("ETH_0", "eth0", output_name="ETH_0.pcap"),),
        epoch_ns=time.time_ns(),
    )
    if len(exported.files) != 1:
        raise ValueError("ReplayExporter did not produce exactly one Round 4 PCAP")
    result = exported.files[0]
    parsed = CaptureParser().parse(result.data, "PCAP")
    if len(parsed.packets) != 1:
        raise ValueError("Round 4 PCAP must contain exactly one packet")
    packet = parsed.packets[0]
    fragment = WireCodec(contract).decode(packet.payload, "UDP", direction="TO_36")
    payload = WireCodec(contract).payload_codec.decode(fragment.message_id, fragment.payload)
    if (fragment.message_id != 7 or fragment.header != header or payload != EXPECTED_PAYLOAD
            or packet.source_ipv4 != SOURCE_ENDPOINT[0] or packet.source_port != SOURCE_ENDPOINT[1]
            or packet.destination_ipv4 != GATEWAY_ENDPOINT[0]
            or packet.destination_port != GATEWAY_ENDPOINT[1]):
        raise ValueError("persisted Round 4 PCAP differs from current-session ID7 probe")

    manifest = {
        "manifest_version": "1.0",
        "status": "ROUND4_ONLINE_PCAP_PREPARED_GATEWAY_ADMISSION_PENDING",
        "source_reference_pcap": "artifacts/history/round1/reference.pcap",
        "source_reference_pcap_sha256": source_hash,
        "baseline_sha256": contract.baseline_sha256,
        "replay_mode": prepared.mode,
        "message_id": 7,
        "direction": "TO_36",
        "channel": "ETH_0",
        "header": asdict(header),
        "payload": payload,
        "online_pcap_sha256": result.sha256,
        "packet_count": len(parsed.packets),
        "source_endpoint": {"ipv4": SOURCE_ENDPOINT[0], "udp_port": SOURCE_ENDPOINT[1]},
        "destination_endpoint": {"ipv4": GATEWAY_ENDPOINT[0], "udp_port": GATEWAY_ENDPOINT[1]},
        "header_type": "Gateway Admission Probe Header",
        "source_capability_authorized": False,
        "gateway_session_admitted": False,
        "target_step_semantically_qualified": False,
        "process_started": False,
        "actual_network_tx": False,
        "received_by_3_6": False,
        "applied": False,
        "consumed": False,
        "execution_ready": False,
        "target_kylin_qualified": False,
    }
    return result.data, manifest


def _session_document(source, reply, gateway_pid):
    record = source.records[-1]
    caps = reply["payload"]["capabilities"]
    return {
        "status": "SESSION_OPENED",
        "session_id": reply["payload"]["session_id"],
        "accepted_roles": reply["payload"]["accepted_roles"],
        "lease_ms": reply["payload"]["lease_ms"],
        "capabilities": caps,
        "request_bytes_base64": base64.b64encode(record.request_json).decode("ascii"),
        "response_bytes_base64": base64.b64encode(record.reply_json or b"").decode("ascii"),
        "monotonic_started_ns": record.started_ns,
        "monotonic_completed_ns": record.completed_ns,
        "gateway_process": {"pid": gateway_pid, "cmdline": _proc_cmdline(gateway_pid)},
        "source_capability_authorized": False,
        "replacement_ready": caps["replacement_ready"],
    }


def _proc_cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return None


def run_source(output_dir, gateway_pid):
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise FileNotFoundError("output directory must be pre-created by the isolated runner")
    for name in ("session_open.json", "online_prepared.pcap", "online_prepared_manifest.json",
                 "tcpreplay_stdout.txt", "tcpreplay_stderr.txt", "tcpreplay_exit_code.txt"):
        if (output_dir / name).exists():
            raise FileExistsError(f"refusing to overwrite evidence: {output_dir / name}")
    tcpreplay = shutil.which("tcpreplay")
    if not tcpreplay:
        raise FileNotFoundError("tcpreplay executable missing")

    contract = load_contract()
    raw = REFERENCE.read_bytes()
    reference_hash = sha256(raw)
    # Warm the decoder/export dependencies and validate the reference before the 1 s lease starts.
    ref_manifest = loads(REFERENCE_MANIFEST.read_bytes())
    if reference_hash != ref_manifest.get("pcap_sha256"):
        raise ValueError("Round 1 reference SHA256 mismatch")
    history = _history(raw)
    binding = CaptureBinding("reference-eth0", "ETH_0", "PCAP:0:0", "interface-0", "clock-0")
    decoded = HistoryDecoder(contract).decode(raw, history, (binding,), model_id="quadrotor_hil",
                                               declared_ids=(7,))
    if len(decoded.records) != 1 or decoded.records[0].stimulus["message_id"] != 7:
        raise ValueError("Round 1 reference did not decode as one ID7 input")
    processor = ReplayProcessor(contract)
    exporter = ReplayExporter(contract)
    export_binding = (ExportBinding("ETH_0", "eth0", output_name="ETH_0.pcap"),)

    identity = {"run_id": "item-01", "source_id": "item-01", "vehicle_id": "vehicle-01",
                "scenario_id": "item-01", "model_id": "quadrotor_hil", "definition_version": "HIL-ICD-1.0"}
    source = UDPSource(contract, source_bind=SOURCE_ENDPOINT, feedback_bind=FEEDBACK_ENDPOINT,
                       receiver_endpoint=GATEWAY_ENDPOINT, channel="ETH_0")
    session = SourceSession(source, identity, ("CONTROLLER",))
    try:
        reply = session.open()
        write_json_new(output_dir / "session_open.json", _session_document(session, reply, gateway_pid))
        sid = reply["payload"]["session_id"]
        if (sid == 0 or "CONTROLLER" not in reply["payload"]["accepted_roles"]
                or reply["payload"]["lease_ms"] != 1000
                or reply["payload"]["capabilities"]["implemented_message_ids"] != [1]):
            raise ICDError("STATE", "SessionOpened did not match the Round 4 capability boundary")

        try:
            session.allocate_header(7, 201, transaction_id=2)
        except ICDError as error:
            if error.code != "TARGET_MISSING":
                raise
        else:
            raise AssertionError("SourceSession unexpectedly authorized ID7")

        opened_completed_ns = session.records[-1].completed_ns
        start_ns = time.monotonic_ns()
        header = Header(session_id=sid, sequence=2, target_step=201, transaction_id=2, valid_for_ms=100)
        prepared = processor.prepare(raw, history, (binding,), model_id="quadrotor_hil", declared_ids=(7,),
                                     headers=(ReplayHeader(0, header),))
        exported = exporter.export(prepared, export_binding, epoch_ns=time.time_ns())
        file = exported.files[0]
        write_new(output_dir / "online_prepared.pcap", file.data)
        manifest = {
            "manifest_version": "1.0", "status": "ROUND4_ONLINE_PCAP_PREPARED_GATEWAY_ADMISSION_PENDING",
            "source_reference_pcap": "artifacts/history/round1/reference.pcap",
            "source_reference_pcap_sha256": reference_hash, "baseline_sha256": contract.baseline_sha256,
            "replay_mode": prepared.mode, "message_id": 7, "direction": "TO_36", "channel": "ETH_0",
            "header": asdict(header), "payload": decoded.records[0].message["payload"],
            "online_pcap_sha256": sha256(file.data), "packet_count": 1,
            "source_endpoint": {"ipv4": SOURCE_ENDPOINT[0], "udp_port": SOURCE_ENDPOINT[1]},
            "destination_endpoint": {"ipv4": GATEWAY_ENDPOINT[0], "udp_port": GATEWAY_ENDPOINT[1]},
            "header_type": "Gateway Admission Probe Header", "source_capability_authorized": False,
            "gateway_session_admitted": False, "target_step_semantically_qualified": False,
            "process_started": False, "actual_network_tx": False, "received_by_3_6": False,
            "applied": False, "consumed": False, "execution_ready": False, "target_kylin_qualified": False,
        }
        write_json_new(output_dir / "online_prepared_manifest.json", manifest)
        age_ns = time.monotonic_ns() - opened_completed_ns
        if age_ns > LEASE_WINDOW_NS:
            raise ICDError("STALE_SESSION", f"FAIL CURRENT_SESSION_WINDOW: preparation took {age_ns} ns")
        pcap = output_dir / "online_prepared.pcap"
        argv = [tcpreplay, "--intf1=eth0", "--loop=1", "--multiplier=1.0", str(pcap)]
        tx_start_ns = time.monotonic_ns()
        if tx_start_ns - opened_completed_ns > LEASE_WINDOW_NS:
            raise ICDError("STALE_SESSION", "FAIL CURRENT_SESSION_WINDOW before tcpreplay start")
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
        write_new(output_dir / "tcpreplay_stdout.txt", result.stdout.encode("utf-8", "replace"))
        write_new(output_dir / "tcpreplay_stderr.txt", result.stderr.encode("utf-8", "replace"))
        write_new(output_dir / "tcpreplay_exit_code.txt", f"{result.returncode}\n".encode("ascii"))
        write_new(output_dir / "executed_tcpreplay_command.json", canonicalize({
            "argv": ["tcpreplay", "--intf1=eth0", "--loop=1", "--multiplier=1.0", str(pcap)],
            "started_monotonic_ns": tx_start_ns, "session_open_completed_monotonic_ns": opened_completed_ns,
            "session_to_process_start_ns": tx_start_ns - opened_completed_ns,
            "process_started": True, "exit_code": result.returncode,
            "path_translation_only": True, "source_capability_authorized": False,
        }) + b"\n")
        if result.returncode != 0:
            raise RuntimeError(f"tcpreplay exited {result.returncode}")
        return {"status": "PROBE_SENT", "session_id": sid, "tcpreplay_exit_code": result.returncode,
                "session_to_process_start_ns": tx_start_ns - opened_completed_ns}
    finally:
        session.close()
        source.close()


def parse_capture(contract, path, direction, source, destination):
    raw = Path(path).read_bytes()
    capture = CaptureParser().parse(raw, "PCAP")
    wire = WireCodec(contract)
    reassembler = Reassembler(contract, retain_completed=False)
    messages = []
    for packet in capture.packets:
        if (packet.transport != "UDP" or (packet.source_ipv4, packet.source_port) != source
                or (packet.destination_ipv4, packet.destination_port) != destination):
            raise ValueError(f"unexpected capture endpoint/transport in {path}")
        fragment = wire.decode(packet.payload, "UDP", direction=direction)
        result = reassembler.push(fragment, channel="ETH_0", direction=direction,
                                  authorized=True, now_ns=packet.timestamp_ns)
        if result is not None:
            messages.append(result.message)
    if reassembler.pending_count:
        raise ValueError(f"incomplete logical message in {path}")
    return messages, sha256(raw), len(capture.packets)


def validate_ack_sequence(acks, header, session_id):
    if len(acks) != 2:
        raise ValueError("exactly two correlated Gateway admission Acks are required")
    expected = (("RECEIVED", "OK"), ("FAILED", "TARGET_MISSING"))
    previous_sequence = 0
    for ack, (stage, error) in zip(acks, expected):
        payload = ack["payload"]
        if (ack["message_id"] != 130 or ack["header"]["session_id"] != session_id
                or ack["header"]["transaction_id"] != header["transaction_id"]
                or ack["header"]["sequence"] <= previous_sequence
                or payload["request_sequence"] != header["sequence"]
                or payload["request_message_id"] != 7 or payload["probe_id"] != 0
                or payload["stage"] != stage or payload["error"] != error):
            raise ValueError(f"Ack correlation/stage mismatch; expected {stage}/{error}")
        if payload["stage"] in {"APPLIED", "CONSUMED"}:
            raise ValueError("unexpected APPLIED/CONSUMED contradicts current Gateway capability")
        previous_sequence = ack["header"]["sequence"]
    return True


def validate_evidence(output_dir):
    output_dir = Path(output_dir)
    contract = load_contract()
    session = loads((output_dir / "session_open.json").read_bytes())
    manifest = loads((output_dir / "online_prepared_manifest.json").read_bytes())
    environment = loads((output_dir / "environment.json").read_bytes())
    execution = loads((output_dir / "executed_tcpreplay_command.json").read_bytes())
    sid = session["session_id"]
    header = manifest["header"]
    source_messages, request_hash, request_packets = parse_capture(
        contract, output_dir / "request_tx.pcap", "TO_36", SOURCE_ENDPOINT, GATEWAY_ENDPOINT)
    feedback_messages, feedback_hash, feedback_packets = parse_capture(
        contract, output_dir / "gateway_feedback.pcap", "FROM_36", GATEWAY_ENDPOINT, FEEDBACK_ENDPOINT)
    opening = [m for m in source_messages if m["message_id"] == 1]
    probes = [m for m in source_messages if m["message_id"] == 7]
    opened = [m for m in feedback_messages if m["message_id"] == 129]
    acks = [m for m in feedback_messages if m["message_id"] == 130]
    if len(opening) != 1 or len(probes) != 1 or len(opened) != 1 or len(acks) != 2:
        raise ValueError("capture must contain one SessionOpen, one ID7 probe, one SessionOpened, and two Acks")
    open_payload = opening[0]["payload"]
    if (opening[0]["header"]["session_id"] != 0 or opening[0]["header"]["sequence"] != 1
            or "CONTROLLER" not in open_payload["roles"]
            or open_payload["identity"]["model_id"] != "quadrotor_hil"):
        raise ValueError("captured SessionOpen is not the expected real CONTROLLER request")
    probe = probes[0]
    if probe["header"] != header or probe["payload"] != EXPECTED_PAYLOAD:
        raise ValueError("captured probe Header/payload differs from online preparation")
    if (opened[0]["payload"]["session_id"] != sid
            or opened[0]["payload"]["accepted_roles"] != ["CONTROLLER"]
            or opened[0]["payload"]["lease_ms"] != 1000
            or opened[0]["payload"]["capabilities"]["implemented_message_ids"] != [1]):
        raise ValueError("captured SessionOpened differs from the recorded real session")
    if session["capabilities"]["implemented_message_ids"] != [1]:
        raise ValueError("SessionOpened capability boundary changed from [1]")
    if (environment.get("environment_class") != "WSL2_SOFTWARE_ONLY"
            or not environment.get("python_prefix", "").endswith("/envs/uav-history-round4")
            or not environment.get("tcpreplay") or not environment.get("tcpdump")):
        raise ValueError("environment evidence is missing the isolated WSL Conda runtime/tools")
    if (output_dir / "request_tcpdump_exit_code.txt").read_text(encoding="ascii").strip() != "0" \
            or (output_dir / "feedback_tcpdump_exit_code.txt").read_text(encoding="ascii").strip() != "0":
        raise ValueError("request/feedback tcpdump did not complete its packet capture")
    for name in ("source_route.txt", "gateway_route.txt"):
        if "default" in (output_dir / name).read_text(encoding="utf-8").lower():
            raise ValueError("isolated namespace unexpectedly had a default route")
    for name in ("source_ethtool_features.txt", "gateway_ethtool_features.txt"):
        features = (output_dir / name).read_text(encoding="utf-8")
        if "tx-checksum-ip-generic: off" not in features:
            raise ValueError(f"TX checksum offload was not disabled in {name}")

    online_pcap = output_dir / "online_prepared.pcap"
    if sha256(online_pcap.read_bytes()) != manifest["online_pcap_sha256"]:
        raise ValueError("persisted online-prepared PCAP hash differs from its manifest")
    if (execution.get("process_started") is not True or execution.get("exit_code") != 0
            or execution.get("session_to_process_start_ns", LEASE_WINDOW_NS + 1) > LEASE_WINDOW_NS
            or execution.get("argv", [])[1:4] != ["--intf1=eth0", "--loop=1", "--multiplier=1.0"]
            or Path(execution.get("argv", [""])[-1]).name != "online_prepared.pcap"):
        raise ValueError("tcpreplay execution evidence violates the single-send/current-session window")

    validate_ack_sequence(acks, header, sid)
    if (output_dir / "tcpreplay_exit_code.txt").read_text(encoding="ascii").strip() != "0":
        raise ValueError("tcpreplay process did not exit successfully")
    cleanup_path = output_dir / "cleanup_status.json"
    cleanup = loads(cleanup_path.read_bytes())
    if cleanup.get("cleanup_complete") is not True or cleanup.get("host_routes_changed") is not False:
        raise ValueError("isolated network cleanup is incomplete or changed host routes")
    if ((output_dir / "host_route_before.txt").read_bytes()
            != (output_dir / "host_route_after.txt").read_bytes()):
        raise ValueError("host route table differs across the isolated Round 4 run")

    manifest.update({
        "status": "ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED",
        "request_tx_pcap_sha256": request_hash, "request_packet_count": request_packets,
        "gateway_feedback_pcap_sha256": feedback_hash, "gateway_feedback_packet_count": feedback_packets,
        "source_capability_authorized": False, "gateway_session_admitted": True,
        "process_started": True, "actual_network_tx": True, "received_by_3_6": True,
        "received_ack_observed": True, "failed_target_missing_observed": True,
        "applied": False, "consumed": False, "execution_ready": False,
        "target_kylin_qualified": False, "cleanup_complete": True,
        "acks": acks,
    })
    write_new(output_dir / "gateway_feedback.json", canonicalize({
        "session_opened": opened[0], "acks": acks,
        "request_tx_pcap_sha256": request_hash, "gateway_feedback_pcap_sha256": feedback_hash,
        "ack_sequences_strictly_increasing": True,
    }) + b"\n")
    write_new(output_dir / "round4_manifest.json", canonicalize(manifest) + b"\n")
    validation = {
        "schema_version": "1.0", "status": "ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED",
        "stages": {
            "session_open": {"status": "PASS", "session_id": sid, "lease_ms": session["lease_ms"],
                             "accepted_roles": session["accepted_roles"], "implemented_message_ids": [1]},
            "online_pcap": {"status": "PASS", "header": header,
                            "payload_semantics_preserved": probe["payload"] == EXPECTED_PAYLOAD},
            "network": {"status": "PASS", "request_packets": request_packets,
                        "feedback_packets": feedback_packets, "tcpreplay_exit_code": 0},
            "gateway_admission": {"status": "PASS", "acks": acks},
            "cleanup": {"status": "PASS", "cleanup_complete": True},
        },
        "claims": {
            "session_opened": True, "real_session_id": True, "source_capability_authorized": False,
            "online_pcap_prepared": True, "process_started": True, "actual_network_tx": True,
            "received_by_3_6": True, "gateway_session_admitted": True,
            "received_ack_observed": True, "failed_target_missing_observed": True,
            "applied": False, "consumed": False, "execution_ready": False,
            "target_step_semantically_qualified": False, "target_kylin_qualified": False,
        },
    }
    write_new(output_dir / "round4_validation.json", canonicalize(validation) + b"\n")
    summary = {
        "schema_version": "1.0", "status": validation["status"],
        "final_attempt": output_dir.name,
        "evidence_directory": output_dir.relative_to(ROOT).as_posix(),
        "round4_manifest": (output_dir / "round4_manifest.json").relative_to(ROOT).as_posix(),
        "round4_validation": (output_dir / "round4_validation.json").relative_to(ROOT).as_posix(),
        "session_id": sid, "claims": validation["claims"],
    }
    write_new(output_dir.parent / "round4_summary.json", canonicalize(summary) + b"\n")
    return validation


def write_environment(output_dir):
    output_dir = Path(output_dir)
    def command(argv):
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
            return (result.stdout + result.stderr).strip()
        except (OSError, subprocess.TimeoutExpired):
            return None
    os_release = Path("/etc/os-release").read_text(encoding="utf-8") if Path("/etc/os-release").exists() else ""
    value = {
        "schema_version": "1.0", "environment_class": "WSL2_SOFTWARE_ONLY",
        "kernel": command(["uname", "-a"]), "os_release": os_release,
        "python": sys.version, "python_executable": sys.executable,
        "python_prefix": sys.prefix, "iproute2": command(["ip", "-Version"]),
        "tcpreplay": command(["tcpreplay", "--version"]), "tcpdump": command(["tcpdump", "--version"]),
        "ethtool": command(["ethtool", "--version"]), "netns_veth_tx_checksum_offload_disabled": True,
        "conda_prefix": os.environ.get("CONDA_PREFIX") or sys.prefix,
        "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV"), "target_kylin_qualified": False,
    }
    write_json_new(output_dir / "environment.json", value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("source")
    source.add_argument("--output-dir", required=True, type=Path)
    source.add_argument("--gateway-pid", required=True, type=int)
    validate = sub.add_parser("validate")
    validate.add_argument("--output-dir", required=True, type=Path)
    environment = sub.add_parser("environment")
    environment.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "source":
            result = run_source(args.output_dir, args.gateway_pid)
        elif args.command == "validate":
            result = validate_evidence(args.output_dir)
        else:
            result = write_environment(args.output_dir)
        print(json.dumps(result, indent=2))
        return 0
    except (ICDError, OSError, ValueError, RuntimeError, AssertionError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAILED", "error": getattr(error, "code", "STATE"),
                          "detail": str(error)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
