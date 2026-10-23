"""Bounded first-circle preparation command boundary for the 3.6 caller."""

from collections import OrderedDict
import datetime

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads


API_VERSION = "1.0"
MAX_REQUESTS = 512


def _timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _copy(value):
    return loads(canonicalize(value))


class PreparationCommandService:
    """Expose only the first-circle prepare/query operations.

    The caller supplies an orchestration ``run_id`` so 3.6 can retain the
    result against its business Run.  That identifier is correlation metadata;
    it never changes the frozen formal identity or the RunConfigure snapshot.
    """

    def __init__(self, template, identity, preparation, *, max_requests=MAX_REQUESTS):
        if (not callable(getattr(preparation, "prepare_current", None)) or type(identity) is not dict
                or type(getattr(template, "model_id", None)) is not str
                or type(getattr(template, "run_configuration", None)) is not dict
                or type(max_requests) is not int or not 1 <= max_requests <= 65536):
            raise ICDError("SCHEMA", "fixed template, identity and preparation service required")
        if identity.get("model_id") != template.model_id:
            raise ICDError("MODEL", "preparation identity and fixed template select different models")
        self.template = template
        self.identity = _copy(identity)
        self.preparation = preparation
        self.max_requests = max_requests
        self._requests = OrderedDict()
        self._results = {}

    @staticmethod
    def _identifier(value, label):
        if type(value) is not str or not 1 <= len(value) <= 128:
            raise ICDError("SCHEMA", "bounded {} required".format(label))

    def _response(self, request, *, status, code, message, data=None):
        return {
            "kind": "HIL_PREPARATION_RESPONSE", "api_version": API_VERSION,
            "request_id": request["params"]["request_id"], "cmd": request["cmd"],
            "status": status, "code": code, "message": message,
            "timestamp": _timestamp(), "data": data,
            "error": None if status == "SUCCESS" else {"code": code, "retryable": False},
        }

    def _validate_envelope(self, request):
        if type(request) is not dict or set(request) != {"cmd", "params"}:
            raise ICDError("SCHEMA", "closed preparation command envelope required")
        if request["cmd"] not in {"hil_prepare", "hil_prepare_get"}:
            raise ICDError("UNSUPPORTED", "unsupported HIL preparation command")
        params = request["params"]
        if type(params) is not dict or params.get("api_version") != API_VERSION:
            raise ICDError("SCHEMA", "HIL preparation API version 1.0 required")
        self._identifier(params.get("request_id"), "request ID")
        required = ({"api_version", "request_id", "prepare_id", "run_id", "run_configuration"}
                    if request["cmd"] == "hil_prepare"
                    else {"api_version", "request_id", "prepare_id"})
        if set(params) != required:
            raise ICDError("SCHEMA", "preparation command fields differ from the fixed contract")
        self._identifier(params.get("prepare_id"), "prepare ID")
        if request["cmd"] == "hil_prepare":
            self._identifier(params.get("run_id"), "Run ID")
            if canonicalize(params["run_configuration"]) != canonicalize(self.template.run_configuration):
                raise ICDError("REFERENCE", "RunConfigure differs from the fixed first-circle snapshot")

    def _remember(self, request, response):
        request_id = request["params"]["request_id"]
        encoded = canonicalize(request)
        existing = self._requests.get(request_id)
        if existing is not None:
            if existing[0] != encoded:
                raise ICDError("IDEMPOTENCY_CONFLICT", "request ID names another preparation command")
            return _copy(existing[1])
        self._requests[request_id] = (encoded, _copy(response))
        while len(self._requests) > self.max_requests:
            self._requests.popitem(last=False)
        return response

    @staticmethod
    def _result_data(result, run_id, prepare_id):
        return {
            "run_id": run_id, "prepare_id": prepare_id, "model_id": result.model_id,
            "config_id": result.config_id, "config_sha256": result.config_sha256,
            "baseline_sha256": result.baseline_sha256,
            "model_revision": str(result.model_revision), "model_step": str(result.model_step),
            "state": result.state, "control_source": result.control_source,
            "configured": result.configured,
        }

    def _prepare(self, request):
        params = request["params"]
        result = self.preparation.prepare_current(
            params["prepare_id"], _copy(self.identity), _copy(params["run_configuration"]))
        data = self._result_data(result, params["run_id"], params["prepare_id"])
        if not data["configured"]:
            raise ICDError("STATE", "preparation result lacks a configured safe boundary")
        self._results[params["prepare_id"]] = _copy(data)
        return self._response(request, status="SUCCESS", code="OK", message="HIL prepared", data=data)

    def _get(self, request):
        data = self._results.get(request["params"]["prepare_id"])
        if data is None:
            raise ICDError("NOT_FOUND", "preparation result is not retained by this service instance")
        return self._response(request, status="SUCCESS", code="OK", message="HIL preparation result", data=_copy(data))

    def handle(self, request):
        """Run a bounded command and retain byte-identical idempotent replies."""
        try:
            self._validate_envelope(request)
            request_id = request["params"]["request_id"]
            encoded = canonicalize(request)
            existing = self._requests.get(request_id)
            if existing is not None:
                if existing[0] != encoded:
                    raise ICDError("IDEMPOTENCY_CONFLICT", "request ID names another preparation command")
                return _copy(existing[1])
            response = self._prepare(request) if request["cmd"] == "hil_prepare" else self._get(request)
            return self._remember(request, response)
        except ICDError as error:
            # A malformed envelope may not carry a valid request ID, in which
            # case the HTTP owner produces its small transport-level error.
            if (type(request) is not dict or request.get("cmd") not in {"hil_prepare", "hil_prepare_get"}
                    or type(request.get("params")) is not dict
                    or type(request["params"].get("request_id")) is not str):
                raise
            response = self._response(request, status="REJECTED", code=error.code,
                                      message=error.detail, data=None)
            try:
                return self._remember(request, response)
            except ICDError:
                return response
