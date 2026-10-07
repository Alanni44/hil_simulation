import copy
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
INTERFACES = ROOT / "docs" / "interfaces" / "baseline"
EXPECTED = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"


def data(name):
    return json.loads((INTERFACES / name).read_text(encoding="utf-8"))


FIXTURES = {f["value"]["message_id"]: f["value"] for f in
            data("input-simulator-v0.3.examples.json")["fixtures"]}
GOLDEN = data("input-simulator-v0.3.golden.json")["vectors"]


def message(message_id):
    return copy.deepcopy(FIXTURES[message_id])


class ICDTest(unittest.TestCase):
    def rejects(self, code, action):
        from icd_runtime.errors import ICDError
        with self.assertRaises(ICDError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
