"""Portable generated-input runner using frozen definitions and original tools."""

import argparse
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path

from icd_gateway.config import load_deployment
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from .send_run import SendPlan, SendRun
from .session import SourceSession
from .tools import ChannelReservations


def _read(path, maximum):
    with Path(path).open('rb') as source:
        raw=source.read(maximum+1)
    if len(raw)>maximum:
        raise ICDError('CAPACITY','run definition/resource exceeds bounded input')
    return raw


def load_plan(path, contract, resource_dir):
    value=loads(_read(path,1024*1024))
    if (type(value) is not dict or set(value)!={'profile','source_kind','model_id','source_inputs','generation'}
            or value['profile']!='RECEPTION_ONLY' or value['source_kind'] not in ('PROTOCOL','SCENARIO')
            or type(value['source_inputs']) is not dict):
        raise ICDError('SCHEMA','closed explicit reception run definition required; HISTORY is externally owned')
    inputs=value['source_inputs']
    contract.validate_source_definition('SourceInputs',inputs)
    if inputs.get('history') is not None:
        raise ICDError('TARGET_MISSING','history stays with its external original owner; not implicitly ignored')
    root=Path(resource_dir).resolve(strict=True)
    resources={}
    for ref in inputs['protocol']['resources']:
        candidate=(root/ref['file_name']).resolve(strict=True)
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ICDError('RESOURCE','protocol resource must remain inside the explicit resource directory')
        resources[ref['resource_id']]=_read(candidate,16*1024*1024)
    if value['source_kind']=='SCENARIO':
        if value['generation'] is not None:
            raise ICDError('SCHEMA','scenario samples come from their explicit frozen events')
        return SendPlan.scenario(contract,inputs,resources,model_id=value['model_id']),inputs,resources
    generation=value['generation']
    if type(generation) is not dict or set(generation)!={'stimuli','count','period_steps','first_step'}:
        raise ICDError('SCHEMA','explicit complete protocol snapshots/count/period/first step required')
    return SendPlan.protocol(contract,inputs,resources,model_id=value['model_id'],**generation),inputs,resources


def _write(output, value):
    output.write(json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(',',':'))+'\n')
    output.flush()


def _save_sessions(output, session):
    for row in session.records:
        _write(output,{'format':'HIL_RECEPTION_SESSION_1','request':row.request,'reply':row.reply,
            'started_ns':str(row.started_ns),'completed_ns':None if row.completed_ns is None else str(row.completed_ns),
            'error':row.error,'model_application_verified':False})


