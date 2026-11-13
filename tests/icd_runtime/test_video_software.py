import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ICDTest, message


FFMPEG = Path("/usr/bin/ffmpeg")


@unittest.skipUnless(FFMPEG.is_file() and shutil.which("ffmpeg"), "actual ffmpeg decoder unavailable")
class VideoSoftwareDecoderTests(ICDTest):
    @classmethod
    def setUpClass(cls):
        from icd_runtime.contract import Contract
        from icd_runtime.video import VideoCodec, VideoHeader, VideoReassembler
        from input_simulator.video_software import VideoSoftwareDecoder
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.decoder = VideoSoftwareDecoder(cls.contract)
        cls.framer = VideoCodec(cls.contract)
        cls.VideoHeader, cls.VideoReassembler = VideoHeader, VideoReassembler

    def _encoded_access_unit(self, codec):
        encoder = "libx264" if codec == "H264" else "libx265"
        extension = "h264" if codec == "H264" else "h265"
        extra = ("-x264-params", "keyint=30:min-keyint=30:scenecut=0") if codec == "H264" else (
            "-x265-params", "keyint=30:min-keyint=30:scenecut=0:pools=1:frame-threads=1:log-level=error")
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ("frame." + extension)
            command = (str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                       "color=c=red:s=1280x720:r=30", "-frames:v", "1", "-pix_fmt", "yuv420p", "-c:v",
                       encoder, *extra, "-f", "h264" if codec == "H264" else "hevc", str(target))
            subprocess.run(command, check=True, timeout=30, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return target.read_bytes()

    def _inputs(self, codec, frame):
        config = copy.deepcopy(message(30)["payload"])
        config["codec"] = codec
        config["bitrate_bps"] = 12_000_000 if codec == "H264" else 8_000_000
        digest = hashlib.sha256(frame).hexdigest()
        config["resource_sha256"] = digest
        metadata = copy.deepcopy(message(43)["payload"])
        metadata.update(resource_sha256=digest, offset_bytes=0, length_bytes=len(frame), frame_sha256=digest,
                        capture_step=1000, pts_us="0", keyframe=True)
        return config, metadata

    def test_actual_h264_and_h265_initial_access_units_decode_to_configured_pixels(self):
        for codec in ("H264", "H265"):
            with self.subTest(codec=codec):
                frame = self._encoded_access_unit(codec)
                config, metadata = self._inputs(codec, frame)
                header = self.VideoHeader(1, config["stream_numeric_id"], metadata["frame_index"],
                                          metadata["capture_step"], int(metadata["pts_us"]), codec)
                reassembler = self.VideoReassembler(self.framer)
                reassembled = None
                for packet in self.framer.encode(frame, header):
                    reassembled = reassembler.push(self.framer.decode(packet)) or reassembled
                self.assertIsNotNone(reassembled)
                self.assertEqual(reassembled.payload, frame)
                decoded = self.decoder.decode_initial(config, metadata, reassembled.payload, trigger_step=1000)
                self.assertEqual((decoded.codec, decoded.width, decoded.height, decoded.frame_index,
                                  decoded.pts_us, decoded.capture_step), (codec, 1280, 720, 0, 0, 1000))
                self.assertEqual(len(decoded.pixels), 1280 * 720 * 3 // 2)
                self.assertEqual(decoded.encoded_sha256, hashlib.sha256(frame).hexdigest())
                self.assertFalse(decoded.hardware_qualified)

    def test_hash_and_initial_parameter_set_or_idr_gates_precede_actual_decoder(self):
        frame = self._encoded_access_unit("H264")
        config, metadata = self._inputs("H264", frame)
        metadata["frame_sha256"] = "0" * 64
        self.rejects("HASH", lambda: self.decoder.decode_initial(config, metadata, frame, trigger_step=1000))
        config, metadata = self._inputs("H264", frame)
        metadata["frame_sha256"] = hashlib.sha256(b"\0\0\1\x65\x88").hexdigest()
        lone_idr = b"\0\0\1\x65\x88"
        metadata.update(resource_sha256=hashlib.sha256(lone_idr).hexdigest(), length_bytes=len(lone_idr),
                        frame_sha256=hashlib.sha256(lone_idr).hexdigest())
        config["resource_sha256"] = metadata["resource_sha256"]
        self.rejects("SCHEMA", lambda: self.decoder.decode_initial(config, metadata, lone_idr, trigger_step=1000))

    def test_pts_and_capture_step_must_remain_bound_to_frame_index_and_trigger_step(self):
        frame = self._encoded_access_unit("H264")
        config, metadata = self._inputs("H264", frame)
        metadata["capture_step"] = 1001
        self.rejects("CLOCK_UNSYNC", lambda: self.decoder.decode_initial(config, metadata, frame, trigger_step=1000))
