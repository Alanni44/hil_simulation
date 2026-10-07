"""Original action/controller observations; peers/services are software-only."""

from dataclasses import replace
import importlib
import inspect
from pathlib import Path
import tempfile

from common import GatewayTest
from icd_runtime.json_codec import loads, canonicalize
from input_simulator.evidence_recorder import ObservationRecorder, read_observation_chain
import test_native_scenario_actions as native_cases
import test_scenario_driver as driver_cases


class ScenarioRecorderTests(GatewayTest):
    def native(self):
        self.f = native_cases.NativeScenarioActionTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.actions = self.f.build([native_cases.send('first',0,7,link_id='CANT'),
                                     native_cases.send('second',1,7,link_id='CANT')])
        self.actions.preflight()
        return self.f

    def writer(self, *, execution=None, **limits):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)/'scenario-recording'
        self.w = ObservationRecorder(self.f.dispatch,self.root,run_id='run-01',native=True,
            coordinator=self.f.owner,native_actions=self.actions,execution=execution,**limits)
        self.addCleanup(self.w.close)
        return self.w

    def settle(self):
        self.w._job.thread.join(5)
        self.assertFalse(self.w._job.thread.is_alive())
        return self.w.poll()

    def complete_can(self, index=0):
        handle = self.actions.begin(self.f.action(index),model_step=index,target_step=100)
        request = self.f.can_request()
        self.f.reply(request,'CANFD',stage='APPLIED',error='OK')
        self.assertEqual(self.actions.poll(handle,model_step=index).state,'COMPLETE')
        return handle

    def test_required_original_scenario_recording_entry(self):
        self.assertIn('native_actions',inspect.signature(ObservationRecorder).parameters,
                      'original scenario/action recording owner missing')

    def test_actions_continue_after_verified_segment_and_plan_saved_once(self):
        self.native()
        writer = self.writer()
        self.complete_can()
        first_records = self.actions.records
        first_raw = self.f.sender.records
        writer.flush()
        self.assertTrue(self.settle())
        self.assertEqual(self.f.sender.records,())
        self.assertEqual(self.actions.records,first_records)
        self.complete_can(1)
        second_records = self.actions.records[len(first_records):]
        writer.flush()
        self.settle()
        close = writer.close()
        chain = read_observation_chain(self.root,self.contract)
        self.assertEqual(len(chain.segments),2)
        self.assertEqual(chain.segments[0].manifest['format'],'HIL_OBSERVATION_SEGMENT_3')
        self.assertEqual(set(chain.segments[0].manifest['stream_counts']),
            {'SOURCE','DISPATCH','INBOX','CAN','L2','PLAN','NATIVE_ACTION','SCENARIO'})
        self.assertEqual(chain.segments[0].manifest['stream_counts']['PLAN'],1)
        self.assertEqual(chain.segments[1].manifest['stream_counts']['PLAN'],0)
        action_records = tuple(r for archive in chain.segments for r in archive.records
                               if type(r).__name__=='NativeActionRecord')
        self.assertEqual(action_records,first_records+second_records)
        self.assertEqual(sum(close.unpersisted_counts.values()),0)
        self.assertTrue(all(row in chain.segments[0].records for row in first_raw))
        self.assertFalse(chain.evidence_complete)

    def test_unconsumed_eth_terminal_feedback_keeps_same_job_until_action_poll(self):
        self.f = native_cases.NativeScenarioActionTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.actions = self.f.build([native_cases.send('eth',0,10)])
        self.actions.preflight()
        writer = self.writer()
        handle = self.actions.begin(self.f.action(0),model_step=0,target_step=100)
        request = self.f.eth_request()
        self.f.reply(request,'UDP',stage='APPLIED',error='OK')
        self.f.owner.poll()
        original = self.f.dispatch.records
        writer.flush()
        job = writer._job
        job.thread.join(5)
        self.assertFalse(writer.poll())
        self.assertIs(writer._job,job)
        self.assertEqual(self.f.dispatch.records,original)
        self.assertEqual(writer.committed_segments,0)
        self.rejects('STATE',writer.close)
        self.assertIs(writer._job,job)
        self.assertEqual(self.actions.poll(handle,model_step=0).state,'COMPLETE')
        self.assertTrue(writer.poll())
        self.assertEqual(self.f.dispatch.records,())
        writer.flush()
        self.settle()
        self.assertIsNone(writer.close().error)
        self.assertTrue(read_observation_chain(self.root,self.contract).locally_closed)

    def test_action_owner_busy_or_replaced_fails_without_worker_or_reclaim(self):
        self.native()
        writer = self.writer()
        self.complete_can()
        self.actions._lock.acquire()
        try:
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
        finally:
            self.actions._lock.release()
        original = self.actions.session
        try:
            self.actions.session = object()
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
        finally:
            self.actions.session = original

    def test_equal_action_record_replacement_refuses_all_stream_commit(self):
        self.native()
        writer = self.writer()
        self.complete_can()
        writer.flush()
        writer._job.thread.join(5)
        self.actions._records[0] = replace(self.actions._records[0])
        original = self.f.sender.records,self.f.f.session.records
        self.rejects('STATE',writer.poll)
        self.assertEqual((self.f.sender.records,self.f.f.session.records),original)
        self.assertEqual(writer.committed_segments,0)

    def test_replaced_plan_is_rejected_before_action_allocation_or_tx(self):
        self.native()
        self.writer()
        plan = self.actions.plan
        before = self.f.sender.records, self.f.f.session._next_sequence
        try:
            self.actions.plan = replace(plan)
            self.rejects('STATE',lambda:self.actions.begin(self.f.action(0),model_step=0,target_step=100))
            self.assertEqual((self.f.sender.records,self.f.f.session._next_sequence),before)
            self.assertEqual(self.actions.records,())
        finally:
            self.actions.plan = plan

    def test_actual_controller_records_and_named_cleanup_are_saved_not_qualified(self):
        f = driver_cases.ScenarioDriverTests('runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.status()
        driver = f.build([native_cases.send('can',0,7,link_id='CANT')])
        from input_simulator.scenario_execution import ScenarioExecution, CLEANUP_FIELDS
        run = ScenarioExecution(self.contract,f.plan,driver)
        self.f,self.actions = f.f,f.native
        writer = self.writer(execution=run)
        run.start(model_step=0)
        request = f.f.can_request()
        f.f.reply(request,'CANFD',stage='APPLIED',error='OK')
        f.services.complete()
        run.advance(model_step=0)
        run.advance(model_step=0)
        self.assertEqual(run.state,'LOCAL_STOPPED')
        controller = run.records
        writer.flush()
        self.assertTrue(self.settle())
        writer.close()
        chain = read_observation_chain(self.root,self.contract)
        restored = tuple(r for r in chain.segments[0].records if type(r).__name__=='ScenarioRecord')
        self.assertEqual(restored,controller)
        self.assertEqual(restored[-1].completed_cleanup_fields,CLEANUP_FIELDS)
        self.assertEqual(run.records,controller)
        self.assertFalse(chain.evidence_complete)

    def test_closed_run_record_fields_handles_and_bytes_are_lossless(self):
        self.native()
        self.complete_can()
        module = importlib.import_module('input_simulator._scenario_evidence')
        record = self.actions.records[0]
        row = loads(module.encode_scenario_record('NATIVE_ACTION',record))
        self.assertEqual(module.decode_scenario_record(row),record)
        self.assertEqual(module.decode_scenario_record(row).request_json,record.request_json)
        for name,value in (('kind','QUALIFIED'),('error','SUCCESS'),('qualification_status','VERIFIED')):
            modified = loads(canonicalize(row))
            modified['record'][name] = value
            self.rejects('RESOURCE',lambda:module.decode_scenario_record(modified))

    def test_persisted_plan_keeps_exact_original_identity_and_resource_bytes(self):
        self.native()
        writer = self.writer()
        writer.flush()
        self.assertTrue(self.settle())
        chain = read_observation_chain(self.root,self.contract)
        row = next(r for r in chain.segments[0].records if type(r).__name__=='ScenarioPlanRecord')
        self.assertEqual(row.scenario_json,self.actions.plan.scenario_json)
        self.assertEqual(row.identity_json,self.f.f.session._identity_json)
        self.assertEqual(row.session_id,self.actions._sid)
        self.assertEqual(row.model_id,self.actions.plan.model_id)

    def test_saved_history_cannot_be_replaced_before_next_segment(self):
        self.native()
        writer = self.writer()
        self.complete_can()
        writer.flush()
        self.settle()
        original = self.actions._records[0]
        try:
            self.actions._records[0] = replace(original)
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
            self.assertEqual(writer.committed_segments,1)
        finally:
            self.actions._records[0] = original

    def test_count_and_byte_limits_do_not_reclaim_or_allocate_worker(self):
        for limits in ({'max_records':1},{'max_bytes':100}):
            self.native()
            writer = self.writer(**limits)
            self.complete_can()
            before = self.f.sender.records,self.f.f.session.records,self.actions.records
            self.rejects('CAPACITY',writer.flush)
            self.assertIsNone(writer._job)
            self.assertEqual((self.f.sender.records,self.f.f.session.records,self.actions.records),before)
            writer.close()

    def test_scenario_rows_cannot_be_downgraded_to_native_only_format(self):
        self.native()
        writer = self.writer()
        writer.flush()
        self.settle()
        from input_simulator.evidence_archive import ObservationArchive, _validate
        archive = read_observation_chain(self.root,self.contract).segments[0]
        manifest = archive.manifest
        manifest['format'] = 'HIL_OBSERVATION_SEGMENT_2'
        for stream in ('PLAN','NATIVE_ACTION','SCENARIO'):
            del manifest['stream_counts'][stream]
        changed = ObservationArchive(archive.records_jsonl,canonicalize(manifest))
        self.rejects('RESOURCE',lambda:_validate(changed,contract=self.contract))

    def test_required_plan_and_event_identifiers_cannot_be_null(self):
        self.native()
        from input_simulator._scenario_evidence import ScenarioPlanRecord, encode_scenario_record, decode_scenario_record
        from input_simulator.scenario_execution import ScenarioRecord
        records = (('PLAN',ScenarioPlanRecord(self.actions.plan.scenario_json,
            self.f.f.session._identity_json,self.actions.plan.model_id,self.actions._sid),'model_id'),
            ('SCENARIO',ScenarioRecord('RUN',0,'RUN',0,'REQUESTED'),'event_id'))
        for stream,record,field in records:
            with self.subTest(stream=stream):
                row = loads(encode_scenario_record(stream,record))
                row['record'][field] = None
                self.rejects('RESOURCE',lambda:decode_scenario_record(row))
