import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import can
from contextlib import redirect_stdout
import io
from unittest.mock import patch

from common import EXPECTED, INTERFACES, ROOT, GatewayTest, message
import test_cli
from test_source_inputs import source_inputs
from test_waveform import event as wave_event
from icd_gateway.config import load_deployment
from input_simulator.session import SourceSession
from input_simulator.udp_source import UDPSource


class SendCLITests(GatewayTest):
    def config(self, kind='PROTOCOL'):
        inputs=source_inputs()
        inputs['scenario']['events']=[wave_event(at_step=0,duration_steps=160,sample_period_steps=80,
            waveform={'kind':'RAMP','start_value':0,'end_value':16,'duration_steps':160})]
        return {'profile':'RECEPTION_ONLY','source_kind':kind,'model_id':'quadrotor_hil',
            'source_inputs':inputs,'generation':None if kind=='SCENARIO' else {
                'stimuli':[{'message_id':10,'payload':message(10)['payload']}],
                'count':3,'period_steps':80,'first_step':0}}

    def command(self, config, output, *extra):
        return [sys.executable,'-X','utf8','-m','input_simulator.send_cli',
            '--contract-dir',str(INTERFACES),'--expected-sha256',EXPECTED,
            '--run-file',str(config),'--output',str(output),*extra]

    def test_dry_run_generates_complete_two_sources_without_network_or_model_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            path,output=Path(folder)/'run.json',Path(folder)/'samples.jsonl'
            for kind in ('PROTOCOL','SCENARIO'):
                path.write_text(json.dumps(self.config(kind)),encoding='utf-8')
                result=subprocess.run(self.command(path,output,'--dry-run'),cwd=ROOT,
                    capture_output=True,text=True,encoding='utf-8',timeout=15)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                report=json.loads(result.stdout)
                self.assertEqual(report['status'],'GENERATED_NOT_TRANSMITTED')
                rows=[json.loads(line) for line in output.read_text().splitlines()]
                self.assertEqual([r['planned_target_step'] for r in rows[1:]],[0,80,160])
                self.assertEqual(rows[0]['model_application_verified'],False)
                if kind=='SCENARIO':
                    self.assertEqual(rows[0]['assertions_status'],'NOT_EVALUATED')
                    self.assertTrue(rows[0]['deferred_assertions'])
                    self.assertEqual([r['stimulus']['payload']['wind_n_mps'] for r in rows[1:]],[0,8,16])
                output.unlink()

    def test_invalid_config_and_existing_output_fail_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path,output=Path(folder)/'run.json',Path(folder)/'data.jsonl'
            value=self.config()
            value['hidden_default']=True
            path.write_text(json.dumps(value),encoding='utf-8')
            result=subprocess.run(self.command(path,output,'--dry-run'),cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads(result.stdout)['error'],'SCHEMA')
            self.assertFalse(output.exists())
            path.write_text(json.dumps(self.config()),encoding='utf-8')
            output.write_bytes(b'existing-evidence\n')
            result=subprocess.run(self.command(path,output,'--dry-run'),cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(output.read_bytes(),b'existing-evidence\n')

    def test_optional_native_can_grants_are_exact_and_unambiguous(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'deployment.json'
            value=test_cli.CLITests.deployment(self)
            value['grants'][0]['can_bindings']=[{'channel':'CANFD_0','interface':'can0'}]
            path.write_text(json.dumps(value),encoding='utf-8')
            deployment=load_deployment(path,self.contract)
            self.assertEqual(deployment.can_bindings,(deployment.grants[0].bindings[1],))
            self.assertEqual(deployment.can_bindings[0].transport,'CANFD')
            value['grants'][0]['can_bindings'][0]['interface']='any'
            path.write_text(json.dumps(value),encoding='utf-8')
            self.rejects('SCHEMA',lambda:load_deployment(path,self.contract))

    def test_native_backend_failure_is_explicit_before_any_data_tx(self):
        from input_simulator.send_cli import main
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            config,output,deployment=folder/'run.json',folder/'sent.jsonl',folder/'deployment.json'
            config.write_text(json.dumps(self.config()),encoding='utf-8')
            value=test_cli.CLITests.deployment(self)
            value['grants'][0]['can_bindings']=[{'channel':'CANFD_0','interface':'can0'}]
            deployment.write_text(json.dumps(value),encoding='utf-8')
            command=self.command(config,output,'--deployment',str(deployment),'--can-channel','CANFD_0','--can-interface','can0')
            stdout=io.StringIO()
            with patch.object(sys,'argv',command[4:]),patch('can.Bus',side_effect=OSError('test unavailable original backend')):
                with redirect_stdout(stdout):
                    code=main()
            self.assertEqual(code,1)
            self.assertEqual(json.loads(stdout.getvalue())['error'],'TARGET_MISSING')
            rows=[json.loads(line) for line in output.read_text().splitlines()]
            self.assertFalse(any(r['format']=='HIL_RECEPTION_TX_1' for r in rows))

    def test_generated_source_cli_keeps_session_and_native_records_with_real_library_bus(self):
        from test_send_run import SendRunTests
        from input_simulator.send_cli import main
        helper=SendRunTests()
        helper.contract=self.contract
        helper.network()
        endpoint=helper.transport.source_endpoint
        feedback=helper.transport.feedback_endpoint
        helper.source.close()
        helper.transport.close()
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder=Path(folder)
                config,output,deployment=folder/'run.json',folder/'sent.jsonl',folder/'deployment.json'
                config.write_text(json.dumps(self.config()),encoding='utf-8')
                address=lambda v:{'ip':v[0],'port':v[1]}
                value={'mode':'DEVELOPMENT','channel':'ETH_0','receiver_bind':address(helper.gateway.address),
                    'grants':[{'identity':message(1)['payload']['identity'],'roles':['STIMULUS'],
                        'source_endpoint':address(endpoint),'feedback_endpoint':address(feedback),
                        'can_bindings':[{'channel':'CANFD_0','interface':'can0'}]}]}
                deployment.write_text(json.dumps(value),encoding='utf-8')
                command=self.command(config,output,'--deployment',str(deployment),
                    '--can-channel','CANFD_0','--can-interface','can0')
                stdout=io.StringIO()
                with patch.object(sys,'argv',command[4:]),patch('can.Bus',return_value=helper.bus),redirect_stdout(stdout):
                    code=main()
                self.assertEqual(code,0,stdout.getvalue())
                rows=[json.loads(line) for line in output.read_text().splitlines()]
                transmitted=[r for r in rows if r['format']=='HIL_RECEPTION_TX_1']
                sessions=[r for r in rows if r['format']=='HIL_RECEPTION_SESSION_1']
                self.assertEqual(len(transmitted),3)
                self.assertTrue(all(r['native_observations'] for r in transmitted))
                self.assertEqual(len(sessions),1)
                self.assertEqual(sessions[0]['request']['message_id'],1)
                self.assertEqual(sessions[0]['reply']['message_id'],129)
                self.assertEqual(len(helper.reception.records),3)
        finally:
            self.assertTrue(helper.doCleanups())

    def test_receiver_process_retains_actual_decoded_standard_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            deployment=test_cli.CLITests.deployment(self)
            config,log=folder/'deployment.json',folder/'received.jsonl'
            config.write_text(json.dumps(deployment),encoding='utf-8')
            grant=deployment['grants'][0]
            unpack=lambda v:(v['ip'],v['port'])
            transport=UDPSource(self.contract,source_bind=unpack(grant['source_endpoint']),
                feedback_bind=unpack(grant['feedback_endpoint']),receiver_endpoint=unpack(deployment['receiver_bind']),channel='ETH_0')
            session=SourceSession(transport,grant['identity'],tuple(grant['roles']))
            command=[sys.executable,'-X','utf8','-m','icd_gateway','--contract-dir',str(INTERFACES),
                '--expected-sha256',EXPECTED,'--deployment',str(config),'--receive-only',
                '--received-jsonl',str(log),'--max-receptions','1']
            process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            lines=queue.Queue()
            reader=threading.Thread(target=lambda:lines.put(process.stdout.readline()),daemon=True)
            reader.start()
            try:
                ready=json.loads(lines.get(timeout=15))
                self.assertEqual(ready['status'],'DEVELOPMENT_READY')
                self.assertFalse(ready['replacement_ready'])
                session.open()
                item=session.prepare_input({'message_id':10,'payload':message(10)['payload']},'UDP',target_step=0)
                transport.send(item.message,owner=session)
                replies=[transport.receive_for(item.message,timeout=0.5,owner=session) for _ in range(2)]
                self.assertEqual([r['payload']['stage'] for r in replies],['RECEIVED','VALIDATED'])
                stdout,stderr=process.communicate(timeout=10)
                self.assertEqual(process.returncode,0,stdout+stderr)
                record=json.loads(log.read_text())
                self.assertEqual(record['message'],item.message)
                self.assertEqual(record['identity'],grant['identity'])
                self.assertEqual(record['validation_scope'],'WIRE_SCHEMA_SESSION_ONLY')
                self.assertFalse(record['model_applied'])
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)
                reader.join(timeout=1)
                session.close()
                transport.close()

    def test_receiver_cli_flushes_decoded_tail_when_native_feedback_fails(self):
        from icd_gateway.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            value=test_cli.CLITests.deployment(self)
            value['grants'][0]['can_bindings']=[{'channel':'CANFD_0','interface':'can0'}]
            config,log=folder/'deployment.json',folder/'decoded.jsonl'
            config.write_text(json.dumps(value),encoding='utf-8')
            channel=uuid.uuid4().hex
            bus=can.Bus(interface='virtual',channel=channel,ignore_config=True)
            peer=can.Bus(interface='virtual',channel=channel,ignore_config=True)
            grant=value['grants'][0]
            unpack=lambda v:(v['ip'],v['port'])
            transport=UDPSource(self.contract,source_bind=unpack(grant['source_endpoint']),
                feedback_bind=unpack(grant['feedback_endpoint']),receiver_endpoint=unpack(value['receiver_bind']),channel='ETH_0')
            session=SourceSession(transport,grant['identity'],tuple(grant['roles']))
            arguments=['gateway','--contract-dir',str(INTERFACES),'--expected-sha256',EXPECTED,
                '--deployment',str(config),'--receive-only','--received-jsonl',str(log),'--can']
            stdout=io.StringIO()
            results,errors=[],[]
            def serve():
                try:
                    results.append(main())
                except Exception as error:
                    errors.append(error)
            with patch.object(sys,'argv',arguments),patch('can.Bus',return_value=bus),\
                    patch.object(bus,'send',side_effect=can.CanError('test feedback failed')),redirect_stdout(stdout):
                thread=threading.Thread(target=serve)
                thread.start()
                try:
                    until=time.monotonic()+10
                    while 'DEVELOPMENT_READY' not in stdout.getvalue() and time.monotonic()<until:
                        time.sleep(0.01)
                    self.assertIn('DEVELOPMENT_READY',stdout.getvalue())
                    session.open()
                    item=session.prepare_input({'message_id':10,'payload':message(10)['payload']},'CANFD',target_step=0)
                    for frame in item.frames:
                        peer.send(can.Message(arbitration_id=frame.arbitration_id,data=frame.data,
                            is_extended_id=False,is_fd=True,bitrate_switch=True,check=True))
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors,[])
                    self.assertEqual(results,[1])
                    self.assertEqual(json.loads(log.read_text())['message'],item.message)
                finally:
                    peer.shutdown()
                    session.close()
                    transport.close()
                    bus.shutdown()
