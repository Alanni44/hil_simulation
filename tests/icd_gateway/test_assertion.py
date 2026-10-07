import copy
from dataclasses import FrozenInstanceError
import importlib.util
import math
import unittest

from common import GatewayTest
from input_simulator.source_inputs import SourceInputAuditor
from test_source_inputs import resources, source_inputs


def definition(**changes):
    return {**source_inputs()['scenario']['assertions'][0], **changes}


class AssertionTests(GatewayTest):
    def compile(self, value=None, *, model='quadrotor_hil'):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.assertion'), 'common assertion comparison missing')
        from input_simulator.assertion import AssertionSpec
        return AssertionSpec.compile(self.contract, definition() if value is None else value, model_id=model)

    def window(self, value=None, *, start=100, mode='ASSERT', **limits):
        spec = self.compile(value)
        from input_simulator.assertion import AssertionWindow
        return AssertionWindow(spec,start_step=start,mode=mode,**limits)

    def test_all_eight_numeric_operators_use_frozen_mathematical_meanings(self):
        for op, yes, no in (('EQ',1,1.0001),('NE',2,1),('LT',0,1),('LE',1,2),
                            ('GT',2,1),('GE',1,0),('WITHIN',1.125,1.25),('EVENTUALLY',1.125,1.25)):
            p = self.compile(definition(operator=op,expected=1,tolerance=0.125))
            self.assertTrue(p.compare(yes),op)
            self.assertFalse(p.compare(no),op)
            self.assertFalse(p.execution_ready)
        p = self.compile(definition(operator='EQ',expected=1,tolerance=1))
        self.assertFalse(p.compare(1.01))

    def test_bool_string_exact_type_and_no_order_or_tolerance(self):
        for expected,probe,mid,path in ((True,'consumer.Status',131,'safety_active'),
                                       ('RECEIVED','consumer.Ack',130,'stage')):
            for op in ('EQ','NE','EVENTUALLY'):
                p = self.compile(definition(probe_id=probe,message_id=mid,field_path=path,stage='E1',
                                            expected=expected,operator=op,tolerance=0))
                self.assertEqual(p.compare(expected),op != 'NE')
            self.rejects('RESOURCE',lambda:self.compile(definition(probe_id=probe,message_id=mid,field_path=path,
                                     expected=expected,operator='GT',tolerance=0)))
            self.rejects('RESOURCE',lambda:self.compile(definition(probe_id=probe,message_id=mid,field_path=path,
                                     expected=expected,tolerance=1)))
        p = self.compile(definition(probe_id='consumer.Status',message_id=131,field_path='safety_active',
                                    expected=True,operator='EQ',tolerance=0))
        self.rejects('SCHEMA',lambda:p.compare(1))

    def test_numeric_observations_reject_bool_nonfinite_containers_and_strings(self):
        p = self.compile()
        for value in (True,float('nan'),float('inf'),-float('inf'),None,[],{},'1'):
            self.rejects('SCHEMA',lambda:p.compare(value))

    def test_frozen_probe_model_target_array_index_and_expected_type(self):
        for model in (None,True,'bad'):
            self.rejects('MODEL',lambda:self.compile(model=model))
        self.rejects('MODEL',lambda:self.compile(definition(probe_id='fixed_wing_hil.input.environment.wind_n_mps')))
        for path in ('environment.wind_e_mps','environment.wind_n_mps[0]','payload.environment.wind_n_mps'):
            self.rejects('SCHEMA',lambda:self.compile(definition(field_path=path)))
        self.rejects('SCHEMA',lambda:self.compile(definition(expected=True,operator='EQ',tolerance=0)))
        self.rejects('TARGET_MISSING',lambda:self.compile(definition(probe_id='NO_PROBE')))
        self.rejects('SCHEMA',lambda:self.compile(definition(probe_id='consumer.Ack')))
        base = definition(probe_id='quadrotor_hil.input.flight_control.motor_command',message_id=7,
                          field_path='flight_control.motor_command[3]',expected=0.5)
        self.compile(base)
        for field in ('flight_control.motor_command','flight_control.motor_command[4]',
                      'flight_control.motor_command[03]','flight_control.motor_command[-1]'):
            self.rejects('SCHEMA',lambda:self.compile({**base,'field_path':field}))

    def test_all_97_registered_probe_bindings_cover_105_scalar_array_values(self):
        count = 0
        catalog = self.contract.catalogue
        mids = {'quadrotor_hil':{'flight_control':7,'fault':11,'parameters':17},
                'multirotor_6_hil':{'flight_control':8,'fault':12,'parameters':18},
                'fixed_wing_hil':{'flight_control':9,'fault':13,'parameters':19}}
        for row in catalog['model_bindings']:
            model = row['model_id']
            probe = next(p for p in catalog['probe_catalog'] if p.get('model_id') == model and p.get('target') == row['path'])
            mid = 10 if row['path'].startswith('environment.') else mids[model][row['path'].split('.')[0]]
            for i in range(row['dimension']):
                field = row['path'] if row['dimension'] == 1 else row['path']+f'[{i}]'
                expected = False if row['type'] == 'bool' else 0
                p = self.compile(definition(message_id=mid,probe_id=probe['name'],field_path=field,
                                            operator='EQ',expected=expected,tolerance=0),model=model)
                self.assertTrue(p.compare(expected))
                count += 1
        self.assertEqual(count,105)

    def test_spec_snapshot_is_detached_and_preserves_signed_zero(self):
        d = definition(expected=-0.0)
        p = self.compile(d)
        d.clear()
        self.assertEqual(math.copysign(1,p.assertion['expected']),-1)
        p.assertion.clear()
        self.assertTrue(p.compare(-0.0))
        with self.assertRaises(FrozenInstanceError):
            p.model_id = 'bad'

    def test_assert_ordinary_mismatch_is_terminal_and_success_needs_all_samples(self):
        w = self.window(definition(operator='EQ',sample_count=2))
        w.observe(model_step=100,sample_sequence=1,value=1)
        self.assertEqual(w.status,'PENDING')
        w.observe(model_step=101,sample_sequence=2,value=1)
        self.assertEqual(w.status,'MATCHED')
        self.assertEqual(w.evidence_status,'NOT_EVALUATED')
        self.assertFalse(w.execution_ready)
        self.rejects('STATE',lambda:w.observe(model_step=102,sample_sequence=3,value=0))
        bad = self.window(definition(operator='EQ',sample_count=2))
        bad.observe(model_step=100,sample_sequence=1,value=0)
        self.assertEqual(bad.status,'MISMATCH')

    def test_eventually_and_wait_reset_consecutive_samples_and_do_not_freeze_model(self):
        for mode,op in (('ASSERT','EVENTUALLY'),('WAIT','EQ')):
            w = self.window(definition(operator=op,sample_count=2,tolerance=0),mode=mode)
            for seq,(step,value) in enumerate(((100,1),(101,0),(102,1),(103,1)),1):
                w.observe(model_step=step,sample_sequence=seq,value=value)
            self.assertEqual(w.status,'MATCHED')
            self.assertEqual(w.consecutive_count,2)
            self.assertEqual(len(w.records),4)

    def test_half_open_timeout_empty_window_and_uint32_overflow(self):
        w = self.window(definition(timeout_steps=2),mode='WAIT')
        w.observe(model_step=101,sample_sequence=1,value=0)
        w.poll(model_step=102)
        self.assertEqual(w.status,'TIMED_OUT')
        empty = self.window(definition(timeout_steps=2))
        empty.poll(model_step=102)
        self.assertEqual(empty.status,'TIMED_OUT')
        self.assertEqual(empty.evidence_status,'NOT_EVALUATED')
        self.rejects('RANGE',lambda:self.window(start=0xffffffff))
        self.rejects('STATE',lambda:self.window().observe(model_step=99,sample_sequence=1,value=1))

    def test_duplicate_sequence_backward_step_and_poll_cannot_create_samples(self):
        w = self.window(definition(sample_count=3))
        w.observe(model_step=100,sample_sequence=10,value=1)
        for seq in (10,9):
            self.rejects('DUPLICATE',lambda:w.observe(model_step=100,sample_sequence=seq,value=1))
        self.rejects('SCHEMA',lambda:w.observe(model_step=99,sample_sequence=11,value=1))
        w.poll(model_step=101)
        self.assertEqual(w.consecutive_count,1)
        self.rejects('SCHEMA',lambda:w.observe(model_step=100,sample_sequence=11,value=1))
        w.observe(model_step=101,sample_sequence=11,value=1)
        w.observe(model_step=101,sample_sequence=12,value=1)
        self.assertEqual(w.status,'MATCHED')

    def test_bounded_records_preflight_and_drain_do_not_reset_highwater_or_state(self):
        w = self.window(definition(sample_count=3),max_records=1)
        w.observe(model_step=100,sample_sequence=1,value=1)
        self.rejects('BUFFER_FULL',lambda:w.observe(model_step=101,sample_sequence=2,value=1))
        self.assertEqual(w.consecutive_count,1)
        records = w.drain_records()
        self.assertEqual(len(records),1)
        self.assertEqual(records[0].value,1)
        self.rejects('DUPLICATE',lambda:w.observe(model_step=100,sample_sequence=1,value=1))
        w.observe(model_step=101,sample_sequence=2,value=1)
        w.drain_records()
        w.observe(model_step=102,sample_sequence=3,value=1)
        w.drain_records()
        self.assertEqual(w.status,'MATCHED')

    def test_strict_timing_count_constructor_and_observation_types(self):
        for changes in ({'message_id':10.0},{'timeout_steps':100.0},{'sample_count':1.0}):
            self.rejects('SCHEMA',lambda:self.compile(definition(**changes)))
        for kw in ({'start':True},{'start':100.0},{'mode':'bad'}):
            self.rejects('SCHEMA',lambda:self.window(**kw))
        for kw in ({'max_records':0},{'max_records':True},{'max_bytes':0},{'max_bytes':1.0}):
            self.rejects('CAPACITY',lambda:self.window(**kw))
        for step,seq in ((True,1),(100.0,1),(100,True),(100,1.0),(100,0)):
            w = self.window()
            self.rejects('SCHEMA',lambda:w.observe(model_step=step,sample_sequence=seq,value=1))

    def test_original_observation_bytes_and_capacity_failure_preserve_state(self):
        w = self.window(definition(expected=-0.0,operator='EVENTUALLY',sample_count=2))
        w.observe(model_step=100,sample_sequence=1,value=-0.0)
        r = w.records[0]
        self.assertEqual(math.copysign(1,r.value),-1)
        with self.assertRaises(FrozenInstanceError):
            r.sample_sequence = 2
        tiny = self.window(definition(sample_count=2),max_bytes=1)
        self.rejects('BUFFER_FULL',lambda:tiny.observe(model_step=100,sample_sequence=1,value=1))
        self.assertEqual(tiny.records,())
        self.assertEqual(tiny.consecutive_count,0)

    def test_all_scene_root_wait_assert_specs_compiled_and_bad_probe_path_rejected(self):
        value = source_inputs()
        root = value['scenario']['assertions'][0]
        value['scenario']['events'] = [{'event_id':'wait','at_step':1,'priority':100,'link_id':'ETHGEN','type':'WAIT',
                     'assertion':{**root,'assertion_id':'wait-assert'}},
                    {'event_id':'assert','at_step':2,'priority':100,'link_id':'ETHGEN','type':'ASSERT',
                     'assertion':{**root,'assertion_id':'event-assert'}}]
        a = SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil')
        self.assertTrue(hasattr(a.scenario_plan,'assertions'),'compiled scenario assertions missing')
        self.assertEqual(len(a.scenario_plan.assertions),3)
        self.assertEqual(a.report()['compiled_assertion_count'],3)
        self.assertFalse(a.execution_ready)
        value['scenario']['assertions'][0]['field_path'] = 'environment.wind_e_mps'
        self.rejects('SCHEMA',lambda:SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil'))

    def test_window_rule_mode_and_deadline_cannot_be_reassigned(self):
        w = self.window()
        for name,value in (('spec',self.compile()),('mode','WAIT'),('start_step',0),('deadline_step',0xffffffff)):
            with self.assertRaises(AttributeError):
                setattr(w,name,value)

    def test_deadline_observation_is_not_counted_or_recorded(self):
        w = self.window(definition(timeout_steps=2),mode='WAIT')
        self.assertEqual(w.observe(model_step=102,sample_sequence=1,value=1),'TIMED_OUT')
        self.assertEqual(w.records,())
        self.assertEqual(w.consecutive_count,0)
        self.assertEqual(w.evidence_status,'NOT_EVALUATED')


if __name__ == '__main__':
    unittest.main()
