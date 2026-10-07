"""Original python-can virtual-library tests, not a Windows device backend."""

import copy
from dataclasses import FrozenInstanceError, replace
import importlib
import socket
import threading
import unittest
import uuid
from unittest.mock import patch

import can

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame
from input_simulator.dispatch import UDPDispatcher
from input_simulator.live_tool_input import LiveToolInputBuilder
from input_simulator.protocol import ProtocolParser
from input_simulator.replay_export import ExportBinding
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations
from input_simulator.udp_source import UDPSource
from test_source_inputs import resources, source_inputs
from test_source_session import LocalClock


class CANSignalTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.can_signal'),'original CANT sender missing')
        self.module=importlib.import_module('input_simulator.can_signal')
        channel='test-'+uuid.uuid4().hex
        self.bus=can.Bus(interface='virtual',channel=channel,ignore_config=True)
        self.peer=can.Bus(interface='virtual',channel=channel,ignore_config=True)
        self.addCleanup(self.bus.shutdown)
        self.addCleanup(self.peer.shutdown)
        self.book=ChannelReservations()
        self.token=self.book.reserve('can-signal','CANT',('can0',),mode='SEND')
        self.binding=ExportBinding('CANFD_0','can0')
        self.clock=LocalClock()

    def live(self,model='quadrotor_hil',*,implemented=None):
        receiver=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        receiver.bind(('127.0.0.1',0)); receiver.settimeout(1)
        self.receiver=receiver
        self.addCleanup(receiver.close)
        self.transport=UDPSource(self.contract,source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),
                                 receiver_endpoint=receiver.getsockname(),channel='ETH_0')
        self.addCleanup(self.transport.close)
        identity=message(1)['payload']['identity']; identity['model_id']=model
        self.session=SourceSession(self.transport,identity,('STIMULUS','CONTROLLER','OBSERVER'),clock=self.clock)
        errors=[]
        def opening():
            try: self.session.open()
            except Exception as error: errors.append(error)
        thread=threading.Thread(target=opening); thread.start()
        packet,_=receiver.recvfrom(1500)
        fragment=self.transport.wire.decode(packet,'UDP',direction='TO_36')
        original=Reassembler(self.contract).push(fragment,channel='ETH_0',direction='TO_36',authorized=True,now_ns=0).message
        grant=message(129)
        grant['header'].update(session_id=73,sequence=1,transaction_id=original['header']['transaction_id'])
        grant['payload'].update(session_id=73,accepted_roles=original['payload']['roles'])
        grant['payload']['capabilities']['model_ids']=[model]
        grant['payload']['capabilities']['implemented_message_ids']=[1,2,7,8,9,10,11,12,13,14,15,16] if implemented is None else list(implemented)
        for value in self.transport.wire.encode(grant,'UDP'):
            receiver.sendto(value,self.transport.feedback_endpoint)
        thread.join(2)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors,[])
        parser=ProtocolParser(self.contract); parser.parse(source_inputs()['protocol'],resources())
        self.builder=LiveToolInputBuilder(self.book,self.session,protocol=parser)

    def sender(self,**kwargs):
        value=self.module.CANSignalSender(self.builder,self.token,self.binding,bus=self.bus,**kwargs)
        self.addCleanup(value.close)
        return value

    def plan(self,mid=7,**kwargs):
        return self.builder.prepare(self.token,{'message_id':mid,'payload':message(mid)['payload']},
                                    self.binding,target_step=100,**kwargs)

    def consume(self,plan):
        for original in plan.source_input.frames:
            actual=self.peer.recv(0.1)
            self.assertIsNotNone(actual)
            self.assertEqual((actual.arbitration_id,bytes(actual.data)),(original.arbitration_id,original.data))
            self.assertEqual((actual.is_fd,actual.bitrate_switch,actual.is_extended_id,actual.is_remote_frame,
                              actual.is_error_frame,actual.error_state_indicator,actual.dlc),(True,True,False,False,False,False,64))

    def emit(self,plan,*,sequence=2,mid=130,stage='FAILED',error='TARGET_MISSING'):
        reply=message(mid)
        header=plan.source_input.message['header']
        reply['header'].update(session_id=header['session_id'],sequence=sequence,transaction_id=header['transaction_id'])
        if mid==130:
            reply['payload'].update(request_sequence=header['sequence'],request_message_id=plan.source_input.message['message_id'],stage=stage,error=error)
        for frame in self.transport.wire.encode(reply,'CANFD'):
            self.peer.send(can.Message(arbitration_id=frame.arbitration_id,data=frame.data,is_extended_id=False,
                                      is_fd=True,bitrate_switch=True,check=True))
        return reply

    def test_actual_original_can_group_and_immutable_attempts(self):
        self.live(); sender=self.sender(); plan=self.plan()
        self.assertEqual(sender.send(plan),len(plan.source_input.frames))
        self.consume(plan)
        rows=[r for r in sender.records if r.kind=='TX']
        self.assertEqual([r.data for r in rows],[f.data for f in plan.source_input.frames])
        self.assertTrue(all(r.send_completed and r.error is None for r in rows))
        with self.assertRaises(FrozenInstanceError): rows[0].data=b'changed'
        self.assertFalse(sender.execution_ready); self.assertFalse(sender.safety_verified)

    def test_all_eleven_inputs_all_models_original_full_groups(self):
        seen=[]
        for model in ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil'):
            self.live(model); sender=self.sender()
            for mid in (2,7,8,9,10,11,12,13,14,15,16):
                if model not in self.contract.entry(mid)['model_ids']: continue
                plan=self.plan(mid); sender.send(plan); self.consume(plan); seen.append(mid)
            sender.close()
            channel='model-'+uuid.uuid4().hex
            self.bus=can.Bus(interface='virtual',channel=channel,ignore_config=True)
            self.peer=can.Bus(interface='virtual',channel=channel,ignore_config=True)
            self.addCleanup(self.bus.shutdown); self.addCleanup(self.peer.shutdown)
        self.assertEqual(set(seen),{2,7,8,9,10,11,12,13,14,15,16})

    def test_standard_can_feedback_matches_actual_full_tx_and_global_highwater(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        reply=self.emit(plan)
        self.assertEqual(sender.receive_for(plan),reply)
        self.assertEqual(self.session.last_rx_sequence,2)
        self.assertTrue(any(r.kind=='RX' and r.data for r in sender.records))
        self.assertTrue(any(r.kind=='FEEDBACK' and r.error=='TARGET_MISSING' for r in sender.records))

    def test_untransmitted_or_forged_plan_cannot_read_or_send(self):
        self.live(); sender=self.sender(); plan=self.plan()
        self.rejects('STATE',lambda:sender.receive_for(plan,timeout=0))
        self.rejects('STATE',lambda:sender.send(replace(plan)))
        self.assertEqual(sender.records,())

    def test_current_role_capability_and_released_token_checked_before_tx(self):
        from icd_runtime.json_codec import canonicalize
        self.live(); sender=self.sender(); plan=self.plan()
        roles=self.session._roles; self.session._roles=('STIMULUS',)
        self.rejects('AUTHORIZATION',lambda:sender.send(plan)); self.session._roles=roles
        caps=self.session._capabilities_json; value=self.session.capabilities
        value['implemented_message_ids']=[1,2]; self.session._capabilities_json=canonicalize(value)
        self.rejects('TARGET_MISSING',lambda:sender.send(plan)); self.session._capabilities_json=caps
        self.book.release(self.token); self.rejects('STATE',lambda:sender.send(plan))
        self.assertEqual(sender.records,())

    def test_bus_failure_keeps_original_attempt_and_does_not_retry(self):
        self.live(); sender=self.sender(); plan=self.plan()
        with patch.object(self.bus,'send',side_effect=can.CanOperationError('send failed')) as operation:
            self.rejects('RESOURCE',lambda:sender.send(plan))
        operation.assert_called_once()
        row=[r for r in sender.records if r.kind=='TX'][-1]
        self.assertEqual(row.data,plan.source_input.frames[0].data)
        self.assertIsNone(row.send_completed)
        self.assertEqual(row.error,'RESOURCE')
        self.assertEqual(sender.records[-1].request_json,plan.source_input.input_json)
        self.rejects('STATE',lambda:sender.send(plan))

    def test_post_tx_expiry_retains_actual_queued_frame(self):
        self.live(); sender=self.sender(); plan=self.plan(); actual=self.bus.send
        def delayed(frame,timeout=None):
            result=actual(frame,timeout); self.clock.value+=1_000_000_000; return result
        with patch.object(self.bus,'send',delayed):
            self.rejects('STALE_SESSION',lambda:sender.send(plan))
        row=[r for r in sender.records if r.kind=='TX'][-1]
        self.assertTrue(row.send_completed); self.assertEqual(row.error,'STALE_SESSION')
        self.assertEqual(bytes(self.peer.recv(0.1).data),row.data)

    def test_missing_socketcan_default_never_falls_back(self):
        self.live()
        with patch.object(self.module.can,'Bus',side_effect=can.CanInterfaceNotImplementedError('SocketCAN unavailable')) as factory:
            self.rejects('TARGET_MISSING',lambda:self.module.CANSignalSender(self.builder,self.token,self.binding))
        factory.assert_called_once_with(interface='socketcan',channel='can0',fd=True,receive_own_messages=False,ignore_config=True)
        sender=self.sender(); self.assertFalse(sender.safety_verified)

    def test_factory_revocation_keeps_opened_native_bus_owned_until_close(self):
        self.live()
        def opened(**kwargs):
            self.book.release(self.token); return self.bus
        with patch.object(self.module.can,'Bus',opened):
            sender=self.module.CANSignalSender(self.builder,self.token,self.binding)
        self.addCleanup(sender.close)
        self.rejects('STATE',lambda:self.book.reserve('too-early','CANREPLAY',('can0',),mode='SEND'))
        self.assertFalse(self.bus._is_shutdown)
        sender.close(); self.assertTrue(self.bus._is_shutdown)
        self.book.reserve('closed-local','CANREPLAY',('can0',),mode='SEND')

    def test_heartbeat_transaction_cannot_be_reused_after_retirement(self):
        self.live(); sender=self.sender(); first=self.plan(2,transaction_id=10)
        sender.send(first); self.consume(first); self.emit(first,mid=131)
        sender.receive_for(first)
        old=self.plan(2,transaction_id=10)
        self.rejects('STATE',lambda:sender.send(old))
        self.assertIsNone(self.peer.recv(0))

    def test_replacement_builder_preserves_session_heartbeat_transaction_history(self):
        self.live(); first=self.sender(); old=self.plan(2,transaction_id=20)
        first.send(old); self.consume(old); first.retire(old); first.close()
        self.clock.value+=500_000_000; deadline=self.session._deadline_ns
        self.builder=LiveToolInputBuilder(self.book,self.session,protocol=self.builder.protocol)
        self.bus=can.Bus(interface='virtual',channel=self.peer.channel_id,ignore_config=True)
        self.addCleanup(self.bus.shutdown); second=self.sender()
        repeated=self.plan(2,transaction_id=20)
        self.rejects('STATE',lambda:second.send(repeated))
        self.emit(old,mid=131)
        self.rejects('STATE',lambda:second.receive_for(repeated,timeout=0))
        self.assertEqual(self.session._deadline_ns,deadline)
        fresh=self.plan(2,transaction_id=21); second.send(fresh); self.consume(fresh)
        reply=self.emit(fresh,mid=131,sequence=3)
        self.assertEqual(second.receive_for(fresh),reply)

    def test_replacement_builder_does_not_reset_session_can_transmit_sequence_floor(self):
        self.live(); old_builder=self.builder; older=self.plan()
        other=LiveToolInputBuilder(self.book,self.session,protocol=old_builder.protocol)
        self.builder=other; first=self.sender(); newer=self.plan(10)
        first.send(newer); self.consume(newer); first.retire(newer); first.close()
        self.builder=old_builder
        self.bus=can.Bus(interface='virtual',channel=self.peer.channel_id,ignore_config=True)
        self.addCleanup(self.bus.shutdown); second=self.sender()
        self.rejects('STATE',lambda:second.send(older))
        self.assertIsNone(self.peer.recv(0))

    def test_capacity_checked_for_whole_group_before_first_tx(self):
        self.live(); sender=self.sender(max_records=1); plan=self.plan(10)
        self.assertGreater(len(plan.source_input.frames),1)
        self.rejects('BUFFER_FULL',lambda:sender.send(plan))
        self.assertIsNone(self.peer.recv(0)); self.assertEqual(sender.records,())

    def test_attached_dispatcher_prevents_send_close_and_bypass(self):
        self.live(); sender=self.sender(); plan=self.plan()
        dispatcher=UDPDispatcher(self.session); self.addCleanup(dispatcher.close)
        self.rejects('STATE',lambda:sender.send(plan)); self.rejects('STATE',sender.close)
        self.assertFalse(self.bus._is_shutdown)

    def test_local_close_preserves_records_reservation_without_remote_safety(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        original=sender.records; sender.close(); sender.close()
        self.assertEqual(sender.records,original); self.assertTrue(self.bus._is_shutdown)
        self.assertIs(self.book.validate(self.token),self.token)
        self.assertFalse(sender.safety_verified)

    def test_rx_timeout_and_expired_lease_do_not_create_applied(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        self.rejects('TIMEOUT',lambda:sender.receive_for(plan,timeout=0))
        self.clock.value+=1_000_000_000
        self.rejects('STALE_SESSION',lambda:sender.receive_for(plan,timeout=0))
        self.assertFalse(any(r.kind=='FEEDBACK' for r in sender.records))

    def test_partial_group_expiry_before_next_frame_records_group_failure(self):
        self.live(); sender=self.sender(); plan=self.plan(10)
        actual=self.session._verify_input; calls=[]
        def expiring(item):
            calls.append(item)
            if len(calls)==4: self.clock.value+=1_000_000_000
            return actual(item)
        with patch.object(self.session,'_verify_input',expiring):
            self.rejects('STALE_SESSION',lambda:sender.send(plan))
        self.assertEqual(len([r for r in sender.records if r.kind=='TX']),1)
        failed=[r for r in sender.records if r.kind=='FAILED']
        self.assertEqual([r.error for r in failed],['STALE_SESSION'])
        self.assertEqual(failed[0].request_json,plan.source_input.input_json)

    def test_native_feedback_for_other_pending_group_is_retained_not_lost(self):
        self.live(); sender=self.sender()
        a,b=self.plan(7),self.plan(10)
        sender.send(a); self.consume(a); sender.send(b); self.consume(b)
        rb=self.emit(b,sequence=2); ra=self.emit(a,sequence=3)
        self.assertEqual(sender.receive_for(a),ra)
        self.assertEqual(sender.receive_for(b,timeout=0),rb)
        self.assertEqual(sender.pending_count,0)
        self.assertEqual(self.session.last_rx_sequence,3)

    def test_fresh_actual_heartbeat_status_renews_from_original_tx_only(self):
        self.live(); sender=self.sender(); self.clock.value+=50_000_000
        plan=self.plan(2); sender.send(plan); self.consume(plan)
        started=self.clock.value; self.clock.value+=100_000_000
        reply=self.emit(plan,mid=131)
        self.assertEqual(sender.receive_for(plan),reply)
        self.assertEqual(self.session._deadline_ns,started+1_000_000_000)
        self.assertEqual(sender.pending_count,0)

    def test_non_none_backend_return_records_unknown_result_and_fails(self):
        self.live(); sender=self.sender(); plan=self.plan()
        with patch.object(self.bus,'send',return_value=1):
            self.rejects('RESOURCE',lambda:sender.send(plan))
        row=[r for r in sender.records if r.kind=='TX'][-1]
        self.assertIsNone(row.send_completed); self.assertEqual(row.error,'RESOURCE')

    def test_actual_corrupt_native_frame_kept_and_not_applied(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        reply=message(130); h=plan.source_input.message['header']
        reply['header'].update(session_id=73,sequence=2,transaction_id=h['transaction_id'])
        reply['payload'].update(request_sequence=h['sequence'],request_message_id=7,stage='FAILED',error='TARGET_MISSING')
        original=self.transport.wire.encode(reply,'CANFD')[0]
        bad=bytearray(original.data); bad[30]^=1
        self.peer.send(can.Message(arbitration_id=original.arbitration_id,data=bad,is_extended_id=False,is_fd=True,bitrate_switch=True,check=True))
        self.rejects('TIMEOUT',lambda:sender.receive_for(plan,timeout=0))
        rx=[r for r in sender.records if r.kind=='RX']
        self.assertEqual(rx[0].data,bytes(bad)); self.assertEqual(rx[0].error,'CRC')
        self.assertEqual(self.session.last_rx_sequence,1)

    def test_receive_delay_expiry_does_not_allocate_half_group(self):
        self.live(); sender=self.sender(); plan=self.plan(2); sender.send(plan); self.consume(plan)
        self.emit(plan,mid=131)
        actual=self.bus.recv
        def late(timeout=None):
            result=actual(timeout); self.clock.value+=1_000_000_000; return result
        with patch.object(self.bus,'recv',late), patch.object(sender.assembler,'push',wraps=sender.assembler.push) as assembling:
            self.rejects('STALE_SESSION',lambda:sender.receive_for(plan,timeout=0))
        assembling.assert_not_called()
        self.assertEqual(sender.assembler.pending_count,0)
        self.assertEqual(self.session.last_rx_sequence,1)
        self.assertEqual([r.error for r in sender.records if r.kind=='RX'],['STALE_SESSION'])

    def test_second_sender_cannot_replay_attempt_after_success_or_partial_failure(self):
        self.live(); first=self.sender()
        plan=self.plan(); first.send(plan); self.consume(plan)
        first.retire(plan); first.drain_records()
        failed=self.plan(10)
        with patch.object(self.bus,'send',side_effect=can.CanOperationError('unknown result')):
            self.rejects('RESOURCE',lambda:first.send(failed))
        first.retire(failed); first.drain_records()
        first.close()
        self.bus=can.Bus(interface='virtual',channel=self.peer.channel_id,ignore_config=True)
        self.addCleanup(self.bus.shutdown); second=self.sender()
        self.rejects('STATE',lambda:second.send(plan))
        self.rejects('STATE',lambda:second.send(failed))
        self.assertIsNone(self.peer.recv(0))

    def test_one_native_feedback_owner_per_reservation_and_actual_bus(self):
        self.live(); first=self.sender()
        self.rejects('STATE',self.sender)
        other=LiveToolInputBuilder(self.book,self.session,protocol=self.builder.protocol)
        self.rejects('STATE',lambda:self.module.CANSignalSender(other,self.token,self.binding,bus=self.bus))
        token=self.book.reserve('different-can','CANT',('can1',),mode='SEND')
        self.rejects('STATE',lambda:self.module.CANSignalSender(self.builder,token,ExportBinding('CANFD_1','can1'),bus=self.bus))
        self.assertFalse(self.bus._is_shutdown); self.assertFalse(first.safety_verified)

    def test_discarded_actual_pending_plan_can_retire_without_forged_identity(self):
        self.live(); sender=self.sender(max_pending=1); plan=self.plan()
        sender.send(plan); self.consume(plan); self.builder.discard(plan)
        self.rejects('STATE',lambda:sender.retire(replace(plan)))
        self.assertEqual(sender.pending_count,1)
        sender.retire(plan); self.assertEqual(sender.pending_count,0)
        next_plan=self.plan(); sender.send(next_plan); self.consume(next_plan)

    def test_released_reservation_does_not_free_still_open_native_backend(self):
        self.live(); sender=self.sender(); self.book.release(self.token)
        self.rejects('STATE',lambda:self.book.reserve('unsafe-switch','CANREPLAY',('can0',),mode='SEND'))
        actual=self.bus.shutdown
        with patch.object(self.bus,'shutdown',side_effect=can.CanOperationError('still open')):
            self.rejects('RESOURCE',sender.close)
        self.rejects('STATE',lambda:self.book.reserve('unsafe-switch','CANREPLAY',('can0',),mode='SEND'))
        sender.close(); self.assertTrue(self.bus._is_shutdown)
        self.book.reserve('local-stopped','CANREPLAY',('can0',),mode='SEND')

    def test_cached_heartbeat_renews_at_acceptance_not_later_delivery(self):
        self.live(); sender=self.sender(); old=self.session._deadline_ns
        self.clock.value=old-100_000_000
        heartbeat=self.plan(2); sender.send(heartbeat); self.consume(heartbeat)
        started=self.clock.value
        signal=self.plan(); sender.send(signal); self.consume(signal)
        status=self.emit(heartbeat,mid=131,sequence=2)
        ack=self.emit(signal,sequence=3)
        self.assertEqual(sender.receive_for(signal),ack)
        self.assertEqual(self.session._deadline_ns,started+1_000_000_000)
        self.clock.value=old+1
        self.assertEqual(sender.receive_for(heartbeat,timeout=0),status)
        self.assertEqual(self.session._deadline_ns,started+1_000_000_000)

    def test_native_receive_failure_retains_bounded_original_request_evidence(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        with patch.object(self.bus,'recv',side_effect=can.CanOperationError('native receive failed')):
            self.rejects('RESOURCE',lambda:sender.receive_for(plan))
        failed=[r for r in sender.records if r.kind=='FAILED']
        self.assertEqual([r.error for r in failed],['RESOURCE'])
        self.assertEqual(failed[0].request_json,plan.source_input.input_json)

    def test_sender_replacement_after_close_keeps_shared_attempt_history(self):
        self.live(); first=self.sender(); plan=self.plan()
        first.send(plan); self.consume(plan); first.retire(plan); first.close()
        self.bus=can.Bus(interface='virtual',channel=self.peer.channel_id,ignore_config=True)
        self.addCleanup(self.bus.shutdown)
        second=self.sender()
        self.rejects('STATE',lambda:second.send(plan))
        self.builder.discard(plan)
        next_plan=self.plan(); second.send(next_plan); self.consume(next_plan)

    def test_original_role_revocation_after_native_tx_retains_actual_attempt(self):
        self.live(); sender=self.sender(); plan=self.plan(); actual=self.bus.send
        def revoking(frame,timeout=None):
            result=actual(frame,timeout); self.session._roles=('STIMULUS',); return result
        with patch.object(self.bus,'send',revoking):
            self.rejects('AUTHORIZATION',lambda:sender.send(plan))
        tx=[r for r in sender.records if r.kind=='TX']
        self.assertEqual(len(tx),1); self.assertTrue(tx[0].send_completed)
        self.assertEqual(tx[0].error,'AUTHORIZATION')
        self.assertEqual(bytes(self.peer.recv(0.1).data),tx[0].data)
        self.assertEqual(sender.records[-1].error,'AUTHORIZATION')

    def test_full_tx_pool_requires_reserved_failure_slot_before_send(self):
        self.live(); plan=self.plan(10); sender=self.sender(max_records=len(plan.source_input.frames))
        self.rejects('BUFFER_FULL',lambda:sender.send(plan))
        self.assertEqual(sender.records,()); self.assertEqual(sender.pending_count,0)
        self.assertIsNone(self.peer.recv(0))

    def test_invalid_native_metadata_keeps_original_received_wire_bytes(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        self.emit(plan); actual=self.bus.recv; seen=[]
        def invalid(timeout=None):
            frame=actual(timeout)
            if frame is not None:
                seen.append(bytes(frame.data)); frame.timestamp=float('nan')
            return frame
        with patch.object(self.bus,'recv',invalid):
            self.rejects('TIMEOUT',lambda:sender.receive_for(plan,timeout=0))
        rx=[r for r in sender.records if r.kind=='RX']
        self.assertEqual([r.data for r in rx],seen)
        self.assertEqual([r.error for r in rx],['SCHEMA'])
        self.assertEqual(self.session.last_rx_sequence,1)

    def test_close_retry_stops_original_periodic_task_after_shutdown_flag_set(self):
        self.live(); sender=self.sender()
        task=self.bus.send_periodic(can.Message(arbitration_id=1,data=b'\x01',is_extended_id=False),1000)
        actual=task.stop; calls=[]
        def stopping(*args,**kwargs):
            calls.append(True)
            if len(calls)==1: raise can.CanOperationError('periodic stop failed')
            return actual(*args,**kwargs)
        with patch.object(task,'stop',stopping):
            self.rejects('RESOURCE',sender.close)
            self.assertTrue(self.bus._is_shutdown)
            sender.close()
        self.assertEqual(len(calls),2)
        self.assertEqual(self.bus._periodic_tasks,[])
        self.assertFalse(self.bus._open)

    def test_native_socketcan_close_retry_keeps_original_bcm_and_raw_cleanup(self):
        from can.interfaces.socketcan.socketcan import SocketcanBus
        self.live()
        raw=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        bcm=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.addCleanup(raw.close); self.addCleanup(bcm.close)
        class CloseOnce:
            calls=0
            def close(inner):
                inner.calls+=1
                if inner.calls==1: raise can.CanOperationError('BCM cleanup failed')
                bcm.close()
        native=SocketcanBus.__new__(SocketcanBus)
        native._is_shutdown=False; native._periodic_tasks=[]
        closer=CloseOnce(); native._bcm_sockets={'can0':closer}; native.socket=raw
        sender=self.module.CANSignalSender(self.builder,self.token,self.binding,bus=native)
        self.addCleanup(sender.close)
        self.rejects('RESOURCE',sender.close)
        self.assertNotEqual(bcm.fileno(),-1); self.assertNotEqual(raw.fileno(),-1)
        sender.close(); sender.close()
        self.assertEqual(closer.calls,2)
        self.assertEqual((bcm.fileno(),raw.fileno()),(-1,-1))

    def test_drain_preserves_complete_tx_context_and_counter_order(self):
        self.live(); sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
        records=sender.records
        self.assertEqual(sender.drain_records(),records)
        self.assertEqual(sender.records,()); self.assertEqual(sender.pending_count,1)
        self.rejects('STATE',lambda:sender.send(plan))
        reply=self.emit(plan); self.assertEqual(sender.receive_for(plan),reply)

    def test_local_retire_frees_capacity_not_wire_authorization_or_reservation(self):
        self.live(); sender=self.sender(max_pending=1); a,b=self.plan(),self.plan(10)
        sender.send(a); self.consume(a)
        self.rejects('BUFFER_FULL',lambda:sender.send(b))
        sender.retire(a); self.assertEqual(sender.pending_count,0)
        sender.send(b); self.consume(b)
        self.assertIs(self.book.validate(self.token),self.token)
        self.assertFalse(sender.safety_verified)

    def test_strict_limits_timeouts_and_original_binding(self):
        self.live()
        for name in ('max_records','max_bytes','max_pending'):
            for invalid in (True,0,-1,1.5):
                self.rejects('CAPACITY',lambda:self.sender(**{name:invalid}))
        sender=self.sender(); plan=self.plan()
        for invalid in (True,-1,float('nan'),0.03):
            self.rejects('SCHEMA',lambda:sender.send(plan,timeout=invalid))
        self.rejects('STATE',lambda:self.module.CANSignalSender(self.builder,replace(self.token),self.binding,bus=self.bus))
        self.rejects('SCHEMA',lambda:self.module.CANSignalSender(self.builder,self.token,ExportBinding('CANFD_0','can1'),bus=self.bus))

    def test_close_failure_retries_same_actual_bus(self):
        self.live(); sender=self.sender(); actual=self.bus.shutdown; calls=[]
        def failure():
            calls.append(self.bus)
            if len(calls)==1: raise can.CanOperationError('first close failed')
            return actual()
        with patch.object(self.bus,'shutdown',failure):
            self.rejects('RESOURCE',sender.close)
            sender.close(); sender.close()
        self.assertEqual(calls,[self.bus,self.bus]); self.assertTrue(self.bus._is_shutdown)

    def test_all_four_formal_can_channels_map_original_library_groups(self):
        self.live()
        for number in range(4):
            if number:
                self.token=self.book.reserve(f'channel-{number}','CANT',(f'can{number}',),mode='SEND')
                channel='channel-'+uuid.uuid4().hex
                self.bus=can.Bus(interface='virtual',channel=channel,ignore_config=True)
                self.peer=can.Bus(interface='virtual',channel=channel,ignore_config=True)
                self.addCleanup(self.bus.shutdown); self.addCleanup(self.peer.shutdown)
            self.binding=ExportBinding(f'CANFD_{number}',f'can{number}')
            sender=self.sender(); plan=self.plan(); sender.send(plan); self.consume(plan)
            self.assertEqual({r.channel_id for r in sender.records},{f'CANFD_{number}'})

    def test_signed_zero_original_can_bytes_not_normalized(self):
        import math
        self.live(); sender=self.sender(); payload=message(7)['payload']; payload['motor_command'][0]=-0.0
        plan=self.builder.prepare(self.token,{'message_id':7,'payload':payload},self.binding,target_step=100)
        sender.send(plan); self.consume(plan)
        assembled=None; decoder=Reassembler(self.contract)
        for frame in plan.source_input.frames:
            assembled=decoder.push(self.transport.wire.decode(frame,'CANFD'),channel='CANFD_0',direction='TO_36',authorized=True,now_ns=0) or assembled
        self.assertEqual(math.copysign(1,assembled.message['payload']['motor_command'][0]),-1)

    def test_held_session_operation_blocks_other_thread_send_and_close(self):
        self.live(); sender=self.sender(); plan=self.plan(); results=[]
        with self.session._operation():
            def operation():
                for action in (lambda:sender.send(plan),sender.close):
                    try: action()
                    except ICDError as error: results.append(error.code)
                    else: results.append('ACCEPTED')
            thread=threading.Thread(target=operation); thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive()); self.assertEqual(results,['STATE','STATE'])
        self.assertFalse(self.bus._is_shutdown)


if __name__=='__main__': unittest.main()
