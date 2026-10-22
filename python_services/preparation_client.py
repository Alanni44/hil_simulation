#!/usr/bin/env python3
"""Loopback client for the fixed first-circle HIL preparation service.

The 8765 INITIALIZE adapter must not create a second C-core configuration
writer.  It delegates to the same ``PreparationCommandService`` that owns the
frozen template, the single preparation lock and the snapshot replay rules.
"""
from __future__ import absolute_import

import hashlib
import http.client
import json
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 1024 * 1024


class PreparationError(RuntimeError):
    """A preparation request did not produce a usable prepared result."""

    def __init__(self, code, message):
        self.code = str(code)
        self.message = str(message)
        RuntimeError.__init__(self, '{}: {}'.format(self.code, self.message))


class PreparationClient(object):
    """One bounded HTTP client; every call owns and closes its connection."""

    def __init__(self, url, timeout_s=10.0):
        parts = urlsplit(url)
        if parts.scheme != 'http' or not parts.hostname:
            raise ValueError('preparation_url must be an http URL with a host')
        if parts.query or parts.fragment:
            raise ValueError('preparation_url must not carry a query or fragment')
        self.host = parts.hostname
        self.port = parts.port or 80
        self.path = parts.path or '/'
        self.timeout_s = float(timeout_s)
        if not 0.05 <= self.timeout_s <= 600.0:
            raise ValueError('preparation timeout must be between 0.05 and 600 seconds')

    def prepare(self, model_id, config_id, request_id, run_configuration):
        """Ask the preparation owner to configure the actual model.

        The derived HTTP request_id is deterministic for one INITIALIZE
        request_id, so a byte-identical retry reuses the preparation owner's
        idempotent response instead of applying a second configuration.
        """
        http_request_id = 'initialize-' + hashlib.sha256(
            request_id.encode('utf-8')).hexdigest()[:32]
        document = {
            'cmd': 'hil_prepare',
            'params': {
                'api_version': '1.0',
                'request_id': http_request_id,
                'prepare_id': request_id,
                'run_id': config_id,
                'run_configuration': run_configuration,
            },
        }
        body = json.dumps(document, separators=(',', ':'), allow_nan=False).encode('utf-8')
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout_s)
        try:
            try:
                connection.request(
                    'POST', self.path, body=body,
                    headers={'Content-Type': 'application/json',
                             'Accept': 'application/json',
                             'Connection': 'close'})
                response = connection.getresponse()
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            except (OSError, http.client.HTTPException) as exc:
                raise PreparationError('PREPARATION_UNAVAILABLE', str(exc))
            if len(raw) > MAX_RESPONSE_BYTES:
                raise PreparationError(
                    'PREPARATION_RESPONSE_TOO_LARGE', 'preparation response exceeds 1 MiB')
            try:
                document = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, ValueError):
                raise PreparationError(
                    'PREPARATION_RESPONSE', 'preparation response is not valid JSON')
            if not isinstance(document, dict):
                raise PreparationError(
                    'PREPARATION_RESPONSE', 'preparation response must be an object')
            if response.status != 200:
                code = document.get('code') or document.get('error') or 'HTTP_{}'.format(
                    response.status)
                message = document.get('message') or document.get('error') or (
                    'preparation request rejected')
                raise PreparationError(code, message)
            if document.get('status') != 'SUCCESS':
                raise PreparationError(
                    document.get('code') or 'PREPARATION_REJECTED',
                    document.get('message') or 'preparation did not succeed')
            data = document.get('data')
            if not isinstance(data, dict):
                raise PreparationError(
                    'PREPARATION_RESPONSE', 'successful preparation lacks data')
            return data
        finally:
            connection.close()
