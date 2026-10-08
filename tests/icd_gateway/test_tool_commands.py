from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from common import message
from icd_runtime.errors import ICDError
from icd_runtime.wire import Header
from input_simulator.history import CaptureBinding
from input_simulator.replay_export import ExportBinding
from input_simulator.tools import ChannelReservations
import test_replay
from test_capture import epb, idb, shb
from test_history import history, udp_packet


class CommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_replay.ReplayTests.setUpClass()
        cls.contract = test_replay.ReplayTests.contract
        cls.wire = test_replay.ReplayTests.wire

    def setUp(self):
        self.book = ChannelReservations()
        self.helper = test_replay.ReplayTests()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve() / 'approved-run'

    def builder(self):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.tool_commands'),
                             'controlled original-tool command preparation is missing')
        from input_simulator.tool_commands import ToolCommandBuilder
        return ToolCommandBuilder(self.contract, self.book)

    def rejects(self, code, action):
        with self.assertRaises(ICDError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def prepared(self, *, can=False, mode='REENCODE', offset=0):
        if not can:
            raw, h = self.helper.input(mode=mode, times=[offset])
            return self.helper.prepare(raw, h, headers=() if mode == 'RAW_VALIDATED' else self.helper.headers())
        frames = self.wire.encode(message(10), 'CANFD')
        raw = b''.join(f'(1.{offset+i*1000:09d}) can0 {f.arbitration_id:03X}##5{f.data.hex()}\n'.encode()
                       for i, f in enumerate(frames))
        h = history(raw, [10], fmt='CAN_LOG', medium='CANFD', end=str(offset+(len(frames)-1)*1000))
        h['policy'].update(mode=mode)
        if mode == 'RAW_VALIDATED':
            h['policy'].update(session_policy='CURRENT_VALID_SESSION', repeat_count=1, rewrite_fields=[])
        elif mode == 'SESSION_REBUILD':
            h['policy']['rewrite_fields'] = ['SESSION', 'SEQUENCE', 'TARGET_STEP', 'TRANSACTION', 'CRC']
        return self.helper.prepare(raw, h,
            bindings=(CaptureBinding('env', 'CANFD_0', 'CAN_LOG:can0', 'can0', 'clock-0'),),
            headers=() if mode == 'RAW_VALIDATED' else self.helper.headers(Header(91, 101, 200, 301, self.contract.entry(10)['valid_for_ms'])))

    def test_local_reservation_validation_never_grants_or_releases(self):
        token = self.book.reserve('watch', 'CUTIL', ('can0',), mode='OBSERVE')
        self.assertTrue(hasattr(self.book, 'validate'), 'opaque reservation validation is missing')
        self.assertIs(self.book.validate(token), token)
        self.rejects('STATE', lambda: self.book.validate(replace(token)))
        self.rejects('STATE', lambda: ChannelReservations().validate(token))
        self.assertEqual(self.book.reservations, (token,))
        self.book.release(token)
        self.rejects('STATE', lambda: self.book.validate(token))

    def test_observation_uses_exact_formal_bidirectional_ids_without_send(self):
        token = self.book.reserve('watch', 'CUTIL', ('can0', 'can1'), mode='OBSERVE')
        plan = self.builder().observe(token, (ExportBinding('CANFD_0', 'can0'), ExportBinding('CANFD_1', 'can1')))
        ids = sorted(m['can_id'] for m in self.contract.messages.values() if m['can_id'] is not None)
        self.assertEqual(len(ids), 13)
        filters = ','.join(f'{i:03X}:C00007FF' for i in ids)
        self.assertEqual(plan.commands[0].argv, ('candump', '-L', '-N', '-x',
                                              'can0,'+filters, 'can1,'+filters))
        self.assertIsNone(plan.export)
        self.assertFalse(plan.execution_ready)
        self.assertFalse(plan.authorized_to_transmit)
        self.assertEqual(self.book.reservations, (token,))
        with self.assertRaises(FrozenInstanceError):
            plan.commands[0].argv = ('cansend',)
        self.rejects('STATE', plan.require_execution_ready)

    def test_observe_rejects_wrong_branch_send_mode_and_released_token(self):
        b = (ExportBinding('CANFD_0', 'can0'),)
        for branch, mode in (('SAVVY', 'OBSERVE'), ('CUTIL', 'SEND')):
            book = ChannelReservations()
            token = book.reserve('run', branch, ('can0',), mode=mode)
            self.builder()
            from input_simulator.tool_commands import ToolCommandBuilder
            self.rejects('AUTHORIZATION', lambda: ToolCommandBuilder(self.contract, book).observe(token, b))
        token = self.book.reserve('watch', 'CUTIL', ('can0',), mode='OBSERVE')
        self.book.release(token)
        self.rejects('STATE', lambda: self.builder().observe(token, b))

    def test_observe_binding_is_bijective_formal_and_never_any(self):
        token = self.book.reserve('watch', 'CUTIL', ('can0',), mode='OBSERVE')
        for bindings in ((), [ExportBinding('CANFD_0', 'can0')],
                         (ExportBinding('CANFD_0', 'can1'),),
                         (ExportBinding('ETH_0', 'can0'),),
                         (ExportBinding('CANFD_0', 'can0'), ExportBinding('CANFD_1', 'can0')),
                         (ExportBinding('CANFD_0', 'can0', source_mac='00:11:22:33:44:55'),)):
            self.rejects('SCHEMA', lambda: self.builder().observe(token, bindings))
        book = ChannelReservations()
        any_token = book.reserve('watch', 'CUTIL', ('any',), mode='OBSERVE')
        self.builder()
        from input_simulator.tool_commands import ToolCommandBuilder
        self.rejects('SCHEMA', lambda: ToolCommandBuilder(self.contract, book).observe(any_token, (ExportBinding('CANFD_0', 'any'),)))

    def test_canplayer_three_modes_exact_resource_explicit_mapping_one_round(self):
        for mode in ('RAW_VALIDATED', 'REENCODE', 'SESSION_REBUILD'):
            token = self.book.reserve(mode, 'CANREPLAY', ('can0',), mode='SEND')
            plan = self.builder().replay(token, self.prepared(can=True, mode=mode),
                                        (ExportBinding('CANFD_0', 'can0'),), directory=self.directory)
            command = plan.commands[0]
            self.assertEqual(command.argv, ('canplayer', '-I', str(self.directory/'CANFD_0.log'), '-l', '1', 'can0=can0'))
            self.assertEqual(command.resource_sha256, hashlib.sha256(plan.export.files[0].data).hexdigest())
            self.assertEqual(command.channel_id, 'CANFD_0')
            self.assertFalse(self.directory.exists())
            self.assertFalse(plan.execution_ready)
            self.book.release(token)

    def test_tcpreplay_three_modes_never_double_scales_or_loops(self):
        for mode in ('RAW_VALIDATED', 'REENCODE', 'SESSION_REBUILD'):
            token = self.book.reserve(mode, 'ETHREPLAY', ('eth0',), mode='SEND')
            plan = self.builder().replay(token, self.prepared(mode=mode),
                                        (ExportBinding('ETH_0', 'eth0'),), directory=self.directory)
            command = plan.commands[0]
            self.assertEqual(command.argv, ('tcpreplay', '--intf1=eth0', '--loop=1', '--multiplier=1.0', str(self.directory/'ETH_0.pcap')))
            self.assertIsNone(plan.export.files[0].tool_timing_compatible)
            self.assertFalse(plan.authorized_to_transmit)
            self.rejects('STATE', plan.require_execution_ready)
            self.book.release(token)

    def test_first_channel_offset_is_retained_not_hidden_by_tool_start(self):
        token = self.book.reserve('run', 'ETHREPLAY', ('eth0',), mode='SEND')
        raw, h = self.helper.input(values=[message(130), message(7)], times=[0, 7000])
        h['streams'][0].update(message_ids=[7], records=1)
        feedback = dict(h['streams'][0], stream_id='feedback', message_ids=[130], records=1, direction='FROM_36')
        h['streams'].append(feedback)
        prepared = self.helper.prepare(raw, h, headers=self.helper.headers(index=1),
            bindings=(self.helper.binding(), self.helper.binding(stream_id='feedback')))
        plan = self.builder().replay(token, prepared,
                                    (ExportBinding('ETH_0', 'eth0'),), directory=self.directory)
        self.assertEqual(plan.commands[0].first_offset_ns, 7000)
        self.assertEqual(plan.export.report()['feedback_records_not_transmitted'], 1)
        self.assertIn('COMMON_START_OFFSET_SCHEDULER', plan.pending_checks)

    def test_replay_rejects_observer_other_branch_or_transport(self):
        prepared = self.prepared()
        for branch, mode in (('ETHREPLAY', 'OBSERVE'), ('ETHGEN', 'SEND'), ('CANREPLAY', 'SEND')):
            book = ChannelReservations()
            token = book.reserve('run', branch, ('eth0',), mode=mode)
            self.builder()
            from input_simulator.tool_commands import ToolCommandBuilder
            code = 'UNSUPPORTED' if branch == 'CANREPLAY' else 'AUTHORIZATION'
            self.rejects(code, lambda: ToolCommandBuilder(self.contract, book).replay(token, prepared,
                (ExportBinding('ETH_0', 'eth0'),), directory=self.directory))

    def test_replay_rechecks_resource_instead_of_trusting_manifest_claims(self):
        prepared = self.prepared()
        packet = replace(prepared.packets[0], wire_data=prepared.packets[0].wire_data[:-1]+b'\xff')
        altered = replace(prepared, packets=(packet,))
        token = self.book.reserve('run', 'ETHREPLAY', ('eth0',), mode='SEND')
        self.rejects('RESOURCE', lambda: self.builder().replay(token, altered,
            (ExportBinding('ETH_0', 'eth0'),), directory=self.directory))
        self.assertFalse(self.directory.exists())

    def test_can_microsecond_inexpressibility_is_rejected_without_rounding(self):
        self.builder()
        token = self.book.reserve('run', 'CANREPLAY', ('can0',), mode='SEND')
        frames = self.wire.encode(message(10), 'CANFD')
        raw = b''.join(f'(1.{i:09d}) can0 {f.arbitration_id:03X}##5{f.data.hex()}\n'.encode() for i, f in enumerate(frames))
        h = history(raw, [10], fmt='CAN_LOG', medium='CANFD', end=str(len(frames)-1))
        prepared = self.helper.prepare(raw, h,
            bindings=(CaptureBinding('env', 'CANFD_0', 'CAN_LOG:can0', 'can0', 'clock-0'),),
            headers=self.helper.headers(Header(91, 101, 200, 301, self.contract.entry(10)['valid_for_ms'])))
        self.rejects('UNSUPPORTED', lambda: self.builder().replay(token, prepared,
            (ExportBinding('CANFD_0', 'can0'),), directory=self.directory))

    def test_canplayer_stdout_pseudo_interface_cannot_replace_actual_send_channel(self):
        token = self.book.reserve('run', 'CANREPLAY', ('stdout',), mode='SEND')
        self.rejects('SCHEMA', lambda: self.builder().replay(token, self.prepared(can=True),
            (ExportBinding('CANFD_0', 'stdout'),), directory=self.directory))
        self.assertFalse(self.directory.exists())

    def test_foreign_forged_released_or_extra_interfaces_never_prepare(self):
        token = self.book.reserve('run', 'ETHREPLAY', ('eth0',), mode='SEND')
        prepared, bindings = self.prepared(), (ExportBinding('ETH_0', 'eth0'),)
        self.rejects('STATE', lambda: self.builder().replay(replace(token), prepared, bindings, directory=self.directory))
        self.book.release(token)
        self.rejects('STATE', lambda: self.builder().replay(token, prepared, bindings, directory=self.directory))
        token = self.book.reserve('next', 'ETHREPLAY', ('eth0', 'eth1'), mode='SEND')
        self.rejects('SCHEMA', lambda: self.builder().replay(token, prepared, bindings, directory=self.directory))

    def test_directory_is_absolute_new_literal_and_no_write_occurs(self):
        token = self.book.reserve('run', 'ETHREPLAY', ('eth0',), mode='SEND')
        prepared, bindings = self.prepared(), (ExportBinding('ETH_0', 'eth0'),)
        for path in (Path('relative'), Path(self.temp.name), self.directory/'missing'/'child'):
            self.rejects('RESOURCE', lambda: self.builder().replay(token, prepared, bindings, directory=path))
        self.assertFalse(self.directory.exists())

    def test_four_can_channels_each_keep_mapping_file_hash_and_start_offset(self):
        values = [message(2) for _ in range(4)]
        for i, value in enumerate(values):
            value['header']['sequence'] += i
        frames = [self.wire.encode(v, 'CANFD')[0] for v in values]
        raw = b''.join(f'(1.{i*1000:09d}) can{i} {f.arbitration_id:03X}##5{f.data.hex()}\n'.encode()
                       for i, f in enumerate(frames))
        h = history(raw, [2], fmt='CAN_LOG', medium='CANFD', records=4, end='3000')
        h['policy'].update(mode='RAW_VALIDATED', session_policy='CURRENT_VALID_SESSION', repeat_count=1, rewrite_fields=[])
        bindings = tuple(CaptureBinding('env', f'CANFD_{i}', f'CAN_LOG:can{i}', f'can{i}', 'clock-0') for i in range(4))
        prepared = self.helper.prepare(raw, h, bindings=bindings)
        token = self.book.reserve('four', 'CANREPLAY', tuple(f'can{i}' for i in range(4)), mode='SEND')
        plan = self.builder().replay(token, prepared, tuple(ExportBinding(f'CANFD_{i}', f'can{i}') for i in range(4)), directory=self.directory)
        self.assertEqual(len(plan.commands), 4)
        for i, (command, item) in enumerate(zip(plan.commands, plan.export.files)):
            self.assertEqual(command.first_offset_ns, i*1000)
            self.assertEqual(command.channel_id, f'CANFD_{i}')
            self.assertEqual(command.argv[-1], f'can{i}=can{i}')
            self.assertEqual(command.resource_sha256, item.sha256)

    def test_four_pcapng_channels_export_independent_full_pcap_commands(self):
        raw = shb() + b''.join(idb(1, name=f'eth{i}'.encode()) for i in range(4))
        for i in range(4):
            value = message(7)
            value['header']['sequence'] += i
            frame = udp_packet(self.wire.encode(value, 'UDP')[0], channel=i)
            raw += epb(frame, interface=i, ticks=1000000000+i*1000)
        h = history(raw, [7], fmt='PCAPNG', records=4, end='3000')
        h['policy'].update(mode='RAW_VALIDATED', session_policy='CURRENT_VALID_SESSION', repeat_count=1, rewrite_fields=[])
        bindings = tuple(CaptureBinding('env', f'ETH_{i}', f'PCAPNG:0:{i}', f'eth{i}', 'clock-0') for i in range(4))
        prepared = self.helper.prepare(raw, h, bindings=bindings)
        token = self.book.reserve('four', 'ETHREPLAY', tuple(f'eth{i}' for i in range(4)), mode='SEND')
        plan = self.builder().replay(token, prepared, tuple(ExportBinding(f'ETH_{i}', f'eth{i}') for i in range(4)), directory=self.directory)
        self.assertEqual(len(plan.commands), 4)
        for i, command in enumerate(plan.commands):
            self.assertEqual(command.first_offset_ns, i*1000)
            self.assertEqual(command.argv[1], f'--intf1=eth{i}')
            self.assertEqual(command.channel_id, f'ETH_{i}')

    def test_preprocessed_rate_and_repeat_stay_upstream_not_tool_options(self):
        first, second = message(7), message(7)
        second['header']['sequence'] += 1
        second['header']['transaction_id'] += 1
        raw, h = self.helper.input(values=[first, second], times=[0, 8000])
        h['policy'].update(rate='2X', execution_mode='OFFLINE', repeat_count=10000, repeat_gap_steps=7)
        prepared = self.helper.prepare(raw, h, headers=self.helper.headers() + self.helper.headers(Header(91, 102, 201, 302, 100), index=1))
        token = self.book.reserve('rate', 'ETHREPLAY', ('eth0',), mode='SEND')
        plan = self.builder().replay(token, prepared, (ExportBinding('ETH_0', 'eth0'),), directory=self.directory)
        report = plan.export.report()
        self.assertEqual(report['files'][0]['packets'][1]['relative_offset_ns'], '4000')
        self.assertEqual(report['policy']['repeat_count'], 10000)
        self.assertEqual(report['repeat_gap_steps'], 7)
        self.assertEqual(plan.commands[0].argv[2:4], ('--loop=1', '--multiplier=1.0'))

    def test_actual_persistence_matches_literal_command_resource_without_launch(self):
        token = self.book.reserve('run', 'ETHREPLAY', ('eth0',), mode='SEND')
        plan = self.builder().replay(token, self.prepared(), (ExportBinding('ETH_0', 'eth0'),), directory=self.directory)
        plan.export.write_new_directory(self.directory)
        actual = Path(plan.commands[0].argv[-1]).read_bytes()
        self.assertEqual(actual, plan.export.files[0].data)
        self.assertEqual(hashlib.sha256(actual).hexdigest(), plan.commands[0].resource_sha256)
        self.assertFalse(plan.execution_ready)


if __name__ == '__main__':
    unittest.main()
