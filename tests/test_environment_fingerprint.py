import copy
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import environment_fingerprint  # noqa: E402


class EnvironmentFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.facts = {
            'operating_system': {'id': 'ubuntu', 'version_id': '18.04'},
            'kernel': {'release': '5.4.10-rt5', 'preempt_rt': True},
            'python': {
                'version': '3.6.9',
                'dependencies': {
                    'pyyaml': {'required': '6.0.1', 'installed': '6.0.1'}}},
            'gcc': {'version': '7.5.0'},
            'matlab': {
                'release': 'R2018b', 'version': '9.5.0.944444',
                'executable': '/usr/local/MATLAB/R2018b/bin/matlab'},
        }

    def test_exact_pinned_environment_is_accepted(self):
        self.assertEqual(
            [], environment_fingerprint.validate_environment(self.facts))

    def test_kernel_and_dependency_drift_are_both_reported(self):
        drifted = copy.deepcopy(self.facts)
        drifted['kernel']['release'] = '5.4.11-rt6'
        drifted['python']['dependencies']['pyyaml']['installed'] = '6.0'

        errors = environment_fingerprint.validate_environment(drifted)

        self.assertTrue(any('kernel.release' in error for error in errors))
        self.assertTrue(any('python.dependencies.pyyaml' in error
                            for error in errors))


if __name__ == '__main__':
    unittest.main()
