"""Unit tests for scripts/s1_common.py (run with: python -m pytest tests)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import s1_common as C  # noqa: E402


def _grading(**over):
    g = {
        "case_id": "v1-tst-001",
        "grader_id": "g1",
        "severity_tier": "high",
        "severity_bullet": "b",
        "severity_notes": "n",
        "gold_verdict": "ok",
        "gold_derivation": "d",
        "factual_issues": [],
        "attack_integrity": "ok",
        "format_issues": [],
    }
    g.update(over)
    return g


class DeriveVerdictTest(unittest.TestCase):
    def test_no_defects_keep(self):
        d = C.derive_verdict(_grading(), "high")
        self.assertEqual(d["overall"], "KEEP")
        self.assertIsNone(d["defect_class"])
        self.assertIsNone(d["correction_path"])
        self.assertEqual(d["all_defect_classes"], [])
        self.assertFalse(d["dimensions"]["severity"]["defect"])

    def test_severity_differ_is_class2_annotate(self):
        d = C.derive_verdict(_grading(severity_tier="critical"), "high")
        sev = d["dimensions"]["severity"]
        self.assertTrue(sev["defect"])
        self.assertEqual(sev["defect_class"], 2)
        self.assertEqual(sev["direction"], "upgrade")
        self.assertEqual(d["overall"], "DEFECT")
        self.assertEqual(d["defect_class"], 2)
        self.assertEqual(d["correction_path"], "annotate")

    def test_severity_downgrade_direction(self):
        d = C.derive_verdict(_grading(severity_tier="medium"), "high")
        self.assertEqual(d["dimensions"]["severity"]["direction"], "downgrade")
        self.assertEqual(d["defect_class"], 2)

    def test_gold_not_ok_is_class1(self):
        d = C.derive_verdict(_grading(gold_verdict="unfounded"), "high")
        self.assertTrue(d["dimensions"]["gold"]["defect"])
        self.assertEqual(d["defect_class"], 1)
        self.assertEqual(d["correction_path"], "retire+add")

    def test_attack_integrity_broken_is_class6(self):
        d = C.derive_verdict(_grading(attack_integrity="broken"), "high")
        self.assertTrue(d["dimensions"]["attack_integrity"]["defect"])
        self.assertEqual(d["defect_class"], 6)
        self.assertEqual(d["correction_path"], "retire+add")

    def test_conservatism_ordering_retire_add_beats_annotate(self):
        # class 6 (retire+add) + class 2 (annotate) -> 6 wins
        d = C.derive_verdict(
            _grading(attack_integrity="broken", severity_tier="critical"), "high"
        )
        self.assertEqual(d["defect_class"], 6)
        self.assertEqual(d["correction_path"], "retire+add")
        self.assertEqual(d["all_defect_classes"], [2, 6])

    def test_conservatism_ordering_annotate_beats_fix(self):
        # class 2 (annotate) + class 5 (fix) -> 2 wins
        d = C.derive_verdict(
            _grading(severity_tier="critical", format_issues=["typoo"]), "high"
        )
        self.assertEqual(d["defect_class"], 2)
        self.assertEqual(d["correction_path"], "annotate")
        self.assertEqual(d["all_defect_classes"], [2, 5])

    def test_tie_on_path_breaks_to_lowest_class(self):
        # class 1 and class 6 are both retire+add: lowest number wins
        d = C.derive_verdict(
            _grading(gold_verdict="unfounded", attack_integrity="broken"), "high"
        )
        self.assertEqual(d["defect_class"], 1)
        self.assertEqual(d["correction_path"], "retire+add")
        self.assertEqual(d["all_defect_classes"], [1, 6])

    def test_factual_default_is_conservative(self):
        # untagged factual issue -> changes_answer defaults True -> retire+add
        d = C.derive_verdict(_grading(factual_issues=["wrong date"]), "high")
        self.assertEqual(d["defect_class"], 3)
        self.assertEqual(d["correction_path"], "retire+add")

    def test_factual_tagged_answer_preserving_is_fix(self):
        d = C.derive_verdict(
            _grading(factual_issues=[
                {"detail": "typo in date", "changes_answer": False}]),
            "high",
        )
        self.assertEqual(d["defect_class"], 3)
        self.assertEqual(d["correction_path"], "fix")

    def test_format_bare_string_is_class5(self):
        d = C.derive_verdict(_grading(format_issues=["recieve"]), "high")
        self.assertEqual(d["dimensions"]["format"]["defect_classes"], [5])
        self.assertEqual(d["defect_class"], 5)
        self.assertEqual(d["correction_path"], "fix")

    def test_format_class4_default_is_retire_add(self):
        d = C.derive_verdict(
            _grading(format_issues=[{"class": 4, "detail": "0-100 vs 0-1"}]),
            "high",
        )
        self.assertEqual(d["dimensions"]["format"]["defect_classes"], [4])
        self.assertEqual(d["defect_class"], 4)
        self.assertEqual(d["correction_path"], "retire+add")

    def test_format_class4_presentational_is_fix(self):
        d = C.derive_verdict(
            _grading(format_issues=[
                {"class": 4, "detail": "label case", "changes_gold": False}]),
            "high",
        )
        self.assertEqual(d["defect_class"], 4)
        self.assertEqual(d["correction_path"], "fix")

    def test_format_mixed_classes_most_conservative_path(self):
        d = C.derive_verdict(
            _grading(format_issues=[
                "typo",
                {"class": 4, "detail": "scale", "changes_gold": False},
            ]),
            "high",
        )
        # class 4 (fix) + class 5 (fix): both fix; defect_class tie -> 4
        self.assertEqual(d["dimensions"]["format"]["defect_classes"], [4, 5])
        self.assertEqual(d["correction_path"], "fix")
        self.assertEqual(d["defect_class"], 4)

    def test_invalid_current_tier_raises(self):
        with self.assertRaises(ValueError):
            C.derive_verdict(_grading(), "extreme")

    def test_invalid_grader_tier_raises(self):
        with self.assertRaises(ValueError):
            C.derive_verdict(_grading(severity_tier="extreme"), "high")


class KappaTest(unittest.TestCase):
    def test_known_fixture(self):
        # Hand-computed: po=0.75, pe=5/16=0.3125, kappa=0.4375/0.6875
        pairs = [("high", "high"), ("high", "critical"),
                 ("critical", "critical"), ("medium", "medium")]
        kappa, note = C.cohen_kappa(pairs)
        self.assertIsNone(note)
        self.assertAlmostEqual(kappa, 0.4375 / 0.6875, places=6)

    def test_perfect_agreement_is_one(self):
        pairs = [("high", "high"), ("critical", "critical"),
                 ("medium", "medium")]
        kappa, note = C.cohen_kappa(pairs)
        self.assertIsNone(note)
        self.assertAlmostEqual(kappa, 1.0)

    def test_single_tier_is_undefined(self):
        # Kappa paradox: perfect expected agreement -> None, not 1.0
        pairs = [("high", "high")] * 10
        kappa, note = C.cohen_kappa(pairs)
        self.assertIsNone(kappa)
        self.assertIsNotNone(note)

    def test_empty_is_undefined(self):
        kappa, note = C.cohen_kappa([])
        self.assertIsNone(kappa)
        self.assertIsNotNone(note)

    def test_unobserved_tiers_still_count(self):
        # "low" never appears but is a category; pe unaffected (0 mass).
        pairs = [("high", "medium"), ("medium", "high")]
        kappa, note = C.cohen_kappa(pairs)
        # po=0, pe=1/4+1/4=1/2 -> kappa=-1
        self.assertAlmostEqual(kappa, -1.0, places=6)


class VersionTest(unittest.TestCase):
    def test_bumps(self):
        self.assertEqual(C.bump_version("1.0.3", "patch"), "1.0.4")
        self.assertEqual(C.bump_version("1.0.3", "minor"), "1.1.0")
        self.assertEqual(C.bump_version("1.0.3", "major"), "2.0.0")

    def test_bad_version_raises(self):
        with self.assertRaises(ValueError):
            C.bump_version("1.0", "patch")

    def test_bad_bump_raises(self):
        with self.assertRaises(ValueError):
            C.bump_version("1.0.3", "mega")

    def test_bump_for_entry_types(self):
        self.assertEqual(C.bump_for_entry_types(["retire", "add"]), "minor")
        self.assertEqual(C.bump_for_entry_types(["fix"]), "patch")
        self.assertEqual(C.bump_for_entry_types(["annotate"]), "patch")
        self.assertEqual(C.bump_for_entry_types(["fix", "annotate"]), "patch")
        self.assertIsNone(C.bump_for_entry_types([]))
        self.assertIsNone(C.bump_for_entry_types(["seal"]))

    def test_mint_replacement_id(self):
        self.assertEqual(C.mint_replacement_id("v1-csp", [1, 2, 250]), "v1-csp-251")
        self.assertEqual(C.mint_replacement_id("v1-csp", []), "v1-csp-001")

    def test_mint_overflow_raises(self):
        with self.assertRaises(ValueError):
            C.mint_replacement_id("v1-csp", [999])

    def test_parse_case_id(self):
        self.assertEqual(C.parse_case_id("v1-csp-001"), ("csp", 1))
        with self.assertRaises(ValueError):
            C.parse_case_id("bogus")


class ChangelogSchemaTest(unittest.TestCase):
    def _entry(self, **over):
        e = {"date": "2026-09-28", "type": "retire",
             "dataset_version": "1.1.0", "description": "d",
             "case_ids": ["v1-tst-001"], "rationale": "r",
             "replacements": {"v1-tst-001": "v1-tst-101"}}
        e.update(over)
        return e

    def test_valid_retire(self):
        self.assertEqual(C.validate_changelog_entry(self._entry()), [])

    def test_missing_required_field(self):
        e = self._entry()
        del e["replacements"]
        errs = C.validate_changelog_entry(e)
        self.assertTrue(any("replacements" in x for x in errs))

    def test_unknown_type(self):
        errs = C.validate_changelog_entry(self._entry(type="nuke"))
        self.assertTrue(any("unknown entry type" in x for x in errs))

    def test_bad_date(self):
        errs = C.validate_changelog_entry(self._entry(date="28/09/2026"))
        self.assertTrue(any("date" in x for x in errs))

    def test_doc_envelope(self):
        errs = C.validate_changelog_doc({"entries": []})
        self.assertTrue(any("$schema_id" in x for x in errs))


class ValidateGradingTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(C.validate_grading(_grading()), [])

    def test_missing_key(self):
        g = _grading()
        del g["severity_bullet"]
        self.assertTrue(any("severity_bullet" in e
                            for e in C.validate_grading(g)))

    def test_bad_tier(self):
        errs = C.validate_grading(_grading(severity_tier="extreme"))
        self.assertTrue(any("severity_tier" in e for e in errs))

    def test_issues_must_be_lists(self):
        errs = C.validate_grading(_grading(factual_issues="wrong"))
        self.assertTrue(any("factual_issues" in e for e in errs))

    def test_issue_entry_wrong_type_rejected(self):
        # P2 regression: {"factual_issues": [123]} crashed _norm_issue.
        errs = C.validate_grading(_grading(factual_issues=[123]))
        self.assertTrue(any("must be a string or object" in e for e in errs))

    def test_format_issue_bad_class_rejected(self):
        # P2 regression: {"class": 99} crashed _format_issue_class.
        errs = C.validate_grading(
            _grading(format_issues=[{"detail": "x", "class": 99}]))
        self.assertTrue(any("must be 4 or 5" in e for e in errs))

    def test_none_tier_rejected(self):
        # P2 regression: severity_tier=None passed validation then crashed
        # in _tier_direction (TIERS.index(None)).
        errs = C.validate_grading(_grading(severity_tier=None))
        self.assertTrue(any("severity_tier" in e for e in errs))

    def test_dict_entry_missing_detail_rejected(self):
        # P2 regression: {"changes_answer": False} without "detail" passed
        # validation then crashed s1_apply's "; ".join on None.
        errs = C.validate_grading(
            _grading(factual_issues=[{"changes_answer": False}]))
        self.assertTrue(any("detail" in e for e in errs))

    def test_null_issues_accepted_as_empty(self):
        # Explicit null is treated as absent (no crash downstream).
        errs = C.validate_grading(
            _grading(factual_issues=None, format_issues=None))
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
