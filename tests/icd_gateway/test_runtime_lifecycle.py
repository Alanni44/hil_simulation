"""Actual native source/feedback; applied model configuration remains a double."""

from dataclasses import FrozenInstanceError, replace

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from input_simulator.model_clock import _remember_feedback
import test_runtime_targets as target_cases
from test_scenario import send


class RuntimeLifecycleTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.f=target_cases.RuntimeTargetTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.source,self.clock=self.f.source,self.f.clock
        caps=self.source.capabilities
        caps['implemented_message_ids']=sorted(set(caps['implemented_message_ids'])|{4})
        caps['available_probes']=sorted(set(caps['available_probes'])|{'consumer.Lifecycle'})
        self.source._capabilities_json=canonicalize(caps)

    def prepare(self, action, state, **fields):
        self.f.f.status(state=state)
        self.f.backend.sample=replace(self.f.sample,view=replace(self.f.sample.view,state=state))
        payload={'action':action,'expected_state':state,
                 'reset_policy':'NEW_SESSION_RESTORE_INITIAL' if action=='RESET' else 'NOT_APPLICABLE',**fields}
        event=send('lifecycle',0,4)
        event['stimulus']={'message_id':4,'payload':payload}
        self.f.f.build([event])
        self.action=next(self.f.f.plan.iter_actions())
        self.targets=self.f.authorizer()
        return self.targets

    def driver(self):
        self.f.f.services._targets=self.targets
        driver=self.f.f.module.OriginalScenarioDriver(self.contract,self.f.f.plan,
            self.f.f.native,self.f.f.services)
        driver.preflight(self.f.f.plan)
        return driver

    def emit(self, request, *, stage='APPLIED', probe=1004):
        native=self.f.f.f
        reply=message(130)
        native.rx_sequence+=1
        reply['header'].update(session_id=self.source.session_id,sequence=native.rx_sequence,
            transaction_id=request['header']['transaction_id'])
        reply['payload'].update(request_message_id=4,request_sequence=request['header']['sequence'],
            stage=stage,error='OK',applied_step=request['header']['target_step'],probe_id=probe)
        for raw in native.f.src.wire.encode(reply,'UDP'):
            native.f.receiver.sendto(raw,native.f.src.feedback_endpoint)
        native.owner.poll()
        return reply

    def test_actual_transition_state_is_checked_before_allocation(self):
        targets=self.prepare('START','PAUSED')
        before=(self.source._next_sequence,self.source._next_transaction)
        self.rejects('STATE',lambda:targets.approve(self.action,model_step=0))
        self.assertEqual((self.source._next_sequence,self.source._next_transaction),before)
        self.assertEqual(targets.records[-1].error,'STATE')

    def test_all_six_actions_keep_the_original_semantic_decision(self):
        cases=(('START','CONFIGURED','RUNNING',()),('PAUSE','RUNNING','PAUSED',()),
               ('STOP','PAUSED','STOPPED',()),('RESUME','PAUSED','RUNNING',()),
               ('RESET','PAUSED','CONFIGURED',()),('STEP','PAUSED','PAUSED',(1,2,3)))
        for action,state,next_state,steps in cases:
            with self.subTest(action=action):
                targets=self.prepare(action,state,**({'step_count':3} if action=='STEP' else {}))
                target=targets.approve(self.action,model_step=0)
                self.assertEqual(target,100 if state=='RUNNING' else 0)
                decision=getattr(targets.records[-1],'lifecycle',None)
                self.assertIsNotNone(decision,'actual frozen LifecycleDecision missing')
                self.assertEqual((decision.next_state,decision.steps),(next_state,steps))
                self.assertEqual(decision.new_session,action in ('RESET','RESUME'))

    def test_offline_step_rejects_physical_loop_and_actual_run_duration(self):
        targets=self.prepare('STEP','PAUSED',step_count=3)
        sample=self.f.backend.sample
        self.f.backend.sample=replace(sample,view=replace(sample.view,physical_closed_loop=True))
        self.rejects('UNSUPPORTED',lambda:targets.approve(self.action,model_step=0))
        self.f.backend.sample=replace(sample,configuration_json=canonicalize({**self.f.config,'max_duration_steps':2}),
            view=replace(sample.view,max_duration_steps=2))
        self.rejects('RANGE',lambda:targets.approve(self.action,model_step=0))

    def test_published_message_without_actual_lifecycle_probe_is_not_ready(self):
        targets=self.prepare('RESET','PAUSED')
        caps=self.source.capabilities
        caps['available_probes'].remove('consumer.Lifecycle')
        self.source._capabilities_json=canonicalize(caps)
        self.rejects('TARGET_MISSING',lambda:targets.preflight(self.f.f.plan))

    def test_stopped_reset_is_management_only_not_permission_for_data(self):
        targets=self.prepare('RESET','STOPPED')
        self.assertEqual(targets.approve(self.action,model_step=0),0)
        self.f.f.build([send('environment',0,10)])
        targets=self.f.authorizer()
        self.rejects('STATE',lambda:targets.approve(next(self.f.f.plan.iter_actions()),model_step=0))

    def test_exact_applied_resume_transaction_can_finish_after_clock_retirement(self):
        self.prepare('RESUME','PAUSED')
        driver=self.driver()
        handle=driver.begin(self.action,model_step=0)
        request=self.f.f.f.eth_request()
        reply=self.emit(request)
        self.rejects('STALE_SESSION',driver.clock.snapshot)
        before=(self.source._next_sequence,self.f.backend.calls)
        result=driver.poll(handle,model_step=0)
        self.assertEqual(result.state,'COMPLETE')
        self.assertEqual((self.source._next_sequence,self.f.backend.calls),before)
        retirement=getattr(self.source,'_model_epoch_retirement',None)
        self.assertIsNotNone(retirement,'original applied retirement provenance missing')
        self.assertEqual((retirement.request_json,retirement.reply_json),
            (canonicalize(request),canonicalize(reply)))
        with self.assertRaises(FrozenInstanceError):
            retirement.request_json=b'{}'
        self.rejects('STALE_SESSION',lambda:driver.begin(self.action,model_step=0))
        self.assertFalse(driver.execution_ready)

    def test_exact_reset_can_finish_but_wrong_step_cannot_use_retirement(self):
        self.prepare('RESET','STOPPED')
        driver=self.driver()
        handle=driver.begin(self.action,model_step=0)
        self.emit(self.f.f.f.eth_request())
        self.rejects('STALE_SESSION',lambda:driver.poll(handle,model_step=1))
        self.assertEqual(driver.poll(handle,model_step=0).state,'COMPLETE')

    def test_first_retirement_is_immutable_and_status_cannot_revive_old_epoch(self):
        self.prepare('RESUME','PAUSED')
        driver=self.driver()
        driver.begin(self.action,model_step=0)
        request=self.f.f.f.eth_request()
        reply=self.emit(request)
        receipt=self.source._model_epoch_retirement
        owner=self.source._dispatcher
        later=loads(canonicalize(request))
        later['header']['sequence']+=1
        later['header']['transaction_id']+=1
        with owner._operation(),self.source._operation(owner=owner):
            _remember_feedback(self.source,later,reply,self.clock.value,self.clock.value,
                transport='UDP',channel=self.source.transport.channel,fresh=True)
        self.assertIs(self.source._model_epoch_retirement,receipt)
        self.f.f.status(state='RUNNING')
        self.rejects('STALE_SESSION',driver.clock.snapshot)
        self.assertIsNone(self.source._model_status)

    def test_validated_ack_does_not_retire_or_finish_lifecycle(self):
        self.prepare('RESUME','PAUSED')
        driver=self.driver()
        handle=driver.begin(self.action,model_step=0)
        self.emit(self.f.f.f.eth_request(),stage='VALIDATED',probe=0)
        self.assertIsNone(self.source._model_epoch_retirement)
        self.assertFalse(self.source._model_clock_retired)
        self.assertEqual(driver.poll(handle,model_step=0).state,'PENDING')

    def test_retirement_does_not_finish_another_pending_native_transaction(self):
        self.prepare('RESUME','PAUSED')
        event=loads(self.action.event_json)
        self.f.f.build([send('environment',0,10),event])
        self.targets=self.f.authorizer()
        driver=self.driver()
        environment,lifecycle=tuple(self.f.f.plan.iter_actions())[:2]
        pending=driver.begin(environment,model_step=0)
        self.f.f.f.eth_request()
        retiring=driver.begin(lifecycle,model_step=0)
        self.emit(self.f.f.f.eth_request())
        self.rejects('STALE_SESSION',lambda:driver.poll(pending,model_step=0))
        self.assertEqual(driver.poll(retiring,model_step=0).state,'COMPLETE')

    def test_lifecycle_probe_is_rechecked_before_allocation_without_counter_use(self):
        self.prepare('START','CONFIGURED')
        self.targets.approve(self.action,model_step=0)
        caps=self.source.capabilities
        caps['available_probes'].remove('consumer.Lifecycle')
        self.source._capabilities_json=canonicalize(caps)
        before=(self.source._next_sequence,self.source._next_transaction)
        with self.targets.allocation_scope(self.action,0,self.f.f.native):
            self.rejects('TARGET_MISSING',lambda:self.f.f.f.owner.submit(self.action.stimulus,target_step=0))
        self.assertEqual((self.source._next_sequence,self.source._next_transaction),before)

    def test_actual_submitted_lifecycle_payload_cannot_replace_approved_steps(self):
        self.prepare('STEP','PAUSED',step_count=1)
        sample=self.f.backend.sample
        self.f.backend.sample=replace(sample,configuration_json=canonicalize({**self.f.config,'max_duration_steps':2}),
            view=replace(sample.view,max_duration_steps=2))
        self.targets.approve(self.action,model_step=0)
        changed=self.action.stimulus
        changed['payload']['step_count']=3
        before=(self.source._next_sequence,self.source._next_transaction)
        with self.targets.allocation_scope(self.action,0,self.f.f.native):
            self.rejects('STATE',lambda:self.f.f.f.owner.submit(changed,target_step=0))
        self.assertEqual((self.source._next_sequence,self.source._next_transaction),before)

    def test_encoded_lifecycle_packet_cannot_replace_approved_steps(self):
        self.prepare('STEP','PAUSED',step_count=1)
        driver=self.driver()
        driver.begin(self.action,model_step=0)
        request=self.f.f.f.eth_request()
        request['payload']['step_count']=3
        packet=self.source.transport.wire.encode(request,'UDP')[0]
        owner=self.source._dispatcher
        with owner._operation(),self.source._operation(owner=owner):
            self.rejects('STATE',lambda:self.source.transport._authorize_packet(packet,self.source))
