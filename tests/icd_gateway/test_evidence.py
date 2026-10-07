import copy
import importlib.util
import socket
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from common import message
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
import test_dispatch


class EvidenceTests(test_dispatch.DispatcherTests):
    """Actual UDP protocol peer, never actual qualified C/model/probe evidence."""

    def emit(self, reply):
        if reply['message_id'] == 129:
            reply=copy.deepcopy(reply)
            reply['payload']['capabilities']['available_probes']=list(getattr(self,'grant_probes',()))
        super().emit(reply)

    def setup_inbox(self, *, probes=(), **limits):
        self.grant_probes=probes
        self.setup_peer()
        method = getattr(self.dispatch, 'enable_evidence_collection', None)
        self.assertTrue(callable(method), 'standard Evidence inbox missing')
        self.inbox = method(**limits)
        return self.inbox

    def watch(self, mid=7, **kwargs):
        header = self.dispatch.submit({'message_id':mid, 'payload':message(mid)['payload']}, target_step=100)
        self.dispatch.watch_evidence(header, event_id='send-01', trace_id='run-01',
                                     min_step=0, max_step=1100, **kwargs)
        return header

    def evidence(self, header, **changes):
        import hashlib
        request = {'message_id':7, 'header':dict((name,getattr(header,name)) for name in
                   ('session_id','sequence','target_step','transaction_id','valid_for_ms')),
                   'payload':message(7)['payload']}
        self.reply_sequence += 1
        reply = message(140)
        reply['header'].update(session_id=header.session_id,transaction_id=header.transaction_id,
                               sequence=self.reply_sequence)
        reply['payload'].update(event_id='send-01', trace_id='run-01',request_sequence=header.sequence,
                                message_id=7,stage='E1',model_step=100,probe_id='NO_PROBE',
                                payload_sha256=hashlib.sha256(self.source.wire.payload_codec.encode(7,request['payload'])).hexdigest(),
                                business_result='NOT_EVALUATED',error='OK')
        reply['payload'].update(changes)
        return reply

    def transmit(self):
        self.dispatch.poll()
        return self.collect()[1]

    def completed(self):
        return [r for r in self.inbox.records if r.kind == 'EVIDENCE']

    def test_inbox_exists_and_actual_evidence_is_observation_not_ack_or_model_success(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        reply=self.evidence(header)
        self.emit(reply)
        self.dispatch.poll()
        record=self.completed()[0]
        self.assertEqual(record.reply,reply)
        self.assertTrue(record.correlation_matched)
        self.assertEqual(record.qualification_status,'NOT_EVALUATED')
        self.assertFalse(self.inbox.execution_ready)
        self.assertEqual(self.dispatch.pending_count,1)
        self.assertEqual(self.session.last_rx_sequence,reply['header']['sequence'])
        self.assertTrue(any(r.kind=='DATAGRAM' and r.wire_data==self.source.wire.encode(reply,'UDP')[0]
                            for r in self.inbox.records))

    def test_standard_evidence_after_terminal_ack_is_still_collected_without_pending(self):
        self.setup_inbox()
        header=self.watch()
        request=self.transmit()[0]
        ack=self.response(request)
        self.dispatch.poll()
        self.assertEqual(self.dispatch.pending_count,0)
        self.emit(self.evidence(header))
        self.dispatch.poll()
        self.assertEqual(len(self.completed()),1)
        self.assertTrue(self.completed()[0].correlation_matched)
        self.assertTrue(any(r.wire_data==self.source.wire.encode(ack,'UDP')[0] for r in self.inbox.records))

    def test_all_declared_evidence_correlations_are_checked_and_bad_rows_retained(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        for changes in ({'event_id':'wrong'}, {'trace_id':'wrong'}, {'request_sequence':999},
                        {'message_id':8}, {'payload_sha256':'0'*64}, {'model_step':1101},
                        {'stage':'E0'}, {'probe_id':'consumer.Environment'},
                        {'stage':'E2','probe_id':'NO_PROBE'}):
            with self.subTest(changes=changes):
                self.emit(self.evidence(header,**changes))
                self.dispatch.poll()
                self.assertFalse(self.completed()[-1].correlation_matched)
                self.assertIsNotNone(self.completed()[-1].error)
        self.assertEqual(self.dispatch.pending_count,1)
        self.assertEqual(len(self.completed()),9)

    def test_raw_wrong_peer_and_bad_crc_are_retained_without_evidence_match(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        packet=self.source.wire.encode(self.evidence(header),'UDP')[0]
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as other:
            other.sendto(packet,self.source.feedback_endpoint)
        bad=bytearray(packet)
        bad[-1]^=1
        self.gateway.socket.sendto(bytes(bad),self.source.feedback_endpoint)
        self.dispatch.poll()
        rows=[r for r in self.inbox.records if r.kind=='DATAGRAM']
        self.assertEqual([r.wire_data for r in rows],[packet,bytes(bad)])
        self.assertEqual(len(self.completed()),0)
        self.assertEqual(self.source.dropped_feedback,2)

    def test_not_actually_transmitted_or_wrong_header_cannot_be_watched(self):
        self.setup_inbox()
        header=self.watch()
        self.rejects('STATE',lambda:self.dispatch.watch_evidence(copy.deepcopy(header),event_id='other',trace_id='run',min_step=0,max_step=100))
        self.emit(self.evidence(header))
        self.dispatch._receive(self.clock.value)
        self.assertEqual(len(self.completed()),1)
        self.assertFalse(self.completed()[0].correlation_matched)
        self.assertEqual(self.completed()[0].error,'STATE')

    def test_watch_limits_duplicates_and_strict_parameters_fail_without_tx(self):
        self.setup_inbox(max_requests=1)
        self.watch()
        header=self.dispatch.submit({'message_id':7,'payload':message(7)['payload']},target_step=101)
        self.rejects('BUFFER_FULL',lambda:self.dispatch.watch_evidence(header,event_id='b',trace_id='r',min_step=0,max_step=200))
        self.assertEqual(self.inbox.request_count,1)
        self.assertEqual(self.collect(),([],[]))

    def test_watch_invalid_bounds_stage_strings_and_opaque_identity(self):
        self.setup_inbox()
        header=self.dispatch.submit({'message_id':7,'payload':message(7)['payload']},target_step=100)
        base=dict(event_id='e',trace_id='t',min_step=0,max_step=100)
        for patch_value in ({'min_step':False},{'max_step':100.0},{'min_step':101},
                            {'max_step':2**32},{'event_id':''},{'trace_id':'x'*129},
                            {'stages':[]},{'stages':('E1','E1')},{'stages':('invalid',)}):
            data={**base,**patch_value}
            self.rejects('SCHEMA',lambda:self.dispatch.watch_evidence(header,**data))
        self.dispatch.watch_evidence(header,**base)
        self.rejects('DUPLICATE',lambda:self.dispatch.watch_evidence(header,**base))

    def test_duplicate_original_evidence_is_idempotent_but_conflict_and_stale_not_accepted(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        original=self.evidence(header)
        self.emit(original)
        self.dispatch.poll()
        self.emit(original)
        self.dispatch.poll()
        self.assertEqual(sum(r.correlation_matched for r in self.completed()),1)
        conflict=copy.deepcopy(original)
        conflict['payload']['model_step']+=1
        self.emit(conflict)
        self.dispatch.poll()
        self.assertEqual(self.completed()[-1].error,'DUPLICATE')

    def test_drain_preserves_request_context_and_feedback_highwater(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        rows=self.inbox.drain_records()
        self.assertTrue(rows)
        self.assertEqual(self.inbox.records,())
        self.assertEqual(self.inbox.request_count,1)
        self.emit(self.evidence(header,model_step=101))
        self.dispatch.poll()
        self.assertTrue(self.completed()[0].correlation_matched)
        row=self.completed()[0]
        detached=row.reply
        detached['payload']['trace_id']='changed'
        self.assertEqual(row.reply['payload']['trace_id'],'run-01')
        with self.assertRaises(FrozenInstanceError):
            row.error='changed'

    def test_capacity_preflight_does_not_read_queued_socket_datagram(self):
        self.setup_inbox(max_records=2)
        header=self.watch()
        self.transmit()
        self.emit(self.evidence(header))
        self.rejects('BUFFER_FULL',self.dispatch.poll)
        self.assertEqual(len(self.completed()),1)
        self.assertEqual(len(self.inbox.records),2)
        reply=self.evidence(header,model_step=101)
        self.emit(reply)
        self.rejects('BUFFER_FULL',self.dispatch.poll)
        self.inbox.drain_records()
        self.rejects('BUFFER_FULL',self.dispatch.poll)
        self.assertEqual(self.completed()[0].reply,reply)

    def test_enable_is_single_owner_close_preserves_records_not_remote_cleanup(self):
        self.setup_inbox()
        self.rejects('STATE',self.dispatch.enable_evidence_collection)
        header=self.watch()
        self.transmit()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        self.dispatch.close()
        self.assertTrue(self.inbox.records)
        self.assertEqual(self.inbox.request_count,0)
        self.assertEqual(self.session.session_id,73)
        self.assertEqual(self.session._state,'LIVE')

    def test_unwatch_original_context_after_ack_does_not_reset_sequences(self):
        self.setup_inbox()
        header=self.watch()
        request=self.transmit()[0]
        self.response(request)
        self.dispatch.poll()
        self.dispatch.unwatch_evidence(header)
        self.assertEqual(self.inbox.request_count,0)
        self.assertEqual(self.session.last_rx_sequence,2)

    def test_public_drain_cannot_race_the_single_socket_owner(self):
        self.setup_inbox()
        with self.dispatch._operation():
            self.rejects('STATE',self.inbox.drain_records)

    def test_published_consumer_e2_claim_is_correlated_but_never_qualified_locally(self):
        probe='consumer.'+message_name(self.contract,7)
        self.setup_inbox(probes=(probe,))
        header=self.watch()
        self.transmit()
        self.emit(self.evidence(header,stage='E2',probe_id=probe,business_result='PASS'))
        self.dispatch.poll()
        record=self.completed()[0]
        self.assertTrue(record.correlation_matched)
        self.assertEqual(record.reply['payload']['business_result'],'PASS')
        self.assertEqual(record.qualification_status,'NOT_EVALUATED')
        self.assertEqual(self.dispatch.pending_count,1)

    def test_unpublished_other_model_and_input_as_e3_probes_are_rejected(self):
        probes=[p for p in self.contract.catalogue['probe_catalog'] if 'model_id' in p and '.flight_control.' in p['name']]
        local=next(p['name'] for p in probes if p['model_id']=='quadrotor_hil')
        foreign=next(p['name'] for p in probes if p['model_id']=='multirotor_6_hil')
        self.setup_inbox(probes=(local,foreign))
        header=self.watch()
        self.transmit()
        for probe,stage,code in (('consumer.'+message_name(self.contract,7),'E2','TARGET_MISSING'),
                                 (foreign,'E2','MODEL'),(local,'E3','SCHEMA')):
            self.emit(self.evidence(header,stage=stage,probe_id=probe,business_result='PASS'))
            self.dispatch.poll()
            self.assertEqual(self.completed()[-1].error,code)
        self.emit(self.evidence(header,stage='E2',probe_id=local,business_result='PASS'))
        self.dispatch.poll()
        self.assertTrue(self.completed()[-1].correlation_matched)

    def test_fragmented_evidence_keeps_actual_arrival_bytes_and_decodes_in_reverse(self):
        self.setup_inbox()
        header=self.dispatch.submit({'message_id':7,'payload':message(7)['payload']},target_step=100)
        text='\U0001f600'*128
        self.dispatch.watch_evidence(header,event_id=text,trace_id=text,min_step=0,max_step=1100)
        self.transmit()
        reply=self.evidence(header,event_id=text,trace_id=text)
        frames=self.source.wire.encode(reply,'UDP')
        self.assertGreater(len(frames),1)
        for packet in reversed(frames):
            self.gateway.socket.sendto(packet,self.source.feedback_endpoint)
        self.dispatch.poll()
        self.assertEqual([r.wire_data for r in self.inbox.records if r.kind=='DATAGRAM'],list(reversed(frames)))
        self.assertEqual(self.completed()[0].reply,reply)
        self.assertTrue(self.completed()[0].correlation_matched)

    def test_packed_signed_zero_uses_actual_payload_bytes_not_canonicalized_request(self):
        import hashlib
        self.setup_inbox()
        payload=message(7)['payload']
        payload['motor_command'][0]=-0.0
        header=self.dispatch.submit({'message_id':7,'payload':payload},target_step=100)
        self.dispatch.watch_evidence(header,event_id='send-01',trace_id='run-01',min_step=0,max_step=1100)
        self.transmit()
        digest=hashlib.sha256(self.source.wire.payload_codec.encode(7,payload)).hexdigest()
        self.emit(self.evidence(header,payload_sha256=digest))
        self.dispatch.poll()
        row=self.completed()[0]
        self.assertTrue(row.correlation_matched)
        self.assertIn(b'-0.0',row.request_json)

    def test_oversized_datagram_keeps_all_original_bytes_not_truncated_prefix(self):
        self.setup_inbox()
        self.watch()
        self.transmit()
        raw=b'x'*10000
        self.gateway.socket.sendto(raw,self.source.feedback_endpoint)
        self.dispatch.poll()
        self.assertEqual(self.inbox.records[0].wire_data,raw)
        self.assertEqual(self.source.dropped_feedback,1)

    def test_all_fourteen_feedback_messages_preserve_their_actual_udp_fragments(self):
        self.setup_inbox()
        self.watch()
        self.transmit()
        raw=[]
        for mid,entry in self.contract.messages.items():
            if entry['direction'] != 'FROM_36':
                continue
            reply=message(mid)
            frames=self.source.wire.encode(reply,'UDP')
            for frame in frames:
                raw.append(frame)
                self.gateway.socket.sendto(frame,self.source.feedback_endpoint)
        self.dispatch.poll()
        self.assertEqual([r.wire_data for r in self.inbox.records if r.kind=='DATAGRAM'],raw)

    def test_public_inbox_close_detaches_collection_without_breaking_normal_ack(self):
        self.setup_inbox()
        self.watch()
        request=self.transmit()[0]
        self.inbox.close()
        self.response(request)
        self.dispatch.poll()
        self.assertEqual(self.dispatch.pending_count,0)
        self.assertIsNone(self.source._evidence_inbox)
        self.assertEqual(self.inbox.request_count,0)

    def test_partial_actual_resource_tx_group_cannot_qualify_evidence_correlation(self):
        import hashlib
        import time
        from test_resource_udp import chunk
        self.setup_inbox()
        request=chunk(b'z'*4000)
        header=self.dispatch.submit({'message_id':34,'payload':request['payload']},target_step=0)
        self.dispatch.watch_evidence(header,event_id='send-01',trace_id='run-01',min_step=0,max_step=1100)
        packets=[]
        for _ in range(100):
            self.dispatch.poll()
            new,_=self.collect()
            packets.extend(new)
            if packets:
                break
            time.sleep(0.001)
        self.assertGreater(len(packets),0)
        self.assertLess(len(packets),len(self.source.wire.encode({**request,'header':dict((n,getattr(header,n)) for n in request['header'])},'UDP')))
        digest=hashlib.sha256(self.source.wire.payload_codec.encode(34,request['payload'])).hexdigest()
        self.emit(self.evidence(header,message_id=34,payload_sha256=digest))
        self.dispatch._receive(self.clock.value)
        self.assertEqual(self.completed()[-1].error,'STATE')

    def test_collection_cannot_be_enabled_on_closed_actual_socket(self):
        self.setup_peer()
        self.source.close()
        self.rejects('STATE',self.dispatch.enable_evidence_collection)

    def test_collection_constructor_limits_remain_strict_and_atomic(self):
        self.setup_peer()
        for limits in ({'max_requests':False},{'max_requests':0},{'max_requests':65537},
                       {'max_records':1.0},{'max_records':0},{'max_bytes':True},
                       {'max_bytes':0},{'max_bytes':128*1024*1024+1}):
            self.rejects('CAPACITY',lambda:self.dispatch.enable_evidence_collection(**limits))
        self.assertIsNone(self.source._evidence_inbox)

    def test_lease_expiry_during_actual_evidence_decode_is_rejected_before_highwater(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        self.emit(self.evidence(header))
        decode=self.source.wire.decode
        def expire(*args,**kwargs):
            self.clock.value=self.session._deadline_ns
            return decode(*args,**kwargs)
        with patch.object(self.source.wire,'decode',expire):
            self.rejects('STALE_SESSION',self.dispatch.poll)
        row=self.completed()[0]
        self.assertFalse(row.correlation_matched)
        self.assertEqual(row.error,'STALE_SESSION')
        self.assertIsNotNone(row.request)
        self.assertEqual(self.session.last_rx_sequence,1)

    def test_clock_failure_during_evidence_decode_preserves_original_failed_claim(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        self.emit(self.evidence(header))
        decode=self.source.wire.decode
        def fail_clock(*args,**kwargs):
            self.clock.value-=1
            return decode(*args,**kwargs)
        with patch.object(self.source.wire,'decode',fail_clock):
            self.rejects('SCHEMA',self.dispatch.poll)
        self.assertEqual(self.completed()[0].error,'SCHEMA')
        self.assertFalse(self.completed()[0].correlation_matched)
        self.assertEqual(self.session.last_rx_sequence,1)


def message_name(contract, mid):
    return contract.entry(mid)['name']


for _name in set(test_dispatch.DispatcherTests.__dict__) | set(test_dispatch.MatchingTests.__dict__):
    if _name.startswith('test_') and _name not in EvidenceTests.__dict__:
        setattr(EvidenceTests,_name,None)
