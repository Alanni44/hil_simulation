"""Actual source/native paths with an explicitly labeled target-getter double."""

import importlib
from dataclasses import FrozenInstanceError, replace

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.errors import ICDError
from icd_gateway.semantic_guards import ModelView
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
import test_scenario_driver as driver_cases
from test_scenario import send


class RuntimeTargetTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.runtime_targets'),
                             'actual original target authorization missing')
        self.module=importlib.import_module('input_simulator.runtime_targets')
        self.f=driver_cases.ScenarioDriverTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.status(state='PAUSED')
        self.driver=self.f.build([send('environment',0,10)])
        self.source=self.f.f.f.session
        self.clock=self.f.f.f.clock
        self.identity=loads(self.source._identity_json)
        self.config=message(3)['payload']
        self.sample=self.module.RuntimeTargetSample(canonicalize(self.identity),canonicalize(self.config),
            ModelView('quadrotor_hil','PAUSED',0,600000,'NONE',False,True),
            None,0,'INTERNAL_CONTROLLER','MANUAL',0,self.clock.value,self.clock.value+240_000_000)
        class ActualGetterDouble(self.module.RuntimeTargetBackend):
            """Explicit software getter fixture, not installed in any CLI."""
            def read_target(self, identity, *, now_ns):
                self.calls+=1
                return self.sample
        self.backend=ActualGetterDouble(self.source.contract,('quadrotor_hil',))
        self.backend.calls=0
        self.backend.sample=self.sample

    def authorizer(self, **limits):
        self.targets=self.module.RuntimeTargetAuthorizer(self.f.plan,self.source,self.backend,
                                                        ahead_steps=100,**limits)
        return self.targets

    def action(self):
        return next(self.f.plan.iter_actions())

    def test_actual_paused_context_approves_current_boundary_without_allocation(self):
        targets=self.authorizer()
        before=(self.source._next_sequence,self.source._next_transaction)
        self.assertEqual(targets.approve(self.action(),model_step=0),0)
        self.assertEqual((self.source._next_sequence,self.source._next_transaction),before)
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(targets.records[0].sample,self.sample)
        self.assertEqual(targets.records[0].target_step,0)
        self.assertFalse(targets.execution_ready)

    def test_installed_authorizer_is_used_by_original_driver_before_native_tx(self):
        targets=self.authorizer()
        self.f.services._targets=targets
        # Install in a newly constructed original driver; arbitrary legacy
        # target integers must not override its explicitly installed reader.
        self.driver=self.f.module.OriginalScenarioDriver(self.contract,self.f.plan,self.f.native,self.f.services)
        self.driver.preflight(self.f.plan)
        self.backend.sample=replace(self.sample,identity_json=canonicalize({**self.identity,'run_id':'other'}))
        before=self.source._next_sequence
        self.rejects('MODEL',lambda:self.driver.begin(self.action(),model_step=0))
        self.assertEqual(self.source._next_sequence,before)
        self.assertEqual(self.f.native.records,())
        self.backend.sample=self.sample
        self.driver.begin(self.action(),model_step=0)
        request=self.f.f.eth_request()
        self.assertEqual(request['header']['target_step'],0)
        self.assertEqual(request['payload'],message(10)['payload'])

    def test_complete_frozen_config_context_and_status_agreement_required(self):
        for kind,error in (('identity','MODEL'),('missing_config','SCHEMA'),('model','MODEL'),
                           ('step','CLOCK_UNSYNC'),('state','STATE'),('duration','MODEL')):
            with self.subTest(kind=kind):
                targets=self.authorizer()
                sample=self.sample
                if kind=='identity':
                    sample=replace(sample,identity_json=canonicalize({**self.identity,'source_id':'other'}))
                elif kind=='missing_config':
                    config=dict(self.config)
                    del config['initial_inputs']
                    sample=replace(sample,configuration_json=canonicalize(config))
                else:
                    changes={'model':{'model_id':'fixed_wing_hil'},'step':{'model_step':1},
                             'state':{'state':'RUNNING'},'duration':{'max_duration_steps':10}}[kind]
                    sample=replace(sample,view=replace(sample.view,**changes))
                self.backend.sample=sample
                self.rejects(error,lambda:targets.approve(self.action(),model_step=0))
                self.assertEqual(targets.records[-1].error,error)
                self.assertIs(targets.records[-1].sample,sample)
                self.backend.sample=self.sample

    def test_invalid_half_open_times_and_source_changed_during_getter_refuse(self):
        targets=self.authorizer()
        self.backend.sample=replace(self.sample,sampled_ns=self.clock.value+1)
        self.rejects('EXPIRED',lambda:targets.approve(self.action(),model_step=0))
        self.backend.sample=self.sample
        def slow(identity, *, now_ns):
            self.clock.value+=240_000_000
            return self.sample
        self.backend.read_target=slow
        self.rejects('EXPIRED',lambda:targets.approve(self.action(),model_step=0))
        self.assertIs(targets.records[-1].sample,self.sample)
        self.assertEqual(targets.records[-1].completed_ns,self.clock.value)

    def test_pre_read_count_and_byte_limits_keep_original_prefix(self):
        targets=self.authorizer(max_records=1)
        targets.approve(self.action(),model_step=0)
        original=targets.records
        self.rejects('BUFFER_FULL',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(targets.records,original)
        targets=self.authorizer(max_bytes=1)
        self.rejects('BUFFER_FULL',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(targets.records,())

    def test_no_default_backend_and_snapshot_immutable_strict_types(self):
        self.rejects('TARGET_MISSING',lambda:self.module.RuntimeTargetAuthorizer(self.f.plan,self.source,None,ahead_steps=1))
        with self.assertRaises(TypeError):
            self.module.RuntimeTargetBackend(self.source.contract,('quadrotor_hil',))
        with self.assertRaises(FrozenInstanceError):
            self.sample.owner_session_id=12
        for changes in ({'owner_session_id':True},{'sampled_ns':False},{'deadline_ns':1.0},
                        {'configuration_json':b'x'*65537},{'owner_lane':'wrong'}):
            self.rejects('SCHEMA',lambda:replace(self.sample,**changes))

    def test_backend_failure_and_replacement_never_approve_or_lose_history(self):
        targets=self.authorizer()
        def fail(identity, *, now_ns):
            raise OSError('explicit getter disconnected')
        self.backend.read_target=fail
        self.rejects('RESOURCE',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual(targets.records[-1].error,'RESOURCE')
        targets.backend=type(self.backend)(self.source.contract,('quadrotor_hil',))
        before=self.source._next_sequence
        self.rejects('STATE',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual(self.source._next_sequence,before)

    def test_running_future_target_is_bounded_by_actual_configured_duration(self):
        self.f.status(state='RUNNING')
        self.backend.sample=replace(self.sample,view=replace(self.sample.view,state='RUNNING'))
        targets=self.authorizer()
        self.assertEqual(targets.approve(self.action(),model_step=0),100)
        config={**self.config,'max_duration_steps':50}
        self.backend.sample=replace(self.backend.sample,configuration_json=canonicalize(config),
                                    view=replace(self.backend.sample.view,max_duration_steps=50))
        self.rejects('RANGE',lambda:targets.approve(self.action(),model_step=0))

    def test_controller_cannot_borrow_same_source_string_without_actual_owner(self):
        self.f.status(state='RUNNING')
        self.driver=self.f.build([send('control',0,7,link_id='CANT')])
        self.backend.sample=replace(self.sample,view=replace(self.sample.view,state='RUNNING'),
            configuration_json=canonicalize({**self.config,'active_channels':['ETH_0','CANFD_0']}))
        targets=self.authorizer(can_sender=self.f.f.sender)
        self.rejects('CONTROL_OWNER',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual(self.source.prepared_inputs,())

    def test_driver_replacement_of_explicit_authorizer_is_rejected_before_tx(self):
        targets=self.authorizer()
        self.f.services._targets=targets
        driver=self.f.module.OriginalScenarioDriver(self.contract,self.f.plan,self.f.native,self.f.services)
        driver.preflight(self.f.plan)
        self.f.services._targets=None
        before=self.source._next_sequence
        self.rejects('STATE',lambda:driver.begin(self.action(),model_step=0))
        self.assertEqual(self.source._next_sequence,before)

    def test_can_requires_actual_selected_sender_before_target_approval(self):
        self.f.build([send('environment',0,10,link_id='CANT')])
        targets=self.authorizer()
        self.rejects('TARGET_MISSING',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual(self.source.prepared_inputs,())

    def test_unhashable_action_and_backend_model_are_typed_rejections(self):
        targets=self.authorizer()
        self.rejects('STATE',lambda:targets.approve(replace(self.action(),event_id=[]),model_step=0))
        self.assertEqual(self.backend.calls,0)
        self.rejects('MODEL',lambda:type(self.backend)(self.source.contract,([],)))

    def test_selected_can_channel_must_be_active_and_original_binding_retained(self):
        self.f.build([send('environment',0,10,link_id='CANT')])
        targets=self.authorizer(can_sender=self.f.f.sender)
        self.rejects('AUTHORIZATION',lambda:targets.approve(self.action(),model_step=0))
        self.backend.sample=replace(self.sample,
            configuration_json=canonicalize({**self.config,'active_channels':['ETH_0','CANFD_0']}))
        self.assertEqual(targets.approve(self.action(),model_step=0),0)
        sender=self.f.f.sender
        original=sender.binding
        try:
            sender.binding=replace(original,channel_id='CANFD_1')
            self.rejects('STATE',lambda:targets.approve(self.action(),model_step=0))
        finally:
            sender.binding=original

    def grant_controller(self):
        # Explicit protocol fixture capabilities, not real model qualification.
        caps=self.source.capabilities
        caps['implemented_message_ids']=sorted(set(caps['implemented_message_ids'])|{6})
        caps['available_probes']=sorted(set(caps['available_probes'])|{'consumer.ControlOwner'})
        self.source._capabilities_json=canonicalize(caps)
        owner=self.f.f.owner
        payload={**message(6)['payload'],'source':'PX4_SITL','role':'CONTROLLER',
                 'input_lane':'FLIGHT_CONTROL','mode':'MANUAL'}
        owner.submit({'message_id':6,'payload':payload},target_step=0)
        owner.poll()
        request=self.f.f.eth_request()
        reply=message(130)
        self.f.f.rx_sequence+=1
        reply['header'].update(session_id=self.source.session_id,sequence=self.f.f.rx_sequence,
            transaction_id=request['header']['transaction_id'])
        reply['payload'].update(request_sequence=request['header']['sequence'],request_message_id=6,
            stage='APPLIED',error='OK',applied_step=0,
            probe_id=next(p['id'] for p in self.contract.catalogue['probe_catalog'] if p.get('message_id')==6))
        for raw in self.f.f.f.src.wire.encode(reply,'UDP'):
            self.f.f.f.receiver.sendto(raw,self.f.f.f.src.feedback_endpoint)
        owner.poll()
        header=owner.submit({'message_id':2,'payload':message(2)['payload']},target_step=0)
        owner.poll()
        self.f.f.eth_request()
        reply=message(131)
        self.f.f.rx_sequence+=1
        reply['header'].update(session_id=header.session_id,sequence=self.f.f.rx_sequence,
            transaction_id=header.transaction_id)
        reply['payload'].update(model_step=0,state='PAUSED',control_source='PX4_SITL')
        for raw in self.f.f.f.src.wire.encode(reply,'UDP'):
            self.f.f.f.receiver.sendto(raw,self.f.f.f.src.feedback_endpoint)
        owner.poll()
        link=PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        registry=SessionRegistry(self.contract,(SourceGrant(self.identity,('CONTROLLER',),(link,)),))
        registry._next_id=self.source.session_id
        opening=message(1)
        opening['payload'].update(identity=self.identity,roles=['CONTROLLER'])
        self.assertEqual(registry.accept(opening,link,now_ns=self.clock.value).session_id,self.source.session_id)
        producer=registry.registered_controller(self.identity,now_ns=self.clock.value)
        self.backend.sample=replace(self.sample,producer=producer,owner_session_id=self.source.session_id,
            owner_lane='FLIGHT_CONTROL',control_deadline_ns=self.clock.value+100_000_000,
            configuration_json=canonicalize({**self.config,'controller':'PX4_SITL'}),
            view=replace(self.sample.view,control_source='PX4_SITL'))

    def test_registered_actual_owner_and_standard_applied_lease_allow_controller_only_until_deadline(self):
        self.grant_controller()
        self.f.build([send('control',0,7)])
        targets=self.authorizer()
        before=(self.source._next_sequence,self.source._next_transaction)
        self.assertEqual(targets.approve(self.action(),model_step=0),0)
        good=self.backend.sample
        for changes in ({'owner_session_id':99},{'owner_lane':'ACTUATOR'},{'owner_mode':'AUTO'},
                        {'producer':replace(good.producer,session_id=99)},
                        {'producer':replace(good.producer,roles=('STIMULUS',))}):
            self.backend.sample=replace(good,**changes)
            self.rejects('CONTROL_OWNER',lambda:targets.approve(self.action(),model_step=0))
        self.backend.sample=good
        self.clock.value+=100_000_000
        self.rejects('CONTROL_OWNER',lambda:targets.approve(self.action(),model_step=0))
        self.assertEqual((self.source._next_sequence,self.source._next_transaction),before)

    def test_registered_snapshot_rejects_nested_mutability_and_boolean_deadlines(self):
        self.grant_controller()
        p=self.backend.sample.producer
        for changes in ({'roles':(['CONTROLLER'],)},{'observed_ns':True},
                        {'bindings':(replace(p.bindings[0],peer=[]),)}):
            self.rejects('SCHEMA',lambda:replace(self.backend.sample,producer=replace(p,**changes)))

    def test_driver_rechecks_selected_sender_after_preflight(self):
        targets=self.authorizer(can_sender=self.f.f.sender)
        self.f.services._targets=targets
        driver=self.f.module.OriginalScenarioDriver(self.contract,self.f.plan,self.f.native,self.f.services)
        driver.preflight(self.f.plan)
        original=self.f.native.sender
        try:
            self.f.native.sender=None
            self.rejects('STATE',lambda:driver.begin(self.action(),model_step=0))
            self.assertEqual(self.f.native.records,())
        finally:
            self.f.native.sender=original

    def test_expired_control_during_native_validation_cannot_allocate_or_tx(self):
        self.grant_controller()
        self.f.build([send('control',0,7)])
        targets=self.authorizer()
        self.f.services._targets=targets
        driver=self.f.module.OriginalScenarioDriver(self.contract,self.f.plan,self.f.native,self.f.services)
        driver.preflight(self.f.plan)
        self.clock.value+=99_000_000
        original=self.f.native._validate_action_backend
        def slow(action,target_step):
            original(action,target_step)
            self.clock.value+=1_000_000
        self.f.native._validate_action_backend=slow
        before=(self.source._next_sequence,len(self.f.f.f.src.l2_records))
        handle=driver.begin(self.action(),model_step=0)
        result=driver.poll(handle,model_step=0)
        self.assertEqual((result.state,result.error),('FAILED','CONTROL_OWNER'))
        self.assertEqual((self.source._next_sequence,len(self.f.f.f.src.l2_records)),before)

    def test_approval_cannot_adopt_a_replaced_lease_during_driver_handoff(self):
        self.grant_controller()
        self.f.build([send('control',0,7)])
        targets=self.authorizer()
        self.f.services._targets=targets
        driver=self.f.module.OriginalScenarioDriver(self.contract,self.f.plan,self.f.native,self.f.services)
        driver.preflight(self.f.plan)
        original=driver._observe
        def change(step=None):
            result=original(step)
            if targets.records[-1].action is not None:
                self.source._control_lease=replace(self.source._control_lease,input_lane='ACTUATOR')
            return result
        driver._observe=change
        before=self.source._next_sequence
        handle=driver.begin(self.action(),model_step=0)
        result=driver.poll(handle,model_step=0)
        self.assertEqual((result.state,result.error),('FAILED','CONTROL_OWNER'))
        self.assertEqual(self.source._next_sequence,before)

    def test_expiry_after_allocation_before_fragment_tx_retains_allocation_without_send(self):
        self.grant_controller()
        self.f.build([send('control',0,7)])
        targets=self.authorizer()
        self.f.services._targets=targets
        driver=self.f.module.OriginalScenarioDriver(self.contract,self.f.plan,self.f.native,self.f.services)
        driver.preflight(self.f.plan)
        self.clock.value+=99_000_000
        original=self.f.f.owner.submit
        def slow(*args,**kwargs):
            header=original(*args,**kwargs)
            self.clock.value+=1_000_000
            return header
        self.f.f.owner.submit=slow
        before=(self.source._next_sequence,len(self.f.f.f.src.l2_records))
        handle=driver.begin(self.action(),model_step=0)
        result=driver.poll(handle,model_step=0)
        self.assertEqual((result.state,result.error),('FAILED','CONTROL_OWNER'))
        self.assertEqual(self.source._next_sequence,before[0]+1)
        self.assertEqual(len(self.f.f.f.src.l2_records),before[1])
        self.assertIsNone(self.source._runtime_target_scope)

    def test_allocation_scope_fails_if_another_original_scope_lock_is_held(self):
        targets=self.authorizer()
        action=self.action()
        target=targets.approve(action,model_step=0)
        self.assertTrue(hasattr(self.source,'_runtime_target_lock'),'single source scope lock missing')
        self.source._runtime_target_lock.acquire()
        try:
            def enter():
                with targets.allocation_scope(action,target,self.f.native):
                    self.fail('concurrent scope must not enter')
            self.rejects('STATE',enter)
        finally:
            self.source._runtime_target_lock.release()
