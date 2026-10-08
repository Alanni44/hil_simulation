import importlib
import unittest
from dataclasses import replace

from common import GatewayTest
from input_simulator.scenario import ScenarioPlan
from test_scenario import scenario, send, periodic, stop
from test_source_inputs import source_inputs, history_input
from test_waveform import event as wave


class ScenarioExecutionTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.scenario_execution'),
                             'original W3 runtime controller is missing')
        self.module = importlib.import_module('input_simulator.scenario_execution')
        module = self.module

        class TestDriver(module.ScenarioDriver):
            """Scheduler test double only, never a production tool/model driver."""
            def __init__(self):
                self.calls, self.handles, self.progress = [], [], {}
                self.fail_preflight = self.fail_begin = self.fail_poll = None
                self.cleanup_fields = module.CLEANUP_FIELDS

            def preflight(self, plan):
                self.calls.append(('preflight', plan))
                if self.fail_preflight:
                    raise self.fail_preflight

            def begin_assertions(self, assertions, *, model_step):
                return self._new(('assertions', assertions, model_step))

            def _new(self, call):
                self.calls.append(call)
                if self.fail_begin:
                    raise self.fail_begin
                handle = object()
                self.handles.append(handle)
                self.progress[handle] = module.ActionProgress(handle, 'PENDING')
                return handle

            def begin(self, action, *, model_step):
                return self._new(('begin', action, model_step))

            def poll(self, handle, *, model_step):
                if self.fail_poll:
                    raise self.fail_poll
                return self.progress[handle]

            def begin_cleanup(self, cleanup, *, model_step):
                self.calls.append(('cleanup', cleanup, model_step))
                self.cleanup_handle = object()
                return self.cleanup_handle

            def poll_cleanup(self, handle, *, model_step):
                return module.CleanupProgress(handle, 'COMPLETE', tuple(self.cleanup_fields))

            def complete(self, handle, *, error=None):
                self.progress[handle] = module.ActionProgress(handle, 'FAILED' if error else 'COMPLETE', error)

        self.driver = TestDriver()

    def build(self, events, **kwargs):
        history_id = kwargs.pop('history_id', None)
        self.plan = ScenarioPlan.compile(self.contract, scenario(events), model_id='quadrotor_hil', history_id=history_id)
        self.execution = self.module.ScenarioExecution(self.contract, self.plan, self.driver, **kwargs)
        return self.execution

    def begun(self):
        return [call[1] for call in self.driver.calls if call[0] == 'begin']

    def complete_all(self):
        for handle in self.driver.handles:
            self.driver.complete(handle)

    def test_missing_driver_and_preflight_rejection_never_start_or_dispatch(self):
        run = self.build([send(step=0)])
        self.rejects('TARGET_MISSING', lambda: self.module.ScenarioExecution(self.contract, self.plan, None))
        from icd_runtime.errors import ICDError
        self.driver.fail_preflight = ICDError('TARGET_MISSING', 'no actual probe/backend')
        self.rejects('TARGET_MISSING', lambda: run.start(model_step=0))
        self.assertEqual(run.state, 'READY')
        self.assertEqual(self.begun(), [])
        self.assertFalse(any(c[0] == 'cleanup' for c in self.driver.calls))

    def test_root_assertions_and_same_original_complete_stimulus_are_retained(self):
        run = self.build([send(step=0, link_id='CUTIL')])
        run.start(model_step=0)
        self.assertEqual(self.driver.calls[1][0], 'assertions')
        self.assertEqual(self.driver.calls[1][1], self.plan.assertions)
        self.assertEqual(self.begun()[0], next(self.plan.iter_actions()))
        self.assertEqual(self.begun()[0].link_id, 'CUTIL')
        self.complete_all()
        run.advance(model_step=0)
        self.assertEqual(run.state, 'CLEANUP_PENDING')
        run.advance(model_step=0)
        self.assertEqual(run.state, 'LOCAL_STOPPED')
        self.assertFalse(run.execution_ready)
        self.assertEqual(run.qualification_status, 'NOT_EVALUATED')

    def test_wait_blocks_same_step_following_until_original_handle_completes(self):
        assertion = {**source_inputs()['scenario']['assertions'][0], 'assertion_id': 'wait-runtime'}
        wait = {'event_id': 'a-wait', 'at_step': 0, 'priority': 10, 'link_id': 'ETHGEN',
                'type': 'WAIT', 'assertion': assertion}
        run = self.build([wait, send('z-send', 0, priority=20)])
        run.start(model_step=0)
        self.assertEqual([a.kind for a in self.begun()], ['WAIT'])
        self.assertEqual(run.state, 'WAITING')
        run.advance(model_step=0)
        self.assertEqual(len(self.begun()), 1)
        self.driver.complete(self.driver.handles[1])
        run.advance(model_step=0)
        self.assertEqual([a.kind for a in self.begun()], ['WAIT', 'SEND'])

    def test_wait_does_not_rewrite_overdue_absolute_steps_after_release(self):
        assertion = {**source_inputs()['scenario']['assertions'][0], 'assertion_id': 'wait-runtime'}
        wait = {'event_id': 'a', 'at_step': 0, 'priority': 10, 'link_id': 'ETHGEN', 'type': 'WAIT', 'assertion': assertion}
        run = self.build([wait, send('b', 1)])
        run.start(model_step=0)
        self.driver.complete(self.driver.handles[1])
        run.advance(model_step=2)
        self.assertEqual(len(self.begun()), 1)
        self.assertEqual(run.failure, 'TIMEOUT')
        self.assertEqual(run.state, 'CLEANUP_PENDING')

    def test_ten_original_event_kinds_and_replay_negative_fields_not_changed(self):
        value = source_inputs()['scenario']
        assertion = {**value['assertions'][0], 'assertion_id': 'runtime-wait'}
        other = {**assertion, 'assertion_id': 'runtime-assert'}
        common = {'priority': 100, 'link_id': 'ETHREPLAY'}
        history, _ = history_input()
        events = [send('send', 0), wave(event_id='wave', at_step=1, duration_steps=1),
                  periodic('period', 3, count=1), stop('period', 4),
                  {'event_id': 'wait', 'type': 'WAIT', 'at_step': 5, 'assertion': assertion, **common},
                  {'event_id': 'replay', 'type': 'REPLAY', 'at_step': 6, 'history_id': 'capture-01',
                   'policy': history['history']['policy'], **common}, send('fault', 7, 11, type='FAULT'),
                  {'event_id': 'assert', 'type': 'ASSERT', 'at_step': 8, 'assertion': other, **common},
                  send('negative', 9, type='NEGATIVE_SEND', mutation={'kind': 'CRC_XOR', 'xor_mask': 1},
                       expected_error='CRC', must_not_apply=True, authorization_case_id='T02'),
                  {'event_id': 'end', 'type': 'END_CLEANUP', 'at_step': 10, 'cleanup': value['cleanup'], **common}]
        run = self.build(events, history_id='capture-01')
        run.start(model_step=0)
        for step in range(11):
            self.complete_all()
            run.advance(model_step=step)
        self.complete_all()
        run.advance(model_step=10)
        self.assertEqual(tuple(self.begun()), tuple(a for a in self.plan.iter_actions() if a.kind != 'END_CLEANUP'))
        self.assertEqual(self.driver.calls[-1][0], 'cleanup')
        self.assertEqual(self.driver.calls[-1][1], value['cleanup'])

    def test_periodic_and_waveform_sampling_uses_original_order_without_duplication(self):
        run = self.build([periodic(mid=7, period=2, count=3), wave(at_step=0, duration_steps=4,
                         sample_period_steps=2, waveform={'kind': 'RAMP', 'start_value': 0, 'end_value': 4, 'duration_steps': 4})])
        run.start(model_step=0)
        for step in (0, 1, 2, 2, 3, 4):
            self.complete_all()
            run.advance(model_step=step)
        self.assertEqual(tuple(self.begun()), tuple(self.plan.iter_actions()))

    def test_root_assertions_must_finish_before_cleanup(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        self.driver.complete(self.driver.handles[1])
        run.advance(model_step=0)
        self.assertEqual(run.state, 'RUNNING')
        self.assertFalse(any(c[0] == 'cleanup' for c in self.driver.calls))

    def test_foreign_progress_handle_is_rejected_and_cleanup_requested(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        self.driver.progress[self.driver.handles[0]] = self.module.ActionProgress(object(), 'COMPLETE')
        run.advance(model_step=0)
        self.assertEqual(run.failure, 'STATE')
        self.assertEqual(run.state, 'CLEANUP_PENDING')

    def test_failure_reaches_cleanup_without_starting_later_events(self):
        run = self.build([send(step=0), send('later', 1)])
        run.start(model_step=0)
        self.driver.complete(self.driver.handles[1], error='TARGET_MISSING')
        run.advance(model_step=1)
        self.assertEqual(run.failure, 'TARGET_MISSING')
        self.assertEqual(len(self.begun()), 1)
        run.advance(model_step=1)
        self.assertEqual(run.state, 'FAILED')

    def test_skip_model_step_fails_without_catchup_or_new_handle(self):
        run = self.build([send(step=1), send('later', 3)])
        run.start(model_step=0)
        run.advance(model_step=2)
        self.assertEqual(run.failure, 'TIMEOUT')
        self.assertEqual(self.begun(), [])

    def test_strict_step_types_backwards_and_second_start(self):
        run = self.build([send(step=5)])
        for step in (True, 0.0, -1, 0x100000000):
            self.rejects('SCHEMA', lambda: run.start(model_step=step))
        run.start(model_step=2)
        self.rejects('STATE', lambda: run.start(model_step=2))
        self.rejects('SCHEMA', lambda: run.advance(model_step=1))
        self.assertEqual(run.state, 'RUNNING')

    def test_cleanup_missing_one_of_nine_fields_never_local_stopped(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        self.driver.cleanup_fields = self.module.CLEANUP_FIELDS[:-1]
        run.stop(model_step=0)
        run.advance(model_step=0)
        self.assertEqual(run.state, 'FAILED')
        self.assertEqual(run.failure, 'SAFETY')
        self.assertFalse(run.safety_verified)
        self.assertTrue(run.pending_cleanup)

    def test_stop_cleanup_once_and_does_not_reexecute_or_claim_remote_safety(self):
        run = self.build([send(step=0), send('later', 1)])
        run.start(model_step=0)
        run.stop(model_step=0)
        run.stop(model_step=0)
        run.advance(model_step=1)
        self.assertEqual(run.state, 'LOCAL_STOPPED')
        self.assertEqual(sum(c[0] == 'cleanup' for c in self.driver.calls), 1)
        self.assertEqual(len(self.begun()), 1)
        self.assertFalse(run.safety_verified)

    def test_complete_budget_rejects_million_actions_before_any_driver_call(self):
        self.rejects('CAPACITY', lambda: self.build([periodic(period=1, count=1000000)]))
        self.assertEqual(self.driver.calls, [])
        for kwargs in ({'max_records': True}, {'max_pending': 0}, {'max_bytes': 0}):
            self.rejects('CAPACITY', lambda: self.build([send()], **kwargs))
        self.rejects('CAPACITY', lambda: self.build([send()], max_bytes=1))

    def test_pending_limit_fails_before_next_begin_without_partial_overwrite(self):
        run = self.build([send('a', 0), send('b', 0, mid=11)], max_pending=1)
        run.start(model_step=0)
        self.assertEqual(self.begun(), [])
        self.assertEqual(run.failure, 'BUFFER_FULL')
        self.assertEqual(len(self.driver.handles), 1)  # Root assertions consume one slot.

    def test_driver_non_icd_exception_is_recorded_and_cleanup_runs(self):
        run = self.build([send(step=0)])
        self.driver.fail_begin = RuntimeError('actual handler failed')
        run.start(model_step=0)
        self.assertEqual(run.failure, 'RESOURCE')
        self.assertEqual(run.state, 'CLEANUP_PENDING')
        self.assertEqual(sum(c[0] == 'cleanup' for c in self.driver.calls), 1)

    def test_forged_compiled_plan_and_unknown_progress_are_not_trusted(self):
        run = self.build([send(step=0)])
        forged = replace(self.plan, _streams=())
        self.rejects('RESOURCE', lambda: self.module.ScenarioExecution(self.contract, forged, self.driver))
        run.start(model_step=0)
        self.driver.progress[self.driver.handles[0]] = self.module.ActionProgress(self.driver.handles[0], 'APPLIED')
        run.advance(model_step=0)
        self.assertEqual(run.failure, 'SCHEMA')

    def test_same_handle_for_two_operations_is_rejected(self):
        run = self.build([send(step=0)])
        original = self.driver.begin
        def reuse(action, *, model_step):
            original(action, model_step=model_step)
            return self.driver.handles[0]
        self.driver.begin = reuse
        run.start(model_step=0)
        self.assertEqual(run.failure, 'STATE')

    def test_event_assertions_do_not_start_as_root_assertions_before_their_events(self):
        assertion = {**source_inputs()['scenario']['assertions'][0], 'assertion_id': 'later-assert'}
        event = {'event_id': 'assert', 'type': 'ASSERT', 'at_step': 10, 'priority': 100,
                 'link_id': 'ETHGEN', 'assertion': assertion}
        run = self.build([event])
        run.start(model_step=0)
        started = self.driver.calls[1][1]
        self.assertEqual([a.assertion['assertion_id'] for a in started],
                         [a['assertion_id'] for a in self.plan.scenario['assertions']])

    def test_wait_timeout_is_enforced_even_if_driver_stays_pending(self):
        assertion = {**source_inputs()['scenario']['assertions'][0], 'assertion_id': 'wait-runtime',
                     'timeout_steps': 2}
        wait = {'event_id': 'a', 'at_step': 0, 'priority': 10, 'link_id': 'ETHGEN', 'type': 'WAIT', 'assertion': assertion}
        run = self.build([wait, send('b', 5)])
        run.start(model_step=0)
        run.advance(model_step=2)
        self.assertEqual(run.failure, 'TIMEOUT')
        self.assertEqual(run.state, 'CLEANUP_PENDING')
        self.assertEqual(len(self.begun()), 1)

    def test_successful_stop_retains_local_cancellation_and_nine_cleanup_receipts(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        run.stop(model_step=0)
        run.advance(model_step=0)
        self.assertEqual(run.pending_count, 0)
        self.assertEqual(sum(r.outcome == 'LOCAL_CANCELLED' for r in run.records), 2)
        receipt = run.records[-1]
        self.assertEqual(receipt.kind, 'CLEANUP')
        self.assertEqual(receipt.completed_cleanup_fields, self.module.CLEANUP_FIELDS)

    def test_terminal_records_keep_original_runtime_handle_correlation(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        handle = self.driver.handles[1]
        self.driver.complete(handle)
        run.advance(model_step=0)
        terminal = next(r for r in run.records if r.kind == 'SEND' and r.outcome == 'COMPLETE')
        self.assertIs(getattr(terminal, 'handle', None), handle)

    def test_each_root_assertion_deadline_is_enforced_independently(self):
        value = scenario([send(step=50)])
        a = value['assertions'][0]
        value['assertions'] = [{**a, 'assertion_id': 'short', 'timeout_steps': 2},
                               {**a, 'assertion_id': 'long', 'timeout_steps': 10}]
        self.plan = ScenarioPlan.compile(self.contract, value, model_id='quadrotor_hil')
        run = self.module.ScenarioExecution(self.contract, self.plan, self.driver)
        run.start(model_step=0)
        run.advance(model_step=2)
        self.assertEqual(run.failure, 'TIMEOUT')

    def test_completed_short_root_does_not_timeout_while_long_root_is_pending(self):
        value = scenario([send(step=50)])
        a = value['assertions'][0]
        value['assertions'] = [{**a, 'assertion_id': 'short', 'timeout_steps': 2},
                               {**a, 'assertion_id': 'long', 'timeout_steps': 10}]
        self.plan = ScenarioPlan.compile(self.contract, value, model_id='quadrotor_hil')
        run = self.module.ScenarioExecution(self.contract, self.plan, self.driver)
        run.start(model_step=0)
        self.driver.complete(self.driver.handles[0])
        run.advance(model_step=1)
        run.advance(model_step=2)
        self.assertIsNone(run.failure)
        self.assertEqual(run.pending_count, 1)

    def test_cleanup_unknown_error_is_normalized_to_frozen_resource(self):
        from icd_runtime.errors import ICDError
        run = self.build([send(step=0)])
        run.start(model_step=0)
        run.stop(model_step=0)
        def failed(handle, *, model_step):
            raise ICDError('NOT_A_FROZEN_ERROR', 'bad adapter exception')
        self.driver.poll_cleanup = failed
        run.advance(model_step=0)
        self.assertEqual(run.failure, 'RESOURCE')
        self.assertEqual(run.records[-1].error, 'RESOURCE')

    def test_begin_failure_record_names_original_attempted_event(self):
        run = self.build([send('failing-original-send', 1)])
        run.start(model_step=0)
        self.driver.fail_begin = RuntimeError('backend failed')
        run.advance(model_step=1)
        self.assertTrue(any(r.event_id == 'failing-original-send' and r.outcome == 'FAILED'
                            for r in run.records))

    def test_poll_exception_preserves_original_failed_handle_not_cancellation(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        self.driver.fail_poll = RuntimeError('backend poll failed')
        run.advance(model_step=0)
        self.assertTrue(any(r.outcome == 'FAILED' and getattr(r, 'handle', None) is self.driver.handles[0]
                            for r in run.records))

    def test_cleanup_exception_record_is_distinct_from_prior_run_failure(self):
        from icd_runtime.errors import ICDError
        run = self.build([send(step=1)])
        run.start(model_step=0)
        def failed(cleanup, *, model_step):
            raise ICDError('SAFETY', 'cleanup start failed')
        self.driver.begin_cleanup = failed
        run.advance(model_step=2)
        self.assertEqual(run.failure, 'TIMEOUT')
        self.assertEqual(run.records[-1].kind, 'CLEANUP')
        self.assertEqual(run.records[-1].error, 'SAFETY')

    def test_incremental_cleanup_requires_all_nine_receipts(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        run.stop(model_step=0)
        fields = self.module.CLEANUP_FIELDS
        self.driver.poll_cleanup = lambda handle, model_step: self.module.CleanupProgress(handle, 'PENDING', fields[:4])
        run.advance(model_step=0)
        self.assertEqual(run.state, 'CLEANUP_PENDING')
        self.driver.poll_cleanup = lambda handle, model_step: self.module.CleanupProgress(handle, 'COMPLETE', fields[4:])
        run.advance(model_step=0)
        self.assertEqual(run.state, 'LOCAL_STOPPED')
        self.assertEqual(run.records[-1].completed_cleanup_fields, fields)

    def test_incremental_cleanup_pending_receipts_are_retained_once(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        run.stop(model_step=0)
        fields = self.module.CLEANUP_FIELDS
        self.driver.poll_cleanup = lambda handle, model_step: self.module.CleanupProgress(handle,'PENDING',fields[:4])
        run.advance(model_step=0)
        progress = [r for r in run.records if r.kind=='CLEANUP' and r.outcome=='PROGRESS']
        self.assertEqual(len(progress),1)
        self.assertEqual(progress[0].completed_cleanup_fields,fields[:4])
        run.advance(model_step=0)
        self.assertEqual(len([r for r in run.records if r.outcome=='PROGRESS']),1)

    def test_all_nine_incremental_receipts_are_bounded_and_survive_failure(self):
        run = self.build([send(step=0)])
        run.start(model_step=0)
        run.stop(model_step=0)
        fields = self.module.CLEANUP_FIELDS
        for field in fields:
            self.driver.poll_cleanup = lambda handle, model_step, f=field: self.module.CleanupProgress(handle,'PENDING',(f,))
            run.advance(model_step=0)
            run.advance(model_step=0)
        rows = [r for r in run.records if r.outcome=='PROGRESS']
        self.assertEqual(tuple(r.completed_cleanup_fields[0] for r in rows),fields)
        self.driver.poll_cleanup = lambda handle, model_step: self.module.CleanupProgress(handle,'FAILED',(),'SAFETY')
        run.advance(model_step=0)
        self.assertEqual(run.records[-1].completed_cleanup_fields,fields)
        self.assertEqual(run.failure,'SAFETY')

    def test_driver_reentrancy_is_rejected_without_second_execution(self):
        run = self.build([send(step=0)])
        original = self.driver.poll
        def poll(handle, *, model_step):
            self.rejects('STATE', lambda: run.advance(model_step=model_step))
            return original(handle, model_step=model_step)
        self.driver.poll = poll
        run.start(model_step=0)
        self.assertEqual(run.state, 'RUNNING')
        self.assertEqual(len(self.begun()), 1)

    def test_end_waits_for_outstanding_assert_operation_before_cleanup(self):
        value = source_inputs()['scenario']
        assertion = {**value['assertions'][0], 'assertion_id': 'runtime-assert'}
        common = {'priority': 100, 'link_id': 'ETHGEN'}
        run = self.build([{'event_id': 'assert', 'type': 'ASSERT', 'at_step': 1, 'assertion': assertion, **common},
                          {'event_id': 'end', 'type': 'END_CLEANUP', 'at_step': 2, 'cleanup': value['cleanup'], **common}])
        run.start(model_step=0)
        self.driver.complete(self.driver.handles[0])
        run.advance(model_step=1)
        run.advance(model_step=2)
        self.assertFalse(any(c[0] == 'cleanup' for c in self.driver.calls))
        self.driver.complete(self.driver.handles[1])
        run.advance(model_step=2)
        self.assertEqual(run.state, 'CLEANUP_PENDING')

    def test_unhashable_adapter_error_code_cannot_escape_failure_recording(self):
        from icd_runtime.errors import ICDError
        for location in ('begin', 'poll', 'cleanup'):
            run = self.build([send(step=0)])
            run.start(model_step=0)
            if location == 'begin':
                # A fresh run exercises begin_assertions without prior effects.
                run = self.build([send(step=0)])
                self.driver.fail_begin = ICDError([], 'unhashable adapter error')
                run.start(model_step=0)
            elif location == 'poll':
                self.driver.fail_poll = ICDError([], 'unhashable adapter error')
                run.advance(model_step=0)
            else:
                run.stop(model_step=0)
                def failed(handle, *, model_step):
                    raise ICDError([], 'unhashable adapter error')
                self.driver.poll_cleanup = failed
                run.advance(model_step=0)
            self.assertEqual(run.failure, 'RESOURCE')
            self.assertTrue(any(r.error == 'RESOURCE' and r.outcome == 'FAILED' for r in run.records))
            self.driver.fail_begin = self.driver.fail_poll = None


if __name__ == '__main__':
    unittest.main()
