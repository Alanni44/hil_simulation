"""Actual receiver registration/semantic gates, not actuator effect qualification."""

from dataclasses import FrozenInstanceError

from common import GatewayTest, message
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.semantic_guards import ModelView, SemanticGuards


class RegisteredControllerTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.selector_identity = message(1)['payload']['identity']
        self.identity = {**self.selector_identity, 'source_id':'controller-01'}
        self.selector_link = PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        self.link = PeerBinding('ETH_1','UDP','127.0.0.1:36202')
        self.can_link = PeerBinding('CANFD_0','CANFD','original-can-peer')
        self.setup_registry()

    def setup_registry(self, *, grant_roles=('CONTROLLER',), requested_roles=('CONTROLLER',)):
        self.registry = SessionRegistry(self.contract, (
            SourceGrant(self.selector_identity,('STIMULUS',),(self.selector_link,)),
            SourceGrant(self.identity,grant_roles,(self.link,self.can_link))))
        self.selector_sid = self.open(self.selector_identity,self.selector_link,('STIMULUS',))
        self.sid = self.open(self.identity,self.link,requested_roles)
        self.guards = SemanticGuards(self.contract)
        self.view = ModelView(self.identity['model_id'],'PAUSED',10,600000,'NONE',False,True)

    def open(self, identity, link, roles, *, nonce='0'*32, now=0):
        value = message(1)
        value['payload'].update(identity=identity.copy(),roles=list(roles),nonce_hex=nonce)
        return self.registry.accept(value,link,now_ns=now).session_id

    def snapshot(self, *, now=0, identity=None):
        return self.registry.registered_controller(self.identity if identity is None else identity,now_ns=now)

    def owner(self, *, source='PX4_SITL', lane='ACTUATOR', sequence=2, now=0):
        value = message(6)
        value['header'].update(session_id=self.selector_sid,sequence=sequence,
                               transaction_id=sequence,target_step=self.view.model_step)
        value['payload'].update(source=source,role='CONTROLLER',input_lane=lane)
        self.registry.accept(value,self.selector_link,now_ns=now)
        return value

    def gate(self, value, *, identity=None, declared='PX4_SITL', now=0, view=None):
        return self.guards.external_control_owner(value,self.view if view is None else view,
            registry=self.registry,producer_identity=self.identity if identity is None else identity,
            declared_controller=declared,now_ns=now)

    def test_required_registry_and_semantic_apis_exist(self):
        self.assertTrue(callable(getattr(self.registry,'registered_controller',None)),
                        'actual receiver controller resolution missing')
        self.assertTrue(callable(getattr(self.guards,'external_control_owner',None)),
                        'actual producer semantic gate missing')

    def test_snapshot_retains_actual_sid_grant_roles_links_and_nonce(self):
        row = self.snapshot()
        self.assertEqual((row.session_id,row.identity,row.roles,row.bindings,row.nonce),
            (self.sid,self.identity,('CONTROLLER',),(self.link,self.can_link),'0'*32))
        self.assertEqual((row.observed_ns,row.deadline_ns,row.last_rx_sequence),(0,1_000_000_000,1))
        self.assertEqual(row.qualification_status,'NOT_EVALUATED')
        self.assertFalse(row.execution_ready)

    def test_snapshot_identity_is_detached_and_record_is_immutable(self):
        row = self.snapshot()
        row.identity['source_id'] = 'foreign'
        self.identity['source_id'] = 'changed-after-grant'
        self.assertEqual(row.identity['source_id'],'controller-01')
        with self.assertRaises(FrozenInstanceError):
            row.session_id = 123

    def test_list_valued_grant_bindings_cannot_escape_as_mutable_alias(self):
        self.registry = SessionRegistry(self.contract,(
            SourceGrant(self.selector_identity,('STIMULUS',),(self.selector_link,)),
            SourceGrant(self.identity,('CONTROLLER',),[self.link,self.can_link])))
        self.sid = self.open(self.identity,self.link,('CONTROLLER',))
        row = self.snapshot()
        self.assertIsInstance(row.bindings,tuple)
        with self.assertRaises(AttributeError):
            row.bindings.clear()
        self.assertEqual(self.snapshot().bindings,(self.link,self.can_link))

    def test_complete_identity_is_required_not_a_model_or_source_string(self):
        for value in (None,'controller-01',{}, {'model_id':'quadrotor_hil'},
                      {**self.identity,'unknown':'value'}):
            self.rejects('SCHEMA',lambda:self.snapshot(identity=value) if value is not None
                         else self.registry.registered_controller(None,now_ns=0))
        for field in self.identity:
            if field == 'definition_version':
                continue
            wrong = {**self.identity,field:'fixed_wing_hil' if field=='model_id' else 'foreign'}
            self.rejects('AUTHORIZATION',lambda:self.snapshot(identity=wrong))

    def test_actual_granted_roles_not_configured_or_requested_roles_are_used(self):
        self.setup_registry(grant_roles=('STIMULUS','CONTROLLER'),requested_roles=('STIMULUS',))
        self.rejects('AUTHORIZATION',self.snapshot)
        self.setup_registry(grant_roles=('STIMULUS',),requested_roles=('STIMULUS',))
        self.rejects('AUTHORIZATION',self.snapshot)

    def test_unique_controller_session_cannot_be_selected_by_latest_nonce(self):
        other = self.open(self.identity,self.link,('CONTROLLER',),nonce='1'*32)
        self.assertNotEqual(other,self.sid)
        self.rejects('CONTROL_OWNER',self.snapshot)
        self.registry.revoke(other)
        self.assertEqual(self.snapshot().session_id,self.sid)

    def test_stimulus_session_does_not_make_the_controller_ambiguous(self):
        self.setup_registry(grant_roles=('STIMULUS','CONTROLLER'))
        other = self.open(self.identity,self.link,('STIMULUS',),nonce='1'*32)
        self.assertNotEqual(other,self.sid)
        self.assertEqual(self.snapshot().session_id,self.sid)

    def test_expiry_is_half_open_and_read_does_not_delete_records(self):
        self.assertEqual(self.snapshot(now=999_999_999).session_id,self.sid)
        before = (self.registry.session_ids,self.registry.cache_count)
        self.rejects('STALE_SESSION',lambda:self.snapshot(now=1_000_000_000))
        self.assertEqual(before,(self.registry.session_ids,self.registry.cache_count))
        self.rejects('SCHEMA',lambda:self.snapshot(now=999_999_999))

    def test_revoked_closed_and_missing_live_producer_fail(self):
        self.registry.revoke(self.sid)
        self.rejects('STALE_SESSION',self.snapshot)
        self.registry.close()
        self.rejects('STATE',self.snapshot)

    def test_monotonic_nanoseconds_are_strict(self):
        for now in (True,-1,0.0,'0'):
            self.rejects('SCHEMA',lambda:self.snapshot(now=now))
        self.snapshot(now=1)
        self.rejects('SCHEMA',self.snapshot)

    def test_reads_do_not_renew_allocate_or_overwrite_receiver_history(self):
        before = (self.registry._next_id,self.registry.cache_count,self.registry.session_ids,
                  self.registry._sessions[self.sid].deadline_ns,
                  self.registry._sessions[self.sid].last_rx,self.registry._sessions[self.sid].last_tx,
                  tuple(self.registry._records.items()),tuple(self.registry._opens.items()))
        for now in (0,1,2):
            self.snapshot(now=now)
        self.assertEqual(before,(self.registry._next_id,self.registry.cache_count,self.registry.session_ids,
                  self.registry._sessions[self.sid].deadline_ns,
                  self.registry._sessions[self.sid].last_rx,self.registry._sessions[self.sid].last_tx,
                  tuple(self.registry._records.items()),tuple(self.registry._opens.items())))

    def test_fresh_heartbeat_updates_actual_session_not_control_lease(self):
        beat = message(2)
        beat['header'].update(session_id=self.sid,sequence=2,transaction_id=2)
        self.registry.accept(beat,self.link,now_ns=500_000_000)
        row = self.snapshot(now=1_000_000_000)
        self.assertEqual((row.deadline_ns,row.last_rx_sequence),(1_500_000_000,2))
        self.assertFalse(hasattr(row,'control_deadline_ns'))

    def test_external_owner_uses_distinct_actual_controller_not_selector_sid(self):
        value = self.owner()
        approval = self.gate(value)
        self.assertEqual(approval.producer.session_id,self.sid)
        self.assertNotEqual(approval.producer.session_id,value['header']['session_id'])
        self.assertEqual((approval.decision.source,approval.decision.input_lane,
                          approval.decision.lease_ms),('PX4_SITL','ACTUATOR',100))
        self.assertTrue(approval.decision.safe_outputs and approval.decision.clear_queues)
        self.assertFalse(approval.execution_ready)
        self.assertEqual(approval.qualification_status,'NOT_EVALUATED')

    def test_original_selector_request_must_actually_be_admitted(self):
        value = self.owner()
        changed = {**value,'payload':{**value['payload'],'mode':'AUTO'}}
        self.rejects('DUPLICATE',lambda:self.gate(changed))
        value['header']['sequence'] = 20
        self.rejects('OUT_OF_ORDER',lambda:self.gate(value))

    def test_cross_vehicle_or_run_producer_cannot_authorize_selector(self):
        for field in ('run_id','vehicle_id','scenario_id'):
            self.identity = {**self.selector_identity,'source_id':'controller-01',field:'other-context'}
            self.setup_registry()
            self.rejects('AUTHORIZATION',lambda:self.gate(self.owner()))

    def test_source_lane_model_and_paused_rules_remain_original(self):
        from dataclasses import replace
        self.rejects('CONTROL_OWNER',lambda:self.gate(self.owner(source='PHYSICAL_UUT')))
        self.rejects('TARGET_MISSING',lambda:self.gate(self.owner(lane='INTERNAL_CONTROLLER',sequence=3)))
        value = self.owner(sequence=4)
        self.rejects('STATE',lambda:self.gate(value,view=replace(self.view,state='RUNNING')))

    def test_none_revocation_does_not_require_live_producer(self):
        value = self.owner(source='NONE',lane='INTERNAL_CONTROLLER')
        self.registry.revoke(self.sid)
        approval = self.gate(value,identity={})
        self.assertIsNone(approval.producer)
        self.assertEqual((approval.decision.source,approval.decision.lease_ms),('NONE',0))

    def test_all_three_models_use_original_external_source_and_lanes(self):
        for model in ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil'):
            self.selector_identity = {**self.selector_identity,'model_id':model}
            self.identity = {**self.selector_identity,'source_id':'controller-01'}
            self.setup_registry()
            for sequence,lane in enumerate(('FLIGHT_CONTROL','ACTUATOR'),start=2):
                self.assertEqual(self.gate(self.owner(lane=lane,sequence=sequence)).producer.session_id,self.sid)

    def test_cross_model_actual_producer_is_not_selected_for_the_view(self):
        self.identity = {**self.identity,'model_id':'fixed_wing_hil'}
        self.setup_registry()
        self.view = ModelView('quadrotor_hil','PAUSED',10,600000,'NONE',False,True)
        self.rejects('AUTHORIZATION',lambda:self.gate(self.owner()))

    def test_selector_model_view_must_match_actual_receiver_session(self):
        from dataclasses import replace
        self.rejects('MODEL',lambda:self.gate(self.owner(),view=replace(self.view,model_id='fixed_wing_hil')))

    def test_expired_other_sid_does_not_make_live_controller_ambiguous(self):
        other = self.open(self.identity,self.link,('CONTROLLER',),nonce='1'*32,now=500_000_000)
        self.assertEqual(self.snapshot(now=1_000_000_000).session_id,other)
        self.assertIn(self.sid,self.registry.session_ids)

    def test_external_gate_rejects_unavailable_registry_and_non_controller_session(self):
        value = self.owner()
        self.rejects('HASH',lambda:self.guards.external_control_owner(value,self.view,
            registry=None,producer_identity=self.identity,declared_controller='PX4_SITL',now_ns=0))
        self.setup_registry(grant_roles=('STIMULUS','CONTROLLER'),requested_roles=('STIMULUS',))
        self.rejects('AUTHORIZATION',lambda:self.gate(self.owner()))

    def test_actual_terminal_selector_request_cannot_later_authorize(self):
        value = self.owner()
        reply = message(130)
        reply['header'].update(session_id=self.selector_sid,sequence=1,
                               transaction_id=value['header']['transaction_id'])
        reply['payload'].update(request_sequence=value['header']['sequence'],request_message_id=6,
                                 stage='FAILED',error='TARGET_MISSING')
        self.registry.record_response(value,(reply,),now_ns=0)
        self.rejects('STATE',lambda:self.gate(value))

    def test_semantic_gate_does_not_run_unrelated_receiver_maintenance(self):
        self.setup_registry(grant_roles=('STIMULUS','CONTROLLER'))
        obsolete = self.open(self.identity,self.link,('STIMULUS',),nonce='1'*32)
        for sid,link in ((self.selector_sid,self.selector_link),(self.sid,self.link)):
            beat = message(2)
            beat['header'].update(session_id=sid,sequence=2,transaction_id=2)
            self.registry.accept(beat,link,now_ns=500_000_000)
        value = self.owner(sequence=3,now=500_000_000)
        before = (self.registry.session_ids,tuple(self.registry._records),tuple(self.registry._opens))
        self.assertEqual(self.gate(value,now=1_000_000_000).producer.session_id,self.sid)
        self.assertEqual(before,(self.registry.session_ids,tuple(self.registry._records),tuple(self.registry._opens)))
        self.assertIn(obsolete,self.registry.session_ids)

    def test_readonly_admission_rejects_expired_selector_without_removing_it(self):
        value = self.owner()
        before = (self.registry.session_ids,tuple(self.registry._records))
        self.rejects('STALE_SESSION',lambda:self.registry.observe_admitted(value,now_ns=1_000_000_000))
        self.assertEqual(before,(self.registry.session_ids,tuple(self.registry._records)))

    def test_readonly_admission_returns_first_receive_and_rejects_claimed_record(self):
        value = self.owner(now=10)
        self.assertEqual(self.registry.observe_admitted(value,now_ns=11),10)
        self.registry.claim_admitted(value,now_ns=12)
        self.rejects('DUPLICATE',lambda:self.registry.observe_admitted(value,now_ns=13))

    def test_readonly_admission_does_not_revive_expired_retry_record(self):
        value = self.owner()
        deadline = self.registry._records[self.selector_sid,2].deadline_ns
        sequence = 3
        for now in range(500_000_000,deadline,500_000_000):
            beat = message(2)
            beat['header'].update(session_id=self.selector_sid,sequence=sequence,transaction_id=sequence)
            self.registry.accept(beat,self.selector_link,now_ns=now)
            sequence += 1
        before = tuple(self.registry._records)
        self.rejects('OUT_OF_ORDER',lambda:self.registry.observe_admitted(value,now_ns=deadline))
        self.assertEqual(tuple(self.registry._records),before)

    def test_frozen_target_and_demo_model_rules_are_not_weakened(self):
        value = self.owner()
        changed = {**value,'header':{**value['header'],'sequence':3,'transaction_id':3,'target_step':11}}
        self.registry.accept(changed,self.selector_link,now_ns=0)
        self.rejects('STATE',lambda:self.gate(changed))
        self.selector_identity = {**self.selector_identity,'model_id':'multirotor_6_hil'}
        self.identity = {**self.selector_identity,'source_id':'controller-01'}
        self.setup_registry()
        self.rejects('UNSUPPORTED',lambda:self.gate(self.owner(source='DEMO_MISSION'),declared='DEMO_MISSION'))
