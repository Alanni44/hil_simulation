"""One original standard session across real UDP and original CAN library peers."""

from dataclasses import replace
from contextvars import copy_context
import importlib
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import can

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from icd_runtime.reassembly import Reassembler
from input_simulator.dispatch import UDPDispatcher
from input_simulator.model_clock import ObservedModelClock
from input_simulator.replay_export import ExportBinding
import test_can_signal as can_cases


class NativeToolTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.native_tools'),
                             'original shared native tool session missing')
        self.module = importlib.import_module('input_simulator.native_tools')
        self.f = can_cases.CANSignalTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.live(implemented=[1, 2, 7, 10, 33])
        self.sender = self.f.sender()
        self.dispatch = UDPDispatcher(self.f.session)
        self.addCleanup(self.dispatch.close)
        self.coordinator = self.module.NativeToolCoordinator(self.dispatch, (self.sender,))
        self.addCleanup(self.coordinator.close)

    def plan(self, mid=7, **kwargs):
        return self.coordinator.prepare_can(self.sender, {'message_id': mid, 'payload': message(mid)['payload']},
                                            target_step=100, **kwargs)

    def udp_request(self):
        assembly = Reassembler(self.contract)
        result = None
        while result is None:
            packet, _ = self.f.receiver.recvfrom(1500)
            result = assembly.push(self.f.transport.wire.decode(packet, 'UDP', direction='TO_36'),
                channel='ETH_0', direction='TO_36', authorized=True, now_ns=0)
        return result.message

    def emit_udp(self, request, *, mid=130, sequence=3):
        reply = message(mid)
        reply['header'].update(session_id=request['header']['session_id'], sequence=sequence,
                               transaction_id=request['header']['transaction_id'])
        if mid == 130:
            reply['payload'].update(request_sequence=request['header']['sequence'],
                request_message_id=request['message_id'], stage='FAILED', error='TARGET_MISSING')
        elif mid == 142:
            reply['payload']['nonce'] = request['payload']['nonce']
        for packet in self.f.transport.wire.encode(reply, 'UDP'):
            self.f.receiver.sendto(packet, self.f.transport.feedback_endpoint)
        return reply

    def test_actual_original_can_and_udp_share_sid_counters_and_feedback(self):
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        header = self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        self.coordinator.poll()
        request = self.udp_request()
        self.assertEqual((plan.source_input.message['header']['session_id'], header.session_id,
                          plan.source_input.message['header']['sequence'], header.sequence), (73, 73, 2, 3))
        actual_can = self.f.emit(plan, sequence=2)
        self.assertEqual(self.coordinator.receive_can(self.sender, plan, timeout=0.2), actual_can)
        actual_udp = self.emit_udp(request)
        self.coordinator.poll()
        self.assertEqual(self.dispatch.records[-2].reply, actual_udp)
        self.assertEqual(self.f.session.last_rx_sequence, 3)
        self.assertFalse(self.coordinator.execution_ready)
        self.assertFalse(self.coordinator.safety_verified)

    def test_direct_native_and_source_apis_cannot_bypass_dispatcher(self):
        plan = self.plan()
        for action in (lambda: self.sender.send(plan), lambda: self.f.builder.validate(plan),
                       lambda: self.f.builder.prepare(self.f.token, {'message_id': 7, 'payload': message(7)['payload']},
                                                      self.f.binding, target_step=100),
                       lambda: self.f.session.heartbeat(100, target_step=100)):
            self.rejects('STATE', action)
        self.assertEqual(self.sender.records, ())

    def test_unregistered_or_forged_original_instances_and_plans_reject(self):
        plan = self.plan()
        self.rejects('STATE', lambda: self.coordinator.send_can(object(), plan))
        self.rejects('STATE', lambda: self.coordinator.send_can(self.sender, replace(plan)))
        self.rejects('STATE', lambda: self.module.NativeToolCoordinator(self.dispatch, (self.sender,)))

    def test_newer_udp_first_tx_prevents_older_prepared_can_first_tx(self):
        plan = self.plan()
        self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        self.coordinator.poll()
        self.udp_request()
        self.rejects('STATE', lambda: self.coordinator.send_can(self.sender, plan))
        self.assertEqual(self.sender.records, ())
        self.assertIsNone(self.f.peer.recv(0))

    def test_newer_can_first_tx_prevents_older_pending_udp_first_tx(self):
        self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.assertEqual(self.coordinator.poll(), 0)
        self.assertEqual(self.dispatch.records[-1].error, 'STATE')

    def test_cross_link_heartbeat_transaction_floor_and_standard_model_observation(self):
        plan = self.plan(2, transaction_id=20)
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.f.emit(plan, sequence=2, mid=131)
        self.coordinator.receive_can(self.sender, plan, timeout=0.2)
        self.assertEqual(ObservedModelClock(self.f.session).snapshot().transport, 'CANFD')
        self.rejects('STATE', lambda: self.coordinator.submit({'message_id': 2, 'payload': message(2)['payload']},
            target_step=100, transaction_id=20))

    def test_reentry_and_other_thread_cannot_get_delegated_tool_authority(self):
        plan = self.plan()
        original = self.f.bus.send
        results = []
        def sending(frame, timeout=None):
            self.rejects('STATE', lambda: self.coordinator.poll())
            def other_thread():
                try:
                    self.f.builder.validate(plan)
                except ICDError as error:
                    results.append(error.code)
            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            return original(frame, timeout)
        with patch.object(self.f.bus, 'send', sending):
            self.coordinator.send_can(self.sender, plan)
        self.assertTrue(results and set(results) == {'STATE'})

    def test_all_local_close_preserves_session_dispatcher_and_send_reservation(self):
        self.coordinator.close()
        self.coordinator.close()
        self.assertTrue(self.f.bus._is_shutdown)
        self.assertIs(self.f.book.validate(self.f.token), self.f.token)
        self.assertEqual(self.f.session.session_id, 73)
        self.assertFalse(self.dispatch._closed)
        self.rejects('STATE', lambda: self.coordinator.poll())

    def test_failed_close_keeps_same_native_handle_for_retry(self):
        original = self.f.bus.shutdown
        calls = []
        def shutting_down():
            calls.append(self.f.bus)
            if len(calls) == 1:
                raise can.CanOperationError('test first close failure')
            return original()
        with patch.object(self.f.bus, 'shutdown', shutting_down):
            self.rejects('RESOURCE', self.coordinator.close)
            self.rejects('STATE', self.coordinator.poll)
            self.coordinator.close()
        self.assertEqual(calls, [self.f.bus, self.f.bus])
        self.assertIs(self.f.book.validate(self.f.token), self.f.token)

    def test_source_and_dispatcher_busy_do_not_allocate_or_send(self):
        before = self.f.session._next_sequence
        with self.dispatch._operation():
            self.rejects('STATE', lambda: self.plan())
        with self.f.session._operation(owner=self.dispatch):
            self.rejects('STATE', lambda: self.plan())
        self.assertEqual(self.f.session._next_sequence, before)
        self.assertEqual(self.sender.records, ())

    def test_original_udp_retry_is_not_a_new_first_tx_after_can(self):
        self.coordinator.submit({'message_id': 33, 'payload': message(33)['payload']}, target_step=100)
        self.coordinator.poll()
        original = self.udp_request()
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.f.clock.value += self.contract.catalogue['policy']['ack_timeout_ms'] * 1_000_000
        self.assertEqual(self.coordinator.poll(), 1)
        self.assertEqual(self.udp_request(), original)
        self.emit_udp(original, mid=142, sequence=2)
        self.coordinator.poll()
        self.assertEqual(self.dispatch.pending_count, 0)

    def test_discard_after_retirement_reclaims_only_local_original_plan(self):
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.coordinator.retire_can(self.sender, plan)
        method = getattr(self.coordinator, 'discard_can', None)
        self.assertTrue(callable(method), 'coordinated original input reclaim missing')
        before = self.f.session._next_sequence
        method(self.sender, plan)
        self.assertEqual(self.f.session.prepared_inputs, ())
        self.assertEqual(self.f.session._next_sequence, before)
        self.rejects('STATE', lambda: self.coordinator.send_can(self.sender, plan))
        self.assertEqual(self.plan().source_input.message['header']['sequence'], before)

    def test_deferred_udp_first_attempt_cannot_send_after_newer_can(self):
        self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        with patch.object(self.f.transport, 'transmit_fragment', return_value=False):
            self.coordinator.poll()
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.assertEqual(self.coordinator.poll(), 0)
        self.assertEqual(self.dispatch.records[-1].error, 'STATE')

    def test_original_recorder_cannot_be_bypassed_for_native_evidence(self):
        from input_simulator.evidence_recorder import ObservationRecorder
        plan = self.plan()
        with tempfile.TemporaryDirectory() as directory:
            recorder = ObservationRecorder(self.dispatch, Path(directory)/'recording', run_id='native-test')
            try:
                self.rejects('STATE', lambda: self.coordinator.send_can(self.sender, plan))
                self.assertEqual(self.sender.records, ())
                recorder.flush()
            finally:
                recorder.close(timeout=2)
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)

    def test_nonfresh_input_allocation_and_invalid_sender_list_reject(self):
        for senders in ([], (), (self.sender,)*5, (object(),)):
            self.rejects('STATE', lambda: self.module.NativeToolCoordinator(self.dispatch, senders))
        self.coordinator.close()
        self.dispatch.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        self.rejects('STATE', lambda: self.module.NativeToolCoordinator(self.dispatch, (self.sender,)))

    def test_all_four_original_can_channels_share_one_actual_grant(self):
        self.coordinator.close()
        self.dispatch.close()
        senders, peers = [], []
        for number in range(4):
            channel = 'native-'+uuid.uuid4().hex
            bus = can.Bus(interface='virtual', channel=channel, ignore_config=True)
            peer = can.Bus(interface='virtual', channel=channel, ignore_config=True)
            self.addCleanup(bus.shutdown)
            self.addCleanup(peer.shutdown)
            token = self.f.token if number == 0 else self.f.book.reserve(
                'native-'+str(number), 'CANT', ('can'+str(number),), mode='SEND')
            sender = self.f.module.CANSignalSender(self.f.builder, token,
                ExportBinding('CANFD_'+str(number), 'can'+str(number)), bus=bus)
            senders.append(sender)
            peers.append(peer)
        dispatcher = UDPDispatcher(self.f.session)
        self.addCleanup(dispatcher.close)
        coordinator = self.module.NativeToolCoordinator(dispatcher, tuple(senders))
        self.addCleanup(coordinator.close)
        for sequence, (sender, peer) in enumerate(zip(senders, peers), 2):
            plan = coordinator.prepare_can(sender, {'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
            coordinator.send_can(sender, plan)
            self.assertEqual(plan.source_input.message['header']['sequence'], sequence)
            self.assertEqual(plan.source_input.message['header']['session_id'], 73)
            for frame in plan.source_input.frames:
                self.assertEqual(bytes(peer.recv(0.1).data), frame.data)

    def test_direct_selected_sender_and_builder_reentry_reject_before_mutation(self):
        plan = self.plan()
        before = self.f.session._next_sequence
        original = self.f.bus.send
        def sending(frame, timeout=None):
            self.rejects('STATE', lambda: self.sender.retire(plan))
            self.rejects('STATE', lambda: self.f.builder.discard(plan))
            self.rejects('STATE', lambda: self.f.builder.validate(plan))
            return original(frame, timeout)
        with patch.object(self.f.bus, 'send', sending):
            self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.assertEqual(self.sender.pending_count, 1)
        self.assertEqual(self.f.session._next_sequence, before)
        actual = self.f.emit(plan, sequence=2)
        self.assertEqual(self.coordinator.receive_can(self.sender, plan, timeout=0.2), actual)

    def test_copied_old_scope_cannot_bypass_current_native_lock(self):
        old_plan = self.plan()
        captured = []
        original = self.f.bus.send
        def capturing(frame, timeout=None):
            if not captured:
                captured.append(copy_context())
            return original(frame, timeout)
        with patch.object(self.f.bus, 'send', capturing):
            self.coordinator.send_can(self.sender, old_plan)
        self.f.consume(old_plan)
        self.coordinator.retire_can(self.sender, old_plan)
        plan = self.plan()
        def sending(frame, timeout=None):
            self.rejects('STATE', lambda: captured[0].run(self.sender.retire, plan))
            self.rejects('STATE', lambda: captured[0].run(self.f.builder.validate, plan))
            return original(frame, timeout)
        with patch.object(self.f.bus, 'send', sending):
            self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.assertEqual(self.sender.pending_count, 1)

    def test_failed_coordinator_close_blocks_original_udp_transmission(self):
        self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        with patch.object(self.f.bus, 'shutdown', side_effect=can.CanOperationError('test close failure')):
            self.rejects('RESOURCE', self.coordinator.close)
        self.rejects('STATE', self.dispatch.poll)
        self.assertFalse(any(row.kind == 'TX' for row in self.dispatch.records))
        self.coordinator.close()
        self.assertEqual(self.dispatch.poll(), 1)
        self.udp_request()

    def test_dispatcher_replacement_waits_for_native_coordinator_cleanup(self):
        self.dispatch.close()
        self.rejects('STATE', lambda: UDPDispatcher(self.f.session))
        self.coordinator.close()
        self.assertTrue(self.f.bus._is_shutdown)
        replacement = UDPDispatcher(self.f.session)
        self.addCleanup(replacement.close)
        self.assertIs(self.f.session._dispatcher, replacement)

    def test_inflight_can_plan_requires_retirement_before_discard(self):
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        self.rejects('STATE', lambda: self.coordinator.discard_can(self.sender, plan))
        self.assertEqual(self.sender.pending_count, 1)
        actual = self.f.emit(plan, sequence=2)
        self.assertEqual(self.coordinator.receive_can(self.sender, plan, timeout=0.2), actual)
        self.coordinator.discard_can(self.sender, plan)
        self.assertEqual(self.f.session.prepared_inputs, ())

    def test_closed_dispatcher_does_not_release_source_before_native_cleanup(self):
        self.dispatch.close()
        before = self.f.session._next_sequence
        self.rejects('STATE', lambda: self.f.session.allocate_header(7, 100))
        self.rejects('STATE', lambda: self.f.session.prepare_input(
            {'message_id': 7, 'payload': message(7)['payload']}, 'CANFD', target_step=100))
        self.rejects('STATE', self.f.session.abandon)
        self.assertEqual(self.f.session._next_sequence, before)
        self.assertEqual(self.f.session.session_id, 73)
        self.coordinator.close()
        self.assertEqual(self.f.session.allocate_header(7, 100).sequence, before)

    def test_other_channel_cannot_discard_shared_builder_inflight_plan(self):
        self.coordinator.close()
        self.dispatch.close()
        senders = []
        peers = []
        for number in range(2):
            channel = 'native-'+uuid.uuid4().hex
            bus = can.Bus(interface='virtual', channel=channel, ignore_config=True)
            peer = can.Bus(interface='virtual', channel=channel, ignore_config=True)
            self.addCleanup(bus.shutdown)
            self.addCleanup(peer.shutdown)
            token = self.f.token if number == 0 else self.f.book.reserve(
                'native-'+str(number), 'CANT', ('can'+str(number),), mode='SEND')
            senders.append(self.f.module.CANSignalSender(self.f.builder, token,
                ExportBinding('CANFD_'+str(number), 'can'+str(number)), bus=bus))
            peers.append(peer)
        dispatcher = UDPDispatcher(self.f.session)
        self.addCleanup(dispatcher.close)
        coordinator = self.module.NativeToolCoordinator(dispatcher, tuple(senders))
        self.addCleanup(coordinator.close)
        plan = coordinator.prepare_can(senders[0], {'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        self.rejects('STATE', lambda: coordinator.discard_can(senders[1], plan))
        coordinator.send_can(senders[0], plan)
        for frame in plan.source_input.frames:
            self.assertEqual(bytes(peers[0].recv(0.1).data), frame.data)
        self.rejects('STATE', lambda: coordinator.discard_can(senders[1], plan))
        self.assertEqual(senders[0].pending_count, 1)
        self.assertIn(plan.source_input, self.f.session.prepared_inputs)
        coordinator.retire_can(senders[0], plan)
        coordinator.discard_can(senders[0], plan)

    def test_nonblocking_native_poll_empty_is_not_a_failure(self):
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        method = getattr(self.coordinator, 'poll_can', None)
        self.assertTrue(callable(method), 'original nonblocking CAN poll missing')
        before = self.sender.records
        for _ in range(3):
            self.assertIsNone(method(self.sender, plan))
        self.assertEqual(self.sender.records, before)
        actual = self.f.emit(plan, sequence=2)
        self.assertEqual(method(self.sender, plan), actual)

    def test_cancel_only_the_exact_owned_udp_group_before_native_tx(self):
        one = self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        two = self.coordinator.submit({'message_id': 10, 'payload': message(10)['payload']}, target_step=100)
        method = getattr(self.coordinator, 'cancel', None)
        self.assertTrue(callable(method), 'original per-group cancellation missing')
        before = self.f.session._next_sequence
        self.rejects('STATE', lambda: method(replace(one)))
        method(one)
        self.assertEqual(self.dispatch.pending_count, 1)
        self.assertEqual(self.f.session._next_sequence, before)
        self.coordinator.poll()
        self.assertEqual(self.udp_request()['header']['sequence'], two.sequence)
        self.assertEqual([r.header for r in self.dispatch.records if r.kind == 'CANCEL'], [one])
        self.assertIs(self.f.book.validate(self.f.token), self.f.token)

    def test_owned_udp_cancel_allowed_after_expiry_or_failed_close(self):
        header = self.coordinator.submit({'message_id': 7, 'payload': message(7)['payload']}, target_step=100)
        method = getattr(self.coordinator, 'cancel', None)
        self.assertTrue(callable(method), 'cleanup cancellation missing')
        with patch.object(self.f.bus, 'shutdown', side_effect=can.CanOperationError('test close failure')):
            self.rejects('RESOURCE', self.coordinator.close)
        self.f.clock.value = self.f.session._deadline_ns
        method(header)
        self.assertEqual(self.dispatch.pending_count, 0)
        self.assertFalse(any(row.kind == 'TX' for row in self.dispatch.records))

    def test_detached_cleanup_keeps_records_counters_and_rejects_send_or_reentry(self):
        plan = self.plan()
        self.coordinator.send_can(self.sender, plan)
        self.f.consume(plan)
        original_records = self.sender.records
        counter = self.f.session._next_sequence
        self.coordinator.close()
        self.dispatch.close()
        replacement = UDPDispatcher(self.f.session)
        self.addCleanup(replacement.close)
        self.rejects('STATE', lambda: self.coordinator.send_can(self.sender, plan))
        original = self.sender.retire
        def retire(value):
            self.rejects('STATE', lambda: self.sender.send(value))
            self.rejects('STATE', lambda: self.f.builder.prepare(self.f.token,
                {'message_id': 7, 'payload': message(7)['payload']}, self.f.binding, target_step=100))
            original(value)
        with patch.object(self.sender, 'retire', side_effect=retire):
            self.coordinator.retire_can(self.sender, plan)
        self.coordinator.discard_can(self.sender, plan)
        self.assertEqual(self.sender.records, original_records)
        self.assertEqual(self.f.session._next_sequence, counter)
        self.assertIs(self.f.session._dispatcher, replacement)
        self.assertEqual(self.f.session.prepared_inputs, ())
        self.assertIs(self.f.book.validate(self.f.token), self.f.token)


if __name__ == '__main__':
    unittest.main()
