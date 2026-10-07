from dataclasses import FrozenInstanceError, replace
import importlib.util
import math
import unittest
from unittest.mock import patch

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from common import EXPECTED, INTERFACES, message
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import WireCodec
from input_simulator.protocol import ProtocolParser
from input_simulator.capture import CaptureParser
from input_simulator.replay_export import ExportBinding
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations
from test_source_inputs import resources, source_inputs
import test_source_session
import test_resource_udp
from test_resources import chunk
from test_capture import pcap


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)

    def setUp(self):
        self.clock = test_source_session.LocalClock()
        self.peer = test_source_session.UnitPeer(self.contract, self.clock)
        self.peer.source_endpoint = ('10.36.0.10', 36102)
        self.peer.receiver_endpoint = ('10.36.0.20', 36100)
        self.session = SourceSession(self.peer, message(1)['payload']['identity'],
                                     ('STIMULUS', 'CONTROLLER', 'OBSERVER'), clock=self.clock)
        self.book = ChannelReservations()
        self.protocol = ProtocolParser(self.contract)
        self.protocol.parse(source_inputs()['protocol'], resources())

    def prepare(self, mid=7, transport='UDP', **kw):
        self.assertTrue(callable(getattr(self.session, 'prepare_input', None)), 'current-grant immutable input preparation missing')
        return self.session.prepare_input({'message_id': mid, 'payload': message(mid)['payload']},
                                          transport, target_step=100, **kw)

    def builder(self, **kw):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.live_tool_input'), 'original live tool input builder missing')
        from input_simulator.live_tool_input import LiveToolInputBuilder
        return LiveToolInputBuilder(self.book, self.session, protocol=self.protocol, **kw)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def binding(self, branch):
        if branch == 'ETHGEN':
            return ExportBinding('ETH_0', 'eth0', '02:00:00:00:00:01', '02:00:00:00:00:02')
        return ExportBinding('CANFD_0', 'can0')

    def token(self, branch):
        return self.book.reserve(branch, branch, (self.binding(branch).interface,), mode='SEND')

    def test_current_grant_complete_input_group_global_allocation_and_no_tx(self):
        self.session.open()
        a, b = self.prepare(7, 'CANFD'), self.prepare(10)
        self.assertEqual((a.message['header']['sequence'], b.message['header']['sequence']), (2, 3))
        self.assertEqual(a.message['header']['session_id'], self.session.session_id)
        self.assertGreater(b.message['header']['transaction_id'], a.message['header']['transaction_id'])
        assembler = Reassembler(self.contract)
        result = None
        wire = WireCodec(self.contract)
        for frame in a.frames:
            result = assembler.push(wire.decode(frame, 'CANFD'), channel='CANFD_0', direction='TO_36', authorized=True, now_ns=0) or result
        self.assertEqual(result.message, a.message)
        self.assertEqual(len(self.peer.requests), 1)
        self.assertFalse(a.execution_ready)
        self.assertIs(self.session.verify_input(a), a)
        with self.assertRaises(FrozenInstanceError):
            a.message_json = b'changed'
        a.message['payload'].clear()
        self.assertTrue(a.message['payload'])

    def test_typed_message_id_is_not_normalized_into_a_valid_integer(self):
        self.session.open()
        self.assertTrue(callable(getattr(self.session,'prepare_input',None)))
        builder=self.builder()
        token=self.token('ETHGEN')
        for mid in (7.0,True):
            stimulus={'message_id':mid,'payload':message(7)['payload']}
            self.rejects('SCHEMA',lambda:self.session.prepare_input(stimulus,'UDP',target_step=100))
            self.rejects('SCHEMA',lambda:builder.prepare(token,stimulus,self.binding('ETHGEN'),target_step=100))
        self.assertEqual(self.prepare().message['header']['sequence'],2)

    def test_packed_signed_zero_survives_source_snapshot_and_original_can_udp_builders(self):
        self.session.open()
        self.assertTrue(callable(getattr(self.session,'prepare_input',None)))
        stimulus={'message_id':7,'payload':message(7)['payload']}
        stimulus['payload']['motor_command'][0]=-0.0
        item=self.session.prepare_input(stimulus,'CANFD',target_step=100)
        self.assertEqual(math.copysign(1,item.message['payload']['motor_command'][0]),-1)
        self.assertEqual(item.frames,tuple(WireCodec(self.contract).encode(item.message,'CANFD')))
        builder=self.builder()
        for branch in ('CANT','ETHGEN'):
            plan=builder.prepare(self.token(branch),stimulus,self.binding(branch),target_step=100)
            self.assertEqual(math.copysign(1,plan.source_input.message['payload']['motor_command'][0]),-1)
            self.assertEqual(plan.source_input.frames,tuple(WireCodec(self.contract).encode(plan.source_input.message,plan.source_input.transport)))

    def test_missing_expired_role_capability_and_invalid_input_do_not_consume_sequence(self):
        self.rejects('STALE_SESSION', self.prepare)
        self.session.open()
        self.rejects('TARGET_MISSING', lambda: self.prepare(17))
        self.rejects('UNSUPPORTED', lambda: self.prepare(34, 'CANFD'))
        self.rejects('SCHEMA', lambda: self.session.prepare_input({'message_id':7,'payload':{}}, 'UDP', target_step=100))
        self.rejects('STATE', lambda: self.prepare(1))
        self.rejects('AUTHORIZATION', lambda: self.prepare(130))
        a = self.prepare()
        self.assertEqual(a.message['header']['sequence'], 2)
        self.clock.value += 1_000_000_000
        self.rejects('STALE_SESSION', lambda: self.session.verify_input(a))
        self.rejects('STALE_SESSION', self.prepare)

    def test_shared_bounded_evidence_pool_drain_and_discard_never_roll_back(self):
        peer = test_source_session.UnitPeer(self.contract, self.clock)
        session = SourceSession(peer, message(1)['payload']['identity'], ('CONTROLLER',), clock=self.clock, max_records=1)
        self.assertTrue(callable(getattr(session, 'prepare_input', None)), 'bounded input preparation missing')
        session.open()
        stimulus = {'message_id':7, 'payload':message(7)['payload']}
        self.rejects('BUFFER_FULL', lambda: session.prepare_input(stimulus,'UDP',target_step=100))
        session.drain_records()
        a = session.prepare_input(stimulus,'UDP',target_step=100)
        self.assertEqual(a.message['header']['sequence'],2)
        self.assertEqual(session.drain_records(), ())
        self.assertEqual(session.prepared_inputs, (a,))
        self.rejects('BUFFER_FULL', lambda: session.prepare_input(stimulus,'UDP',target_step=100))
        self.rejects('BUFFER_FULL', lambda: session.request(stimulus,target_step=100))
        session.discard_input(a)
        b = session.prepare_input(stimulus,'UDP',target_step=100)
        self.assertEqual(b.message['header']['sequence'],3)
        self.assertEqual(session.prepared_inputs,(b,))

    def test_forged_foreign_discarded_and_abandoned_inputs_are_not_live(self):
        self.session.open()
        a = self.prepare()
        self.rejects('STATE', lambda: self.session.verify_input(replace(a)))
        peer = test_source_session.UnitPeer(self.contract,self.clock)
        other = SourceSession(peer,message(1)['payload']['identity'],('CONTROLLER',),clock=self.clock)
        self.rejects('STATE', lambda: other.verify_input(a))
        self.session.discard_input(a)
        self.rejects('STATE', lambda: self.session.verify_input(a))
        b = self.prepare()
        self.session.abandon()
        self.assertEqual(self.session.prepared_inputs,())
        self.rejects('STATE', lambda: self.session.verify_input(b))
        self.assertEqual(len(self.peer.requests),1)

    def test_malformed_objects_and_forged_bytes_fail_explicitly_before_allocation(self):
        self.session.open()
        self.assertTrue(callable(getattr(self.session,'prepare_input',None)))
        for bad in (None, 1, [], 'input'):
            self.rejects('SCHEMA',lambda:self.session.prepare_input(bad,'UDP',target_step=100))
        item=self.prepare()
        self.rejects('STATE',lambda:self.session.verify_input(replace(item,message_json=b'not-json')))
        self.rejects('STATE',lambda:self.session.discard_input(replace(item,message_json=b'not-json')))
        self.assertEqual(item.message['header']['sequence'],2)
        builder=self.builder()
        token=self.token('ETHGEN')
        for bad in (None,1,[],'input'):
            self.rejects('SCHEMA',lambda:builder.prepare(token,bad,self.binding('ETHGEN'),target_step=100))
        self.assertEqual(self.prepare().message['header']['sequence'],3)

    def test_source_prepare_respects_exclusive_owner_and_counter_exhaustion(self):
        self.session.open()
        self.session._dispatcher = object()
        self.rejects('STATE', self.prepare)
        self.session._dispatcher = None
        self.session._next_sequence = 0xffffffff
        a = self.prepare()
        self.assertEqual(a.message['header']['sequence'],0xffffffff)
        self.assertIs(self.session.verify_input(a),a)
        self.rejects('CAPACITY', self.prepare)

    def test_cantools_python_can_complete_group_is_original_bytes_not_mutable_snapshot(self):
        self.session.open()
        builder = self.builder()
        token = self.token('CANT')
        plan = builder.prepare(token, {'message_id':7,'payload':message(7)['payload']}, self.binding('CANT'), target_step=100)
        actual = builder.python_can_messages(plan)
        self.assertEqual(len(actual),len(plan.source_input.frames))
        for obj, frame in zip(actual,plan.source_input.frames):
            self.assertEqual(bytes(obj.data),frame.data)
            self.assertEqual(obj.arbitration_id,frame.arbitration_id)
            self.assertTrue(obj.is_fd and obj.bitrate_switch)
            self.assertFalse(obj.is_extended_id or obj.is_remote_frame or obj.is_error_frame or obj.is_rx)
            self.assertEqual(obj.dlc,64)
            self.assertEqual(obj.channel,'can0')
        actual[0].data[0] ^= 1
        self.assertEqual(bytes(builder.python_can_messages(plan)[0].data),plan.source_input.frames[0].data)
        self.assertFalse(plan.authorized_to_transmit)
        self.rejects('STATE',plan.require_execution_ready)

    def test_cansend_literal_complete_group_has_no_frontend_options(self):
        self.session.open()
        builder = self.builder()
        plan = builder.prepare(self.token('CUTIL'), {'message_id':10,'payload':message(10)['payload']}, self.binding('CUTIL'), target_step=100)
        self.assertEqual(len(plan.commands),len(plan.source_input.frames))
        for command, frame in zip(plan.commands,plan.source_input.frames):
            self.assertEqual(command.argv, ('cansend','can0',f'{frame.arbitration_id:03X}##1{frame.data.hex().upper()}'))
        self.assertFalse(plan.execution_ready)
        self.assertEqual(len(self.peer.requests),1)

    def test_scapy_complete_ethernet_uses_current_transport_endpoints_and_original_wire(self):
        self.session.open()
        builder = self.builder()
        plan = builder.prepare(self.token('ETHGEN'), {'message_id':7,'payload':message(7)['payload']}, self.binding('ETHGEN'), target_step=100)
        for raw, wire in zip(plan.ethernet_frames, plan.source_input.frames):
            ether = Ether(raw)
            self.assertEqual((ether.src,ether.dst),(self.binding('ETHGEN').source_mac,self.binding('ETHGEN').destination_mac))
            self.assertEqual((ether[IP].src,ether[UDP].sport),self.peer.source_endpoint)
            self.assertEqual((ether[IP].dst,ether[UDP].dport),self.peer.receiver_endpoint)
            self.assertEqual(bytes(ether[UDP].payload),wire)
            self.assertIsNotNone(ether[IP].chksum)
            self.assertIsNotNone(ether[UDP].chksum)
        self.assertFalse(plan.execution_ready)

    def test_preflight_bad_binding_protocol_and_mac_preserve_global_counter(self):
        self.session.open()
        builder = self.builder()
        token = self.token('CANT')
        stimulus = {'message_id':7,'payload':message(7)['payload']}
        for b in (ExportBinding('ETH_0','can0'), ExportBinding('CANFD_0','can1')):
            self.rejects('SCHEMA', lambda: builder.prepare(token,stimulus,b,target_step=100))
        self.builder()
        from input_simulator.live_tool_input import LiveToolInputBuilder
        unparsed = LiveToolInputBuilder(self.book,self.session,protocol=ProtocolParser(self.contract))
        self.rejects('STATE', lambda: unparsed.prepare(token,stimulus,self.binding('CANT'),target_step=100))
        et = self.token('ETHGEN')
        for mac in ('00:00:00:00:00:00','ff:ff:ff:ff:ff:ff','bad',None):
            self.rejects('SCHEMA', lambda: builder.prepare(et,stimulus,ExportBinding('ETH_0','eth0',mac,'02:00:00:00:00:02'),target_step=100))
        self.assertEqual(self.prepare().message['header']['sequence'],2)

    def test_plan_validation_links_actual_reservation_source_and_discard(self):
        self.session.open()
        builder = self.builder()
        token = self.token('ETHGEN')
        plan = builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},self.binding('ETHGEN'),target_step=100)
        self.assertIs(builder.validate(plan),plan)
        self.rejects('STATE',lambda:builder.validate(replace(plan)))
        self.rejects('STATE',lambda:self.builder().validate(plan))
        builder.discard(plan)
        self.assertEqual(self.session.prepared_inputs,())
        self.assertEqual(self.book.reservations,(token,))
        self.rejects('STATE',lambda:builder.validate(plan))
        second=builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},self.binding('ETHGEN'),target_step=100)
        self.assertEqual(second.source_input.message['header']['sequence'],3)
        self.book.release(token)
        self.rejects('STATE',lambda:builder.validate(second))
        builder.discard(second)

    def test_builder_capacity_never_evicts_or_consumes_failed_sequence(self):
        self.session.open()
        builder = self.builder(capacity=1)
        token = self.token('ETHGEN')
        stimulus = {'message_id':7,'payload':message(7)['payload']}
        plan=builder.prepare(token,stimulus,self.binding('ETHGEN'),target_step=100)
        self.rejects('BUFFER_FULL',lambda:builder.prepare(token,stimulus,self.binding('ETHGEN'),target_step=100))
        self.assertEqual(self.session.prepared_inputs,(plan.source_input,))
        self.assertEqual(self.prepare().message['header']['sequence'],3)

    def test_byte_limits_preflight_before_counter_and_never_clear_existing(self):
        self.session.open()
        builder=self.builder(max_bytes=1)
        token=self.token('ETHGEN')
        self.rejects('BUFFER_FULL',lambda:builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},self.binding('ETHGEN'),target_step=100))
        self.session._max_record_bytes=1
        self.rejects('BUFFER_FULL',self.prepare)
        self.session._max_record_bytes=4*1024*1024
        self.assertEqual(self.prepare().message['header']['sequence'],2)

    def test_lack_of_role_wrong_model_or_other_ethernet_channel_never_allocates(self):
        peer=test_source_session.UnitPeer(self.contract,self.clock)
        session=SourceSession(peer,message(1)['payload']['identity'],('STIMULUS',),clock=self.clock)
        session.open()
        self.assertTrue(callable(getattr(session,'prepare_input',None)))
        self.rejects('AUTHORIZATION',lambda:session.prepare_input({'message_id':7,'payload':message(7)['payload']},'CANFD',target_step=100))
        self.rejects('MODEL',lambda:session.prepare_input({'message_id':8,'payload':message(8)['payload']},'CANFD',target_step=100))
        self.assertEqual(session.prepare_input({'message_id':10,'payload':message(10)['payload']},'CANFD',target_step=100).message['header']['sequence'],2)
        self.session.open()
        builder=self.builder()
        token=self.token('ETHGEN')
        self.rejects('AUTHORIZATION',lambda:builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},
            replace(self.binding('ETHGEN'),channel_id='ETH_1'),target_step=100))
        self.assertEqual(self.prepare().message['header']['sequence'],2)

    def test_observer_unknown_original_branch_and_invalid_limits_are_rejected(self):
        self.session.open()
        builder=self.builder()
        for branch,mode in (('CANT','OBSERVE'),('SAVVY','SEND'),('CANREPLAY','SEND'),('ETHREPLAY','SEND')):
            token=self.book.reserve(branch,branch,('can0',),mode=mode)
            self.rejects('AUTHORIZATION',lambda:builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},ExportBinding('CANFD_0','can0'),target_step=100))
            self.book.release(token)
        for kw in ({'capacity':True},{'capacity':0},{'capacity':65},{'max_bytes':True},{'max_bytes':0}):
            self.rejects('CAPACITY',lambda:self.builder(**kw))
        self.assertEqual(self.prepare().message['header']['sequence'],2)

    def test_post_allocation_tool_error_or_revoke_preserves_original_input_no_rollback(self):
        self.session.open()
        builder=self.builder()
        token=self.token('ETHGEN')
        original=builder._materialize
        calls=[]
        def failure(*args):
            calls.append(1)
            if len(calls)==2:
                raise ICDError('RESOURCE','injected original tool post-allocation failure')
            return original(*args)
        with patch.object(builder,'_materialize',side_effect=failure):
            self.rejects('RESOURCE',lambda:builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},self.binding('ETHGEN'),target_step=100))
        self.assertEqual(self.session.prepared_inputs[0].message['header']['sequence'],2)
        self.assertEqual(len(self.peer.requests),1)
        calls.clear()
        def revoked(*args):
            calls.append(1)
            if len(calls)==2:
                self.book.release(token)
            return original(*args)
        with patch.object(builder,'_materialize',side_effect=revoked):
            self.rejects('STATE',lambda:builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},self.binding('ETHGEN'),target_step=100))
        self.assertEqual([i.message['header']['sequence'] for i in self.session.prepared_inputs],[2,3])
        self.assertEqual(self.prepare().message['header']['sequence'],4)

    def test_failed_preparation_budget_identity_and_revoked_local_recovery(self):
        from input_simulator.live_tool_input import ToolPreparationError
        self.session.open()
        builder = self.builder(capacity=1)
        token = self.token('CANT')
        original = builder._materialize
        calls = 0
        def failure(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.book.release(token)
                raise ICDError('RESOURCE', 'post-allocation failure after revoke')
            return original(*args)
        stimulus = {'message_id': 7, 'payload': message(7)['payload']}
        with patch.object(builder, '_materialize', side_effect=failure):
            with self.assertRaises(ToolPreparationError) as caught:
                builder.prepare(token, stimulus, self.binding('CANT'), target_step=100)
        context = caught.exception.failure
        self.assertIs(builder.failed_preparations[0], context)
        self.assertIs(self.session.prepared_inputs[0], context.source_input)
        retained_bytes = builder._bytes
        self.assertGreater(retained_bytes, 0)
        token = self.token('CANT')
        self.rejects('BUFFER_FULL', lambda: builder.prepare(token, stimulus, self.binding('CANT'), target_step=100))
        self.assertEqual(self.session._next_sequence, 3)
        self.rejects('STATE', lambda: builder.discard_failed(replace(context)))
        self.assertEqual(builder._bytes, retained_bytes)
        builder.discard_failed(context)
        self.assertEqual((builder.failed_preparations, self.session.prepared_inputs, builder._bytes), ((), (), 0))
        self.rejects('STATE', lambda: builder.discard_failed(context))
        plan = builder.prepare(token, stimulus, self.binding('CANT'), target_step=100)
        self.assertEqual(plan.source_input.message['header']['sequence'], 3)

    def test_lease_expiry_during_encoding_rejects_without_consuming_sequence(self):
        self.session.open()
        self.assertTrue(callable(getattr(self.session,'prepare_input',None)))
        original=WireCodec.encode
        def late(codec,*args):
            result=original(codec,*args)
            self.clock.value+=1_000_000_000
            return result
        with patch.object(WireCodec,'encode',late):
            self.rejects('STALE_SESSION',self.prepare)
        self.assertEqual(self.session.prepared_inputs,())
        self.assertEqual(self.session._next_sequence,2)

    def test_expired_plan_cannot_validate_but_can_discard_without_releasing_channel(self):
        self.session.open()
        builder=self.builder()
        token=self.token('ETHGEN')
        plan=builder.prepare(token,{'message_id':7,'payload':message(7)['payload']},self.binding('ETHGEN'),target_step=100)
        self.clock.value+=1_000_000_000
        self.rejects('STALE_SESSION',lambda:builder.validate(plan))
        builder.discard(plan)
        self.assertEqual(self.book.reservations,(token,))
        self.assertEqual(self.session.prepared_inputs,())

    def test_all_11_can_inputs_and_44_grantable_udp_inputs_use_complete_original_groups(self):
        self.builder()
        from input_simulator.live_tool_input import LiveToolInputBuilder
        can_count=udp_count=0
        for mid,entry in self.contract.messages.items():
            if mid==1 or entry['direction']!='TO_36':
                continue
            clock=test_source_session.LocalClock()
            peer=test_source_session.UnitPeer(self.contract,clock)
            peer.source_endpoint,peer.receiver_endpoint=self.peer.source_endpoint,self.peer.receiver_endpoint
            def grant(response):
                response['payload']['capabilities']['implemented_message_ids']=list(self.contract.messages)
                return response
            peer.modify=grant
            identity=message(1)['payload']['identity']
            identity['model_id']=entry['model_ids'][0]
            session=SourceSession(peer,identity,('STIMULUS','CONTROLLER','OBSERVER'),clock=clock)
            session.open()
            book=ChannelReservations()
            builder=LiveToolInputBuilder(book,session,protocol=self.protocol)
            stimulus={'message_id':mid,'payload':message(mid)['payload']}
            et=book.reserve('eth','ETHGEN',('eth0',),mode='SEND')
            plan=builder.prepare(et,stimulus,self.binding('ETHGEN'),target_step=100)
            raw=pcap([(1,i,f) for i,f in enumerate(plan.ethernet_frames)],nano=True)
            parsed=CaptureParser().parse(raw,'PCAP')
            self.assertEqual(tuple(p.payload for p in parsed.packets),plan.source_input.frames)
            self.assertTrue(all(p.transport_checksum_verified for p in parsed.packets))
            udp_count+=1
            if 'CANFD' in entry['transports']:
                ct=book.reserve('can','CANT',('can0',),mode='SEND')
                cp=builder.prepare(ct,stimulus,self.binding('CANT'),target_step=100)
                self.assertEqual(tuple(bytes(m.data) for m in builder.python_can_messages(cp)),tuple(f.data for f in cp.source_input.frames))
                self.assertGreater(cp.source_input.message['header']['sequence'],plan.source_input.message['header']['sequence'])
                can_count+=1
        self.assertEqual((can_count,udp_count),(11,44))


class ActualInputTests(test_resource_udp.ResourceUDPTests):
    def test_actual_standard_grant_prepares_published_resource_without_tool_tx_claim(self):
        self.assertTrue(callable(getattr(SourceSession,'prepare_input',None)), 'real grant input preparation missing')
        self.network()
        test_source_session.ActualSourceSessionTests.poll_gateway(self)
        session=SourceSession(self.source,message(1)['payload']['identity'],('STIMULUS',))
        session.open()
        self.assertEqual(session.capabilities['implemented_message_ids'],[1,34])
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.live_tool_input'))
        from input_simulator.live_tool_input import LiveToolInputBuilder
        book=ChannelReservations()
        token=book.reserve('actual','ETHGEN',('eth0',),mode='SEND')
        builder=LiveToolInputBuilder(book,session)
        resource=chunk(b'actual-video-byte-resource-not-model',kind='VIDEO')
        before=self.receiver.admitted_count
        plan=builder.prepare(token,{'message_id':34,'payload':resource['payload']},
            ExportBinding('ETH_0','eth0','02:00:00:00:00:01','02:00:00:00:00:02'),target_step=0)
        self.assertEqual(plan.source_input.message['header']['session_id'],session.session_id)
        self.assertIn(session.session_id,self.registry.session_ids)
        self.assertEqual(self.receiver.admitted_count,before)
        self.assertEqual((Ether(plan.ethernet_frames[0])[IP].src,Ether(plan.ethernet_frames[0])[UDP].sport),self.source.source_endpoint)
        self.assertFalse(plan.authorized_to_transmit)
        self.assertFalse(session.capabilities['replacement_ready'])
        self.assertEqual(session.capabilities['available_probes'],[])


for _name in list(test_resource_udp.ResourceUDPTests.__dict__):
    if _name.startswith('test_'):
        setattr(ActualInputTests,_name,None)


if __name__ == '__main__':
    unittest.main()
