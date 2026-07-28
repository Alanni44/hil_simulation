#!/usr/bin/env python3
"""Local-only strict Mini-UE4 simulator for the no-WebSocket V2 session."""
from __future__ import print_function

import argparse
import json
import os
import socket
import sys
import time

from z_protocol import (ProtocolSequenceValidator, ProtocolViolation,
                        build_self_test_session)


MAX_FRAME_BYTES = 1048576
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TRANSCRIPT = os.path.join(
    ROOT, 'runtime', 'z_debug', 'mini_ue4_transcript.json')


def receive_frame(stream):
    wire = stream.readline(MAX_FRAME_BYTES + 2)
    if not wire:
        return None
    if len(wire) > MAX_FRAME_BYTES + 1 or not wire.endswith(b'\n'):
        raise ProtocolViolation('newline JSON frame exceeds 1 MiB or is incomplete')
    try:
        message = json.loads(wire.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolViolation('invalid UTF-8 JSON frame: {}'.format(exc))
    return message


def send_frame(connection, message):
    wire = json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n'
    connection.sendall(wire)


def write_result(validator, summary, transcript_path):
    parent = os.path.dirname(os.path.abspath(transcript_path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    validator.write_transcript(transcript_path, summary)


def run_self_test(transcript_path):
    validator, summary = build_self_test_session()
    write_result(validator, summary, transcript_path)
    print('LOCAL SIMULATOR PASSED: strict V2 sequence and 50 Hz fixture validated.')
    print('No real UE4 target was contacted. Transcript: {}'.format(
        transcript_path))
    return 0


def serve(host, port, transcript_path, timeout_s):
    validator = ProtocolSequenceValidator()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    server.settimeout(timeout_s)
    print('LOCAL Mini-UE4 simulator listening on {}:{}'.format(host, port))
    print('This simulator does not contact the real UE4 target.')
    connection = None
    try:
        connection, address = server.accept()
        connection.settimeout(timeout_s)
        stream = connection.makefile('rb')
        print('Local client connected from {}:{}'.format(*address))
        while True:
            message = receive_frame(stream)
            if message is None:
                break
            ack = validator.observe(message, time.monotonic())
            if ack is not None:
                send_frame(connection, ack)
        summary = validator.finish()
        write_result(validator, summary, transcript_path)
        print('LOCAL SIMULATOR PASSED: recorded strict V2 session at {:.3f} Hz.'.format(
            summary['average_state_rate_hz']))
        print('No real UE4 target was contacted. Transcript: {}'.format(
            transcript_path))
        return 0
    except (socket.timeout, OSError, ProtocolViolation) as exc:
        print('LOCAL SIMULATOR FAILED: {}'.format(exc), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()
        server.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Local-only strict Mini-UE4 V2 validator')
    parser.add_argument('--self-test', action='store_true',
                        help='validate a deterministic local fixture without networking')
    parser.add_argument('--host', default='127.0.0.1',
                        help='local listen address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=5000,
                        help='local listen port (default: 5000)')
    parser.add_argument('--timeout', type=float, default=60.0,
                        help='accept/read timeout in seconds')
    parser.add_argument('--transcript', default=DEFAULT_TRANSCRIPT,
                        help='scoped JSON transcript path')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.self_test:
        return run_self_test(args.transcript)
    if not 1 <= args.port <= 65535:
        print('LOCAL SIMULATOR FAILED: port must be 1..65535', file=sys.stderr)
        return 2
    return serve(args.host, args.port, args.transcript, args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
