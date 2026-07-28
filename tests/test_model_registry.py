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


def input_descriptor(field, unit, value_type='double', minimum=-1000.0,
                     maximum=1000.0):
    return {'field': field, 'unit': unit, 'type': value_type,
            'dimension': 1, 'min': minimum, 'max': maximum}


def required_inputs():
    return {
        'flight_control': {
            'mode': 'axis_command',
            'ports': {
                'throttle': input_descriptor('throttle', '1', minimum=-1.0, maximum=1.0),
                'roll_cmd': input_descriptor('roll_cmd', '1', minimum=-1.0, maximum=1.0),
                'pitch_cmd': input_descriptor('pitch_cmd', '1', minimum=-1.0, maximum=1.0),
                'yaw_cmd': input_descriptor('yaw_cmd', '1', minimum=-1.0, maximum=1.0),
            },
        },
        'environment': {'ports': {
            'wind_n_mps': input_descriptor('wind_n_mps', 'm/s'),
            'wind_e_mps': input_descriptor('wind_e_mps', 'm/s'),
            'wind_d_mps': input_descriptor('wind_d_mps', 'm/s'),
            'pressure_pa': input_descriptor('pressure_pa', 'Pa', minimum=1000.0, maximum=120000.0),
            'temperature_k': input_descriptor('temperature_k', 'K', minimum=100.0, maximum=400.0),
            'ground_height_m': input_descriptor('ground_height_m', 'm'),
        }},
        'fault': {'ports': {
            'gps_bias_n_m': input_descriptor('gps_bias_n_m', 'm'),
            'gps_bias_e_m': input_descriptor('gps_bias_e_m', 'm'),
            'gps_bias_d_m': input_descriptor('gps_bias_d_m', 'm'),
            'imu_bias_p_radps': input_descriptor('imu_bias_p_radps', 'rad/s'),
            'imu_bias_q_radps': input_descriptor('imu_bias_q_radps', 'rad/s'),
            'imu_bias_r_radps': input_descriptor('imu_bias_r_radps', 'rad/s'),
            'motor_1_failed': input_descriptor('motor_1_failed', 'bool', 'bool', 0.0, 1.0),
            'motor_2_failed': input_descriptor('motor_2_failed', 'bool', 'bool', 0.0, 1.0),
            'motor_3_failed': input_descriptor('motor_3_failed', 'bool', 'bool', 0.0, 1.0),
            'motor_4_failed': input_descriptor('motor_4_failed', 'bool', 'bool', 0.0, 1.0),
            'command_delay_ms': input_descriptor('command_delay_ms', 'ms', minimum=0.0, maximum=1000.0),
            'sensor_delay_ms': input_descriptor('sensor_delay_ms', 'ms', minimum=0.0, maximum=1000.0),
            'packet_loss_ratio': input_descriptor('packet_loss_ratio', '1', minimum=0.0, maximum=1.0),
        }},
    }


class ModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, 'controlled')
        self.package = os.path.join(self.root, 'example')
        os.makedirs(self.package)
        with open(os.path.join(self.package, 'example.slx'), 'wb') as output:
            output.write(b'fixture slx')
        contract = {'contract_version': 2, 'model_name': 'example',
                    'state': {'frame': 'NED', 'orientation': 'FRD_TO_NED_QUATERNION',
                              'outputs': {field: field for field in FIELDS}, 'units': UNITS},
                    'inputs': required_inputs(),
                    'outputs': {'internal_state': {
                        'rate_hz': 50, 'consumer': 'c_python_only',
                        'include_in_ue4_json': False,
                        'acceleration': {
                            'ax_mps2': input_descriptor('ax_mps2', 'm/s2'),
                            'ay_mps2': input_descriptor('ay_mps2', 'm/s2'),
                            'az_mps2': input_descriptor('az_mps2', 'm/s2')}}},
                    'execution': {'step_s': 0.001,
                                  'locked_configuration': ['solver_step_s', 'model_topology',
                                                           'port_schema', 'communication_endpoint']},
                    'parameters': [{'name': 'gain', 'generated_field': 'gain', 'type': 'double',
                                    'unit': '1', 'default': 1.0, 'min': 0.0, 'max': 10.0,
                                    'class': 'live', 'allowed_phases': ['RUNNING', 'PAUSED'],
                                    'binding': {'kind': 'extu', 'field': 'gain'}}]}
        with open(os.path.join(self.package, 'hil_contract.json'), 'w') as out: json.dump(contract, out)
        self._write_manifest()

    def tearDown(self): self.temp.cleanup()

    def _write_manifest(self):
        files = {}
        for name in ('example.slx', 'hil_contract.json'):
            with open(os.path.join(self.package, name), 'rb') as source:
                files[name] = hashlib.sha256(source.read()).hexdigest()
        manifest = {'model_ref': 'external-42', 'model_revision_ref': 'rev-3', 'top_model': 'example.slx',
                    'matlab_version': 'R2018b', 'files': files, 'dependencies': [],
                    'package_sha256': package_sha256(self.package)}
        with open(os.path.join(self.package, 'package_manifest.json'), 'w') as out: json.dump(manifest, out)

    def test_valid_local_package_has_explicit_verified_contract(self):
        result = validate_package(self.package, self.root, package_sha256(self.package))
        self.assertEqual('example', result['contract']['model_name'])
        self.assertEqual(64, len(result['contract_sha256']))

    def test_internal_acceleration_declaration_is_accepted(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        result = validate_package(self.package, self.root, package_sha256(self.package))
        self.assertEqual(50, result['contract']['outputs']['internal_state']['rate_hz'])

    def test_legacy_ue4_acceleration_declaration_is_rejected(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        with open(contract_path, 'r') as source:
            contract = json.load(source)
        contract['outputs']['ue4_state'] = contract['outputs'].pop('internal_state')
        with open(contract_path, 'w') as output:
            json.dump(contract, output)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root, package_sha256(self.package))

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

    def test_undeclared_payload_file_is_rejected(self):
        with open(os.path.join(self.package, 'dependencies.txt'), 'w') as output:
            output.write('not checksummed')
        with self.assertRaises(PackageError): validate_package(self.package, self.root)

    def test_parameter_default_outside_its_contract_range_is_rejected(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        with open(contract_path, 'r') as source:
            contract = json.load(source)
        contract['parameters'][0]['default'] = 11.0
        with open(contract_path, 'w') as out:
            json.dump(contract, out)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root)

    def test_declared_dependency_path_is_returned(self):
        dependency_dir = os.path.join(self.package, 'dependencies')
        os.makedirs(dependency_dir)
        dependency = os.path.join(dependency_dir, 'init_model.m')
        with open(dependency, 'w') as output:
            output.write('% fixture')
        manifest = json.load(open(os.path.join(self.package, 'package_manifest.json')))
        with open(dependency, 'rb') as source:
            manifest['files']['dependencies/init_model.m'] = hashlib.sha256(source.read()).hexdigest()
        manifest['dependencies'] = [{'path': 'dependencies/init_model.m', 'kind': 'init_script'}]
        manifest['package_sha256'] = package_sha256(self.package)
        with open(os.path.join(self.package, 'package_manifest.json'), 'w') as output:
            json.dump(manifest, output)
        self.assertEqual([dependency], validate_package(self.package, self.root)['dependency_paths'])

    def test_writable_parameter_rejects_unknown_binding(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        contract = json.load(open(contract_path))
        contract['parameters'][0]['binding'] = {'kind': 'p_struct_offset', 'field': 'gain'}
        with open(contract_path, 'w') as output:
            json.dump(contract, output)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root)

    def test_missing_required_environment_input_is_rejected(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        contract = json.load(open(contract_path))
        del contract['inputs']['environment']['ports']['wind_d_mps']
        with open(contract_path, 'w') as output:
            json.dump(contract, output)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root)

    def test_flight_control_modes_are_mutually_exclusive(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        contract = json.load(open(contract_path))
        contract['inputs']['flight_control']['ports']['motor_command'] = input_descriptor(
            'motor_command', '1', minimum=-1.0, maximum=1.0)
        with open(contract_path, 'w') as output:
            json.dump(contract, output)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root)

    def test_reset_only_parameter_requires_paused_phase(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        contract = json.load(open(contract_path))
        parameter = dict(contract['parameters'][0])
        parameter.update({'name': 'mass_kg', 'class': 'reset_only',
                          'allowed_phases': ['RUNNING'],
                          'binding': {'kind': 'exported_global', 'symbol': 'uav_mass_kg'}})
        contract['parameters'].append(parameter)
        with open(contract_path, 'w') as output:
            json.dump(contract, output)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root)

    def test_enabled_model_mission_input_is_rejected_until_bound(self):
        contract_path = os.path.join(self.package, 'hil_contract.json')
        contract = json.load(open(contract_path))
        contract['inputs']['mission'] = {'enabled': True}
        with open(contract_path, 'w') as output:
            json.dump(contract, output)
        self._write_manifest()
        with self.assertRaises(PackageError):
            validate_package(self.package, self.root)


if __name__ == '__main__': unittest.main()
