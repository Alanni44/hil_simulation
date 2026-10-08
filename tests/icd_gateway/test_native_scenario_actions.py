"""Actual original library peers, not model/control/clock qualification."""

from dataclasses import replace
import importlib
import threading
import unittest
import uuid
from unittest.mock import patch

import can
from scapy.layers.inet import UDP

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from input_simulator.can_signal import CANSignalSender
from input_simulator.dispatch import UDPDispatcher
from input_simulator.live_tool_input import LiveToolInputBuilder
from input_simulator.native_tools import NativeToolCoordinator
from input_simulator.protocol import ProtocolParser
from input_simulator.replay_export import ExportBinding
from input_simulator.scenario import ScenarioPlan
from test_scenario import periodic, scenario, send, stop
from test_source_inputs import resources, source_inputs
from test_waveform import event as wave
import test_scapy_source as scapy_cases


class NativeScenarioActionTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.native_scenario_actions'),
                             'actual original scenario send handler missing')
        self.module = importlib.import_module('input_simulator.native_scenario_actions')
        self.f = scapy_cases.ScapySourceTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.live(implemented=[1, 2, 7, 10, 11])
        self.token = self.f.book.reserve('native-scenario', 'CANT', ('can0',), mode='SEND')
        parser = ProtocolParser(self.contract)
        parser.parse(source_inputs()['protocol'], resources())
        self.builder = LiveToolInputBuilder(self.f.book, self.f.session, protocol=parser)
        channel = 'scenario-'+uuid.uuid4().hex
        self.bus = can.Bus(interface='virtual', channel=channel, ignore_config=True)
        self.peer = can.Bus(interface='virtual', channel=channel, ignore_config=True)
        self.addCleanup(self.bus.shutdown)
        self.addCleanup(self.peer.shutdown)
        self.sender = CANSignalSender(self.builder, self.token, ExportBinding('CANFD_0', 'can0'), bus=self.bus)
        self.dispatch = UDPDispatcher(self.f.session)
        self.addCleanup(self.dispatch.close)
        self.owner = NativeToolCoordinator(self.dispatch, (self.sender,))
        self.addCleanup(self.owner.close)
        self.rx_sequence = 1

    def build(self, events, **limits):
        self.plan = ScenarioPlan.compile(self.contract, scenario(events), model_id='quadrotor_hil')
        self.handler = self.module.NativeScenarioActions(self.contract, self.plan, self.owner,
                                                        can_sender=self.sender, **limits)
        return self.handler

    def action(self, index=0):
        return tuple(self.plan.iter_actions())[index]

    def can_request(self):
        from icd_runtime.reassembly import Reassembler
        from icd_runtime.wire import CANFrame
        assembler = Reassembler(self.contract)
        result = None
        while result is None:
            frame = self.peer.recv(0.1)
            self.assertIsNotNone(frame)
            part = self.f.src.wire.decode(CANFrame(frame.arbitration_id, bytes(frame.data)), 'CANFD', direction='TO_36')
            result = assembler.push(part, channel='CANFD_0', direction='TO_36', authorized=True, now_ns=0)
        return result.message

    def eth_request(self):
        from icd_runtime.reassembly import Reassembler
        assembler = Reassembler(self.contract)
        result = None
        while result is None:
            frame = self.f.receive_frame()
            part = self.f.src.wire.decode(bytes(frame[UDP].payload), 'UDP', direction='TO_36')
            result = assembler.push(part, channel='ETH_0', direction='TO_36', authorized=True, now_ns=0)
        return result.message

    def reply(self, request, transport, *, stage='FAILED', error='TARGET_MISSING'):
        self.rx_sequence += 1
        value = message(130)
        value['header'].update(session_id=73, sequence=self.rx_sequence,
                               transaction_id=request['header']['transaction_id'])
        value['payload'].update(request_sequence=request['header']['sequence'],
            request_message_id=request['message_id'], stage=stage, error=error)
        for raw in self.f.src.wire.encode(value, transport):
            if transport == 'CANFD':
                self.peer.send(can.Message(arbitration_id=raw.arbitration_id, data=raw.data,
                    is_extended_id=False, is_fd=True, bitrate_switch=True, check=True))
            else:
                self.f.receiver.sendto(raw, self.f.src.feedback_endpoint)
        return value

    def test_preflight_checks_native_actions_without_allocation_or_transmission(self):
        handler = self.build([send('can', 0, 7, link_id='CANT'), send('eth', 0, 10)])
        before = self.f.session._next_sequence
        handler.preflight()
        self.assertEqual(self.f.session._next_sequence, before)
        self.assertEqual(self.sender.records, ())
        self.assertEqual(len(self.f.src.l2_records), 1)
        self.assertFalse(handler.execution_ready)
        self.assertFalse(handler.safety_verified)

    def test_native_can_and_scapy_preserve_original_stimulus_sid_and_feedback(self):
        handler = self.build([send('can', 0, 7, link_id='CANT'), send('eth', 0, 10)])
        handler.preflight()
        first = handler.begin(self.action(0), model_step=0, target_step=100)
        can_request = self.can_request()
        second = handler.begin(self.action(1), model_step=0, target_step=100)
        eth_request = self.eth_request()
        self.assertEqual((can_request['header']['session_id'], eth_request['header']['session_id']), (73, 73))
        self.assertEqual((can_request['header']['sequence'], eth_request['header']['sequence']), (2, 3))
        self.assertEqual(can_request['payload'], message(7)['payload'])
        self.assertEqual(eth_request['payload'], message(10)['payload'])
        self.reply(can_request, 'CANFD')
        self.reply(eth_request, 'UDP')
        self.assertEqual(handler.poll(first, model_step=0).error, 'TARGET_MISSING')
        self.assertEqual(handler.poll(second, model_step=0).error, 'TARGET_MISSING')
        self.assertEqual(handler.pending_count, 0)
        self.assertEqual(self.f.session.prepared_inputs, ())

    def test_empty_native_poll_does_not_create_failed_observations(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        handle = handler.begin(self.action(), model_step=0, target_step=100)
        self.can_request()
        rows = self.sender.records
        for _ in range(3):
            self.assertEqual(handler.poll(handle, model_step=0).state, 'PENDING')
        self.assertEqual(self.sender.records, rows)

    def test_intermediate_ack_is_not_completion_and_terminal_is_remote_claim_only(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        handle = handler.begin(self.action(), model_step=0, target_step=100)
        request = self.can_request()
        self.reply(request, 'CANFD', stage='RECEIVED', error='OK')
        self.assertEqual(handler.poll(handle, model_step=0).state, 'PENDING')
        self.reply(request, 'CANFD', stage='APPLIED', error='OK')
        self.assertEqual(handler.poll(handle, model_step=0).state, 'COMPLETE')
        self.assertTrue(all(r.qualification_status == 'NOT_EVALUATED' for r in handler.records))
        self.assertFalse(handler.execution_ready)

    def test_original_wave_periodic_and_fault_values_are_not_replaced(self):
        handler = self.build([wave(event_id='wave', at_step=0, duration_steps=2,
            sample_period_steps=1, link_id='CANT', waveform={'kind': 'RAMP', 'start_value': 0,
                'end_value': 2, 'duration_steps': 2}), periodic('p', 0, 7, period=1, count=2),
            stop('p', 2), send('fault', 3, 11, type='FAULT', link_id='CANT')])
        handler.preflight()
        for action in self.plan.iter_actions():
            handle = handler.begin(action, model_step=action.step, target_step=100+action.step)
            if action.kind == 'PERIODIC_STOP':
                self.assertEqual(handler.poll(handle, model_step=action.step).state, 'COMPLETE')
                continue
            request = self.can_request() if action.link_id == 'CANT' else self.eth_request()
            self.assertEqual(request['payload'], action.stimulus['payload'])
            self.reply(request, 'CANFD' if action.link_id == 'CANT' else 'UDP')
            self.assertEqual(handler.poll(handle, model_step=action.step).state, 'FAILED')

    def test_forged_action_duplicate_begin_and_foreign_handle_reject(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        action = self.action()
        before = self.f.session._next_sequence
        self.rejects('STATE', lambda: handler.begin(replace(action, event_id='other'), model_step=0, target_step=100))
        self.assertEqual(self.f.session._next_sequence, before)
        handle = handler.begin(action, model_step=0, target_step=100)
        self.can_request()
        self.rejects('STATE', lambda: handler.begin(action, model_step=0, target_step=100))
        self.rejects('STATE', lambda: handler.poll(replace(handle), model_step=0))
        self.rejects('STATE', lambda: handler.poll(object(), model_step=0))

    def test_strict_original_steps_and_explicit_target_no_counter_on_rejection(self):
        handler = self.build([send(step=5, mid=7, link_id='CANT')])
        handler.preflight()
        before = self.f.session._next_sequence
        for step, target, error in ((True,100,'SCHEMA'), (4,100,'TIMEOUT'), (6,100,'TIMEOUT'),
                                    (5,True,'SCHEMA'), (5,-1,'SCHEMA')):
            self.rejects(error, lambda: handler.begin(self.action(), model_step=step, target_step=target))
        self.assertEqual(self.f.session._next_sequence, before)

    def test_missing_original_send_branch_never_falls_back(self):
        for branch in ('CUTIL', 'SAVVY', 'CANREPLAY', 'ETHREPLAY'):
            handler = self.build([send(step=0, mid=7, link_id=branch)])
            self.rejects('TARGET_MISSING', handler.preflight)
        self.assertEqual(self.f.session._next_sequence, 2)

    def test_expired_grant_or_unpublished_capability_reject_without_tx(self):
        handler = self.build([send(step=0, mid=10)])
        caps = self.f.session._capabilities_json
        value = self.f.session.capabilities
        value['implemented_message_ids'] = [1]
        self.f.session._capabilities_json = canonicalize(value)
        self.rejects('TARGET_MISSING', handler.preflight)
        self.f.session._capabilities_json = caps
        handler.preflight()
        self.f.clock.value = self.f.session._deadline_ns
        self.rejects('STALE_SESSION', lambda: handler.begin(self.action(), model_step=0, target_step=100))
        self.assertEqual(self.f.session._next_sequence, 2)

    def test_finite_run_budgets_preflight_before_original_input_allocation(self):
        for limits in ({'max_pending': True}, {'max_records': 1}, {'max_bytes': 1}):
            self.rejects('CAPACITY', lambda: self.build([send(step=0, mid=7, link_id='CANT')], **limits))
        self.assertEqual(self.f.session._next_sequence, 2)

    def test_pending_limit_rejects_before_second_original_allocation(self):
        handler = self.build([send('one', 0, 7, link_id='CANT'), send('two', 0, 10)], max_pending=1)
        handler.preflight()
        handler.begin(self.action(0), model_step=0, target_step=100)
        self.can_request()
        before = self.f.session._next_sequence
        self.rejects('BUFFER_FULL', lambda: handler.begin(self.action(1), model_step=0, target_step=100))
        self.assertEqual(self.f.session._next_sequence, before)

    def test_elapsed_original_can_validity_fails_without_late_application_claim(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        handle = handler.begin(self.action(), model_step=0, target_step=100)
        request = self.can_request()
        self.f.clock.value += self.contract.entry(7)['valid_for_ms'] * 1_000_000
        self.reply(request, 'CANFD', stage='APPLIED', error='OK')
        self.assertEqual(handler.poll(handle, model_step=0).error, 'TIMEOUT')

    def test_stop_cancels_only_owned_groups_preserving_shared_backends(self):
        handler = self.build([send(step=0, mid=10)])
        handler.preflight()
        handle = handler.begin(self.action(), model_step=0, target_step=100)
        self.eth_request()
        other = self.owner.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        before = self.f.session._next_sequence
        handler.stop(model_step=0)
        handler.stop(model_step=0)
        self.assertEqual(handler.pending_count, 0)
        self.assertEqual(self.dispatch.pending_count, 1)
        self.assertEqual(self.f.session._next_sequence, before)
        self.assertFalse(self.bus._is_shutdown)
        self.assertIs(self.f.book.validate(self.token), self.token)
        self.assertIs(self.f.book.validate(self.f.token), self.f.token)
        self.assertEqual(handler.poll(handle, model_step=0).state, 'FAILED')
        self.owner.poll()
        self.assertEqual(self.eth_request()['header']['sequence'], other.sequence)

    def test_partial_native_send_failure_is_retained_not_retried(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        with patch.object(self.bus, 'send', side_effect=can.CanOperationError('injected native send failure')) as native:
            handle = handler.begin(self.action(), model_step=0, target_step=100)
        self.assertEqual(native.call_count, 1)
        self.assertEqual(handler.poll(handle, model_step=0).error, 'RESOURCE')
        self.rejects('STATE', lambda: handler.begin(self.action(), model_step=0, target_step=100))
        self.assertTrue(any(r.kind == 'FAILED' for r in self.sender.records))
        handler.stop(model_step=0)

    def test_original_record_drain_cannot_turn_pending_request_into_success(self):
        handler = self.build([send(step=0, mid=10)])
        handler.preflight()
        handle = handler.begin(self.action(), model_step=0, target_step=100)
        self.eth_request()
        self.dispatch.drain_records()
        self.rejects('STATE', lambda: handler.poll(handle, model_step=0))
        handler.stop(model_step=0)
        self.assertEqual(self.dispatch.pending_count, 0)

    def test_reentry_rejects_before_allocating_another_event(self):
        handler = self.build([send('one',0,7,link_id='CANT'),send('two',0,10)])
        handler.preflight()
        original = self.bus.send
        def sending(frame, timeout=None):
            self.rejects('STATE', lambda: handler.begin(self.action(1), model_step=0, target_step=100))
            return original(frame, timeout)
        with patch.object(self.bus, 'send', sending):
            handler.begin(self.action(0), model_step=0, target_step=100)
        self.can_request()
        self.assertEqual(self.f.session._next_sequence, 3)

    def test_other_event_handlers_are_not_claimed_as_implemented(self):
        assertion = {**source_inputs()['scenario']['assertions'][0], 'assertion_id': 'wait-native'}
        handler = self.build([{'event_id':'wait', 'at_step':0, 'priority':10,
            'link_id':'ETHGEN', 'type':'WAIT', 'assertion':assertion}])
        handler.preflight()
        self.rejects('TARGET_MISSING', lambda: handler.begin(self.action(), model_step=0, target_step=100))
        self.assertEqual(self.f.session._next_sequence, 2)

    def test_stop_still_cancels_udp_group_after_begin_poll_failure(self):
        handler = self.build([send(step=0, mid=10)])
        handler.preflight()
        with patch.object(self.owner, 'poll', side_effect=ICDError('RESOURCE', 'injected dispatcher operation failure')):
            handle = handler.begin(self.action(), model_step=0, target_step=100)
        self.assertEqual(handler.poll(handle, model_step=0).error, 'RESOURCE')
        self.assertEqual(self.dispatch.pending_count, 1)
        handler.stop(model_step=0)
        self.assertEqual(self.dispatch.pending_count, 0)
        self.assertFalse(any(row.kind == 'TX' for row in self.dispatch.records))

    def test_local_reclaim_failure_is_not_hidden_by_remote_terminal_claim(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        handle = handler.begin(self.action(), model_step=0, target_step=100)
        request = self.can_request()
        self.reply(request, 'CANFD', stage='APPLIED', error='OK')
        with patch.object(self.owner, 'discard_can', side_effect=ICDError('RESOURCE', 'injected reclaim failure')):
            result = handler.poll(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED', 'RESOURCE'))
        self.assertTrue(handler.pending_local_cleanup)
        self.assertEqual([r.kind for r in handler.records], ['STARTED', 'COMPLETE', 'LOCAL_RECLAIM_FAILED'])
        handler.stop(model_step=0)
        self.assertFalse(handler.pending_local_cleanup)
        self.assertEqual(self.f.session.prepared_inputs, ())

    def test_typed_action_metadata_cannot_use_equal_bool_values(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        for field, value in (('index', False), ('step', False), ('kind', []), ('event_id', [])):
            self.rejects('STATE', lambda: handler.begin(replace(self.action(), **{field:value}), model_step=0, target_step=100))
        self.assertEqual(self.f.session._next_sequence, 2)

    def test_invalid_original_contract_is_a_closed_error_not_attribute_failure(self):
        self.build([send(step=0, mid=10)])
        self.rejects('HASH', lambda: self.module.NativeScenarioActions(None, self.plan, self.owner))

    def test_standalone_original_scapy_does_not_require_an_unrelated_can_backend(self):
        self.owner.close()
        self.dispatch.close()
        dispatcher = UDPDispatcher(self.f.session)
        self.addCleanup(dispatcher.close)
        plan = ScenarioPlan.compile(self.contract, scenario([send(step=0, mid=10)]), model_id='quadrotor_hil')
        handler = self.module.NativeScenarioActions(self.contract, plan, dispatcher)
        handler.preflight()
        handle = handler.begin(next(plan.iter_actions()), model_step=0, target_step=100)
        self.assertEqual(self.eth_request()['header']['sequence'], 2)
        handler.stop(model_step=0)
        self.assertEqual(handler.poll(handle, model_step=0).state, 'FAILED')

    def test_plain_udp_is_not_used_as_original_ethgen(self):
        import test_can_signal as can_cases
        fixture = can_cases.CANSignalTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.live()
        dispatcher = UDPDispatcher(fixture.session)
        self.addCleanup(dispatcher.close)
        plan = ScenarioPlan.compile(self.contract, scenario([send(step=0, mid=10)]), model_id='quadrotor_hil')
        handler = self.module.NativeScenarioActions(self.contract, plan, dispatcher)
        self.rejects('TARGET_MISSING', handler.preflight)
        self.assertEqual(fixture.session._next_sequence, 2)

    def test_original_selected_protocol_must_declare_every_scheduled_can_message(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        descriptor = source_inputs()['protocol']
        descriptor['message_ids'].remove(7)
        parser = ProtocolParser(self.contract)
        parser.parse(descriptor, resources())
        self.builder.protocol = parser
        self.rejects('RESOURCE', handler.preflight)
        self.assertEqual(self.f.session._next_sequence, 2)
        self.assertEqual(handler.records, ())

    def test_can_only_plan_still_requires_common_original_reservation_book(self):
        from input_simulator.tools import ChannelReservations
        self.owner.close()
        self.dispatch.close()
        book = ChannelReservations()
        token = book.reserve('separate-book', 'CANT', ('can0',), mode='SEND')
        builder = LiveToolInputBuilder(book, self.f.session, protocol=self.builder.protocol)
        bus = can.Bus(interface='virtual', channel='separate-'+uuid.uuid4().hex, ignore_config=True)
        self.addCleanup(bus.shutdown)
        sender = CANSignalSender(builder, token, ExportBinding('CANFD_0','can0'), bus=bus)
        dispatcher = UDPDispatcher(self.f.session)
        self.addCleanup(dispatcher.close)
        owner = NativeToolCoordinator(dispatcher, (sender,))
        self.addCleanup(owner.close)
        plan = ScenarioPlan.compile(self.contract, scenario([send(step=0,mid=7,link_id='CANT')]), model_id='quadrotor_hil')
        handler = self.module.NativeScenarioActions(self.contract, plan, owner, can_sender=sender)
        self.rejects('STATE', handler.preflight)
        self.assertEqual(self.f.session._next_sequence, 2)

    def test_local_can_reclaim_survives_failed_and_completed_shared_close(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        handler.begin(self.action(), model_step=0, target_step=100)
        self.can_request()
        with patch.object(self.bus, 'shutdown', side_effect=can.CanOperationError('injected close failure')):
            self.rejects('RESOURCE', self.owner.close)
        handler.stop(model_step=0)
        self.assertFalse(handler.pending_local_cleanup)
        self.owner.close()
        handler.stop(model_step=0)
        self.assertEqual(self.f.session.prepared_inputs, ())

    def test_local_can_reclaim_survives_detach_and_new_dispatcher(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        handler.begin(self.action(), model_step=0, target_step=100)
        self.can_request()
        self.owner.close()
        self.dispatch.close()
        replacement = UDPDispatcher(self.f.session)
        self.addCleanup(replacement.close)
        handler.stop(model_step=0)
        self.assertFalse(handler.pending_local_cleanup)
        self.assertEqual(self.f.session.prepared_inputs, ())
        self.assertIs(self.f.session._dispatcher, replacement)

    def test_failed_post_allocation_preparation_has_owned_recoverable_context(self):
        handler = self.build([send(step=0, mid=7, link_id='CANT')])
        handler.preflight()
        original = self.builder._materialize
        calls = 0
        def failure(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ICDError('RESOURCE', 'injected after actual source allocation')
            return original(*args)
        with patch.object(self.builder, '_materialize', side_effect=failure):
            handle = handler.begin(self.action(), model_step=0, target_step=100)
        self.assertEqual(handler.poll(handle, model_step=0).error, 'RESOURCE')
        self.assertTrue(handler.pending_local_cleanup)
        item = self.f.session.prepared_inputs[0]
        self.assertEqual(handler.records[0].request_json, item.input_json)
        self.assertEqual(self.f.session._next_sequence, 3)
        self.assertIsNone(self.peer.recv(0))
        self.owner.close()
        self.dispatch.close()
        replacement = UDPDispatcher(self.f.session)
        self.addCleanup(replacement.close)
        handler.stop(model_step=0)
        self.assertEqual(self.f.session.prepared_inputs, ())
        self.assertFalse(handler.pending_local_cleanup)
        self.assertIs(self.f.session._dispatcher, replacement)
        self.assertEqual(self.f.session._next_sequence, 3)


if __name__ == '__main__':
    unittest.main()
