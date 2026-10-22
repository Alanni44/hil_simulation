"""Standard UDP ingress process with an explicit formal-release integrity gate."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import signal
import threading

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from .config import load_deployment, parse_endpoint
from .receiver import Receiver
from .session import SessionRegistry
from .udp import UDPGateway
from .reception_service import ReceptionService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument('--receive-only',action='store_true')
    parser.add_argument('--received-jsonl',type=Path)
    parser.add_argument('--max-receptions',type=int,default=0)
    parser.add_argument('--can',action='store_true')
    parser.add_argument('--c-core-endpoint',action='append',default=[],metavar='MODEL=IP:PORT',
                        help='install explicit C-core RunConfigure backend for this model')
    parser.add_argument('--c-core-resource-root',type=Path,
                        help='owned persistent ResourceStore root required with --c-core-endpoint')
    parser.add_argument('--c-core-runtime-contract',action='append',default=[],metavar='MODEL=PATH',
                        help='optional generated hil_contract.json; installs verified input consumers')
    args = parser.parse_args()
    try:
        contract = Contract.load(args.contract_dir, expected_sha256=args.expected_sha256)
        deployment = load_deployment(args.deployment, contract)
        if (args.receive_only and args.received_jsonl is None
                or not args.receive_only and (args.received_jsonl is not None or args.max_receptions)
                or not 0<=args.max_receptions<=4096):
            raise ICDError('SCHEMA','receive-only requires exclusive JSONL output and bounded receive count')
        if args.can and not deployment.can_bindings:
            raise ICDError('AUTHORIZATION','native CAN requires explicit deployment grants')
        if bool(args.c_core_endpoint) != bool(args.c_core_resource_root):
            raise ICDError('SCHEMA','C-core endpoint(s) and owned C-core resource root must be supplied together')
        endpoints={}
        for value in args.c_core_endpoint:
            try:
                model_id, text=value.split('=',1)
            except ValueError:
                raise ICDError('SCHEMA','C-core endpoint must use MODEL=IP:PORT')
            if (model_id in endpoints or model_id not in contract.entry(3)['model_ids']):
                raise ICDError('MODEL','C-core endpoint model is duplicate or unsupported by RunConfigure')
            endpoints[model_id]=parse_endpoint(text)
        runtime_contracts={}
        for value in args.c_core_runtime_contract:
            try:
                model_id, path_text=value.split('=',1)
                path=Path(path_text)
                raw=path.read_bytes()
            except (ValueError,OSError) as error:
                raise ICDError('RESOURCE','C-core runtime contract must use readable MODEL=PATH') from error
            if (model_id in runtime_contracts or model_id not in endpoints or len(raw)>1024*1024):
                raise ICDError('MODEL','runtime contract must name one configured bounded C-core endpoint')
            runtime_contracts[model_id]=loads(raw)
        if endpoints and args.receive_only:
            raise ICDError('SCHEMA','receive-only mode cannot install a C-core configuration backend')
        registry=SessionRegistry(contract,deployment.grants)
        reception=None
        if args.receive_only:
            mids=tuple(mid for mid,entry in contract.messages.items()
                       if entry['direction']=='TO_36' and mid not in (1,2))
            reception=ReceptionService(contract,registry,mids)
        # systemd stops this long-running gateway with SIGTERM.  Converting
        # that into a normal loop exit is important: ExitStack then closes the
        # C-core service and releases its exclusive ResourceStore lock.
        stopping = False

        def request_stop(_signum, _frame):
            nonlocal stopping
            stopping = True

        # signal.signal() only works on the main thread.  Tests and other
        # embedders may drive main() from a worker thread, where they own
        # their shutdown instead.
        handles_sigterm = threading.current_thread() is threading.main_thread()
        previous_sigterm = (signal.signal(signal.SIGTERM, request_stop)
                            if handles_sigterm else None)
        stack = ExitStack()
        try:
            log=stack.enter_context(args.received_jsonl.open('x',encoding='utf-8')) if reception else None
            ccore=None
            if endpoints:
                from .hil_service import CcoreHILService
                ccore=stack.enter_context(CcoreHILService(contract,deployment.grants,endpoints,
                                                            args.c_core_resource_root,
                                                            runtime_contracts=runtime_contracts or None))
                registry=ccore.registry
                receiver=ccore.receiver
                for model_id in endpoints:
                    ccore.target_status(model_id)
            else:
                receiver = Receiver(contract,registry,reception_service=reception)
            service=stack.enter_context(UDPGateway(receiver,bind=deployment.bind,
                feedback_routes=deployment.feedback_routes,channel=deployment.channel))
            cursor=0
            def flush_received():
                nonlocal cursor
                if reception:
                    records=reception.records
                    for record in records[cursor:]:
                        log.write(json.dumps(record.document(),ensure_ascii=True,allow_nan=False)+'\n')
                        log.flush()
                        cursor+=1
            stack.callback(flush_received)
            gateways=[]
            if args.can:
                from .can_ingress import CANGateway
                for binding in deployment.can_bindings:
                    gateways.append(stack.enter_context(CANGateway(receiver,channel=binding.channel,interface=binding.peer)))
            formal = deployment.formal_release is not None
            print(json.dumps({"status": "FORMAL_RELEASE_READY" if formal else "DEVELOPMENT_READY",
                              "bind": list(service.address),
                              "baseline_sha256": contract.baseline_sha256, "replacement_ready": False,
                              "release_gate_verified": formal,
                              'validation_scope':('WIRE_SCHEMA_SESSION_ONLY' if reception else
                                                  'C_CORE_CONFIGURATION_BOUNDARY' if ccore else 'NO_MODEL_BACKEND'),
                              'c_core_models':sorted(endpoints),
                              'can_inputs':[b.peer for b in deployment.can_bindings] if args.can else []}), flush=True)
            while not stopping:
                service.poll(timeout=0.001 if gateways else 0.02)
                for gateway in gateways:
                    gateway.poll(timeout=0)
                flush_received()
                if reception:
                    if args.max_receptions and cursor>=args.max_receptions:
                        print(json.dumps({'status':'RECEPTION_COMPLETE','received':cursor,
                            'model_application_verified':False,'replacement_ready':False}),flush=True)
                        return 0
        finally:
            try:
                stack.close()
            finally:
                if handles_sigterm:
                    signal.signal(signal.SIGTERM, previous_sigterm)
    except KeyboardInterrupt:
        return 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
