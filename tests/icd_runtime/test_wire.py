import dataclasses
import importlib.util
import struct
import binascii

from common import EXPECTED, FIXTURES, GOLDEN, INTERFACES, ICDTest, message


def repair_udp(raw):
    raw = bytearray(raw)
    struct.pack_into("<I", raw, 36, binascii.crc32(raw[:36] + raw[40:]) & 0xffffffff)
    return bytes(raw)


class WireAvailabilityTests(ICDTest):
    def test_wire_codec_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_runtime.wire"), "common framing is missing")


class WireTests(ICDTest):
    @classmethod
    def setUpClass(cls):
        from icd_runtime.contract import Contract
        from icd_runtime.wire import WireCodec
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.wire = WireCodec(cls.contract)

    def test_all_business_golden_fragments_byte_exact(self):
        for vector in GOLDEN:
            if vector["transport"] == "VIDEO":
                continue
            with self.subTest(mid=vector["message_id"], transport=vector["transport"], index=vector["fragment_index"]):
                frames = self.wire.encode(message(vector["message_id"]), vector["transport"])
                raw = frames[vector["fragment_index"]]
                if vector["transport"] == "CANFD":
                    self.assertEqual(raw.arbitration_id, vector["can_id"])
                    self.assertTrue(raw.is_fd and raw.bitrate_switch)
                    self.assertFalse(raw.is_extended_id)
                    raw = raw.data
                self.assertEqual(raw.hex(), vector["wire_hex"])

    def test_decode_every_logical_message_fragment(self):
        from dataclasses import asdict
        from icd_runtime.payload import PayloadCodec
        codec = PayloadCodec(self.contract)
        for mid, value in FIXTURES.items():
            for transport in self.contract.entry(mid)["transports"]:
                frames = self.wire.encode(value, transport)
                fragments = [self.wire.decode(f, transport, direction=self.contract.entry(mid)["direction"]) for f in frames]
                self.assertEqual(b"".join(f.payload for f in fragments), codec.encode(mid, value["payload"]))
                for fragment in fragments:
                    self.assertEqual(asdict(fragment.header), value["header"])
                    self.assertEqual(fragment.count, len(frames))

    def test_crc_reference_check_values(self):
        from icd_runtime.wire import crc16, crc32
        self.assertEqual(crc16(b"123456789"), 0x29b1)
        self.assertEqual(crc32(b"123456789"), 0xcbf43926)

    def test_crc_and_truncation_rejected(self):
        udp = self.wire.encode(message(8), "UDP")[0]
        self.rejects("CRC", lambda: self.wire.decode(udp[:-1] + bytes([udp[-1] ^ 1]), "UDP"))
        self.rejects("FRAGMENT", lambda: self.wire.decode(udp[:-1], "UDP"))
        can = self.wire.encode(message(8), "CANFD")[0]
        bad = dataclasses.replace(can, data=can.data[:-1] + bytes([can.data[-1] ^ 1]))
        self.rejects("CRC", lambda: self.wire.decode(bad, "CANFD"))
        self.rejects("FRAGMENT", lambda: self.wire.decode(dataclasses.replace(can, data=can.data[:63]), "CANFD"))

    def test_udp_magic_version_flags_reserved_and_ids(self):
        raw = self.wire.encode(message(7), "UDP")[0]
        for offset in (0, 4, 5, 6, 34):
            bad = bytearray(raw)
            bad[offset] ^= 1
            self.rejects("VERSION", lambda: self.wire.decode(repair_udp(bad), "UDP"))
        bad = bytearray(raw)
        struct.pack_into("<H", bad, 32, 46)
        self.rejects("UNSUPPORTED", lambda: self.wire.decode(repair_udp(bad), "UDP"))
        self.rejects("AUTHORIZATION", lambda: self.wire.decode(raw, "UDP", direction="FROM_36"))

    def test_udp_fragment_indexes_counts_and_payload_lengths(self):
        raw = self.wire.encode(message(3), "UDP")[0]
        for offset, value in ((24, 3), (26, 0), (26, 58), (28, 1159)):
            bad = bytearray(raw)
            struct.pack_into("<H", bad, offset, value)
            self.rejects("FRAGMENT", lambda: self.wire.decode(repair_udp(bad), "UDP"))
        # A short non-last chunk is invalid even with a consistent header and CRC.
        bad = bytearray(raw[:-1])
        struct.pack_into("<H", bad, 28, 1159)
        self.rejects("FRAGMENT", lambda: self.wire.decode(repair_udp(bad), "UDP"))
        bad = bytearray(self.wire.encode(message(7), "UDP")[0])
        struct.pack_into("<H", bad, 26, 2)
        self.rejects("FRAGMENT", lambda: self.wire.decode(repair_udp(bad), "UDP"))

    def test_can_transport_attributes_and_padding_rejected(self):
        from icd_runtime.wire import crc16
        frame = self.wire.encode(message(2), "CANFD")[0]
        for changes in ({"is_fd": False}, {"bitrate_switch": False}, {"is_extended_id": True}, {"is_remote_frame": True}):
            self.rejects("SCHEMA", lambda: self.wire.decode(dataclasses.replace(frame, **changes), "CANFD"))
        self.rejects("UNSUPPORTED", lambda: self.wire.decode(dataclasses.replace(frame, arbitration_id=0x600), "CANFD"))
        bad = bytearray(frame.data)
        bad[40] = 1
        struct.pack_into("<H", bad, 62, crc16(struct.pack("<H", frame.arbitration_id) + bad[:62]))
        self.rejects("FRAGMENT", lambda: self.wire.decode(dataclasses.replace(frame, data=bytes(bad)), "CANFD"))

    def test_json_cannot_be_sent_over_can_and_no_unknown_transport(self):
        self.rejects("UNSUPPORTED", lambda: self.wire.encode(message(1), "CANFD"))
        self.rejects("UNSUPPORTED", lambda: self.wire.encode(message(7), "TCP"))

    def test_wire_headers_checked_before_payload_reassembly(self):
        raw = self.wire.encode(message(7), "UDP")[0]
        for offset, value, code, fmt in ((8, 0, "STALE_SESSION", "I"), (12, 0, "SCHEMA", "I"),
                                        (20, 0, "SCHEMA", "I"), (30, 101, "SCHEMA", "H")):
            bad = bytearray(raw)
            struct.pack_into("<" + fmt, bad, offset, value)
            self.rejects(code, lambda: self.wire.decode(repair_udp(bad), "UDP"))

    def test_integral_json_header_numbers_encode_without_struct_errors(self):
        value = message(7)
        value["header"] = {key: float(number) for key, number in value["header"].items()}
        for transport in ("UDP", "CANFD"):
            raw = self.wire.encode(value, transport)
            self.assertEqual(self.wire.decode(raw[0], transport).header.sequence, 7)

    def test_udp_65536_byte_capacity_requires_a_576_byte_final_chunk(self):
        from icd_runtime.wire import UDP_HEADER, crc32
        def packet(length):
            prefix = UDP_HEADER.pack(b"HIL1", 1, 0, 0, 1, 3, 1000, 3, 56, 57, length, 1000, 3, 0)
            payload = bytes(length)
            return prefix + struct.pack("<I", crc32(prefix + payload)) + payload
        fragment = self.wire.decode(packet(576), "UDP")
        self.assertEqual(fragment.reservation_bytes, 65536)
        self.rejects("FRAGMENT", lambda: self.wire.decode(packet(577), "UDP"))
