"""Actual standard transport/service tests; model backend is a labeled double."""

import importlib.util
from dataclasses import FrozenInstanceError, replace
import threading

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.errors import ICDError
from icd_runtime.wire import WireCodec
from icd_gateway.receiver import Receiver
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant


class StatusServiceTests(GatewayTest):
    def create(self, *, transport='UDP', model='quadrotor_hil', open_session=True, **limits):
        self.assertIsNotNone(importlib.util.find_spec('icd_gateway.status_service'),
                             'original Receiver Heartbeat/Status service missing')
        from icd_gateway.status_service import ModelStatusBackend, ModelStatusSample, ModelStatusService
        class ExplicitModelDouble(ModelStatusBackend):
            def read_status(self, identity, *, now_ns):
                self.calls+=1
                return self.sample
        self.backend=ExplicitModelDouble(self.contract,(model,))
        self.backend.calls=0
        self.payload=message(131)['payload']
        self.payload.update(model_step=17,phase='TAKEOFF')
        self.identity=message(1)['payload']['identity']
        self.identity['model_id']=model
        self.backend.sample=ModelStatusSample(canonicalize(self.identity),canonicalize(self.payload),0,240_000_000)
        self.link=PeerBinding('ETH_0' if transport=='UDP' else 'CANFD_0',transport,
                              '127.0.0.1:36102' if transport=='UDP' else 'can0')
        self.open_link=PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        links=tuple(dict.fromkeys((self.open_link,self.link)))
        self.registry=SessionRegistry(self.contract,[SourceGrant(self.identity,('STIMULUS',),links)])
        self.now=0
        self.service=ModelStatusService(self.contract,self.registry,self.backend,clock=lambda:self.now,**limits)
        self.receiver=Receiver(self.contract,self.registry,status_service=self.service)
        self.wire=WireCodec(self.contract)
        self.transport=transport
        opening=message(1)
        opening['payload']['identity']=self.identity
        self.sid=None
        self.opened=self.open_request(opening) if open_session else ()
        if self.opened and self.opened[0]['message_id']==129:
            self.sid=self.opened[0]['payload']['session_id']

    def open_request(self, request=None, now=0):
        self.now=now
        request=message(1) if request is None else request
        replies=()
        for packet in self.wire.encode(request,'UDP'):
            replies=self.receiver.receive(packet,self.open_link,now_ns=now)
        return replies

    def deliver(self, request, now=0):
        self.now=now
        replies=()
        for packet in self.wire.encode(request,self.transport):
            replies=self.receiver.receive(packet,self.link,now_ns=now)
        return replies

    def heartbeat(self, sequence=2):
        request=message(2)
        request['header'].update(session_id=self.sid,sequence=sequence,transaction_id=sequence)
        return request

    def test_installed_backend_open_grant_uses_actual_model_step_not_interface_origin(self):
        self.create()
        reply=self.deliver(message(1))[0]
        self.assertEqual(reply['payload']['receiver_step'],17)
        self.assertEqual(reply['header']['target_step'],17)
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(len(self.service.records),1)
        record=self.service.records[0]
        self.assertEqual(loads(record.request_json)['message_id'],1)
        self.assertEqual(loads(record.reply_json),reply)

    def test_open_retry_preserves_original_grant_and_sample_without_new_sid(self):
        self.create()
        original=self.opened
        deadline=self.registry._sessions[self.sid].deadline_ns
        next_id=self.registry._next_id
        self.backend.sample=replace(self.backend.sample,
            payload_json=canonicalize({**self.payload,'model_step':99}))
        self.assertEqual(self.open_request(now=1),original)
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(len(self.service.records),1)
        self.assertEqual(self.registry._next_id,next_id)
        self.assertEqual(self.registry._sessions[self.sid].deadline_ns,deadline)

    def test_preview_open_checks_identity_roles_nonce_and_capacity_without_allocation(self):
        self.create(open_session=False)
        next_id=self.registry._next_id
        preview=self.registry.preview_open(message(1),self.open_link,now_ns=0)
        self.assertEqual(preview.session_id,0)
        self.assertIsNone(preview.replay)
        self.assertEqual(self.registry.session_ids,())
        self.assertEqual(self.registry.cache_count,0)
        self.assertEqual(self.registry._opens,{})
        self.assertEqual(self.registry._next_id,next_id)
        for field in ('identity','roles'):
            request=message(1)
            if field=='identity':
                request['payload']['identity']['scenario_id']='other-context'
            else:
                request['payload']['roles']=['CONTROLLER']
            self.assertEqual(self.open_request(request)[-1]['payload']['error'],'AUTHORIZATION')
        self.assertEqual(self.backend.calls,0)
        granted=self.open_request()
        self.assertEqual(self.registry.preview_open(message(1),self.open_link,now_ns=0).replay,granted)
        changed=message(1)
        changed['header']['transaction_id']+=1
        self.assertEqual(self.open_request(changed)[-1]['payload']['error'],'DUPLICATE')
        self.registry._max_sessions=1
        changed['payload']['nonce_hex']='0123456789abcdef0123456789abcdef'
        self.assertEqual(self.open_request(changed)[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(self.registry.active_count,1)

    def test_failed_open_snapshot_retained_no_grant_and_exact_attempt_not_resampled(self):
        self.create(open_session=False)
        next_id=self.registry._next_id
        payload=dict(self.payload)
        del payload['model_step']
        self.backend.sample=replace(self.backend.sample,payload_json=canonicalize(payload))
        first=self.open_request()
        self.assertEqual(first[-1]['payload']['error'],'SCHEMA')
        self.assertEqual(first[-1]['header']['session_id'],0)
        self.assertEqual(first[-1]['payload']['stage'],'FAILED')
        self.assertEqual(self.registry.session_ids,())
        self.assertEqual(self.registry._opens,{})
        self.assertEqual(self.registry.cache_count,0)
        self.assertEqual(self.registry._next_id,next_id)
        self.assertEqual(self.receiver.admitted_count,0)
        self.assertIs(self.service.records[0].sample,self.backend.sample)
        self.assertIsNone(self.service.records[0].reply_json)
        self.assertEqual(self.open_request(now=1)[-1]['payload']['error'],'SCHEMA')
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(len(self.service.records),1)

    def test_open_invalid_context_freshness_type_or_backend_failure_never_allocates(self):
        for kind,error in (('identity','MODEL'),('future','EXPIRED'),('expired','EXPIRED'),
                           ('untyped','STATE'),('throw','RESOURCE')):
            with self.subTest(kind=kind):
                self.create(open_session=False)
                next_id=self.registry._next_id
                if kind=='identity':
                    self.backend.sample=replace(self.backend.sample,
                        identity_json=canonicalize({**self.identity,'scenario_id':'other'}))
                elif kind=='future':
                    self.backend.sample=replace(self.backend.sample,sampled_ns=1)
                elif kind=='expired':
                    self.backend.sample=replace(self.backend.sample,deadline_ns=1)
                else:
                    def fail(identity, *, now_ns):
                        self.backend.calls+=1
                        if kind=='throw':
                            raise OSError('explicit test getter failure')
                        return {'fake':True}
                    self.backend.read_status=fail
                self.assertEqual(self.open_request(now=1 if kind=='expired' else 0)[-1]['payload']['error'],error)
                self.assertEqual(self.registry.session_ids,())
                self.assertEqual(self.registry.cache_count,0)
                self.assertEqual(self.registry._next_id,next_id)
                self.assertEqual(self.service.records[-1].error,error)
                self.assertIsNone(self.service.records[-1].reply_json)

    def test_failed_open_after_field_validation_retries_original_error_without_read(self):
        self.create(open_session=False)
        self.backend.sample=replace(self.backend.sample,deadline_ns=1)
        self.assertEqual(self.open_request(now=1)[-1]['payload']['error'],'EXPIRED')
        self.assertEqual(self.open_request(now=2)[-1]['payload']['error'],'EXPIRED')
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(len(self.service.records),1)
        self.assertEqual(self.registry.session_ids,())

    def test_slow_open_allocates_lease_and_caches_reply_at_actual_completion(self):
        self.create(open_session=False)
        sample=self.backend.sample
        def slow(identity, *, now_ns):
            self.backend.calls+=1
            self.now=50_000_000
            return sample
        self.backend.read_status=slow
        granted=self.open_request()[0]
        sid=granted['payload']['session_id']
        self.assertEqual(granted['payload']['receiver_step'],17)
        self.assertEqual(self.registry._sessions[sid].deadline_ns,1_050_000_000)
        self.assertEqual(self.service.records[0].completed_ns,50_000_000)
        self.assertEqual(self.open_request(now=50_000_001),(granted,))
        self.assertEqual(self.backend.calls,1)

    def test_open_outliving_request_never_grants_even_with_fresh_model_sample(self):
        self.create(open_session=False)
        next_id=self.registry._next_id
        sample=replace(self.backend.sample,sampled_ns=1_000_000_000,deadline_ns=1_240_000_000)
        def slow(identity, *, now_ns):
            self.backend.calls+=1
            self.now=1_000_000_000
            return sample
        self.backend.read_status=slow
        self.assertEqual(self.open_request()[-1]['payload']['error'],'EXPIRED')
        self.assertEqual(self.registry.session_ids,())
        self.assertEqual(self.registry._next_id,next_id)
        self.assertIs(self.service.records[0].sample,sample)
        self.assertEqual(self.service.records[0].completed_ns,1_000_000_000)

    def test_opening_sample_seeds_same_sid_model_floor_before_first_heartbeat(self):
        self.create()
        self.backend.sample=replace(self.backend.sample,
            payload_json=canonicalize({**self.payload,'model_step':16}))
        self.assertEqual(self.deliver(self.heartbeat())[-1]['payload']['error'],'CLOCK_UNSYNC')

    def test_full_pending_retry_cache_rejects_open_before_read_or_sid_allocation(self):
        from icd_gateway.session import _Record
        self.create(open_session=False)
        for index in range(self.registry._policy['duplicate_cache_messages']):
            self.registry._records[(0,index)]=_Record(b'x',2_000_000_000,0,
                                                    resource_deadline_ns=2_000_000_000)
        next_id=self.registry._next_id
        before=tuple(self.registry._records.items())
        self.assertEqual(self.open_request()[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual(self.registry.session_ids,())
        self.assertEqual(self.registry._opens,{})
        self.assertEqual(self.registry._next_id,next_id)
        self.assertEqual(tuple(self.registry._records.items()),before)
        self.assertEqual(self.backend.calls,0)
        self.assertEqual(self.service.records,())

    def test_standard_heartbeat_status_exact_payload_and_original_correlation(self):
        for medium in ('UDP','CANFD'):
            with self.subTest(medium=medium):
                self.create(transport=medium)
                request=self.heartbeat()
                replies=self.deliver(request,now=1)
                self.assertEqual(len(replies),1)
                reply=replies[0]
                self.assertEqual(reply['message_id'],131)
                self.assertEqual(reply['payload'],self.payload)
                self.assertEqual(reply['header']['session_id'],self.sid)
                self.assertEqual(reply['header']['transaction_id'],2)
                self.assertEqual(reply['header']['target_step'],17)
                self.contract.validate_message(reply,direction='FROM_36')
                self.assertEqual(self.backend.calls,2)
                self.assertEqual(len(self.service.records),2)
                record=self.service.records[-1]
                self.assertEqual(record.request_json,canonicalize(request))
                self.assertEqual(record.reply_json,canonicalize(reply))
                self.assertEqual(record.sample,self.backend.sample)
                self.assertFalse(self.service.execution_ready)
                self.assertEqual(self.service.qualification_status,'NOT_EVALUATED')

    def test_only_installed_status_capability_is_published_without_model_ready_claims(self):
        self.create()
        caps=self.deliver(message(1))[0]['payload']['capabilities']
        self.assertEqual(caps['implemented_message_ids'],[1,2])
        self.assertEqual(caps['available_probes'],['consumer.Status'])
        self.assertEqual(caps['qualified_channels'],[])
        for field in ('initialization_port_ready','system_model_ready','replacement_ready','phase_controller_ready'):
            self.assertFalse(caps[field])
        self.assertEqual(self.backend.calls,1)

    def test_original_retry_uses_identical_cached_status_without_resampling_or_renewal(self):
        self.create()
        request=self.heartbeat()
        first=self.deliver(request,now=1)
        deadline=self.registry._sessions[self.sid].deadline_ns
        self.backend.sample=replace(self.backend.sample,payload_json=canonicalize({**self.payload,'model_step':99}))
        self.assertEqual(self.deliver(request,now=2),first)
        self.assertEqual(self.backend.calls,2)
        self.assertEqual(len(self.service.records),2)
        self.assertEqual(self.registry._sessions[self.sid].deadline_ns,deadline)
        self.rejects('STATE',lambda:self.service.respond(request,now_ns=2))
        self.assertEqual(self.backend.calls,2)

    def test_all_twelve_fields_required_exact_types_and_unknown_fields_rejected(self):
        self.create()
        sequence=2
        for key in self.payload:
            payload=dict(self.payload)
            del payload[key]
            self.backend.sample=replace(self.backend.sample,payload_json=canonicalize(payload))
            replies=self.deliver(self.heartbeat(sequence))
            sequence+=1
            self.assertEqual(replies[-1]['payload']['error'],'SCHEMA',key)
        for key,value in (('model_step',17.0),('safety_active',0),('extra',1)):
            # Preserve a literal JSON float; RFC8785 would normalize 17.0.
            raw=canonicalize({**self.payload,key:value})
            if key=='model_step':
                raw=raw.replace(b'"model_step":17',b'"model_step":17.0')
            self.backend.sample=replace(self.backend.sample,payload_json=raw)
            replies=self.deliver(self.heartbeat(sequence))
            sequence+=1
            self.assertEqual(replies[-1]['payload']['error'],'SCHEMA',key)
        self.assertTrue(all(r.error=='SCHEMA' and r.reply_json is None for r in self.service.records[1:]))

    def test_original_sample_identity_all_context_fields_must_match(self):
        self.create()
        for index,key in enumerate(self.identity):
            identity={**self.identity,key:'other-context'}
            self.backend.sample=replace(self.backend.sample,identity_json=canonicalize(identity))
            replies=self.deliver(self.heartbeat(2+index))
            self.assertEqual(replies[-1]['payload']['error'],'MODEL')
            self.assertIs(self.service.records[-1].sample,self.backend.sample)

    def test_snapshot_half_open_deadline_future_and_frozen_240ms_freshness(self):
        for sampled,deadline,now in ((2,100,1),(0,100,100),(0,500_000_000,240_000_000)):
            with self.subTest(sampled=sampled,deadline=deadline,now=now):
                self.create()
                self.backend.sample=replace(self.backend.sample,sampled_ns=sampled,deadline_ns=deadline)
                replies=self.deliver(self.heartbeat(),now=now)
                self.assertEqual(replies[-1]['payload']['error'],'EXPIRED')
                self.assertEqual(self.service.records[-1].received_ns,now)
                self.assertIsNone(self.service.records[-1].reply_json)

    def test_same_sid_model_step_and_sample_time_cannot_regress(self):
        for kind in ('model_step','sampled_ns'):
            self.create()
            self.backend.sample=replace(self.backend.sample,sampled_ns=10)
            self.assertEqual(self.deliver(self.heartbeat(),now=10)[0]['message_id'],131)
            self.backend.sample=replace(self.backend.sample,
                payload_json=canonicalize({**self.payload,'model_step':16 if kind=='model_step' else 17}),
                sampled_ns=9 if kind=='sampled_ns' else 11)
            replies=self.deliver(self.heartbeat(3),now=11)
            self.assertEqual(replies[-1]['payload']['error'],'CLOCK_UNSYNC')
            self.assertEqual(self.backend.calls,3)

    def test_finite_evidence_reservation_refuses_before_backend_read(self):
        self.create(max_records=2)
        self.deliver(self.heartbeat())
        original=self.service.records
        replies=self.deliver(self.heartbeat(3))
        self.assertEqual(replies[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual(self.backend.calls,2)
        self.assertEqual(self.service.records,original)
        self.create(max_bytes=1)
        self.assertEqual(self.opened[-1]['payload']['error'],'BUFFER_FULL')
        self.assertIsNone(self.sid)
        self.assertEqual(self.registry.session_ids,())
        self.assertEqual(self.backend.calls,0)
        self.assertEqual(self.service.records,())

    def test_backend_error_and_untyped_sample_never_create_status_or_application(self):
        self.create()
        def failing(identity, *, now_ns):
            raise ICDError('TARGET_MISSING','explicit test model getter missing')
        self.backend.read_status=failing
        replies=self.deliver(self.heartbeat())
        self.assertEqual([r['payload']['stage'] for r in replies],['RECEIVED','FAILED'])
        self.assertEqual(replies[-1]['payload']['error'],'TARGET_MISSING')
        self.assertEqual(self.service.records[-1].error,'TARGET_MISSING')
        def untyped(identity, *, now_ns):
            return {'fake':True}
        self.backend.read_status=untyped
        self.assertEqual(self.deliver(self.heartbeat(3))[-1]['payload']['error'],'STATE')
        def ordinary_failure(identity, *, now_ns):
            raise OSError('test getter transport disconnected')
        self.backend.read_status=ordinary_failure
        self.assertEqual(self.deliver(self.heartbeat(4))[-1]['payload']['error'],'RESOURCE')
        self.assertTrue(all(r.reply_json is None for r in self.service.records[1:]))

    def test_same_receiver_registry_and_backend_identity_cannot_be_replaced(self):
        self.create()
        original=self.backend
        self.service.backend=type(original)(self.contract,('quadrotor_hil',))
        before=self.receiver.admitted_count
        self.rejects('STATE',lambda:self.deliver(self.heartbeat()))
        self.assertEqual(self.receiver.admitted_count,before)
        self.assertEqual(original.calls,1)
        self.service.backend=original
        from icd_gateway.status_service import ModelStatusService
        replacement=ModelStatusService(self.contract,self.registry,original)
        self.receiver.status_service=replacement
        self.rejects('STATE',lambda:self.deliver(self.heartbeat()))
        self.assertEqual(self.receiver.admitted_count,before)

    def test_no_backend_can_be_created_or_implicitly_enabled(self):
        self.create()
        from icd_gateway.status_service import ModelStatusBackend, ModelStatusService
        self.rejects('TARGET_MISSING',lambda:ModelStatusService(self.contract,self.registry,None))
        with self.assertRaises(TypeError):
            ModelStatusBackend(self.contract,('quadrotor_hil',))
        registry=SessionRegistry(self.contract,[SourceGrant(self.identity,('STIMULUS',),(self.open_link,))])
        receiver=Receiver(self.contract,registry)
        opened=()
        for packet in self.wire.encode(message(1),'UDP'):
            opened=receiver.receive(packet,self.open_link,now_ns=0)
        self.assertEqual(opened[0]['payload']['capabilities']['implemented_message_ids'],[1])
        self.assertEqual(opened[0]['payload']['receiver_step'],0)

    def test_immutable_sample_strict_time_and_byte_bounds(self):
        self.create()
        from icd_gateway.status_service import ModelStatusSample
        with self.assertRaises(FrozenInstanceError):
            self.backend.sample.sampled_ns=12
        for identity,payload,start,end in ((b'x'*4097,b'{}',0,1),(b'{}',b'{}',True,1),
                                          (b'{}',b'{}',0,1.0),(b'{}',b'{}',1,1)):
            self.rejects('SCHEMA',lambda:ModelStatusSample(identity,payload,start,end))

    def test_reentrant_backend_and_closed_service_do_not_lose_original_records(self):
        self.create()
        request=self.heartbeat()
        sample=self.backend.sample
        def reentrant(identity, *, now_ns):
            self.rejects('STATE',lambda:self.service.respond(request,now_ns=now_ns))
            self.rejects('STATE',self.service.close)
            self.rejects('STATE',self.receiver.close)
            self.assertFalse(self.registry._closed)
            return sample
        self.backend.read_status=reentrant
        self.assertEqual(self.deliver(request)[0]['message_id'],131)
        records=self.service.records
        self.receiver.close()
        self.assertEqual(self.service.records,records)
        self.rejects('STATE',lambda:self.service.respond(request,now_ns=0))

    def test_all_frozen_models_and_new_sid_allow_new_model_epoch_without_reusing_old_floor(self):
        for model in self.contract.entry(2)['model_ids']:
            self.create(model=model)
            self.assertEqual(self.deliver(self.heartbeat())[0]['payload']['model_step'],17)
            self.receiver.retire_session(self.sid)
            opening=message(1)
            opening['payload']['identity']=self.identity
            opening['payload']['nonce_hex']='0123456789abcdef0123456789abcdef'
            opening['header'].update(sequence=1,transaction_id=20)
            self.backend.sample=replace(self.backend.sample,
                payload_json=canonicalize({**self.payload,'model_step':0}))
            self.now=1
            opened=()
            for packet in self.wire.encode(opening,'UDP'):
                opened=self.receiver.receive(packet,self.open_link,now_ns=1)
            old_sid=self.sid
            self.sid=opened[0]['payload']['session_id']
            self.assertNotEqual(self.sid,old_sid)
            self.assertEqual(opened[0]['payload']['receiver_step'],0)
            self.assertEqual(self.deliver(self.heartbeat(),now=1)[0]['payload']['model_step'],0)
            self.assertEqual(len(self.service.records),4)

    def test_direct_service_requires_original_admission_and_typed_request(self):
        self.create()
        request=self.heartbeat()
        self.rejects('OUT_OF_ORDER',lambda:self.service.respond(request,now_ns=0))
        self.registry.accept(request,self.link,now_ns=0)
        malformed={**request,'header':{**request['header'],'sequence':2.0}}
        self.rejects('SCHEMA',lambda:self.service.respond(malformed,now_ns=0))
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(len(self.service.records),1)

    def test_slow_backend_snapshot_expiry_is_checked_at_actual_completion_not_ingress(self):
        self.create()
        sample=self.backend.sample
        def slow(identity, *, now_ns):
            self.now=240_000_000
            return sample
        self.backend.read_status=slow
        replies=self.deliver(self.heartbeat())
        self.assertEqual(replies[-1]['payload']['error'],'EXPIRED')
        self.assertEqual(self.service.records[-1].completed_ns,240_000_000)
        self.assertEqual(self.service.records[-1].received_ns,0)
        self.assertIsNone(self.service.records[-1].reply_json)

    def test_backend_returns_after_lease_expiry_no_status_or_stale_ack_is_minted(self):
        self.create()
        sample=self.backend.sample
        returned=replace(sample,sampled_ns=1_000_000_000,deadline_ns=1_240_000_000)
        def slow(identity, *, now_ns):
            self.now=1_000_000_000
            return returned
        self.backend.read_status=slow
        self.rejects('STALE_SESSION',lambda:self.deliver(self.heartbeat()))
        self.assertEqual(self.service.records[-1].error,'STALE_SESSION')
        self.assertIsNone(self.service.records[-1].reply_json)
        self.assertIs(self.service.records[-1].sample,returned)

    def test_throwing_backend_retains_actual_completion_time_and_does_not_ack_expired_sid(self):
        self.create()
        def slow_failure(identity, *, now_ns):
            self.now=1_000_000_000
            raise OSError('test getter disconnected after lease expired')
        self.backend.read_status=slow_failure
        self.rejects('STALE_SESSION',lambda:self.deliver(self.heartbeat()))
        self.assertEqual(self.service.records[-1].completed_ns,1_000_000_000)
        self.assertEqual(self.service.records[-1].error,'RESOURCE')
        self.assertIsNone(self.service.records[-1].sample)

    def test_actual_udp_receiver_status_feeds_original_source_clock_and_reader(self):
        from test_udp import UDPTests
        from icd_gateway.status_service import ModelStatusBackend, ModelStatusSample, ModelStatusService
        from input_simulator.session import SourceSession
        from input_simulator.model_clock import ObservedModelClock
        from input_simulator.scenario_assertions import StatusObservationReader
        fixture=UDPTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.create_network()
        identity=message(1)['payload']['identity']
        payload={**message(131)['payload'],'model_step':17,'state':'PAUSED'}
        class CoherentModelDouble(ModelStatusBackend):
            def read_status(self, requested, *, now_ns):
                return ModelStatusSample(canonicalize(identity),canonicalize(payload),now_ns,now_ns+240_000_000)
        backend=CoherentModelDouble(fixture.contract,('quadrotor_hil',))
        service=ModelStatusService(fixture.contract,fixture.registry,backend)
        fixture.receiver=Receiver(fixture.contract,fixture.registry,status_service=service)
        fixture.gateway.receiver=fixture.receiver
        stop=threading.Event()
        errors=[]
        def run():
            try:
                while not stop.is_set():
                    fixture.gateway.poll(timeout=0.001)
            except Exception as exc:
                errors.append(exc)
        thread=threading.Thread(target=run)
        thread.start()
        try:
            source=SourceSession(fixture.source,identity,('STIMULUS',))
            grant=source.open()
            self.assertEqual(grant['payload']['receiver_step'],17)
            self.rejects('TARGET_MISSING',lambda:ObservedModelClock(source).require_step(17))
            reader=StatusObservationReader(source)
            reply=source.heartbeat(17,target_step=17)
            snapshot=ObservedModelClock(source).require_step(17,required_state='PAUSED')
            self.assertEqual(snapshot.status,reply)
            self.assertEqual(reader.records[0].status,reply)
            self.assertEqual(loads(service.records[-1].reply_json),reply)
            self.assertEqual(source.capabilities['available_probes'],['consumer.Status'])
            reader.close()
            source.close()
        finally:
            stop.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
