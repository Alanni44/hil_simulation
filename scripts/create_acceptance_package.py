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
contract = {'contract_version': 1, 'model_name': model,
            'state': {'frame': 'NED', 'orientation': 'FRD_TO_NED_QUATERNION',
                      'outputs': {name: name for name in fields}, 'units': units},
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
