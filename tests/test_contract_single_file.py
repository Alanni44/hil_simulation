import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs" / "interfaces" / "baseline"
SCRIPT = ROOT / "scripts" / "build_contract_single_file.py"


class SingleFileContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "single-file contract builder is missing")
        spec = importlib.util.spec_from_file_location("single_file_builder", SCRIPT)
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)
        self.document = self.builder.build_document(SOURCES)

    def test_all_original_artifacts_are_embedded_byte_exact(self):
        raw = self.document.encode("utf-8")
        for name in self.builder.SOURCE_FILES:
            with self.subTest(source=name):
                marker = self.builder.start_marker(name).encode("ascii")
                begin = raw.index(marker) + len(marker)
                source = (SOURCES / name).read_bytes()
                self.assertEqual(raw[begin:begin + len(source)], source)
                self.assertEqual(hashlib.sha256(raw[begin:begin + len(source)]).digest(),
                                 hashlib.sha256(source).digest())
        self.assertEqual(len(self.builder.SOURCE_FILES), 14)

    def test_all_schema_references_resolve_inside_document(self):
        summary = self.builder.verify_document(self.document, SOURCES)
        self.assertGreater(summary["resolved_schema_references"], 300)
        self.assertEqual(summary["business_messages"], 59)
        self.assertEqual(summary["management_commands"], 25)
        self.assertEqual(summary["golden_vectors"], 85)
        self.assertEqual(summary["physical_channels"], 56)
        self.assertEqual(summary["model_bindings"], 97)

    def test_all_field_rows_and_management_definitions_present(self):
        fields = (SOURCES / "input-simulator-fields-v0.3.md").read_text(encoding="utf-8")
        for row in fields.splitlines():
            if row.startswith("| `"):
                self.assertIn(row, self.document)
        schema = json.loads((SOURCES / "input-simulator-api-v0.3.schema.json").read_bytes())
        for name in schema["$defs"]:
            self.assertIn(f"### API.{name}\n", self.document)
        self.assertIn("机器定义均已完整嵌入本文件", self.document)
        self.assertIn("不是应用实现完成或硬件验收通过", self.document)

    def test_missing_or_corrupt_snapshot_fails_verification(self):
        name = "input-simulator-business-v0.3.schema.json"
        damaged = self.document.replace(self.builder.start_marker(name), "", 1)
        with self.assertRaises(ValueError):
            self.builder.verify_document(damaged, SOURCES)


if __name__ == "__main__":
    unittest.main()
