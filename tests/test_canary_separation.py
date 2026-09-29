"""Unit tests for scripts/check_canary_separation.py (run with: python -m unittest discover tests)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_canary_separation.py"
# Fixture GUIDs only. Never use the production CANARY.md / DATASHEET.md
# GUID here: the two-tier policy permits that GUID solely in those two
# documents, and this test file is neither.
DOC_GUID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CASE_GUID = "aaabbbcccdddeeeffff0000111122223333"


def _write_canary_md(root: Path):
    (root / "CANARY.md").write_text(
        f"# Canary\n\n```text\npeira-doc-canary:{DOC_GUID}\n```\n")
    (root / "DATASHEET.md").write_text(
        f"# Datasheet\n\n```text\npeira-doc-canary:{DOC_GUID}\n```\n")


def _write_suite(root: Path, suite="dataset/trial", with_canary=True):
    d = root / suite
    d.mkdir(parents=True, exist_ok=True)
    (d / "CANARY.txt").write_text(CASE_GUID + "\n")
    case = {"case_id": "t-001", "family": "x", "primitive": "choice",
            "severity": "low",
            "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                       "expected_decision": "a"},
            "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                        "target_decision": "b"}}
    if with_canary:
        case["canary"] = f"peira-trial-canary:{CASE_GUID}"
        case["evaluation_only"] = True
        case["do_not_train"] = True
    (d / "cases.jsonl").write_text(json.dumps(case) + "\n")


class TestCanarySeparation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root)],
            capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout + proc.stderr

    def test_clean_separation_passes(self):
        _write_canary_md(self.root)
        _write_suite(self.root)
        code, out = self._run()
        self.assertEqual(code, 0, out)
        self.assertIn("cleanly separated", out)

    def test_unsealed_suite_is_info_not_error(self):
        _write_canary_md(self.root)
        # No CANARY.txt: suite not sealed yet.
        code, out = self._run()
        self.assertEqual(code, 0, out)
        self.assertIn("not sealed", out)

    def test_case_missing_canary_fails(self):
        _write_canary_md(self.root)
        _write_suite(self.root, with_canary=False)
        code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("missing tier-1", out)

    def test_tier1_guid_in_docs_fails(self):
        _write_canary_md(self.root)
        _write_suite(self.root)
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "notes.md").write_text(f"the guid {CASE_GUID} leaked\n")
        code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("tier-1 canary", out)
        self.assertIn("documentation", out)

    def test_tier2_guid_in_cases_fails(self):
        _write_canary_md(self.root)
        d = self.root / "dataset" / "trial"
        d.mkdir(parents=True)
        (d / "CANARY.txt").write_text(CASE_GUID + "\n")
        case = {"case_id": "t-001",
                "canary": f"peira-trial-canary:{CASE_GUID}",
                "evaluation_only": True,
                "do_not_train": True,
                "notes": f"doc guid {DOC_GUID} leaked into a case"}
        (d / "cases.jsonl").write_text(json.dumps(case) + "\n")
        code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("tier-2 doc canary appears outside", out)

    def test_tier2_guid_missing_from_docs_fails(self):
        # CANARY.md without the doc GUID.
        (self.root / "CANARY.md").write_text("# Canary\n\nno guid here\n")
        (self.root / "DATASHEET.md").write_text(
            f"```text\npeira-doc-canary:{DOC_GUID}\n```\n")
        code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("does not contain", out)


if __name__ == "__main__":
    unittest.main()
