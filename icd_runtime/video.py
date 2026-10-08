"""HIV1 framing only; no pixel decoding, hardware injection or consume evidence."""

from dataclasses import dataclass
import struct

from .errors import ICDError
from .wire import crc32

VIDEO_HEADER = struct.Struct("<4sBBHIIIIQHHIHH")


@dataclass(frozen=True, slots=True)
class VideoHeader:
    session_id: int
    stream_numeric_id: int
    frame_index: int
    capture_step: int
    pts_us: int
    codec: str


@dataclass(frozen=True, slots=True)
class VideoFragment:
    header: VideoHeader
    index: int
    count: int
    frame_bytes: int
    payload: bytes
    transport: str = "VIDEO"


class VideoCodec:
    def __init__(self, contract):
        self.rules = contract.catalogue["codecs"]["VIDEO"]
        self._codes = self.rules["codec_codes"]
        self._names = {v: k for k, v in self._codes.items()}

    def validate_header(self, header):
        if not isinstance(header, VideoHeader) or header.codec not in self._codes:
            raise ICDError("SCHEMA", "VideoHeader with a declared codec required")
        limits = ((header.session_id, 1, 0xffffffff), (header.stream_numeric_id, 1, 0xffffffff),
                  (header.frame_index, 0, 0xffffffff), (header.capture_step, 0, 0xffffffff),
                  (header.pts_us, 0, 0xffffffffffffffff))
        if any(type(value) is not int or not low <= value <= high for value, low, high in limits):
            raise ICDError("SCHEMA", "video header integer outside declared range")

    def validate_frame(self, frame, header):
        self.validate_header(header)
        if type(frame) is not bytes or not frame:
            raise ICDError("SCHEMA", "nonempty frame bytes required")
        if len(frame) > self.rules["max_frame_bytes"]:
            raise ICDError("CAPACITY", "video frame exceeds 2MiB")
        if header.codec == "RAW" and len(frame) != 921600:
            raise ICDError("SCHEMA", "RAW frame requires 640x480 BGR24 without padding")
        if header.codec != "RAW" and not frame.startswith((b"\x00\x00\x01", b"\x00\x00\x00\x01")):
            raise ICDError("SCHEMA", "H26x frame must use Annex B start codes")

    def encode(self, frame: bytes, header: VideoHeader) -> list[bytes]:
        self.validate_frame(frame, header)
        chunk_bytes = self.rules["chunk_bytes"]
        count = (len(frame) + chunk_bytes - 1) // chunk_bytes
        packets = []
        for index in range(count):
            chunk = frame[index * chunk_bytes:(index + 1) * chunk_bytes]
            prefix = VIDEO_HEADER.pack(b"HIV1", 1, self._codes[header.codec], 0, header.session_id,
                                       header.stream_numeric_id, header.frame_index, header.capture_step,
                                       header.pts_us, index, count, len(frame), len(chunk), 0)
            packets.append(prefix + struct.pack("<I", crc32(prefix + chunk)) + chunk)
        return packets

    def decode(self, raw: bytes) -> VideoFragment:
        if type(raw) is not bytes or not 49 <= len(raw) <= self.rules["max_datagram_bytes"]:
            raise ICDError("FRAGMENT", "invalid video datagram length")
        (magic, major, codec, flags, session, stream, frame_index, step, pts, index,
         count, frame_bytes, length, reserved) = VIDEO_HEADER.unpack_from(raw)
        if (magic, major, flags, reserved) != (b"HIV1", 1, 0, 0):
            raise ICDError("VERSION", "video magic/version/flags/reserved mismatch")
        if len(raw) != 48 + length:
            raise ICDError("FRAGMENT", "video size differs from chunk_length")
        if crc32(raw[:44] + raw[48:]) != struct.unpack_from("<I", raw, 44)[0]:
            raise ICDError("CRC", "video CRC mismatch")
        if codec not in self._names:
            raise ICDError("SCHEMA", "unknown video codec")
        header = VideoHeader(session, stream, frame_index, step, pts, self._names[codec])
        self.validate_header(header)
        size = self.rules["chunk_bytes"]
        if not 1 <= frame_bytes <= self.rules["max_frame_bytes"]:
            raise ICDError("CAPACITY", "invalid video frame capacity")
        if header.codec == "RAW" and frame_bytes != 921600:
            raise ICDError("SCHEMA", "invalid RAW frame size")
        expected_count = (frame_bytes + size - 1) // size
        if not (1 <= count <= self.rules["max_fragments"] and count == expected_count and 0 <= index < count):
            raise ICDError("FRAGMENT", "video fragment count/index inconsistent with frame size")
        if length != min(size, frame_bytes - index * size):
            raise ICDError("FRAGMENT", "video chunk does not match its exact offset/size")
        return VideoFragment(header, index, count, frame_bytes, raw[48:])
