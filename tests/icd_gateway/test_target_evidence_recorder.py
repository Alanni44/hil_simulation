"""Original target/ACK persistence; model getters are explicit software doubles."""

from dataclasses import replace
import inspect
from pathlib import Path
import tempfile
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.json_codec import canonicalize, loads
from input_simulator.evidence_archive import _encode_record, _decode_record
from input_simulator.evidence_recorder import ObservationRecorder, read_observation_chain
import test_runtime_lifecycle as lifecycle_cases


class TargetRecorderTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.case=lifecycle_cases.RuntimeLifecycleTests('runTest')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.source=self.case.source
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'target-recording'

    def build(self, action='STEP',state='PAUSED',with_assertions=False,with_execution=False,**limits):
        self.case.prepare(action,state,**({'step_count':3} if action=='STEP' else {}))
        assertions=None
        if with_assertions:
            from input_simulator.scenario_assertions import StatusObservationReader,StatusScenarioAssertions
            caps=self.source.capabilities
            caps['available_probes']=sorted(set(caps['available_probes'])|{'consumer.Status'})
            self.source._capabilities_json=canonicalize(caps)
            self.reader=StatusObservationReader(self.source)
            self.addCleanup(self.reader.close)
            assertions=StatusScenarioAssertions(self.case.f.f.native.contract,self.case.f.f.plan,self.reader)
        self.driver=self.case.driver()
        self.targets=self.case.targets
        native=self.case.f.f.f
        execution=None
        if with_execution:
            from input_simulator.scenario_execution import ScenarioExecution
            execution=ScenarioExecution(self.case.f.f.native.contract,self.case.f.f.plan,self.driver)
        self.writer=ObservationRecorder(native.dispatch,self.root,run_id='run-01',native=True,
            coordinator=native.owner,native_actions=self.case.f.f.native,targets=self.targets,
            assertions=assertions,execution=execution,**limits)
        self.addCleanup(self.writer.close)
        return self.writer

    def settle(self):
        self.writer._job.thread.join(5)
        self.assertFalse(self.writer._job.thread.is_alive())
        self.assertTrue(self.writer.poll())

    def rows(self, name):
        chain=read_observation_chain(self.root,self.contract)
        return tuple(r for a in chain.segments for r in a.records if type(r).__name__==name)

    def test_explicit_original_target_entry_required(self):
        self.assertIn('targets',inspect.signature(ObservationRecorder).parameters)

    def test_success_failure_and_new_reads_during_write_are_lossless(self):
        writer=self.build()
        self.targets.approve(self.case.action,model_step=0)
        before=(self.source._next_sequence,self.case.f.backend.calls)
        writer.flush()
        self.assertEqual((self.source._next_sequence,self.case.f.backend.calls),before)
        sample=self.case.f.backend.sample
        self.case.f.backend.sample=replace(sample,configuration_json=b'not-json')
        self.rejects('SCHEMA',lambda:self.targets.approve(self.case.action,model_step=0))
        self.settle()
        self.case.f.backend.sample=sample
        self.targets.approve(self.case.action,model_step=0)
        original=self.targets.records
        writer.flush()
        self.settle()
        close=writer.close()
        self.assertFalse(any(close.unpersisted_counts.values()))
        self.assertEqual(self.rows('RuntimeTargetRecord'),original)
        self.assertEqual(self.targets.records,original)
        self.assertEqual(original[-1].lifecycle.steps,(1,2,3))
        chain=read_observation_chain(self.root,self.contract)
        self.assertEqual(chain.segments[0].manifest['format'],'HIL_OBSERVATION_SEGMENT_5')
        self.assertEqual(len(chain.segments[0].manifest['stream_counts']),10)
        self.assertFalse(chain.evidence_complete)

    def test_exact_retirement_survives_actual_source_close_before_snapshot(self):
        writer=self.build('RESUME')
        handle=self.driver.begin(self.case.action,model_step=0)
        request=self.case.f.f.f.eth_request()
        reply=self.case.emit(request)
        self.assertEqual(self.driver.poll(handle,model_step=0).state,'COMPLETE')
        receipt=self.source._model_epoch_retirement
        self.case.f.f.f.owner.close()
        self.case.f.f.f.dispatch.close()
        self.source.close()
        self.assertIsNone(self.source._model_epoch_retirement)
        writer.flush()
        self.settle()
        writer.close()
        self.assertEqual(self.rows('ModelEpochRetirement'),(receipt,))
        self.assertEqual(receipt.reply_json,canonicalize(reply))
        self.assertEqual(self.targets.epoch_records,(receipt,))

    def test_target_lock_refuses_snapshot_without_worker_or_getter(self):
        writer=self.build()
        before=(self.source._next_sequence,self.case.f.backend.calls)
        self.targets._lock.acquire()
        try:
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
        finally:
            self.targets._lock.release()
        self.assertEqual((self.source._next_sequence,self.case.f.backend.calls),before)

    def test_target_backend_replacement_refuses_before_snapshot(self):
        writer=self.build()
        original=self.targets.backend
        self.targets.backend=type(original)(self.contract,('quadrotor_hil',))
        self.rejects('STATE',writer.flush)
        self.assertIsNone(writer._job)
        self.targets.backend=original

    def test_close_reports_unsaved_target_records_without_claiming_remote_cleanup(self):
        writer=self.build()
        writer.flush()
        self.settle()
        self.targets.approve(self.case.action,model_step=0)
        close=writer.close()
        self.assertEqual(close.unpersisted_counts['TARGET_AUTHORIZATION'],1)
        self.assertEqual(close.unpersisted_counts['MODEL_EPOCH'],0)
        self.assertFalse(read_observation_chain(self.root,self.contract).evidence_complete)

    def test_combined_assertion_and_target_profile_keeps_all_fourteen_streams(self):
        writer=self.build(with_assertions=True)
        self.case.f.f.status(state='PAUSED')
        writer.flush()
        self.settle()
        writer.close()
        chain=read_observation_chain(self.root,self.contract)
        manifest=chain.segments[0].manifest
        self.assertEqual(manifest['format'],'HIL_OBSERVATION_SEGMENT_6')
        self.assertEqual(len(manifest['stream_counts']),14)
        self.assertEqual(manifest['stream_counts']['STATUS_SAMPLE'],1)
        self.assertEqual(manifest['stream_counts']['TARGET_AUTHORIZATION'],1)

    def test_original_producer_bindings_and_control_lease_bytes_roundtrip(self):
        from test_scenario import send
        self.case.f.grant_controller()
        self.case.f.f.build([send('control',0,7)])
        targets=self.case.f.authorizer()
        targets.approve(next(self.case.f.f.plan.iter_actions()),model_step=0)
        original=targets.records[-1]
        restored=_decode_record(loads(_encode_record('TARGET_AUTHORIZATION',original)))
        self.assertEqual(restored,original)
        self.assertIsNotNone(restored.sample.producer)
        self.assertIsNotNone(restored.control_lease)
        from input_simulator._target_evidence import validate_target_record
        validate_target_record(restored,self.contract)

    def test_successful_controller_cannot_drop_or_corrupt_its_original_lease(self):
        from test_scenario import send
        from input_simulator._target_evidence import validate_target_record
        self.case.f.grant_controller()
        self.case.f.f.build([send('control',0,7)])
        targets=self.case.f.authorizer()
        targets.approve(next(self.case.f.f.plan.iter_actions()),model_step=0)
        original=targets.records[-1]
        lease=original.control_lease
        validate_target_record(original,self.contract)
        for changed in (replace(original,control_lease=None),
                replace(original,control_lease=replace(lease,owner_reply_json=b'not-json')),
                replace(original,control_lease=replace(lease,deadline_ns=original.completed_ns)),
                replace(original,control_lease=replace(lease,session_id=lease.session_id+1))):
            restored=_decode_record(loads(_encode_record('TARGET_AUTHORIZATION',changed)))
            self.rejects('RESOURCE',lambda:validate_target_record(restored,self.contract))

    def test_actual_validated_and_applied_control_renewals_keep_original_owner_bytes(self):
        from test_scenario import send
        from input_simulator._target_evidence import validate_target_record
        self.case.f.grant_controller()
        caps=self.source.capabilities
        caps['available_probes']=sorted(set(caps['available_probes'])|{'consumer.FlightQuad'})
        self.source._capabilities_json=canonicalize(caps)
        self.case.f.f.build([send('control',0,7)])
        targets=self.case.f.authorizer()
        owner=self.case.f.f.f.owner
        original=self.source._control_lease
        for stage in ('VALIDATED','APPLIED'):
            owner.submit({'message_id':7,'payload':message(7)['payload']},target_step=0)
            owner.poll()
            request=self.case.f.f.f.eth_request()
            reply=message(130)
            self.case.f.f.f.rx_sequence+=1
            reply['header'].update(session_id=self.source.session_id,sequence=self.case.f.f.f.rx_sequence,
                transaction_id=request['header']['transaction_id'])
            reply['payload'].update(request_sequence=request['header']['sequence'],request_message_id=7,
                stage=stage,error='OK',applied_step=0,probe_id=1007 if stage=='APPLIED' else 0)
            native=self.case.f.f.f.f
            for raw in native.src.wire.encode(reply,'UDP'):
                native.receiver.sendto(raw,native.src.feedback_endpoint)
            owner.poll()
            targets.approve(next(self.case.f.f.plan.iter_actions()),model_step=0)
            record=targets.records[-1]
            restored=_decode_record(loads(_encode_record('TARGET_AUTHORIZATION',record)))
            validate_target_record(restored,self.contract)
            self.assertEqual(restored.control_lease.owner_request_json,original.owner_request_json)
            self.assertEqual(restored.control_lease.lease_request_json,canonicalize(request))

    def test_installed_original_driver_target_replacement_refuses_snapshot(self):
        writer=self.build(with_execution=True)
        services=self.driver.services
        original=services._targets
        services._targets=None
        try:
            self.rejects('STATE',writer.flush)
            self.assertIsNone(writer._job)
        finally:
            services._targets=original

    def test_persistence_failure_retains_original_histories_and_reports_unsaved_rows(self):
        from input_simulator.evidence_archive import ObservationArchive
        writer=self.build()
        native=self.case.f.f.f
        originals=(self.source.records,native.dispatch.records,self.targets.records)
        with patch.object(ObservationArchive,'write_new_directory',side_effect=OSError('disk failure')):
            writer.flush()
            writer._job.thread.join(5)
            self.assertFalse(writer._job.thread.is_alive())
        self.rejects('RESOURCE',writer.poll)
        self.assertEqual((self.source.records,native.dispatch.records,self.targets.records),originals)
        close=writer.close()
        self.assertEqual(close.error,'RESOURCE')
        self.assertEqual(close.unpersisted_counts['TARGET_AUTHORIZATION'],len(originals[2]))

    def test_uint64_times_remain_decimal_strings_without_precision_loss(self):
        self.build()
        original=self.targets.records[0]
        shift=2**63
        status=replace(original.status,started_ns=original.status.started_ns+shift,
            completed_ns=original.status.completed_ns+shift,deadline_ns=original.status.deadline_ns+shift)
        sample=replace(original.sample,sampled_ns=original.sample.sampled_ns+shift,
            deadline_ns=original.sample.deadline_ns+shift)
        record=replace(original,status=status,sample=sample,started_ns=original.started_ns+shift,
            completed_ns=original.completed_ns+shift)
        encoded=loads(_encode_record('TARGET_AUTHORIZATION',record))
        self.assertIsInstance(encoded['record']['completed_ns'],str)
        self.assertEqual(_decode_record(encoded),record)

    def test_tampered_lifecycle_decision_and_required_status_fail_closed(self):
        self.build()
        self.targets.approve(self.case.action,model_step=0)
        from input_simulator._target_evidence import validate_target_record
        original=loads(_encode_record('TARGET_AUTHORIZATION',self.targets.records[-1]))
        changed=loads(canonicalize(original))
        changed['record']['lifecycle']['next_state']='RUNNING'
        restored=_decode_record(changed)
        self.rejects('RESOURCE',lambda:validate_target_record(restored,self.contract))
        original['record']['status']=None
        self.rejects('RESOURCE',lambda:_decode_record(original))

    def test_nested_mutable_tuple_is_not_silently_frozen_by_encoder(self):
        self.build()
        self.targets.approve(self.case.action,model_step=0)
        record=self.targets.records[-1]
        changed=replace(record,action=replace(record.action,writable_targets=list(record.action.writable_targets)))
        self.rejects('STATE',lambda:_encode_record('TARGET_AUTHORIZATION',changed))

    def test_removed_recording_attachment_cannot_allow_an_unrecorded_read(self):
        self.build()
        before=self.case.f.backend.calls
        self.targets._recording_owner=None
        try:
            self.rejects('STATE',lambda:self.targets.approve(self.case.action,model_step=0))
            self.assertEqual(self.case.f.backend.calls,before)
        finally:
            self.targets._recording_owner=self.writer

    def test_snapshot_capacity_failure_preserves_original_approval_history(self):
        writer=self.build(max_records=1)
        original=self.targets.records
        self.rejects('CAPACITY',writer.flush)
        self.assertIsNone(writer._job)
        self.assertEqual(self.targets.records,original)

    def test_tampered_epoch_ack_probe_or_request_correlation_is_rejected(self):
        writer=self.build('RESET')
        handle=self.driver.begin(self.case.action,model_step=0)
        self.case.emit(self.case.f.f.f.eth_request())
        self.driver.poll(handle,model_step=0)
        record=self.targets.epoch_records[0]
        from input_simulator._target_evidence import validate_target_record
        for name,value in (('probe_id',0),('request_sequence',999)):
            reply=loads(record.reply_json)
            reply['payload'][name]=value
            changed=replace(record,reply_json=canonicalize(reply))
            self.rejects('RESOURCE',lambda:validate_target_record(changed,self.contract))
        writer.flush()
        self.settle()
