"""L-012 的受限 H.26x 软件预处理；不访问视频注入硬件。"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError


@dataclass(frozen=True, slots=True)
class DecodedVideoFrame:
    """一个已由真实软件解码器验证的 YUV420P 帧，仍不是硬件注入证据。"""

    codec: str
    encoded_sha256: str
    pixels: bytes
    pixels_sha256: str
    width: int
    height: int
    frame_index: int
    pts_us: int
    capture_step: int

    @property
    def hardware_qualified(self):
        return False


def _annex_b_nals(frame: bytes) -> tuple[bytes, ...]:
    starts = []
    cursor = 0
    while cursor + 3 <= len(frame):
        if frame[cursor:cursor + 3] == b"\0\0\1":
            starts.append((cursor, 3))
            cursor += 3
        elif cursor + 4 <= len(frame) and frame[cursor:cursor + 4] == b"\0\0\0\1":
            starts.append((cursor, 4))
            cursor += 4
        else:
            cursor += 1
    if not starts or starts[0][0] != 0:
        raise ICDError("SCHEMA", "H.26x frame must start with an Annex-B start code")
    nals = []
    for index, (start, prefix) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(frame)
        nal = frame[start + prefix:end]
        if not nal:
            raise ICDError("SCHEMA", "H.26x Annex-B access unit contains an empty NAL")
        nals.append(nal)
    return tuple(nals)


def _require_initial_idr(codec: str, frame: bytes) -> None:
    nals = _annex_b_nals(frame)
    if codec == "H264":
        kinds = {nal[0] & 0x1F for nal in nals}
        if not {5, 7, 8}.issubset(kinds):
            raise ICDError("SCHEMA", "initial H264 access unit requires SPS, PPS and IDR")
        return
    if any(len(nal) < 2 for nal in nals):
        raise ICDError("SCHEMA", "H265 NAL header is incomplete")
    kinds = {(nal[0] >> 1) & 0x3F for nal in nals}
    if not {19, 20}.intersection(kinds) or not {32, 33, 34}.issubset(kinds):
        raise ICDError("SCHEMA", "initial H265 access unit requires VPS, SPS, PPS and IDR")


class VideoSoftwareDecoder:
    """在注入设备之前校验并解码单个 H264/H265 Annex-B 访问单元。

    这是受限预处理边界：输入的配置和元数据必须已符合冻结 ICD，命令
    固定为本机 ffmpeg 解码为 YUV420P，不提供任意程序、编解码参数或设备路径。
    """

    def __init__(self, contract: Contract, *, ffmpeg: Path = Path("/usr/bin/ffmpeg"), timeout_s: int = 10):
        if type(contract) is not Contract or not contract.component_hashes:
            raise ICDError("STATE", "verified frozen contract required for video software decoding")
        if (not isinstance(ffmpeg, Path) or not ffmpeg.is_absolute() or not ffmpeg.is_file()
                or type(timeout_s) is not int or not 1 <= timeout_s <= 60):
            raise ICDError("RESOURCE", "literal local ffmpeg and bounded timeout required")
        self.contract = contract
        self._ffmpeg, self._timeout_s = ffmpeg.resolve(strict=True), timeout_s

    @staticmethod
    def _expected_pts(frame_index: int, config: dict) -> int:
        numerator = frame_index * 1_000_000 * config["fps_den"]
        return (numerator * 2 + config["fps_num"]) // (2 * config["fps_num"])

    def decode_initial(self, config: dict, metadata: dict, resource: bytes, *, trigger_step: int) -> DecodedVideoFrame:
        self.contract.validate_payload(30, config)
        self.contract.validate_payload(43, metadata)
        if (type(resource) is not bytes or not resource
                or type(trigger_step) is not int or not 0 <= trigger_step <= 0xFFFFFFFF):
            raise ICDError("SCHEMA", "nonempty immutable resource and uint32 trigger step required")
        codec = config["codec"]
        if codec not in ("H264", "H265"):
            raise ICDError("UNSUPPORTED", "software H.26x decoder accepts H264/H265 only")
        if (config["stream_id"] != metadata["stream_id"]
                or config["stream_numeric_id"] != metadata["stream_numeric_id"]
                or metadata["keyframe"] is not True):
            raise ICDError("SCHEMA", "initial frame must retain configured stream identity and keyframe flag")
        resource_sha256 = hashlib.sha256(resource).hexdigest()
        if resource_sha256 != config["resource_sha256"] or resource_sha256 != metadata["resource_sha256"]:
            raise ICDError("HASH", "configured and metadata resource SHA-256 must match exact resource bytes")
        offset, length = metadata["offset_bytes"], metadata["length_bytes"]
        if offset + length > len(resource):
            raise ICDError("SCHEMA", "metadata frame byte range exceeds video resource")
        frame = resource[offset:offset + length]
        encoded_sha256 = hashlib.sha256(frame).hexdigest()
        if encoded_sha256 != metadata["frame_sha256"]:
            raise ICDError("HASH", "metadata frame SHA-256 differs from exact resource slice")
        pts_us = self._expected_pts(metadata["frame_index"], config)
        if int(metadata["pts_us"]) != pts_us or metadata["capture_step"] != trigger_step + (pts_us + 500) // 1000:
            raise ICDError("CLOCK_UNSYNC", "video PTS/capture_step does not match configured frame rate and trigger step")
        _require_initial_idr(codec, frame)
        expected_bytes = config["width"] * config["height"] * 3 // 2
        input_format = "h264" if codec == "H264" else "hevc"
        argv = (str(self._ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-f", input_format,
                "-i", "pipe:0", "-map", "0:v:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt",
                "yuv420p", "pipe:1")
        try:
            process = subprocess.run(argv, input=frame, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     timeout=self._timeout_s, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ICDError("RESOURCE", "local ffmpeg decoder could not complete") from error
        if process.returncode != 0 or len(process.stdout) != expected_bytes:
            raise ICDError("BUSINESS_FAILED", "actual ffmpeg decoder rejected frame or output geometry differs")
        pixels = process.stdout
        return DecodedVideoFrame(codec, encoded_sha256, pixels, hashlib.sha256(pixels).hexdigest(),
                                 config["width"], config["height"], metadata["frame_index"],
                                 pts_us, metadata["capture_step"])
