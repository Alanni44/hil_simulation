import hashlib
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))
from shared.model_package import PackageError, package_sha256, validate_package  # noqa


FIELDS = ('north_m east_m down_m vn_mps ve_mps vd_mps q_w q_x q_y q_z '
          'p_radps q_radps r_radps airborne').split()
UNITS = dict(zip(FIELDS, ('m m m m/s m/s m/s 1 1 1 1 rad/s rad/s rad/s bool').split()))


class ModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, 'controlled')
        self.package = os.path.join(self.root, 'example')
        os.makedirs(self.package)
        with open(os.path.join(self.package, 'example.slx'), 'wb') as output:
            output.write(b'fixture slx')
        contract = {'contract_version': 1, 'model_name': 'example',
                    'state': {'frame': 'NED', 'orientation': 'FRD_TO_NED_QUATERNION',
                              'outputs': {field: field for field in FIELDS}, 'units': UNITS},
                    'parameters': [{'name': 'gain', 'generated_field': 'gain', 'type': 'double',
                                    'unit': '1', 'default': 1.0, 'min': 0.0, 'max': 10.0,
                                    'class': 'live', 'allowed_phases': ['RUNNING', 'PAUSED']}]}
        with open(os.path.join(self.package, 'hil_contract.json'), 'w') as out: json.dump(contract, out)
        self._write_manifest()

    def tearDown(self): self.temp.cleanup()

    def _write_manifest(self):
        files = {}
        for name in ('example.slx', 'hil_contract.json'):
            with open(os.path.join(self.package, name), 'rb') as source:
                files[name] = hashlib.sha256(source.read()).hexdigest()
        manifest = {'model_ref': 'external-42', 'model_revision_ref': 'rev-3', 'top_model': 'example.slx',
                    'matlab_version': 'R2018b', 'files': files, 'package_sha256': package_sha256(self.package)}
        with open(os.path.join(self.package, 'package_manifest.json'), 'w') as out: json.dump(manifest, out)

    def test_valid_local_package_has_explicit_verified_contract(self):
        result = validate_package(self.package, self.root, package_sha256(self.package))
        self.assertEqual('example', result['contract']['model_name'])
        self.assertEqual(64, len(result['contract_sha256']))

    def test_missing_attitude_speed_or_units_is_rejected(self):
        for field, remove_unit in (('q_z', False), ('vd_mps', False), ('north_m', True)):
            contract_path = os.path.join(self.package, 'hil_contract.json')
            with open(contract_path, 'r') as source:
                contract = json.load(source)
            if remove_unit: del contract['state']['units'][field]
            else: del contract['state']['outputs'][field]
            with open(contract_path, 'w') as out: json.dump(contract, out)
            self._write_manifest()
            with self.assertRaises(PackageError): validate_package(self.package, self.root)
            self.tearDown(); self.setUp()

    def test_outside_controlled_root_is_rejected(self):
        with self.assertRaises(PackageError): validate_package(self.package, os.path.join(self.temp.name, 'elsewhere'))


if __name__ == '__main__': unittest.main()
