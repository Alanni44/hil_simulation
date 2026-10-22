import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from common import EXPECTED, INTERFACES, ROOT, ICDTest, data


class ManagementContractTests(ICDTest):
    @classmethod
    def setUpClass(cls):
        from icd_runtime.contract import Contract
        from icd_runtime.management import ManagementContract
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.management = ManagementContract.load(INTERFACES, contract=cls.contract)
        cls.create = data("input-simulator-v0.3.examples.json")["management_create_schema_fixture"]

    def test_create_fixture_and_frozen_command_catalogue_validate(self):
        self.management.validate_request(copy.deepcopy(self.create))
        self.assertEqual(len(self.management.commands), 25)
        self.assertEqual(self.management.commands[7], "simulator_run_create")

    def test_minimal_integration_management_examples_are_schema_only_and_valid(self):
        document = json.loads((ROOT / "docs" / "interfaces" / "examples" /
                               "simulator-hil-minimal-integration-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(document["purpose"], "SCHEMA_FIXTURES_ONLY_NOT_DEPLOYMENT_OR_EXECUTION_RESULTS")
        commands = []
        for entry in document["requests"]:
            if "baseline_fixture" in entry:
                reference = entry["baseline_fixture"]
                value = data(reference["file"])[reference["key"]]
            else:
                value = entry["value"]
            self.management.validate_request(value)
            commands.append(value["cmd"])
        self.assertEqual(commands, ["simulator_run_create", "simulator_run_get",
                                    "simulator_run_control", "simulator_run_control",
                                    "simulator_records_list"])
        for entry in document["responses"]:
            self.management.validate_response(entry["value"])

        from icd_runtime.payload import PayloadCodec
        formal = {item["name"]: item["value"] for item in
                  data("input-simulator-v0.3.examples.json")["fixtures"]}
        codec = PayloadCodec(self.contract)
        for reference in document["formal_message_fixtures"]:
            value = copy.deepcopy(formal[reference["name"]])
            self.assertEqual(value["message_id"], reference["message_id"])
            self.contract.validate_message(value)
            self.assertEqual(codec.decode(value["message_id"], codec.encode(
                value["message_id"], value["payload"])), value["payload"])

    def test_request_rejects_unknown_and_malformed_params(self):
        value = copy.deepcopy(self.create)
        value["params"]["unexpected"] = True
        self.rejects("SCHEMA", lambda: self.management.validate_request(value))
        value = copy.deepcopy(self.create)
        value["params"]["expected_revision"] = 1
        self.rejects("SCHEMA", lambda: self.management.validate_request(value))
        value = copy.deepcopy(self.create)
        value["params"]["run_configuration"]["max_duration_steps"] = 18446744073709551616
        self.rejects("SCHEMA", lambda: self.management.validate_request(value))

    def test_definition_validation_uses_same_cross_schema_registry(self):
        self.management.validate_definition("CreateParams", copy.deepcopy(self.create["params"]))
        value = copy.deepcopy(self.create["params"])
        value["run_configuration"]["model_id"] = "not-a-model"
        self.rejects("SCHEMA", lambda: self.management.validate_definition("CreateParams", value))
        self.rejects("UNSUPPORTED", lambda: self.management.validate_definition("Unknown", {}))

    def test_response_rejects_invalid_failure_and_success_shapes(self):
        failure = {
            "kind": "RESPONSE", "api_version": "0.3", "request_id": "request-01",
            "cmd": "simulator_run_create", "status": "REJECTED", "code": "BASELINE_MISMATCH",
            "message": "baseline differs", "timestamp": "2026-10-20T00:00:00Z",
            "operation_id": None, "data": None,
            "error": {"code": "BASELINE_MISMATCH", "retryable": False, "details": []},
        }
        self.management.validate_response(failure)
        failure["data"] = {}
        self.rejects("SCHEMA", lambda: self.management.validate_response(failure))

    def test_tampered_api_or_package_schema_cannot_load(self):
        files = [
            "input-simulator-api-v0.3.schema.json",
            "input-simulator-business-v0.3.schema.json",
            "input-simulator-package-v0.2.schema.json",
            "input-simulator-canfd-v0.3.dbc",
            "input-simulator-icd-v0.3.json",
            "input-simulator-data-contract-v0.3.md",
            "input-simulator-v0.3.baseline.json",
            "input-simulator-v0.3.manifest.json",
        ]
        from icd_runtime.contract import Contract
        from icd_runtime.management import ManagementContract
        for name in ("input-simulator-api-v0.3.schema.json", "input-simulator-package-v0.2.schema.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                for source in files:
                    shutil.copy2(INTERFACES / source, folder / source)
                target = folder / name
                target.write_bytes(target.read_bytes() + b" ")
                contract = Contract.load(folder, expected_sha256=EXPECTED)
                self.rejects("HASH", lambda: ManagementContract.load(folder, contract=contract))

    def test_package_fingerprint_constant_matches_current_frozen_asset(self):
        from icd_runtime.management import PACKAGE_SHA256
        raw = (INTERFACES / "input-simulator-package-v0.2.schema.json").read_bytes()
        self.assertEqual(PACKAGE_SHA256, hashlib.sha256(raw).hexdigest())
