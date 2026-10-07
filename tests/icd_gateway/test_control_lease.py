"""Standard feedback provenance; protocol doubles do not qualify model control."""

from dataclasses import FrozenInstanceError
import importlib
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from input_simulator.session import SourceSession
from test_source_session import LocalClock, UnitPeer


class ControlLeaseTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.module = importlib.import_module('input_simulator.model_clock')
        self.assertTrue(hasattr(self.module, 'ObservedControlLease'),
                        'actual standard ControlOwner lease observation missing')
        self.clock = LocalClock()
        self.peer = UnitPeer(self.contract, self.clock)
        self.peer.modify = self.reply
        self.session = SourceSession(self.peer, message(1)['payload']['identity'],
            ('STIMULUS', 'CONTROLLER', 'OBSERVER'), clock=self.clock)
        self.session.open()
        self.reader = self.module.ObservedControlLease(self.session)

    def reply(self, response):
        if response['message_id'] == 129:
            response['payload']['capabilities'].update(
                implemented_message_ids=[1, 2, 4, 6, 7, 10, 14, 38],
                available_probes=['consumer.ControlOwner', 'consumer.FlightQuad', 'consumer.ActuatorQuad'])
        return response

    def status(self, source='PX4_SITL', state='PAUSED', safety=False):
        original = self.peer.modify
        def reply(response):
            response['payload'].update(model_step=100, state=state, control_source=source, safety_active=safety)
            return response
        self.peer.modify = reply
        try:
            return self.session.heartbeat(100, target_step=100)
        finally:
            self.peer.modify = original

    def ack(self, mid, *, stage='APPLIED', error='OK', probe=None):
        original = self.peer.modify
        def reply(response):
            response['payload'].update(stage=stage, error=error, applied_step=100,
                probe_id=1000+mid if probe is None else probe)
            return response
        self.peer.modify = reply
        try:
            payload = message(mid)['payload']
            if mid == 6:
                payload.update(source='PX4_SITL', role='CONTROLLER', input_lane='FLIGHT_CONTROL')
            return self.session.request({'message_id':mid, 'payload':payload}, target_step=100)
        finally:
            self.peer.modify = original

    def grant(self):
        self.status(source='NONE')
        self.ack(6)
        self.status()
        return self.reader.snapshot(model_step=100)

    def test_status_alone_cannot_invent_control_lease(self):
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_exact_applied_owner_retains_original_provenance_without_qualification(self):
        self.grant()
        owner_record = next(r for r in self.session.records if r.request['message_id'] == 6)
        value = self.reader.require(model_step=100, source='PX4_SITL', input_lane='FLIGHT_CONTROL')
        self.assertEqual((value.session_id, value.model_id, value.source, value.role, value.input_lane),
                         (73, 'quadrotor_hil', 'PX4_SITL', 'CONTROLLER', 'FLIGHT_CONTROL'))
        self.assertEqual((value.owner_request_json, value.owner_reply_json),
                         (owner_record.request_json, owner_record.reply_json))
        self.assertEqual(value.deadline_ns, owner_record.started_ns+100_000_000)
        with self.assertRaises(FrozenInstanceError):
            value.source = 'DEMO_MISSION'
        self.assertFalse(value.execution_ready)
        self.assertFalse(value.safety_verified)
        self.assertEqual(value.qualification_status, 'NOT_EVALUATED')

    def test_control_deadline_exact_boundary_and_heartbeat_do_not_renew(self):
        value = self.grant()
        self.clock.value = value.deadline_ns-1
        self.status()
        self.reader.snapshot(model_step=100)
        self.clock.value += 1
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_validated_matching_control_renews_from_first_tx_not_reply(self):
        self.grant()
        self.clock.value += 50_000_000
        started = self.clock.value
        self.peer.delay_ns = 10_000_000
        self.ack(7, stage='VALIDATED', probe=0)
        value = self.reader.snapshot(model_step=100)
        self.assertEqual(value.deadline_ns, started+100_000_000)
        self.assertEqual(value.lease_request_json, self.session.records[-1].request_json)
        self.assertEqual(value.lease_reply_json, self.session.records[-1].reply_json)

    def test_received_failed_environment_and_wrong_lane_never_renew(self):
        initial = self.grant()
        self.clock.value += 40_000_000
        for mid, stage, error in ((7,'RECEIVED','OK'), (7,'FAILED','RANGE'),
                                  (10,'APPLIED','OK'), (14,'APPLIED','OK')):
            self.ack(mid, stage=stage, error=error)
        self.assertEqual(self.reader.snapshot(model_step=100).deadline_ns, initial.deadline_ns)

    def test_expired_lease_cannot_be_recreated_by_late_command_ack(self):
        initial = self.grant()
        self.clock.value = initial.deadline_ns
        self.ack(7)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_unpublished_or_received_owner_never_establishes_lease(self):
        self.status(source='NONE')
        self.ack(6, stage='RECEIVED', probe=0)
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))
        self.status(source='NONE')
        self.ack(6, probe=0)
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_unpublished_owner_probe_never_establishes_lease(self):
        from icd_runtime.json_codec import canonicalize
        capabilities = self.session.capabilities
        capabilities['available_probes'].remove('consumer.ControlOwner')
        self.session._capabilities_json = canonicalize(capabilities)
        self.status(source='NONE')
        self.ack(6)
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_new_owner_attempt_invalidates_old_even_when_send_fails(self):
        self.grant()
        self.peer.raise_error = ICDError('TIMEOUT', 'original request failed')
        self.rejects('TIMEOUT', lambda: self.ack(6))
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_old_owner_reply_after_new_attempt_cannot_restore_old_lease(self):
        self.grant()
        previous = next(r for r in self.session.records if r.request['message_id']==6)
        self.peer.raise_error = ICDError('TIMEOUT', 'new owner failed')
        self.rejects('TIMEOUT', lambda: self.ack(6))
        old = previous.reply
        old['header']['sequence'] += 100
        with self.session._operation():
            self.session._remember_model_feedback(previous.request, old, previous.started_ns,
                self.clock.value, transport='UDP', channel='ETH_0', fresh=True)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_old_owner_reply_after_status_revocation_cannot_restore_old_lease(self):
        self.grant()
        previous = next(r for r in self.session.records if r.request['message_id']==6)
        self.status(source='NONE')
        old = previous.reply
        old['header']['sequence'] += 100
        with self.session._operation():
            self.session._remember_model_feedback(previous.request, old, previous.started_ns,
                self.clock.value, transport='UDP', channel='ETH_0', fresh=True)
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_control_permission_failure_revokes_existing_lease(self):
        self.grant()
        self.ack(7, stage='FAILED', error='CONTROL_OWNER')
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_applied_owner_cannot_establish_from_an_active_safety_status(self):
        self.status(source='NONE', safety=True)
        self.ack(6)
        self.status(safety=False)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_safety_status_and_changed_source_revoke_without_regain(self):
        self.grant()
        self.status(safety=True)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))
        self.status(source='NONE')
        self.ack(6)
        self.status(source='PHYSICAL_UUT')
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_safety_lifecycle_attempt_revokes_before_reply(self):
        self.grant()
        payload = message(4)['payload']
        payload.update(action='STOP', expected_state='PAUSED')
        self.peer.raise_error = ICDError('TIMEOUT', 'actual stop attempt timed out')
        self.rejects('TIMEOUT', lambda: self.session.request({'message_id':4,'payload':payload}, target_step=100))
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_status_step_freshness_and_strict_expected_source_lane_are_required(self):
        self.grant()
        self.rejects('CLOCK_UNSYNC', lambda: self.reader.snapshot(model_step=101))
        self.rejects('SCHEMA', lambda: self.reader.snapshot(model_step=True))
        self.rejects('SCHEMA', lambda: self.reader.require(model_step=100, source=True, input_lane='FLIGHT_CONTROL'))
        self.rejects('CONTROL_OWNER', lambda: self.reader.require(
            model_step=100, source='PHYSICAL_UUT', input_lane='FLIGHT_CONTROL'))
        self.rejects('CONTROL_OWNER', lambda: self.reader.require(
            model_step=100, source='PX4_SITL', input_lane='ACTUATOR'))

    def test_abandon_and_new_sid_never_adopt_previous_lease(self):
        self.grant()
        self.session.abandon()
        self.peer.sid += 1
        self.session.open()
        self.status()
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_drain_and_reader_replacement_never_reset_deadline(self):
        value = self.grant()
        self.session.drain_records()
        self.clock.value = value.deadline_ns
        self.rejects('CONTROL_OWNER', lambda: self.module.ObservedControlLease(self.session).snapshot(model_step=100))

    def test_duplicate_command_feedback_cannot_renew_again(self):
        self.grant()
        self.clock.value += 20_000_000
        self.ack(7)
        value = self.reader.snapshot(model_step=100)
        self.clock.value += 20_000_000
        self.peer.sequence -= 1
        self.ack(7)
        self.assertEqual(self.reader.snapshot(model_step=100).deadline_ns, value.deadline_ns)

    def test_control_reader_does_not_transmit_allocate_or_drain(self):
        self.grant()
        before = (len(self.peer.requests), self.session._next_sequence, self.session.records)
        self.reader.snapshot(model_step=100)
        self.assertEqual((len(self.peer.requests), self.session._next_sequence, self.session.records), before)

    def test_control_capture_requires_actual_source_operation_owner(self):
        self.grant()
        record = next(r for r in self.session.records if r.request['message_id']==6)
        self.rejects('STATE', lambda: self.session._remember_model_feedback(record.request, record.reply,
            record.started_ns, record.completed_ns, transport='UDP', channel='ETH_0', fresh=True))


