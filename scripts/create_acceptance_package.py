#!/usr/bin/env python3
"""Create a manifest for the explicit-contract acceptance test package."""
from __future__ import print_function
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python_services'))
from shared.model_package import package_sha256  # noqa

package = os.path.abspath(sys.argv[1])
model = 'hil_test_model'
fields = ('north_m east_m down_m vn_mps ve_mps vd_mps q_w q_x q_y q_z '
          'p_radps q_radps r_radps airborne').split()
units = dict(zip(fields, ('m m m m/s m/s m/s 1 1 1 1 rad/s rad/s rad/s bool').split()))


def descriptor(field, unit, value_type='double', minimum=-1000000.0, maximum=1000000.0):
    return {'field': field, 'unit': unit, 'type': value_type, 'dimension': 1,
            'min': minimum, 'max': maximum}


inputs = {
    'flight_control': {'mode': 'axis_command', 'ports': {
        'throttle': descriptor('throttle', '1', minimum=-1.0, maximum=1.0),
        'roll_cmd': descriptor('roll_cmd', '1', minimum=-1.0, maximum=1.0),
        'pitch_cmd': descriptor('pitch_cmd', '1', minimum=-1.0, maximum=1.0),
        'yaw_cmd': descriptor('yaw_cmd', '1', minimum=-1.0, maximum=1.0)}},
    'environment': {'ports': {
        'wind_n_mps': descriptor('wind_n_mps', 'm/s'),
        'wind_e_mps': descriptor('wind_e_mps', 'm/s'),
        'wind_d_mps': descriptor('wind_d_mps', 'm/s'),
        'pressure_pa': descriptor('pressure_pa', 'Pa', minimum=1000.0, maximum=120000.0),
        'temperature_k': descriptor('temperature_k', 'K', minimum=100.0, maximum=400.0),
        'ground_height_m': descriptor('ground_height_m', 'm')}},
    'fault': {'ports': {
        'gps_bias_n_m': descriptor('gps_bias_n_m', 'm'),
        'gps_bias_e_m': descriptor('gps_bias_e_m', 'm'),
        'gps_bias_d_m': descriptor('gps_bias_d_m', 'm'),
        'imu_bias_p_radps': descriptor('imu_bias_p_radps', 'rad/s'),
        'imu_bias_q_radps': descriptor('imu_bias_q_radps', 'rad/s'),
        'imu_bias_r_radps': descriptor('imu_bias_r_radps', 'rad/s'),
        'motor_1_failed': descriptor('motor_1_failed', 'bool', 'bool', 0.0, 1.0),
        'motor_2_failed': descriptor('motor_2_failed', 'bool', 'bool', 0.0, 1.0),
        'motor_3_failed': descriptor('motor_3_failed', 'bool', 'bool', 0.0, 1.0),
        'motor_4_failed': descriptor('motor_4_failed', 'bool', 'bool', 0.0, 1.0),
        'command_delay_ms': descriptor('command_delay_ms', 'ms', minimum=0.0, maximum=1000.0),
        'sensor_delay_ms': descriptor('sensor_delay_ms', 'ms', minimum=0.0, maximum=1000.0),
        'packet_loss_ratio': descriptor('packet_loss_ratio', '1', minimum=0.0, maximum=1.0)}}
}

contract = {'contract_version': 2, 'model_name': model,
            'state': {'frame': 'NED', 'orientation': 'FRD_TO_NED_QUATERNION',
                      'outputs': {name: name for name in fields}, 'units': units},
            'inputs': inputs,
            'outputs': {'ue4_state': {'rate_hz': 50, 'acceleration': {
                'ax_mps2': descriptor('ax_mps2', 'm/s2'),
                'ay_mps2': descriptor('ay_mps2', 'm/s2'),
                'az_mps2': descriptor('az_mps2', 'm/s2')}}},
            'execution': {'step_s': 0.001,
                          'locked_configuration': ['solver_step_s', 'model_topology',
                                                   'port_schema', 'communication_endpoint']},
            'parameters': [{'name': 'gain', 'generated_field': 'gain', 'type': 'double',
                            'unit': 'm/s', 'default': 1.0, 'min': 0.0, 'max': 5.0,
                            'class': 'live', 'allowed_phases': ['RUNNING', 'PAUSED'],
                            'binding': {'kind': 'extu', 'field': 'gain'}},
                           {'name': 'reset_gain', 'generated_field': 'reset_gain', 'type': 'double',
                            'unit': 'm/s', 'default': 0.0, 'min': 0.0, 'max': 5.0,
                            'class': 'reset_only', 'allowed_phases': ['PAUSED'],
                            'binding': {'kind': 'extu', 'field': 'reset_gain'}},
                           {'name': 'mass_kg', 'generated_field': 'mass_kg', 'type': 'double',
                            'unit': 'kg', 'default': 5.0, 'min': 0.1, 'max': 100.0,
                            'class': 'reset_only', 'allowed_phases': ['PAUSED'],
                            'binding': {'kind': 'exported_global', 'symbol': 'uav_mass_kg'}},
                           {'name': 'north_diagnostic', 'generated_field': 'north_m', 'type': 'double',
                            'unit': 'm', 'default': 0.0, 'min': -1000000.0, 'max': 1000000.0,
                            'class': 'readonly', 'allowed_phases': ['RUNNING', 'PAUSED', 'RESETTING', 'ENDED']}]} 
with open(os.path.join(package, 'hil_contract.json'), 'w') as output:
    json.dump(contract, output, indent=2, sort_keys=True); output.write('\n')
files = {}
for name in (model + '.slx', 'hil_contract.json'):
    with open(os.path.join(package, name), 'rb') as source:
        files[name] = hashlib.sha256(source.read()).hexdigest()
manifest = {'model_ref': 'acceptance-model', 'model_revision_ref': 'acceptance-r1',
            'top_model': model + '.slx', 'matlab_version': 'R2018b',
            'files': files, 'dependencies': [], 'package_sha256': package_sha256(package)}
with open(os.path.join(package, 'package_manifest.json'), 'w') as output:
    json.dump(manifest, output, indent=2, sort_keys=True); output.write('\n')
