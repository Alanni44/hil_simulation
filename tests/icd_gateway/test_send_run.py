"""Self-generated inputs through original CAN/Scapy tools into the real Receiver."""

import importlib.util
import math
import base64
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import select
import socket
import threading
import time
import uuid
import can
from scapy.layers.inet import UDP
from scapy.layers.l2 import Ether
from scapy.supersocket import SimpleSocket

from common import GatewayTest, message
from test_source_inputs import resources, source_inputs
from test_scenario import scenario, send, periodic, stop
from test_waveform import event as wave_event
from test_udp import available_port
from icd_gateway.can_ingress import CANGateway
from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.json_codec import loads
from input_simulator.can_signal import CANSignalSender
from input_simulator.live_tool_input import LiveToolInputBuilder
from input_simulator.protocol import ProtocolParser
from input_simulator.replay_export import ExportBinding
from input_simulator.scapy_source import ScapySource
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations
from input_simulator.udp_source import UDPSource


class SendRunTests(GatewayTest):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.send_run'),'runnable self-generated send profile missing')
        from input_simulator import send_run
        return send_run

    def protocol(self, **changes):
        return self.module().SendPlan.protocol(self.contract,source_inputs(),resources(),
            model_id='quadrotor_hil',stimuli=[{'message_id':10,'payload':message(10)['payload']}],
            **{'count':3,'period_steps':80,'first_step':0,**changes})

    def scenario_plan(self, events, *, assertions=None):
        value=source_inputs()
        value['scenario']=scenario(events)
        if assertions is not None:
            value['scenario']['assertions']=assertions
        return self.module().SendPlan.scenario(self.contract,value,resources(),model_id='quadrotor_hil')

    def test_protocol_requires_complete_explicit_payload_and_generates_samples(self):
        plan=self.protocol()
        self.assertEqual([a.step for a in plan.actions],[0,80,160])
        self.assertEqual([a.link_id for a in plan.actions],['CANT']*3)
        self.assertEqual(plan.actions[0].stimulus['payload'],message(10)['payload'])
        self.assertEqual(plan.source_kind,'PROTOCOL')
        self.assertFalse(plan.model_application_verified)
        self.rejects('SCHEMA',lambda:self.protocol(count=True))
        self.rejects('CAPACITY',lambda:self.protocol(count=100000))

    def test_original_float_sign_is_preserved_in_generated_and_received_snapshots(self):
        stimulus={'message_id':10,'payload':message(10)['payload']}
        stimulus['payload']['wind_n_mps']=-0.0
        plan=self.module().SendPlan.protocol(self.contract,source_inputs(),resources(),model_id='quadrotor_hil',
            stimuli=[stimulus],count=1,period_steps=80,first_step=0)
        self.assertEqual(math.copysign(1,plan.actions[0].stimulus['payload']['wind_n_mps']),-1)
        self.network()
        rows=self.module().SendRun(plan,self.source,can_sender=self.can_sender).run()
        self.assertEqual(math.copysign(1,loads(rows[0].request_json)['payload']['wind_n_mps']),-1)
        self.assertEqual(math.copysign(1,loads(self.reception.records[0].message_json)['payload']['wind_n_mps']),-1)

    def test_long_stream_explicitly_opens_new_session_without_model_reset_claim(self):
        plan=self.protocol(count=2,period_steps=1100)
        self.network()
        rows=self.module().SendRun(plan,self.source,can_sender=self.can_sender).run()
        requests=[loads(row.request_json) for row in rows]
        self.assertNotEqual(requests[0]['header']['session_id'],requests[1]['header']['session_id'])
        self.assertEqual(len(self.reception.records),2)
        self.assertEqual([row.request['message_id'] for row in self.source.records],[1,1])

    def test_partial_can_send_persists_actual_first_frame_and_uncertain_failed_attempt(self):
        self.network()
        run=self.module().SendRun(self.protocol(count=1),self.source,can_sender=self.can_sender)
        actual=self.bus.send
        calls=[]
        def partial(frame,**kwargs):
            calls.append(frame)
            if len(calls)==2:
                raise can.CanError('test second frame failed')
            return actual(frame,**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'failed.jsonl'
            with output.open('x',encoding='utf-8') as log,patch.object(self.bus,'send',side_effect=partial):
                self.rejects('RESOURCE',lambda:run.run(on_record=lambda row:log.write(json.dumps(row.document())+'\n')))
            row=json.loads(output.read_text())
        self.assertEqual(row['sent_fragments'],1)
        tx=[r for r in row['native_observations'] if r.get('kind')=='TX']
        self.assertEqual(len(tx),2)
        self.assertEqual(tx[0]['send_completed'],True)
        self.assertIsNone(tx[1]['send_completed'])
        self.assertEqual(tx[1]['error'],'RESOURCE')
        self.assertEqual(bytes.fromhex(tx[0]['data']['data']),bytes(calls[0].data))
        self.assertEqual(self.reception.records,())

    def test_partial_scapy_send_persists_full_and_failed_original_frames(self):
        payload=message(34)['payload']
        raw=b'x'*4096
        payload.update(size_bytes=len(raw),chunk_length=len(raw),data_base64=base64.b64encode(raw).decode('ascii'),
            chunk_sha256=hashlib.sha256(raw).hexdigest(),resource_sha256=hashlib.sha256(raw).hexdigest(),final=True)
        plan=self.scenario_plan([send(step=0,mid=34,stimulus={'message_id':34,'payload':payload})])
        self.network(scapy=True)
        self.reception.message_ids=self.reception._message_ids=(34,)
        self.source.open()
        actual=self.l2.send
        calls=[]
        def partial(frame):
            calls.append(frame)
            if len(calls)==2:
                raise OSError('test second Ethernet frame failed')
            return actual(frame)
        run=self.module().SendRun(plan,self.source)
        documents=[]
        with patch.object(self.l2,'send',side_effect=partial):
            self.rejects('RESOURCE',lambda:run.run(on_record=lambda row:documents.append(row.document())))
        row=documents[0]
        self.assertEqual(row['sent_fragments'],1)
        self.assertEqual(len(row['native_observations']),2)
        first,failed=row['native_observations']
        self.assertEqual(bytes.fromhex(first['ethernet_data']['data']),bytes(calls[0]))
        self.assertEqual(first['sent_bytes'],len(bytes(calls[0])))
        self.assertIsNone(failed['sent_bytes'])
        self.assertEqual(failed['error'],'RESOURCE')
        self.assertEqual(self.reception.records,())

    def test_scenario_reuses_waveform_full_snapshots_and_periodic_stop(self):
        wave=wave_event(at_step=0,duration_steps=160,sample_period_steps=80,
            waveform={'kind':'RAMP','start_value':0,'end_value':16,'duration_steps':160})
        plan=self.scenario_plan([wave])
        self.assertEqual([a.stimulus['payload']['wind_n_mps'] for a in plan.actions],[0,8,16])
        self.assertTrue(all(len(a.stimulus['payload'])==6 for a in plan.actions))
        plan=self.scenario_plan([periodic(count=10,period_steps=80),stop(step=160,priority=50)])
        self.assertEqual([a.step for a in plan.actions],[0,80])

    def test_effect_handlers_and_external_replay_are_not_silently_dropped(self):
        assertion=source_inputs()['scenario']['assertions'][0]
        wait={'event_id':'wait','at_step':20,'priority':1,'link_id':'ETHGEN','type':'WAIT',
              'assertion':{**assertion,'assertion_id':'wait-probe'}}
        self.rejects('TARGET_MISSING',lambda:self.scenario_plan([send(step=0),wait]))
        plan=self.scenario_plan([send(step=0)],assertions=[assertion])
        self.assertEqual([loads(raw) for raw in plan.deferred_assertions_json],[assertion])
        self.assertFalse(plan.model_application_verified)
        self.rejects('TARGET_MISSING',lambda:self.scenario_plan([send(step=0,link_id='CUTIL')]))

    def network(self, *, scapy=False):
        endpoint=('127.0.0.1',available_port())
        self.book=ChannelReservations()
        self.binding=ExportBinding('CANFD_0','can0')
        self.token=self.book.reserve('send-test','CANT',('can0',),mode='SEND')
        self.frames=[]
        self.sink=None
        if scapy:
            left,self.sink=socket.socketpair()
            self.l2=SimpleSocket(left,Ether)
            binding=ExportBinding('ETH_0','eth0','02:00:00:00:00:01','02:00:00:00:00:02')
            token=self.book.reserve('send-test-eth','ETHGEN',('eth0',),mode='SEND')
            self.transport=ScapySource(self.contract,source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),
                receiver_endpoint=endpoint,binding=binding,reservations=self.book,reservation=token,l2socket=self.l2)
        else:
            self.transport=UDPSource(self.contract,source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),
                receiver_endpoint=endpoint,channel='ETH_0')
        self.source=SourceSession(self.transport,message(1)['payload']['identity'],('STIMULUS',),max_records=4096)
        udp=PeerBinding('ETH_0','UDP',f'127.0.0.1:{self.transport.source_endpoint[1]}')
        can_binding=PeerBinding('CANFD_0','CANFD','can0')
        registry=SessionRegistry(self.contract,[SourceGrant(message(1)['payload']['identity'],('STIMULUS',),(udp,can_binding))])
        self.reception=ReceptionService(self.contract,registry,(10,))
        self.receiver=Receiver(self.contract,registry,reception_service=self.reception)
        self.gateway=UDPGateway(self.receiver,bind=endpoint,feedback_routes={udp:self.transport.feedback_endpoint},channel='ETH_0')
        channel=uuid.uuid4().hex
        self.bus=can.Bus(interface='virtual',channel=channel,ignore_config=True)
        peer=can.Bus(interface='virtual',channel=channel,ignore_config=True)
        self.can_gateway=CANGateway(self.receiver,channel='CANFD_0',interface='can0',bus=peer)
        parser=ProtocolParser(self.contract)
        parser.parse(source_inputs()['protocol'],resources())
        builder=LiveToolInputBuilder(self.book,self.source,protocol=parser)
        self.can_sender=CANSignalSender(builder,self.token,self.binding,bus=self.bus)
        self.stop_event=threading.Event()
        self.errors=[]
        def run():
            buffer=b''
            try:
                while not self.stop_event.is_set():
                    if self.sink is not None and select.select([self.sink],[],[],0)[0]:
                        block=self.sink.recv(65536)
                        if not block:
                            break
                        buffer+=block
                        while len(buffer)>=34 and len(buffer)>=14+int.from_bytes(buffer[16:18],'big'):
                            size=14+int.from_bytes(buffer[16:18],'big')
                            frame=Ether(buffer[:size])
                            buffer=buffer[size:]
                            self.frames.append(bytes(frame))
                            # Test NIC relay only: production never substitutes UDP for Scapy.
                            self.transport.socket.sendto(bytes(frame[UDP].payload),endpoint)
                    self.gateway.poll(timeout=0.001)
                    self.can_gateway.poll(timeout=0)
            except Exception as exc:
                self.errors.append(exc)
        self.thread=threading.Thread(target=run)
        self.thread.start()
        self.addCleanup(self.close_network)

    def close_network(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.can_sender.close()
        self.source.close()
        self.transport.close()
        if self.sink is not None:
            self.sink.close()
        self.can_gateway.close()
        self.gateway.close()
        self.assertEqual(self.errors,[])

    def test_protocol_cant_generates_and_receiver_decodes_real_library_frames(self):
        plan=self.protocol()
        self.network()
        run=self.module().SendRun(plan,self.source,can_sender=self.can_sender)
        rows=run.run()
        self.assertEqual(len(rows),3)
        self.assertEqual(len(self.reception.records),3)
        self.assertTrue(all(r.error is None for r in rows))
        self.assertTrue(all(r.validation_scope=='WIRE_SCHEMA_SESSION_ONLY' for r in rows))
        self.assertEqual([loads(r.message_json)['header']['target_step'] for r in self.reception.records],[0,80,160])
        self.assertTrue(all(r.binding.transport=='CANFD' for r in self.reception.records))
        self.assertTrue(any(r.kind=='TX' and r.send_completed for r in self.can_sender.records))
        self.rejects('STATE',run.run)

    def test_scenario_ethgen_scapy_self_generates_ramp_and_receiver_gets_exact_values(self):
        plan=self.scenario_plan([wave_event(at_step=0,duration_steps=160,sample_period_steps=80,
            waveform={'kind':'RAMP','start_value':0,'end_value':16,'duration_steps':160})])
        self.network(scapy=True)
        rows=self.module().SendRun(plan,self.source).run()
        self.assertEqual([loads(r.message_json)['payload']['wind_n_mps'] for r in self.reception.records],[0,8,16])
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r.error is None for r in rows))
        self.assertGreaterEqual(len(self.frames),4)
        self.assertTrue(all(r.sent_bytes==len(r.ethernet_data) and r.error is None for r in self.transport.l2_records))
        self.assertFalse(self.receiver._closed)

    def test_missing_native_ethgen_does_not_fallback_or_open_session(self):
        plan=self.scenario_plan([send(step=0)])
        self.network()
        self.rejects('TARGET_MISSING',lambda:self.module().SendRun(plan,self.source))
        self.assertIsNone(self.source.session_id)

    def test_missing_receiver_implementation_stops_before_first_data_tx(self):
        plan=self.protocol()
        self.network()
        self.receiver.reception_service.message_ids=(11,)
        self.receiver.reception_service._message_ids=(11,)
        run=self.module().SendRun(plan,self.source,can_sender=self.can_sender)
        self.rejects('TARGET_MISSING',run.run)
        self.assertEqual(self.reception.records,())
        self.assertFalse(any(r.kind=='TX' for r in self.can_sender.records))
