import copy
from dataclasses import FrozenInstanceError
import importlib.util
import math
import unittest
from unittest.mock import patch

from common import GatewayTest, message
from input_simulator.source_inputs import SourceInputAuditor
from test_source_inputs import history_input, resources, source_inputs
from test_waveform import event as wave_event


def send(name='send-01', step=100, mid=10, **changes):
    return {'event_id': name, 'at_step': step, 'priority': 100, 'link_id': 'ETHGEN',
            'type': 'SEND', 'stimulus': {'message_id': mid, 'payload': message(mid)['payload']}, **changes}


def periodic(name='period-01', step=0, mid=10, *, period=10, count=10, **changes):
    return send(name, step, mid, **{'type':'PERIODIC_START', 'sender_id':name,
                                  'period_steps':period, 'count':count, **changes})


def stop(sender='period-01', step=50, **changes):
    return {'event_id': 'stop-01', 'at_step': step, 'priority': 50, 'link_id': 'ETHGEN',
            'type': 'PERIODIC_STOP', 'sender_id': sender, **changes}


def scenario(events):
    result = source_inputs()['scenario']
    result['events'] = events
    return result


class ScenarioTests(GatewayTest):
    def compile(self, events, *, model='quadrotor_hil', **kwargs):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.scenario'), 'common scenario timeline missing')
        from input_simulator.scenario import ScenarioPlan
        value = scenario(events)
        if model in ('quadrotor_hil','multirotor_6_hil','fixed_wing_hil'):
            value['assertions'][0]['probe_id'] = model + '.input.environment.wind_n_mps'
        return ScenarioPlan.compile(self.contract, value, model_id=model, **kwargs)

    def test_all_ten_events_retained_sorted_and_controls_not_executed(self):
        assertion = source_inputs()['scenario']['assertions'][0]
        history, _ = history_input()
        common = {'priority': 100, 'link_id': 'ETHGEN'}
        events = [send('send', 1), wave_event(event_id='wave', at_step=2, duration_steps=1),
                  periodic('period', 4, count=1), stop('period', 5),
                  {'event_id': 'wait', 'at_step': 6, 'type': 'WAIT',
                   'assertion': {**assertion, 'assertion_id': 'wait-probe'}, **common},
                  {'event_id': 'replay', 'at_step': 7, 'type': 'REPLAY', 'history_id': 'capture-01',
                   'policy': history['history']['policy'], **common},
                  send('fault', 8, 11, type='FAULT'),
                  {'event_id': 'assert', 'at_step': 9, 'type': 'ASSERT',
                   'assertion': {**assertion, 'assertion_id': 'assert-probe'}, **common},
                  send('negative', 10, type='NEGATIVE_SEND', mutation={'kind': 'CRC_XOR', 'xor_mask': 1},
                       expected_error='CRC', must_not_apply=True, authorization_case_id='T02'),
                  {'event_id': 'end', 'at_step': 11, 'type': 'END_CLEANUP',
                   'cleanup': source_inputs()['scenario']['cleanup'], **common}]
        p = self.compile(list(reversed(events)), history_id='capture-01')
        actions = tuple(p.iter_actions())
        self.assertEqual({a.kind for a in actions}, {e['type'] for e in events})
        self.assertEqual([a.step for a in actions], sorted(a.step for a in actions))
        self.assertFalse(p.execution_ready)
        self.assertTrue(all(not a.execution_ready for a in actions))
        wait = next(a for a in actions if a.kind == 'WAIT')
        self.assertTrue(wait.blocks_following_events)
        self.assertTrue(wait.needs_runtime_handler)
        neg = next(a for a in actions if a.kind == 'NEGATIVE_SEND')
        self.assertEqual(neg.stimulus, events[-2]['stimulus'])
        self.assertTrue(neg.needs_runtime_handler)
        self.assertIn('ACTUAL_EVENT_EXECUTION_AND_WAIT_PROBES', p.pending_checks)
        self.assertIn('REPLAY_WRITABLE_TARGETS_AND_EXPANSION', p.pending_checks)

    def test_sort_priority_then_event_id_without_changing_original_snapshot(self):
        p = self.compile([send('z', 50, 11, priority=20), send('b', 50, 17, priority=10),
                          send('a', 50, 10, priority=10)])
        self.assertEqual([a.event_id for a in p.iter_actions()], ['a', 'b', 'z'])
        self.assertEqual([e['event_id'] for e in p.scenario['events']], ['z', 'b', 'a'])

    def test_snapshot_actions_detached_immutable_and_signed_zero_preserved(self):
        e = send()
        e['stimulus']['payload']['wind_n_mps'] = -0.0
        p = self.compile([e])
        e['stimulus']['payload'].clear()
        a = next(p.iter_actions())
        self.assertEqual(math.copysign(1, a.stimulus['payload']['wind_n_mps']), -1)
        a.stimulus['payload'].clear()
        p.scenario['events'].clear()
        self.assertEqual(len(next(p.iter_actions()).stimulus['payload']), 6)
        with self.assertRaises(FrozenInstanceError):
            a.step = 99
        self.assertEqual(set(a.stimulus), {'message_id', 'payload'})

    def test_periodic_first_count_and_same_step_stop_sort_boundary(self):
        p = self.compile([periodic(count=4)])
        self.assertEqual([(a.step, a.index) for a in p.iter_actions()], [(0,0),(10,1),(20,2),(30,3)])
        for priority, steps in ((50,[0,10]), (150,[0,10,20])):
            p = self.compile([periodic(count=4), stop(step=20,priority=priority)])
            self.assertEqual([a.step for a in p.iter_actions() if a.stimulus is not None], steps)
            self.assertEqual(sum(a.kind == 'PERIODIC_STOP' for a in p.iter_actions()), 1)

    def test_waveform_exact_terminal_sample_even_when_period_not_divisible(self):
        p = self.compile([wave_event(at_step=10, duration_steps=25, sample_period_steps=20,
                                    waveform={'kind':'RAMP','start_value':0,'end_value':25,'duration_steps':25})])
        actions = tuple(p.iter_actions())
        self.assertEqual([a.step for a in actions], [10,30,35])
        self.assertEqual([a.stimulus['payload']['wind_n_mps'] for a in actions], [0,20,25])
        self.assertEqual(len(actions[0].writable_targets), 6)
        self.assertEqual(len(p.waveforms), 1)

    def test_end_cleanup_clips_future_streams_but_is_not_completed_cleanup(self):
        end = source_inputs()['scenario']['events'][-1]
        end['at_step'] = 25
        p = self.compile([periodic(count=100), end])
        self.assertEqual([a.step for a in p.iter_actions()], [0,10,20,25])
        self.assertTrue(tuple(p.iter_actions())[-1].blocks_following_events)
        self.assertFalse(tuple(p.iter_actions())[-1].execution_ready)
        self.rejects('RESOURCE', lambda:self.compile([end, send(step=26)]))

    def test_large_finite_streams_are_not_expanded_and_output_limit_fails_before_yield(self):
        p = self.compile([periodic(mid=7, period=1,count=1000000),
                          wave_event(at_step=0,duration_steps=86400000,sample_period_steps=1)])
        self.assertEqual(p.stream_count, 2)
        self.assertEqual(p.action_count, 87400001)
        iterator = p.iter_actions(max_actions=2)
        self.rejects('CAPACITY', lambda:next(iterator))
        actions = tuple(p.iter_actions(start_step=999998,end_step=999999,max_actions=4))
        self.assertEqual(len(actions), 4)

    def test_strict_models_timing_counts_and_uint32_overflow(self):
        for model in (None, True, 3, '', 'hexacopter_hil'):
            self.rejects('MODEL',lambda:self.compile([send()],model=model))
        for kw in ({'at_step':100.0},{'priority':100.0},{'at_step':True}):
            self.rejects('SCHEMA',lambda:self.compile([send(**kw)]))
        for kw in ({'period':10.0},{'count':10.0},{'count':True}):
            self.rejects('SCHEMA',lambda:self.compile([periodic(**kw)]))
        self.rejects('RANGE',lambda:self.compile([periodic(step=0xffffffff, count=2)]))
        p = self.compile([send()])
        for kw in ({'start_step':True},{'end_step':100.0},{'max_actions':0},{'start_step':20,'end_step':10}):
            self.rejects('SCHEMA' if 'max_actions' not in kw else 'CAPACITY',lambda:tuple(p.iter_actions(**kw)))

    def test_duplicate_namespaces_prior_stop_link_and_fault_restrictions(self):
        self.rejects('RESOURCE',lambda:self.compile([send(),send()]))
        self.rejects('RESOURCE',lambda:self.compile([periodic(),periodic(name='other',sender_id='period-01',step=101)]))
        self.rejects('RESOURCE',lambda:self.compile([stop(),periodic(step=100)]))
        self.rejects('RESOURCE',lambda:self.compile([periodic(),stop(link_id='CUTIL')]))
        self.rejects('RESOURCE',lambda:self.compile([periodic(),stop(),stop(step=60,event_id='stop-02')]))
        self.rejects('RESOURCE',lambda:self.compile([send(type='FAULT')]))
        assertion = source_inputs()['scenario']['assertions'][0]
        self.rejects('RESOURCE',lambda:self.compile([{'event_id':'wait','at_step':0,'priority':100,
                      'link_id':'ETHGEN','type':'WAIT','assertion':assertion}]))

    def test_replay_reference_negative_case_and_unresolved_consumers_are_explicit(self):
        history, _ = history_input()
        replay = {'event_id':'r','at_step':0,'priority':100,'link_id':'ETHREPLAY','type':'REPLAY',
                  'history_id':'capture-01','policy':history['history']['policy']}
        self.rejects('RESOURCE',lambda:self.compile([replay]))
        self.rejects('RESOURCE',lambda:self.compile([replay],history_id='wrong'))
        p = self.compile([replay],history_id='capture-01')
        self.assertIn('REPLAY_WRITABLE_TARGETS_AND_EXPANSION', p.pending_checks)
        negative = send(type='NEGATIVE_SEND',mutation={'kind':'CRC_XOR','xor_mask':1},expected_error='CRC',
                        must_not_apply=True,authorization_case_id='T01')
        self.rejects('AUTHORIZATION',lambda:self.compile([negative]))
        for mid in (24,26,45):
            p = self.compile([send(mid=mid)])
            self.assertIn(f'WRITABLE_TARGETS:{mid}',p.pending_checks)
            self.assertEqual(next(p.iter_actions()).writable_targets, ())
            self.assertFalse(p.execution_ready)

    def test_complete_snapshot_collision_across_original_tools_and_alias_messages(self):
        self.rejects('RESOURCE',lambda:self.compile([send('a'),send('b',link_id='CUTIL')]))
        self.rejects('RESOURCE',lambda:self.compile([send('a',mid=7),send('b',mid=14,link_id='CANT')]))
        self.compile([send('a',mid=10),send('b',mid=11)])

    def test_two_waveforms_different_changed_fields_still_write_full_same_ports(self):
        self.rejects('RESOURCE',lambda:self.compile([wave_event(event_id='a',field='wind_n_mps'),
                         wave_event(event_id='b',field='wind_e_mps',link_id='CUTIL')]))

    def test_periodic_collision_with_static_and_later_coprime_intersection(self):
        self.rejects('RESOURCE',lambda:self.compile([periodic(),send('later',30)]))
        self.rejects('RESOURCE',lambda:self.compile([periodic('a',period=97,count=1000),
                                                    periodic('b',step=1,period=101,count=1000)]))
        p = self.compile([periodic('a',period=10),periodic('b',step=1,period=10)])
        self.assertEqual(p.action_count, 20)

    def test_terminal_waveform_sample_collision_and_stop_clipping_are_not_missed(self):
        self.rejects('RESOURCE',lambda:self.compile([wave_event(at_step=0,duration_steps=25,sample_period_steps=20),
                                                    send('last',25)]))
        p = self.compile([periodic('a',period=10,count=100),stop('a',step=25),send('safe',30)])
        self.assertEqual([a.step for a in p.iter_actions()], [0,10,20,25,30])

    def test_collision_budget_does_not_silently_ignore_long_overlapping_streams(self):
        events = [periodic('a',period=10,count=100),periodic('b',step=1,period=10,count=100),
                  periodic('c',step=2,period=10,count=100)]
        self.rejects('CAPACITY',lambda:self.compile(events,max_collision_checks=1))
        self.compile(events,max_collision_checks=3)

    def test_arrays_all_elements_and_boolean_targets_count_for_complete_snapshot(self):
        for model,mid in (('quadrotor_hil',7),('multirotor_6_hil',8),('fixed_wing_hil',9)):
            p = self.compile([send(mid=mid)],model=model)
            targets = next(p.iter_actions()).writable_targets
            self.assertEqual(len(targets), 6 if mid == 8 else 4)
        self.assertEqual(len(next(self.compile([send(mid=11)]).iter_actions()).writable_targets), 13)

    def test_source_audit_exposes_plan_and_rejects_real_complete_snapshot_collision(self):
        value = source_inputs()
        value['scenario'] = scenario([periodic(mid=7),send('env',30)])
        result = SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil')
        self.assertTrue(hasattr(result,'scenario_plan'),'audit must expose compiled scenario plan')
        self.assertIsNotNone(result.scenario_plan)
        self.assertTrue(result.report()['scenario_compiled'])
        self.assertFalse(result.execution_ready)
        value['scenario']['events'] = [send('a'),send('b',link_id='CUTIL')]
        self.rejects('RESOURCE',lambda:SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil'))

    def test_all_97_frozen_bindings_and_105_elements_resolve_to_complete_actual_fields(self):
        targets = set()
        for model, mids in (('quadrotor_hil',(7,10,11,14,17)),
                            ('multirotor_6_hil',(8,10,12,15,18)),
                            ('fixed_wing_hil',(9,10,13,16,19))):
            p = self.compile([send(str(mid),index,mid) for index,mid in enumerate(mids)],model=model)
            for action in p.iter_actions():
                targets.update(action.writable_targets)
        expected = set()
        for row in self.contract.catalogue['model_bindings']:
            root = row['model_id'] + '.' + row['target_field']
            expected.update({root} if row['dimension'] == 1 else
                            {root + f'[{i}]' for i in range(row['dimension'])})
        self.assertEqual(targets,expected)
        self.assertEqual(len(targets),105)

    def test_arithmetic_intersection_matches_small_enumerated_progressions(self):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.scenario'))
        from input_simulator.scenario import _Stream, _intersection
        streams = [_Stream(a,p,n,0,'test',b'{}',()) for a in range(7) for p in range(1,8) for n in range(1,5)]
        for a in streams:
            left = {a.first+i*a.period for i in range(a.count)}
            for b in streams:
                common = left & {b.first+i*b.period for i in range(b.count)}
                self.assertEqual(_intersection(a,b),min(common) if common else None)

    def test_negative_mutation_integer_fields_do_not_accept_float_or_bool(self):
        for mutation in ({'kind':'CRC_XOR','xor_mask':1.0},
                         {'kind':'SEQUENCE_OVERRIDE','sequence':1.0},
                         {'kind':'SESSION_OVERRIDE','session_id':1.0},
                         {'kind':'TARGET_STEP_OVERRIDE','target_step':100.0},
                         {'kind':'TRUNCATE','remove_tail_bytes':1.0}):
            negative = send(type='NEGATIVE_SEND',mutation=mutation,expected_error='CRC',
                            must_not_apply=True,authorization_case_id='T02')
            self.rejects('SCHEMA',lambda:self.compile([negative]))

    def test_all_snapshot_storage_counts_and_unverified_contract_rejects(self):
        from icd_runtime.contract import Contract
        from icd_runtime.json_codec import canonicalize
        from input_simulator.scenario import ScenarioPlan, _snapshot
        value = scenario([send()])
        total = len(_snapshot(value)) + len(canonicalize(value)) + len(_snapshot(value['events'][0]))
        total += sum(len(_snapshot(a)) for a in value['assertions'])
        with patch('input_simulator.scenario.MAX_PLAN_BYTES',total-1):
            self.rejects('CAPACITY',lambda:ScenarioPlan.compile(self.contract,value,model_id='quadrotor_hil'))
        with patch('input_simulator.scenario.MAX_PLAN_BYTES',total):
            ScenarioPlan.compile(self.contract,value,model_id='quadrotor_hil')
        unverified = Contract(self.contract._schema,self.contract.catalogue,self.contract.baseline_sha256)
        self.rejects('HASH',lambda:ScenarioPlan.compile(unverified,value,model_id='quadrotor_hil'))


if __name__ == '__main__':
    unittest.main()
