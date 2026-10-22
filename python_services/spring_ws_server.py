#!/usr/bin/env python3
"""Dedicated HIL-server endpoint for the Spring WebSocket V0.3 contract."""
from __future__ import absolute_import

import asyncio
import base64
from collections import OrderedDict
import hashlib
import json
import threading

from config_loader import CONFIG
from model_runtime import MODEL_RUNTIME
from shared import state_cache
from shared.logger import get_logger
from shared.ws_framing import FrameError, read_frame, write_frame
from spring_protocol import (ProtocolError, command_result, current_timestamp_ms,
                             parse_command, project_state)

logger = get_logger('spring_ws')

def _default_state_reader():
    return state_cache.get_normalized_state(), state_cache.last_update_monotonic()


def settings():
    value = dict(CONFIG.get('spring_ws', {}))
    value.setdefault('listen_host', '0.0.0.0')
    value.setdefault('listen_port', 8765)
    value.setdefault('path', '/ws/hil')
    value.setdefault('publish_rate_hz', 50)
    value.setdefault('state_max_age_s', 0.5)
    value.setdefault('control_queue_size', 32)
    value.setdefault('send_timeout_s', 5)
    value.setdefault('request_cache_size', 256)
    value.setdefault('allow_commands', True)
    return value


class SpringWsServer(object):
    def __init__(self, config=None, runtime=None, state_reader=None):
        self.config = dict(config or settings())
        self.runtime = runtime or MODEL_RUNTIME
        self.state_reader = state_reader or _default_state_reader
        self._requests = OrderedDict()
        self._requests_lock = threading.Lock()

    def _cache_size(self):
        return int(self.config.get('request_cache_size', 256))

    def handle_command(self, payload):
        """Validate/deduplicate a command before scheduling any model work."""
        request_id, action = parse_command(payload)
        with self._requests_lock:
            known = self._requests.get(request_id)
            if known is not None:
                known_action, response = known
                if known_action == action:
                    return response, None
                return command_result(request_id, False, 'request_id conflicts with prior command'), None
            if not bool(self.config.get('allow_commands', True)):
                response = command_result(request_id, False, 'telemetry endpoint is read-only')
                self._requests[request_id] = (action, response)
                while len(self._requests) > self._cache_size():
                    self._requests.popitem(last=False)
                return response, None
            accepted, reason = self.runtime.request(action)
            response = command_result(request_id, accepted, reason)
            self._requests[request_id] = (action, response)
            while len(self._requests) > self._cache_size():
                self._requests.popitem(last=False)
        return response, action if accepted else None

    async def websocket_client(self, reader, writer):
        if not await self._handshake(reader, writer):
            return
        peer = writer.get_extra_info('peername')
        logger.info('Spring WebSocket client connected: %s', peer)
        control = asyncio.Queue(maxsize=int(self.config['control_queue_size']))
        telemetry = asyncio.Queue(maxsize=1)
        # ensure_future/get_event_loop retain compatibility with the deployed
        # Python 3.6 baseline.
        sender = asyncio.ensure_future(self._send_loop(writer, control, telemetry))
        publisher = asyncio.ensure_future(self._publish_loop(telemetry))
        try:
            await self._receive_loop(reader, writer, control)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, FrameError):
            pass
        except Exception as exc:
            logger.warning('Spring WebSocket client error: %s', exc)
        finally:
            for task in (publisher, sender):
                task.cancel()
            await asyncio.gather(publisher, sender, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except (AttributeError, ConnectionError):
                pass
            logger.info('Spring WebSocket client disconnected: %s', peer)

    async def _handshake(self, reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=5.0)
            lines = request.decode('ascii').split('\r\n')
        except (UnicodeDecodeError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            writer.close()
            return False
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().lower()] = value.strip()
        first = lines[0].split()
        target = first[1].split('?', 1)[0] if len(first) >= 2 else ''
        key = headers.get('sec-websocket-key')
        if (len(first) != 3 or first[0] != 'GET' or target != self.config['path']
                or headers.get('upgrade', '').lower() != 'websocket' or not key):
            writer.write(b'HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n')
            await writer.drain()
            writer.close()
            return False
        accept = base64.b64encode(hashlib.sha1((key +
            '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
        writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                      'Connection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n'.format(accept)).encode('ascii'))
        await writer.drain()
        return True

    async def _receive_loop(self, reader, writer, control):
        while True:
            opcode, payload = await read_frame(reader, require_masked=True)
            if opcode == 0x9:
                await self._put_control(control, (0xA, payload))
                continue
            if opcode == 0x8:
                await write_frame(writer, 0x8, payload, masked=False)
                return
            if opcode != 0x1:
                continue
            try:
                command_text = payload.decode('utf-8')
            except UnicodeDecodeError as exc:
                logger.warning('Rejected non-UTF-8 Spring frame: %s', exc)
                continue
            try:
                response, action = self.handle_command(command_text)
            except ProtocolError as exc:
                logger.warning('Rejected Spring command: %s', exc)
                # Do not manufacture an identifier for malformed input.  When
                # one was validly supplied, however, Spring gets a correlated
                # rejection rather than waiting indefinitely for a receipt.
                if exc.request_id is not None:
                    await self._put_control(control, command_result(
                        exc.request_id, False, str(exc)))
                continue
            logger.info('Received Spring command: %s', command_text)
            logger.info('Queued Spring command result: %s',
                        json.dumps(response, separators=(',', ':'), sort_keys=True))
            await self._put_control(control, response)
            if action is not None:
                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, self.runtime.execute, action)

    async def _publish_loop(self, telemetry):
        period = 1.0 / float(self.config['publish_rate_hz'])
        while True:
            state = state_cache.get_normalized_state()
            if state is not None and not state_cache.is_stale(float(self.config['state_max_age_s'])):
                message = project_state(state, current_timestamp_ms())
                if message is not None:
                    if telemetry.full():
                        try:
                            telemetry.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    telemetry.put_nowait(message)
            await asyncio.sleep(period)

    async def _put_control(self, control, message):
        # A receipt must never be discarded behind best-effort telemetry.
        await asyncio.wait_for(control.put(message), timeout=float(self.config['send_timeout_s']))

    async def _send_loop(self, writer, control, telemetry):
        while True:
            control_get = asyncio.ensure_future(control.get())
            telemetry_get = asyncio.ensure_future(telemetry.get())
            # Cancelling this connection while waiting must also cancel both
            # Queue.get tasks.  Otherwise Python 3.6 leaves orphan getters
            # behind and emits pending-task warnings on loop shutdown.
            try:
                done, _pending = await asyncio.wait((control_get, telemetry_get),
                                                     return_when=asyncio.FIRST_COMPLETED)
                # When both are ready, protocol receipts are written first.
                message = control_get.result() if control_get in done else telemetry_get.result()
            finally:
                for task in (control_get, telemetry_get):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(control_get, telemetry_get, return_exceptions=True)
            if isinstance(message, tuple):
                opcode, payload = message
            else:
                opcode, payload = 0x1, json.dumps(message, separators=(',', ':')).encode('utf-8')
            await asyncio.wait_for(write_frame(writer, opcode, payload, masked=False),
                                   timeout=float(self.config['send_timeout_s']))
            if not isinstance(message, tuple):
                if message.get('type') == 'STATE_TELEMETRY':
                    logger.info('Pushed Spring telemetry: %s', payload.decode('utf-8'))
                else:
                    logger.info('Pushed Spring message: %s', payload.decode('utf-8'))


def start_spring_ws_server():
    config = settings()
    service = SpringWsServer(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = loop.run_until_complete(asyncio.start_server(
        service.websocket_client, config['listen_host'], int(config['listen_port'])))
    logger.info('Spring WebSocket server listening on %s:%s%s', config['listen_host'],
                config['listen_port'], config['path'])
    try:
        loop.run_forever()
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()
