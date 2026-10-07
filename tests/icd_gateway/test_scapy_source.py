import copy
import importlib
import socket
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether
from scapy.supersocket import SimpleSocket

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from icd_runtime.reassembly import Reassembler
from input_simulator.tools import ChannelReservations
from input_simulator.replay_export import ExportBinding
from input_simulator.session import SourceSession
from input_simulator.dispatch import UDPDispatcher
from test_source_session import LocalClock


class ScapySourceTests(GatewayTest):
    """Real Scapy socket and local frame sink only, not a hardware backend."""
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.scapy_source'), 'original Scapy sender missing')
        self.module = importlib.import_module('input_simulator.scapy_source')
        self.book = ChannelReservations()
        self.binding = ExportBinding('ETH_0', 'eth0', '02:00:00:00:00:01', '02:00:00:00:00:02')
        self.token = self.book.reserve('scapy-test', 'ETHGEN', ('eth0',), mode='SEND')
        left, self.sink = socket.socketpair()
        self.l2 = SimpleSocket(left, Ether)
        self.sink.settimeout(1)
        self.addCleanup(self.sink.close)
        self.addCleanup(self.l2.close)
        self.receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receiver.bind(('127.0.0.1', 0))
        self.addCleanup(self.receiver.close)
        self.clock = LocalClock()

    def source(self, **kwargs):
        source = self.module.ScapySource(self.contract, source_bind=('127.0.0.1', 0),
             feedback_bind=('127.0.0.1', 0), receiver_endpoint=self.receiver.getsockname(),
             binding=self.binding, reservations=self.book, reservation=self.token, l2socket=self.l2, **kwargs)
        self.addCleanup(source.close)
        return source

    def receive_frame(self):
        def read(n):
            data = b''
            while len(data) < n:
                block = self.sink.recv(n-len(data))
                if not block:
                    raise RuntimeError('actual frame sink closed early')
                data += block
            return data
        head = read(34)
        return Ether(head + read(int.from_bytes(head[16:18], 'big') - 20))

    def live(self, *, implemented=None, **kwargs):
        self.src = self.source(**kwargs)
        self.session = SourceSession(self.src, message(1)['payload']['identity'],
                                    ('STIMULUS','CONTROLLER','OBSERVER'), clock=self.clock)
        errors = []
        def opening():
            try:
                self.session.open()
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=opening)
        thread.start()
        frame = self.receive_frame()
        raw = bytes(frame[UDP].payload)
        fragment = self.src.wire.decode(raw, 'UDP', direction='TO_36')
        assembler = Reassembler(self.contract)
        request = assembler.push(fragment, channel='ETH_0', direction='TO_36', authorized=True, now_ns=0).message
        reply = message(129)
        reply['header'].update(session_id=73, sequence=1, transaction_id=request['header']['transaction_id'])
        reply['payload'].update(session_id=73, accepted_roles=request['payload']['roles'])
        reply['payload']['capabilities']['implemented_message_ids'] = [1,2,7,33,34] if implemented is None else list(implemented)
        for packet in self.src.wire.encode(reply, 'UDP'):
            self.receiver.sendto(packet, self.src.feedback_endpoint)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.reply_sequence = 1
        return self.src

    def request(self, mid=7):
        item = self.session.prepare_input({'message_id': mid, 'payload': message(mid)['payload']}, 'UDP', target_step=100)
        return item.message

    def test_actual_scapy_complete_frame_and_standard_grant_no_udp_fallback(self):
        src = self.live()
        value = self.request()
        self.assertEqual(src.send(value, owner=self.session), 1)
        frame = self.receive_frame()
        self.assertEqual((frame.src,frame.dst), (self.binding.source_mac,self.binding.destination_mac))
        self.assertEqual((frame[IP].src,frame[IP].dst), ('127.0.0.1','127.0.0.1'))
        self.assertEqual((frame[UDP].sport,frame[UDP].dport), (src.source_endpoint[1],self.receiver.getsockname()[1]))
        self.assertEqual(bytes(frame[UDP].payload), src.wire.encode(value,'UDP')[0])
        self.receiver.settimeout(0)
        self.assertRaises(BlockingIOError, self.receiver.recvfrom, 1500)
        self.assertEqual(src.l2_records[-1].ethernet_data, bytes(frame))
        self.assertEqual(src.l2_records[-1].sent_bytes, len(bytes(frame)))
        self.assertEqual(src.l2_records[-1].qualification_status, 'NOT_EVALUATED')
        self.assertFalse(src.execution_ready)

    def test_cooperative_original_dispatcher_uses_scapy_and_matching_feedback(self):
        src = self.live()
        dispatch = UDPDispatcher(self.session)
        self.addCleanup(dispatch.close)
        header = dispatch.submit({'message_id':7,'payload':message(7)['payload']},target_step=100)
        dispatch.poll()
        frame = self.receive_frame()
        self.assertEqual(src.wire.decode(bytes(frame[UDP].payload),'UDP').header, header)
        reply = message(130)
        reply['header'].update(session_id=73,sequence=2,transaction_id=header.transaction_id)
        reply['payload'].update(request_sequence=header.sequence,request_message_id=7,stage='FAILED',error='TARGET_MISSING')
        for packet in src.wire.encode(reply,'UDP'):
            self.receiver.sendto(packet,src.feedback_endpoint)
        dispatch.poll()
        self.assertEqual(dispatch.pending_count,0)
        self.assertEqual([r.error for r in dispatch.records if r.kind=='FAILED'],['TARGET_MISSING'])
        self.assertTrue(any(r.kind=='TX' for r in dispatch.records))

    def test_missing_original_l2_backend_never_falls_back(self):
        with patch.object(self.module.conf,'L2socket',None):
            self.rejects('TARGET_MISSING',lambda:self.module.ScapySource(self.contract,
                source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),receiver_endpoint=self.receiver.getsockname(),
                binding=self.binding,reservations=self.book,reservation=self.token))

    def test_source_rejects_foreign_reservation_branch_mapping_and_bad_mac(self):
        from dataclasses import replace
        self.rejects('STATE',lambda:self.module.ScapySource(self.contract,source_bind=('127.0.0.1',0),
            feedback_bind=('127.0.0.1',0),receiver_endpoint=self.receiver.getsockname(),binding=self.binding,
            reservations=self.book,reservation=replace(self.token),l2socket=self.l2))
        for binding in (ExportBinding('CANFD_0','eth0'), ExportBinding('ETH_0','eth1',self.binding.source_mac,self.binding.destination_mac),
                        ExportBinding('ETH_0','eth0','00:00:00:00:00:00',self.binding.destination_mac),
                        ExportBinding('ETH_0','eth0','ff:ff:ff:ff:ff:ff',self.binding.destination_mac)):
            self.rejects('SCHEMA',lambda:self.module.ScapySource(self.contract,source_bind=('127.0.0.1',0),
                feedback_bind=('127.0.0.1',0),receiver_endpoint=self.receiver.getsockname(),binding=binding,
                reservations=self.book,reservation=self.token,l2socket=self.l2))

    def test_no_live_standard_grant_cannot_send_regular_input(self):
        src = self.source()
        self.rejects('AUTHORIZATION',lambda:src.send(message(7)))
        self.assertEqual(src.l2_records,())

    def test_short_write_is_recorded_not_success_and_no_retry_fallback(self):
        src = self.live()
        value = self.request()
        with patch.object(self.l2,'send',return_value=3) as sender:
            self.rejects('RESOURCE',lambda:src.send(value,owner=self.session))
        self.assertEqual(sender.call_count,1)
        record=src.l2_records[-1]
        self.assertEqual((record.sent_bytes,record.error),(3,'RESOURCE'))
        self.assertEqual(record.udp_data,src.wire.encode(value,'UDP')[0])

    def test_socket_error_retains_complete_attempt_and_dispatch_failure(self):
        src = self.live()
        value=self.request()
        with patch.object(self.l2,'send',side_effect=OSError('actual injected send failure')):
            self.rejects('RESOURCE',lambda:src.send(value,owner=self.session))
        record=src.l2_records[-1]
        self.assertIsNone(record.sent_bytes)
        self.assertEqual(record.error,'RESOURCE')
        self.assertEqual(bytes(Ether(record.ethernet_data)[UDP].payload),record.udp_data)

    def test_expired_grant_rejected_before_send(self):
        src=self.live()
        value=self.request()
        self.clock.value+=1_000_000_000
        count=len(src.l2_records)
        self.rejects('STALE_SESSION',lambda:src.send(value,owner=self.session))
        self.assertEqual(len(src.l2_records),count)

    def test_released_local_token_cannot_transmit_and_is_not_automatically_reacquired(self):
        src=self.live()
        value=self.request()
        self.book.release(self.token)
        self.rejects('STATE',lambda:src.send(value,owner=self.session))
        self.assertEqual(len(src.l2_records),1)

    def test_bounded_l2_records_fail_before_send_and_keep_original_prefix(self):
        src=self.live(max_l2_records=1)
        value=self.request()
        self.rejects('BUFFER_FULL',lambda:src.send(value,owner=self.session))
        self.assertEqual(len(src.l2_records),1)
        old=src.l2_records
        self.assertEqual(src.drain_l2_records(),old)
        self.assertEqual(src.send(value,owner=self.session),1)
        self.receive_frame()

    def test_close_retains_records_reservation_and_does_not_report_remote_cleanup(self):
        src=self.live()
        original=src.l2_records
        src.close()
        self.assertTrue(self.l2.closed)
        self.assertEqual(src.l2_records,original)
        self.assertIs(self.book.validate(self.token),self.token)
        self.assertFalse(src.safety_verified)
        src.close()

    def test_direct_send_and_close_cannot_bypass_session_operation(self):
        src=self.live()
        value=self.request()
        with self.session._operation():
            result=[]
            def other_thread():
                for operation in (lambda:src.send(value,owner=self.session),src.close):
                    try: operation()
                    except ICDError as error: result.append(error.code)
                    else: result.append('ACCEPTED')
            thread=threading.Thread(target=other_thread)
            thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result,['STATE','STATE'])
        self.assertFalse(self.l2.closed)
        self.assertEqual(len(src.l2_records),1)

    def test_direct_send_and_close_cannot_bypass_attached_dispatcher(self):
        src=self.live()
        value=self.request()
        dispatcher=UDPDispatcher(self.session)
        self.addCleanup(dispatcher.close)
        self.rejects('STATE',lambda:src.send(value,owner=self.session))
        self.rejects('STATE',src.close)
        self.assertFalse(self.l2.closed)

    def test_explicit_transaction_gap_and_header_mutation_are_not_allocations(self):
        src=self.live()
        value=self.request()
        self.session.allocate_header(7,100,transaction_id=100)
        value['header']['transaction_id']=50
        self.rejects('STATE',lambda:src.send(value,owner=self.session))
        self.assertEqual(len(src.l2_records),1)

    def test_post_send_expiry_keeps_actual_transmitted_bytes_and_failure(self):
        src=self.live()
        value=self.request()
        actual=self.l2.send
        def delayed(frame):
            result=actual(frame)
            self.clock.value+=1_000_000_000
            return result
        with patch.object(self.l2,'send',delayed):
            self.rejects('STALE_SESSION',lambda:src.send(value,owner=self.session))
        frame=self.receive_frame()
        self.assertEqual(src.l2_records[-1].ethernet_data,bytes(frame))
        self.assertEqual(src.l2_records[-1].sent_bytes,len(bytes(frame)))
        self.assertEqual(src.l2_records[-1].error,'STALE_SESSION')

    def test_role_and_capability_and_sid_are_checked_at_actual_tx(self):
        src=self.live()
        value=self.request()
        roles=self.session._roles
        self.session._roles=('STIMULUS',)
        self.rejects('AUTHORIZATION',lambda:src.send(value,owner=self.session))
        self.session._roles=roles
        from icd_runtime.json_codec import canonicalize
        caps=self.session.capabilities
        caps['implemented_message_ids']=[1,2]
        self.session._capabilities_json=canonicalize(caps)
        self.rejects('TARGET_MISSING',lambda:src.send(value,owner=self.session))
        value['header']['session_id']=74
        self.rejects('STALE_SESSION',lambda:src.send(value,owner=self.session))
        self.assertEqual(len(src.l2_records),1)

    def test_bounded_bytes_fail_before_actual_call_and_limits_are_strict(self):
        src=self.live()
        value=self.request()
        src._max_l2_bytes=src._l2_bytes
        with patch.object(self.l2,'send') as sender:
            self.rejects('BUFFER_FULL',lambda:src.send(value,owner=self.session))
        sender.assert_not_called()
        for key in ('max_l2_records','max_l2_bytes'):
            for invalid in (True,0,-1,1.5):
                self.rejects('CAPACITY',lambda:self.source(**{key:invalid}))

    def test_invalid_backend_return_is_not_success(self):
        src=self.live()
        value=self.request()
        for result in (True,None,-1,10**9):
            with patch.object(self.l2,'send',return_value=result):
                self.rejects('RESOURCE',lambda:src.send(value,owner=self.session))
            self.assertIsNone(src.l2_records[-1].sent_bytes)
            self.assertEqual(src.l2_records[-1].error,'RESOURCE')

    def test_actual_record_is_immutable_and_drain_cannot_overlap_tx(self):
        src=self.live()
        old=src.l2_records
        with self.assertRaises(FrozenInstanceError):
            old[0].sent_bytes=0
        self.assertTrue(src._l2_lock.acquire(blocking=False))
        try:
            self.rejects('STATE',src.drain_l2_records)
        finally:
            src._l2_lock.release()
        self.assertEqual(src.drain_l2_records(),old)
        self.assertEqual(src.l2_records,())

    def test_close_failure_retries_same_original_pcap_handle(self):
        from scapy.arch.libpcap import _L2libpcapSocket
        class FD:
            calls=0
            def close(self):
                self.calls+=1
                if self.calls==1: raise OSError('first actual handle close failure')
        raw=_L2libpcapSocket.__new__(_L2libpcapSocket)
        raw.closed=False
        raw.pcap_fd=FD()
        src=self.module.ScapySource(self.contract,source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),
            receiver_endpoint=self.receiver.getsockname(),binding=self.binding,reservations=self.book,
            reservation=self.token,l2socket=raw)
        self.addCleanup(src.close)
        self.rejects('RESOURCE',src.close)
        src.close()
        self.assertEqual(raw.pcap_fd.calls,2)
        self.assertFalse(src.execution_ready)

    def test_constructor_backend_failure_closes_both_udp_sockets(self):
        actual=socket.socket
        opened=[]
        def tracked(*args,**kwargs):
            value=actual(*args,**kwargs)
            opened.append(value)
            return value
        with patch('input_simulator.udp_source.socket.socket',tracked),patch.object(self.module.conf,'L2socket',side_effect=OSError('no raw backend')):
            self.rejects('TARGET_MISSING',lambda:self.module.ScapySource(self.contract,
                source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),receiver_endpoint=self.receiver.getsockname(),
                binding=self.binding,reservations=self.book,reservation=self.token))
        self.assertEqual(len(opened),2)
        self.assertEqual([s.fileno() for s in opened],[-1,-1])

    def test_successful_original_pcap_close_is_not_repeated(self):
        from scapy.arch.libpcap import _L2libpcapSocket
        class FD:
            calls=0
            def close(self): self.calls+=1
        raw=_L2libpcapSocket.__new__(_L2libpcapSocket)
        raw.closed=False
        raw.pcap_fd=FD()
        src=self.module.ScapySource(self.contract,source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),
            receiver_endpoint=self.receiver.getsockname(),binding=self.binding,reservations=self.book,
            reservation=self.token,l2socket=raw)
        self.addCleanup(src.close)
        src.close(); src.close()
        self.assertEqual(raw.pcap_fd.calls,1)

    def test_l2_record_drain_rejected_while_original_recorder_attached(self):
        from input_simulator.evidence_recorder import ObservationRecorder
        from pathlib import Path
        import tempfile
        src=self.live()
        dispatcher=UDPDispatcher(self.session)
        self.addCleanup(dispatcher.close)
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        recorder=ObservationRecorder(dispatcher,Path(temporary.name)/'scapy-recording',run_id='scapy-run')
        self.addCleanup(recorder.close)
        original=src.l2_records
        self.rejects('STATE',src.drain_l2_records)
        self.assertEqual(src.l2_records,original)

    def test_original_recorded_udp_dispatch_bytes_still_match_outer_frames(self):
        src=self.live()
        dispatcher=UDPDispatcher(self.session)
        self.addCleanup(dispatcher.close)
        inbox=dispatcher.enable_evidence_collection()
        header=dispatcher.submit({'message_id':7,'payload':message(7)['payload']},target_step=100)
        dispatcher.poll()
        frame=self.receive_frame()
        records=[row for row in dispatcher.records if row.kind=='TX']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0].wire_data,bytes(frame[UDP].payload))
        self.assertEqual(records[0].header,header)
        self.assertFalse(inbox.execution_ready)

    def test_all_four_formal_eth_mappings_keep_same_standard_contract(self):
        for index in range(4):
            with self.subTest(channel=f'ETH_{index}'):
                if index:
                    left,self.sink=socket.socketpair()
                    self.l2=SimpleSocket(left,Ether)
                    self.sink.settimeout(1)
                    self.addCleanup(self.sink.close)
                    self.addCleanup(self.l2.close)
                self.binding=ExportBinding(f'ETH_{index}','eth0',self.binding.source_mac,self.binding.destination_mac)
                src=self.live()
                self.assertEqual(src.channel,f'ETH_{index}')
                value=self.request()
                src.send(value,owner=self.session)
                self.assertEqual(bytes(self.receive_frame()[UDP].payload),src.wire.encode(value,'UDP')[0])
                src.close()

    def test_existing_prepared_bytes_remain_owned_after_later_allocation(self):
        src=self.live()
        value=self.request()
        self.session.allocate_header(7,100,transaction_id=100)
        src.send(value,owner=self.session)
        self.assertEqual(bytes(self.receive_frame()[UDP].payload),src.wire.encode(value,'UDP')[0])

    def test_signed_zero_remains_original_wire_bytes(self):
        import math
        src=self.live()
        stimulus={'message_id':7,'payload':message(7)['payload']}
        stimulus['payload']['motor_command'][0]=-0.0
        item=self.session.prepare_input(stimulus,'UDP',target_step=100)
        src.send(item.message,owner=self.session)
        packet=bytes(self.receive_frame()[UDP].payload)
        self.assertEqual(packet,item.frames[0])
        assembler=Reassembler(self.contract)
        decoded=assembler.push(src.wire.decode(packet,'UDP'),channel=src.channel,direction='TO_36',authorized=True,now_ns=0)
        self.assertEqual(math.copysign(1,decoded.message['payload']['motor_command'][0]),-1)

    def test_actual_scapy_resource_fragments_keep_original_no_burst_pacing(self):
        from test_resource_udp import chunk
        from icd_runtime.resource_budget import ResourceBudget
        src=self.live()
        clock=LocalClock()
        tokens=[]
        packets=[]
        for data in (b'a'*1000,b'b'*1000):
            item=self.session.prepare_input({'message_id':34,'payload':chunk(data)['payload']},'UDP',target_step=0)
            tokens.append(src.prepare_transmission(item.message,owner=self.session))
            packets.append(item.frames[0])
        with patch('input_simulator.udp_source.time.perf_counter_ns',clock):
            self.assertFalse(src.transmit_fragment(tokens[0],0,owner=self.session))
            self.assertFalse(src.transmit_fragment(tokens[1],0,owner=self.session))
            clock.value+=10_000_000
            self.assertTrue(src.transmit_fragment(tokens[0],0,owner=self.session))
            self.assertFalse(src.transmit_fragment(tokens[1],0,owner=self.session))
            duration=(ResourceBudget.wire_bits((packets[1],))*1_000_000_000+19_999_999)//20_000_000
            clock.value+=duration
            self.assertTrue(src.transmit_fragment(tokens[1],0,owner=self.session))
        self.assertEqual([bytes(self.receive_frame()[UDP].payload) for _ in range(2)],packets)
        self.assertEqual(src._resource_budget.bits_per_second,20_000_000)
        self.assertEqual(src._resource_group_ns,100_000_000)


if __name__=='__main__':
    unittest.main()