class ControlLeaseSocketTests(GatewayTest):
    """Actual UDP/VirtualBus protocol peers, not physical or model qualification."""
    def setUp(self):
        super().setUp()
        import test_can_signal as can_cases
        from input_simulator.dispatch import UDPDispatcher
        from input_simulator.model_clock import ObservedControlLease
        from input_simulator.native_tools import NativeToolCoordinator
        self.f = can_cases.CANSignalTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        def published_message(mid):
            value = message(mid)
            if mid == 129:
                value['payload']['capabilities']['available_probes'] = [
                    'consumer.ControlOwner', 'consumer.FlightQuad']
            return value
        with patch.object(can_cases, 'message', side_effect=published_message):
            self.f.live(implemented=[1,2,6,7])
        self.sender = self.f.sender()
        self.dispatch = UDPDispatcher(self.f.session)
        self.addCleanup(self.dispatch.close)
        self.owner = NativeToolCoordinator(self.dispatch, (self.sender,))
        self.addCleanup(self.owner.close)
        self.reader = ObservedControlLease(self.f.session)
        self.sequence = 1

    def collect(self):
        from icd_runtime.reassembly import Reassembler
        assembly = Reassembler(self.contract)
        result = None
        while result is None:
            packet, _ = self.f.receiver.recvfrom(1500)
            result = assembly.push(self.f.transport.wire.decode(packet,'UDP',direction='TO_36'),
                channel='ETH_0', direction='TO_36', authorized=True, now_ns=0)
        return result.message

    def emit(self, request, *, stage='APPLIED', probe=None, source='PX4_SITL', safety=False):
        self.sequence += 1
        mid = request['message_id']
        reply = message(131 if mid == 2 else 130)
        reply['header'].update(session_id=request['header']['session_id'], sequence=self.sequence,
                               transaction_id=request['header']['transaction_id'])
        if mid == 2:
            reply['payload'].update(state='PAUSED', model_step=100, control_source=source, safety_active=safety)
        else:
            reply['payload'].update(request_sequence=request['header']['sequence'], request_message_id=mid,
                stage=stage, error='OK', applied_step=100, probe_id=1000+mid if probe is None else probe)
        for packet in self.f.transport.wire.encode(reply,'UDP'):
            self.f.receiver.sendto(packet,self.f.transport.feedback_endpoint)
        return reply

    def submit(self, mid):
        payload = message(mid)['payload']
        if mid == 6:
            payload.update(source='PX4_SITL', role='CONTROLLER', input_lane='FLIGHT_CONTROL')
        elif mid == 2:
            payload['sender_step'] = 100
        header = self.owner.submit({'message_id':mid,'payload':payload}, target_step=100)
        self.owner.poll()
        return header, self.collect()

    def exchange(self, mid, **kwargs):
        header, request = self.submit(mid)
        self.emit(request, **kwargs)
        self.owner.poll()
        return header

    def grant(self):
        self.exchange(2, source='NONE')
        self.exchange(6)
        self.exchange(2)
        return self.reader.snapshot(model_step=100)

    def test_actual_udp_validated_command_extends_same_original_lease(self):
        value = self.grant()
        self.f.clock.value += 50_000_000
        header = self.exchange(7, stage='VALIDATED', probe=0)
        actual = self.reader.snapshot(model_step=100)
        self.assertEqual(actual.deadline_ns, value.deadline_ns+50_000_000)
        self.assertEqual(actual.transport, 'UDP')
        from icd_runtime.json_codec import loads
        self.assertEqual(loads(actual.lease_request_json)['header']['sequence'], header.sequence)

    def test_actual_can_command_and_udp_share_one_lease_observation(self):
        value = self.grant()
        self.f.clock.value += 50_000_000
        plan = self.owner.prepare_can(self.sender, {'message_id':7,'payload':message(7)['payload']},
                                      target_step=100)
        self.owner.send_can(self.sender, plan)
        self.f.consume(plan)
        reply = message(130)
        header = plan.source_input.message['header']
        self.sequence += 1
        reply['header'].update(session_id=header['session_id'], sequence=self.sequence,
                               transaction_id=header['transaction_id'])
        reply['payload'].update(request_sequence=header['sequence'], request_message_id=7,
                               stage='APPLIED', error='OK', applied_step=100, probe_id=1007)
        import can
        for frame in self.f.transport.wire.encode(reply,'CANFD'):
            self.f.peer.send(can.Message(arbitration_id=frame.arbitration_id, data=frame.data,
                is_extended_id=False, is_fd=True, bitrate_switch=True, check=True))
        self.owner.receive_can(self.sender, plan, timeout=0.2)
        actual = self.reader.snapshot(model_step=100)
        self.assertEqual((actual.deadline_ns,actual.transport,actual.channel),
                         (value.deadline_ns+50_000_000,'CANFD','CANFD_0'))
        self.assertEqual(actual.owner_request_json, value.owner_request_json)
        self.owner.retire_can(self.sender, plan)
        self.owner.discard_can(self.sender, plan)

    def test_actual_interleaved_owner_replies_keep_latest_attempt_only(self):
        self.exchange(2, source='NONE')
        old_header, old = self.submit(6)
        new_header, new = self.submit(6)
        self.emit(new)
        self.emit(old)
        self.owner.poll()
        self.exchange(2)
        value = self.reader.snapshot(model_step=100)
        from icd_runtime.json_codec import loads
        self.assertEqual(loads(value.owner_request_json)['header']['sequence'], new_header.sequence)
        self.assertGreater(new_header.sequence, old_header.sequence)

    def test_pending_owner_ack_cannot_undo_later_safety_status(self):
        self.exchange(2, source='NONE')
        _, pending_owner = self.submit(6)
        self.exchange(2, safety=True)
        self.emit(pending_owner)
        self.owner.poll()
        self.exchange(2, safety=False)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_earlier_heartbeat_conflict_permanently_revokes_applied_owner(self):
        self.exchange(2, source='NONE')
        _, heartbeat = self.submit(2)
        _, owner = self.submit(6)
        self.emit(owner)
        self.owner.poll()
        self.emit(heartbeat, source='PHYSICAL_UUT')
        self.owner.poll()
        self.exchange(2)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))

    def test_pending_owner_source_conflict_requires_a_new_owner_exchange(self):
        self.exchange(2, source='NONE')
        _, pending = self.submit(6)
        self.exchange(2, source='PHYSICAL_UUT')
        self.emit(pending)
        self.owner.poll()
        self.exchange(2)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))
        self.exchange(6)
        self.exchange(2)
        self.reader.snapshot(model_step=100)

    def test_fresh_conflicting_status_revokes_even_if_clock_cache_keeps_newer_request(self):
        self.grant()
        _, old = self.submit(2)
        self.exchange(2)
        self.emit(old, safety=True)
        self.owner.poll()
        self.exchange(2)
        self.rejects('CONTROL_OWNER', lambda: self.reader.snapshot(model_step=100))
