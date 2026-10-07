import copy
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
INTERFACES = ROOT / "docs" / "interfaces" / "baseline"
EXPECTED = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
FIXTURES = {f["value"]["message_id"]: f["value"] for f in json.loads(
    (INTERFACES / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]}


def message(mid):
    return copy.deepcopy(FIXTURES[mid])


class GatewayTest(unittest.TestCase):
    def setUp(self):
        from icd_runtime.contract import Contract
        self.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)

    def rejects(self, code, action):
        from icd_runtime.errors import ICDError
        with self.assertRaises(ICDError) as error:
            action()
        self.assertEqual(error.exception.code, code)
