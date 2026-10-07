import dataclasses
import importlib.util
import struct
import binascii

from common import EXPECTED, GOLDEN, INTERFACES, ICDTest


def repair(raw):
    raw = bytearray(raw)
    struct.pack_into("<I", raw, 44, binascii.crc32(raw[:44] + raw[48:]) & 0xffffffff)
    return bytes(raw)


class VideoAvailabilityTests(ICDTest):
    def test_common_video_framing_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_runtime.video"), "video framing missing")


class VideoTests(ICDTest):
    @classmethod
    def setUpClass(cls):
        from icd_runtime.contract import Contract
        from icd_runtime.video import VideoCodec, VideoHeader
        cls.codec = VideoCodec(Contract.load(INTERFACES, expected_sha256=EXPECTED))
        cls.header = VideoHeader(session_id=1, stream_numeric_id=1, frame_index=0,
                                 capture_step=1000, pts_us=0, codec="RAW")

    def test_raw_800_fragments_and_all_existing_video_goldens(self):
        frames = self.codec.encode(bytes(921600), self.header)
        self.assertEqual(len(frames), 800)
        for vector in GOLDEN:
            if vector["transport"] == "VIDEO":
                self.assertEqual(frames[vector["fragment_index"]].hex(), vector["wire_hex"])
        pieces = [self.codec.decode(frame) for frame in frames]
        self.assertEqual(b"".join(p.payload for p in pieces), bytes(921600))
        self.assertTrue(all(p.header == self.header and p.frame_bytes == 921600 for p in pieces))

    def test_h264_h265_fragment_shapes_and_capacity(self):
        for codec in ("H264", "H265"):
            header = dataclasses.replace(self.header, codec=codec, pts_us=18446744073709551615)
            raw = b"\x00\x00\x00\x01" + bytes(2097152 - 4)
            frames = self.codec.encode(raw, header)
            self.assertEqual(len(frames), 1821)
            last = self.codec.decode(frames[-1])
            self.assertEqual(last.header.pts_us, 18446744073709551615)
            self.assertEqual(last.index, 1820)
            self.assertEqual(len(last.payload), 512)
            self.rejects("CAPACITY", lambda: self.codec.encode(raw + b"0", header))

    def test_invalid_raw_size_codec_header_and_empty_data(self):
        self.rejects("SCHEMA", lambda: self.codec.encode(bytes(921599), self.header))
        self.rejects("SCHEMA", lambda: self.codec.encode(b"", self.header))
        for changes in ({"codec": "JPEG"}, {"session_id": 0}, {"stream_numeric_id": 0},
                        {"pts_us": 18446744073709551616}, {"frame_index": -1}, {"session_id": True}):
            header = dataclasses.replace(self.header, **changes)
            self.rejects("SCHEMA", lambda: self.codec.encode(bytes(921600), header))
        self.rejects("SCHEMA", lambda: self.codec.encode(b"not annex b", dataclasses.replace(self.header, codec="H264")))

    def test_reject_crc_version_flags_reserved_and_fragment_length(self):
        raw = self.codec.encode(bytes(921600), self.header)[0]
        self.rejects("CRC", lambda: self.codec.decode(raw[:-1] + b"1"))
        self.rejects("FRAGMENT", lambda: self.codec.decode(raw[:-1]))
        for offset in (0, 4, 6, 42):
            bad = bytearray(raw)
            bad[offset] ^= 1
            self.rejects("VERSION", lambda: self.codec.decode(repair(bad)))
        for offset, value in ((32, 800), (34, 799), (40, 1151)):
            bad = bytearray(raw)
            struct.pack_into("<H", bad, offset, value)
            self.rejects("FRAGMENT", lambda: self.codec.decode(repair(bad)))
        bad = bytearray(raw)
        bad[5] = 99
        self.rejects("SCHEMA", lambda: self.codec.decode(repair(bad)))
