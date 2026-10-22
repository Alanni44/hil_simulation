"""Run the bounded v0.3 simulator management HTTP endpoint."""

import argparse
import json
from pathlib import Path

from icd_gateway.config import parse_endpoint
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.management import ManagementContract
from .management_http import SimulatorManagementHTTPServer
from .run_service import SimulatorRunService
from .run_store import RunStore
from .run_template import FixedRunTemplate


def build_service(*, contract_directory, expected_sha256, template_path, runtime_config=None,
                  state_directory=None):
    """Load only verified formal assets and one fixed deployment template."""
    contract = Contract.load(contract_directory, expected_sha256=expected_sha256)
    management = ManagementContract.load(contract_directory, contract=contract)
    template = FixedRunTemplate.load(template_path)
    # Validate deployment-owned result fields before accepting any command.
    management.validate_definition("ProfileRef", template.profile_ref)
    management.validate_definition("PackageRef", template.package_ref)
    management.validate_definition("ScenarioRef", template.scenario_ref)
    executor = None
    if runtime_config is not None:
        from .run_executor import RunExecutor
        from .runtime_factory import FormalRuntimeFactory
        executor = RunExecutor(FormalRuntimeFactory.load(contract, runtime_config).backend())
    store = RunStore(state_directory=state_directory) if state_directory is not None else None
    return SimulatorRunService(management, template, store=store, executor=executor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--bind", required=True, help="IPv4:port")
    parser.add_argument("--runtime-config", type=Path,
                        help="explicit fixed formal UDP/HIL runtime configuration")
    parser.add_argument("--state-dir", type=Path,
                        help="existing owned directory for durable Run/Record state; active Runs recover INCOMPLETE")
    args = parser.parse_args()
    try:
        service = build_service(
            contract_directory=args.contract_dir, expected_sha256=args.expected_sha256,
            template_path=args.template, runtime_config=args.runtime_config,
            state_directory=args.state_dir)
        with SimulatorManagementHTTPServer(service, bind=parse_endpoint(args.bind)) as server:
            print(json.dumps({
                "status": "SIMULATOR_MANAGEMENT_READY", "bind": list(server.address),
                "baseline_sha256": service.management.contract.baseline_sha256,
                "commands": ["simulator_run_create", "simulator_run_get", "simulator_run_control",
                             "simulator_records_list"],
                "execution": ("FORMAL_UDP_HIL_BACKEND" if service.executor is not None
                              else "CREATE_GET_ONLY_NO_HIL_SESSION_OR_TRANSMISSION"),
            }), flush=True)
            server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
