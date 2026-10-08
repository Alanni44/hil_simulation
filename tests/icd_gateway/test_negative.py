"""Frozen negative bytes only; no actual sender/no-apply model qualification."""

from dataclasses import FrozenInstanceError, replace
import importlib.util
import struct
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.json_codec import loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame, WireCodec
from input_simulator.session import SourceSession
from test_scenario import send
from test_source_session import LocalClock, UnitPeer


class NegativeTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.clock=LocalClock()
        self.peer=UnitPeer(self.contract,self.clock)
        def publish(reply):
            if reply['message_id']==129:
                reply['payload']['capabilities']['implemented_message_ids']=[1,2,3,7,10,33,34,38]
            return reply
        self.peer.modify=publish
        self.source=SourceSession(self.peer,message(1)['payload']['identity'],
                                  ('STIMULUS','CONTROLLER','OBSERVER'),clock=self.clock)
        self.source.open()
        self.wire=WireCodec(self.contract)

    def prepare(self, mutation, *, mid=10, transport='UDP', cases=('T02',), **limits):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.negative'),
                             'original frozen NEGATIVE_SEND byte builder missing')
        from input_simulator.negative import prepare_negative_input
        event=send('negative-01',100,mid,type='NEGATIVE_SEND',mutation=mutation,
                   expected_error='SCHEMA',must_not_apply=True,authorization_case_id='T02',
                   link_id='CANT' if transport=='CANFD' else 'ETHGEN')
        item=self.source.prepare_input(event['stimulus'],transport,target_step=100)
        before=(self.source._next_sequence,self.source._next_transaction,self.source.prepared_inputs,
                len(self.peer.requests),self.source._deadline_ns)
        result=prepare_negative_input(self.source,item,event,enabled_cases=cases,**limits)
        self.assertEqual((self.source._next_sequence,self.source._next_transaction,self.source.prepared_inputs,
                          len(self.peer.requests),self.source._deadline_ns),before)
        self.assertIs(result.source_input,item)
        self.assertEqual(result.original_frames,item.frames)
        self.assertFalse(result.execution_ready)
        self.assertFalse(result.authorized_to_transmit)
        self.assertEqual(result.qualification_status,'NOT_EVALUATED')
        return result

    def assemble(self, result):
        assembler=Reassembler(self.contract)
        value=None
        for frame in result.mutated_frames:
            value=assembler.push(self.wire.decode(frame,result.source_input.transport),
                channel='CANFD_0' if result.source_input.transport=='CANFD' else 'ETH_0',
                direction='TO_36',authorized=True,now_ns=0) or value
        return value.message

    def payload(self, result):
        return b''.join(self.wire.decode(f,result.source_input.transport).payload
                        for f in result.mutated_frames)

    def test_packed_patch_retains_complete_fragments_but_receiver_rejects_range(self):
        for medium in ('UDP','CANFD'):
            with self.subTest(medium=medium):
                r=self.prepare({'kind':'PATCH_VALUE','field_path':'wind_n_mps','value':1000000},transport=medium)
                self.assertEqual(struct.unpack_from('<d',self.payload(r))[0],1000000)
                self.rejects('SCHEMA',lambda:self.assemble(r))

    def test_json_structural_drop_add_and_nested_array_patch_are_exact(self):
        cases=[({'kind':'DROP_FIELD','field_path':'origin.latitude_deg'},'origin','latitude_deg'),
               ({'kind':'ADD_UNKNOWN_FIELD','field_path':'origin.unexpected','value':1},'origin','unexpected')]
        for mutation,parent,key in cases:
            r=self.prepare(mutation,mid=3)
            payload=loads(self.payload(r))
            self.assertEqual(key in payload[parent],mutation['kind']=='ADD_UNKNOWN_FIELD')
            self.rejects('SCHEMA',lambda:self.assemble(r))
        r=self.prepare({'kind':'PATCH_VALUE','field_path':'initial_inputs.flight_control.motor_command[2]',
                        'value':1000000},mid=3)
        self.assertEqual(loads(self.payload(r))['initial_inputs']['flight_control']['motor_command'],[0,0,1000000,0])
        self.rejects('SCHEMA',lambda:self.assemble(r))

    def test_json_whole_container_field_is_a_unique_structural_target(self):
        r=self.prepare({'kind':'DROP_FIELD','field_path':'origin'},mid=3)
        self.assertNotIn('origin',loads(self.payload(r)))
        self.rejects('SCHEMA',lambda:self.assemble(r))
        r=self.prepare({'kind':'PATCH_VALUE','field_path':'initial_inputs.flight_control.motor_command',
                        'value':'invalid'},mid=3)
        self.assertEqual(loads(self.payload(r))['initial_inputs']['flight_control']['motor_command'],'invalid')
        self.rejects('SCHEMA',lambda:self.assemble(r))

    def test_all_header_mutations_reframe_every_fragment_and_keep_payload(self):
        for medium in ('UDP','CANFD'):
            for kind,field,value in (('SEQUENCE_OVERRIDE','sequence',0),('SESSION_OVERRIDE','session_id',0),
                                     ('TARGET_STEP_OVERRIDE','target_step',4294967295)):
                with self.subTest(medium=medium,kind=kind):
                    r=self.prepare({'kind':kind,field:value},transport=medium)
                    original=self.wire.payload_codec.encode(10,r.source_input.message['payload'])
                    pieces=[]
                    for frame in r.mutated_frames:
                        data=frame.data if medium=='CANFD' else frame
                        pieces.append(data[24:24+data[3]] if medium=='CANFD' else data[40:])
                        offset=(4 if medium=='CANFD' else 8)+4*('session_id','sequence','target_step').index(field)
                        self.assertEqual(struct.unpack_from('<I',data,offset)[0],value)
                    self.assertEqual(b''.join(pieces),original)
                    if field=='session_id':
                        self.rejects('STALE_SESSION',lambda:self.wire.decode(r.mutated_frames[0],medium))
                    elif field=='sequence':
                        self.rejects('SCHEMA',lambda:self.wire.decode(r.mutated_frames[0],medium))
                    else:
                        self.assertEqual(self.payload(r),original)
                        for f in r.mutated_frames:
                            self.assertEqual(getattr(self.wire.decode(f,medium).header,field),value)

    def test_crc_and_truncation_corrupt_only_one_original_fragment(self):
        for medium in ('UDP','CANFD'):
            r=self.prepare({'kind':'CRC_XOR','xor_mask':3},transport=medium)
            self.assertEqual(r.mutated_frames[1:],r.original_frames[1:])
            self.rejects('CRC',lambda:self.wire.decode(r.mutated_frames[0],medium))
            r=self.prepare({'kind':'TRUNCATE','remove_tail_bytes':1},transport=medium)
            self.assertEqual(r.mutated_frames[:-1],r.original_frames[:-1])
            raw=lambda f:f.data if type(f) is CANFrame else f
            self.assertEqual(raw(r.mutated_frames[-1]),raw(r.original_frames[-1])[:-1])
            self.rejects('FRAGMENT',lambda:self.wire.decode(r.mutated_frames[-1],medium))

    def test_f64_raw_nan_and_array_bits_never_pass_through_json(self):
        for medium in ('UDP','CANFD'):
            r=self.prepare({'kind':'F64_BITS','field_path':'wind_n_mps','bits_hex_le':'000000000000f87f'},transport=medium)
            self.assertEqual(self.payload(r)[:8],bytes.fromhex('000000000000f87f'))
            self.rejects('SCHEMA',lambda:self.assemble(r))
        r=self.prepare({'kind':'F64_BITS','field_path':'motor_command[3]','bits_hex_le':'010000000000f07f'},mid=7)
        self.assertEqual(self.payload(r)[24:],bytes.fromhex('010000000000f07f'))
        self.assertEqual(self.payload(r)[:24],self.wire.payload_codec.encode(7,r.source_input.message['payload'])[:24])

    def test_disabled_unknown_and_duplicate_case_lists_refuse_before_mutation(self):
        for cases in ((),('T05',),('NOT_APPROVED',),('T02','T02'),['T02'],([],),({'case':'T02'},)):
            self.rejects('AUTHORIZATION',lambda:self.prepare({'kind':'CRC_XOR','xor_mask':1},cases=cases))

    def test_wrong_missing_ambiguous_and_expression_paths_refuse(self):
        for path in ('motor_command','motor_command[4]','motor_command[-1]','motor_command[01]',
                     'motor_command[0].x','__dict__','motor_command[0]+1'):
            self.rejects('SCHEMA',lambda:self.prepare({'kind':'PATCH_VALUE','field_path':path,'value':2},mid=7))

    def test_structural_packed_and_raw_json_mutations_are_explicitly_unrepresentable(self):
        for mutation in ({'kind':'DROP_FIELD','field_path':'wind_n_mps'},
                         {'kind':'ADD_UNKNOWN_FIELD','field_path':'unknown','value':1}):
            self.rejects('UNSUPPORTED',lambda:self.prepare(mutation))
        self.rejects('UNSUPPORTED',lambda:self.prepare({'kind':'F64_BITS','field_path':'step_us',
                                                      'bits_hex_le':'000000000000f87f'},mid=3))

    def test_no_op_and_unknown_field_overwrite_are_not_negative_evidence(self):
        self.rejects('RESOURCE',lambda:self.prepare({'kind':'PATCH_VALUE','field_path':'wind_n_mps',
                                                   'value':message(10)['payload']['wind_n_mps']}))
        self.rejects('RESOURCE',lambda:self.prepare({'kind':'TARGET_STEP_OVERRIDE','target_step':100}))
        self.rejects('SCHEMA',lambda:self.prepare({'kind':'ADD_UNKNOWN_FIELD','field_path':'origin.frame','value':'x'},mid=3))

    def test_strict_mutation_types_and_truncate_bounds(self):
        for mutation in ({'kind':'CRC_XOR','xor_mask':True},{'kind':'SEQUENCE_OVERRIDE','sequence':0.0},
                         {'kind':'TRUNCATE','remove_tail_bytes':1200}):
            self.rejects('SCHEMA' if mutation['kind']!='TRUNCATE' else 'RANGE',lambda:self.prepare(mutation))

    def test_forged_and_stale_original_inputs_refuse(self):
        from input_simulator.negative import prepare_negative_input
        r=self.prepare({'kind':'CRC_XOR','xor_mask':1})
        event=r.event
        self.rejects('STATE',lambda:prepare_negative_input(self.source,replace(r.source_input),event,enabled_cases=('T02',)))
        self.clock.value=self.source._deadline_ns
        self.rejects('STALE_SESSION',lambda:prepare_negative_input(self.source,r.source_input,event,enabled_cases=('T02',)))

    def test_discarded_original_input_cannot_be_reused_for_negative_preparation(self):
        from input_simulator.negative import prepare_negative_input
        r=self.prepare({'kind':'CRC_XOR','xor_mask':1})
        self.source.discard_input(r.source_input)
        before=(self.source._next_sequence,self.source._next_transaction,
                self.source.prepared_inputs,len(self.peer.requests))
        self.rejects('STATE',lambda:prepare_negative_input(self.source,r.source_input,r.event,enabled_cases=('T02',)))
        self.assertEqual((self.source._next_sequence,self.source._next_transaction,
                         self.source.prepared_inputs,len(self.peer.requests)),before)

    def test_event_original_stimulus_and_tool_medium_cannot_be_substituted(self):
        from input_simulator.negative import prepare_negative_input
        r=self.prepare({'kind':'CRC_XOR','xor_mask':1})
        for key,value in (('type','SEND'),('must_not_apply',False),('link_id','CANT')):
            event=r.event
            event[key]=value
            self.rejects('SCHEMA' if key!='link_id' else 'AUTHORIZATION',
                lambda:prepare_negative_input(self.source,r.source_input,event,enabled_cases=('T02',)))
        event=r.event
        event['stimulus']['payload']['wind_n_mps']=1
        self.rejects('RESOURCE',lambda:prepare_negative_input(self.source,r.source_input,event,enabled_cases=('T02',)))

    def test_capacity_and_immutable_bytes_preserve_original_input(self):
        self.rejects('CAPACITY',lambda:self.prepare({'kind':'CRC_XOR','xor_mask':1},max_bytes=1))
        r=self.prepare({'kind':'CRC_XOR','xor_mask':1})
        with self.assertRaises(FrozenInstanceError):
            r.mutated_frames=()
        r.event['mutation']['xor_mask']=200
        self.assertEqual(r.event['mutation']['xor_mask'],1)

    def test_packed_patch_and_bits_preserve_negative_zero_exactly(self):
        for medium in ('UDP','CANFD'):
            for mutation in ({'kind':'PATCH_VALUE','field_path':'wind_n_mps','value':-0.0},
                             {'kind':'F64_BITS','field_path':'wind_n_mps','bits_hex_le':'0000000000000080'}):
                r=self.prepare(mutation,transport=medium)
                self.assertEqual(self.payload(r)[:8],struct.pack('<d',-0.0))
                self.assertEqual(self.payload(r)[8:],
                    self.wire.payload_codec.encode(10,r.source_input.message['payload'])[8:])

    def test_exact_negative_evidence_byte_bound_and_preserved_counters(self):
        from input_simulator.negative import prepare_negative_input
        r=self.prepare({'kind':'CRC_XOR','xor_mask':1})
        before=(self.source._next_sequence,self.source._next_transaction,self.source.prepared_inputs)
        exact=prepare_negative_input(self.source,r.source_input,r.event,enabled_cases=('T02',),max_bytes=r.stored_bytes)
        self.assertEqual(exact,r)
        self.rejects('CAPACITY',lambda:prepare_negative_input(self.source,r.source_input,r.event,
            enabled_cases=('T02',),max_bytes=r.stored_bytes-1))
        self.assertEqual((self.source._next_sequence,self.source._next_transaction,self.source.prepared_inputs),before)

    def receiver(self):
        from icd_gateway.receiver import Receiver
        from icd_gateway.session import PeerBinding,SessionRegistry,SourceGrant
        eth=PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        can=PeerBinding('CANFD_0','CANFD','can0')
        grant=SourceGrant(message(1)['payload']['identity'],('STIMULUS','CONTROLLER','OBSERVER'),(eth,can))
        with patch('icd_gateway.session.secrets.randbelow',return_value=72):
            registry=SessionRegistry(self.contract,[grant])
        receiver=Receiver(self.contract,registry)
        opened=None
        for frame in self.wire.encode(self.peer.requests[0],'UDP'):
            opened=receiver.receive(frame,eth,now_ns=self.clock.value)
        self.assertEqual(opened[0]['payload']['session_id'],self.source.session_id)
        return receiver,eth,can

    def test_actual_receiver_rejects_mutated_payload_before_admission(self):
        for medium in ('UDP','CANFD'):
            receiver,eth,can=self.receiver()
            r=self.prepare({'kind':'PATCH_VALUE','field_path':'wind_n_mps','value':1000000},transport=medium)
            replies=()
            for frame in r.mutated_frames:
                replies=receiver.receive(frame,eth if medium=='UDP' else can,now_ns=self.clock.value)
            self.assertEqual(replies[-1]['payload']['stage'],'FAILED')
            self.assertEqual(replies[-1]['payload']['error'],'SCHEMA')
            self.assertEqual(replies[-1]['payload']['request_sequence'],r.source_input.message['header']['sequence'])
            self.assertEqual(receiver.admitted_count,1)
            self.assertFalse(any(reply['payload'].get('stage')=='APPLIED' for reply in replies))

    def test_actual_receiver_crc_decode_failure_is_not_fabricated_correlated_ack(self):
        receiver,eth,can=self.receiver()
        r=self.prepare({'kind':'CRC_XOR','xor_mask':1})
        self.rejects('CRC',lambda:receiver.receive(r.mutated_frames[0],eth,now_ns=self.clock.value))
        self.assertEqual(receiver.admitted_count,1)
