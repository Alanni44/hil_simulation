from dataclasses import FrozenInstanceError
from fractions import Fraction
import importlib.util
import struct
import unittest

from scapy.layers.inet import IP, TCP, UDP
from scapy.layers.l2 import Dot1Q, Ether

from icd_runtime.errors import ICDError


def ethernet(payload=b"hello", *, tcp=False, vlan=None, **ip_fields):
    packet = Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02")
    if vlan is not None:
        packet /= Dot1Q(vlan=vlan)
    packet /= IP(src="10.36.0.10", dst="10.36.0.20", **ip_fields)
    packet /= (TCP(sport=36102, dport=36100) if tcp else UDP(sport=36102, dport=36100))
    return bytes(packet / payload)


def socketcan(data=b"\x01\x02", *, fd=False, can_id=0x600, flags=0, fd_flags=5):
    return struct.pack(">IBBBB", can_id | flags, len(data), fd_flags if fd else 0, 0, 0) + data.ljust(64 if fd else 8, b"\x00")


def pcap(packets=None, *, linktype=1, endian="<", nano=False, caplen=None, wirelen=None):
    packets = [(1, 123, ethernet())] if packets is None else packets
    magic = 0xA1B23C4D if nano else 0xA1B2C3D4
    result = struct.pack(endian + "IHHIIII", magic, 2, 4, 0, 0, 65535, linktype)
    for sec, fraction, raw in packets:
        result += struct.pack(endian + "IIII", sec, fraction,
                              len(raw) if caplen is None else caplen,
                              len(raw) if wirelen is None else wirelen) + raw
    return result


def option(code, value, endian="<"):
    return struct.pack(endian + "HH", code, len(value)) + value + b"\x00" * (-len(value) % 4)


def block(kind, body, endian="<"):
    length = len(body) + 12
    return struct.pack(endian + "II", kind, length) + body + struct.pack(endian + "I", length)


def shb(endian="<"):
    return block(0x0A0D0D0A, struct.pack(endian + "IHHq", 0x1A2B3C4D, 1, 0, -1), endian)


def idb(linktype=1, *, endian="<", name=b"eth0", resolution=9, offset=0, extra=b""):
    opts = option(2, name, endian) + option(9, bytes([resolution]), endian)
    if offset:
        opts += option(14, struct.pack(endian + "q", offset), endian)
    return block(1, struct.pack(endian + "HHI", linktype, 0, 65535) + opts + extra + b"\x00" * 4, endian)


def epb(raw=None, *, endian="<", interface=0, ticks=1_000_000_123, wirelen=None, opts=b""):
    raw = ethernet() if raw is None else raw
    body = struct.pack(endian + "IIIII", interface, ticks >> 32, ticks & 0xffffffff,
                       len(raw), len(raw) if wirelen is None else wirelen)
    return block(6, body + raw + b"\x00" * (-len(raw) % 4) + opts + b"\x00" * 4, endian)


def pcapng(raw=None, **kwargs):
    return shb() + idb() + epb(raw, **kwargs)


