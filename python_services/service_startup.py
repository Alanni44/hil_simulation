#!/usr/bin/env python3
"""Fail-fast listener preflight for the independently owned HIL endpoints."""
from __future__ import absolute_import

import socket


class StartupError(RuntimeError):
    pass


def listener_specs(config, management_host):
    """Return the sockets main.py must own before reporting service startup."""
    spring = config.get('spring_ws', {})
    return (
        ('UDP status receiver', socket.SOCK_DGRAM, '0.0.0.0',
         int(config['local_udp']['status_port'])),
        ('management WebSocket', socket.SOCK_STREAM, management_host,
         int(config['spring_boot']['websocket_port'])),
        ('Spring WebSocket', socket.SOCK_STREAM, spring.get('listen_host', '0.0.0.0'),
         int(spring.get('listen_port', 8765))),
    )


def preflight_listeners(specs):
    """Check all required ports before starting any long-lived worker.

    This is deliberately only a preflight: each server still binds its own
    socket.  It turns the common old-service collision into an immediate,
    actionable startup error rather than a daemon thread traceback.
    """
    seen = set()
    probes = []
    try:
        for name, sock_type, host, port in specs:
            key = (sock_type, host, port)
            if key in seen:
                raise StartupError('{} duplicates another configured listener'.format(name))
            seen.add(key)
            probe = socket.socket(socket.AF_INET, sock_type)
            try:
                probe.bind((host, port))
            except OSError as exc:
                probe.close()
                raise StartupError('{} cannot bind {}:{}: {}'.format(name, host, port, exc))
            probes.append(probe)
    finally:
        for probe in probes:
            probe.close()
