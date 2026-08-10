import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ParameterRegistryStaticTests(unittest.TestCase):
    def test_runtime_query_returns_contract_metadata_and_current_value(self):
        source = (ROOT / 'c_core' / 'src' / 'main_rt.c').read_text()
        self.assertIn('parse_get_parameter_registry', source)
        self.assertIn('"current"', source)
        self.assertIn('"review_status"', source)
        self.assertIn('"get_parameter_registry"', source)

    def test_analysis_emits_review_only_candidate_report(self):
        source = (ROOT / 'matlab_scripts' / 'analyze_model.m').read_text()
        self.assertIn('write_parameter_candidates', source)
        self.assertIn("'review_required', true", source)


if __name__ == '__main__':
    unittest.main()
