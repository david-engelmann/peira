"""Unit tests for scripts/s1_sheet.py (run with: python -m unittest discover tests)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import s1_common as C  # noqa: E402
import s1_sheet  # noqa: E402


def _case(cid="v1-tst-001", severity="high"):
    return {
        "case_id": cid,
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": severity,
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


def _cases_dir(root: Path) -> Path:
    cases = root / "cases"
    cases.mkdir(parents=True)
    with open(cases / "state_poisoning.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(_case()) + "\n")
    return cases


class GradingSheetTest(unittest.TestCase):
    def test_severity_value_redacted(self):
        sheet = s1_sheet.render_grading_sheet(_case(severity="high"))
        # The redacted marker is present...
        self.assertIn("[REDACTED", sheet)
        # ...and the live tier value is not attached to the severity field.
        self.assertNotIn('"severity": "high"', sheet)
        # The case is otherwise intact.
        self.assertIn('"case_id": "v1-tst-001"', sheet)

    def test_template_has_all_schema_keys(self):
        sheet = s1_sheet.render_grading_sheet(_case())
        for key in C.REQUIRED_GRADING_KEYS:
            self.assertIn(f'"{key}"', sheet)

    def test_tagging_guidance_present(self):
        sheet = s1_sheet.render_grading_sheet(_case())
        self.assertIn("changes_answer", sheet)
        self.assertIn("changes_gold", sheet)

    def test_grading_mode_writes_one_sheet_per_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _cases_dir(root)
            sample = root / "sample.json"
            sample.write_text(json.dumps({
                "cases": [{"case_id": "v1-tst-001", "family": "state_poisoning"}]
            }), encoding="utf-8")
            out = root / "sheets"
            self.assertEqual(
                s1_sheet.main(["--sample", str(sample),
                               "--cases", str(cases),
                               "--out", str(out)]), 0)
            sheets = list(out.glob("*.md"))
            self.assertEqual(len(sheets), 1)
            self.assertEqual(sheets[0].name, "v1-tst-001.md")

    def test_grading_mode_unknown_case_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _cases_dir(root)
            sample = root / "sample.json"
            sample.write_text(json.dumps({
                "cases": [{"case_id": "v1-nope-999", "family": "x"}]
            }), encoding="utf-8")
            with self.assertRaises(SystemExit):
                s1_sheet.main(["--sample", str(sample),
                               "--cases", str(cases),
                               "--out", str(root / "sheets")])


class AdjudicationSheetTest(unittest.TestCase):
    def _dispute(self):
        return {
            "case_id": "v1-tst-001",
            "dimensions": ["severity"],
            "grader_a": {"case_id": "v1-tst-001", "grader_id": "g1-secret",
                         "severity_tier": "critical", "severity_bullet": "b",
                         "severity_notes": "n"},
            "grader_b": {"case_id": "v1-tst-001", "grader_id": "g2-secret",
                         "severity_tier": "high", "severity_bullet": "b2",
                         "severity_notes": "n2"},
        }

    def test_grader_identities_stripped(self):
        sheet = s1_sheet.render_adjudication_sheet(_case(), self._dispute())
        self.assertNotIn("g1-secret", sheet)
        self.assertNotIn("g2-secret", sheet)
        # ...but both verdicts' rationales are present, labeled A/B.
        self.assertIn("Grader A verdict", sheet)
        self.assertIn("Grader B verdict", sheet)
        self.assertIn('"severity_tier": "critical"', sheet)
        self.assertIn('"severity_tier": "high"', sheet)

    def test_adjudicator_sees_full_case(self):
        # Protocol 6.2: the adjudicator sees "the case"; only grader
        # identities are blinded. The current tier is shown.
        sheet = s1_sheet.render_adjudication_sheet(
            _case(severity="high"), self._dispute())
        self.assertIn('"severity": "high"', sheet)

    def test_disputed_dimensions_listed(self):
        sheet = s1_sheet.render_adjudication_sheet(_case(), self._dispute())
        self.assertIn("severity", sheet)

    def test_adjudication_mode_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _cases_dir(root)
            disp = root / "dis.json"
            disp.write_text(json.dumps(
                {"disagreements": [self._dispute()]}), encoding="utf-8")
            out = root / "adj"
            self.assertEqual(
                s1_sheet.main(["--adjudicate", str(disp),
                               "--cases", str(cases),
                               "--out", str(out)]), 0)
            sheets = list(out.glob("*.md"))
            self.assertEqual(len(sheets), 1)

    def test_needs_exactly_one_mode(self):
        with self.assertRaises(SystemExit):
            s1_sheet.main(["--out", "/tmp/x"])
        with self.assertRaises(SystemExit):
            s1_sheet.main(["--sample", "a", "--adjudicate", "b",
                           "--out", "/tmp/x"])


if __name__ == "__main__":
    unittest.main()
