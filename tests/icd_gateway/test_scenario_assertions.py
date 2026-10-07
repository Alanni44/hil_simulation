"""Actual standard UDP observations, not qualified model or hardware readers."""

import importlib.util
from dataclasses import replace
from unittest.mock import patch

from common import GatewayTest, message
from input_simulator.scenario import ScenarioPlan
from test_assertion import definition
from test_scenario import scenario, send
import test_evidence as evidence_cases


class ScenarioAssertionTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.scenario_assertions'),
                             'actual original assertion reader/handler missing')
        from input_simulator.scenario_assertions import StatusObservationReader, StatusScenarioAssertions
        self.Reader, self.Runner = StatusObservationReader, StatusScenarioAssertions
        self.f = evidence_cases.EvidenceTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.setup_inbox(probes=('consumer.Status',))
        self.reader = self.Reader(self.f.session)
        self.addCleanup(self.reader.close)
        self.status()

    def status(self, step=100, **payload):
        header = self.f.dispatch.submit({'message_id':2, 'payload':{'sender_step':step,
            'last_rx_sequence':self.f.session.last_rx_sequence}}, target_step=step)
        self.f.dispatch.poll()
        request = self.f.collect()[1][0]
        self.f.reply_sequence += 1
        response = message(131)
        response['header'].update(session_id=header.session_id, sequence=self.f.reply_sequence,
                                  transaction_id=header.transaction_id)
        response['payload'].update(model_step=step, state='PAUSED', **payload)
        self.f.emit(response)
        self.f.dispatch.poll()
        return request, response

    def build(self, *, events=None, roots=None, **changes):
        assertion = definition(**{'message_id':131, 'probe_id':'consumer.Status', 'stage':'E1',
            'field_path':'receive_queue_depth', 'expected':1, **changes})
        document = scenario(events or [send()])
        document['assertions'] = [assertion] if roots is None else roots or [
            definition(assertion_id='root-extra', message_id=131, probe_id='consumer.Status',
                       stage='E1', field_path='model_step', expected=100)]
        self.plan = ScenarioPlan.compile(self.contract, document, model_id='quadrotor_hil')
        self.runner = self.Runner(self.contract, self.plan, self.reader)
        self.runner.preflight(self.plan)
        return self.runner

    def begin(self):
        return self.runner.begin_assertions(self.plan.assertions, model_step=100)

    def test_all_eight_operators_use_actual_status_values(self):
        for op, value in (('EQ',1),('NE',2),('LT',0),('LE',1),('GT',2),('GE',1),
                          ('WITHIN',1),('EVENTUALLY',1)):
            self.build(operator=op)
            handle = self.begin()
            self.status(receive_queue_depth=value)
            result = self.runner.poll(handle, model_step=100)
            self.assertIs(result.handle, handle)
            self.assertEqual(result.state, 'COMPLETE', op)
            self.assertFalse(self.runner.execution_ready)
            self.assertEqual(self.runner.qualification_status, 'NOT_EVALUATED')

    def test_old_status_and_repeated_poll_do_not_count(self):
        self.build(sample_count=2)
        handle = self.begin()
        self.assertEqual(self.runner.poll(handle, model_step=100).state, 'PENDING')
        self.status(receive_queue_depth=1)
        self.assertEqual(self.runner.poll(handle, model_step=100).state, 'PENDING')
        self.assertEqual(self.runner.poll(handle, model_step=100).state, 'PENDING')
        self.status(receive_queue_depth=1)
        self.assertEqual(self.runner.poll(handle, model_step=100).state, 'COMPLETE')

    def test_unpolled_intermediate_mismatch_breaks_consecutive_wait_samples(self):
        assertion = definition(assertion_id='wait', message_id=131, probe_id='consumer.Status',
            stage='E1', field_path='receive_queue_depth', expected=1, sample_count=2)
        event = {'event_id':'wait-event','type':'WAIT','at_step':100,'priority':100,
                 'link_id':'ETHGEN','assertion':assertion}
        self.build(events=[event], roots=[])
        action = next(self.plan.iter_actions())
        handle = self.runner.begin(action, model_step=100)
        for value in (1,0,1):
            self.status(receive_queue_depth=value)
        self.assertEqual(self.runner.poll(handle, model_step=100).state, 'PENDING')
        self.status(receive_queue_depth=1)
        self.assertEqual(self.runner.poll(handle, model_step=100).state, 'COMPLETE')

    def test_ordinary_assert_mismatch_fails_with_original_handle(self):
        self.build()
        handle = self.begin()
        self.status(receive_queue_depth=0)
        result = self.runner.poll(handle, model_step=100)
        self.assertEqual((result.state,result.error), ('FAILED','BUSINESS_FAILED'))
        self.assertIs(result.handle, handle)

    def test_half_open_deadline_does_not_catch_up_old_samples(self):
        self.build(timeout_steps=2)
        handle = self.begin()
        self.status(step=101, receive_queue_depth=1)
        self.status(step=102, receive_queue_depth=1)
        result = self.runner.poll(handle, model_step=102)
        self.assertEqual((result.state,result.error), ('FAILED','TIMEOUT'))

    def test_exact_raw_sample_provenance_is_detached_and_immutable(self):
        request, reply = self.status(receive_queue_depth=1)
        sample = self.reader.records[-1]
        self.assertEqual(sample.request, request)
        self.assertEqual(sample.status, reply)
        self.assertEqual((sample.session_id,sample.model_id,sample.model_step,sample.transport,sample.channel),
                         (73,'quadrotor_hil',100,'UDP','ETH_0'))
        sample.status.clear()
        self.assertEqual(self.reader.records[-1].status, reply)

    def test_forged_handle_and_action_and_duplicate_begin_are_rejected(self):
        self.build()
        handle = self.begin()
        self.rejects('STATE', lambda:self.runner.poll(replace(handle), model_step=100))
        self.rejects('DUPLICATE', self.begin)

    def test_missing_model_reader_and_evidence_stage_fail_before_allocation(self):
        before = self.f.session._next_sequence
        for stage in ('E2','E3'):
            self.rejects('TARGET_MISSING', lambda:self.build(stage=stage))
        self.rejects('TARGET_MISSING', lambda:self.build(roots=[definition()]))
        self.assertEqual(self.f.session._next_sequence, before)

    def test_field_and_expected_type_are_checked_at_preflight(self):
        for path in ('payload.safety_active','unknown','flight_control.motor_command[0]'):
            self.rejects('SCHEMA', lambda:self.build(field_path=path))
        self.rejects('SCHEMA', lambda:self.build(field_path='safety_active', expected=1))

    def test_reader_does_not_send_allocate_drain_or_renew(self):
        self.build()
        handle = self.begin()
        before = (self.f.session._next_sequence,self.f.session._deadline_ns,
                  self.f.dispatch.records,self.f.session.records)
        self.runner.poll(handle, model_step=100)
        self.assertEqual(before,(self.f.session._next_sequence,self.f.session._deadline_ns,
                                self.f.dispatch.records,self.f.session.records))

    def test_unread_samples_from_successive_steps_are_compared_in_order(self):
        self.build(sample_count=2)
        handle = self.begin()
        self.status(receive_queue_depth=1)
        self.status(step=101, receive_queue_depth=1)
        self.assertEqual(self.runner.poll(handle, model_step=101).state, 'COMPLETE')

    def test_forged_compiled_plan_cannot_change_original_assertions(self):
        self.build()
        from input_simulator.assertion import AssertionSpec
        changed = AssertionSpec.compile(self.contract,
            {**self.plan.assertions[0].assertion, 'expected':2}, model_id=self.plan.model_id)
        forged = replace(self.plan, assertions=(changed,))
        self.rejects('RESOURCE', lambda:self.Runner(self.contract, forged, self.reader))

    def test_invalid_handle_fields_fail_as_state_not_python_exception(self):
        self.build()
        self.begin()
        from input_simulator.scenario_assertions import AssertionHandle
        for value in (None,object(),AssertionHandle([]),AssertionHandle(True)):
            self.rejects('STATE', lambda:self.runner.poll(value, model_step=100))

    def test_bool_and_string_fields_use_exact_received_types(self):
        for field, expected in (('safety_active',True),('control_source','PHYSICAL_UUT')):
            self.build(field_path=field,expected=expected,operator='EQ',tolerance=0)
            handle = self.begin()
            self.status(**{field:expected})
            self.assertEqual(self.runner.poll(handle, model_step=100).state, 'COMPLETE')

    def test_reader_overflow_retains_prefix_and_does_not_hide_transport_rx(self):
        self.reader.close()
        self.reader = self.Reader(self.f.session,max_records=1)
        self.addCleanup(self.reader.close)
        self.build()
        handle = self.begin()
        self.status(receive_queue_depth=1)
        first = self.reader.records
        _, overflow = self.status(receive_queue_depth=1)
        self.assertEqual(self.reader.records, first)
        self.assertEqual(self.reader.failure[0], 'BUFFER_FULL')
        self.assertTrue(any(r.reply == overflow for r in self.f.dispatch.records if r.kind=='RX'))
        result = self.runner.poll(handle, model_step=100)
        self.assertEqual((result.state,result.error),('FAILED','BUFFER_FULL'))

    def test_reader_is_single_owner_and_close_retains_history(self):
        first = self.reader.records
        self.rejects('STATE',lambda:self.Reader(self.f.session))
        self.reader.close()
        self.reader.close()
        self.assertEqual(self.reader.records,first)
        self.assertIsNone(self.f.session._status_assertion_reader)

    def test_source_and_reader_replacement_and_close_do_not_adopt_samples(self):
        self.build()
        handle = self.begin()
        self.reader.close()
        fresh = self.Reader(self.f.session)
        self.addCleanup(fresh.close)
        self.status(receive_queue_depth=1)
        result = self.runner.poll(handle, model_step=100)
        self.assertEqual((result.state,result.error),('FAILED','STALE_SESSION'))

    def test_pending_handler_fails_on_wrong_actual_model_step(self):
        self.build()
        handle = self.begin()
        result = self.runner.poll(handle, model_step=101)
        self.assertEqual((result.state,result.error),('FAILED','CLOCK_UNSYNC'))

    def test_expired_unread_sample_cannot_count_toward_success(self):
        self.build()
        handle = self.begin()
        self.status(receive_queue_depth=1)
        self.f.clock.value = self.reader.records[-1].deadline_ns
        self.status(receive_queue_depth=1)
        result = self.runner.poll(handle, model_step=100)
        self.assertEqual((result.state,result.error),('FAILED','EXPIRED'))

    def test_event_assert_and_foreign_action_keep_original_routing(self):
        assertion = definition(assertion_id='event-assert',message_id=131,probe_id='consumer.Status',
            stage='E1',field_path='safety_active',expected=False,tolerance=0,operator='EQ')
        event = {'event_id':'assert-event','type':'ASSERT','at_step':100,'priority':100,
                 'link_id':'CUTIL','assertion':assertion}
        self.build(events=[event],roots=[])
        action = next(self.plan.iter_actions())
        self.rejects('STATE', lambda:self.runner.begin(replace(action,step=101),model_step=100))
        handle = self.runner.begin(action,model_step=100)
        self.status(safety_active=False)
        self.assertEqual(self.runner.poll(handle,model_step=100).state,'COMPLETE')

    def test_actual_can_status_uses_the_same_original_reader_and_handler(self):
        import test_can_signal as can_cases
        f = can_cases.CANSignalTests('runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        def published(mid):
            value = message(mid)
            if mid == 129:
                value['payload']['capabilities']['available_probes'] = ['consumer.Status']
            elif mid == 131:
                value['payload'].update(model_step=100,state='PAUSED',received_count=1)
            return value
        with patch.object(can_cases,'message',side_effect=published):
            f.live(implemented=[1,2])
        sender = f.sender()
        reader = self.Reader(f.session)
        self.addCleanup(reader.close)
        def exchange(sequence):
            plan = f.plan(2)
            sender.send(plan)
            f.consume(plan)
            with patch.object(can_cases,'message',side_effect=published):
                f.emit(plan,sequence=sequence,mid=131)
            sender.receive_for(plan,timeout=0.2)
            sender.retire(plan)
            f.builder.discard(plan)
        exchange(2)
        doc = scenario([send()])
        doc['assertions'] = [definition(message_id=131,probe_id='consumer.Status',stage='E1',
                                       field_path='received_count',expected=1)]
        plan = ScenarioPlan.compile(self.contract,doc,model_id='quadrotor_hil')
        runner = self.Runner(self.contract,plan,reader)
        runner.preflight(plan)
        handle = runner.begin_assertions(plan.assertions,model_step=100)
        exchange(3)
        self.assertEqual(runner.poll(handle,model_step=100).state,'COMPLETE')
        self.assertEqual((runner.records[-1].sample.transport,runner.records[-1].sample.channel),
                         ('CANFD','CANFD_0'))

    def test_handler_capacity_limits_fail_before_new_handle(self):
        self.build(sample_count=2)
        runner = self.Runner(self.contract,self.plan,self.reader,max_records=2)
        self.rejects('CAPACITY', lambda:runner.preflight(self.plan))
        before = self.f.session._next_sequence
        runner = self.Runner(self.contract,self.plan,self.reader,max_bytes=1)
        runner.preflight(self.plan)
        self.rejects('BUFFER_FULL',lambda:runner.begin_assertions(self.plan.assertions,model_step=100))
        self.assertEqual(self.f.session._next_sequence,before)

    def test_capture_cannot_bypass_actual_source_operation_owner(self):
        row = self.reader.records[-1]
        self.rejects('STATE',lambda:self.reader._capture(row.request,row.status,row.started_ns,
            row.completed_ns,transport=row.transport,channel=row.channel,fresh=True))

    def test_full_sample_history_rejects_new_handle_without_mutation(self):
        assertion = definition(assertion_id='wait',message_id=131,probe_id='consumer.Status',
            stage='E1',field_path='receive_queue_depth',expected=1,sample_count=1)
        event = {'event_id':'wait-event','type':'WAIT','at_step':100,'priority':100,
                 'link_id':'ETHGEN','assertion':assertion}
        self.build(events=[event],roots=[])
        runner = self.Runner(self.contract,self.plan,self.reader,max_records=4)
        runner.preflight(self.plan)
        handle = runner.begin(next(self.plan.iter_actions()),model_step=100)
        for _ in range(3):
            self.status(receive_queue_depth=0)
            self.assertEqual(runner.poll(handle,model_step=100).state,'PENDING')
        roots = tuple(s for s in self.plan.assertions if s.assertion['assertion_id']=='root-extra')
        before = (runner.records,tuple(runner._entries),frozenset(runner._begun),
                  runner._bytes,self.f.session._next_sequence)
        self.rejects('BUFFER_FULL',lambda:runner.begin_assertions(roots,model_step=100))
        self.assertEqual(before,(runner.records,tuple(runner._entries),frozenset(runner._begun),
                                runner._bytes,self.f.session._next_sequence))

    def test_unpublished_status_probe_is_rejected_from_actual_grant(self):
        other = evidence_cases.EvidenceTests('runTest')
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.setup_inbox(probes=())
        reader = self.Reader(other.session)
        self.addCleanup(reader.close)
        self.f,self.reader = other,reader
        self.status()
        before = self.f.session._next_sequence
        self.rejects('TARGET_MISSING',self.build)
        self.assertEqual(self.f.session._next_sequence,before)

    def services(self, assertions):
        from input_simulator.scenario_driver import ScenarioRuntimeServices
        from icd_runtime.errors import ICDError
        class IncompleteServices(ScenarioRuntimeServices):
            """Only inherited assertion methods are real; other tasks are unavailable."""
            def preflight(self, plan):
                self.preflight_assertions(plan)
                raise ICDError('TARGET_MISSING','remaining production services are not installed')
            def native_target(self, action, *, model_step):
                raise ICDError('TARGET_MISSING','actual producer reader missing')
            def begin_cleanup(self, cleanup, *, model_step):
                raise ICDError('TARGET_MISSING','actual nine-part cleanup missing')
            def poll_cleanup(self, handle, *, model_step):
                raise ICDError('TARGET_MISSING','actual nine-part cleanup missing')
        return IncompleteServices(self.f.session,assertions=assertions)

    def test_original_runtime_boundary_delegates_to_real_assertion_handler(self):
        self.build()
        services = self.services(self.runner)
        services.preflight_assertions(self.plan)
        handle = services.begin_assertions(self.plan.assertions,model_step=100)
        self.status(receive_queue_depth=1)
        self.assertEqual(services.poll(handle,model_step=100).state,'COMPLETE')
        self.rejects('TARGET_MISSING',lambda:services.begin(next(self.plan.iter_actions()),model_step=100))

    def test_original_services_cannot_default_to_fake_success_without_reader(self):
        self.build()
        services = self.services(None)
        self.rejects('TARGET_MISSING',lambda:services.begin_assertions(self.plan.assertions,model_step=100))

    def test_all_twelve_frozen_status_fields_are_read_without_invented_values(self):
        payload = message(131)['payload']
        payload.update(model_step=100,state='PAUSED')
        self.assertEqual(len(payload),12)
        for field, expected in payload.items():
            self.build(field_path=field,expected=expected,operator='EQ',tolerance=0)
            handle = self.begin()
            self.status()
            self.assertEqual(self.runner.poll(handle,model_step=100).state,'COMPLETE',field)
