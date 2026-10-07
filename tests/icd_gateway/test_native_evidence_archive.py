"""Original native software observations, not physical or run qualification."""

from dataclasses import replace
import importlib
from pathlib import Path
import struct
import tempfile
import uuid

import can

from common import GatewayTest
from icd_runtime.json_codec import canonicalize, loads
import test_native_tools as native_cases
import test_scapy_source as scapy_cases
import test_can_signal as can_cases


class NativeArchiveTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.module = importlib.import_module('input_simulator.evidence_archive')

    def native(self):
        self.f = native_cases.NativeToolTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.plan = self.f.plan()
        self.f.coordinator.send_can(self.f.sender,self.plan)
        self.f.f.consume(self.plan)
        self.f.f.emit(self.plan,sequence=2)
        self.f.coordinator.receive_can(self.f.sender,self.plan,timeout=0.2)
        return self.f

    def prepare(self, **kwargs):
        return self.module.prepare_native_evidence_archive(self.f.dispatch,run_id='run-01',
            coordinator=self.f.coordinator,**kwargs)

    def test_required_native_archive_api_exists(self):
        self.assertTrue(callable(getattr(self.module,'prepare_native_evidence_archive',None)),
                        'native CAN/L2 original archive entry missing')

    def test_actual_can_records_and_original_source_roundtrip_without_drain(self):
        f = self.native()
        original = f.f.session.records+f.dispatch.records+f.sender.records
        before = (f.f.session._next_sequence,f.f.session._deadline_ns,
                  f.f.session.last_rx_sequence,f.sender.pending_count,f.f.builder._bytes)
        archive = self.prepare()
        self.assertEqual(archive.records,original)
        self.assertEqual(archive.manifest['format'],'HIL_OBSERVATION_SEGMENT_2')
        self.assertEqual(set(archive.manifest['stream_counts']),{'SOURCE','DISPATCH','INBOX','CAN','L2'})
        self.assertEqual(archive.manifest['stream_counts']['CAN'],len(f.sender.records))
        self.assertEqual(before,(f.f.session._next_sequence,f.f.session._deadline_ns,
                  f.f.session.last_rx_sequence,f.sender.pending_count,f.f.builder._bytes))
        self.assertEqual(original,f.f.session.records+f.dispatch.records+f.sender.records)
        self.assertFalse(archive.manifest['evidence_complete'])
        self.assertFalse(archive.execution_ready)
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'native'
            archive.write_new_directory(target)
            saved = self.module.read_evidence_archive(target,self.contract)
            self.assertEqual(saved.records_jsonl,archive.records_jsonl)
            self.assertEqual(saved.records,original)

    def test_actual_scapy_opening_l2_records_are_not_dropped(self):
        f = scapy_cases.ScapySourceTests('runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.live()
        from input_simulator.dispatch import UDPDispatcher
        dispatch = UDPDispatcher(f.session)
        self.addCleanup(dispatch.close)
        archive = self.module.prepare_native_evidence_archive(dispatch,run_id='run-01')
        self.assertEqual(archive.records,f.session.records+f.src.l2_records)
        self.assertEqual(archive.manifest['stream_counts']['L2'],len(f.src.l2_records))
        self.assertEqual(archive.records[-1].ethernet_data,f.src.l2_records[-1].ethernet_data)

    def test_native_snapshot_locks_and_wrong_owner_fail_without_reclaim(self):
        f = self.native()
        original = f.sender.records
        for lock in (f.coordinator._lock,f.dispatch._lock,f.sender._lock,f.f.builder._lock,f.f.session._lock):
            lock.acquire()
            try:
                self.rejects('STATE',self.prepare)
            finally:
                lock.release()
        self.rejects('STATE',lambda:self.module.prepare_native_evidence_archive(f.dispatch,
            run_id='run-01',coordinator=object()))
        self.rejects('STATE',lambda:self.module.prepare_native_evidence_archive(f.dispatch,run_id='run-01'))
        self.assertEqual(f.sender.records,original)

    def test_exact_native_count_and_complete_byte_bounds(self):
        self.native()
        archive = self.prepare()
        size = len(archive.records_jsonl)+len(archive.manifest_json)
        self.assertEqual(self.prepare(max_bytes=size).records,archive.records)
        self.rejects('CAPACITY',lambda:self.prepare(max_bytes=size-1))
        self.rejects('CAPACITY',lambda:self.prepare(max_records=len(archive.records)-1))

    def test_can_timestamp_negative_zero_and_nan_bits_are_retained_exactly(self):
        self.native()
        from input_simulator.can_signal import CANObservation
        module = importlib.import_module('input_simulator._native_evidence')
        for stamp in (-0.0,None):
            bits = struct.pack('>d',-0.0) if stamp is not None else bytes.fromhex('7ff8000000000042')
            record = CANObservation('RX','CANFD_0','can0',2,data=b'raw-invalid-frame',
                arbitration_id=123,library_timestamp=stamp,library_timestamp_bits=bits,error='SCHEMA')
            decoded = module.decode_native_record(loads(module.encode_native_record('CAN',record)))
            self.assertEqual(decoded.library_timestamp_bits,bits)
            self.assertEqual(decoded.data,record.data)
            if stamp is not None:
                self.assertEqual(struct.pack('>d',decoded.library_timestamp),bits)

    def test_old_format_cannot_claim_native_rows_and_tampered_flags_fail(self):
        self.native()
        archive = self.prepare()
        manifest = archive.manifest
        manifest['format'] = 'HIL_OBSERVATION_SEGMENT_1'
        self.rejects('RESOURCE',lambda:self.module._validate(replace(archive,manifest_json=canonicalize(manifest))))
        rows = [loads(line) for line in archive.records_jsonl.splitlines()]
        row = next(r for r in rows if r['stream']=='CAN')
        row['record']['qualification_status'] = 'VERIFIED'
        raw = b''.join(canonicalize(r)+b'\n' for r in rows)
        manifest = archive.manifest
        manifest.update(records_sha256=self.module._digest(raw),records_size_bytes=len(raw))
        self.rejects('RESOURCE',lambda:self.module._validate(replace(archive,records_jsonl=raw,
            manifest_json=canonicalize(manifest))))

    def test_replaced_native_sender_list_cannot_drop_original_records(self):
        f = self.native()
        original = f.coordinator.senders
        try:
            f.coordinator.senders = ()
            self.rejects('STATE',self.prepare)
        finally:
            f.coordinator.senders = original

    def test_actual_closed_original_owners_can_still_be_archived(self):
        f = self.native()
        f.coordinator.close()
        f.dispatch.close()
        archive = self.prepare()
        self.assertEqual(archive.manifest['stream_counts']['CAN'],len(f.sender.records))
        self.assertEqual(archive.records,f.f.session.records+f.dispatch.records+f.sender.records)

    def test_closed_native_field_domains_and_original_integer_metadata(self):
        self.native()
        from input_simulator.can_signal import CANObservation
        module = importlib.import_module('input_simulator._native_evidence')
        record = CANObservation('RX','CANFD_0','can0',2,actual_channel=-(2**63),
                                library_timestamp=-0.0,library_timestamp_bits=struct.pack('>d',-0.0))
        row = loads(module.encode_native_record('CAN',record))
        self.assertEqual(module.decode_native_record(row),record)
        for name,value in (('is_fd',1),('started_ns','02'),('data','not base64'),
                           ('library_timestamp_bits','AA=='),('kind','SENT'),
                           ('channel_id','ETH_0'),('qualification_status','VERIFIED')):
            changed = loads(canonicalize(row))
            changed['record'][name] = value
            self.rejects('RESOURCE',lambda:module.decode_native_record(changed))

    def four_senders(self):
        from input_simulator.dispatch import UDPDispatcher
        from input_simulator.native_tools import NativeToolCoordinator
        from input_simulator.replay_export import ExportBinding
        from common import message
        f = can_cases.CANSignalTests('runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.live()
        senders = [f.sender()]
        for index in range(1,4):
            bus = can.Bus(interface='virtual',channel=uuid.uuid4().hex,ignore_config=True)
            self.addCleanup(bus.shutdown)
            token = f.book.reserve(f'archive-{index}','CANT',(f'can{index}',),mode='SEND')
            sender = f.module.CANSignalSender(f.builder,token,ExportBinding(f'CANFD_{index}',f'can{index}'),bus=bus)
            self.addCleanup(sender.close)
            senders.append(sender)
        dispatch = UDPDispatcher(f.session)
        self.addCleanup(dispatch.close)
        coordinator = NativeToolCoordinator(dispatch,tuple(senders))
        self.addCleanup(coordinator.close)
        for sender in senders:
            plan = coordinator.prepare_can(sender,{'message_id':7,'payload':message(7)['payload']},target_step=100)
            coordinator.send_can(sender,plan)
            if sender is senders[0]:
                f.consume(plan)
        return f,dispatch,coordinator,tuple(senders)

    def test_all_four_actual_can_senders_keep_their_original_channels(self):
        f,dispatch,coordinator,senders = self.four_senders()
        archive = self.module.prepare_native_evidence_archive(dispatch,run_id='run-01',coordinator=coordinator)
        expected = f.session.records+dispatch.records+tuple(r for s in senders for r in s.records)
        self.assertEqual(archive.records,expected)
        self.assertEqual({r.channel_id for r in archive.records if type(r).__name__=='CANObservation'},
                         {f'CANFD_{i}' for i in range(4)})
