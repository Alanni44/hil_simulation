"""Run the remote first-circle HIL preparation HTTP service."""

import argparse
import json
from pathlib import Path

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError

from .config import load_deployment, parse_endpoint
from .model_consumer import CcoreConfigurationBackend
from .preparation_http import PreparationHTTPServer
from .preparation_management import PreparationCommandService
from .preparation_service import PreparationService
from input_simulator.run_template import FixedRunTemplate


def build_service(*, contract_directory, expected_sha256, template_path, deployment_path, c_core_endpoint):
    try:
        model_id, endpoint_text = c_core_endpoint.split("=", 1)
        contract = Contract.load(contract_directory, expected_sha256=expected_sha256)
        template = FixedRunTemplate.load(template_path)
        deployment = load_deployment(deployment_path, contract)
        if template.model_id != model_id:
            raise ICDError("MODEL", "fixed template and C-core endpoint name different models")
        identity = next((grant.identity for grant in deployment.grants
                         if grant.identity.get("model_id") == model_id), None)
        if identity is None:
            raise ICDError("AUTHORIZATION", "deployment grants no fixed preparation identity")
        backend = CcoreConfigurationBackend(contract, {model_id: parse_endpoint(endpoint_text)})
        return PreparationCommandService(template, identity, PreparationService(contract, backend))
    except (ICDError, OSError, ValueError):
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--c-core-endpoint", required=True, metavar="MODEL=IP:PORT")
    parser.add_argument("--bind", required=True)
    args = parser.parse_args()
    try:
        service = build_service(contract_directory=args.contract_dir,
                                expected_sha256=args.expected_sha256,
                                template_path=args.template,
                                deployment_path=args.deployment,
                                c_core_endpoint=args.c_core_endpoint)
        with PreparationHTTPServer(service, bind=parse_endpoint(args.bind)) as server:
            print(json.dumps({"status": "HIL_PREPARATION_MANAGEMENT_READY",
                              "bind": list(server.address), "model_id": service.template.model_id,
                              "baseline_sha256": service.preparation.contract.baseline_sha256}, sort_keys=True),
                  flush=True)
            server.serve_forever()
        return 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "HIL_PREPARATION_MANAGEMENT_FAILED",
                          "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
