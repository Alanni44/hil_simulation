"""Common original-tool lifecycle tests, not original binary/device qualification."""

import importlib.util
import importlib
from dataclasses import replace
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from common import message
from icd_runtime.errors import ICDError
from icd_runtime.wire import Header
from input_simulator.replay_export import ExportBinding
from input_simulator.tool_process import ProcessSnapshot
from test_history import history, udp_packet
from test_capture import pcap
from test_capture import shb, idb, epb
import test_scapy_source
import test_tool_commands


class ReplayProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_tool_commands.CommandTests.setUpClass()
        cls.contract = test_tool_commands.CommandTests.contract

    def setup_run(self, *, can=False, offset=0, mode='REENCODE', authority=True):
        self.module = importlib.import_module('input_simulator.replay_process')
        self.f = test_scapy_source.ScapySourceTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.live(implemented=[1,2,10])
        self.helper = test_tool_commands.CommandTests('runTest')
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.helper.book = self.f.book
        value = message(10)
        value['header']['session_id'] = 73 if mode=='RAW_VALIDATED' else 42
        if can:
            frames = self.helper.wire.encode(value,'CANFD')
            raw = b''.join(f'(1.{offset+i*1000:09d}) can0 {f.arbitration_id:03X}##5{f.data.hex()}\n'.encode()
                           for i,f in enumerate(frames))
            h = history(raw,[10],fmt='CAN_LOG',medium='CANFD',end=str(offset+(len(frames)-1)*1000))
            from input_simulator.history import CaptureBinding
            capture_bindings = (CaptureBinding('env','CANFD_0','CAN_LOG:can0','can0','clock-0'),)
            self.bindings = (ExportBinding('CANFD_0','can0'),)
            self.token = self.f.book.reserve('replay-run','CANREPLAY',('can0',),mode='SEND')
        elif offset:
            first=udp_packet(self.helper.wire.encode(value,'UDP')[0])
            value['header']['sequence']+=1
            value['header']['transaction_id']+=1
            second=udp_packet(self.helper.wire.encode(value,'UDP')[0],channel=1)
            raw=shb()+idb(1,name=b'eth0')+idb(1,name=b'eth1')+epb(first,interface=0,ticks=1000000000)+epb(second,interface=1,ticks=1000000000+offset)
            h=history(raw,[10],fmt='PCAPNG',records=2,end=str(offset))
            from input_simulator.history import CaptureBinding
            capture_bindings=tuple(CaptureBinding('env',f'ETH_{i}',f'PCAPNG:0:{i}',f'eth{i}','clock-0') for i in range(2))
            self.bindings=(ExportBinding('ETH_0','eth1'),ExportBinding('ETH_1','eth2'))
            self.token=self.f.book.reserve('replay-run','ETHREPLAY',('eth1','eth2'),mode='SEND')
        else:
            frames = self.helper.wire.encode(value,'UDP')
            raw = pcap([(1,offset+i*1000,udp_packet(f)) for i,f in enumerate(frames)],nano=True)
            h = history(raw,[10],end=str(offset+(len(frames)-1)*1000))
            capture_bindings = (self.helper.helper.binding(),)
            self.bindings = (ExportBinding('ETH_0','eth1'),)
            self.token = self.f.book.reserve('replay-run','ETHREPLAY',('eth1',),mode='SEND')
        h['policy']['mode'] = mode
        if mode=='RAW_VALIDATED':
            h['policy'].update(session_policy='CURRENT_VALID_SESSION',repeat_count=1,rewrite_fields=[])
        elif mode=='SESSION_REBUILD':
            h['policy']['rewrite_fields'] = ['SESSION','SEQUENCE','TARGET_STEP','TRANSACTION','CRC']
        from input_simulator.replay import ReplayHeader
        headers=tuple(ReplayHeader(i,Header(73,101+i,200,301+i,self.contract.entry(10)['valid_for_ms']))
                      for i in range(2 if offset and not can else 1))
        self.prepared = self.helper.helper.prepare(raw,h,bindings=capture_bindings,
            headers=() if mode=='RAW_VALIDATED' else headers)
        self.plan = self.helper.builder().replay(self.token,self.prepared,self.bindings,directory=self.helper.directory)
        class Guard(self.module.ReplayProcessAuthority):
            def __init__(this,source):
                super().__init__(source)
                this.calls=[]
                this.error=None
            def preflight(this,prepared,plan):
                this.calls.append('preflight')
                if this.error:
                    raise ICDError(this.error,'test runtime authority rejected')
            def check(this,prepared,plan,*,channel_id=None):
                this.calls.append(channel_id or 'poll')
                if this.error:
                    raise ICDError(this.error,'test runtime authority rejected')
        self.guard = Guard(self.f.session) if authority else None
        name = 'canplayer' if can else 'tcpreplay'
        self.run = self.module.ReplayProcessRun(self.contract,self.prepared,self.plan,self.bindings,
            self.f.book,self.token,authority=self.guard,executables={name:Path(sys.executable).resolve()},
            start_lateness_ns=1000000)
        self.addCleanup(self.run.close)
        return self.run

    def rejects(self,code,action):
        with self.assertRaises(ICDError) as error:
            action()
        self.assertEqual(error.exception.code,code)

    def fake_processes(self):
        """Coordination-only stand-ins: not canplayer/tcpreplay execution evidence."""
        self.children=[]
        children=self.children
        class Child:
            def __init__(self,argv,**kwargs):
                self.argv=argv
                self._threads=[]
                self.state='NEW'
                children.append(self)
            @property
            def snapshot(self):
                done=self.state in ('EXITED','STOPPED')
                return ProcessSnapshot(self.state,1 if self.state!='NEW' else None,0 if done else None,
                    0 if self.state!='NEW' else None,1 if done else None,b'',b'',0,0,None,done,done)
            def start(self):
                self.state='RUNNING'
                return self.snapshot
            def poll(self):
                return self.snapshot
            def stop(self):
                self.state='STOPPED'
                return self.snapshot
        return patch.object(self.module,'ProcessSupervisor',Child)

    def test_required_original_replay_process_entry(self):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.replay_process'),
                             'original replay process execution wiring is missing')

    def test_missing_authority_fails_before_export_or_child_allocation(self):
        run=self.setup_run(authority=False)
        self.rejects('TARGET_MISSING',run.start)
        self.assertFalse(self.helper.directory.exists())
        self.assertEqual(run.processes,())

    def test_rejection_before_start_preserves_reservation_and_counters(self):
        run=self.setup_run()
        self.guard.error='CONTROL_OWNER'
        before=self.f.session._next_sequence,self.f.session.records
        self.rejects('CONTROL_OWNER',run.start)
        self.assertFalse(self.helper.directory.exists())
        self.assertEqual((self.f.session._next_sequence,self.f.session.records),before)
        self.assertIs(self.f.book.validate(self.token),self.token)

    def test_original_canplayer_modes_launch_only_exact_flags_and_local_exit(self):
        for mode in ('RAW_VALIDATED','REENCODE','SESSION_REBUILD'):
            run=self.setup_run(can=True,mode=mode)
            with self.fake_processes():
                run.start()
                self.assertEqual(self.children[0].argv[1:],self.plan.commands[0].argv[1:])
                self.children[0].state='EXITED'
                result=run.poll()
                self.assertEqual(result.state,'LOCAL_EXITED')
                self.assertFalse(result.execution_ready)
                self.assertFalse(result.evidence_complete)
                self.assertFalse(result.tree_cleanup_verified)
                self.assertEqual(run.records[0].command,self.plan.commands[0])
            run.close()

    def test_channel_offset_is_not_model_step_and_missed_start_does_not_launch(self):
        run=self.setup_run(offset=10000000)
        with self.fake_processes():
            run.start()
            self.assertEqual(len(self.children),1)
            self.f.clock.value+=12000000
            result=run.poll()
            self.assertEqual(result.error,'LATE')
            self.assertEqual(len(self.children),1)

    def test_persisted_file_tamper_before_delayed_launch_fails_without_process(self):
        run=self.setup_run(offset=10000000)
        with self.fake_processes():
            run.start()
            path=self.helper.directory/self.plan.export.files[0].name
            with patch.object(self.module,'_read_bounded',side_effect=ICDError('RESOURCE','tampered file')):
                self.f.clock.value+=10000000
                result=run.poll()
            self.assertEqual(result.error,'RESOURCE')
            self.assertEqual(len(self.children),1)

    def test_runtime_revocation_stops_actual_owned_handles_without_releasing_book(self):
        run=self.setup_run()
        with self.fake_processes():
            run.start()
            self.guard.error='AUTHORIZATION'
            result=run.poll()
            self.assertEqual(result.state,'FAILED')
            self.assertEqual(self.children[0].state,'STOPPED')
            self.assertEqual(result.error,'AUTHORIZATION')
            self.assertIs(self.f.book.validate(self.token),self.token)
            self.assertFalse(result.safety_verified)

    def test_real_supervisor_failure_keeps_original_argv_and_never_native_fallback(self):
        run=self.setup_run(can=True)
        run.start()
        deadline=time.monotonic()+5
        while run.snapshot.state=='RUNNING' and time.monotonic()<deadline:
            time.sleep(.01)
            run.poll()
        self.assertEqual(run.snapshot.state,'FAILED')
        self.assertEqual(run.snapshot.error,'STATE')
        self.assertTrue(run.processes[0].direct_child_terminal)
        self.assertEqual(run.records[0].command,self.plan.commands[0])
        self.assertFalse(run.snapshot.evidence_complete)

    def test_replaced_authority_source_and_modified_command_are_rejected(self):
        run=self.setup_run()
        original=self.guard.session
        self.guard.session=object()
        try:
            self.rejects('STATE',run.start)
        finally:
            self.guard.session=original
        bad=replace(self.plan,commands=(replace(self.plan.commands[0],argv=('tcpreplay','--loop=2','bad')),))
        self.rejects('RESOURCE',lambda:self.module.ReplayProcessRun(self.contract,self.prepared,bad,self.bindings,
            self.f.book,self.token,authority=self.guard,executables={'tcpreplay':Path(sys.executable).resolve()}))

    def test_malformed_original_commands_return_explicit_resource_error(self):
        self.setup_run()
        for commands in ((object(),),(replace(self.plan.commands[0],argv=()),)):
            bad=replace(self.plan,commands=commands)
            self.rejects('RESOURCE',lambda:self.module.ReplayProcessRun(self.contract,self.prepared,bad,self.bindings,
                self.f.book,self.token,authority=self.guard,executables={'tcpreplay':Path(sys.executable).resolve()}))

    def test_one_stop_failure_does_not_skip_other_original_child(self):
        run=self.setup_run(offset=10000000)
        with self.fake_processes():
            run.start()
            self.f.clock.value+=10000000
            run.poll()
            first,second=self.children
            original=first.stop
            first.stop=lambda:(_ for _ in ()).throw(ICDError('STATE','stop failed'))
            try:
                self.assertEqual(run.stop().state,'FAILED')
                self.assertEqual(second.state,'STOPPED')
                self.assertTrue(run.snapshot.pending_cleanup)
                self.rejects('STATE',run.close)
            finally:
                first.stop=original
            self.assertFalse(run.close().pending_cleanup)

    def test_tcpreplay_modes_keep_exact_flags_and_do_not_repeat_locally(self):
        for mode in ('RAW_VALIDATED','REENCODE','SESSION_REBUILD'):
            run=self.setup_run(mode=mode)
            with self.fake_processes():
                run.start()
                self.assertEqual(self.children[0].argv[1:],self.plan.commands[0].argv[1:])
                self.rejects('STATE',run.start)
                run.stop()
                self.assertEqual(len(self.children),1)
            run.close()

    def test_stopped_before_start_cannot_reopen(self):
        run=self.setup_run()
        run.stop()
        self.rejects('STATE',run.start)
        self.assertFalse(self.helper.directory.exists())

    def test_unknown_authority_exception_has_typed_failure_and_no_files(self):
        run=self.setup_run()
        self.guard.preflight=lambda *args:(_ for _ in ()).throw(ValueError('reader failed'))
        self.rejects('RESOURCE',run.start)
        self.assertFalse(self.helper.directory.exists())
        self.assertEqual(run.snapshot.error,'RESOURCE')

    def test_expired_grant_stops_owned_child_without_resetting_source_floor(self):
        run=self.setup_run()
        with self.fake_processes():
            run.start()
            counter=self.f.session._next_sequence
            self.f.clock.value=self.f.session._deadline_ns
            result=run.poll()
            self.assertEqual(result.error,'STALE_SESSION')
            self.assertEqual(self.children[0].state,'STOPPED')
            self.assertEqual(self.f.session._next_sequence,counter)

    def test_boolean_authority_result_cannot_substitute_for_validation(self):
        run=self.setup_run()
        self.guard.preflight=lambda *args:True
        self.rejects('SCHEMA',run.start)
        self.assertFalse(self.helper.directory.exists())

    def test_actual_supervisor_timeout_returned_by_stop_is_not_local_success(self):
        # Python receives unchanged canplayer args, not a qualified replay backend.
        run=self.setup_run(can=True)
        self.assertEqual(run.start().state,'RUNNING')
        run._children[0]._timeout_ns=1000000
        time.sleep(.02)
        result=run.stop()
        self.assertEqual(result.processes[0].error,'TIMEOUT')
        self.assertEqual(result.state,'FAILED')
        self.assertEqual(result.error,'TIMEOUT')
        self.assertEqual([r.error for r in run.records if r.kind=='STOP_FAILED'],['TIMEOUT'])
        run.close()
        self.assertEqual(len([r for r in run.records if r.kind=='STOP_FAILED']),1)

    def test_failed_popen_retains_error_without_nonexistent_child_cleanup(self):
        run=self.setup_run(can=True)
        with patch('input_simulator.tool_process.subprocess.Popen',side_effect=PermissionError('test launch denied')):
            result=run.start()
        self.assertEqual(result.state,'FAILED')
        self.assertEqual(result.error,'RESOURCE')
        self.assertEqual(len(result.processes),1)
        self.assertIsNone(result.processes[0].pid)
        self.assertFalse(result.pending_cleanup)
        self.assertFalse(run.close().pending_cleanup)
        self.assertEqual(run.snapshot.error,'RESOURCE')
        self.assertIs(self.f.book.validate(self.token),self.token)


if __name__ == '__main__':
    unittest.main()
