"""Small HTTP boundary for the simulator v0.3 command envelope.

The caller owns authentication, routing policy and persistence.  This module
only turns one bounded JSON request at the deployment-selected endpoint into
one ``SimulatorRunService`` command response.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


COMMAND_PATH = "/api/simulator/commands"
MAX_REQUEST_BYTES = 1024 * 1024


def _status(response):
    if response["status"] != "REJECTED":
        return 200
    if response["code"] == "NOT_FOUND":
        return 404
    if response["code"] in {"IDEMPOTENCY_CONFLICT", "VERSION_CONFLICT", "STATE_CONFLICT", "CONTROL_CONFLICT"}:
        return 409
    if response["code"] in {"INVALID_REQUEST", "VALUE_OUT_OF_RANGE", "REFERENCE_INVALID"}:
        return 400
    return 422


class SimulatorManagementHTTPServer:
    """Lifecycle owner for one local management command endpoint."""

    def __init__(self, service, *, bind=("127.0.0.1", 0), max_request_bytes=MAX_REQUEST_BYTES):
        if (not callable(getattr(service, "handle", None)) or not isinstance(bind, tuple) or len(bind) != 2
                or type(bind[0]) is not str or type(bind[1]) is not int
                or not 0 <= bind[1] <= 65535 or type(max_request_bytes) is not int
                or not 1024 <= max_request_bytes <= 16 * 1024 * 1024):
            raise ICDError("SCHEMA", "bounded command service and IPv4 HTTP endpoint required")
        self.service = service
        self._max_request_bytes = max_request_bytes
        self._closed = False

        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                # Do not mix management request metadata into process stderr.
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
                content_type = self.headers.get("Content-Type", "")
                parts = [part.strip().lower() for part in content_type.split(";")]
                if (not parts or parts[0] != "application/json"
                        or any(part.startswith("charset=") and part != "charset=utf-8" for part in parts[1:])):
                    self._send(415, {"error": "unsupported_media_type"})
                    return
                length = self.headers.get("Content-Length")
                try:
                    length = int(length)
                except (TypeError, ValueError):
                    self._send(411, {"error": "content_length_required"})
                    return
                if not 0 <= length <= outer._max_request_bytes:
                    self._send(413, {"error": "request_too_large"})
                    return
                try:
                    request = loads(self.rfile.read(length))
                    response = outer.service.handle(request)
                    self._send(_status(response), response)
                except ICDError as error:
                    # A malformed document may not contain the mandatory v0.3
                    # request ID/command, so a schema-valid management Response
                    # cannot be constructed safely at this HTTP boundary.
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
            raise ICDError("STATE", "management HTTP server is closed")
        self._server.serve_forever()

    def serve_in_thread(self):
        if self._closed:
            raise ICDError("STATE", "management HTTP server is closed")
        thread = threading.Thread(target=self.serve_forever, name="simulator-management-http", daemon=True)
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