class CaptureTests(unittest.TestCase):
    def parse(self, raw, fmt="PCAP", **limits):
        from input_simulator.capture import CaptureParser
        return CaptureParser(**limits).parse(raw, fmt)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as error:
            action()
        self.assertEqual(error.exception.code, code)

    def test_parser_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.capture"), "actual capture parser missing")

    def test_can_log_original_tool_parses_can_and_fd_with_exact_unix_ns(self):
        line = b"(1770000000.000000001) can0 600#0102 R\n"
        fd = b"(1770000000.000000002) canfd0 307##5" + bytes(range(64)).hex().encode() + b" T\n"
        result = self.parse(line + fd, "CAN_LOG")
        self.assertEqual(len(result.packets), 2)
        first, last = result.packets
        self.assertEqual(first.timestamp_ns, 1770000000000000001)
        self.assertEqual(last.timestamp_ns, 1770000000000000002)
        self.assertEqual(first.time_resolution_ns, Fraction(1))
        self.assertEqual(first.raw_bytes, line)
        self.assertEqual(last.raw_bytes, fd)
        self.assertEqual(first.capture_interface, "can0")
        self.assertEqual(first.capture_direction, "INBOUND")
        self.assertEqual(last.capture_direction, "OUTBOUND")
        self.assertEqual(first.transport, "CAN")
        self.assertEqual(last.transport, "CANFD")
        self.assertEqual(last.can.data, bytes(range(64)))
        self.assertTrue(last.can.bitrate_switch)

    def test_can_log_preserves_remote_extended_error_and_esi_for_later_qualification(self):
        raw = b"(0.000000) can0 00000600#R8\n(0.000001) canfd0 600##700\n(0.000002) can0 20000080#0000000000000000\n"
        packets = self.parse(raw, "CAN_LOG").packets
        self.assertTrue(packets[0].can.is_extended_id)
        self.assertTrue(packets[0].can.is_remote_frame)
        self.assertEqual(packets[0].can.dlc, 8)
        self.assertTrue(packets[1].can.error_state_indicator)
        self.assertTrue(packets[2].can.is_error_frame)

    def test_can_log_malformed_precision_flags_and_lengths_rejected(self):
        for raw in (b"\n", b"(nan) can0 600#00\n", b"(-1) can0 600#00\n",
                    b"(1.0000000001) can0 600#00\n", b"(1) can0 600#0\n",
                    b"(1) can0 600##9ff\n", b"(1) can0 600#010203040506070809\n",
                    b"(1) can0 600##5010203040506070809\n", b"(1) can0 900#01\n",
                    b"(18446744074) can0 600#00\n", b"(1) can0 600#00 X\n", b"\xff\n"):
            with self.subTest(raw=raw):
                self.rejects("RESOURCE", lambda: self.parse(raw, "CAN_LOG"))

    def test_pcap_all_endian_and_micro_nano_timestamp_combinations(self):
        for endian in ("<", ">"):
            for nano in (False, True):
                raw_packet = ethernet()
                packet = self.parse(pcap([(1770000000, 123, raw_packet)], endian=endian, nano=nano)).packets[0]
                self.assertEqual(packet.timestamp_ns, 1770000000000000000 + 123 * (1 if nano else 1000))
                self.assertEqual(packet.time_resolution_ns, Fraction(1 if nano else 1000))
                self.assertEqual(packet.raw_bytes, raw_packet)
                self.assertEqual(packet.payload, b"hello")
                self.assertEqual(packet.transport, "UDP")
                self.assertEqual((packet.source_ipv4, packet.destination_ipv4, packet.source_port,
                                  packet.destination_port), ("10.36.0.10", "10.36.0.20", 36102, 36100))
                self.assertTrue(packet.transport_checksum_verified)

    def test_pcap_ng_multi_interface_and_multiple_sections_do_not_share_clock_domain(self):
        first = shb() + idb() + idb(227, name=b"canfd0")
        first += epb(ethernet()) + epb(socketcan(bytes(range(64)), fd=True), interface=1)
        second = shb(">") + idb(227, endian=">", name=b"can0", resolution=6)
        second += epb(socketcan(), endian=">", ticks=123)
        result = self.parse(first + second, "PCAPNG")
        self.assertEqual([p.transport for p in result.packets], ["UDP", "CANFD", "CAN"])
        self.assertEqual(result.packets[-1].timestamp_ns, 123000)
        self.assertEqual(len({p.clock_domain for p in result.packets}), 3)
        self.assertEqual(result.packets[-1].capture_interface, "can0")
        self.assertEqual(result.packets[1].can.data, bytes(range(64)))

    def test_pcap_ng_exact_offset_binary_resolution_and_direction(self):
        raw = shb() + idb(resolution=0x80 | 10, offset=2)
        raw += epb(ticks=512, opts=option(2, struct.pack("<I", 2)))
        packet = self.parse(raw, "PCAPNG").packets[0]
        self.assertEqual(packet.timestamp_ns, 2500000000)
        self.assertEqual(packet.time_resolution_ns, Fraction(1_000_000_000, 1024))
        self.assertEqual(packet.capture_direction, "OUTBOUND")

    def test_pcap_ng_sub_ns_timestamp_and_overflow_rejected_without_rounding(self):
        for raw in (shb() + idb(resolution=10) + epb(ticks=1),
                    shb() + idb(resolution=0) + epb(ticks=0xffffffffffffffff),
                    shb() + idb(offset=-2) + epb(ticks=1)):
            self.rejects("RESOURCE", lambda: self.parse(raw, "PCAPNG"))

    def test_pcap_and_ng_wire_truncation_is_preserved_not_fabricated(self):
        raw_packet = ethernet()[:20]
        for fmt, raw in (("PCAP", pcap([(1, 0, raw_packet)], wirelen=100)),
                         ("PCAPNG", pcapng(raw_packet, wirelen=100))):
            result = self.parse(raw, fmt)
            self.assertEqual(result.observed_truncated_packets, 1)
            self.assertEqual(result.packets[0].raw_bytes, raw_packet)
            self.assertEqual(result.packets[0].transport, "UNDECODED_TRUNCATED")
            self.assertEqual(result.packets[0].payload, b"")

    def test_pcap_ng_actual_drop_metadata_is_preserved(self):
        raw = pcapng(opts=option(4, struct.pack("<Q", 3)))
        stats = struct.pack("<III", 0, 0, 2000000000) + option(5, struct.pack("<Q", 5)) + b"\x00" * 4
        raw += block(5, stats)
        result = self.parse(raw, "PCAPNG")
        self.assertEqual(result.observed_lost_packets, 5)
        self.assertEqual(result.packets[0].reported_drop_count, 3)
        self.assertTrue(result.loss_count_is_lower_bound)

    def test_malformed_container_or_trailing_bytes_never_become_eof_success(self):
        for fmt, good in (("PCAP", pcap()), ("PCAPNG", pcapng())):
            for raw in (good[:3], good[:-1], good + b"x", good + b"\x00" * 8):
                with self.subTest(fmt=fmt, size=len(raw)):
                    self.rejects("RESOURCE", lambda: self.parse(raw, fmt))
        bad = bytearray(pcapng())
        bad[-4:] = struct.pack("<I", 12)
        self.rejects("RESOURCE", lambda: self.parse(bytes(bad), "PCAPNG"))

    def test_pcap_ng_unknown_interface_duplicate_option_and_no_timestamp_block_fail_closed(self):
        for raw in (shb() + idb() + epb(interface=1),
                    shb() + idb(extra=option(9, b"\x06")) + epb(),
                    shb() + idb() + block(3, struct.pack("<I", 4) + b"abcd")):
            with self.assertRaises(ICDError):
                self.parse(raw, "PCAPNG")
        self.rejects("UNSUPPORTED", lambda: self.parse(shb() + idb() + block(0x9999, b"abcd"), "PCAPNG"))

    def test_unknown_linktype_and_format_mismatch_are_not_inferred_from_filename(self):
        self.rejects("UNSUPPORTED", lambda: self.parse(pcap(linktype=101)))
        self.rejects("RESOURCE", lambda: self.parse(pcapng(), "PCAP"))
        self.rejects("RESOURCE", lambda: self.parse(pcap(), "PCAPNG"))
        self.rejects("UNSUPPORTED", lambda: self.parse(pcap(), "JSON"))

    def test_pcap_timestamp_caplen_snaplen_and_version_are_validated(self):
        bad_headers = ((4, "H", 3), (16, "I", 10), (24 + 4, "I", 1000000),
                       (24 + 8, "I", 99999999), (24 + 12, "I", 1))
        for offset, kind, value in bad_headers:
            bad = bytearray(pcap())
            struct.pack_into("<" + kind, bad, offset, value)
            self.rejects("RESOURCE", lambda: self.parse(bytes(bad)))

    def test_socketcan_metadata_and_length_are_preserved_for_later_formal_gate(self):
        for raw in (socketcan(), socketcan(bytes(range(64)), fd=True), socketcan(flags=0x80000000)):
            result = self.parse(pcap([(1, 0, raw)], linktype=227))
            self.assertEqual(result.packets[0].raw_bytes, raw)
            self.assertEqual(result.packets[0].can.data, raw[8:8 + raw[4]])
            self.assertEqual(result.packets[0].can.is_extended_id, bool(raw[0] & 0x80))
        bad = bytearray(socketcan(fd=True))
        bad[5] = 0x85
        self.rejects("RESOURCE", lambda: self.parse(pcap([(1, 0, bytes(bad))], linktype=227)))

    def test_vlan_tcp_and_zero_udp_checksum_are_explicit_analysis_metadata(self):
        for tcp in (False, True):
            packet = self.parse(pcap([(1, 0, ethernet(tcp=tcp, vlan=123))])).packets[0]
            self.assertEqual(packet.vlan_id, 123)
            self.assertEqual(packet.transport, "TCP_ANALYSIS_ONLY" if tcp else "UDP")
            self.assertTrue(packet.transport_checksum_verified)
        raw = bytearray(ethernet())
        raw[40:42] = b"\x00\x00"
        packet = self.parse(pcap([(1, 0, bytes(raw))])).packets[0]
        self.assertFalse(packet.transport_checksum_verified)

    def test_bad_ip_transport_checksum_fragment_or_lengths_are_rejected(self):
        raw = ethernet()
        for offset in (24, 40, len(raw) - 1):
            bad = bytearray(raw)
            bad[offset] ^= 1
            self.rejects("RESOURCE", lambda: self.parse(pcap([(1, 0, bytes(bad))])))
        self.rejects("UNSUPPORTED", lambda: self.parse(pcap([(1, 0, ethernet(flags="MF"))])))
        self.rejects("RESOURCE", lambda: self.parse(pcap([(1, 0, raw[:30])])) )

    def test_container_results_are_immutable_keep_original_order_and_never_executable(self):
        result = self.parse(pcap([(2, 0, ethernet()), (1, 0, ethernet())]))
        self.assertEqual([p.timestamp_ns for p in result.packets], [2000000000, 1000000000])
        with self.assertRaises(FrozenInstanceError):
            result.packets[0].timestamp_ns = 0
        self.assertFalse(result.execution_ready)
        self.assertFalse(result.history_decoded)

    def test_capture_bytes_packet_limits_and_invalid_limit_types(self):
        self.rejects("CAPACITY", lambda: self.parse(pcap(), max_bytes=16))
        self.rejects("CAPACITY", lambda: self.parse(pcap([(1, 0, ethernet()), (2, 0, ethernet())]), max_packets=1))
        self.rejects("CAPACITY", lambda: self.parse(pcap(), max_packets=True))
        self.rejects("RESOURCE", lambda: self.parse(bytearray(pcap())))
        self.rejects("RESOURCE", lambda: self.parse(b"", "CAN_LOG"))

    def test_metadata_only_sections_have_an_independent_capacity_bound(self):
        self.rejects("CAPACITY", lambda: self.parse(shb() * 101, "PCAPNG"))

    def test_metadata_options_and_interfaces_have_independent_capacity_bounds(self):
        self.rejects("CAPACITY", lambda: self.parse(shb() + idb() * 101 + epb(), "PCAPNG"))
        many_comments = option(1, b"") * 1025
        self.rejects("CAPACITY", lambda: self.parse(shb() + idb(extra=many_comments) + epb(), "PCAPNG"))
        large_comment = option(1, b"x" * 65535)
        self.rejects("CAPACITY", lambda: self.parse(shb() + idb(extra=large_comment) + epb(), "PCAPNG"))

    def test_can_log_rejects_raw_rtr_flags_with_fd_or_data(self):
        for raw in (b"(1) can0 40000600##501\n", b"(1) can0 40000600#01\n"):
            self.rejects("RESOURCE", lambda: self.parse(raw, "CAN_LOG"))

    def test_error_frames_require_classic_can_eight_bytes_and_no_rtr(self):
        for raw in (b"(1) can0 20000080#01\n", b"(1) can0 20000080##50000000000000000\n",
                    b"(1) can0 60000080#R8\n"):
            self.rejects("RESOURCE", lambda: self.parse(raw, "CAN_LOG"))
        for raw in (socketcan(flags=0x20000000), socketcan(b"\x00" * 8, fd=True, flags=0x20000000),
                    socketcan(b"\x00" * 8, flags=0x60000000)):
            self.rejects("RESOURCE", lambda: self.parse(pcap([(1, 0, raw)], linktype=227)))
        good = socketcan(b"\x00" * 8, can_id=0x80, flags=0x20000000)
        self.assertTrue(self.parse(pcap([(1, 0, good)], linktype=227)).packets[0].can.is_error_frame)

    def test_classic_len8_dlc_is_explicitly_unsupported_not_invalid_reserved_data(self):
        raw = bytearray(socketcan(b"\x00" * 8))
        raw[7] = 15
        self.rejects("UNSUPPORTED", lambda: self.parse(pcap([(1, 0, bytes(raw))], linktype=227)))
        self.rejects("UNSUPPORTED", lambda: self.parse(b"(1) can0 600#0000000000000000_F\n", "CAN_LOG"))
