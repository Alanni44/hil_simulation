import hashlib
import json
import pathlib
import socket
import socketserver
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from preparation_client import PreparationClient, PreparationError  # noqa: E402

BASELINE = '22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27'
RUN_CONFIGURATION = {'model_id': 'quadrotor_hil', 'step_us': 1000,
                     'communication_cycle_ms': 80, 'max_duration_steps': 600000}


def _success_data(request_id, run_id, model_id):
    return {
        'run_id': run_id, 'prepare_id': request_id, 'model_id': model_id,
        'config_id': 'snapshot-hash', 'config_sha256': 'f' * 64,
        'baseline_sha256': BASELINE, 'model_revision': '1', 'model_step': '0',
        'state': 'CONFIGURED', 'control_source': 'NONE', 'configured': True,
    }


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _PreparationHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    received = []
    reply_status = 200
    reply_document = {}

    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length)
        type(self).received.append({
            'path': self.path, 'body': body,
            'content_type': self.headers.get('Content-Type')})
        raw = json.dumps(type(self).reply_document).encode('utf-8')
        self.send_response(type(self).reply_status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class PreparationClientTests(unittest.TestCase):
    def setUp(self):
        _PreparationHandler.received = []
        _PreparationHandler.reply_status = 200
        _PreparationHandler.reply_document = {
            'status': 'SUCCESS', 'code': 'OK', 'message': 'HIL prepared',
            'data': _success_data('init-1', 'snapshot-1', 'quadrotor_hil')}
        self.server = _ThreadingHTTPServer(('127.0.0.1', 0), _PreparationHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.url = 'http://{}:{}/api/hil/preparation/commands'.format(host, port)
        self.client = PreparationClient(self.url, timeout_s=1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_prepare_sends_the_fixed_preparation_envelope(self):
        data = self.client.prepare('quadrotor_hil', 'snapshot-1', 'init-1',
                                   RUN_CONFIGURATION)
        self.assertEqual('CONFIGURED', data['state'])
        self.assertEqual(1, len(_PreparationHandler.received))
        received = _PreparationHandler.received[0]
        self.assertEqual('/api/hil/preparation/commands', received['path'])
        self.assertEqual('application/json', received['content_type'])
        document = json.loads(received['body'].decode('utf-8'))
        self.assertEqual({'cmd', 'params'}, set(document))
        self.assertEqual('hil_prepare', document['cmd'])
        params = document['params']
        self.assertEqual('1.0', params['api_version'])
        self.assertEqual('init-1', params['prepare_id'])
        self.assertEqual('snapshot-1', params['run_id'])
        expected_request_id = 'initialize-' + hashlib.sha256(
            b'init-1').hexdigest()[:32]
        self.assertEqual(expected_request_id, params['request_id'])
        self.assertEqual(RUN_CONFIGURATION, params['run_configuration'])

    def test_rejection_keeps_the_preparation_error_code(self):
        _PreparationHandler.reply_status = 409
        _PreparationHandler.reply_document = {
            'status': 'REJECTED', 'code': 'STATE',
            'message': 'actual HIL is not at the configured safe boundary',
            'data': None}
        with self.assertRaises(PreparationError) as raised:
            self.client.prepare('quadrotor_hil', 'snapshot-1', 'init-1',
                                RUN_CONFIGURATION)
        self.assertEqual('STATE', raised.exception.code)
        self.assertIn('configured safe boundary', raised.exception.message)

    def test_non_success_200_response_is_not_accepted(self):
        _PreparationHandler.reply_document = {
            'status': 'REJECTED', 'code': 'MODEL', 'message': 'model differs',
            'data': None}
        with self.assertRaises(PreparationError) as raised:
            self.client.prepare('quadrotor_hil', 'snapshot-1', 'init-1',
                                RUN_CONFIGURATION)
        self.assertEqual('MODEL', raised.exception.code)

    def test_unreachable_preparation_service_is_explicit(self):
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        client = PreparationClient(
            'http://127.0.0.1:{}/api/hil/preparation/commands'.format(port), timeout_s=0.2)
        with self.assertRaises(PreparationError) as raised:
            client.prepare('quadrotor_hil', 'snapshot-1', 'init-1', RUN_CONFIGURATION)
        self.assertEqual('PREPARATION_UNAVAILABLE', raised.exception.code)

    def test_url_must_be_bounded_http(self):
        for url in ('https://127.0.0.1/prepare', 'http:///prepare',
                    'http://127.0.0.1/prepare?x=1'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    PreparationClient(url)


if __name__ == '__main__':
    unittest.main()
