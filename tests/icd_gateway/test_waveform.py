import copy
import importlib.util
import math
import unittest

from common import GatewayTest, message
from input_simulator.source_inputs import SourceInputAuditor
from test_source_inputs import resources, source_inputs


def event(waveform=None, *, mid=10, field='wind_n_mps', **changes):
    return {'event_id': 'wave-01', 'at_step': 100, 'priority': 100,
            'link_id': 'ETHGEN', 'type': 'WAVEFORM',
            'stimulus': {'message_id': mid, 'payload': message(mid)['payload']},
            'field_path': field, 'duration_steps': 1000, 'sample_period_steps': 20,
            'waveform': {'kind': 'CONSTANT', 'value': 2} if waveform is None else waveform,
            **changes}


class WaveformTests(GatewayTest):
    def compile(self, value=None, *, model='quadrotor_hil'):
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.waveform'), 'frozen waveform sampler missing')
        from input_simulator.waveform import WaveformSampler
        return WaveformSampler.compile(self.contract, event() if value is None else value, model_id=model)

    def test_constant_is_complete_detached_stimulus_with_no_header_or_execution_claim(self):
        e = event()
        p = self.compile(e)
        e['stimulus']['payload'].clear()
        sample = p.sample(100)
        self.assertEqual(set(sample), {'message_id', 'payload'})
        self.assertEqual(sample['payload']['wind_n_mps'], 2)
        self.assertEqual(len(sample['payload']), 6)
        sample['payload'].clear()
        self.assertEqual(len(p.sample(101)['payload']), 6)
        self.assertEqual(p.unit, 'm/s')
        self.assertEqual(p.target_path, 'environment.wind_n_mps')
        self.assertFalse(p.execution_ready)

    def test_relative_step_changes_at_elapsed_boundary_and_holds_end(self):
        p = self.compile(event({'kind': 'STEP', 'before': -2, 'after': 3, 'change_step': 20}))
        self.assertEqual([p.sample(s)['payload']['wind_n_mps'] for s in (100,119,120,1101)], [-2,-2,3,3])
        self.rejects('STATE', lambda: p.sample(99))

    def test_ramp_linear_formula_internal_and_outer_end_hold(self):
        wave = {'kind': 'RAMP', 'start_value': 0, 'end_value': 10, 'duration_steps': 100}
        p = self.compile(event(wave))
        self.assertEqual([p.sample(s)['payload']['wind_n_mps'] for s in (100,150,200,1200)], [0,5,10,10])
        short = self.compile(event(wave, duration_steps=50))
        self.assertEqual(short.sample(200)['payload']['wind_n_mps'], 5)

    def test_sine_and_ascending_descending_chirp_use_frozen_phase_formula(self):
        p = self.compile(event({'kind': 'SINE', 'offset': 2, 'amplitude': 3, 'frequency_hz': 1, 'phase_rad': 0}))
        self.assertAlmostEqual(p.sample(350)['payload']['wind_n_mps'], 5)
        for f0, f1 in ((1,3),(3,1)):
            w = {'kind': 'CHIRP', 'offset': 2, 'amplitude': 3, 'start_frequency_hz': f0,
                 'end_frequency_hz': f1, 'duration_steps': 1000, 'phase_rad': 0.3}
            p = self.compile(event(w))
            t = 0.25
            expected = 2 + 3*math.sin(2*math.pi*(f0*t+(f1-f0)*t*t/2)+0.3)
            self.assertAlmostEqual(p.sample(350)['payload']['wind_n_mps'], expected)
            self.assertEqual(p.sample(1100), p.sample(1200))

    def test_peak_between_samples_is_rejected_and_valid_short_interval_is_not(self):
        w = {'kind': 'SINE', 'offset': 49, 'amplitude': 2, 'frequency_hz': 1, 'phase_rad': 0}
        self.rejects('RANGE', lambda: self.compile(event(w)))
        p = self.compile(event(w, duration_steps=10))
        self.assertLess(p.sample(110)['payload']['wind_n_mps'], 50)
        w['phase_rad'] = math.pi/2
        self.rejects('RANGE', lambda: self.compile(event(w, duration_steps=10)))

    def test_ten_times_sampling_boundary_both_chirp_ends_and_long_wave_no_expansion(self):
        sine = {'kind': 'SINE', 'offset': 0, 'amplitude': 1, 'frequency_hz': 5, 'phase_rad': 0}
        self.compile(event(sine, sample_period_steps=20))
        self.rejects('RANGE', lambda: self.compile(event(sine, sample_period_steps=21)))
        for f0,f1 in ((1,50),(50,1)):
            chirp = {'kind':'CHIRP', 'offset':0, 'amplitude':1, 'start_frequency_hz':f0,
                     'end_frequency_hz':f1, 'duration_steps':1000, 'phase_rad':0}
            self.compile(event(chirp, sample_period_steps=2))
            self.rejects('RANGE', lambda:self.compile(event(chirp,sample_period_steps=3)))
        p = self.compile(event(duration_steps=86400000,sample_period_steps=1))
        self.assertEqual(p.sample(86400100)['payload']['wind_n_mps'], 2)

    def test_fixed_array_explicit_index_all_models_and_no_mutable_alias(self):
        for mid,model,index in ((7,'quadrotor_hil',3),(8,'multirotor_6_hil',5),(9,'fixed_wing_hil',None)):
            field = 'throttle' if index is None else f'motor_command[{index}]'
            p = self.compile(event({'kind':'CONSTANT','value':0.5},mid=mid,field=field),model=model)
            result = p.sample(100)['payload']
            self.assertEqual(result['throttle'] if index is None else result['motor_command'][index], 0.5)
        for field in ('motor_command','motor_command[4]','motor_command[-1]','motor_command[00]',
                      'motor_command[0].x','payload.motor_command[0]'):
            self.rejects('SCHEMA',lambda:self.compile(event(mid=7,field=field)))

    def test_unregistered_bool_feedback_wrong_model_and_bad_event_types_rejected(self):
        for field in ('missing','environment.wind_n_mps','state.x','wind_n_mps[0]'):
            self.rejects('SCHEMA',lambda:self.compile(event(field=field)))
        self.rejects('SCHEMA',lambda:self.compile(event(mid=11,field='motor_1_failed')))
        self.rejects('TARGET_MISSING',lambda:self.compile(event(mid=26,field='imu_stale_ms')))
        self.rejects('MODEL',lambda:self.compile(event(mid=8,field='motor_command[0]')))
        self.rejects('SCHEMA',lambda:self.compile(event(type='SEND')))
        self.rejects('SCHEMA',lambda:self.compile(event(stimulus={'message_id':10.0,'payload':message(10)['payload']})))

    def test_strict_steps_end_overflow_and_packed_signed_zero_preserved(self):
        p = self.compile(event({'kind':'CONSTANT','value':-0.0}))
        self.assertEqual(math.copysign(1,p.sample(100)['payload']['wind_n_mps']),-1)
        for step in (True,100.0,-1,0x100000000):
            self.rejects('SCHEMA',lambda:p.sample(step))
        for kw in ({'at_step':100.0},{'duration_steps':1000.0},{'sample_period_steps':20.0}):
            self.rejects('SCHEMA',lambda:self.compile(event(**kw)))
        self.rejects('RANGE',lambda:self.compile(event(at_step=0xffffffff,duration_steps=1)))

    def test_source_audit_enforces_wave_semantics_and_exposes_all_samplers(self):
        value = source_inputs()
        value['scenario']['events'] = [event(), event(event_id='wave-02',at_step=1200,field='wind_e_mps')]
        result = SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil')
        self.assertTrue(hasattr(result,'waveforms'),'audit must expose compiled frozen waveform samplers')
        self.assertEqual(len(result.waveforms),2)
        self.assertFalse(result.execution_ready)
        bad = copy.deepcopy(value)
        bad['scenario']['events'][0]['field_path'] = 'missing'
        self.rejects('SCHEMA',lambda:SourceInputAuditor(self.contract).audit(bad,resources(),model_id='quadrotor_hil'))

    def test_source_audit_preserves_original_number_types_and_negative_zero(self):
        value = source_inputs()
        value['scenario']['events'] = [event({'kind':'CONSTANT','value':-0.0})]
        result = SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil')
        self.assertEqual(math.copysign(1,result.input_document['scenario']['events'][0]['waveform']['value']),-1)
        for mid in (10.0,True):
            value['scenario']['events'][0]['stimulus']['message_id'] = mid
            self.rejects('SCHEMA',lambda:SourceInputAuditor(self.contract).audit(value,resources(),model_id='quadrotor_hil'))

    def test_direct_sampler_requires_explicit_frozen_model_identity(self):
        for model in (None, True, 7, '', 'unknown'):
            self.rejects('MODEL',lambda:self.compile(model=model))

    def test_ramp_explicit_endpoint_negative_zero_is_not_recomputed_positive(self):
        p = self.compile(event({'kind':'RAMP','start_value':-0.0,'end_value':1,'duration_steps':10}))
        self.assertEqual(math.copysign(1,p.sample(100)['payload']['wind_n_mps']),-1)
        p = self.compile(event({'kind':'RAMP','start_value':1,'end_value':-0.0,'duration_steps':10}))
        self.assertEqual(math.copysign(1,p.sample(110)['payload']['wind_n_mps']),-1)
        self.assertEqual(math.copysign(1,p.sample(1000)['payload']['wind_n_mps']),-1)

    def test_all_registered_numeric_bindings_and_array_elements_are_sampled(self):
        model_mids = {'quadrotor_hil':(7,10,11,17), 'multirotor_6_hil':(8,10,12,18), 'fixed_wing_hil':(9,10,13,19)}
        count = 0
        for row in self.contract.catalogue['model_bindings']:
            if row['type'] != 'double':
                continue
            group,name = row['path'].split('.')
            mid = model_mids[row['model_id']][('flight_control','environment','fault','parameters').index(group)]
            for index in (range(row['dimension']) if row['dimension'] > 1 else (None,)):
                field = name if index is None else f'{name}[{index}]'
                value = (row['min']+row['max'])/2
                p = self.compile(event({'kind':'CONSTANT','value':value},mid=mid,field=field),model=row['model_id'])
                sample = p.sample(100)
                self.contract.validate_stimulus(sample,model_id=row['model_id'])
                self.assertEqual(sample['payload'][name] if index is None else sample['payload'][name][index],value)
                self.assertEqual(p.unit,row['unit'])
                count += 1
        self.assertGreater(count,80)


if __name__ == '__main__':
    unittest.main()