@contextmanager
def _new_output(path):
    with path.open('x',encoding='utf-8') as output:
        try:
            yield output
        except (Exception,KeyboardInterrupt) as error:
            _write(output,{'format':'HIL_RECEPTION_SUMMARY_1','status':'FAILED',
                'error':error.code if isinstance(error,ICDError) else 'RESOURCE',
                'detail':str(error),'model_application_verified':False,'replacement_ready':False})
            raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--contract-dir',required=True,type=Path)
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--run-file',required=True,type=Path)
    parser.add_argument('--resource-dir',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--deployment',type=Path)
    parser.add_argument('--grant-index',type=int,default=0)
    parser.add_argument('--can-channel')
    parser.add_argument('--can-interface')
    parser.add_argument('--eth-interface')
    parser.add_argument('--source-mac')
    parser.add_argument('--destination-mac')
    args=parser.parse_args()
    try:
        contract=Contract.load(args.contract_dir,expected_sha256=args.expected_sha256)
        plan,inputs,resources=load_plan(args.run_file,contract,args.resource_dir or args.contract_dir)
        links={a.link_id for a in plan.actions}
        deployment=grant=None
        if not args.dry_run:
            if args.deployment is None:
                raise ICDError('SCHEMA','actual transmission requires an explicit shared deployment')
            deployment=load_deployment(args.deployment,contract)
            if not 0<=args.grant_index<len(deployment.grants):
                raise ICDError('RANGE','explicit existing deployment grant index required')
            grant=deployment.grants[args.grant_index]
            if grant.identity['model_id']!=plan.model_id:
                raise ICDError('MODEL','generated model and actual source grant differ')
            for action in plan.actions:
                role=contract.entry(action.stimulus['message_id'])['role']
                if role!='ANY_SESSION_ROLE' and role not in grant.roles:
                    raise ICDError('AUTHORIZATION','all generated roles must be explicitly granted before TX')
            if 'CANT' in links and not any(b.channel==args.can_channel and b.peer==args.can_interface
                    and b.transport=='CANFD' for b in grant.bindings):
                raise ICDError('AUTHORIZATION','CANT mapping must match the selected shared source grant')
            if 'ETHGEN' in links and any(v is None for v in (args.eth_interface,args.source_mac,args.destination_mac)):
                raise ICDError('SCHEMA','original ETHGEN needs explicit interface/source/destination MAC')
        with ExitStack() as stack:
            output=stack.enter_context(_new_output(args.output))
            _write(output,{'format':'HIL_RECEPTION_RUN_1','profile':'RECEPTION_ONLY',
                'source_kind':plan.source_kind,'model_id':plan.model_id,'baseline_sha256':plan.baseline_sha256,
                'sample_count':len(plan.actions),'validation_scope':'WIRE_SCHEMA_SESSION_ONLY',
                'assertions_status':'NOT_EVALUATED','deferred_assertions':[loads(a) for a in plan.deferred_assertions_json],
                'cleanup_status':'LOCAL_OWNERS_ONLY_NOT_MODEL_CLEANUP','model_application_verified':False,
                'replacement_ready':False,'physical_tool_qualification':'NOT_EVALUATED',
                'transmission_status':'NOT_STARTED'})
            if args.dry_run:
                for sample in plan.actions:
                    _write(output,{'format':'HIL_GENERATED_SAMPLE_1','event_id':sample.event_id,'link_id':sample.link_id,
                        'planned_target_step':sample.step,'stimulus':sample.stimulus,'transmitted':False})
                print(json.dumps({'status':'GENERATED_NOT_TRANSMITTED','sample_count':len(plan.actions),
                    'output':str(args.output.resolve()),'model_application_verified':False}))
                return 0
            from .replay_export import ExportBinding
            from .udp_source import UDPSource
            book=ChannelReservations()
            udp_binding=next(b for b in grant.bindings if b.transport=='UDP')
            host,port=udp_binding.peer.rsplit(':',1)
            network=dict(source_bind=(host,int(port)),feedback_bind=deployment.feedback_routes[udp_binding],
                         receiver_endpoint=deployment.bind)
            if 'ETHGEN' in links:
                from .scapy_source import ScapySource
                binding=ExportBinding(deployment.channel,args.eth_interface,args.source_mac,args.destination_mac)
                token=book.reserve('generated-eth','ETHGEN',(args.eth_interface,),mode='SEND')
                stack.callback(book.release,token)
                transport=ScapySource(contract,**network,binding=binding,reservations=book,reservation=token)
            else:
                transport=UDPSource(contract,**network,channel=deployment.channel)
            stack.callback(transport.close)
            session=SourceSession(transport,grant.identity,grant.roles,max_records=4096)
            stack.callback(session.close)
            stack.callback(_save_sessions,output,session)
            sender=None
            if 'CANT' in links:
                from .can_signal import CANSignalSender
                from .live_tool_input import LiveToolInputBuilder
                from .protocol import ProtocolParser
                token=book.reserve('generated-can','CANT',(args.can_interface,),mode='SEND')
                stack.callback(book.release,token)
                protocol=ProtocolParser(contract)
                protocol.parse(inputs['protocol'],resources)
                builder=LiveToolInputBuilder(book,session,protocol=protocol)
                sender=CANSignalSender(builder,token,ExportBinding(args.can_channel,args.can_interface),max_records=65536)
                stack.callback(sender.close)
            run=SendRun(plan,session,can_sender=sender)
            rows=run.run(on_record=lambda record:_write(output,record.document()))
            _write(output,{'format':'HIL_RECEPTION_SUMMARY_1','status':'RECEPTION_VALIDATED',
                'completed_samples':len(rows),'model_application_verified':False,'replacement_ready':False})
        print(json.dumps({'status':'RECEPTION_VALIDATED','completed_samples':len(rows),
            'output':str(args.output.resolve()),'model_application_verified':False,'replacement_ready':False}))
        return 0
    except (ICDError,OSError,ValueError) as error:
        print(json.dumps({'status':'FAILED','error':error.code if isinstance(error,ICDError) else 'RESOURCE',
            'detail':str(error),'replacement_ready':False}),flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
