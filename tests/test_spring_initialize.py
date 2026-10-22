"""8765 is telemetry-only; first-circle preparation is HTTP-only."""

import asyncio
import json
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_services"))

from spring_ws_server import SpringWsServer  # noqa: E402


class SpringTelemetryOnlyTests(unittest.TestCase):
    def test_initialize_is_not_a_websocket_first_circle_entry(self):
        server = SpringWsServer({"allow_commands": False})
        with self.assertRaisesRegex(Exception, "type must be COMMAND"):
            server.handle_command(json.dumps({
                "type": "INITIALIZE", "request_id": "prepare-01", "data": {}}))

    def test_receive_loop_routes_initialize_to_the_same_read_only_rejection(self):
        server = SpringWsServer({"allow_commands": False})

        class Reader:
            def __init__(self):
                self.frames = [(0x1, json.dumps({
                    "type": "INITIALIZE", "request_id": "prepare-02", "data": {}}).encode()),
                               (0x8, b"")]

        class Writer:
            def write(self, _value):
                pass

            async def drain(self):
                pass

        async def frames(_reader, require_masked):
            self.assertTrue(require_masked)
            return reader.frames.pop(0)

        sent = []

        async def capture(_control, value):
            sent.append(value)

        import spring_ws_server
        reader = Reader()
        old_read = spring_ws_server.read_frame
        try:
            spring_ws_server.read_frame = frames
            server._put_control = capture
            asyncio.run(server._receive_loop(reader, Writer(), object()))
        finally:
            spring_ws_server.read_frame = old_read
        self.assertEqual(len(sent), 1)
        self.assertFalse(sent[0]["data"]["accepted"])


if __name__ == "__main__":
    unittest.main()
