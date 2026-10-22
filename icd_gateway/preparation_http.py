"""HTTP owner for the fixed first-circle HIL preparation commands."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


COMMAND_PATH = "/api/hil/preparation/commands"
MAX_REQUEST_BYTES = 1024 * 1024


def _status(response):
    if response["status"] == "SUCCESS":
        return 200
    if response["code"] == "NOT_FOUND":
        return 404
    if response["code"] in {"IDEMPOTENCY_CONFLICT", "DUPLICATE", "STATE"}:
        return 409
    if response["code"] in {"SCHEMA", "REFERENCE", "BASELINE", "MODEL"}:
        return 400
    return 422


class PreparationHTTPServer:
    """One bounded HTTP listener; command semantics remain in its service."""

    def __init__(self, service, *, bind=("127.0.0.1", 0), max_request_bytes=MAX_REQUEST_BYTES):
        if (not callable(getattr(service, "handle", None)) or type(bind) is not tuple or len(bind) != 2
                or type(bind[0]) is not str or type(bind[1]) is not int
                or not 0 <= bind[1] <= 65535 or type(max_request_bytes) is not int
                or not 1024 <= max_request_bytes <= 16 * 1024 * 1024):
            raise ICDError("SCHEMA", "bounded HIL preparation command service and IPv4 endpoint required")
        self._closed = False
        self._max_request_bytes = max_request_bytes
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def _send(self, status, document):
                raw = canonicalize(document)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                if self.path != COMMAND_PATH:
                    self._send(404, {"error": "not_found"})
                    return
                if self.headers.get("Content-Type", "").lower().split(";", 1)[0].strip() != "application/json":
                    self._send(415, {"error": "unsupported_media_type"})
                    return
                try:
                    length = int(self.headers.get("Content-Length"))
                except (TypeError, ValueError):
                    self._send(411, {"error": "content_length_required"})
                    return
                if not 0 <= length <= outer._max_request_bytes:
                    self._send(413, {"error": "request_too_large"})
                    return
                try:
                    response = service.handle(loads(self.rfile.read(length)))
                    self._send(_status(response), response)
                except ICDError as error:
                    self._send(400, {"error": "invalid_request", "code": error.code})
                except (BrokenPipeError, ConnectionResetError):
                    return

            def do_GET(self):
                self._send(405, {"error": "method_not_allowed"})

        self._server = ThreadingHTTPServer(bind, Handler)

    @property
    def address(self):
        return self._server.server_address

    def serve_forever(self):
        if self._closed:
            raise ICDError("STATE", "HIL preparation HTTP server is closed")
        self._server.serve_forever()

    def serve_in_thread(self):
        thread = threading.Thread(target=self.serve_forever, name="hil-preparation-http", daemon=True)
        thread.start()
        return thread

    def close(self):
        if not self._closed:
            self._closed = True
            self._server.shutdown()
            self._server.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
