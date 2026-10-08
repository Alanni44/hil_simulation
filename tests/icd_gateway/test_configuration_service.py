"""Actual standard ingress; configuration backend is an explicit model double."""

from dataclasses import FrozenInstanceError, replace
import importlib.util
import threading
import time

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.wire import Header, WireCodec
from icd_gateway.receiver import Receiver
from icd_gateway.semantic_guards import ModelView
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant


class ConfigurationServiceTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('icd_gateway.configuration_service'),
                             'actual original RunConfigure consumer service missing')
        from icd_gateway import configuration_service
        self.module=configuration_service

    def create(self, *, model='quadrotor_hil',transport='UDP',installed=True,with_status=False,**limits):
        module=self.module
        self.identity=message(1)['payload']['identity']
        self.identity['model_id']=model
        self.now=0
        self.open_link=PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        self.link=PeerBinding('ETH_0' if transport=='UDP' else 'CANFD_0',transport,
                              '127.0.0.1:36102' if transport=='UDP' else 'can0')
        self.registry=SessionRegistry(self.contract,[SourceGrant(self.identity,('STIMULUS',),
            tuple(dict.fromkeys((self.open_link,self.link))))])
        test=self
        class ExplicitConfigurationDouble(module.ModelConfigurationBackend):
            """No real model, resource preparation or target qualification is implied."""
            def read_context(self, identity, request_json, *, now_ns):
                self.read_calls+=1
                if self.read_hook is not None:
                    return self.read_hook(identity,request_json,now_ns)
                self.context=replace(self.context,request_json=request_json)
                return self.context
            def apply_configuration(self, request_json, context, *, now_ns):
                self.write_calls+=1
                self.original_writes.append(request_json)
                if self.write_hook is not None:
                    return self.write_hook(request_json,context,now_ns)
                return self.receipt
        self.backend=ExplicitConfigurationDouble(self.contract,(model,))
        self.backend.read_calls=self.backend.write_calls=0
        self.backend.original_writes=[]
        self.backend.read_hook=self.backend.write_hook=None
        view=ModelView(model,'STOPPED',10,600000,'NONE',False,True)
        self.backend.context=module.ModelConfigurationContext(canonicalize(self.identity),b'{}',view,None,0,240000000)
        self.service=module.ModelConfigurationService(self.contract,self.registry,self.backend,
            clock=lambda:test.now,**limits)
        status=None
        if with_status:
            from icd_gateway.status_service import ModelStatusBackend,ModelStatusSample,ModelStatusService
            class StatusDouble(ModelStatusBackend):
                def read_status(self,identity,*,now_ns):
                    if self.read_hook is not None:
                        self.read_hook()
                    payload={**message(131)['payload'],'state':'STOPPED','model_step':10,'control_source':'NONE'}
                    return ModelStatusSample(canonicalize(identity),canonicalize(payload),now_ns,now_ns+240000000)
            self.status_backend=StatusDouble(self.contract,(model,))
            self.status_backend.read_hook=None
            status=ModelStatusService(self.contract,self.registry,self.status_backend,clock=lambda:test.now)
        self.receiver=Receiver(self.contract,self.registry,configuration_service=self.service if installed else None,
                               status_service=status)
        self.wire=WireCodec(self.contract)
        opening=message(1)
        opening['payload']['identity']=self.identity
        self.opened=self.deliver(opening,link=self.open_link)
        self.sid=self.opened[0]['payload']['session_id']
        self.request=message(3)
        self.request['header'].update(session_id=self.sid,sequence=2,transaction_id=2,target_step=10)
        config=self.request['payload']
        config.update(model_id=model,terrain_resource_sha256=None,obstacle_resource_sha256=None)
        initial=config['initial_inputs']
        initial['model_id']=model
        if model!='quadrotor_hil':
            for key,mid in zip(('flight_control','fault','parameters'),
                              (8,12,18) if model=='multirotor_6_hil' else (9,13,19)):
                initial[key]=message(mid)['payload']
            for key,value in initial['flight_control'].items():
                initial['flight_control'][key]=[0]*len(value) if type(value) is list else 0
        self.backend.receipt=module.ModelConfigurationReceipt(canonicalize(self.identity),
            canonicalize(self.request),canonicalize(config),canonicalize(config['initial_state']),
            canonicalize(initial),replace(view,state='CONFIGURED',configured_once=True,
                max_duration_steps=config['max_duration_steps']),7,0,240000000)
        self.backend.context=replace(self.backend.context,request_json=canonicalize(self.request))
        return self.service

    def deliver(self, request, *, link=None, now=None):
        if now is not None:
            self.now=now
        link=self.link if link is None else link
        replies=()
        for raw in self.wire.encode(request,link.transport):
            replies=self.receiver.receive(raw,link,now_ns=self.now)
        return replies

    def test_default_receiver_does_not_publish_or_apply_configuration(self):
        self.create(installed=False)
        caps=self.opened[0]['payload']['capabilities']
        self.assertNotIn(3,caps['implemented_message_ids'])
        self.assertNotIn('consumer.RunConfigure',caps['available_probes'])
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'TARGET_MISSING')
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))

    def test_installed_capability_is_only_consumer_not_hardware_qualification(self):
        service=self.create()
        caps=self.opened[0]['payload']['capabilities']
        self.assertEqual(caps['implemented_message_ids'],[1,3])
        self.assertEqual(caps['available_probes'],['consumer.RunConfigure'])
        for name in ('initialization_port_ready','system_model_ready','replacement_ready'):
            self.assertFalse(caps[name])
        self.assertFalse(service.execution_ready)
        self.assertEqual(service.qualification_status,'NOT_EVALUATED')

    def test_complete_three_model_receipts_on_frozen_udp_transport(self):
        for model in ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil'):
            for transport in ('UDP',):
                with self.subTest(model=model,transport=transport):
                    service=self.create(model=model,transport=transport)
                    replies=self.deliver(self.request)
                    self.assertEqual([r['payload']['stage'] for r in replies],['RECEIVED','APPLIED'])
                    payload=replies[-1]['payload']
                    self.assertEqual((payload['error'],payload['applied_step'],payload['model_revision'],payload['probe_id']),
                                     ('OK',10,7,1003))
                    self.assertEqual(loads(service.records[-1].reply_json),replies[-1])
                    self.assertIs(service.records[-1].receipt,self.backend.receipt)
                    self.assertTrue(service.records[-1].write_attempted)
                    self.assertEqual(self.backend.original_writes,[canonicalize(self.request)])

    def test_configuration_keeps_frozen_udp_only_transport(self):
        self.create(transport='CANFD')
        self.rejects('UNSUPPORTED',lambda:self.deliver(self.request))
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))

    def test_exact_retry_keeps_original_terminal_feedback_without_read_write_or_renewal(self):
        service=self.create()
        original=self.deliver(self.request)
        deadline=self.registry._sessions[self.sid].deadline_ns
        self.backend.receipt=None
        self.assertEqual(self.deliver(self.request,now=1),original)
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(1,1))
        self.assertEqual(len(service.records),1)
        self.assertEqual(self.registry._sessions[self.sid].deadline_ns,deadline)

    def test_invalid_semantics_reject_before_write_and_keep_context(self):
        for change,error in (({'state':'RUNNING'},'STATE'),({'configured_once':True,'state':'CONFIGURED'},'STATE'),
                             ({'model_step':11},'STATE'),({'model_id':'fixed_wing_hil'},'MODEL')):
            with self.subTest(change=change):
                service=self.create()
                self.backend.context=replace(self.backend.context,view=replace(self.backend.context.view,**change))
                replies=self.deliver(self.request)
                self.assertEqual(replies[-1]['payload']['error'],error)
                self.assertEqual(self.backend.write_calls,0)
                self.assertIs(service.records[-1].context,self.backend.context)
                self.assertFalse(service.records[-1].write_attempted)

    def test_unsafe_initial_input_and_unresolved_terrain_cannot_write(self):
        for kind,error in (('control','SAFETY'),('terrain','RESOURCE'),('quaternion','RANGE')):
            with self.subTest(kind=kind):
                service=self.create()
                if kind=='control':
                    self.request['payload']['initial_inputs']['flight_control']['motor_command'][0]=0.5
                elif kind=='terrain':
                    self.request['payload']['terrain_resource_sha256']='a'*64
                else:
                    self.request['payload']['initial_state']['orientation']['q_w']=0.5
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],error)
                self.assertEqual(self.backend.write_calls,0)
                self.assertIsNone(service.records[-1].receipt)

    def test_applied_configuration_state_and_input_readback_must_match_every_field(self):
        for field in ('configuration_json','initial_state_json','initial_inputs_json'):
            with self.subTest(field=field):
                service=self.create()
                receipt=self.backend.receipt
                raw=loads(getattr(receipt,field))
                if field=='configuration_json':
                    raw['random_seed']+=1
                elif field=='initial_state_json':
                    raw['velocity_n_mps']+=0.1
                else:
                    raw['environment']['wind_n_mps']+=1
                self.backend.receipt=replace(receipt,**{field:canonicalize(raw)})
                replies=self.deliver(self.request)
                self.assertEqual(replies[-1]['payload']['error'],'BUSINESS_FAILED')
                self.assertEqual(replies[-1]['payload']['probe_id'],0)
                self.assertTrue(service.records[-1].write_attempted)
                self.assertIs(service.records[-1].receipt,self.backend.receipt)

    def test_wrong_original_request_or_receipt_identity_cannot_mint_applied(self):
        for field in ('request_json','identity_json'):
            with self.subTest(field=field):
                self.create()
                raw=loads(getattr(self.backend.receipt,field))
                if field=='request_json':
                    raw['header']['sequence']+=1
                else:
                    raw['run_id']='other'
                self.backend.receipt=replace(self.backend.receipt,**{field:canonicalize(raw)})
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'MODEL' if field=='identity_json' else 'DUPLICATE')

    def test_invalid_raw_readback_is_retained_and_failure_retry_never_rewrites(self):
        service=self.create()
        self.backend.receipt=replace(self.backend.receipt,initial_inputs_json=b'not-json')
        first=self.deliver(self.request)
        self.assertEqual(first[-1]['payload']['error'],'SCHEMA')
        self.assertEqual(service.records[-1].receipt.initial_inputs_json,b'not-json')
        self.assertIsNone(service.records[-1].reply_json)
        self.assertEqual(self.deliver(self.request),first)
        self.assertEqual(self.backend.write_calls,1)

    def test_context_expiry_during_getter_cannot_write(self):
        service=self.create()
        def slow(identity,request_json,now):
            self.now=240000000
            return self.backend.context
        self.backend.read_hook=slow
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'EXPIRED')
        self.assertEqual(self.backend.write_calls,0)
        self.assertEqual(service.records[-1].completed_ns,240000000)

    def test_requested_terrain_origin_and_initial_point_reach_getter_before_write(self):
        service=self.create()
        config=self.request['payload']
        config['terrain_resource_sha256']='a'*64
        config['origin'].update(latitude_deg=30,longitude_deg=120,height_ellipsoid_m=100)
        config['initial_state']['position'].update(north_m=123,east_m=456,down_m=-7)
        config['initial_inputs']['environment']['ground_height_m']=7
        self.backend.receipt=replace(self.backend.receipt,request_json=canonicalize(self.request),
            configuration_json=canonicalize(config),initial_state_json=canonicalize(config['initial_state']),
            initial_inputs_json=canonicalize(config['initial_inputs']))
        reads=[]
        def read(identity,request_json=None,*,now_ns):
            reads.append(request_json)
            self.assertEqual(request_json,canonicalize(self.request))
            self.assertEqual(self.backend.write_calls,0)
            self.backend.context=replace(self.backend.context,request_json=request_json,ground_down=-7)
            return self.backend.context
        self.backend.read_context=read
        self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'APPLIED')
        self.assertEqual(reads,[canonicalize(self.request)])
        self.assertEqual(service.records[-1].context.request_json,canonicalize(self.request))

    def test_context_from_another_requested_terrain_or_point_cannot_write(self):
        self.assertIn('request_json',self.module.ModelConfigurationContext.__dataclass_fields__)
        for field in ('terrain','point','origin','sequence'):
            with self.subTest(field=field):
                service=self.create()
                other=loads(canonicalize(self.request))
                if field=='terrain':
                    other['payload']['terrain_resource_sha256']='b'*64
                elif field=='point':
                    other['payload']['initial_state']['position']['north_m']=1
                elif field=='origin':
                    other['payload']['origin']['latitude_deg']=1
                else:
                    other['header']['sequence']+=1
                context=replace(self.backend.context,request_json=canonicalize(other))
                def read(identity,request_json=None,*,now_ns):
                    return context
                self.backend.read_context=read
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'DUPLICATE')
                self.assertEqual(self.backend.write_calls,0)
                self.assertIs(service.records[-1].context,context)

    def test_context_request_and_maximum_failed_receipt_are_reserved_before_getter(self):
        service=self.create(max_bytes=260000)
        self.backend.receipt=replace(self.backend.receipt,identity_json=b'x'*4096,
            request_json=b'x'*69632,configuration_json=b'x'*65536,
            initial_state_json=b'x'*4096,initial_inputs_json=b'x'*65536)
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))
        self.assertEqual(service.records,())

    def test_late_or_throwing_writer_retains_completion_without_claiming_no_effect(self):
        for kind,error in (('late','EXPIRED'),('throw','RESOURCE')):
            with self.subTest(kind=kind):
                service=self.create()
                def write(request,context,now):
                    self.now=240000000
                    if kind=='throw':
                        raise OSError('explicit model failure after possible writes')
                    return self.backend.receipt
                self.backend.write_hook=write
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],error)
                self.assertEqual(service.records[-1].completed_ns,240000000)
                self.assertTrue(service.records[-1].write_attempted)

    def test_owner_replacement_after_context_read_refuses_before_write(self):
        self.create()
        original=self.backend
        def swap(identity,request_json,now):
            self.service.backend=object()
            return original.context
        original.read_hook=swap
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'STATE')
        self.assertEqual(original.write_calls,0)
        self.service.backend=original

    def test_history_reservation_precedes_getter_and_preserves_first_record(self):
        service=self.create(max_records=1)
        self.deliver(self.request)
        original=service.records
        request=loads(canonicalize(self.request))
        request['header'].update(sequence=3,transaction_id=3)
        self.assertEqual(self.deliver(request)[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(1,1))
        self.assertEqual(service.records,original)

    def test_feedback_counter_limit_refuses_write(self):
        self.create()
        self.registry._sessions[self.sid].last_tx=0xffffffff-1
        self.rejects('CAPACITY',lambda:self.deliver(self.request))
        self.assertEqual(self.backend.write_calls,0)

    def test_ordinary_session_layer_still_cannot_forge_consumer_applied(self):
        self.create()
        self.registry.accept(self.request,self.link,now_ns=0)
        reply=self.receiver._ack(3,Header(**self.request['header']),stage='RECEIVED',error='OK')
        reply['payload'].update(stage='APPLIED',applied_step=10,model_revision=7,probe_id=1003)
        self.rejects('STATE',lambda:self.registry.record_response(self.request,(reply,),now_ns=0))

    def test_context_and_receipt_are_strict_immutable_bounded_samples(self):
        self.create()
        with self.assertRaises(FrozenInstanceError):
            self.backend.context.sampled_ns=1
        for changes in ({'sampled_ns':True},{'deadline_ns':0},{'identity_json':bytearray(b'{}')},
                        {'view':{'state':'STOPPED'}},{'request_json':bytearray(b'{}')},
                        {'request_json':b'x'*69633}):
            self.rejects('SCHEMA',lambda:replace(self.backend.context,**changes))
        for changes in ({'model_revision':True},{'model_revision':-1},{'initial_inputs_json':b'x'*65537}):
            self.rejects('SCHEMA',lambda:replace(self.backend.receipt,**changes))

    def test_actual_view_metadata_cannot_escape_bounded_immutable_evidence(self):
        self.create()
        class MutableEnumDouble:
            def __eq__(self,other):
                return True
        for changes in ({'model_id':'x'*1000000},{'state':MutableEnumDouble()},
                        {'control_source':MutableEnumDouble()}):
            with self.subTest(field=next(iter(changes))):
                view=replace(self.backend.context.view,**changes)
                for sample in (self.backend.context,self.backend.receipt):
                    self.rejects('SCHEMA',lambda:replace(sample,view=view))

    def test_missing_backend_and_unhashable_model_ids_are_typed_errors(self):
        self.create()
        self.rejects('TARGET_MISSING',lambda:self.module.ModelConfigurationService(self.contract,self.registry,None))
        self.rejects('MODEL',lambda:type(self.backend)(self.contract,([],)))

    def test_busy_status_cannot_partially_close_installed_configuration_service(self):
        self.create(with_status=True)
        def close_during_read():
            self.rejects('STATE',self.receiver.close)
            self.assertFalse(self.service._closed)
        self.status_backend.read_hook=close_during_read
        heartbeat=message(2)
        heartbeat['header'].update(session_id=self.sid,sequence=2,transaction_id=2,target_step=10)
        self.assertEqual(self.deliver(heartbeat)[-1]['message_id'],131)
        self.assertFalse(self.service._closed)

    def test_byte_budget_refuses_before_read_and_write(self):
        service=self.create(max_bytes=1)
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))
        self.assertEqual(service.records,())

    def test_failed_maximum_receipt_reservation_cannot_exceed_history_budget(self):
        service=self.create(max_bytes=180000)
        self.backend.receipt=replace(self.backend.receipt,identity_json=b'x'*4096,
            request_json=b'x'*69632,configuration_json=b'x'*65536,
            initial_state_json=b'x'*4096,initial_inputs_json=b'x'*65536)
        self.deliver(self.request)
        self.assertLessEqual(service.stored_bytes,service._max_bytes)
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))

    def test_throwing_getter_retains_original_error_and_actual_completion_without_write(self):
        service=self.create()
        def fail(identity,request_json,now):
            self.now=50000000
            raise OSError('actual getter failed')
        self.backend.read_hook=fail
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'RESOURCE')
        record=service.records[-1]
        self.assertEqual(record.completed_ns,50000000)
        self.assertFalse(record.write_attempted)
        self.assertIsNone(record.context)

    def test_real_model_queue_pending_inputs_are_not_silently_discarded_for_configuration(self):
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        from test_model_bindings import declared_runtime
        self.create()
        queue=ModelQueue(self.contract,self.registry,[ModelBindings(self.contract,'quadrotor_hil',
            declared_runtime(self.contract,'quadrotor_hil'))])
        env=message(10)
        env['header'].update(session_id=self.sid,sequence=2,transaction_id=2,target_step=1)
        self.registry.accept(env,self.link,now_ns=0)
        pending=queue.enqueue(env,state='RUNNING',now_ns=0)
        self.backend.context=replace(self.backend.context,view=replace(self.backend.context.view,model_step=0))
        self.request['header'].update(sequence=3,transaction_id=3,target_step=0)
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'STATE')
        self.assertEqual(self.backend.write_calls,0)
        self.assertIs(queue._pending[pending.key],pending)

    def test_forged_direct_configuration_completion_is_refused_outside_original_operation(self):
        self.create()
        self.registry.accept(self.request,self.link,now_ns=0)
        received=self.receiver._ack(3,Header(**self.request['header']),stage='RECEIVED',error='OK')
        applied=self.receiver._ack(3,Header(**self.request['header']),stage='APPLIED',error='OK')
        applied['payload'].update(probe_id=1003,model_revision=7,applied_step=10)
        self.rejects('STATE',lambda:self.registry._record_configuration_response(
            self.request,(received,applied),self.service,now_ns=0))

    def test_receipt_state_control_boundary_and_future_sampling_fail_closed(self):
        for changes,error in (({'state':'RUNNING'},'STATE'),({'configured_once':False},'STATE'),
                              ({'model_step':11},'STATE'),({'control_source':'PX4_SITL'},'STATE')):
            with self.subTest(changes=changes):
                self.create()
                self.backend.receipt=replace(self.backend.receipt,view=replace(self.backend.receipt.view,**changes))
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],error)
        self.create()
        self.backend.receipt=replace(self.backend.receipt,sampled_ns=1)
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'EXPIRED')

    def test_actual_udp_source_receives_original_configuration_consumer_applied(self):
        from test_udp import UDPTests
        from input_simulator.session import SourceSession
        fixture=UDPTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.create_network()
        module=self.module
        identity=message(1)['payload']['identity']
        config=message(3)['payload']
        config.update(terrain_resource_sha256=None,obstacle_resource_sha256=None)
        class ActualBoundaryDouble(module.ModelConfigurationBackend):
            """Actual UDP is real; simulated preparation/readback does not qualify C."""
            def read_context(self, identity, request_json, *, now_ns):
                return module.ModelConfigurationContext(canonicalize(identity),request_json,self.view,None,
                                                        now_ns,now_ns+240000000)
            def apply_configuration(self, original,context, *, now_ns):
                self.calls+=1
                self.view=replace(self.view,state='CONFIGURED',configured_once=True)
                sampled=time.monotonic_ns()
                return module.ModelConfigurationReceipt(canonicalize(identity),original,canonicalize(config),
                    canonicalize(config['initial_state']),canonicalize(config['initial_inputs']),self.view,
                    9,sampled,sampled+240000000)
        backend=ActualBoundaryDouble(fixture.contract,('quadrotor_hil',))
        backend.view=ModelView('quadrotor_hil','STOPPED',0,600000,'NONE',False,False)
        backend.calls=0
        service=module.ModelConfigurationService(fixture.contract,fixture.registry,backend)
        fixture.receiver=Receiver(fixture.contract,fixture.registry,configuration_service=service)
        fixture.gateway.receiver=fixture.receiver
        stop=threading.Event()
        errors=[]
        def run():
            try:
                while not stop.is_set():
                    fixture.gateway.poll(timeout=0.001)
            except Exception as error:
                errors.append(error)
        thread=threading.Thread(target=run)
        thread.start()
        try:
            source=SourceSession(fixture.source,identity,('STIMULUS',))
            source.open()
            reply=source.request({'message_id':3,'payload':config},target_step=0)
            self.assertEqual((reply['payload']['stage'],reply['payload']['probe_id']),('APPLIED',1003))
            self.assertEqual(reply['payload']['model_revision'],9)
            self.assertEqual(loads(service.records[-1].reply_json),reply)
            self.assertEqual(source.records[-1].reply,reply)
            self.assertEqual(backend.calls,1)
            self.assertFalse(source.capabilities['initialization_port_ready'])
            source.close()
        finally:
            stop.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
