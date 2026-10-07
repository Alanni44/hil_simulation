"""Real native/standard peers; model services here are explicitly test doubles."""

import importlib
from dataclasses import replace
from unittest.mock import patch

from common import GatewayTest, message
from icd_runtime.errors import ICDError
from input_simulator.scenario import ScenarioPlan
from input_simulator.scenario_execution import ActionProgress, CleanupProgress, CLEANUP_FIELDS, ScenarioExecution
from input_simulator.native_scenario_actions import NativeScenarioActions
from test_scenario import scenario, send
import test_native_scenario_actions as native_cases


class ScenarioDriverTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.scenario_driver'),
                             'original native scenario driver integration missing')
        self.module = importlib.import_module('input_simulator.scenario_driver')
        self.f = native_cases.NativeScenarioActionTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        module = self.module
        class TestServices(module.ScenarioRuntimeServices):
            """Trusted controller test double, never production model/probe qualification."""
            def __init__(self, session):
                super().__init__(session)
                self.calls, self.progress = [], {}
                self.target = 100
                self.cleanup_fields = CLEANUP_FIELDS
                self.preflight_failure = None
            def preflight(self, plan):
                self.calls.append(('preflight', plan))
                if self.preflight_failure:
                    raise self.preflight_failure
            def native_target(self, action, *, model_step):
                self.calls.append(('target', action, model_step))
                return self.target
            def _new(self, call):
                self.calls.append(call)
                handle = object()
                self.progress[handle] = ActionProgress(handle, 'PENDING')
                return handle
            def begin_assertions(self, assertions, *, model_step):
                return self._new(('assertions', assertions, model_step))
            def begin(self, action, *, model_step):
                return self._new(('begin', action, model_step))
            def poll(self, handle, *, model_step):
                return self.progress[handle]
            def begin_cleanup(self, cleanup, *, model_step):
                self.calls.append(('cleanup', cleanup, model_step))
                self.cleanup_handle = object()
                return self.cleanup_handle
            def poll_cleanup(self, handle, *, model_step):
                return CleanupProgress(handle, 'COMPLETE', self.cleanup_fields)
            def complete(self):
                for handle in self.progress:
                    self.progress[handle] = ActionProgress(handle, 'COMPLETE')
        self.services = TestServices(self.f.f.session)

    def status(self, step=0, state='RUNNING'):
        owner = self.f.owner
        payload = message(2)['payload']
        payload['sender_step'] = step
        header = owner.submit({'message_id': 2, 'payload': payload}, target_step=step)
        owner.poll()
        request = self.f.eth_request()
        reply = message(131)
        self.f.rx_sequence += 1
        reply['header'].update(session_id=header.session_id, sequence=self.f.rx_sequence,
                               transaction_id=header.transaction_id)
        reply['payload'].update(model_step=step, state=state)
        for raw in self.f.f.src.wire.encode(reply, 'UDP'):
            self.f.f.receiver.sendto(raw, self.f.f.src.feedback_endpoint)
        owner.poll()
        return request

    def build(self, events=None, *, history_id=None, **limits):
        self.plan = ScenarioPlan.compile(self.contract, scenario(events or [send(step=0, link_id='CANT')]),
            model_id='quadrotor_hil', history_id=history_id)
        self.native = NativeScenarioActions(self.contract, self.plan, self.f.owner,
            can_sender=self.f.sender, assigned_links=('CANT','ETHGEN'))
        self.driver = self.module.OriginalScenarioDriver(self.contract, self.plan,
            self.native, self.services, **limits)
        return self.driver

    def test_actual_original_native_tx_and_feedback_inside_controller(self):
        self.status()
        driver = self.build([send('can', 0, 7, link_id='CANT'), send('eth', 0, 10)])
        run = ScenarioExecution(self.contract, self.plan, driver)
        run.start(model_step=0)
        can_request, eth_request = self.f.can_request(), self.f.eth_request()
        self.assertEqual(can_request['payload'], message(7)['payload'])
        self.assertEqual(eth_request['payload'], message(10)['payload'])
        self.f.reply(can_request, 'CANFD', stage='APPLIED', error='OK')
        self.f.reply(eth_request, 'UDP', stage='APPLIED', error='OK')
        self.services.complete()
        run.advance(model_step=0)
        run.advance(model_step=0)
        self.assertEqual(run.state, 'LOCAL_STOPPED')
        self.assertEqual(self.f.f.session.prepared_inputs, ())
        self.assertEqual(self.services.calls[1][1], self.plan.assertions)
        self.assertFalse(driver.execution_ready)
        self.assertFalse(driver.safety_verified)

    def test_missing_services_or_status_never_allocates_or_transmits(self):
        driver = self.build()
        before = self.f.f.session._next_sequence
        self.rejects('TARGET_MISSING', lambda: driver.preflight(self.plan))
        self.rejects('TARGET_MISSING', lambda: self.module.OriginalScenarioDriver(
            self.contract, self.plan, self.native, None))
        self.assertEqual(self.f.f.session._next_sequence, before)
        self.assertEqual(self.native.records, ())

    def test_whole_plan_service_preflight_failure_precedes_native_send(self):
        self.status()
        driver = self.build()
        self.services.preflight_failure = ICDError('TARGET_MISSING', 'actual root probe unavailable')
        before = self.f.f.session._next_sequence
        self.rejects('TARGET_MISSING', lambda: driver.preflight(self.plan))
        self.assertEqual(self.native.records, ())
        self.assertEqual(self.f.f.session._next_sequence, before)

    def test_partition_preserves_original_nonnative_link_and_plan(self):
        self.status()
        event = send('external', 0, 10, link_id='CUTIL')
        driver = self.build([event])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        handle = driver.begin(action, model_step=0)
        self.assertEqual(self.services.calls[-1], ('begin', action, 0))
        self.assertIs(self.services.calls[0][1], self.plan)
        self.assertEqual(self.native.records, ())
        self.assertEqual(driver.poll(handle, model_step=0).state, 'PENDING')

    def test_wrong_kind_on_native_link_remains_service_event(self):
        self.status()
        event = {**send('negative', 0, 7, link_id='CANT'), 'type':'NEGATIVE_SEND',
            'mutation':{'kind':'CRC_XOR','xor_mask':1}, 'expected_error':'CRC',
            'must_not_apply':True, 'authorization_case_id':'T02'}
        driver = self.build([event])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        driver.begin(action, model_step=0)
        self.assertEqual(self.services.calls[-1], ('begin', action, 0))
        self.assertEqual(self.native.records, ())

    def test_strict_observed_step_target_and_action_before_native_allocation(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        before = self.f.f.session._next_sequence
        self.rejects('CLOCK_UNSYNC', lambda: driver.begin(action, model_step=1))
        self.rejects('STATE', lambda: driver.begin(replace(action, index=False), model_step=0))
        for target, code in ((False,'SCHEMA'), (0,'LATE'), (1001,'RANGE')):
            self.services.target = target
            self.rejects(code, lambda: driver.begin(action, model_step=0))
        self.assertEqual(self.f.f.session._next_sequence, before)
        self.assertEqual(self.native.records, ())

    def test_frozen_model_native_target_must_equal_actual_current_step(self):
        self.status(state='PAUSED')
        driver = self.build([send('env', 0, 10)])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        self.rejects('STATE', lambda: driver.begin(action, model_step=0))
        self.services.target = 0
        driver.begin(action, model_step=0)
        self.assertEqual(self.f.eth_request()['header']['target_step'], 0)

    def test_wrapped_original_handles_reject_forged_or_foreign_progress(self):
        self.status()
        driver = self.build([send('service', 0, 10, link_id='CUTIL')])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        handle = driver.begin(action, model_step=0)
        self.rejects('STATE', lambda: driver.poll(replace(handle), model_step=0))
        self.rejects('STATE', lambda: driver.begin(action, model_step=0))
        delegate = next(iter(self.services.progress))
        self.services.progress[delegate] = ActionProgress(object(), 'COMPLETE')
        self.rejects('STATE', lambda: driver.poll(handle, model_step=0))

    def test_cleanup_starts_remote_even_when_local_stop_needs_retry(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        driver.begin(next(self.plan.iter_actions()), model_step=0)
        self.f.can_request()
        with patch.object(self.f.owner, 'retire_can', side_effect=ICDError('RESOURCE', 'local close injection')):
            handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
            self.assertEqual(self.services.calls[-1][0], 'cleanup')
            self.assertEqual(driver.poll_cleanup(handle, model_step=0).state, 'PENDING')
        result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.completed_fields), ('COMPLETE', CLEANUP_FIELDS))
        self.assertEqual(sum(call[0]=='cleanup' for call in self.services.calls), 1)
        self.assertFalse(self.native.pending_local_cleanup)
        self.assertEqual(driver.cleanup_errors[0][1], 'RESOURCE')

    def test_cleanup_has_local_monotonic_deadline(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        driver.begin(next(self.plan.iter_actions()), model_step=0)
        self.f.can_request()
        with patch.object(self.f.owner, 'retire_can', side_effect=ICDError('RESOURCE','local failure')):
            handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
            self.f.f.clock.value += 1_000_000_000
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED', 'TIMEOUT'))
        self.assertTrue(self.native.pending_local_cleanup)
        driver.poll_cleanup(handle, model_step=0)
        self.assertFalse(self.native.pending_local_cleanup)

    def test_missing_receipt_never_becomes_complete(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        self.services.cleanup_fields = CLEANUP_FIELDS[:-1]
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED','SAFETY'))

    def test_explicit_none_step_cannot_start_remote_cleanup(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        self.rejects('SCHEMA', lambda: driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=None))
        self.assertFalse(any(c[0]=='cleanup' for c in self.services.calls))

    def test_bad_local_cleanup_clock_still_attempts_remote_cleanup(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        self.f.f.clock.value = -1
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        self.assertEqual(self.services.calls[-1][0], 'cleanup')
        result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED','SCHEMA'))

    def test_cleanup_error_history_stays_bounded_and_invalid_receipts_are_closed(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        errors = ['RESOURCE','STATE']*20
        def failure(*args, **kwargs):
            raise ICDError(errors.pop(0),'repeat local failure')
        with patch.object(self.native, 'stop', side_effect=failure):
            handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
            with patch.object(self.services, 'poll_cleanup', return_value=
                              CleanupProgress(self.services.cleanup_handle, 'PENDING')):
                for _ in range(19):
                    driver.poll_cleanup(handle, model_step=0)
        self.assertLessEqual(len(driver.cleanup_errors), 2)
        self.services.cleanup_fields = ([],)
        result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED','SCHEMA'))

    def test_service_poll_exception_retains_context_and_separate_remote_error(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        with patch.object(self.services, 'poll_cleanup', side_effect=OSError('original remote poll failure')):
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED','RESOURCE'))
        self.assertIn(('REMOTE_POLL','RESOURCE'), driver.cleanup_errors)

    def test_delegate_begin_failure_is_not_retried(self):
        self.status()
        driver = self.build([send('external', 0, 10, link_id='CUTIL')])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        with patch.object(self.services, 'begin', side_effect=ICDError('RESOURCE','begin failed')) as called:
            self.rejects('RESOURCE', lambda: driver.begin(action, model_step=0))
            self.rejects('STATE', lambda: driver.begin(action, model_step=0))
        self.assertEqual(called.call_count, 1)

    def test_cleanup_deadline_clock_failure_is_local_not_remote(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        with patch.object(self.native, 'stop', side_effect=ICDError('RESOURCE','local recovery blocked')):
            handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
            self.f.f.clock.value = -1
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED','SCHEMA'))
        self.assertIn(('LOCAL_CLOCK','SCHEMA'), driver.cleanup_errors)
        self.assertNotIn(('REMOTE_POLL','SCHEMA'), driver.cleanup_errors)

    def test_forged_root_assertion_metadata_is_rejected_before_service_begin(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        assertion = replace(self.plan.assertions[0],
                            reader_path_pending=int(self.plan.assertions[0].reader_path_pending))
        self.rejects('STATE', lambda: driver.begin_assertions((assertion,), model_step=0))
        self.assertFalse(any(c[0]=='assertions' for c in self.services.calls))

    def test_cleanup_accumulates_original_incremental_receipts(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        delegate = self.services.cleanup_handle
        with patch.object(self.services, 'poll_cleanup', side_effect=[
                CleanupProgress(delegate, 'PENDING', CLEANUP_FIELDS[:4]),
                CleanupProgress(delegate, 'COMPLETE', CLEANUP_FIELDS[4:])]):
            first = driver.poll_cleanup(handle, model_step=0)
            last = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual(first.completed_fields, CLEANUP_FIELDS[:4])
        self.assertEqual((last.state, last.completed_fields), ('COMPLETE', CLEANUP_FIELDS))

    def test_remote_terminal_receipt_is_not_repolled_while_local_recovery_pending(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        delegate = self.services.cleanup_handle
        with patch.object(self.services, 'poll_cleanup', side_effect=[
                CleanupProgress(delegate, 'COMPLETE', CLEANUP_FIELDS),
                ICDError('STATE','original remote handle already terminal')]) as poll:
            with patch.object(self.native, 'stop', side_effect=ICDError('RESOURCE','local retry needed')):
                self.assertEqual(driver.poll_cleanup(handle, model_step=0).state, 'PENDING')
            self.assertEqual(driver.poll_cleanup(handle, model_step=0).state, 'COMPLETE')
        self.assertEqual(poll.call_count, 1)

    def test_service_poll_session_change_cannot_cache_completion(self):
        self.status()
        driver = self.build([send('service', 0, 10, link_id='CUTIL')])
        driver.preflight(self.plan)
        handle = driver.begin(next(self.plan.iter_actions()), model_step=0)
        delegate = next(iter(self.services.progress))
        def changed_session(*args, **kwargs):
            self.f.f.session._sid += 1
            return ActionProgress(delegate, 'COMPLETE')
        with patch.object(self.services, 'poll', side_effect=changed_session):
            self.rejects('STALE_SESSION', lambda: driver.poll(handle, model_step=0))
        self.assertIsNone(driver._entries[id(handle)].result)

    def test_cleanup_stale_session_stops_local_without_remote_begin(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        self.f.f.session._sid += 1
        with patch.object(self.native, 'stop', wraps=self.native.stop) as stop:
            handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertGreaterEqual(stop.call_count, 1)
        self.assertFalse(any(c[0]=='cleanup' for c in self.services.calls))
        self.assertEqual((result.state, result.error), ('FAILED','STALE_SESSION'))

    def test_cleanup_provider_session_change_cannot_count_new_receipts(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        delegate = self.services.cleanup_handle
        def changed_session(*args, **kwargs):
            self.f.f.session._sid += 1
            return CleanupProgress(delegate, 'COMPLETE', CLEANUP_FIELDS)
        with patch.object(self.services, 'poll_cleanup', side_effect=changed_session):
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error, result.completed_fields),
                         ('FAILED','STALE_SESSION',()))

    def test_service_begin_session_change_retains_attempt_without_retry(self):
        self.status()
        driver = self.build([send('service', 0, 10, link_id='CUTIL')])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        def changed_session(*args, **kwargs):
            self.f.f.session._sid += 1
            return self.services._new(('begin', action, 0))
        with patch.object(self.services, 'begin', side_effect=changed_session) as begin:
            self.rejects('STALE_SESSION', lambda: driver.begin(action, model_step=0))
            self.rejects('STALE_SESSION', lambda: driver.begin(action, model_step=0))
        self.assertEqual(begin.call_count, 1)
        self.assertEqual(len(driver._entries), 1)

    def test_cleanup_session_change_before_poll_never_calls_remote(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        self.f.f.session._sid += 1
        with patch.object(self.services, 'poll_cleanup', wraps=self.services.poll_cleanup) as poll:
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual(poll.call_count, 0)
        self.assertEqual((result.state, result.error), ('FAILED','STALE_SESSION'))

    def test_cleanup_can_confirm_actual_original_source_close(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        delegate = self.services.cleanup_handle
        def actual_close(*args, **kwargs):
            self.f.owner.close()
            self.f.owner.dispatcher.close()
            self.f.f.session.close()
            return CleanupProgress(delegate, 'COMPLETE', CLEANUP_FIELDS)
        with patch.object(self.services, 'poll_cleanup', side_effect=actual_close) as poll:
            first = driver.poll_cleanup(handle, model_step=0)
            last = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((first.state, first.completed_fields), ('COMPLETE', CLEANUP_FIELDS))
        self.assertIs(last, first)
        self.assertEqual(poll.call_count, 1)
        self.assertIsNone(self.f.f.session.session_id)

    def test_cleanup_synchronous_original_close_can_deliver_final_receipt(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        begin = self.services.begin_cleanup
        def synchronous_close(*args, **kwargs):
            delegate = begin(*args, **kwargs)
            self.f.owner.close()
            self.f.owner.dispatcher.close()
            self.f.f.session.close()
            return delegate
        with patch.object(self.services, 'begin_cleanup', side_effect=synchronous_close):
            handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        with patch.object(self.services, 'poll_cleanup', wraps=self.services.poll_cleanup) as poll:
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.completed_fields), ('COMPLETE', CLEANUP_FIELDS))
        self.assertEqual(poll.call_count, 1)

    def test_closing_another_sid_cannot_confirm_original_cleanup(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        handle = driver.begin_cleanup(self.plan.scenario['cleanup'], model_step=0)
        delegate = self.services.cleanup_handle
        def changed_close(*args, **kwargs):
            self.f.f.session._sid += 1
            self.f.owner.close()
            self.f.owner.dispatcher.close()
            self.f.f.session.close()
            return CleanupProgress(delegate, 'COMPLETE', CLEANUP_FIELDS)
        with patch.object(self.services, 'poll_cleanup', side_effect=changed_close):
            result = driver.poll_cleanup(handle, model_step=0)
        self.assertEqual((result.state, result.error), ('FAILED','STALE_SESSION'))

    def test_empty_provider_handle_cannot_be_wrapped_as_valid_action(self):
        self.status()
        driver = self.build([send('service', 0, 10, link_id='CUTIL')])
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        with patch.object(self.services, 'begin', return_value=None) as begin:
            self.rejects('STATE', lambda: driver.begin(action, model_step=0))
            self.rejects('STATE', lambda: driver.begin(action, model_step=0))
        self.assertEqual(begin.call_count, 1)

    def test_empty_provider_handle_cannot_be_wrapped_as_valid_root_assertion(self):
        self.status()
        driver = self.build()
        driver.preflight(self.plan)
        with patch.object(self.services, 'begin_assertions', return_value=None) as begin:
            self.rejects('STATE', lambda: driver.begin_assertions(self.plan.assertions, model_step=0))
            self.rejects('STATE', lambda: driver.begin_assertions(self.plan.assertions, model_step=0))
        self.assertEqual(begin.call_count, 1)

    def test_finite_handle_budget_and_reentry_are_rejected(self):
        self.status()
        self.rejects('CAPACITY', lambda: self.build(max_handles=1))
        driver = self.build()
        driver.preflight(self.plan)
        action = next(self.plan.iter_actions())
        def target(value, *, model_step):
            self.rejects('STATE', lambda: driver.begin(value, model_step=model_step))
            return 100
        with patch.object(self.services, 'native_target', side_effect=target):
            driver.begin(action, model_step=0)
        self.f.can_request()
