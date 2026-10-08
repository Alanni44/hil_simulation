"""Pure capture comparison for isolated replay network evidence.

This module does not send packets or open interfaces. It compares persisted
PCAP captures using the existing parser and formal WireCodec.
"""

from dataclasses import asdict
import hashlib

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from icd_runtime.errors import ICDError
from icd_runtime.wire import Header, WireCodec
from .capture import CaptureParser


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compare_replay_captures(
    contract,
    prepared_raw: bytes,
    received_raw: bytes,
    *,
    expected_message_id: int | None = None,
    expected_header: Header | None = None,
    expected_payload: dict | None = None,
):
    """Compare prepared and actually received Ethernet PCAPs packet-by-packet.

    Container bytes/timestamps are allowed to differ. Ethernet frame bytes,
    order, UDP payloads and formal HIL decoding must match exactly.
    """
    if type(prepared_raw) is not bytes or type(received_raw) is not bytes:
        raise ICDError("RESOURCE", "capture comparison requires immutable PCAP bytes")
    if not prepared_raw or not received_raw:
        raise ICDError("RESOURCE", "capture comparison requires nonempty PCAP bytes")

    prepared = CaptureParser().parse(prepared_raw, "PCAP")
    received = CaptureParser().parse(received_raw, "PCAP")
    if len(prepared.packets) != len(received.packets) or not prepared.packets:
        raise ICDError("RESOURCE", "TX/RX packet count differs or is empty")

    wire = WireCodec(contract)
    frames = []
    for index, (tx, rx) in enumerate(zip(prepared.packets, received.packets)):
        if tx.linktype != 1 or rx.linktype != 1:
            raise ICDError("RESOURCE", "Round 3 requires Ethernet linktype PCAPs")
        if tx.transport != "UDP" or rx.transport != "UDP":
            raise ICDError("RESOURCE", "Round 3 expected UDP Ethernet packets")
        if tx.raw_bytes != rx.raw_bytes:
            raise ICDError("RESOURCE", f"TX/RX raw Ethernet frame differs at packet {index}")
        if tx.payload != rx.payload:
            raise ICDError("RESOURCE", f"TX/RX UDP payload differs at packet {index}")
        if not tx.transport_checksum_verified or not rx.transport_checksum_verified:
            raise ICDError("RESOURCE", f"transport checksum verification failed at packet {index}")

        fragment = wire.decode(rx.payload, "UDP", direction="TO_36")
        payload = wire.payload_codec.decode(fragment.message_id, fragment.payload)
        if expected_message_id is not None and fragment.message_id != expected_message_id:
            raise ICDError("RESOURCE", "received HIL message id differs from expected")
        if expected_header is not None and fragment.header != expected_header:
            raise ICDError("RESOURCE", "received HIL header differs from expected")
        if expected_payload is not None and payload != expected_payload:
            raise ICDError("RESOURCE", "received business payload differs from expected")

        eth = Ether(rx.raw_bytes)
        ip = eth[IP]
        udp = eth[UDP]
        frames.append({
            "index": index,
            "tx_timestamp_ns": str(tx.timestamp_ns),
            "rx_timestamp_ns": str(rx.timestamp_ns),
            "raw_frame_sha256": _sha256(rx.raw_bytes),
            "udp_payload_sha256": _sha256(rx.payload),
            "source_mac": eth.src,
            "destination_mac": eth.dst,
            "ether_type": int(eth.type),
            "source_ipv4": ip.src,
            "destination_ipv4": ip.dst,
            "ip_total_length": int(ip.len),
            "ip_checksum": int(ip.chksum),
            "source_udp_port": int(udp.sport),
            "destination_udp_port": int(udp.dport),
            "udp_length": int(udp.len),
            "udp_checksum": int(udp.chksum),
            "message_id": fragment.message_id,
            "direction": fragment.direction,
            "header": asdict(fragment.header),
            "fragment_index": fragment.index,
            "fragment_count": fragment.count,
            "business_payload": payload,
            "hil_crc_verified": True,
            "raw_frame_bytes_equal": True,
        })

    return {
        "packet_count": len(frames),
        "packet_order_equal": True,
        "all_raw_frame_bytes_equal": True,
        "prepared_pcap_sha256": _sha256(prepared_raw),
        "received_pcap_sha256": _sha256(received_raw),
        "frames": frames,
    }
