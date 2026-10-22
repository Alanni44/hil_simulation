import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / 'deploy' / 'systemd' / 'hil-deploy'


def load_helper():
    loader = importlib.machinery.SourceFileLoader('hil_deploy_test_helper', str(HELPER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SystemdDeployHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = pathlib.Path(self.temporary.name) / 'runtime'
        (self.runtime / 'work' / 'run-1').mkdir(parents=True)
        (self.runtime / 'pending').mkdir()
        (self.runtime / 'verified').mkdir()
        self.helper = load_helper()
        self.helper.RUNTIME_ROOT = str(self.runtime)

    def tearDown(self):
        self.temporary.cleanup()

    def write_descriptor(self, executable, sha256):
        with open(str(self.runtime / 'pending' / 'current.json'), 'w') as output:
            json.dump({'executable_path': str(executable), 'executable_sha256': sha256}, output)

    def test_accepts_a_hashed_executable_below_work_root(self):
        executable = self.runtime / 'work' / 'run-1' / 'model_rt'
        executable.write_bytes(b'verified model')
        executable.chmod(0o750)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        self.write_descriptor(executable, digest)

        pending, path, actual_digest = self.helper._read_descriptor('current')

        self.assertEqual(str(self.runtime / 'pending' / 'current.json'), pending)
        self.assertEqual(str(executable), path)
        self.assertEqual(digest, actual_digest)

    def test_rejects_an_executable_outside_work_root(self):
        outside = pathlib.Path(self.temporary.name) / 'outside_rt'
        outside.write_bytes(b'not controlled')
        self.write_descriptor(outside, hashlib.sha256(outside.read_bytes()).hexdigest())

        with self.assertRaisesRegex(self.helper.DeployError, 'outside the verified work root'):
            self.helper._read_descriptor('current')

    def test_rejects_invalid_hash_before_any_install(self):
        executable = self.runtime / 'work' / 'run-1' / 'model_rt'
        executable.write_bytes(b'fixture')
        self.write_descriptor(executable, 'not-a-sha256')

        with self.assertRaisesRegex(self.helper.DeployError, 'SHA-256 is invalid'):
            self.helper._read_descriptor('current')

    def test_failed_restart_restores_the_previous_verified_core(self):
        executable = self.runtime / 'work' / 'run-1' / 'model_rt'
        executable.write_bytes(b'new verified model')
        executable.chmod(0o750)
        self.write_descriptor(executable, hashlib.sha256(executable.read_bytes()).hexdigest())
        current = self.runtime / 'verified' / 'current_rt'
        current.write_bytes(b'old verified model')
        current.chmod(0o750)

        def copy_checked(source, expected, destination):
            self.assertEqual(str(executable), source)
            staged = pathlib.Path(destination + '.new')
            staged.write_bytes(executable.read_bytes())
            os.replace(str(staged), destination)

        with patch.object(self.helper.os, 'geteuid', return_value=0), \
                patch.object(self.helper, '_copy_checked', side_effect=copy_checked), \
                patch.object(self.helper, '_restart_core', side_effect=[OSError('new core failed'), None]) as restart:
            with self.assertRaisesRegex(self.helper.DeployError, 'previous verified core was restored'):
                self.helper.deploy('current')

        self.assertEqual(current.read_bytes(), b'old verified model')
        self.assertFalse((self.runtime / 'verified' / 'current_rt.rollback').exists())
        self.assertTrue((self.runtime / 'pending' / 'current.json').exists())
        self.assertEqual(restart.call_count, 2)

    def test_restart_requires_the_replacement_to_remain_active(self):
        with patch.object(self.helper.subprocess, 'check_call', side_effect=[None, None,
                self.helper.subprocess.CalledProcessError(3, ['systemctl', 'is-active'])]) as call, \
                patch.object(self.helper.time, 'sleep') as sleep:
            with self.assertRaises(self.helper.subprocess.CalledProcessError):
                self.helper._restart_core('current')

        self.assertEqual(call.call_args_list[0][0][0],
                         ['systemctl', 'restart', 'hil-core@current.service'])
        self.assertEqual(sleep.call_count, 2)

    def test_deploy_unit_does_not_order_a_restart_behind_itself(self):
        unit = (ROOT / 'deploy' / 'systemd' / 'hil-deploy@.service').read_text(encoding='utf-8')
        self.assertNotIn('Before=hil-core@%i.service', unit)
        self.assertIn('ExecStart=/opt/hil/bin/hil-deploy %i', unit)

    def test_input_simulator_unit_is_unprivileged_and_uses_fixed_runtime_configuration(self):
        unit = (ROOT / 'deploy' / 'systemd' / 'input-simulator.service').read_text(encoding='utf-8')
        self.assertIn('User=hil', unit)
        self.assertIn('ExecStart=/opt/hil/.venv/bin/python -m input_simulator.manage', unit)
        self.assertNotIn('/opt/hil/venv/bin/python3', unit)
        self.assertIn('--runtime-config /etc/hil/minimal-integration-simulator.json', unit)
        self.assertIn('--state-dir /opt/hil/runtime/input-simulator-state', unit)
        self.assertIn('--bind 0.0.0.0:18080', unit)
        self.assertIn('NoNewPrivileges=true', unit)
        self.assertIn('ProtectSystem=strict', unit)

    def test_gateway_unit_uses_the_explicit_core_and_three_vcan_configuration(self):
        unit = (ROOT / 'deploy' / 'systemd' / 'hil-gateway.service').read_text(encoding='utf-8')
        topology = (ROOT / 'deploy' / 'systemd' / 'hil-vcan-setup').read_text(encoding='utf-8')
        starter = (ROOT / 'deploy' / 'systemd' / 'start-minimal-hil.sh').read_text(encoding='utf-8')
        self.assertIn('Requires=hil-vcan.service hil-core@current.service', unit)
        self.assertIn('--c-core-endpoint quadrotor_hil=127.0.0.1:9997', unit)
        self.assertIn('--c-core-runtime-contract quadrotor_hil=/opt/hil/artifacts/z_mission/model/hil_contract.json', unit)
        self.assertIn('--can', unit)
        self.assertIn('CAP_NET_RAW', unit)
        for interface in ('can0', 'can1', 'can2'):
            self.assertIn(interface, topology)
        self.assertIn('/opt/hil/bin/hil-deploy current', starter)
        self.assertIn('systemctl restart hil-prepare.service', starter)
        self.assertIn('systemctl restart hil-gateway.service', starter)

    def test_full_flow_runner_restores_configured_readiness_after_the_smoke(self):
        runner = (ROOT / 'deploy' / 'systemd' / 'run-minimal-full-flow.sh').read_text(encoding='utf-8')
        self.assertIn('-m input_simulator.smoke', runner)
        self.assertIn('systemctl restart hil-core@current.service', runner)
        self.assertIn('systemctl restart hil-prepare.service', runner)
        self.assertIn('systemctl stop hil-gateway.service', runner)
        self.assertIn('systemctl start hil-gateway.service', runner)
        self.assertIn('rm -f "$gateway_lock"', runner)

    def test_preparation_unit_uses_the_same_fixed_template_as_the_simulator(self):
        unit = (ROOT / 'deploy' / 'systemd' / 'hil-prepare.service').read_text(encoding='utf-8')
        self.assertIn('User=hil', unit)
        self.assertIn('-m icd_gateway.prepare_minimal', unit)
        self.assertIn('--template /opt/hil/config/minimal-integration-template.json', unit)
        self.assertIn('--c-core-endpoint quadrotor_hil=127.0.0.1:9997', unit)

    def test_remote_preparation_and_read_only_telemetry_units_are_deployed(self):
        preparation = (ROOT / 'deploy' / 'systemd' / 'hil-preparation.service').read_text(encoding='utf-8')
        telemetry = (ROOT / 'deploy' / 'systemd' / 'hil-telemetry.service').read_text(encoding='utf-8')
        installer = (ROOT / 'deploy' / 'systemd' / 'install-production.sh').read_text(encoding='utf-8')
        starter = (ROOT / 'deploy' / 'systemd' / 'start-minimal-hil.sh').read_text(encoding='utf-8')
        self.assertIn('-m icd_gateway.prepare_manage', preparation)
        self.assertIn('--bind 0.0.0.0:18081', preparation)
        self.assertIn('Requires=hil-core@current.service', preparation)
        self.assertIn('telemetry_main.py', telemetry)
        self.assertIn('ExecStart=/opt/hil/.venv/bin/python', telemetry)
        self.assertNotIn('/opt/hil/venv/bin/python3', telemetry)
        self.assertIn('Conflicts=hil-python-services.service', telemetry)
        self.assertIn('After=network-online.target hil-core@current.service '
                      'hil-preparation.service', telemetry)
        self.assertIn('Wants=network-online.target hil-preparation.service', telemetry)
        self.assertIn('hil-preparation.service', installer)
        self.assertIn('hil-telemetry.service', installer)
        self.assertIn('systemctl start hil-preparation.service', starter)
        self.assertIn('systemctl start hil-telemetry.service', starter)

    def test_installer_requires_the_isolated_simulator_runtime_before_installing_units(self):
        installer = (ROOT / 'deploy' / 'systemd' / 'install-production.sh').read_text(encoding='utf-8')
        self.assertIn('simulator_python=/opt/hil/.venv/bin/python', installer)
        self.assertIn('missing isolated Python 3.12 simulator runtime', installer)
        self.assertIn('simulator_base_prefix=', installer)
        self.assertIn('simulator virtual environment was copied from outside /opt/hil', installer)
        self.assertIn('import icd_gateway, icd_runtime, input_simulator, jsonschema, referencing', installer)
        self.assertIn('yaml', installer)
        self.assertIn('systemctl disable --now hil-python-services.service || true', installer)
        self.assertIn('chown -R hil:hil /opt/hil/logs', installer)

    def test_installer_does_not_register_tmpfiles_below_the_editable_checkout(self):
        installer = (ROOT / 'deploy' / 'systemd' / 'install-production.sh').read_text(encoding='utf-8')
        self.assertIn('rm -f /etc/tmpfiles.d/hil-runtime.conf', installer)
        self.assertNotIn('systemd-tmpfiles --create', installer)
