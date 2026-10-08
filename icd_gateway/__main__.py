"""Development-only standard UDP ingress process, never a formal release claim."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from .config import load_deployment
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
        registry=SessionRegistry(contract,deployment.grants)
        reception=None
        if args.receive_only:
            mids=tuple(mid for mid,entry in contract.messages.items()
                       if entry['direction']=='TO_36' and mid not in (1,2))
            reception=ReceptionService(contract,registry,mids)
        receiver = Receiver(contract,registry,reception_service=reception)
        with ExitStack() as stack:
            log=stack.enter_context(args.received_jsonl.open('x',encoding='utf-8')) if reception else None
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
            print(json.dumps({"status": "DEVELOPMENT_READY", "bind": list(service.address),
                              "baseline_sha256": contract.baseline_sha256, "replacement_ready": False,
                              'validation_scope':'WIRE_SCHEMA_SESSION_ONLY' if reception else 'NO_MODEL_BACKEND',
                              'can_inputs':[b.peer for b in deployment.can_bindings] if args.can else []}), flush=True)
            while True:
                service.poll(timeout=0.001 if gateways else 0.02)
                for gateway in gateways:
                    gateway.poll(timeout=0)
                flush_received()
                if reception:
                    if args.max_receptions and cursor>=args.max_receptions:
                        print(json.dumps({'status':'RECEPTION_COMPLETE','received':cursor,
                            'model_application_verified':False,'replacement_ready':False}),flush=True)
                        return 0
    except KeyboardInterrupt:
        return 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
