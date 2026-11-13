#!/usr/bin/env python3
"""L-012：HIV1 分片、H.26x 初始帧校验与实际软件解码验证。"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.video import VideoCodec, VideoHeader, VideoReassembler
from input_simulator.video_software import VideoSoftwareDecoder


def _fixture(message_id: int) -> dict:
    entries = json.loads((ROOT / "docs/interfaces/baseline/input-simulator-v0.3.examples.json").read_text(encoding="utf-8"))["fixtures"]
    for entry in entries:
        if entry["value"]["message_id"] == message_id:
            return copy.deepcopy(entry["value"]["payload"])
    raise ICDError("RESOURCE", "frozen video fixture is missing")


def _encode(ffmpeg: Path, codec: str, target: Path) -> bytes:
    encoder = "libx264" if codec == "H264" else "libx265"
    output_format = "h264" if codec == "H264" else "hevc"
    tuning = ("-x264-params", "keyint=30:min-keyint=30:scenecut=0") if codec == "H264" else (
        "-x265-params", "keyint=30:min-keyint=30:scenecut=0:pools=1:frame-threads=1:log-level=error")
    command = (str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "color=c=red:s=1280x720:r=30", "-frames:v", "1", "-pix_fmt", "yuv420p", "-c:v", encoder,
               *tuning, "-f", output_format, str(target))
    try:
        result = subprocess.run(command, check=False, timeout=30, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ICDError("RESOURCE", "local ffmpeg encoder could not produce the verification frame") from error
    if result.returncode != 0 or not target.is_file():
        raise ICDError("RESOURCE", "local ffmpeg encoder rejected the fixed verification frame")
    return target.read_bytes()


def run(output: Path, ffmpeg: Path) -> dict:
    if not ffmpeg.is_absolute() or not ffmpeg.is_file():
        raise ICDError("RESOURCE", "literal installed ffmpeg required")
    output.mkdir(parents=True, exist_ok=False)
    contract = Contract.load(ROOT / "docs/interfaces/baseline",
                             expected_sha256="22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27")
    framer, decoder = VideoCodec(contract), VideoSoftwareDecoder(contract, ffmpeg=ffmpeg)
    results = []
    for codec in ("H264", "H265"):
        frame = _encode(ffmpeg, codec, output / ("frame." + ("h264" if codec == "H264" else "h265")))
        digest = hashlib.sha256(frame).hexdigest()
        config, metadata = _fixture(30), _fixture(43)
        config.update(codec=codec, bitrate_bps=12_000_000 if codec == "H264" else 8_000_000,
                      resource_sha256=digest)
        metadata.update(resource_sha256=digest, offset_bytes=0, length_bytes=len(frame), frame_sha256=digest,
                        capture_step=1000, pts_us="0", keyframe=True)
        header = VideoHeader(1, config["stream_numeric_id"], metadata["frame_index"], metadata["capture_step"],
                             int(metadata["pts_us"]), codec)
        reassembler, complete = VideoReassembler(framer), None
        packets = framer.encode(frame, header)
        for packet in packets:
            complete = reassembler.push(framer.decode(packet)) or complete
        if complete is None or complete.payload != frame:
            raise ICDError("FRAGMENT", "HIV1 video frame did not reassemble exactly")
        decoded = decoder.decode_initial(config, metadata, complete.payload, trigger_step=1000)
        results.append({"codec": codec, "annex_b_sha256": digest, "hiv1_fragments": len(packets),
                        "pixels_sha256": decoded.pixels_sha256, "pixel_bytes": len(decoded.pixels),
                        "frame_index": decoded.frame_index, "pts_us": decoded.pts_us,
                        "capture_step": decoded.capture_step})
    return {"format": "HIL_L012_VIDEO_SOFTWARE_1", "status": "SOFTWARE_H26X_DECODE_VALIDATED",
            "ffmpeg": str(ffmpeg), "frames": results, "hardware_injection_qualified": False,
            "limits": ["No video injector, RS422 sync line, physical video Ethernet or device output was used.",
                       "Serial, AD/DA and TTL are REQUIRED_DRIVER hardware items and remain unqualified."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg"))
    args = parser.parse_args()
    try:
        result = run(args.output.resolve(), args.ffmpeg.resolve(strict=True))
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        result = {"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                  "detail": str(error)}
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 1
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
