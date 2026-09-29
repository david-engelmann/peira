"""Unit tests for scripts/s1_diff.py (run with: python -m pytest tests)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import s1_diff  # noqa: E402


def _grading(cid, gid, tier="high", **over):
    g = {
        "case_id": cid,
        "grader_id": gid,
        "severity_tier": tier,
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


def _case(cid, severity="high"):
    return {
        "case_id": cid, "family": "state_poisoning", "primitive": "choice",
        "severity": severity,
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


def _fixture(root: Path, cases, ga, gb):
    cases_dir = root / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    with open(cases_dir / "state_poisoning.jsonl", "w",
              encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    pa, pb = root / "a.json", root / "b.json"
    pa.write_text(json.dumps(ga), encoding="utf-8")
    pb.write_text(json.dumps(gb), encoding="utf-8")
    return cases_dir, pa, pb


class DiffTest(unittest.TestCase):
    def test_identical_sets_perfect_agreement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high"), _case("v1-tst-002", "critical")]
            ga = [_grading("v1-tst-001", "g1", "high"),
                  _grading("v1-tst-002", "g1", "critical")]
            gb = [_grading("v1-tst-001", "g2", "high"),
                  _grading("v1-tst-002", "g2", "critical")]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            self.assertEqual(
                s1_diff.main(["--a", str(pa), "--b", str(pb),
                              "--cases", str(cases_dir),
                              "--out", str(out)]), 0)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["n_disagreements"], 0)
            self.assertEqual(doc["agreement"]["severity_raw"], 1.0)
            self.assertEqual(doc["agreement"]["severity_kappa"], 1.0)
            self.assertTrue(doc["agreement"]["gate"]["pass"])

    def test_severity_disagreement_derived_mechanically(self):
        # Grader A says critical, grader B says high; current tier high.
        # -> A has a class-2 defect, B does not; case is a disagreement.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high")]
            ga = [_grading("v1-tst-001", "g1", "critical")]
            gb = [_grading("v1-tst-001", "g2", "high")]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            self.assertEqual(doc["n_disagreements"], 1)
            dis = doc["disagreements"][0]
            self.assertEqual(dis["dimensions"], ["severity"])
            da = doc["derived"]["v1-tst-001"]["grader_a"]
            db = doc["derived"]["v1-tst-001"]["grader_b"]
            self.assertEqual(da["overall"], "DEFECT")
            self.assertEqual(da["defect_class"], 2)
            self.assertEqual(da["correction_path"], "annotate")
            self.assertEqual(db["overall"], "KEEP")

    def test_issue_order_insensitive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high")]
            ga = [_grading("v1-tst-001", "g1",
                           factual_issues=["x", "y"])]
            gb = [_grading("v1-tst-001", "g2",
                           factual_issues=["y", "x"])]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            self.assertEqual(doc["n_disagreements"], 0)

    def test_missing_case_counted_not_compared(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high")]
            ga = [_grading("v1-tst-001", "g1")]
            gb = []
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            self.assertEqual(doc["n_compared"], 0)
            self.assertEqual(doc["n_only_in_a"], 1)

    def test_invalid_tier_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high")]
            ga = [_grading("v1-tst-001", "g1", "extreme")]
            gb = [_grading("v1-tst-001", "g2", "high")]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            with self.assertRaises(SystemExit):
                s1_diff.main(["--a", str(pa), "--b", str(pb),
                              "--cases", str(cases_dir),
                              "--out", str(root / "dis.json")])

    def test_two_tier_flag(self):
        # 1 of 10 cases has a two-tier disagreement (10% > 5%) -> flag.
        # Protocol 6.3's example is high vs low: two steps on the tier scale.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case(f"v1-tst-{i:03d}", "high") for i in range(1, 11)]
            ga, gb = [], []
            for i in range(1, 11):
                cid = f"v1-tst-{i:03d}"
                ga.append(_grading(cid, "g1", "low" if i == 1 else "high"))
                gb.append(_grading(cid, "g2", "high"))
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            ag = doc["agreement"]
            self.assertEqual(ag["two_tier_disagreements"], 1)
            self.assertAlmostEqual(ag["two_tier_fraction"], 0.1)
            self.assertTrue(ag["two_tier_flag"])

    def test_gate_fails_on_low_agreement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case(f"v1-tst-{i:03d}", "high") for i in range(1, 11)]
            tiers = ["critical", "high", "medium", "low"]
            ga = [_grading(f"v1-tst-{i:03d}", "g1", tiers[i % 4])
                  for i in range(1, 11)]
            gb = [_grading(f"v1-tst-{i:03d}", "g2", tiers[(i + 1) % 4])
                  for i in range(1, 11)]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            self.assertFalse(doc["agreement"]["gate"]["pass"])

    def test_overall_agreement_diagnostic(self):
        # Both graders agree on tiers but one finds a gold defect:
        # severity agreement 1.0, overall DEFECT/KEEP agreement 0.0.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high")]
            ga = [_grading("v1-tst-001", "g1", gold_verdict="unfounded")]
            gb = [_grading("v1-tst-001", "g2")]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            self.assertEqual(doc["agreement"]["severity_raw"], 1.0)
            self.assertEqual(doc["agreement"]["overall_defect_keep_raw"], 0.0)
            self.assertEqual(doc["disagreements"][0]["dimensions"], ["gold"])

    def test_marginals_cover_all_tiers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case("v1-tst-001", "high")]
            ga = [_grading("v1-tst-001", "g1", "high")]
            gb = [_grading("v1-tst-001", "g2", "high")]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            for side in ("grader_a", "grader_b"):
                for t in ("critical", "high", "medium", "low"):
                    self.assertIn(t, doc["agreement"]["marginals"][side])

    def test_kappa_unevaluable_single_tier(self):
        # All graders say "high": kappa undefined -> gate not passed on
        # kappa, reported as unevaluable (6.3.1 diagnostic path).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = [_case(f"v1-tst-{i:03d}", "high") for i in range(1, 6)]
            ga = [_grading(f"v1-tst-{i:03d}", "g1", "high") for i in range(1, 6)]
            gb = [_grading(f"v1-tst-{i:03d}", "g2", "high") for i in range(1, 6)]
            cases_dir, pa, pb = _fixture(root, cases, ga, gb)
            out = root / "dis.json"
            s1_diff.main(["--a", str(pa), "--b", str(pb),
                          "--cases", str(cases_dir), "--out", str(out)])
            doc = json.loads(out.read_text())
            ag = doc["agreement"]
            self.assertIsNone(ag["severity_kappa"])
            self.assertIsNotNone(ag["kappa_note"])
            self.assertFalse(ag["gate"]["kappa_evaluable"])
            self.assertFalse(ag["gate"]["pass"])


if __name__ == "__main__":
    unittest.main()
