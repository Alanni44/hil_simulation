import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "docs" / "superpowers" / "plans"


def assert_coverage(test, plan, ledger):
    tasks = {}
    stage = None
    ordinal = 0
    for line in plan.splitlines():
        heading = re.match(r"### (M[0-7]) ", line)
        if heading:
            stage, ordinal = heading[1], 0
        elif line.startswith("## "):
            stage = None
        elif stage and re.match(r"- \[[ x]\] ", line):
            ordinal += 1
            tasks[f"{stage}-{ordinal:02d}"] = line[6:]
    rows = [line.split("|")[1:-1] for line in ledger.splitlines()
            if re.match(r"\| M[0-7]-\d\d \|", line)]
    ids = [row[0].strip() for row in rows]
    test.assertEqual(len(ids), len(set(ids)), "duplicate plan responsibility")
    test.assertEqual(set(ids), set(tasks), "missing or extra plan responsibility")
    linux = set(re.findall(r"^- \[[ x]\] \*\*(L-\d{3})\*\*", ledger, re.MULTILINE))
    test.assertEqual(len(linux), 17)
    for row in rows:
        test.assertEqual(len(row), 5)
        key, task, common, transfer, boundary = (part.strip() for part in row)
        test.assertEqual(task, tasks[key], key)
        test.assertTrue(common and boundary, key)
        references = set(re.findall(r"L-\d{3}", transfer))
        test.assertTrue(references <= linux, key)
        test.assertTrue(references or "持续" in boundary, key)
    test.assertIn("W1收尾移交", ledger)
    return len(tasks)


def assert_linux_evidence(test, ledger):
    checked = set(re.findall(r"^- \[x\] \*\*(L-\d{3})\*\*", ledger, re.MULTILINE))
    evidence = dict(re.findall(r"^Linux完成证据：(L-\d{3}) -> (\S+)$", ledger, re.MULTILINE))
    test.assertTrue(checked <= set(evidence), "Linux completion requires a target report")
    for key in checked:
        path = (ROOT / evidence[key]).resolve()
        test.assertTrue(path.is_relative_to(ROOT.resolve()))
        report = json.loads(path.read_text(encoding="utf-8"))
        test.assertTrue(report["execution_host"].lower().startswith("linux"))
        test.assertEqual(report["status"], "LINUX_TARGET_VERIFIED")
        test.assertIn(key, report["completed_linux_items"])
        test.assertTrue(report["verification"])


class BacklogTests(unittest.TestCase):
    def setUp(self):
        self.plan = (PLANS / "2026-10-02-input-simulator-overall.md").read_text(encoding="utf-8")
        self.ledger = (PLANS / "linux-development-backlog.md").read_text(encoding="utf-8")

    def test_all_41_plan_items_have_common_and_linux_ownership(self):
        self.assertEqual(assert_coverage(self, self.plan, self.ledger), 41)

    def test_removed_or_duplicated_plan_item_cannot_pass_coverage(self):
        row = next(line for line in self.ledger.splitlines() if line.startswith("| M1-04 |"))
        for mutated in (self.ledger.replace(row, ""), self.ledger + "\n" + row):
            with self.assertRaises(AssertionError):
                assert_coverage(self, self.plan, mutated)

    def test_stage_closeout_is_append_only_and_linux_completion_requires_evidence(self):
        self.assertIn("追加", self.ledger)
        self.assertIn("已有记录不得删除覆盖", self.ledger)
        assert_linux_evidence(self, self.ledger)
        checked_without_evidence = self.ledger.replace("- [ ] **L-001**", "- [x] **L-001**")
        with self.assertRaises(AssertionError):
            assert_linux_evidence(self, checked_without_evidence)
