#!/usr/bin/env python3
"""Small RFC 6455 frame codec used by the HIL WebSocket server.

The codec is intentionally independent from command handling so the protocol
rules (client masking, no fragmentation and bounded payloads) are testable.
"""
from __future__ import print_function

import struct


MAX_TEXT_BYTES = 1024 * 1024
CONTROL_OPCODES = (0x8, 0x9, 0xA)


class FrameError(ValueError):
    pass


def _validate_header(first, second, require_masked):
    if not (first & 0x80):
        raise FrameError('fragmented WebSocket frames are unsupported')
    if first & 0x70:
        raise FrameError('WebSocket RSV bits must be zero')
    opcode = first & 0x0F
    if opcode not in (0x1, 0x2, 0x8, 0x9, 0xA):
        raise FrameError('unsupported WebSocket opcode {}'.format(opcode))
    masked = bool(second & 0x80)
    if require_masked and not masked:
        raise FrameError('client WebSocket frames must be masked')
    return opcode, masked, second & 0x7F


def _payload_length(indicator, read):
    if indicator < 126:
        return indicator
    if indicator == 126:
        return struct.unpack('>H', read(2))[0]
    return struct.unpack('>Q', read(8))[0]


def _validate_length(opcode, length):
    if opcode in CONTROL_OPCODES and length > 125:
        raise FrameError('control frame payload exceeds 125 bytes')
    if length > MAX_TEXT_BYTES:
        raise FrameError('WebSocket payload exceeds 1 MiB')


def decode_frame(stream, require_masked):
    """Decode one complete frame from a binary file-like ``stream``."""
    def read(size):
        data = stream.read(size)
        if len(data) != size:
            raise FrameError('truncated WebSocket frame')
        return data
    first, second = bytearray(read(2))
    opcode, masked, indicator = _validate_header(first, second, require_masked)
    length = _payload_length(indicator, read)
    _validate_length(opcode, length)
    mask = read(4) if masked else None
    payload = bytearray(read(length))
    if mask:
        for index in range(length):
            payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)


def encode_frame(opcode, payload, masked=False, mask=None):
    """Encode a single unfragmented WebSocket frame."""
    if not isinstance(payload, bytes):
        raise FrameError('payload must be bytes')
    if opcode not in (0x1, 0x2, 0x8, 0x9, 0xA):
        raise FrameError('unsupported WebSocket opcode {}'.format(opcode))
    _validate_length(opcode, len(payload))
    first = 0x80 | opcode
    if len(payload) < 126:
        header = bytearray([first, (0x80 if masked else 0) | len(payload)])
    elif len(payload) <= 0xFFFF:
        header = bytearray([first, (0x80 if masked else 0) | 126]) + bytearray(struct.pack('>H', len(payload)))
    else:
        header = bytearray([first, (0x80 if masked else 0) | 127]) + bytearray(struct.pack('>Q', len(payload)))
    if not masked:
        return bytes(header) + payload
    if mask is None or len(mask) != 4:
        raise FrameError('masked frame requires four-byte mask')
    encoded = bytearray(payload)
    for index in range(len(encoded)):
        encoded[index] ^= mask[index % 4]
    return bytes(header) + mask + bytes(encoded)


async def read_frame(reader, require_masked):
    """Asyncio ``StreamReader`` counterpart of :func:`decode_frame`."""
    header = await reader.readexactly(2)
    opcode, masked, indicator = _validate_header(header[0], header[1], require_masked)
    async def read(size):
        return await reader.readexactly(size)
    if indicator < 126:
        length = indicator
    elif indicator == 126:
        length = struct.unpack('>H', await read(2))[0]
    else:
        length = struct.unpack('>Q', await read(8))[0]
    _validate_length(opcode, length)
    mask = await read(4) if masked else None
    payload = bytearray(await read(length))
    if mask:
        for index in range(length):
            payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)


async def write_frame(writer, opcode, payload, masked=False):
    writer.write(encode_frame(opcode, payload, masked=masked))
    await writer.drain()
