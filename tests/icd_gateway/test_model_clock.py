"""Standard protocol observations, not a qualified model clock or target."""

from dataclasses import FrozenInstanceError
import importlib
import threading
import time
import unittest
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from input_simulator.session import SourceSession
import test_source_session as session_cases
import test_can_signal as can_cases
import test_dispatch as dispatch_cases


class ModelClockTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.model_clock'),
                             'original standard feedback model clock missing')
        self.module = importlib.import_module('input_simulator.model_clock')
        self.clock = session_cases.LocalClock()
        self.peer = session_cases.UnitPeer(self.contract, self.clock)
        self.session = SourceSession(self.peer, message(1)['payload']['identity'],
                                     ('STIMULUS', 'OBSERVER'), clock=self.clock)
        self.session.open()
        self.reader = self.module.ObservedModelClock(self.session)

    def status(self, step=100, state='RUNNING'):
        def modify(reply):
            reply['payload'].update(model_step=step, state=state)
            return reply
        self.peer.modify = modify
        return self.session.heartbeat(step, target_step=step)

    def test_requires_actual_status_not_grant_or_an_arbitrary_object(self):
        self.rejects('TARGET_MISSING', self.reader.snapshot)
        self.rejects('STATE', lambda: self.module.ObservedModelClock({}))
        self.assertFalse(hasattr(self.reader, 'observe'))

    def test_immutable_detached_snapshot_retains_original_exchange_and_identity(self):
        reply = self.status()
        snapshot = self.reader.snapshot()
        record = self.session.records[-1]
        self.assertEqual((snapshot.session_id, snapshot.model_id, snapshot.model_step, snapshot.state),
                         (73, 'quadrotor_hil', 100, 'RUNNING'))
        self.assertEqual((snapshot.request_json, snapshot.status_json, snapshot.started_ns, snapshot.completed_ns),
                         (record.request_json, record.reply_json, record.started_ns, record.completed_ns))
        snapshot.status['payload']['model_step'] = 9
        reply['payload']['model_step'] = 8
        self.assertEqual(self.reader.snapshot().model_step, 100)
        with self.assertRaises(FrozenInstanceError):
            snapshot.model_step = 8
        self.assertFalse(snapshot.execution_ready)
        self.assertFalse(snapshot.synchronized)
        self.assertFalse(snapshot.safety_verified)
        self.assertEqual(snapshot.qualification_status, 'NOT_EVALUATED')

    def test_local_elapsed_time_never_advances_reported_model_step(self):
        self.status()
        self.clock.value += 100_000_000
        self.assertEqual(self.reader.require_step(100).model_step, 100)
        self.rejects('CLOCK_UNSYNC', lambda: self.reader.require_step(200))

    def test_frozen_240ms_validity_exact_boundary_and_delayed_arrival(self):
        self.status()
        self.clock.value += 239_999_999
        self.reader.snapshot()
        self.clock.value += 1
        self.rejects('EXPIRED', self.reader.snapshot)
        self.peer.delay_ns = 240_000_000
        self.status(200)
        self.rejects('EXPIRED', self.reader.snapshot)

    def test_current_lease_is_required_even_with_cached_status(self):
        self.status()
        self.clock.value += 1_000_000_000
        self.rejects('STALE_SESSION', self.reader.snapshot)

    def test_strict_exact_step_and_required_state(self):
        self.status(state='PAUSED')
        for step in (True, 100.0, -1, 0x100000000):
            self.rejects('SCHEMA', lambda: self.reader.require_step(step))
        self.reader.require_step(100, required_state='PAUSED')
        self.rejects('STATE', lambda: self.reader.require_step(100, required_state='RUNNING'))
        self.rejects('SCHEMA', lambda: self.reader.require_step(100, required_state='UNKNOWN'))

    def test_unread_regression_survives_drain_and_reader_replacement(self):
        self.status(100)
        self.session.drain_records()
        self.status(99)
        self.rejects('CLOCK_UNSYNC', self.module.ObservedModelClock(self.session).snapshot)
        self.status(101)
        self.assertEqual(self.reader.snapshot().model_step, 101)

    def test_duplicate_feedback_cannot_refresh_original_deadline(self):
        self.status()
        self.peer.sequence -= 1
        self.clock.value += 200_000_000
        self.status()
        self.clock.value += 40_000_000
        self.rejects('EXPIRED', self.reader.snapshot)

    def test_reused_heartbeat_transaction_cannot_retime_or_replace_sample(self):
        self.status()
        transaction = self.peer.requests[-1]['header']['transaction_id']
        self.clock.value += 200_000_000
        before = len(self.peer.requests)
        self.rejects('STATE', lambda: self.session.request(
            {'message_id': 2, 'payload': {'last_rx_sequence': 2, 'sender_step': 100}},
            target_step=100, transaction_id=transaction))
        self.assertEqual(len(self.peer.requests), before)
        self.clock.value += 40_000_000
        self.rejects('EXPIRED', self.reader.snapshot)

    def test_private_feedback_capture_cannot_bypass_actual_operation_owner(self):
        reply = self.status()
        record = self.session.records[-1]
        self.rejects('STATE', lambda: self.session._remember_model_feedback(
            record.request, reply, record.started_ns, record.completed_ns,
            transport='UDP', channel='ETH_0', fresh=True))
        self.assertEqual(self.reader.snapshot().status, reply)

    def test_local_monotonic_clock_reversal_is_not_a_model_reset(self):
        self.status()
        self.clock.value -= 1
        self.rejects('SCHEMA', self.reader.snapshot)

    def test_new_sid_requires_new_status_and_allows_reset_step(self):
        self.status()
        self.session.abandon()
        self.rejects('STALE_SESSION', self.reader.snapshot)
        self.peer.sid += 1
        self.peer.modify = lambda response: response
        self.session.open()
        self.rejects('TARGET_MISSING', self.reader.snapshot)
        self.status(0, 'CONFIGURED')
        snapshot = self.reader.snapshot()
        self.assertEqual((snapshot.session_id, snapshot.model_step), (74, 0))

    def lifecycle(self, action, *, stage='APPLIED', probe=True):
        original = self.peer.modify
        def reply(value):
            if value['message_id'] == 129:
                value['payload']['capabilities']['implemented_message_ids'].append(4)
                if probe:
                    value['payload']['capabilities']['available_probes'] = ['consumer.Lifecycle']
            elif value['message_id'] == 130:
                value['payload'].update(stage=stage, error='OK' if stage != 'FAILED' else 'STATE',
                                        applied_step=0, probe_id=1004)
            return value
        self.session.abandon()
        self.peer.sid += 1
        self.peer.modify = reply
        self.session.open()
        self.status()
        self.peer.modify = reply
        self.session.request({'message_id': 4, 'payload': {
            'action': action, 'expected_state': 'PAUSED',
            'reset_policy': 'NEW_SESSION_RESTORE_INITIAL' if action == 'RESET' else 'NOT_APPLICABLE'}},
            target_step=100)
        self.peer.modify = original

    def test_applied_reset_and_resume_invalidate_old_sid_until_new_grant(self):
        for action in ('RESET', 'RESUME'):
            self.lifecycle(action)
            self.rejects('STALE_SESSION', self.reader.snapshot)
            self.status(0)
            self.rejects('STALE_SESSION', self.reader.snapshot)

    def test_failed_received_or_unpublished_lifecycle_does_not_claim_reset(self):
        for stage, probe in (('FAILED', True), ('RECEIVED', True), ('APPLIED', False)):
            self.lifecycle('RESET', stage=stage, probe=probe)
            self.assertEqual(self.reader.snapshot().model_step, 100)

    def test_source_owner_lock_and_closed_session_are_respected(self):
        self.status()
        with self.session._operation():
            self.rejects('STATE', self.reader.snapshot)
        self.session.close()
        self.rejects('STATE', self.reader.snapshot)

    def test_original_can_feedback_uses_source_clock_domain(self):
        fixture = can_cases.CANSignalTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.live()
        sender, plan = fixture.sender(), fixture.plan(2)
        sender.send(plan)
        fixture.consume(plan)
        fixture.emit(plan, mid=131)
        sender.receive_for(plan)
        snapshot = self.module.ObservedModelClock(fixture.session).snapshot()
        self.assertEqual((snapshot.transport, snapshot.channel), ('CANFD', 'CANFD_0'))
        self.assertEqual((snapshot.started_ns, snapshot.completed_ns), (fixture.clock.value, fixture.clock.value))
        fixture.clock.value += 240_000_000
        self.rejects('EXPIRED', self.module.ObservedModelClock(fixture.session).snapshot)

    def test_dispatcher_feedback_reader_never_sends_or_drains(self):
        fixture = dispatch_cases.DispatcherTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_peer()
        fixture.dispatch.submit({'message_id': 2, 'payload': {'last_rx_sequence': 1, 'sender_step': 100}}, target_step=100)
        fixture.dispatch.poll()
        _, requests = fixture.collect()
        reply = message(131)
        reply['header'].update(session_id=73, sequence=2,
                               transaction_id=requests[0]['header']['transaction_id'])
        reply['payload'].update(model_step=100, state='RUNNING')
        fixture.emit(reply)
        fixture.dispatch.poll()
        before = (fixture.session.records, fixture.dispatch.records, fixture.session._next_sequence)
        reader = self.module.ObservedModelClock(fixture.session)
        self.assertEqual(reader.snapshot().model_step, 100)
        self.assertEqual(reader.snapshot().transport, 'UDP')
        self.assertEqual(before, (fixture.session.records, fixture.dispatch.records, fixture.session._next_sequence))
        with fixture.dispatch._operation():
            self.rejects('STATE', reader.snapshot)

    def test_serial_udp_status_is_bound_to_actual_socket_request(self):
        fixture = dispatch_cases.DispatcherTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_peer()
        fixture.dispatch.close()
        errors = []
        def heartbeat():
            try:
                fixture.session.heartbeat(100, target_step=100)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=heartbeat)
        thread.start()
        self.addCleanup(thread.join, 2)
        fixture.gateway.socket.settimeout(1)
        packet, _ = fixture.gateway.socket.recvfrom(1500)
        original = fixture.peer_assembler.push(fixture.source.wire.decode(packet, 'UDP', direction='TO_36'),
            channel='ETH_0', direction='TO_36', authorized=True, now_ns=time.monotonic_ns()).message
        reply = message(131)
        reply['header'].update(session_id=73, sequence=2, transaction_id=original['header']['transaction_id'])
        reply['payload'].update(model_step=100, state='RUNNING')
        fixture.emit(reply)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        snapshot = self.module.ObservedModelClock(fixture.session).snapshot()
        self.assertEqual(snapshot.request, original)
        self.assertEqual(snapshot.status, reply)

    def test_interleaved_older_heartbeat_still_contributes_model_step_floor(self):
        fixture = dispatch_cases.DispatcherTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_peer()
        heartbeat = {'message_id': 2, 'payload': {'last_rx_sequence': 1, 'sender_step': 100}}
        fixture.dispatch.submit(heartbeat, target_step=100)
        fixture.dispatch.submit(heartbeat, target_step=100)
        fixture.dispatch.poll()
        _, requests = fixture.collect()
        reader = self.module.ObservedModelClock(fixture.session)
        for sequence, request, step in ((2, requests[1], 100), (3, requests[0], 200)):
            reply = message(131)
            reply['header'].update(session_id=73, sequence=sequence,
                                   transaction_id=request['header']['transaction_id'])
            reply['payload'].update(model_step=step, state='RUNNING')
            fixture.emit(reply)
            fixture.dispatch.poll()
        fixture.dispatch.submit(heartbeat, target_step=100)
        fixture.dispatch.poll()
        _, requests = fixture.collect()
        reply = message(131)
        reply['header'].update(session_id=73, sequence=4,
                               transaction_id=requests[0]['header']['transaction_id'])
        reply['payload'].update(model_step=150, state='RUNNING')
        fixture.emit(reply)
        fixture.dispatch.poll()
        self.rejects('CLOCK_UNSYNC', reader.snapshot)

    def test_timed_out_heartbeat_transaction_cannot_be_reused_after_dispatch_replacement(self):
        fixture = dispatch_cases.DispatcherTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_peer()
        heartbeat = {'message_id': 2, 'payload': {'last_rx_sequence': 1, 'sender_step': 100}}
        header = fixture.dispatch.submit(heartbeat, target_step=100)
        fixture.dispatch.poll()
        fixture.collect()
        fixture.clock.value += 240_000_000
        fixture.dispatch.poll()
        self.assertEqual(fixture.dispatch.pending_count, 0)
        fixture.dispatch.close()
        self.rejects('STATE', lambda: fixture.session.request(
            heartbeat, target_step=100, transaction_id=header.transaction_id))
        from input_simulator.dispatch import UDPDispatcher
        replacement = UDPDispatcher(fixture.session)
        self.addCleanup(replacement.close)
        self.rejects('STATE', lambda: replacement.submit(
            heartbeat, target_step=100, transaction_id=header.transaction_id))
        self.rejects('TARGET_MISSING', self.module.ObservedModelClock(fixture.session).snapshot)

    def test_failed_serial_heartbeat_attempt_cannot_reuse_transaction(self):
        self.peer.raise_error = ICDError('TIMEOUT', 'protocol test timeout')
        self.rejects('TIMEOUT', lambda: self.session.heartbeat(100, target_step=100))
        transaction = self.peer.requests[-1]['header']['transaction_id']
        self.peer.raise_error = None
        self.rejects('STATE', lambda: self.session.request(
            {'message_id': 2, 'payload': {'last_rx_sequence': 1, 'sender_step': 100}},
            target_step=100, transaction_id=transaction))

    def test_temporarily_deferred_original_heartbeat_claims_transaction_once(self):
        fixture = dispatch_cases.DispatcherTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_peer()
        header = fixture.dispatch.submit(
            {'message_id': 2, 'payload': {'last_rx_sequence': 1, 'sender_step': 100}}, target_step=100)
        with patch.object(fixture.source, 'transmit_fragment', return_value=False):
            self.assertEqual(fixture.dispatch.poll(), 0)
        self.assertEqual(fixture.dispatch.poll(), 1)
        self.assertTrue(fixture.dispatch._pending[header.sequence].sent_once)

    def test_can_heartbeat_attempt_blocks_reuse_by_serial_udp(self):
        fixture = can_cases.CANSignalTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.live()
        sender, plan = fixture.sender(), fixture.plan(2)
        sender.send(plan)
        fixture.consume(plan)
        sender.close()
        self.rejects('STATE', lambda: fixture.session.request(
            {'message_id': 2, 'payload': {'last_rx_sequence': 1, 'sender_step': 100}}, target_step=100,
            transaction_id=plan.source_input.message['header']['transaction_id']))


if __name__ == '__main__':
    unittest.main()
