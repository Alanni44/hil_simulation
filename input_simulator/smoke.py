"""Run one bounded CREATE -> START -> input -> STOP management smoke flow."""

import argparse
import copy
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from .run_template import FixedRunTemplate


def _post(endpoint, document):
    raw = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(endpoint, data=raw, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=3) as reply:
            return reply.status, loads(reply.read())
    except urllib.error.HTTPError as error:
        return error.code, loads(error.read())


def _wait_ready(endpoint, deadline):
    """Wait for the local POST-only boundary without creating a Run."""
    request = urllib.request.Request(endpoint, method="GET")
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=1):
                return
        except urllib.error.HTTPError as error:
            if error.code == 405:
                error.read()
                return
        except urllib.error.URLError:
            pass
        time.sleep(0.05)
    raise ICDError("TIMEOUT", "simulator management endpoint did not become ready")


def _request_id(prefix):
    return prefix + "-" + uuid.uuid4().hex


def _get(endpoint, run_id):
    return _post(endpoint, {"cmd": "simulator_run_get", "params": {
        "api_version": "0.3", "request_id": _request_id("smoke-get"), "run_id": run_id}})


def _records(endpoint, run_id, after_cursor=None):
    params = {
        "api_version": "0.3", "request_id": _request_id("smoke-records"),
        "run_id": run_id, "limit": 10}
    if after_cursor is not None:
        params["after_cursor"] = after_cursor
    return _post(endpoint, {"cmd": "simulator_records_list", "params": params})


def _all_records(endpoint, run_id):
    cursor, rows = None, []
    for _ in range(100):
        page = _require(*_records(endpoint, run_id, cursor), "RECORDS")["data"]
        rows.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return rows
    raise ICDError("CAPACITY", "bounded smoke record pagination did not complete")


def _require(status, response, label):
    if status != 200 or response.get("status") not in {"SUCCESS", "ACCEPTED"}:
        raise ICDError("STATE", label + " failed: " + json.dumps(response, sort_keys=True))
    return response


def run(*, endpoint, template_path, timeout_s):
    template = FixedRunTemplate.load(template_path)
    create = {"cmd": "simulator_run_create", "params": {
        "api_version": "0.3", "request_id": _request_id("smoke-create"),
        "package_ref": copy.deepcopy(template.package_ref),
        "scenario_ref": copy.deepcopy(template.scenario_ref), "mode": template.mode,
        "source_binding_ref": template.source_binding_ref, "link_ids": copy.deepcopy(template.link_ids),
        "baseline_sha256": template.source_inputs["baseline_sha256"],
        "run_configuration": copy.deepcopy(template.run_configuration),
        "source_inputs": copy.deepcopy(template.source_inputs),
    }}
    deadline = time.monotonic() + timeout_s
    _wait_ready(endpoint, deadline)
    _status, response = _post(endpoint, create)
    created = _require(_status, response, "CREATE")
    run_id = created["data"]["run_id"]
    started = _require(*_post(endpoint, {"cmd": "simulator_run_control", "params": {
        "api_version": "0.3", "request_id": _request_id("smoke-start"), "run_id": run_id,
        "expected_revision": "1", "action": "START"}}), "START")
    applied = False
    last_run = started["data"]
    while time.monotonic() < deadline:
        _status, response = _get(endpoint, run_id)
        current = _require(_status, response, "GET")
        last_run = current["data"]
        facts = _all_records(endpoint, run_id)
        applied = any(fact["kind"] == "APPLIED" and fact["reason_code"] == "SCENARIO_INPUT_APPLIED"
                      and fact["message_id"] == "10" for fact in facts)
        if applied:
            break
        if last_run["state"] == "COMPLETED":
            raise ICDError("STATE", "execution completed before the scenario input was applied")
        time.sleep(0.05)
    if not applied:
        raise ICDError("TIMEOUT", "scenario input was not applied before the smoke timeout")
    stopped = _require(*_post(endpoint, {"cmd": "simulator_run_control", "params": {
        "api_version": "0.3", "request_id": _request_id("smoke-stop"), "run_id": run_id,
        "expected_revision": last_run["revision"], "action": "STOP"}}), "STOP")
    while time.monotonic() < deadline:
        _status, response = _get(endpoint, run_id)
        completed = _require(_status, response, "GET")["data"]
        if completed["state"] == "COMPLETED":
            facts = _all_records(endpoint, run_id)
            stopped_fact = any(fact["kind"] == "RESPONSE" and fact["reason_code"] == "HIL_STOP_APPLIED"
                               for fact in facts)
            if completed["result"] != "INCOMPLETE" or not stopped_fact:
                raise ICDError("STATE", "terminal run lacks expected formal stop evidence")
            return {"status": "MINIMAL_FULL_FLOW_READY", "run_id": run_id,
                    "start_operation_id": started["operation_id"], "stop_operation_id": stopped["operation_id"],
                    "result": completed["result"], "scenario_input_applied": applied,
                    "hil_stop_applied": stopped_fact, "record_count": len(facts)}
        time.sleep(0.05)
    raise ICDError("TIMEOUT", "Run did not reach a terminal state after STOP")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18080/api/simulator/commands")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--timeout-s", type=float, default=12.0)
    args = parser.parse_args()
    try:
        if not 1.0 <= args.timeout_s <= 60.0:
            raise ICDError("SCHEMA", "bounded smoke timeout required")
        print(json.dumps(run(endpoint=args.endpoint, template_path=args.template,
                             timeout_s=args.timeout_s), sort_keys=True), flush=True)
        return 0
    except (ICDError, OSError, ValueError, urllib.error.URLError) as error:
        print(json.dumps({"status": "MINIMAL_FULL_FLOW_FAILED",
                          "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
