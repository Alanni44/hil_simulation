#!/usr/bin/env python3
"""Receipt-gated local UDP client for commands accepted by the C core."""
from __future__ import absolute_import

import json
import secrets
import socket

from config_loader import CONFIG


CMD_HOST = '127.0.0.1'
CMD_PORT = CONFIG['local_udp']['command_port']


def core_send(command, host=CMD_HOST, port=CMD_PORT):
    """Best-effort command transmit for high-rate local adapters.

    This intentionally does not wait for the C-core receipt.  MAVLink
    actuator frames arrive at control-loop frequency, whereas receipts are
    reserved for operator actions and would otherwise add socket churn and
    back-pressure to the HIL path.
    """
    try:
        payload = json.dumps(command, separators=(',', ':')).encode('utf-8')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(payload, (host, port))
        finally:
            sock.close()
        return True
    except (OSError, ValueError):
        return False


def core_request(command, host=CMD_HOST, port=CMD_PORT, timeout_s=2.0):
    """Send one command and return only the matching C-core receipt."""
    request_id = command.setdefault('request_id', secrets.token_hex(12))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(('127.0.0.1', 0))
        sock.settimeout(timeout_s)
        payload = json.dumps(command, separators=(',', ':')).encode('utf-8')
        sock.sendto(payload, (host, port))
        while True:
            response, _sender = sock.recvfrom(65536)
            receipt = json.loads(response.decode('utf-8'))
            if receipt.get('request_id') == request_id:
                return receipt
    except (OSError, ValueError) as exc:
        return {
            'request_id': request_id,
            'accepted': False,
            'reason': 'C core receipt failed: {}'.format(exc),
        }
    finally:
        sock.close()
