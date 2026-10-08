"""Actual receiver session groups; no model lifecycle application is implied."""

from dataclasses import FrozenInstanceError
import time
import tempfile

from common import GatewayTest, message
from icd_gateway.receiver import Receiver
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant


class RunRetirementTests(GatewayTest):
    def create(self,*,foreign_field='run_id',foreign_value='other-run',**options):
        self.opens=[]
        self.links=[]
        grants=[]
        for index in range(4):
            opening=message(1)
            opening['payload']['identity']['source_id']=f'actor-{index}'
            if index==3:
                opening['payload']['identity'][foreign_field]=foreign_value
            opening['payload']['nonce_hex']=f'{index:032x}'
            opening['payload']['roles']=['CONTROLLER'] if index==1 else ['STIMULUS']
            link=PeerBinding('ETH_0','UDP',f'127.0.0.1:{36500+index}')
            grants.append(SourceGrant(opening['payload']['identity'],tuple(opening['payload']['roles']),(link,)))
            self.opens.append(opening)
            self.links.append(link)
        self.registry=SessionRegistry(self.contract,grants)
        self.receiver=Receiver(self.contract,self.registry,**options)
        self.sids=[self.deliver(opening,index=index)[0]['payload']['session_id']
                   for index,opening in enumerate(self.opens)]

    def deliver(self,value,*,index=0,now=0):
        replies=()
        for raw in self.receiver.wire.encode(value,'UDP'):
            replies=self.receiver.receive(raw,self.links[index],now_ns=now)
        return replies

    def queue_inputs(self):
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        from test_model_bindings import declared_runtime
        self.queue=ModelQueue(self.contract,self.registry,[ModelBindings(self.contract,'quadrotor_hil',
            declared_runtime(self.contract,'quadrotor_hil'))])
        self.pending=[]
        for index,mid in enumerate((10,7,11,17)):
            value=message(mid)
            value['header'].update(session_id=self.sids[index],sequence=2,transaction_id=2,target_step=5+index)
            self.registry.accept(value,self.links[index],now_ns=0)
            kwargs={'control_source':'PX4_SITL','input_lane':'FLIGHT_CONTROL'} if index==1 else {}
            self.pending.append(self.queue.enqueue(value,state='RUNNING',now_ns=0,**kwargs))

    def fragments(self):
        for index in (0,2,3):
            value=message(3)
            value['header'].update(session_id=self.sids[index],sequence=20,transaction_id=20)
            raws=self.receiver.wire.encode(value,'UDP')
            self.assertGreater(len(raws),1)
            self.receiver.receive(raws[0],self.links[index],now_ns=0)

    def test_registry_resolves_all_original_sources_but_not_other_run(self):
        self.create()
        self.assertTrue(hasattr(self.registry,'run_session_ids'),'actual run-session resolver missing')
        before=(self.registry.active_count,self.registry.cache_count,self.registry._next_id)
        self.assertEqual(self.registry.run_session_ids(self.sids[0],now_ns=0),tuple(self.sids[:3]))
        self.assertEqual((self.registry.active_count,self.registry.cache_count,self.registry._next_id),before)
        self.assertEqual(self.registry._sessions[self.sids[1]].roles,('CONTROLLER',))

    def test_receiver_retirement_is_scoped_retained_and_not_model_success(self):
        self.create()
        self.assertTrue(hasattr(self.receiver,'retire_run'),'actual group retirement missing')
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertEqual(record.selected_sessions,tuple(self.sids[:3]))
        self.assertEqual(record.retired_sessions,tuple(self.sids[:3]))
        self.assertEqual(record.discarded_inputs,())
        self.assertIsNone(record.error)
        self.assertEqual(self.registry.session_ids,(self.sids[3],))
        self.assertIs(self.receiver.run_retirements[0],record)
        self.assertFalse(record.execution_ready)
        self.assertEqual(record.qualification_status,'NOT_EVALUATED')

    def test_context_selection_does_not_cross_vehicle_scenario_or_model(self):
        for field,value in (('vehicle_id','other-vehicle'),('scenario_id','other-scenario'),
                            ('model_id','fixed_wing_hil')):
            with self.subTest(field=field):
                self.create(foreign_field=field,foreign_value=value)
                self.assertEqual(self.registry.run_session_ids(self.sids[0],now_ns=0),tuple(self.sids[:3]))

    def test_matching_expired_actor_is_selected_without_unrelated_maintenance(self):
        self.create()
        self.registry._sessions[self.sids[1]].deadline_ns=1
        self.registry._sessions[self.sids[3]].deadline_ns=1
        deadlines={sid:s.deadline_ns for sid,s in self.registry._sessions.items()}
        self.assertEqual(self.registry.run_session_ids(self.sids[0],now_ns=1),tuple(self.sids[:3]))
        self.assertEqual({sid:s.deadline_ns for sid,s in self.registry._sessions.items()},deadlines)
        self.assertEqual(self.registry.active_count,4)
        self.registry._sessions[self.sids[0]].deadline_ns=1
        self.rejects('STALE_SESSION',lambda:self.registry.run_session_ids(self.sids[0],now_ns=1))

    def test_strict_origins_and_uint64_times_never_delete_or_allocate(self):
        self.create()
        for sid in (True,0,-1,2**32,float(self.sids[0]),str(self.sids[0]),None,[]):
            for operation in (self.registry.run_session_ids,self.receiver.retire_run):
                self.rejects('SCHEMA',lambda:operation(sid,now_ns=0))
        for now in (True,-1,2**64,0.0,None):
            self.rejects('SCHEMA',lambda:self.receiver.retire_run(self.sids[0],now_ns=now))
        self.assertEqual(self.registry.active_count,4)
        self.assertEqual(self.receiver.run_retirements,())

    def test_queue_fragment_cache_and_model_step_provenance_are_preserved(self):
        self.create()
        self.queue_inputs()
        self.fragments()
        self.queue._steps['quadrotor_hil']=3
        before_cache=self.registry.cache_count
        groups=dict(self.receiver.assembler._groups)
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertEqual(record.captured_inputs,tuple(self.pending[:3]))
        self.assertEqual(record.discarded_inputs,tuple(self.pending[:3]))
        self.assertEqual(self.queue._pending,{self.pending[3].key:self.pending[3]})
        self.assertEqual(self.queue._steps['quadrotor_hil'],3)
        self.assertEqual(self.registry.cache_count,before_cache)
        self.assertEqual(len(record.captured_groups),2)
        self.assertEqual(record.discarded_groups,record.captured_groups)
        for captured in record.captured_groups:
            self.assertIs(captured.first,groups[captured.key].first)
            self.assertEqual(captured.pieces,tuple(sorted(groups[captured.key].pieces.items())))
        self.assertEqual(self.receiver.assembler.pending_count,1)

    def test_exact_local_retry_returns_old_record_without_adopting_new_sid(self):
        self.create()
        original=self.receiver.retire_run(self.sids[0],now_ns=0)
        opening=message(1)
        opening['payload']['identity']=self.opens[0]['payload']['identity']
        opening['payload']['nonce_hex']='f'*32
        new_sid=self.deliver(opening)[0]['payload']['session_id']
        self.assertIs(self.receiver.retire_run(self.sids[0],now_ns=1),original)
        self.assertIn(new_sid,self.registry.session_ids)
        self.assertEqual(len(self.receiver.run_retirements),1)
        self.rejects('STALE_SESSION',lambda:self.registry.run_session_ids(self.sids[0],now_ns=1))

    def test_record_byte_and_input_capacity_fail_before_deletion(self):
        for limits in ({'run_retirement_bytes':1},{'maintenance_input_capacity':1}):
            with self.subTest(limits=limits):
                self.create(**limits)
                self.queue_inputs()
                self.fragments()
                self.rejects('BUFFER_FULL',lambda:self.receiver.retire_run(self.sids[0],now_ns=0))
                self.assertEqual(self.registry.session_ids,tuple(self.sids))
                self.assertEqual(self.queue.count,4)
                self.assertEqual(self.receiver.assembler.pending_count,3)
                self.assertEqual(self.receiver.run_retirements,())
        self.create(run_retirement_capacity=1)
        first=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.rejects('BUFFER_FULL',lambda:self.receiver.retire_run(self.sids[3],now_ns=0))
        self.assertEqual(self.registry.session_ids,(self.sids[3],))
        self.assertEqual(self.receiver.run_retirements,(first,))

    def test_exception_retains_actual_partial_deletion_and_does_not_restart(self):
        self.create()
        self.queue_inputs()
        self.fragments()
        original=self.receiver.retire_session
        calls=[]
        def stop_after_one(sid):
            calls.append(sid)
            original(sid)
            raise OSError('failure after original effects')
        self.receiver.retire_session=stop_after_one
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertEqual(record.error,'RESOURCE')
        self.assertEqual(record.retired_sessions,(self.sids[0],))
        self.assertEqual(record.discarded_inputs,(self.pending[0],))
        self.assertEqual(record.captured_inputs,tuple(self.pending[:3]))
        self.assertEqual(len(record.discarded_groups),1)
        self.assertEqual(self.registry.session_ids,tuple(self.sids[1:]))
        self.assertIs(self.receiver.retire_run(self.sids[0],now_ns=0),record)
        self.assertEqual(calls,[self.sids[0]])

    def test_history_is_immutable_and_survives_close(self):
        self.create()
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        with self.assertRaises(FrozenInstanceError):
            record.retired_sessions=()
        self.receiver.close()
        self.assertEqual(self.receiver.run_retirements,(record,))
        self.rejects('STATE',lambda:self.receiver.retire_run(self.sids[0],now_ns=0))

    def test_regressed_time_and_changed_registry_reject_before_mutation(self):
        self.create()
        self.registry.run_session_ids(self.sids[0],now_ns=1)
        self.rejects('SCHEMA',lambda:self.receiver.retire_run(self.sids[0],now_ns=0))
        self.receiver.registry=object()
        self.rejects('STATE',lambda:self.receiver.retire_run(self.sids[0],now_ns=1))
        self.assertEqual(self.registry.active_count,4)

    def test_reentrant_shutdown_cannot_partially_close_the_receiver(self):
        self.create()
        original=self.receiver.retire_session
        def callback(sid):
            self.rejects('STATE',self.receiver.close)
            self.rejects('STATE',lambda:self.receiver.retire_run(sid,now_ns=0))
            return original(sid)
        self.receiver.retire_session=callback
        self.assertIsNone(self.receiver.retire_run(self.sids[0],now_ns=0).error)
        self.assertFalse(self.receiver._closed)

    def test_replaced_owner_after_first_effect_keeps_original_partial_record(self):
        self.create()
        self.queue_inputs()
        original=self.receiver.retire_session
        def replace_owner(sid):
            result=original(sid)
            self.receiver.registry=object()
            return result
        self.receiver.retire_session=replace_owner
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertEqual(record.error,'STATE')
        self.assertEqual(record.retired_sessions,(self.sids[0],))
        self.assertEqual(record.discarded_inputs,(self.pending[0],))
        self.assertIs(self.receiver.run_retirements[-1],record)
        self.assertFalse(self.receiver._run_busy)
        self.assertEqual(self.registry.session_ids,tuple(self.sids[1:]))

    def test_closed_original_queue_refuses_retirement_before_deletion(self):
        self.create()
        self.queue_inputs()
        self.queue.close()
        self.rejects('STATE',lambda:self.receiver.retire_run(self.sids[0],now_ns=0))
        self.assertEqual(self.registry.session_ids,tuple(self.sids))
        self.assertEqual(self.receiver.run_retirements,())

    def test_actual_resource_worker_cancels_staging_without_claiming_file_cleanup_early(self):
        from test_resource_worker import ResourceWorkerTests
        from icd_runtime.json_codec import loads
        fixture=ResourceWorkerTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_worker()
        original=fixture.submit(b'abcdef',offset=0,length=3)
        outcome=fixture.result()
        self.assertFalse(loads(outcome.payload_bytes)['complete'])
        fixture.worker.release_result(outcome.key)
        receiver=Receiver(fixture.contract,fixture.registry,resource_worker=fixture.worker)
        record=receiver.retire_run(fixture.sid,now_ns=time.monotonic_ns())
        self.assertEqual(record.retired_sessions,(fixture.sid,))
        self.assertIsNone(record.error)
        self.assertFalse(record.execution_ready)
        aborted=fixture.worker.drain_abort_records(timeout=2)
        self.assertEqual(len(aborted),1)
        self.assertEqual(loads(aborted[0].requests[0]),original)
        self.assertEqual(list((fixture.store.root/'incoming').iterdir()),[])
        self.assertTrue(fixture.worker.available)

    def test_reentrant_ingress_and_retirement_cannot_add_or_delete_uncaptured_groups(self):
        self.create()
        self.fragments()
        original=self.receiver.retire_session
        def callback(sid):
            result=original(sid)
            value=message(3)
            value['header'].update(session_id=self.sids[2],sequence=21,transaction_id=21)
            raw=self.receiver.wire.encode(value,'UDP')[0]
            self.rejects('STATE',lambda:self.receiver.receive(raw,self.links[2],now_ns=0))
            self.rejects('STATE',lambda:self.receiver.tick(now_ns=0))
            self.rejects('STATE',lambda:original(self.sids[3]))
            self.rejects('STATE',self.receiver.drain_maintenance)
            self.rejects('STATE',self.receiver.drain_resource_records)
            self.rejects('STATE',self.receiver.drain_shutdown)
            return result
        self.receiver.retire_session=callback
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertIsNone(record.error)
        self.assertEqual(len(record.captured_groups),2)
        self.assertEqual(record.captured_groups,record.discarded_groups)
        self.assertEqual(self.registry.session_ids,(self.sids[3],))

    def test_other_registry_actual_worker_is_rejected_before_wrong_cancellation(self):
        from icd_gateway.resource_worker import ResourceWorker
        from icd_gateway.resources import ResourceStore
        self.create()
        other=SessionRegistry(self.contract,[SourceGrant(self.opens[0]['payload']['identity'],
            ('STIMULUS',),(self.links[0],))])
        other._next_id=self.sids[0]
        sid=other.accept(self.opens[0],self.links[0],now_ns=0).session_id
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store=ResourceStore(self.contract,directory.name,min_free_bytes=0)
        worker=ResourceWorker(self.contract,other,store)
        self.addCleanup(worker.close)
        self.registry._resource_worker=worker
        self.rejects('STATE',lambda:self.receiver.retire_run(self.sids[0],now_ns=0))
        self.assertIn(sid,worker._live)
        self.assertEqual(self.registry.session_ids,tuple(self.sids))
        self.assertEqual(self.receiver.run_retirements,())

    def test_closed_actual_worker_rejects_before_local_session_deletion(self):
        from test_resource_worker import ResourceWorkerTests
        fixture=ResourceWorkerTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_worker()
        receiver=Receiver(fixture.contract,fixture.registry,resource_worker=fixture.worker)
        fixture.worker.close()
        self.rejects('STATE',lambda:receiver.retire_run(fixture.sid,now_ns=time.monotonic_ns()))
        self.assertEqual(fixture.registry.session_ids,(fixture.sid,))
        self.assertEqual(receiver.run_retirements,())

    def test_worker_replaced_after_first_effect_preserves_partial_record(self):
        self.create()
        self.queue_inputs()
        original=self.receiver.retire_session
        def replace_after_effect(sid):
            result=original(sid)
            self.registry._resource_worker=object()
            return result
        self.receiver.retire_session=replace_after_effect
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertEqual(record.error,'STATE')
        self.assertEqual(record.retired_sessions,(self.sids[0],))
        self.assertEqual(record.discarded_inputs,(self.pending[0],))
        self.assertEqual(self.registry.session_ids,tuple(self.sids[1:]))
        self.assertFalse(self.receiver._run_busy)
        self.assertIsNone(self.receiver._run_allowed_sid)

    def test_original_worker_binding_cannot_be_adopted_by_historical_retry(self):
        self.create()
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.receiver.resource_worker=object()
        self.rejects('STATE',lambda:self.receiver.retire_run(self.sids[0],now_ns=0))
        self.assertEqual(self.receiver.run_retirements,(record,))
        self.assertEqual(self.registry.session_ids,(self.sids[3],))

    def test_worker_replaced_inside_callback_cannot_cancel_foreign_session(self):
        from icd_gateway.resource_worker import ResourceWorker
        from icd_gateway.resources import ResourceStore
        self.create()
        other=SessionRegistry(self.contract,[SourceGrant(self.opens[0]['payload']['identity'],
            ('STIMULUS',),(self.links[0],))])
        other._next_id=self.sids[0]
        sid=other.accept(self.opens[0],self.links[0],now_ns=0).session_id
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        worker=ResourceWorker(self.contract,other,ResourceStore(self.contract,directory.name,min_free_bytes=0))
        self.addCleanup(worker.close)
        original=self.receiver.retire_session
        def replace_before_effect(selected):
            self.registry._resource_worker=worker
            return original(selected)
        self.receiver.retire_session=replace_before_effect
        record=self.receiver.retire_run(self.sids[0],now_ns=0)
        self.assertEqual(record.error,'STATE')
        self.assertEqual(record.retired_sessions,())
        self.assertIn(sid,worker._live)
        self.assertEqual(self.registry.session_ids,tuple(self.sids))
