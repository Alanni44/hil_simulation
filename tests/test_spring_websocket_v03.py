import json
import pathlib
import asyncio
import socket
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from shared.ws_framing import encode_frame, read_frame  # noqa: E402
from spring_protocol import ProtocolError, parse_command, project_state  # noqa: E402
from spring_ws_server import SpringWsServer  # noqa: E402


class FakeRuntime(object):
    def __init__(self):
        self.requests = []

    def request(self, action):
        self.requests.append(action)
        return (action == 'START', 'accepted' if action == 'START' else 'model is not running')

    def execute(self, action):
        return True, 'completed'


class SpringProtocolTests(unittest.TestCase):
    def test_command_requires_contract_envelope(self):
        self.assertEqual(('r-1', 'START'), parse_command(
            '{"type":"COMMAND","request_id":"r-1","data":{"action":"START"}}'))
        for value in ('[]', 'null', '{"type":"COMMAND","data":{"action":"START"}}',
                      '{"type":"COMMAND","request_id":"r","data":{"action":"PAUSE"}}'):
            with self.assertRaises(ProtocolError):
                parse_command(value)

    def test_state_projection_keeps_ned_and_uint64_precision(self):
        state = {'version': 3, 'sequence': 9007199254740993, 'sim_time_s': 12.0,
                 'lifecycle': 0, 'north_m': 1.0, 'east_m': 2.0, 'down_m': -3.0,
                 'vn_mps': 0.0, 've_mps': 0.0, 'vd_mps': 0.0,
                 'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
                 'p_radps': 0.0, 'q_radps': 0.0, 'r_radps': 0.0,
                 'ax_mps2': 0.0, 'ay_mps2': 0.0, 'az_mps2': 0.0,
                 'airborne': 0, 'wind_n_mps': float('nan')}
        message = project_state(state, 100)
        self.assertEqual('9007199254740993', message['data']['sequence'])
        self.assertEqual(-3.0, message['data']['down_m'])
        self.assertNotIn('wind_n_mps', message['data'])
        self.assertEqual(100, message['timestamp_ms'])

    def test_duplicate_request_is_not_executed_twice(self):
        runtime = FakeRuntime()
        server = SpringWsServer({'request_cache_size': 2}, runtime)
        payload = json.dumps({'type': 'COMMAND', 'request_id': 'same', 'data': {'action': 'START'}})
        first, action = server.handle_command(payload)
        second, duplicate_action = server.handle_command(payload)
        conflict, conflict_action = server.handle_command(json.dumps(
            {'type': 'COMMAND', 'request_id': 'same', 'data': {'action': 'STOP'}}))
        self.assertTrue(first['data']['accepted'])
        self.assertEqual(first, second)
        self.assertEqual('START', action)
        self.assertIsNone(duplicate_action)
        self.assertFalse(conflict['data']['accepted'])
        self.assertIsNone(conflict_action)
        self.assertEqual(['START'], runtime.requests)

    def test_invalid_command_with_request_id_has_correlated_rejection(self):
        runtime = FakeRuntime()
        server = SpringWsServer({'request_cache_size': 2}, runtime)
        with self.assertRaises(ProtocolError) as raised:
            parse_command('{"type":"COMMAND","request_id":"bad-1","data":{"action":"PAUSE"}}')
        self.assertEqual('bad-1', raised.exception.request_id)

    def test_read_only_telemetry_endpoint_never_dispatches_control(self):
        runtime = FakeRuntime()
        server = SpringWsServer({'request_cache_size': 2, 'allow_commands': False}, runtime)
        response, action = server.handle_command(json.dumps(
            {'type': 'COMMAND', 'request_id': 'control-01', 'data': {'action': 'START'}}))
        self.assertFalse(response['data']['accepted'])
        self.assertEqual('telemetry endpoint is read-only', response['data']['reason'])
        self.assertIsNone(action)
        self.assertEqual([], runtime.requests)


class SpringWebSocketE2ETests(unittest.TestCase):
    def test_masked_command_gets_correlated_response_over_real_websocket(self):
        async def scenario():
            runtime = FakeRuntime()
            service = SpringWsServer({'path': '/ws/hil', 'publish_rate_hz': 50,
                                      'state_max_age_s': 0.5, 'control_queue_size': 2,
                                      'send_timeout_s': 1, 'request_cache_size': 8}, runtime)
            server = await asyncio.start_server(service.websocket_client, '127.0.0.1', 0)
            try:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                writer.write((
                    'GET /ws/hil HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                    'Connection: Upgrade\r\nSec-WebSocket-Key: test-key\r\n'
                    'Sec-WebSocket-Version: 13\r\n\r\n').encode('ascii'))
                await writer.drain()
                self.assertIn(b'101 Switching Protocols', await reader.readuntil(b'\r\n\r\n'))
                command = json.dumps({'type': 'COMMAND', 'request_id': 'bad-1',
                                      'data': {'action': 'PAUSE'}}).encode('utf-8')
                writer.write(encode_frame(0x1, command, masked=True, mask=b'abcd'))
                await writer.drain()
                opcode, body = await read_frame(reader, require_masked=False)
                self.assertEqual(0x1, opcode)
                reply = json.loads(body.decode('utf-8'))
                self.assertEqual('bad-1', reply['request_id'])
                self.assertFalse(reply['data']['accepted'])
                writer.write(encode_frame(0x8, b'', masked=True, mask=b'efgh'))
                await writer.drain()
                opcode, _body = await read_frame(reader, require_masked=False)
                self.assertEqual(0x8, opcode)
                writer.close()
                try:
                    await writer.wait_closed()
                except AttributeError:
                    pass
                # The server owns cancellation of its publisher/sender tasks;
                # wait for its close before tearing down this test loop.
                await reader.read()
                await asyncio.sleep(0.01)
            finally:
                server.close()
                await server.wait_closed()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(scenario())
        except PermissionError:
            self.skipTest('test environment does not permit loopback sockets')
        finally:
            loop.close()


if __name__ == '__main__':
    unittest.main()
