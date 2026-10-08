import copy
from dataclasses import replace
import hashlib
import importlib
import shutil
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from icd_runtime.json_codec import canonicalize, loads
import test_evidence_archive


class RecorderTests(test_evidence_archive.ArchiveTests):
    """Actual threads/files/UDP observations, never model qualifications."""

    def recorder_module(self):
        try:
            return importlib.import_module('input_simulator.evidence_recorder')
        except ModuleNotFoundError:
            self.fail('common continuous evidence recorder missing')

    def recorder(self, **kwargs):
        module=self.recorder_module()
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'recording'
        recorder=module.ObservationRecorder(self.dispatch,self.root,run_id='run-01',inbox=self.inbox,**kwargs)
        self.addCleanup(recorder.close)
        self.writer=recorder
        return recorder

    def settle(self):
        self.writer._job.thread.join(5)
        self.assertFalse(self.writer._job.thread.is_alive(),'actual writer thread did not terminate')
        return self.writer.poll()

    def test_actual_background_persistence_reclaims_only_saved_original_prefix(self):
        header=self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        started,release=threading.Event(),threading.Event()
        cls=self.archive_module().ObservationArchive
        save=cls.write_new_directory
        def held(archive,path):
            started.set()
            if not release.wait(5): raise OSError('test worker release missing')
            return save(archive,path)
        try:
            with patch.object(cls,'write_new_directory',held):
                writer.flush()
                self.assertTrue(started.wait(2))
                self.assertFalse(writer.poll())
                self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
                self.emit(self.evidence(header))
                self.dispatch.poll()
                newer=self.inbox.records[len([r for r in original if type(r).__name__=='EvidenceRecord']):]
                highwater=self.session.last_rx_sequence
                release.set()
                self.assertTrue(self.settle())
        finally:
            release.set()
        self.assertEqual(self.inbox.records,newer)
        self.assertEqual(self.session.records,())
        self.assertEqual(self.dispatch.records,())
        self.assertEqual(self.session.last_rx_sequence,highwater)
        self.assertEqual(self.inbox.request_count,1)
        chain=self.recorder_module().read_observation_chain(self.root,self.contract)
        self.assertEqual(chain.segments[0].records,original)
        self.assertFalse(chain.execution_ready)
        self.assertFalse(chain.evidence_complete)

    def test_two_actual_segments_have_continuous_counts_hash_and_original_bytes(self):
        header=self.observed()
        writer=self.recorder()
        first=self.session.records+self.dispatch.records+self.inbox.records
        writer.flush()
        self.settle()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        second=self.inbox.records
        writer.flush()
        self.settle()
        chain=self.recorder_module().read_observation_chain(self.root,self.contract)
        self.assertEqual(tuple(r for s in chain.segments for r in s.records),first+second)
        self.assertEqual(len(chain.segments),2)
        links=[loads(raw) for raw in chain.descriptor_jsons]
        self.assertEqual(links[0]['previous_sha256'],'0'*64)
        self.assertEqual(links[1]['previous_sha256'],hashlib.sha256(chain.descriptor_jsons[0]).hexdigest())
        self.assertEqual(links[1]['stream_start_counts'],links[0]['stream_end_counts'])
        self.assertEqual(writer.committed_segments,2)
        self.assertFalse(writer.execution_ready)

    def test_record_ownership_blocks_all_three_side_drain_paths(self):
        self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        for action in (self.dispatch.drain_records,self.inbox.drain_records,self.session.drain_records):
            self.rejects('STATE',action)
        self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertEqual(writer.committed_segments,0)

    def test_writer_failure_keeps_original_records_and_incomplete_owned_directory(self):
        self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        with patch.object(self.archive_module().ObservationArchive,'write_new_directory',side_effect=OSError('disk full')):
            writer.flush()
            self.rejects('RESOURCE',self.settle)
        self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertEqual(writer.status,'FAILED')
        self.assertEqual(writer.committed_segments,0)
        self.rejects('STATE',writer.flush)
        close=writer.close()
        self.assertEqual(close.error,'RESOURCE')
        self.assertTrue(close.worker_stopped)
        self.assertEqual(sum(close.unpersisted_counts.values()),len(original))

    def test_saved_prefix_identity_mutation_refuses_atomic_reclaim(self):
        self.observed()
        writer=self.recorder()
        writer.flush()
        writer._job.thread.join(5)
        self.inbox._records.pop(0)
        source,dispatch,inbox=self.session.records,self.dispatch.records,self.inbox.records
        self.rejects('STATE',writer.poll)
        self.assertEqual((source,dispatch,inbox),(self.session.records,self.dispatch.records,self.inbox.records))
        self.assertEqual(writer.committed_segments,0)

    def test_successful_reclaim_frees_exact_record_bytes_not_context_or_pending_reservations(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        writer=self.recorder()
        pending=self.dispatch.pending_count
        reserved=(self.dispatch._reserved_count,self.dispatch._reserved_bytes)
        context=self.inbox._context_bytes
        writer.flush()
        self.settle()
        self.assertEqual(self.dispatch.pending_count,pending)
        self.assertEqual((self.dispatch._reserved_count,self.dispatch._reserved_bytes),reserved)
        self.assertEqual(self.session._record_bytes,0)
        self.assertEqual((self.dispatch._used_count,self.dispatch._used_bytes),(0,0))
        self.assertEqual(self.inbox._record_bytes,0)
        self.assertEqual(self.inbox._context_bytes,context)
        self.assertEqual(self.inbox.request_count,1)
        self.emit(self.evidence(header))
        self.dispatch.poll()
        self.assertTrue(self.completed()[-1].correlation_matched)

    def test_owner_busy_after_worker_completion_can_retry_same_job_without_rewrite(self):
        self.observed()
        writer=self.recorder()
        writer.flush()
        job=writer._job
        job.thread.join(5)
        self.dispatch._lock.acquire()
        try:
            self.rejects('STATE',writer.poll)
        finally:
            self.dispatch._lock.release()
        self.assertIs(writer._job,job)
        self.assertTrue(writer.poll())
        self.assertEqual(writer.committed_segments,1)

    def test_limits_fail_before_worker_start_or_any_reclaim(self):
        self.observed()
        writer=self.recorder(max_total_bytes=1)
        original=self.session.records+self.dispatch.records+self.inbox.records
        self.rejects('CAPACITY',writer.flush)
        self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertIsNone(writer._job)
        self.assertEqual(writer.committed_segments,0)

    def test_maximum_segments_rejects_later_flush_without_losing_new_rx(self):
        header=self.observed()
        writer=self.recorder(max_segments=1)
        writer.flush()
        self.settle()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        original=self.inbox.records
        self.rejects('CAPACITY',writer.flush)
        self.assertEqual(self.inbox.records,original)
        self.assertEqual(writer.committed_segments,1)

    def test_duplicate_owner_invalid_limits_and_existing_root_do_not_replace_recording(self):
        self.setup_inbox()
        module=self.recorder_module()
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            for keyword,values in {'max_segments':(False,1.0,0,100001),
                                   'max_records':(True,1.0,0,100001),
                                   'max_bytes':(False,0,256*1024*1024+1),
                                   'max_total_bytes':(True,0,1024**3+1)}.items():
                for value in values:
                    self.rejects('CAPACITY',lambda:module.ObservationRecorder(self.dispatch,base/'new',run_id='run',inbox=self.inbox,**{keyword:value}))
            self.assertFalse((base/'new').exists())
            self.rejects('RESOURCE',lambda:module.ObservationRecorder(self.dispatch,base,run_id='run',inbox=self.inbox))
        writer=self.recorder()
        self.rejects('STATE',lambda:module.ObservationRecorder(self.dispatch,self.root.parent/'second',run_id='run',inbox=self.inbox))
        self.assertEqual(writer.status,'LIVE')

    def test_timeout_close_retains_actual_thread_handle_and_original_owner_until_retry(self):
        self.observed()
        writer=self.recorder()
        started,release=threading.Event(),threading.Event()
        cls=self.archive_module().ObservationArchive
        save=cls.write_new_directory
        def held(archive,path):
            started.set()
            if not release.wait(5): raise OSError('test release missing')
            return save(archive,path)
        try:
            with patch.object(cls,'write_new_directory',held):
                writer.flush()
                self.assertTrue(started.wait(2))
                job=writer._job
                self.rejects('TIMEOUT',lambda:writer.close(timeout=0))
                self.assertIs(writer._job,job)
                self.assertTrue(job.thread.is_alive())
                self.rejects('STATE',self.dispatch.drain_records)
                release.set()
                close=writer.close(timeout=5)
        finally:
            release.set()
        self.assertTrue(close.worker_stopped)
        self.assertEqual(writer.status,'CLOSED')
        self.assertEqual(writer.committed_segments,1)

    def test_single_pending_job_and_strict_close_timeout_types(self):
        self.observed()
        writer=self.recorder()
        for value in (False,-1,float('inf'),float('nan'),31,'1'):
            self.rejects('SCHEMA',lambda:writer.close(timeout=value))
        started,release=threading.Event(),threading.Event()
        cls=self.archive_module().ObservationArchive
        save=cls.write_new_directory
        def held(archive,path):
            started.set()
            if not release.wait(5): raise OSError('test release missing')
            return save(archive,path)
        try:
            with patch.object(cls,'write_new_directory',held):
                writer.flush()
                self.assertTrue(started.wait(2))
                self.rejects('BUFFER_FULL',writer.flush)
                release.set()
                self.settle()
        finally:
            release.set()

    def test_thread_start_failure_preserves_records_and_retains_explicit_failure(self):
        self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        with patch.object(threading.Thread,'start',side_effect=RuntimeError('actual start failed')):
            self.rejects('STATE',writer.flush)
        self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertEqual(writer.status,'FAILED')
        self.assertTrue(writer.close().worker_stopped)

    def test_local_close_reports_unsaved_records_and_releases_only_local_drain_guard(self):
        self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        sid=self.session.session_id
        close=writer.close()
        self.assertEqual(sum(close.unpersisted_counts.values()),len(original))
        self.assertEqual(self.session.session_id,sid)
        self.assertEqual(self.session._state,'LIVE')
        self.assertEqual(self.dispatch.drain_records(),tuple(r for r in original if type(r).__name__=='DispatchRecord'))
        self.assertIs(writer.close(),close)

    def test_chain_rejects_missing_reordered_or_rehashed_foreign_identity_counts_and_flags(self):
        header=self.observed()
        writer=self.recorder()
        writer.flush()
        self.settle()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        writer.flush()
        self.settle()
        module=self.recorder_module()
        commit=self.root/'segment-000001.json'
        original=commit.read_bytes()
        for changes in ({'index':0},{'run_id':'other'},{'previous_sha256':'0'*64},
                        {'archive_manifest_sha256':'0'*64},{'execution_ready':True},
                        {'stream_start_counts':{'SOURCE':0,'DISPATCH':0,'INBOX':0}}):
            with self.subTest(changes=changes):
                value=loads(original)
                value.update(changes)
                commit.write_bytes(canonicalize(value))
                self.rejects('RESOURCE',lambda:module.read_observation_chain(self.root,self.contract))
                commit.write_bytes(original)
        commit.unlink()
        self.rejects('RESOURCE',lambda:module.read_observation_chain(self.root,self.contract))

    def test_chain_capacity_and_uncommitted_tail_fail_closed(self):
        self.observed()
        writer=self.recorder()
        writer.flush()
        self.settle()
        module=self.recorder_module()
        for kwargs in ({'max_bytes':1},{'max_records':1},{'max_segments':True}):
            self.rejects('CAPACITY',lambda:module.read_observation_chain(self.root,self.contract,**kwargs))
        (self.root/'segment-000001').mkdir()
        self.rejects('RESOURCE',lambda:module.read_observation_chain(self.root,self.contract))

    def test_original_recorder_prevents_replacing_closed_dispatcher_until_detached(self):
        self.observed()
        writer=self.recorder()
        self.dispatch.close()
        from input_simulator.dispatch import UDPDispatcher
        self.rejects('STATE',lambda:UDPDispatcher(self.session))
        self.assertIsNone(self.session._dispatcher)
        writer.close()
        replacement=UDPDispatcher(self.session)
        self.addCleanup(replacement.close)
        self.assertIs(self.session._dispatcher,replacement)

    def test_deleted_final_segment_requires_trusted_count_tip_or_local_close_anchor(self):
        header=self.observed()
        writer=self.recorder()
        writer.flush()
        self.settle()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        writer.flush()
        self.settle()
        module=self.recorder_module()
        with tempfile.TemporaryDirectory() as root:
            truncated=Path(root)/'truncated'
            truncated.mkdir()
            shutil.copytree(self.root/'segment-000000',truncated/'segment-000000')
            for suffix in ('.json','.pending.json'):
                shutil.copy2(self.root/f'segment-000000{suffix}',truncated/f'segment-000000{suffix}')
            self.rejects('RESOURCE',lambda:module.read_observation_chain(truncated,self.contract,
                         expected_segments=2,expected_tip_sha256=writer.tip_sha256))
            writer.close()
            for name in ('close.json','close.pending.json'):
                shutil.copy2(self.root/name,truncated/name)
            self.rejects('RESOURCE',lambda:module.read_observation_chain(truncated,self.contract))
        chain=module.read_observation_chain(self.root,self.contract)
        self.assertTrue(chain.locally_closed)
        self.assertEqual(len(chain.segments),2)
        self.assertFalse(chain.evidence_complete)

    def test_chain_trusted_anchor_types_are_strict_and_missing_half_anchor_rejected(self):
        self.observed()
        writer=self.recorder()
        writer.flush()
        self.settle()
        module=self.recorder_module()
        for kwargs in ({'expected_segments':True,'expected_tip_sha256':'0'*64},
                       {'expected_segments':1}, {'expected_tip_sha256':'0'*64},
                       {'expected_segments':1,'expected_tip_sha256':'X'*64}):
            self.rejects('SCHEMA',lambda:module.read_observation_chain(self.root,self.contract,**kwargs))

    def test_readback_tampering_before_reclaim_never_deletes_original_records(self):
        self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        writer.flush()
        writer._job.thread.join(5)
        (self.root/'segment-000000'/'records.jsonl').write_bytes(b'corrupt')
        self.rejects('RESOURCE',writer.poll)
        self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertEqual(writer.committed_segments,0)

    def test_closed_recording_checkpoint_failure_keeps_memory_and_explicit_close_error(self):
        self.observed()
        writer=self.recorder()
        original=self.session.records+self.dispatch.records+self.inbox.records
        module=self.recorder_module()
        with patch.object(module.os,'fsync',side_effect=OSError('close checkpoint fsync failed')):
            close=writer.close()
        self.assertEqual(close.error,'RESOURCE')
        self.assertEqual(original,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertFalse((self.root/'close.json').exists())

    def test_closed_checkpoint_strict_counts_flags_and_hash_reject_even_matching_pending(self):
        self.observed()
        writer=self.recorder()
        writer.flush()
        self.settle()
        writer.close()
        module=self.recorder_module()
        original=(self.root/'close.json').read_bytes()
        self.rejects('CAPACITY',lambda:module.read_observation_chain(self.root,self.contract,
                     max_bytes=writer._used_bytes))
        for changes in ({'committed_segments':True},{'committed_segments':2},
                        {'tip_sha256':'0'*64},{'stream_counts':dict.fromkeys(module.STREAMS,0)},
                        {'unpersisted_counts':dict.fromkeys(module.STREAMS,False)},
                        {'worker_stopped':False},{'execution_ready':True},{'error':'PASS'},
                        {'persisted_segment_bytes':1},{'unknown':0}):
            with self.subTest(changes=changes):
                value=loads(original)
                value.update(changes)
                (self.root/'close.json').write_bytes(canonicalize(value))
                (self.root/'close.pending.json').write_bytes(canonicalize(value))
                self.rejects('RESOURCE',lambda:module.read_observation_chain(self.root,self.contract))
                (self.root/'close.json').write_bytes(original)
                (self.root/'close.pending.json').write_bytes(original)
        self.rejects('RESOURCE',lambda:module.read_observation_chain(self.root,self.contract,
                     expected_segments=1,expected_tip_sha256='0'*64))
        chain=module.read_observation_chain(self.root,self.contract,
                     expected_segments=1,expected_tip_sha256=writer.tip_sha256)
        self.assertTrue(chain.locally_closed)

    def test_close_owner_busy_after_checkpoint_retries_detach_without_rewriting(self):
        self.observed()
        writer=self.recorder()
        module=self.recorder_module()
        link=module.os.link
        def hold_after_link(source,target):
            result=link(source,target)
            self.dispatch._lock.acquire()
            return result
        try:
            with patch.object(module.os,'link',hold_after_link):
                self.rejects('STATE',writer.close)
            self.assertIs(self.session._observation_recorder,writer)
            checkpoint=(self.root/'close.json').read_bytes()
            self.rejects('STATE',writer.flush)
        finally:
            if self.dispatch._lock.locked():
                self.dispatch._lock.release()
        close=writer.close()
        self.assertIsNone(close.error)
        self.assertEqual((self.root/'close.json').read_bytes(),checkpoint)
        self.assertIsNone(self.session._observation_recorder)

    def test_close_checkpoint_and_reader_are_included_in_total_byte_budget(self):
        self.observed()
        writer=self.recorder()
        writer.flush()
        self.settle()
        segment_bytes=writer._used_bytes
        writer._max_total_bytes=segment_bytes
        close=writer.close()
        self.assertEqual(close.error,'CAPACITY')
        self.assertFalse((self.root/'close.json').exists())

    def test_equal_record_replacement_after_snapshot_is_not_a_trusted_identity_prefix(self):
        self.observed()
        writer=self.recorder()
        module=self.recorder_module()
        prepare=module._prepare_evidence_snapshot
        original=self.session._records[0]
        def substituted(*args,**kwargs):
            snapshot=prepare(*args,**kwargs)
            self.session._records[0]=replace(original)
            return snapshot
        with patch.object(module,'_prepare_evidence_snapshot',substituted):
            writer.flush()
        self.assertIsNot(self.session._records[0],original)
        source,dispatch,inbox=self.session.records,self.dispatch.records,self.inbox.records
        self.rejects('STATE',self.settle)
        self.assertEqual((source,dispatch,inbox),(self.session.records,self.dispatch.records,self.inbox.records))
        self.assertEqual(writer.committed_segments,0)


for _name in dir(test_evidence_archive.ArchiveTests):
    if _name.startswith('test_') and _name not in RecorderTests.__dict__:
        setattr(RecorderTests,_name,None)
