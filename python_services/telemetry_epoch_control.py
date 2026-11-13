#!/usr/bin/env python3
"""Protected local control channel for the HIL telemetry reset epoch."""
from __future__ import print_function

import json
import os
import socket
import threading

from shared import state_cache
from shared.logger import get_logger


logger = get_logger('telemetry_epoch_control')
DEFAULT_SOCKET_PATH = '/run/hil/telemetry-control.sock'
MAX_MESSAGE_BYTES = 4096


def _validate(value):
    if type(value) is not dict or set(value) != {
            'cmd', 'reset_id', 'run_id', 'model_step', 'sim_time_us'}:
        raise ValueError('closed telemetry epoch command required')
    if value['cmd'] != 'telemetry_epoch_advance':
        raise ValueError('unsupported telemetry epoch command')
    for name in ('reset_id', 'run_id'):
        if type(value[name]) is not str or not 1 <= len(value[name]) <= 128:
            raise ValueError('bounded {} required'.format(name))
    if value['model_step'] != 0 or value['sim_time_us'] != 0:
        raise ValueError('verified zero-step reset readback required')


class TelemetryEpochServer(object):
    """Unix-socket endpoint owned by the telemetry process, not a network API."""
    def __init__(self, path=DEFAULT_SOCKET_PATH):
        self.path = path
        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self._reset_epochs = {}
        self._lock = threading.Lock()

    def start(self):
        parent = os.path.dirname(self.path)
        if not os.path.isdir(parent):
            raise OSError('telemetry control directory is unavailable: {}'.format(parent))
        try:
            os.unlink(self.path)
        except OSError as exc:
            if exc.errno != 2:
                raise
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        os.chmod(self.path, 0o660)
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, name='telemetry-epoch-control', daemon=True)
        self._thread.start()
        logger.info('Telemetry epoch control listening on %s', self.path)
        return self

    def close(self):
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        if self._thread is not None:
            self._thread.join(2.0)
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _serve(self):
        while not self._stop.is_set():
            try:
                client, _address = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with client:
                self._handle(client)

    def _handle(self, client):
        try:
            if hasattr(socket, 'SO_PEERCRED'):
                import struct
                _pid, uid, _gid = struct.unpack('3i', client.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                if uid != os.geteuid():
                    raise ValueError('telemetry control peer is not the HIL service user')
            raw = client.recv(MAX_MESSAGE_BYTES + 1)
            if not raw or len(raw) > MAX_MESSAGE_BYTES:
                raise ValueError('bounded telemetry control request required')
            request = json.loads(raw.decode('utf-8'))
            _validate(request)
            with self._lock:
                epoch = self._reset_epochs.get(request['reset_id'])
                if epoch is None:
                    epoch = state_cache.advance_epoch_after_verified_reset()
                    if len(self._reset_epochs) >= 256:
                        self._reset_epochs.pop(next(iter(self._reset_epochs)))
                    self._reset_epochs[request['reset_id']] = epoch
                    logger.info('TELEMETRY_EPOCH_ADVANCED reset_id=%s run_id=%s epoch=%s',
                                request['reset_id'], request['run_id'], epoch)
            response = {'status': 'SUCCESS', 'epoch': epoch}
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            logger.warning('TELEMETRY_EPOCH_REJECTED detail=%s', exc)
            response = {'status': 'REJECTED', 'detail': str(exc)}
        client.sendall(json.dumps(response, separators=(',', ':')).encode('utf-8'))
