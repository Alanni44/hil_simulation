import base64
import copy
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import importlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
import test_evidence


class ArchiveTests(test_evidence.EvidenceTests):
    """Original UDP observations are saved, not qualified model evidence."""

    def archive_module(self):
        try:
            return importlib.import_module('input_simulator.evidence_archive')
        except ModuleNotFoundError:
            self.fail('common original evidence archive missing')

    def observed(self):
        self.setup_inbox()
        header = self.watch()
        request = self.transmit()[0]
        self.response(request)
        self.dispatch.poll()
        self.emit(self.evidence(header, event_id='wrong'))
        self.dispatch.poll()
        self.emit(self.evidence(header))
        self.dispatch.poll()
        return header

    def prepare(self, **kwargs):
        return self.archive_module().prepare_evidence_archive(self.dispatch, run_id='run-01', inbox=self.inbox, **kwargs)

    def test_actual_snapshot_roundtrips_all_original_records_without_drain_or_qualification(self):
        self.observed()
        original = self.session.records + self.dispatch.records + self.inbox.records
        counts = (self.session.last_rx_sequence, self.inbox.request_count, self.dispatch.pending_count)
        archive = self.prepare()
        self.assertEqual(archive.records, original)
        self.assertFalse(archive.execution_ready)
        self.assertEqual(archive.qualification_status, 'NOT_EVALUATED')
        self.assertFalse(archive.manifest['evidence_complete'])
        self.assertEqual(archive.manifest['record_count'], len(original))
        self.assertEqual(counts, (self.session.last_rx_sequence, self.inbox.request_count, self.dispatch.pending_count))
        self.assertEqual(original, self.session.records + self.dispatch.records + self.inbox.records)

    def test_actual_new_directory_readback_and_existing_directory_not_overwritten(self):
        self.observed()
        archive = self.prepare()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'owned'
            manifest = archive.write_new_directory(target)
            saved = self.archive_module().read_evidence_archive(target, self.contract)
            self.assertEqual(manifest, target / 'manifest.json')
            self.assertEqual(saved.records_jsonl, archive.records_jsonl)
            self.assertEqual(saved.manifest_json, archive.manifest_json)
            self.assertEqual(saved.records, archive.records)
            before = {p.name:p.read_bytes() for p in target.iterdir()}
            self.rejects('RESOURCE', lambda:archive.write_new_directory(target))
            self.assertEqual(before, {p.name:p.read_bytes() for p in target.iterdir()})

    def test_snapshot_is_detached_immutable_and_keeps_new_records_out(self):
        header = self.observed()
        archive = self.prepare()
        rows = archive.records
        self.emit(self.evidence(header))
        self.dispatch.poll()
        self.assertEqual(archive.records, rows)
        self.assertLess(len(rows),len(self.session.records+self.dispatch.records+self.inbox.records))
        detached = archive.manifest
        detached['evidence_complete'] = True
        self.assertFalse(archive.manifest['evidence_complete'])
        with self.assertRaises(FrozenInstanceError):
            archive.records_jsonl = b''

    def test_source_and_dispatcher_owner_locks_reject_concurrent_snapshot(self):
        self.setup_inbox()
        for lock in (self.dispatch._lock,self.session._lock):
            lock.acquire()
            try:
                self.rejects('STATE',self.prepare)
            finally:
                lock.release()
        self.assertTrue(self.prepare().records)

    def test_exact_record_and_byte_bounds_and_strict_limit_types(self):
        self.observed()
        archive = self.prepare()
        size = len(archive.records_jsonl)+len(archive.manifest_json)
        self.assertEqual(self.prepare(max_bytes=size).records,archive.records)
        self.rejects('CAPACITY', lambda:self.prepare(max_bytes=size-1))
        self.rejects('CAPACITY', lambda:self.prepare(max_records=len(archive.records)-1))
        for value in (True,1.0,0,-1,100001):
            self.rejects('CAPACITY', lambda:self.prepare(max_records=value))
        for value in (True,1.0,0,-1,256*1024*1024+1):
            self.rejects('CAPACITY', lambda:self.prepare(max_bytes=value))

    def test_explicit_run_identity_is_not_a_path_or_current_authorization(self):
        self.setup_inbox()
        module = self.archive_module()
        for value in (None,False,12,'','x'*129,'\ud800'):
            self.rejects('SCHEMA',lambda:module.prepare_evidence_archive(self.dispatch,run_id=value,inbox=self.inbox))
        archive = module.prepare_evidence_archive(self.dispatch,run_id='../run',inbox=self.inbox)
        self.assertEqual(archive.manifest['run_id'],'../run')
        self.assertFalse(archive.execution_ready)

    def test_closed_inbox_and_dispatcher_failure_records_remain_archivable(self):
        self.setup_inbox()
        self.watch()
        self.dispatch.close()
        self.inbox.close()
        archive = self.prepare()
        self.assertEqual(archive.records,self.session.records+self.dispatch.records+self.inbox.records)
        self.assertTrue(any(getattr(r,'kind',None)=='CANCEL' for r in archive.records))
        self.assertFalse(archive.manifest['evidence_complete'])

    def test_foreign_inbox_rejected_before_snapshot(self):
        self.setup_inbox()
        fake = copy.copy(self.inbox)
        fake._owner = object()
        self.rejects('STATE',lambda:self.archive_module().prepare_evidence_archive(self.dispatch,run_id='run',inbox=fake))

    def test_uint64_strings_and_packed_negative_zero_bytes_not_normalized(self):
        self.setup_inbox()
        from input_simulator.evidence import EvidenceRecord
        from input_simulator.session import _snapshot_message
        raw = _snapshot_message({'value':-0.0,'integer':1,'float':1.0})
        row = EvidenceRecord('EVIDENCE',2**64-1,'ETH_0',('127.0.0.1',36101),reply_json=raw,error='STATE')
        self.inbox._record(row)
        archive = self.prepare()
        self.assertEqual(archive.records[-1],row)
        text = archive.records_jsonl.decode('ascii')
        self.assertIn('"received_ns":"18446744073709551615"',text)
        self.assertIn(base64.b64encode(raw).decode('ascii'),text)
        self.assertEqual(archive.records[-1].reply_json,raw)

    def test_fsync_or_publication_failure_retains_incomplete_directory_and_memory(self):
        self.observed()
        archive = self.prepare()
        original = self.inbox.records
        module = self.archive_module()
        for name in ('fsync','link'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as root:
                target = Path(root)/'owned'
                with patch.object(module.os,name,side_effect=OSError('actual persistence failure')):
                    self.rejects('RESOURCE',lambda:archive.write_new_directory(target))
                self.assertTrue(target.exists())
                self.assertFalse((target/'manifest.json').exists())
                self.assertEqual(self.inbox.records,original)
                self.rejects('RESOURCE',lambda:module.read_evidence_archive(target,self.contract))

    def test_corrupt_readback_never_publishes_manifest(self):
        self.observed()
        archive = self.prepare()
        module = self.archive_module()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'owned'
            with patch.object(module,'_read_bounded',return_value=b'corrupt'):
                self.rejects('RESOURCE',lambda:archive.write_new_directory(target))
            self.assertFalse((target/'manifest.json').exists())

    def test_tampered_missing_or_extra_files_and_wrong_baseline_fail_readback(self):
        self.observed()
        archive = self.prepare()
        module = self.archive_module()
        for mode in ('hash','missing','extra','baseline','qualification','ready','count'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                target = Path(root)/'owned'
                archive.write_new_directory(target)
                if mode=='hash':
                    (target/'records.jsonl').write_bytes(b'corrupt')
                elif mode=='missing':
                    (target/'manifest.json').unlink()
                elif mode=='extra':
                    (target/'extra.bin').write_bytes(b'x')
                else:
                    manifest=archive.manifest
                    key={'baseline':'baseline_sha256','qualification':'qualification_status','ready':'execution_ready','count':'record_count'}[mode]
                    manifest[key]={'baseline':'0'*64,'qualification':'PASS','ready':True,'count':999}[mode]
                    # Replacing both hard-linked names in-place changes the shared bytes.
                    (target/'manifest.json').write_bytes(canonicalize(manifest))
                self.rejects('RESOURCE',lambda:module.read_evidence_archive(target,self.contract))

    def test_rehashed_unknown_record_fields_and_bad_base64_are_not_accepted(self):
        self.observed()
        archive = self.prepare()
        module = self.archive_module()
        for mode in ('extra','base64','time','kind','qualification'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                target=Path(root)/'owned'
                archive.write_new_directory(target)
                rows=[loads(line) for line in archive.records_jsonl.splitlines()]
                row=next(r for r in rows if r['stream']=='INBOX')
                if mode=='extra': row['record']['extra']=1
                elif mode=='base64': row['record']['wire_data']='not base64'
                elif mode=='time': row['record']['received_ns']=123
                elif mode=='kind': row['record']['kind']='APPLIED'
                else: row['record']['qualification_status']='PASS'
                raw=b''.join(canonicalize(r)+b'\n' for r in rows)
                manifest=archive.manifest
                manifest['records_sha256']=hashlib.sha256(raw).hexdigest()
                manifest['records_size_bytes']=len(raw)
                (target/'records.jsonl').write_bytes(raw)
                (target/'manifest.json').write_bytes(canonicalize(manifest))
                self.rejects('RESOURCE',lambda:module.read_evidence_archive(target,self.contract))

    def test_readback_size_limit_and_record_limit_are_fail_closed(self):
        self.observed()
        archive=self.prepare()
        module=self.archive_module()
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'owned'
            archive.write_new_directory(target)
            self.rejects('CAPACITY',lambda:module.read_evidence_archive(target,self.contract,max_bytes=1))
            self.rejects('CAPACITY',lambda:module.read_evidence_archive(target,self.contract,max_records=1))

    def test_actual_bad_crc_and_full_oversize_datagrams_are_saved_byte_exact(self):
        self.setup_inbox()
        header=self.watch()
        self.transmit()
        packet=bytearray(self.source.wire.encode(self.evidence(header),'UDP')[0])
        packet[-1]^=1
        oversize=b'x'*10000
        for raw in (bytes(packet),oversize):
            self.gateway.socket.sendto(raw,self.source.feedback_endpoint)
        self.dispatch.poll()
        archive=self.prepare()
        actual=[r.wire_data for r in archive.records if getattr(r,'kind',None)=='DATAGRAM']
        self.assertEqual(actual,[bytes(packet),oversize])
        self.assertEqual(archive.manifest['dropped_feedback'],2)

    def test_no_inbox_snapshot_never_invents_missing_original_rx(self):
        self.setup_peer()
        module=self.archive_module()
        archive=module.prepare_evidence_archive(self.dispatch,run_id='run-01')
        self.assertEqual(archive.records,self.session.records)
        self.assertEqual(archive.manifest['stream_counts']['INBOX'],0)
        self.assertFalse(archive.manifest['evidence_complete'])

    def test_local_source_close_keeps_failed_history_archivable_without_live_grant(self):
        self.observed()
        self.dispatch.close()
        self.session.close()
        archive=self.prepare()
        self.assertIsNone(archive.manifest['session_id'])
        self.assertEqual(archive.manifest['session_state'],'ABANDONED')
        self.assertTrue(archive.records)
        self.assertFalse(archive.execution_ready)

    def test_invalid_archive_cannot_create_owned_directory(self):
        self.observed()
        original=self.prepare()
        module=self.archive_module()
        forged=module.ObservationArchive(original.records_jsonl,b'{}')
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'owned'
            self.rejects('RESOURCE',lambda:forged.write_new_directory(target))
            self.assertFalse(target.exists())

    def test_symbolic_archive_file_rejected_before_reading_contents(self):
        self.observed()
        archive=self.prepare()
        module=self.archive_module()
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'owned'
            archive.write_new_directory(target)
            original=Path.is_symlink
            with patch.object(Path,'is_symlink',lambda p:p.name=='records.jsonl' or original(p)):
                self.rejects('RESOURCE',lambda:module.read_evidence_archive(target,self.contract))

    def test_directory_inventory_rejects_extra_entry_without_unbounded_scan(self):
        self.observed()
        archive=self.prepare()
        module=self.archive_module()
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'owned'
            archive.write_new_directory(target)
            def entries():
                for name in ('records.jsonl','manifest.json','manifest.pending.json','extra.bin'):
                    yield target/name
                raise AssertionError('archive scanned beyond its bounded four entries')
            @contextmanager
            def inventory(_path):
                yield entries()
            with patch.object(module.os,'scandir',inventory):
                self.rejects('RESOURCE',lambda:module.read_evidence_archive(target,self.contract))


for _name in dir(test_evidence.EvidenceTests):
    if _name.startswith('test_') and _name not in ArchiveTests.__dict__:
        setattr(ArchiveTests,_name,None)
