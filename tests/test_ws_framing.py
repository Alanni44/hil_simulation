import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))
from shared.ws_framing import FrameError, decode_frame, encode_frame  # noqa


class WebSocketFramingTests(unittest.TestCase):
    def test_client_masked_text_is_unmasked(self):
        frame = encode_frame(0x1, b'{"cmd":"pause"}', masked=True, mask=b'ABCD')
        self.assertEqual((0x1, b'{"cmd":"pause"}'), decode_frame(io.BytesIO(frame), require_masked=True))

    def test_server_text_is_not_masked(self):
        frame = encode_frame(0x1, b'{"accepted":true}', masked=False)
        self.assertEqual(0, frame[1] & 0x80)

    def test_unmasked_client_and_fragmented_frame_are_rejected(self):
        with self.assertRaises(FrameError):
            decode_frame(io.BytesIO(encode_frame(0x1, b'{}')), require_masked=True)
        with self.assertRaises(FrameError):
            decode_frame(io.BytesIO(b'\x01\x80ABCD'), require_masked=True)
