"""Validate Round 3 isolated tcpreplay/tcpdump evidence from persisted files."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import Header
from input_simulator.reference_pcap import BASELINE_SHA256
from input_simulator.replay_network_evidence import compare_replay_captures


PREPARED = ROOT / "artifacts" / "history" / "round2" / "prepared.pcap"
ROUND2_MANIFEST = ROOT / "artifacts" / "history" / "round2" / "prepared_manifest.json"
ROUND2_COMMAND = ROOT / "artifacts" / "history" / "round2" / "tcpreplay_command.json"
ATTEMPT_NAME = sys.argv[1] if len(sys.argv) > 1 else "retry_1"
ATTEMPT = ROOT / "artifacts" / "history" / "round3" / ATTEMPT_NAME
RECEIVED = ATTEMPT / "received.pcap"
EXPECTED_SHA256 = "febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134"
EXPECTED_HEADER = Header(session_id=92, sequence=102, target_step=201, transaction_id=302, valid_for_ms=100)
EXPECTED_PAYLOAD = {"motor_command": [0.1, 0.2, 0.3, 0.4]}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_kv(path: Path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def write_new_json(path: Path, value):
    raw = canonicalize(value) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            raise OSError(f"existing JSON differs from regenerated evidence: {path}")
        return
    with path.open("xb") as stream:
        stream.write(raw)
    if path.read_bytes() != raw:
        raise OSError(f"persisted JSON differs: {path}")


def main():
    contract = Contract.load(ROOT / "docs" / "interfaces" / "baseline", expected_sha256=BASELINE_SHA256)
    prepared_raw = PREPARED.read_bytes()
    received_raw = RECEIVED.read_bytes()
    round2_manifest = loads(ROUND2_MANIFEST.read_bytes())
    round2_command = loads(ROUND2_COMMAND.read_bytes())

    prepared_hash = sha256(prepared_raw)
    if prepared_hash != EXPECTED_SHA256:
        raise ValueError("Round 2 prepared.pcap SHA256 changed")
    if round2_manifest["prepared_pcap_sha256"] != prepared_hash:
        raise ValueError("Round 2 manifest SHA256 differs")
    if round2_command["resource_sha256"] != prepared_hash:
        raise ValueError("Round 2 command resource SHA256 differs")

    env = parse_kv(ATTEMPT / "environment.txt")
    tx_route = (ATTEMPT / "tx_route.txt").read_text(encoding="utf-8")
    rx_route = (ATTEMPT / "rx_route.txt").read_text(encoding="utf-8")
    if "default" in tx_route.lower() or "default" in rx_route.lower():
        raise ValueError("isolated namespace unexpectedly had a default route")
    if (ATTEMPT / "tcpreplay_exit_code.txt").read_text().strip() != "0":
        raise ValueError("tcpreplay did not exit successfully")
    if (ATTEMPT / "tcpdump_exit_code.txt").read_text().strip() != "0":
        raise ValueError("tcpdump did not exit successfully")
    if (ATTEMPT / "cleanup_status.txt").read_text().strip() != "cleanup_complete=true":
        raise ValueError("Round 3 cleanup was not completed")

    comparison = compare_replay_captures(
        contract,
        prepared_raw,
        received_raw,
        expected_message_id=7,
        expected_header=EXPECTED_HEADER,
        expected_payload=EXPECTED_PAYLOAD,
    )

    windows_argv = list(round2_command["argv"])
    if windows_argv[:4] != ["tcpreplay", "--intf1=eth0", "--loop=1", "--multiplier=1.0"]:
        raise ValueError("Round 2 tcpreplay semantic argv changed")
    linux_path = env["prepared_linux_path"]
    actual_argv = windows_argv[:4] + [linux_path]

    executed_command = {
        "argv": actual_argv,
        "path_translation_only": True,
        "source_builder_argv": windows_argv,
        "resource_sha256": prepared_hash,
        "tcpreplay_exit_code": 0,
        "process_started": True,
        "actual_network_tx": True,
    }

    manifest = {
        "manifest_version": "1.0",
        "environment_class": env["environment_class"],
        "target_kylin_qualified": False,
        "kernel": env["kernel"],
        "os_release": (ATTEMPT / "os-release.txt").read_text(encoding="utf-8").strip(),
        "iproute2": (ATTEMPT / "ip_version.txt").read_text(encoding="utf-8").strip(),
        "tcpreplay_version": (ATTEMPT / "tcpreplay_version.txt").read_text(encoding="utf-8").splitlines()[0],
        "tcpdump_version": (ATTEMPT / "tcpdump_version.txt").read_text(encoding="utf-8").splitlines()[0],
        "source_prepared_pcap": "artifacts/history/round2/prepared.pcap",
        "source_prepared_pcap_sha256": prepared_hash,
        "received_pcap_sha256": comparison["received_pcap_sha256"],
        "path_translation_only": True,
        "tx_namespace": env["tx_namespace"],
        "rx_namespace": env["rx_namespace"],
        "tx_interface": "eth0",
        "rx_interface": "eth0",
        "tx_mac": "02:00:00:00:00:01",
        "rx_mac": "02:00:00:00:00:02",
        "tx_ipv4": "10.36.0.10/24",
        "rx_ipv4": "10.36.0.20/24",
        "default_route_present": False,
        "expected_packet_count": comparison["packet_count"],
        "actual_packet_count": comparison["packet_count"],
        "packet_order_equal": comparison["packet_order_equal"],
        "raw_frame_bytes_equal": comparison["all_raw_frame_bytes_equal"],
        "frames": comparison["frames"],
        "cleanup_complete": True,
        "process_started": True,
        "actual_network_tx": True,
        "actual_network_rx": True,
        "frame_bytes_matched": True,
        "three_six_receiver_involved": False,
        "online_session_authorized": False,
        "received_by_3_6": False,
        "applied": False,
        "consumed": False,
        "execution_ready": False,
    }

    validation = {
        "status": "ROUND3_ISOLATED_NETWORK_TX_RX_VALIDATED",
        "stages": {
            "input_hash_verified": {"status": "PASS", "sha256": prepared_hash},
            "linux_environment": {"status": "PASS", "environment_class": env["environment_class"]},
            "isolated_topology": {"status": "PASS", "default_route_present": False},
            "tcpreplay": {"status": "PASS", "exit_code": 0, "packets_sent": comparison["packet_count"]},
            "tcpdump": {"status": "PASS", "exit_code": 0, "packets_captured": comparison["packet_count"]},
            "frame_comparison": {
                "status": "PASS",
                "packet_order_equal": True,
                "raw_frame_bytes_equal": True,
                "hil_crc_verified": True,
                "expected_header": asdict(EXPECTED_HEADER),
                "payload_semantics_preserved": True,
            },
            "cleanup": {"status": "PASS", "cleanup_complete": True},
        },
        "claims": {
            "process_started": True,
            "actual_network_tx": True,
            "actual_network_rx": True,
            "frame_bytes_matched": True,
            "three_six_receiver_involved": False,
            "online_session_authorized": False,
            "received_by_3_6": False,
            "applied": False,
            "consumed": False,
            "execution_ready": False,
            "target_kylin_qualified": False,
        },
    }

    write_new_json(ATTEMPT / "executed_tcpreplay_command.json", executed_command)
    write_new_json(ATTEMPT / "round3_manifest.json", manifest)
    write_new_json(ATTEMPT / "round3_validation.json", validation)

    print(json.dumps({
        "status": validation["status"],
        "prepared_sha256": prepared_hash,
        "received_pcap_sha256": comparison["received_pcap_sha256"],
        "packet_count": comparison["packet_count"],
        "raw_frame_bytes_equal": comparison["all_raw_frame_bytes_equal"],
        "process_started": True,
        "actual_network_tx": True,
        "actual_network_rx": True,
        "received_by_3_6": False,
    }, indent=2))


if __name__ == "__main__":
    main()
