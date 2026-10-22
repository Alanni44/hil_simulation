"""Prepare the fixed minimal HIL configuration before second-circle execution."""

import argparse
import copy
import json
from pathlib import Path

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from .config import load_deployment, parse_endpoint
from .model_consumer import CcoreConfigurationBackend
from .preparation_service import PreparationService
from input_simulator.run_template import FixedRunTemplate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--c-core-endpoint", required=True, metavar="MODEL=IP:PORT")
    parser.add_argument("--prepare-id", default="minimal-integration-prepare-v1")
    args = parser.parse_args()
    try:
        model_id, endpoint_text = args.c_core_endpoint.split("=", 1)
        contract = Contract.load(args.contract_dir, expected_sha256=args.expected_sha256)
        template = FixedRunTemplate.load(args.template)
        deployment = load_deployment(args.deployment, contract)
        if template.model_id != model_id:
            raise ICDError("MODEL", "fixed template and C-core endpoint name different models")
        identity = next((grant.identity for grant in deployment.grants
                         if grant.identity.get("model_id") == model_id), None)
        if identity is None:
            raise ICDError("AUTHORIZATION", "deployment grants no fixed preparation identity")
        request = {
            "message_id": 3,
            "header": {"session_id": 1, "sequence": 1, "target_step": 0,
                       "transaction_id": 1, "valid_for_ms": 1000},
            "payload": copy.deepcopy(template.run_configuration),
        }
        backend = CcoreConfigurationBackend(contract, {model_id: parse_endpoint(endpoint_text)})
        result = PreparationService(contract, backend).prepare(args.prepare_id, identity, request)
        print(json.dumps({
            "status": "HIL_PREPARATION_READY", "prepare_id": result.prepare_id,
            "model_id": result.model_id, "config_sha256": result.config_sha256,
            "model_revision": result.model_revision, "model_step": result.model_step,
            "state": result.state, "control_source": result.control_source,
        }, sort_keys=True), flush=True)
        return 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "HIL_PREPARATION_FAILED",
                          "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
