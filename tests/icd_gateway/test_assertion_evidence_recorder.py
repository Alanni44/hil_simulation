"""Actual original Status feedback persistence, not C/model/tool qualification."""

from dataclasses import replace
import importlib
import inspect
from pathlib import Path
import tempfile
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from input_simulator.evidence_recorder import ObservationRecorder, read_observation_chain
from input_simulator.scenario import ScenarioPlan
from input_simulator.scenario_assertions import StatusObservationReader, StatusScenarioAssertions
from test_assertion import definition
from test_scenario import scenario, send
import test_native_scenario_actions as native_cases


class AssertionRecorderTests(GatewayTest):
    def build(self, *, reader_limit=4096, **limits):
        self.f=native_cases.NativeScenarioActionTests('runTest')
        def peer_message(mid):
            value=message(mid)
            if mid==129:
                value['payload']['capabilities']['available_probes']=['consumer.Status']
            return value
        # Configure the protocol peer before its actual standard grant is sent.
        with patch('test_scapy_source.message',side_effect=peer_message):
            self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.reader=StatusObservationReader(self.f.f.session,max_records=reader_limit)
        self.addCleanup(self.reader.close)
        document=scenario([send('native',0,7,link_id='CANT')])
        document['assertions']=[definition(message_id=131,probe_id='consumer.Status',stage='E1',
            field_path='receive_queue_depth',expected=1,sample_count=2)]
        self.plan=ScenarioPlan.compile(self.contract,document,model_id='quadrotor_hil')
        from input_simulator.native_scenario_actions import NativeScenarioActions
        self.actions=NativeScenarioActions(self.contract,self.plan,self.f.owner,can_sender=self.f.sender)
        self.runner=StatusScenarioAssertions(self.contract,self.plan,self.reader)
        self.status()
        self.runner.preflight(self.plan)
        self.actions.preflight()
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/'assertion-recording'
        self.writer=ObservationRecorder(self.f.dispatch,self.root,run_id='run-01',native=True,
            coordinator=self.f.owner,native_actions=self.actions,assertions=self.runner,**limits)
        self.addCleanup(self.writer.close)
        return self.writer

    def status(self, *, depth=0):
        source=self.f.f.session
        h=self.f.owner.submit({'message_id':2,'payload':{'last_rx_sequence':source.last_rx_sequence,
            'sender_step':0}},target_step=0)
        self.f.owner.poll()
        self.f.eth_request()
        reply=message(131)
        self.f.rx_sequence+=1
        reply['header'].update(session_id=h.session_id,sequence=self.f.rx_sequence,transaction_id=h.transaction_id)
        reply['payload'].update(model_step=0,state='PAUSED',receive_queue_depth=depth)
        for packet in self.f.f.src.wire.encode(reply,'UDP'):
            self.f.f.receiver.sendto(packet,self.f.f.src.feedback_endpoint)
        self.f.owner.poll()
        return reply

    def begin(self):
        return self.runner.begin_assertions(self.plan.assertions,model_step=0)

    def settle(self):
        self.writer._job.thread.join(5)
        self.assertFalse(self.writer._job.thread.is_alive())
        self.assertTrue(self.writer.poll())

    def test_required_explicit_actual_assertion_owner_entry(self):
        self.assertIn('assertions',inspect.signature(ObservationRecorder).parameters,
                      'actual assertion/sample lifecycle recording missing')

    def test_actual_samples_comparisons_lifecycle_continue_during_save(self):
        writer=self.build()
        h=self.begin()
        writer.flush()
        self.status(depth=1)
        self.assertEqual(self.runner.poll(h,model_step=0).state,'PENDING')
        self.settle()
        self.status(depth=1)
        self.assertEqual(self.runner.poll(h,model_step=0).state,'COMPLETE')
        histories=(self.reader.records,self.runner.records,self.runner.lifecycle_records)
        writer.flush()
        self.settle()
        self.assertFalse(any(writer.close().unpersisted_counts.values()))
        chain=read_observation_chain(self.root,self.contract)
        self.assertEqual(chain.segments[0].manifest['format'],'HIL_OBSERVATION_SEGMENT_4')
        expected=('ModelClockSnapshot','RuntimeAssertionRecord','RuntimeAssertionLifecycle')
        for name,original in zip(expected,histories):
            restored=tuple(r for a in chain.segments for r in a.records if type(r).__name__==name)
            self.assertEqual(restored,original)
        self.assertEqual((self.reader.records,self.runner.records,self.runner.lifecycle_records),histories)
        self.assertFalse(chain.evidence_complete)
        self.assertEqual([r.state for r in histories[2]],['PENDING','COMPLETE'])

    def test_failure_terminal_retains_begin_and_error_once(self):
        writer=self.build()
        h=self.begin()
        self.status(depth=0)
        result=self.runner.poll(h,model_step=0)
        self.assertEqual(result.error,'BUSINESS_FAILED')
        self.runner.poll(h,model_step=0)
        self.assertEqual(len(self.runner.lifecycle_records),2)
        writer.flush()
        self.settle()
        writer.close()
        rows=tuple(r for r in read_observation_chain(self.root,self.contract).segments[0].records
                   if type(r).__name__=='RuntimeAssertionLifecycle')
        self.assertEqual(rows[-1].error,'BUSINESS_FAILED')
        self.assertEqual(rows[-1].handle,h)

    def test_handler_lock_and_replacement_refuse_without_worker_or_reclaim(self):
        writer=self.build()
        self.runner._lock.acquire()
        try:
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
        finally:
            self.runner._lock.release()
        original=self.runner.reader
        try:
            self.runner.reader=object()
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
        finally:
            self.runner.reader=original

    def test_sample_replacement_does_not_allow_partial_reclaim(self):
        writer=self.build()
        writer.flush()
        writer._job.thread.join(5)
        original=self.reader._records[0]
        before=self.f.dispatch.records,self.f.f.session.records
        try:
            self.reader._records[0]=replace(original)
            self.rejects('STATE',writer.poll)
            self.assertEqual((self.f.dispatch.records,self.f.f.session.records),before)
        finally:
            self.reader._records[0]=original

    def test_first_overflow_is_persisted_without_qualification(self):
        writer=self.build(reader_limit=1)
        self.begin()
        self.status(depth=1)
        self.assertEqual(self.reader.failure[0],'BUFFER_FULL')
        writer.flush()
        self.settle()
        writer.close()
        rows=read_observation_chain(self.root,self.contract).segments[0].records
        failure=next(r for r in rows if type(r).__name__=='StatusReaderFailure')
        self.assertEqual(failure.error,'BUFFER_FULL')
        self.assertEqual(failure.received_ns,self.reader.failure[2])
        self.assertEqual(len(self.reader.records),1)

    def test_codec_preserves_raw_provenance_and_rejects_null_required_fields(self):
        self.build()
        h=self.begin()
        self.status(depth=1)
        self.runner.poll(h,model_step=0)
        module=importlib.import_module('input_simulator._assertion_evidence')
        rows=(('STATUS_SAMPLE',self.reader.records[-1]),('ASSERTION',self.runner.records[-1]),
              ('ASSERTION_LIFECYCLE',self.runner.lifecycle_records[0]))
        for stream,record in rows:
            encoded=module.encode_assertion_record(stream,record)
            self.assertEqual(module.decode_assertion_record(loads(encoded)),record)
        row=loads(module.encode_assertion_record('ASSERTION',self.runner.records[-1]))
        row['record']['assertion_id']=None
        self.rejects('RESOURCE',lambda:module.decode_assertion_record(row))

    def test_format_three_cannot_contain_assertion_rows(self):
        writer=self.build()
        self.begin()
        writer.flush()
        self.settle()
        from input_simulator.evidence_archive import ObservationArchive, _validate
        archive=read_observation_chain(self.root,self.contract).segments[0]
        manifest=archive.manifest
        manifest['format']='HIL_OBSERVATION_SEGMENT_3'
        for stream in ('STATUS_SAMPLE','STATUS_FAILURE','ASSERTION','ASSERTION_LIFECYCLE'):
            del manifest['stream_counts'][stream]
        self.rejects('RESOURCE',lambda:_validate(ObservationArchive(archive.records_jsonl,
            canonicalize(manifest)),contract=self.contract))

    def test_capacity_failure_preserves_samples_and_no_worker(self):
        writer=self.build(max_records=1)
        before=self.reader.records,self.f.dispatch.records,self.f.f.session._next_sequence
        self.rejects('CAPACITY',writer.flush)
        self.assertIsNone(writer._job)
        self.assertEqual((self.reader.records,self.f.dispatch.records,self.f.f.session._next_sequence),before)

    def test_equal_plan_replacement_rejected_before_assertion_begin(self):
        self.build()
        before=(self.runner.lifecycle_records,self.runner.records,self.f.f.session._next_sequence)
        original=self.runner.plan
        try:
            self.runner.plan=replace(original)
            self.rejects('STATE',self.begin)
            self.assertEqual((self.runner.lifecycle_records,self.runner.records,
                              self.f.f.session._next_sequence),before)
        finally:
            self.runner.plan=original

    def test_local_close_lists_unsaved_lifecycle_without_faking_result(self):
        writer=self.build()
        writer.flush()
        self.settle()
        self.begin()
        close=writer.close()
        self.assertEqual(close.unpersisted_counts['ASSERTION_LIFECYCLE'],1)
        self.assertEqual(self.runner.lifecycle_records[-1].state,'PENDING')
        self.assertFalse(read_observation_chain(self.root,self.contract).evidence_complete)

    def test_live_recording_cannot_silently_detach_status_sampling(self):
        writer=self.build()
        before=self.reader.records
        self.rejects('STATE',self.reader.close)
        self.assertFalse(self.reader._closed)
        self.assertIs(self.f.f.session._status_assertion_reader,self.reader)
        self.assertEqual(self.reader.records,before)
        writer.close()
        self.reader.close()
        self.assertTrue(self.reader._closed)
        self.assertIsNone(self.f.f.session._status_assertion_reader)

    def test_codec_uint64_times_and_status_identity_are_lossless_and_strict(self):
        self.build()
        module=importlib.import_module('input_simulator._assertion_evidence')
        sample=self.reader.records[0]
        delta=2**53+1
        sample=replace(sample,started_ns=sample.started_ns+delta,completed_ns=sample.completed_ns+delta,
                       deadline_ns=sample.deadline_ns+delta)
        row=loads(module.encode_assertion_record('STATUS_SAMPLE',sample))
        self.assertEqual(module.decode_assertion_record(row),sample)
        for field,value in (('model_id',None),('session_id',True),('model_step',None),('started_ns',float(delta))):
            bad=loads(canonicalize(row))
            bad['record'][field]=value
            self.rejects('RESOURCE',lambda:module.decode_assertion_record(bad))
