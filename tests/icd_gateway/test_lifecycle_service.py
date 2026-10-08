"""Standard lifecycle consumer; every model backend here is an explicit double."""

from dataclasses import FrozenInstanceError, replace
import importlib.util

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from icd_gateway.receiver import Receiver
from icd_gateway.semantic_guards import ModelView
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant


class LifecycleServiceTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('icd_gateway.lifecycle_service'),
                             'original complete Lifecycle consumer is missing')
        from icd_gateway import lifecycle_service
        self.module=lifecycle_service

    def create(self, *, action='START',model='quadrotor_hil',installed=True,transport='UDP',peer_context=None,**limits):
        m=self.module
        self.now=0
        self.identity=message(1)['payload']['identity']
        self.identity['model_id']=model
        self.link=PeerBinding('ETH_0','UDP','127.0.0.1:36602')
        self.data_link=self.link if transport=='UDP' else PeerBinding('CANFD_0','CANFD','can0')
        grants=[SourceGrant(self.identity,('STIMULUS',),tuple(dict.fromkeys((self.link,self.data_link))))]
        if peer_context is not None:
            self.peer_identity={**self.identity,'source_id':'second-source',**peer_context}
            self.peer_link=PeerBinding('ETH_0','UDP','127.0.0.1:36603')
            grants.append(SourceGrant(self.peer_identity,('STIMULUS',),(self.peer_link,)))
        self.registry=SessionRegistry(self.contract,grants)
        test=self
        class ExplicitLifecycleDouble(m.ModelLifecycleBackend):
            """No C solver, hardware output or real-time qualification is implied."""
            def read_context(self,identity,request_json,*,now_ns):
                self.read_calls+=1
                if self.read_hook is not None:
                    return self.read_hook(identity,request_json,now_ns)
                self.context=replace(self.context,request_json=request_json)
                return self.context
            def apply_lifecycle(self,request_json,context,decision,*,now_ns):
                self.write_calls+=1
                self.decisions.append(decision)
                if self.write_hook is not None:
                    return self.write_hook(request_json,context,decision,now_ns)
                test.now=max(test.now,self.receipt.sampled_ns)
                return replace(self.receipt,request_json=request_json)
        self.backend=ExplicitLifecycleDouble(self.contract,(model,))
        self.backend.read_calls=self.backend.write_calls=0
        self.backend.read_hook=self.backend.write_hook=None
        self.backend.decisions=[]
        self.service=m.ModelLifecycleService(self.contract,self.registry,self.backend,clock=lambda:test.now,**limits)
        self.receiver=Receiver(self.contract,self.registry,lifecycle_service=self.service if installed else None)
        opening=message(1)
        opening['payload']['identity']=self.identity
        self.opened=self.deliver(opening)
        self.sid=self.opened[0]['payload']['session_id']
        if peer_context is not None:
            peer=message(1)
            peer['payload']['identity']=self.peer_identity
            peer['payload']['nonce_hex']='b'*32
            self.peer_sid=self.deliver(peer,link=self.peer_link)[0]['payload']['session_id']
        config=message(3)['payload']
        config.update(model_id=model,terrain_resource_sha256=None,obstacle_resource_sha256=None)
        if model!='quadrotor_hil':
            for field,mid in zip(('flight_control','fault','parameters'),
                                 (8,12,18) if model=='multirotor_6_hil' else (9,13,19)):
                config['initial_inputs'][field]=message(mid)['payload']
            for key,value in config['initial_inputs']['flight_control'].items():
                config['initial_inputs']['flight_control'][key]=[0]*len(value) if type(value) is list else 0
        config['initial_inputs']['model_id']=model
        state={'START':'CONFIGURED','PAUSE':'RUNNING','RESUME':'PAUSED','STOP':'PAUSED',
               'RESET':'STOPPED','STEP':'PAUSED'}[action]
        view=ModelView(model,state,10,config['max_duration_steps'],'NONE',False,True)
        actual=message(132)['payload']
        actual.update(model_step=10,vn_mps=2)
        actual['position']['north_m']=3
        inputs=loads(canonicalize(config['initial_inputs']))
        inputs['environment']['wind_n_mps']=9
        self.config=config
        self.request=message(4)
        self.request['header'].update(session_id=self.sid,sequence=2,transaction_id=2,
                                      target_step=11 if state=='RUNNING' else 10)
        self.request['payload']={'action':action,'expected_state':state,
            'reset_policy':'NEW_SESSION_RESTORE_INITIAL' if action=='RESET' else 'NOT_APPLICABLE'}
        if action=='STEP':
            self.request['payload']['step_count']=3
        self.backend.context=m.ModelLifecycleContext(canonicalize(self.identity),canonicalize(self.request),
            canonicalize(config),canonicalize(actual),canonicalize(inputs),view,0,240000000)
        end={'START':'RUNNING','PAUSE':'PAUSED','RESUME':'RUNNING','STOP':'STOPPED',
             'RESET':'CONFIGURED','STEP':'PAUSED'}[action]
        step=0 if action=='RESET' else 13 if action=='STEP' else self.request['header']['target_step']
        actual=loads(canonicalize(actual))
        actual['model_step']=step
        if action=='RESET':
            initial=config['initial_state']
            for key in ('position','orientation','p_radps','q_radps','r_radps','airborne'):
                actual[key]=initial[key]
            for axis in ('n','e','d'):
                actual[f'v{axis}_mps']=initial[f'velocity_{axis}_mps']
            inputs=config['initial_inputs']
        self.actuators=loads(canonicalize(config['initial_inputs']['flight_control']))
        steps=[]
        if action=='STEP':
            for number in range(11,14):
                sample=loads(canonicalize(actual))
                sample['model_step']=number
                steps.append(m.ModelLifecycleStep(canonicalize(sample),canonicalize(self.actuators),
                                                   (number-10)*1000000,1000))
        sampled=3000000 if action=='STEP' else 0
        self.backend.receipt=m.ModelLifecycleReceipt(canonicalize(self.identity),canonicalize(self.request),
            canonicalize(config),canonicalize(actual),canonicalize(inputs),replace(view,state=end,model_step=step),
            canonicalize(self.actuators),0,0,tuple(steps),7,sampled,sampled+240000000)
        return self.service

    def deliver(self, value, *, link=None):
        binding=link or self.link
        replies=()
        for packet in self.receiver.wire.encode(value,binding.transport):
            replies=self.receiver.receive(packet,binding,now_ns=self.now)
        return replies

    def test_missing_consumer_does_not_publish_or_write(self):
        self.create(installed=False)
        self.assertNotIn(4,self.opened[0]['payload']['capabilities']['implemented_message_ids'])
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'TARGET_MISSING')
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))

    def test_all_three_models_and_six_actions_have_correlated_applied_readback(self):
        for model in ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil'):
            for action in ('START','PAUSE','RESUME','STOP','RESET','STEP'):
                with self.subTest(model=model,action=action):
                    self.create(model=model,action=action)
                    replies=self.deliver(self.request)
                    self.assertEqual([r['payload']['stage'] for r in replies],['RECEIVED','APPLIED'])
                    self.assertEqual(replies[-1]['payload']['probe_id'],1004)
                    self.assertEqual(replies[-1]['payload']['applied_step'],self.backend.receipt.view.model_step)
                    record=self.service.records[-1]
                    self.assertEqual(loads(record.reply_json),replies[-1])
                    self.assertTrue(record.write_attempted)
                    self.assertEqual(self.sid not in self.registry.session_ids,action in ('RESET','RESUME'))
                    self.assertEqual((self.backend.read_calls,self.backend.write_calls),(1,1))

    def test_capability_is_only_consumer_not_model_or_hardware_qualification(self):
        self.create()
        caps=self.opened[0]['payload']['capabilities']
        self.assertEqual(caps['implemented_message_ids'],[1,4])
        self.assertEqual(caps['available_probes'],['consumer.Lifecycle'])
        self.assertFalse(caps['replacement_ready'])
        self.assertFalse(caps['initialization_port_ready'])
        self.assertFalse(self.service.execution_ready)
        self.assertEqual(self.service.qualification_status,'NOT_EVALUATED')

    def test_lifecycle_preserves_frozen_udp_only_transport(self):
        self.create(transport='CANFD')
        self.rejects('UNSUPPORTED',lambda:self.deliver(self.request,link=self.data_link))
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))

    def queue_input(self):
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        from test_model_bindings import declared_runtime
        model=self.identity['model_id']
        self.queue=ModelQueue(self.contract,self.registry,[ModelBindings(self.contract,model,
            declared_runtime(self.contract,model))])
        self.queue._steps[model]=10
        value=message(10)
        value['header'].update(session_id=self.sid,sequence=2,transaction_id=2,target_step=15)
        self.registry.accept(value,self.link,now_ns=0)
        self.pending=self.queue.enqueue(value,state='RUNNING',now_ns=0)
        self.request['header'].update(sequence=3,transaction_id=3)

    def test_live_retry_is_original_and_never_rereads_rewrites_or_renews(self):
        self.create()
        replies=self.deliver(self.request)
        deadline=self.registry._sessions[self.sid].deadline_ns
        self.now=1
        self.backend.receipt=None
        self.assertEqual(self.deliver(self.request),replies)
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(1,1))
        self.assertEqual(self.registry._sessions[self.sid].deadline_ns,deadline)

    def test_reset_requires_complete_initial_state_and_every_initial_input(self):
        for field in ('state_json','inputs_json'):
            with self.subTest(field=field):
                self.create(action='RESET')
                raw=loads(getattr(self.backend.receipt,field))
                if field=='state_json':
                    raw['position']['north_m']+=1
                else:
                    raw['sensor_fault']['gps_valid']=False
                self.backend.receipt=replace(self.backend.receipt,**{field:canonicalize(raw)})
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'BUSINESS_FAILED')
                self.assertIn(self.sid,self.registry.session_ids)
                self.assertTrue(self.service.records[-1].write_attempted)

    def test_resume_preserves_complete_paused_state_and_confirmed_inputs(self):
        for field in ('state_json','inputs_json'):
            with self.subTest(field=field):
                self.create(action='RESUME')
                raw=loads(getattr(self.backend.receipt,field))
                if field=='state_json':
                    raw['electrical_voltage_v']+=1
                else:
                    raw['environment']['wind_n_mps']+=1
                self.backend.receipt=replace(self.backend.receipt,**{field:canonicalize(raw)})
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'BUSINESS_FAILED')
                self.assertIn(self.sid,self.registry.session_ids)

    def test_safety_uses_actual_outputs_owner_and_receive_queue_readback(self):
        for field,raw,error in (('actuators_json',canonicalize(message(14)['payload']),'SAFETY'),
                               ('owner_session_id',1,'CONTROL_OWNER'),('receive_queue_depth',1,'STATE')):
            with self.subTest(field=field):
                self.create(action='STOP')
                self.backend.receipt=replace(self.backend.receipt,**{field:raw})
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],error)
                self.assertIsNotNone(self.service.records[-1].receipt)

    def test_step_requires_every_exact_sequential_observation_and_solver_step(self):
        for case in ('missing','order','clock','solver'):
            with self.subTest(case=case):
                self.create(action='STEP')
                steps=list(self.backend.receipt.steps)
                if case=='missing':
                    steps.pop()
                elif case=='order':
                    steps[1]=steps[0]
                elif case=='clock':
                    steps[1]=replace(steps[1],sampled_ns=steps[0].sampled_ns)
                else:
                    steps[1]=replace(steps[1],step_us=2000)
                self.backend.receipt=replace(self.backend.receipt,steps=tuple(steps))
                self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'FAILED')
                self.assertTrue(self.service.records[-1].write_attempted)

    def test_offline_solver_steps_do_not_require_one_ms_host_sleep(self):
        self.create(action='STEP')
        self.backend.receipt=replace(self.backend.receipt,steps=tuple(replace(s,sampled_ns=index+1)
            for index,s in enumerate(self.backend.receipt.steps)),sampled_ns=3,deadline_ns=240000003)
        self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'APPLIED')

    def test_state_expected_target_configuration_and_physical_checks_precede_write(self):
        for changes,error in (({'state':'STOPPED'},'STATE'),({'model_step':11},'STATE'),
                              ({'configured_once':False},'STATE'),({'physical_closed_loop':True},'UNSUPPORTED'),
                              ({'control_source':'PX4_SITL'},'CONTROL_OWNER')):
            with self.subTest(changes=changes):
                self.create(action='STEP')
                view=replace(self.backend.context.view,**changes)
                state=loads(self.backend.context.state_json)
                state['model_step']=view.model_step
                self.backend.context=replace(self.backend.context,view=view,state_json=canonicalize(state))
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],error)
                self.assertEqual(self.backend.write_calls,0)

    def test_other_same_model_run_rejects_before_write_or_local_deletion(self):
        self.create(action='RESET',peer_context={'run_id':'foreign-run'})
        before=self.registry.session_ids
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'CONTROL_OWNER')
        self.assertEqual(self.backend.write_calls,0)
        self.assertEqual(self.registry.session_ids,before)

    def test_same_group_all_old_sources_retire_but_other_model_source_survives(self):
        self.create(action='RESET',peer_context={})
        original=tuple(self.registry.session_ids)
        replies=self.deliver(self.request)
        self.assertEqual(replies[-1]['payload']['stage'],'APPLIED')
        self.assertEqual(self.registry.session_ids,())
        self.assertEqual(self.service.records[-1].retirement.retired_sessions,original)
        self.create(action='RESET',peer_context={'model_id':'fixed_wing_hil'})
        self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'APPLIED')
        self.assertEqual(self.registry.session_ids,(self.peer_sid,))

    def test_queue_and_fragments_captured_before_reset_and_real_step_floor_synchronized(self):
        self.create(action='RESET')
        self.queue_input()
        partial=message(3)
        partial['header'].update(session_id=self.sid,sequence=25,transaction_id=25,target_step=10)
        self.receiver.receive(self.receiver.wire.encode(partial,'UDP')[0],self.link,now_ns=0)
        self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'APPLIED')
        record=self.service.records[-1]
        self.assertEqual(record.captured_inputs,(self.pending,))
        self.assertEqual(record.discarded_inputs,(self.pending,))
        self.assertEqual(len(record.captured_groups),1)
        self.assertEqual(record.captured_groups,record.discarded_groups)
        self.assertEqual(self.queue.count,0)
        self.assertEqual(self.queue._steps['quadrotor_hil'],0)

    def test_pause_clears_original_queue_without_retiring_session_or_resetting_step(self):
        self.create(action='PAUSE')
        self.queue_input()
        self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'APPLIED')
        self.assertIn(self.sid,self.registry.session_ids)
        self.assertEqual(self.queue.count,0)
        self.assertEqual(self.queue._steps['quadrotor_hil'],11)
        self.assertIsNone(self.service.records[-1].retirement)

    def test_history_capacity_and_retirement_capacity_reject_before_effect(self):
        for limits in ({'max_records':1},{'max_bytes':1}):
            with self.subTest(limits=limits):
                self.create(**limits)
                if limits.get('max_records'):
                    self.deliver(self.request)
                    self.request['header'].update(sequence=3,transaction_id=3)
                    self.request['payload'].update(action='PAUSE',expected_state='RUNNING')
                    self.request['header']['target_step']=11
                reads,writes=self.backend.read_calls,self.backend.write_calls
                self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'BUFFER_FULL')
                self.assertEqual((self.backend.read_calls,self.backend.write_calls),(reads,writes))
        self.create(action='RESET')
        self.receiver._run_byte_capacity=1
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'BUFFER_FULL')
        self.assertEqual(self.backend.write_calls,0)
        self.assertIn(self.sid,self.registry.session_ids)

    def test_getter_and_writer_expiry_preserve_context_receipt_and_actual_completion(self):
        for phase in ('read','write'):
            with self.subTest(phase=phase):
                self.create(action='RESET')
                if phase=='read':
                    def late_read(identity,raw,now):
                        self.now=240000000
                        return replace(self.backend.context,request_json=raw)
                    self.backend.read_hook=late_read
                else:
                    def late_write(raw,context,decision,now):
                        self.now=1000000000
                        return replace(self.backend.receipt,request_json=raw)
                    self.backend.write_hook=late_write
                reply=self.deliver(self.request)[-1]
                self.assertEqual(reply['payload']['stage'],'FAILED')
                record=self.service.records[-1]
                self.assertEqual(record.completed_ns,self.now)
                self.assertIsNotNone(record.context)
                self.assertEqual(record.write_attempted,phase=='write')
                self.assertIn(self.sid,self.registry.session_ids)

    def test_writer_exception_keeps_original_inputs_and_never_retries_effects(self):
        self.create(action='STOP')
        self.queue_input()
        def failure(raw,context,decision,now):
            self.now=20000000
            raise OSError('model effect may have happened')
        self.backend.write_hook=failure
        replies=self.deliver(self.request)
        self.assertEqual(replies[-1]['payload']['error'],'RESOURCE')
        record=self.service.records[-1]
        self.assertTrue(record.write_attempted)
        self.assertEqual(record.completed_ns,20000000)
        self.assertIs(self.queue._pending[self.pending.key],self.pending)
        self.assertEqual(self.deliver(self.request),replies)
        self.assertEqual(self.backend.write_calls,1)

    def test_invalid_full_context_or_receipt_does_not_produce_application_probe(self):
        for field in ('configuration_json','state_json','inputs_json'):
            for phase in ('context','receipt'):
                with self.subTest(field=field,phase=phase):
                    self.create(action='RESET')
                    value=getattr(self.backend,phase)
                    setattr(self.backend,phase,replace(value,**{field:b'not-json'}))
                    reply=self.deliver(self.request)[-1]
                    self.assertEqual((reply['payload']['stage'],reply['payload']['probe_id']),('FAILED',0))
                    self.assertEqual(self.backend.write_calls,0 if phase=='context' else 1)

    def test_reentrant_receiver_operations_and_close_are_rejected_during_backend(self):
        self.create()
        def read(identity,raw,now):
            self.rejects('STATE',lambda:self.receiver.tick(now_ns=now))
            self.rejects('STATE',lambda:self.receiver.retire_run(self.sid,now_ns=now))
            self.rejects('STATE',lambda:self.receiver.retire_session(self.sid))
            self.rejects('STATE',self.receiver.drain_maintenance)
            self.rejects('STATE',self.receiver.close)
            self.rejects('STATE',self.service.close)
            return replace(self.backend.context,request_json=raw)
        self.backend.read_hook=read
        self.assertEqual(self.deliver(self.request)[-1]['payload']['stage'],'APPLIED')
        self.assertFalse(self.receiver._closed)

    def test_changed_backend_or_queue_fails_and_keeps_original_effect_provenance(self):
        self.create(action='RESET')
        self.queue_input()
        def replace_after_write(raw,context,decision,now):
            self.registry._model_queue=object()
            return replace(self.backend.receipt,request_json=raw)
        self.backend.write_hook=replace_after_write
        self.assertEqual(self.deliver(self.request)[-1]['payload']['error'],'STATE')
        self.assertTrue(self.service.records[-1].write_attempted)
        self.assertEqual(self.service.records[-1].discarded_inputs,())
        self.assertIn(self.sid,self.registry.session_ids)

    def test_immutable_snapshots_and_history_survive_service_close(self):
        self.create()
        self.deliver(self.request)
        record=self.service.records[-1]
        with self.assertRaises(FrozenInstanceError):
            record.completed_ns=1
        for change in ({'sampled_ns':True},{'deadline_ns':2**64},{'identity_json':bytearray(b'{}')},
                       {'view':replace(self.backend.context.view,state=type('S',(str,),{})('CONFIGURED'))}):
            self.rejects('SCHEMA',lambda:replace(self.backend.context,**change))
        self.service.close()
        self.assertEqual(self.service.records,(record,))

    def test_ordinary_registry_cannot_forge_applied_lifecycle(self):
        from icd_runtime.wire import Header
        self.create()
        self.registry.accept(self.request,self.link,now_ns=0)
        received=self.receiver._ack(4,Header(**self.request['header']),stage='RECEIVED',error='OK')
        applied=self.receiver._ack(4,Header(**self.request['header']),stage='APPLIED',error='OK')
        applied['payload'].update(probe_id=1004,applied_step=10)
        self.rejects('STATE',lambda:self.registry.record_response(self.request,(received,applied),now_ns=0))
        self.rejects('STATE',lambda:self.registry._record_lifecycle_response(
            self.request,(received,applied),self.service,now_ns=0))

    def test_wrong_received_ack_is_rejected_before_any_backend_effect(self):
        from icd_runtime.wire import Header
        self.create(action='RESET')
        self.registry.accept(self.request,self.link,now_ns=0)
        received=self.receiver._ack(4,Header(**self.request['header']),stage='RECEIVED',error='OK')
        received['payload']['request_sequence']+=1
        self.rejects('STATE',lambda:self.service.respond(self.request,received,now_ns=0))
        self.assertEqual((self.backend.read_calls,self.backend.write_calls),(0,0))
        self.assertIn(self.sid,self.registry.session_ids)

    def test_start_requires_valid_complete_actuator_readback(self):
        self.create(action='START')
        self.backend.receipt=replace(self.backend.receipt,actuators_json=b'not-json')
        reply=self.deliver(self.request)[-1]
        self.assertEqual((reply['payload']['stage'],reply['payload']['probe_id']),('FAILED',0))
        self.assertIsNotNone(self.service.records[-1].receipt)

    def test_incomplete_local_cleanup_never_publishes_applied(self):
        for action in ('STOP','RESET'):
            for owner in ('queue','assembler'):
                with self.subTest(action=action,owner=owner):
                    self.create(action=action)
                    self.queue_input()
                    partial=message(3)
                    partial['header'].update(session_id=self.sid,sequence=25,transaction_id=25,target_step=10)
                    self.receiver.receive(self.receiver.wire.encode(partial,'UDP')[0],self.link,now_ns=0)
                    target=self.queue if owner=='queue' else self.receiver.assembler
                    target.discard_session=lambda sid:None
                    reply=self.deliver(self.request)[-1]
                    self.assertEqual((reply['payload']['stage'],reply['payload']['probe_id']),('FAILED',0))
                    record=self.service.records[-1]
                    self.assertEqual(record.error,'STATE')
                    self.assertTrue(record.write_attempted)
                    self.assertEqual(record.discarded_inputs if owner=='queue' else record.discarded_groups,())

    def test_expired_earlier_group_actor_does_not_replace_live_request_origin(self):
        self.create(action='RESET',peer_context={})
        self.request['header']['session_id']=self.peer_sid
        self.backend.context=replace(self.backend.context,identity_json=canonicalize(self.peer_identity))
        self.backend.receipt=replace(self.backend.receipt,identity_json=canonicalize(self.peer_identity),
                                     sampled_ns=2,deadline_ns=240000002)
        self.registry._sessions[self.sid].deadline_ns=1
        def read(identity,raw,now):
            self.now=2
            return replace(self.backend.context,request_json=raw)
        self.backend.read_hook=read
        reply=self.deliver(self.request,link=self.peer_link)[-1]
        self.assertEqual(reply['payload']['stage'],'APPLIED')
        self.assertEqual(self.service.records[-1].retirement.retired_sessions,(self.sid,self.peer_sid))

    def test_actual_udp_source_retires_old_epoch_and_explicitly_opens_current_step(self):
        import threading
        from test_udp import available_port
        from icd_gateway.status_service import ModelStatusBackend, ModelStatusSample, ModelStatusService
        from icd_gateway.udp import UDPGateway
        from input_simulator.session import SourceSession
        from input_simulator.udp_source import UDPSource
        for action in ('RESET','RESUME'):
            with self.subTest(action=action):
                self.create(action=action)
                endpoint=('127.0.0.1',available_port())
                transport=UDPSource(self.contract,source_bind=('127.0.0.1',0),feedback_bind=('127.0.0.1',0),
                                    receiver_endpoint=endpoint,channel='ETH_0')
                link=PeerBinding('ETH_0','UDP',f'127.0.0.1:{transport.source_endpoint[1]}')
                registry=SessionRegistry(self.contract,[SourceGrant(self.identity,('STIMULUS',),(link,))])
                backend=self.backend
                current=[backend.context.view]
                class ExplicitStatusDouble(ModelStatusBackend):
                    def read_status(self,identity,*,now_ns):
                        payload=message(131)['payload']
                        payload.update(state=current[0].state,model_step=current[0].model_step,control_source='NONE')
                        return ModelStatusSample(canonicalize(identity),canonicalize(payload),now_ns,now_ns+240000000)
                def read(identity,raw,now):
                    return replace(backend.context,identity_json=canonicalize(identity),request_json=raw,
                                   sampled_ns=now,deadline_ns=now+240000000)
                def write(raw,context,decision,now):
                    current[0]=backend.receipt.view
                    return replace(backend.receipt,request_json=raw,sampled_ns=now,deadline_ns=now+240000000)
                backend.read_hook,backend.write_hook=read,write
                service=self.module.ModelLifecycleService(self.contract,registry,backend)
                status=ModelStatusService(self.contract,registry,ExplicitStatusDouble(self.contract,backend.model_ids))
                receiver=Receiver(self.contract,registry,status_service=status,lifecycle_service=service)
                gateway=UDPGateway(receiver,bind=endpoint,feedback_routes={link:transport.feedback_endpoint},channel='ETH_0')
                stop=threading.Event()
                errors=[]
                def run():
                    try:
                        while not stop.is_set():
                            gateway.poll(timeout=0.001)
                    except Exception as exc:
                        errors.append(exc)
                thread=threading.Thread(target=run)
                thread.start()
                source=None
                try:
                    source=SourceSession(transport,self.identity,('STIMULUS',))
                    opening=source.open()
                    sid=source.session_id
                    self.assertEqual(opening['payload']['receiver_step'],10)
                    reply=source.request({'message_id':4,'payload':self.request['payload']},target_step=10)
                    self.assertEqual((reply['payload']['stage'],reply['payload']['probe_id']),('APPLIED',1004))
                    self.assertTrue(source._model_clock_retired)
                    self.assertEqual(loads(source._model_epoch_retirement.reply_json),reply)
                    self.assertNotIn(sid,registry.session_ids)
                    self.assertEqual((backend.read_calls,backend.write_calls),(1,1))
                    source.abandon()
                    new=source.open()
                    self.assertNotEqual(source.session_id,sid)
                    self.assertEqual(new['payload']['receiver_step'],0 if action=='RESET' else 10)
                    self.assertFalse(new['payload']['capabilities']['replacement_ready'])
                    self.assertEqual(len(service.records),1)
                finally:
                    if source is not None:
                        source.close()
                    stop.set()
                    thread.join(timeout=2)
                    if not thread.is_alive():
                        gateway.close()
                    transport.close()
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors,[])
