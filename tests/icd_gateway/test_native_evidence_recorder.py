"""Actual native record persistence/ownership; no model or hardware claims."""

from pathlib import Path
from dataclasses import replace
import inspect
import tempfile
import threading
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
import test_native_evidence_archive as archive_cases
import test_scapy_source as scapy_cases
import test_native_scenario_actions as action_cases
from input_simulator.evidence_recorder import ObservationRecorder, read_observation_chain


class NativeRecorderTests(GatewayTest):
    def native(self):
        self.case = archive_cases.NativeArchiveTests('runTest')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.f = self.case.native()
        return self.f

    def writer(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)/'native-recording'
        writer = ObservationRecorder(self.f.dispatch,self.root,run_id='run-01',
                                    native=True,coordinator=self.f.coordinator,**kwargs)
        self.addCleanup(writer.close)
        self.w = writer
        return writer

    def settle(self):
        self.w._job.thread.join(5)
        self.assertFalse(self.w._job.thread.is_alive())
        return self.w.poll()

    def send_next(self, sequence=3):
        plan = self.f.plan()
        self.f.coordinator.send_can(self.f.sender,plan)
        self.f.f.consume(plan)
        self.f.f.emit(plan,sequence=sequence)
        self.f.coordinator.receive_can(self.f.sender,plan,timeout=0.2)

    def test_required_native_continuous_recorder(self):
        self.native()
        self.assertIn('native',inspect.signature(ObservationRecorder).parameters,
                      'actual native continuous recorder entry missing')
        writer = self.writer()
        original = self.case.prepare().records
        writer.flush()
        self.assertTrue(self.settle())
        self.assertEqual(self.f.sender.records,())
        self.assertEqual(self.f.sender._bytes,0)
        self.assertEqual(self.f.f.session.records,())
        chain = read_observation_chain(self.root,self.contract)
        self.assertEqual(chain.segments[0].records,original)
        self.assertEqual(loads(chain.descriptor_jsons[0])['format'],'HIL_OBSERVATION_CHAIN_LINK_2')
        close = writer.close()
        self.assertEqual(set(close.unpersisted_counts),{'SOURCE','DISPATCH','INBOX','CAN','L2'})
        self.assertTrue(read_observation_chain(self.root,self.contract).locally_closed)
        self.assertFalse(chain.evidence_complete)

    def test_native_sending_continues_while_real_writer_is_busy_and_prefix_only_reclaimed(self):
        self.native()
        writer = self.writer()
        original = self.case.prepare().records
        first_count = len(self.f.sender.records)
        started,release = threading.Event(),threading.Event()
        cls = self.case.module.ObservationArchive
        save = cls.write_new_directory
        def held(archive,path):
            started.set()
            if not release.wait(5):
                raise OSError('writer release missing')
            return save(archive,path)
        try:
            with patch.object(cls,'write_new_directory',held):
                writer.flush()
                self.assertTrue(started.wait(2))
                self.send_next()
                newer = self.f.sender.records[first_count:]
                highwater = self.f.f.session.last_rx_sequence
                pending = self.f.sender.pending_count
                self.assertFalse(writer.poll())
                release.set()
                self.assertTrue(self.settle())
        finally:
            release.set()
        self.assertEqual(self.f.sender.records,newer)
        self.assertEqual(self.f.sender.pending_count,pending)
        self.assertEqual(self.f.f.session.last_rx_sequence,highwater)
        self.assertEqual(self.f.sender._bytes,sum(self.f.sender._size(r) for r in newer))
        self.assertEqual(read_observation_chain(self.root,self.contract).segments[0].records,original)
        writer.flush()
        self.settle()
        writer.close()
        chain = read_observation_chain(self.root,self.contract)
        self.assertEqual(len(chain.segments),2)
        links = tuple(loads(r) for r in chain.descriptor_jsons)
        self.assertEqual(links[1]['stream_start_counts'],links[0]['stream_end_counts'])

    def test_all_native_side_drains_are_blocked_but_send_is_not(self):
        self.native()
        self.writer()
        original = self.f.sender.records
        self.rejects('STATE',lambda:self.f.coordinator.drain_can(self.f.sender))
        self.rejects('STATE',self.f.sender.drain_records)
        self.rejects('STATE',self.f.dispatch.drain_records)
        self.rejects('STATE',self.f.f.session.drain_records)
        self.assertEqual(self.f.sender.records,original)
        self.send_next()

    def test_native_accounting_failure_reclaims_no_other_stream(self):
        self.native()
        writer = self.writer()
        writer.flush()
        writer._job.thread.join(5)
        original = self.case.prepare().records
        self.f.sender._bytes -= 1
        self.rejects('STATE',writer.poll)
        self.assertEqual(self.case.prepare().records,original)
        self.assertEqual(writer.committed_segments,0)

    def test_native_backend_close_does_not_lose_final_records(self):
        self.native()
        writer = self.writer()
        self.f.coordinator.close()
        self.f.dispatch.close()
        writer.flush()
        self.assertTrue(self.settle())
        close = writer.close()
        self.assertIsNone(close.error)
        self.assertEqual(sum(close.unpersisted_counts.values()),0)
        self.assertTrue(read_observation_chain(self.root,self.contract).locally_closed)

    def scapy_writer(self):
        f = scapy_cases.ScapySourceTests('runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.live()
        from input_simulator.dispatch import UDPDispatcher
        dispatch = UDPDispatcher(f.session)
        self.addCleanup(dispatch.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)/'l2-recording'
        self.w = ObservationRecorder(dispatch,self.root,run_id='run-01',native=True)
        self.addCleanup(self.w.close)
        return f,dispatch,self.w

    def test_actual_scapy_two_segments_reclaim_l2_bytes_and_readback_close(self):
        f,dispatch,writer = self.scapy_writer()
        first = f.session.records+f.src.l2_records
        writer.flush()
        self.settle()
        self.assertEqual(f.src.l2_records,())
        self.assertEqual(f.src._l2_bytes,0)
        self.rejects('STATE',f.src.drain_l2_records)
        header = dispatch.submit({'message_id':7,'payload':message(7)['payload']},target_step=100)
        dispatch.poll()
        f.receive_frame()
        reply = message(130)
        reply['header'].update(session_id=73,sequence=2,transaction_id=header.transaction_id)
        reply['payload'].update(request_sequence=header.sequence,request_message_id=7,
                                stage='FAILED',error='TARGET_MISSING')
        for packet in f.src.wire.encode(reply,'UDP'):
            f.receiver.sendto(packet,f.src.feedback_endpoint)
        dispatch.poll()
        second = f.session.records+dispatch.records+f.src.l2_records
        writer.flush()
        self.settle()
        writer.close()
        chain = read_observation_chain(self.root,self.contract)
        self.assertEqual(tuple(r for a in chain.segments for r in a.records),first+second)
        self.assertEqual(f.src._l2_bytes,0)
        self.assertTrue(chain.locally_closed)
        self.assertFalse(chain.evidence_complete)

    def test_scapy_prefix_accounting_failure_retains_source_and_l2(self):
        f,dispatch,writer = self.scapy_writer()
        writer.flush()
        writer._job.thread.join(5)
        original = f.session.records,f.src.l2_records
        f.src._l2_bytes -= 1
        self.rejects('STATE',writer.poll)
        self.assertEqual((f.session.records,f.src.l2_records),original)
        self.assertEqual(writer.committed_segments,0)

    def test_writer_failure_retains_native_bytes_and_unpersisted_counts(self):
        self.native()
        writer = self.writer()
        original = self.case.prepare().records
        with patch.object(self.case.module.ObservationArchive,'write_new_directory',side_effect=OSError('disk full')):
            writer.flush()
            self.rejects('RESOURCE',self.settle)
        self.assertEqual(self.case.prepare().records,original)
        close = writer.close()
        self.assertEqual(close.error,'RESOURCE')
        self.assertEqual(close.unpersisted_counts['CAN'],len(self.f.sender.records))
        self.assertEqual(writer.committed_segments,0)

    def test_all_native_locks_reject_flush_without_allocating_worker(self):
        self.native()
        writer = self.writer()
        before = self.case.prepare().records
        for lock in (self.f.coordinator._lock,self.f.dispatch._lock,self.f.sender._lock,
                     self.f.f.builder._lock,self.f.f.session._lock):
            lock.acquire()
            try:
                self.rejects('STATE',writer.flush)
                self.assertIsNone(writer._job)
            finally:
                lock.release()
        self.assertEqual(self.case.prepare().records,before)

    def test_recording_cannot_adopt_replaced_sender_binding_before_tx(self):
        self.native()
        plan = self.f.plan()
        self.writer()
        original = self.f.sender.binding
        rows = self.f.sender.records
        try:
            self.f.sender.binding = replace(original)
            self.rejects('STATE',lambda:self.f.coordinator.send_can(self.f.sender,plan))
            self.assertEqual(self.f.sender.records,rows)
        finally:
            self.f.sender.binding = original

    def test_four_sender_prefixes_remain_valid_when_first_channel_appends(self):
        case = archive_cases.NativeArchiveTests('runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        f,dispatch,coordinator,senders = case.four_senders()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)/'four-recording'
        writer = ObservationRecorder(dispatch,root,run_id='run-01',native=True,coordinator=coordinator)
        self.addCleanup(writer.close)
        original = tuple(s.records for s in senders)
        writer.flush()
        writer._job.thread.join(5)
        self.assertFalse(writer._job.thread.is_alive())
        plan = coordinator.prepare_can(senders[0],{'message_id':7,'payload':message(7)['payload']},target_step=100)
        coordinator.send_can(senders[0],plan)
        f.consume(plan)
        newer = senders[0].records[len(original[0]):]
        try:
            committed = writer.poll()
        except ICDError as error:
            self.fail(f'intact individual CAN prefixes were falsely rejected: {error.code}')
        self.assertTrue(committed)
        self.assertEqual(senders[0].records,newer)
        self.assertTrue(all(s.records == () for s in senders[1:]))
        self.assertEqual(senders[0]._bytes,sum(senders[0]._size(r) for r in newer))
        self.assertTrue(all(s._bytes == 0 for s in senders[1:]))
        saved = read_observation_chain(root,self.contract).segments[0]
        self.assertEqual(saved.manifest['stream_counts']['CAN'],sum(len(rows) for rows in original))

    def test_all_five_actual_streams_share_original_can_scapy_actions_and_persistent_readback(self):
        f = action_cases.NativeScenarioActionTests('runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        inbox = f.dispatch.enable_evidence_collection()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)/'five-stream-recording'
        writer = ObservationRecorder(f.dispatch,root,run_id='run-01',native=True,coordinator=f.owner,inbox=inbox)
        self.addCleanup(writer.close)
        handler = f.build([action_cases.send('can',0,7,link_id='CANT'),action_cases.send('eth',0,10)])
        handler.preflight()
        first = handler.begin(f.action(0),model_step=0,target_step=100)
        can_request = f.can_request()
        second = handler.begin(f.action(1),model_step=0,target_step=100)
        eth_request = f.eth_request()
        f.reply(can_request,'CANFD')
        f.reply(eth_request,'UDP')
        handler.poll(first,model_step=0)
        handler.poll(second,model_step=0)
        original = f.f.session.records+f.dispatch.records+inbox.records+f.sender.records+f.f.src.l2_records
        writer.flush()
        writer._job.thread.join(5)
        self.assertFalse(writer._job.thread.is_alive())
        self.assertTrue(writer.poll())
        close = writer.close()
        chain = read_observation_chain(root,self.contract)
        self.assertEqual(chain.segments[0].records,original)
        self.assertTrue(all(n > 0 for n in chain.segments[0].manifest['stream_counts'].values()))
        self.assertEqual(sum(close.unpersisted_counts.values()),0)
        self.assertEqual((f.sender._bytes,f.f.src._l2_bytes),(0,0))
        self.assertFalse(chain.evidence_complete)
