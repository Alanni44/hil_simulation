"""Actual ICD reception without a model backend or application evidence."""

from dataclasses import FrozenInstanceError
import importlib.util

from common import GatewayTest, message
from icd_gateway.receiver import Receiver
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_runtime.json_codec import loads


class ReceptionTests(GatewayTest):
    def create(self, *, model='quadrotor_hil', roles=('STIMULUS','CONTROLLER'), **limits):
        self.assertIsNotNone(importlib.util.find_spec('icd_gateway.reception_service'),
                             'explicit reception-only service is missing')
        from icd_gateway.reception_service import ReceptionService
        identity=message(1)['payload']['identity']
        identity['model_id']=model
        self.udp=PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        self.can=PeerBinding('CANFD_0','CANFD','can0')
        self.registry=SessionRegistry(self.contract,[SourceGrant(identity,roles,(self.udp,self.can))])
        self.service=ReceptionService(self.contract,self.registry,tuple(range(7,20)),**limits)
        self.receiver=Receiver(self.contract,self.registry,reception_service=self.service)
        opening=message(1)
        opening['payload']['identity']=identity
        opening['payload']['roles']=list(roles)
        opened=self.deliver(opening)[0]
        self.sid=opened['payload']['session_id']
        self.caps=opened['payload']['capabilities']

    def deliver(self, value, *, link=None, now=0):
        link=link or self.udp
        replies=()
        for packet in self.receiver.wire.encode(value,link.transport):
            replies=self.receiver.receive(packet,link,now_ns=now)
        return replies

    def request(self, mid=10, sequence=2):
        value=message(mid)
        value['header'].update(session_id=self.sid,sequence=sequence,transaction_id=sequence,target_step=80)
        return value

    def test_udp_decodes_full_payload_and_only_publishes_e1(self):
        self.create()
        value=self.request()
        replies=self.deliver(value)
        self.assertEqual([r['payload']['stage'] for r in replies],['RECEIVED','VALIDATED'])
        self.assertTrue(all(r['payload']['probe_id']==0 for r in replies))
        self.assertEqual(self.caps['available_probes'],[])
        self.assertFalse(self.caps['replacement_ready'])
        record=self.service.records[0]
        self.assertEqual(loads(record.message_json),value)
        self.assertEqual(record.binding,self.udp)
        self.assertEqual(record.received_ns,0)
        self.assertFalse(record.model_applied)
        self.assertEqual(record.validation_scope,'WIRE_SCHEMA_SESSION_ONLY')
        self.assertEqual(loads(record.identity_json)['model_id'],'quadrotor_hil')
        with self.assertRaises(FrozenInstanceError):
            record.received_ns=1

    def test_all_models_all_applicable_messages_and_transports(self):
        for model in ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil'):
            self.create(model=model)
            seq=2
            for mid in range(7,20):
                entry=self.contract.entry(mid)
                if model not in entry['model_ids']:
                    self.assertNotIn(mid,self.caps['implemented_message_ids'])
                    continue
                for transport in entry['transports']:
                    with self.subTest(model=model,mid=mid,transport=transport):
                        replies=self.deliver(self.request(mid,seq),link=self.can if transport=='CANFD' else self.udp)
                        self.assertEqual(replies[-1]['payload']['stage'],'VALIDATED')
                        self.assertEqual(self.service.records[-1].binding.transport,transport)
                        seq+=1

    def test_exact_retry_returns_original_feedback_without_duplicate_record(self):
        self.create(max_records=1)
        request=self.request()
        replies=self.deliver(request)
        self.assertEqual(self.deliver(request,now=1),replies)
        self.assertEqual(len(self.service.records),1)
        self.assertEqual(self.service.records[0].received_ns,0)

    def test_capacity_rejects_before_new_admission_and_preserves_old_records(self):
        for limits in ({'max_records':1},{'max_bytes':1}):
            with self.subTest(limits=limits):
                self.create(**limits)
                if limits.get('max_records'):
                    self.deliver(self.request())
                before=self.registry._sessions[self.sid].last_rx
                replies=self.deliver(self.request(sequence=3))
                self.assertEqual((replies[-1]['payload']['stage'],replies[-1]['payload']['error']),('FAILED','BUFFER_FULL'))
                self.assertEqual(self.registry._sessions[self.sid].last_rx,before)

    def test_role_crc_and_expiry_do_not_record_or_validate(self):
        self.create(roles=('STIMULUS',))
        self.rejects('AUTHORIZATION',lambda:self.deliver(self.request(7)))
        bad=bytearray(self.receiver.wire.encode(self.request(),'UDP')[0])
        bad[-1]^=1
        self.rejects('CRC',lambda:self.receiver.receive(bytes(bad),self.udp,now_ns=0))
        self.assertEqual(self.service.records,())
        self.rejects('STALE_SESSION',lambda:self.deliver(self.request(),now=1000000000))
        self.assertEqual(self.service.records,())

    def test_reception_does_not_enable_status_or_lifecycle_effects(self):
        self.create()
        self.assertNotIn(2,self.caps['implemented_message_ids'])
        self.assertNotIn(4,self.caps['implemented_message_ids'])
        self.assertEqual(self.deliver(self.request(4))[-1]['payload']['error'],'TARGET_MISSING')
        self.assertEqual(self.service.records,())

    def test_wrong_owner_and_source_identity_are_rejected(self):
        self.create()
        old=self.receiver.reception_service
        self.receiver.reception_service=object()
        self.rejects('STATE',lambda:self.deliver(self.request()))
        self.receiver.reception_service=old
        self.rejects('AUTHORIZATION',lambda:self.deliver(self.request(),link=PeerBinding('ETH_0','UDP','127.0.0.1:39999')))
        self.assertEqual(self.service.records,())

    def test_close_keeps_decoded_records_and_rejects_new_receive(self):
        self.create()
        self.deliver(self.request())
        records=self.service.records
        self.receiver.close()
        self.assertEqual(self.service.records,records)
        self.rejects('STATE',lambda:self.deliver(self.request(sequence=3)))
