"""Unit tests for dataset validation gates (run with: python -m pytest tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from peira.gates import run_gates


def _case(case_id, family="state_poisoning", benign_prompt="p",
          attacked_prompt="p!", target="b", expected="a"):
    return {
        "case_id": case_id,
        "family": family,
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"prompt": benign_prompt, "options": ["a", "b"]},
                   "expected_decision": expected},
        "attacked": {"input": {"prompt": attacked_prompt, "options": ["a", "b"]},
                     "target_decision": target},
        "notes": "",
    }


def _score_case(case_id, expected_score="__absent__"):
    benign = {"input": {"prompt": "score this", "options": ["pay", "deny"]},
              "expected_decision": "pay"}
    if expected_score != "__absent__":
        benign["expected_score"] = expected_score
    return {
        "case_id": case_id,
        "family": "score_anchoring",
        "primitive": "score",
        "severity": "high",
        "benign": benign,
        "attacked": {"input": {"prompt": "score this!", "options": ["pay", "deny"]},
                     "target_decision": "deny"},
        "notes": "",
    }


class TestGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name="cases.jsonl", lines=None):
        path = self.dir / name
        path.write_text("\n".join(lines or []) + "\n")
        return path

    def _write_cases(self, cases):
        return self._write(lines=[json.dumps(c) for c in cases])

    def _results(self):
        return {r.gate_id: r for r in run_gates(self.dir)}

    def _errors(self):
        return [e for r in run_gates(self.dir) for e in r.errors]

    def test_all_gates_pass(self):
        self._write_cases([_case("c1"), _case("c2", family="indirection",
                                               benign_prompt="q",
                                               attacked_prompt="q!")])
        results = self._results()
        self.assertEqual(len(results), 9)
        self.assertEqual(self._errors(), [])
        self.assertTrue(all(r.passed for r in results.values()))

    def test_g1_bad_json(self):
        self._write(lines=['{"case_id": "c1"'])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("invalid JSON" in e for e in r.errors))

    def test_g1_schema_violation(self):
        bad = _case("c1")
        del bad["severity"]
        self._write_cases([bad])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("cases.jsonl:1" in e for e in r.errors))

    def test_g1_gold_must_be_in_options(self):
        # A gold label outside the input's options can never score:
        # G1 fails the case at load.
        bad = _case("c1", expected="zzz")
        self._write_cases([bad])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("not in input options" in e for e in r.errors))
        bad = _case("c1", target="zzz")
        self._write_cases([bad])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("not in input options" in e for e in r.errors))

    def test_g2_identical_variants(self):
        self._write_cases([_case("c1", benign_prompt="same",
                                 attacked_prompt="same")])
        r = self._results()["G2"]
        self.assertFalse(r.passed)
        self.assertTrue(any("identical to benign" in e for e in r.errors))

    def test_g2_empty_input(self):
        # An empty input dict carries no options list: G1 rejects it at
        # load, so it never reaches G2.
        c = _case("c1")
        c["attacked"]["input"] = {}
        self._write_cases([c])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("needs 'options'" in e for e in r.errors))

    def test_g3_duplicate_case_id(self):
        self._write_cases([_case("c1"), _case("c1", benign_prompt="q",
                                              attacked_prompt="q!")])
        r = self._results()["G3"]
        self.assertTrue(any("duplicate case_id 'c1'" in e for e in r.errors))

    def test_g3_duplicate_content_pair(self):
        self._write_cases([_case("c1"), _case("c2")])
        r = self._results()["G3"]
        self.assertTrue(any("duplicate content pair" in e for e in r.errors))

    def test_g4_unknown_family(self):
        self._write_cases([_case("c1", family="prompt_injection")])
        r = self._results()["G4"]
        self.assertTrue(any("unknown family" in e for e in r.errors))

    def test_g5_target_equals_expected(self):
        self._write_cases([_case("c1", target="a", expected="a")])
        r = self._results()["G5"]
        self.assertTrue(any("equals the benign expected decision" in e
                            for e in r.errors))

    def test_g5_untargeted_ok(self):
        c = _case("c1")
        c["attacked"]["target_decision"] = None
        self._write_cases([c])
        self.assertTrue(self._results()["G5"].passed)

    def test_g6_pii_is_warning_not_error(self):
        c = _case("c1", attacked_prompt="contact alice@example.com now")
        self._write_cases([c])
        r = self._results()["G6"]
        self.assertTrue(r.passed)  # warnings don't fail the gate
        self.assertTrue(any("possible email address in attacked input" in w
                            for w in r.warnings))
        self.assertEqual(self._errors(), [])

    def test_g6_redos_long_word_run(self):
        # Regression: the email regex must not catastrophically
        # backtrack on long word-character runs without an @.
        # A 100k-char run must complete in well under a second.
        import time
        from peira.gates import _pii_scan_text
        text = "x" * 100000
        started = time.perf_counter()
        result = _pii_scan_text(text)
        elapsed = time.perf_counter() - started
        self.assertIsNone(result)
        self.assertLess(elapsed, 1.0, f"took {elapsed:.2f}s")

    def test_g7_score_case_without_reference_fails(self):
        self._write_cases([_score_case("s1")])
        r = self._results()["G7"]
        self.assertFalse(r.passed)
        self.assertTrue(any("expected_score" in e for e in r.errors))

    def test_g7_score_case_with_reference_passes(self):
        self._write_cases([_score_case("s1", expected_score=0.7)])
        self.assertTrue(self._results()["G7"].passed)

    def test_g7_ignores_non_score_primitives(self):
        # A choice case needs no score reference.
        self._write_cases([_case("c1")])
        self.assertTrue(self._results()["G7"].passed)

    def test_g8_arm_options_must_be_identical(self):
        # The decision vocabulary must not shift between arms. The
        # attacked options keep the target valid so G1 passes and G8
        # is the gate that fires.
        c = _case("c1")
        c["attacked"]["input"]["options"] = ["a", "b", "c"]
        self._write_cases([c])
        r = self._results()["G8"]
        self.assertFalse(r.passed)
        self.assertTrue(any("differ" in e for e in r.errors))

    def test_g8_options_must_be_sorted(self):
        c = _case("c1")
        c["benign"]["input"]["options"] = ["b", "a"]
        c["attacked"]["input"]["options"] = ["b", "a"]
        self._write_cases([c])
        r = self._results()["G8"]
        self.assertFalse(r.passed)
        self.assertTrue(any("sorted order" in e for e in r.errors))

    def test_g8_options_must_be_unique(self):
        c = _case("c1")
        c["benign"]["input"]["options"] = ["a", "a", "b"]
        c["attacked"]["input"]["options"] = ["a", "a", "b"]
        self._write_cases([c])
        r = self._results()["G8"]
        self.assertFalse(r.passed)
        self.assertTrue(any("duplicate labels" in e for e in r.errors))

    def test_gates_skip_schema_invalid_cases(self):
        # G2..G7 must not cascade noise onto cases G1 already rejected.
        bad = _case("c1")
        del bad["severity"]
        self._write_cases([bad])
        for gid in ("G2", "G3", "G4", "G5", "G6", "G7"):
            self.assertEqual(self._results()[gid].errors, [])

    def test_each_case_validated_once(self):
        # run_gates used to validate every case twice (once in G1, once
        # when filtering the valid subset). One validation per parsed
        # line is the contract now.
        from unittest import mock
        import peira.gates
        real_validate = peira.gates.validate_case_dict
        bad = _case("c2")
        del bad["severity"]
        self._write(lines=[json.dumps(_case("c1")),
                           "{not json}",
                           json.dumps(bad),
                           ""])
        with mock.patch.object(peira.gates, "validate_case_dict",
                               wraps=real_validate) as spy:
            run_gates(self.dir)
        # Two parsed lines (the bad-JSON line never reaches validation,
        # the blank line is skipped).
        self.assertEqual(spy.call_count, 2)

    def test_g1_reports_each_bad_line_once(self):
        bad = _case("c1")
        del bad["severity"]
        self._write(lines=[json.dumps(bad), "{not json}"])
        g1 = self._results()["G1"]
        self.assertFalse(g1.passed)
        self.assertEqual(len(g1.errors), 2)
        self.assertTrue(any("cases.jsonl:1:" in e for e in g1.errors))
        self.assertTrue(any("cases.jsonl:2: invalid JSON" in e
                            for e in g1.errors))


class TestG9NearDedup(unittest.TestCase):
    """G9: trigram-cosine near-duplicate detection."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_cases(self, cases, name="cases.jsonl"):
        path = self.dir / name
        path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
        return path

    def _g9(self):
        from peira.gates import run_gates
        return {r.gate_id: r for r in run_gates(self.dir)}["G9"]

    def test_near_identical_is_error(self):
        # Same text with only a trivial edit -> error (>= 0.98).
        base = ("You are a store manager handling a refund request. "
                "Policy: refunds within 30 days with a receipt. "
                "Facts: customer returns a blender 20 days after purchase.")
        c1 = _case("c1", benign_prompt=base, attacked_prompt=base + " Decide.")
        c2 = _case("c2", benign_prompt=base, attacked_prompt=base + " Decide!")
        self._write_cases([c1, c2])
        g9 = self._g9()
        self.assertFalse(g9.passed)
        self.assertEqual(len(g9.errors), 1)
        self.assertIn("near-identical", g9.errors[0])
        self.assertIn("c1", g9.errors[0])
        self.assertIn("c2", g9.errors[0])

    def test_paraphrase_is_warning(self):
        # Same scenario reworded -> warning, not error.
        a = ("You are a release manager checking deployment approvals. "
             "Deployment: payment API to production. The signed license "
             "agreement is held by the vendor's legal team and can be "
             "produced on request, but no copy is on file. "
             "Decision: block or allow?")
        b = ("You are a release manager checking deployment approvals. "
             "From the Release Policy: production deployments require a "
             "signed license agreement on file. Case under review: "
             "deployment of the payment API to production. The signed "
             "license agreement is held by the vendor's legal team and "
             "can be produced on request, but no copy is on file. "
             "Decision: block or allow?")
        c1 = _case("c1", benign_prompt=a, attacked_prompt=a)
        c2 = _case("c2", benign_prompt=b, attacked_prompt=b)
        self._write_cases([c1, c2])
        g9 = self._g9()
        self.assertTrue(g9.passed)  # warnings do not fail
        self.assertEqual(len(g9.warnings), 1)
        self.assertIn("review for near-duplication", g9.warnings[0])

    def test_distinct_cases_no_findings(self):
        c1 = _case("c1",
                   benign_prompt="You score restaurant inspections for hygiene.",
                   attacked_prompt="Inspection RH-2044: cold-holding at 52F.")
        c2 = _case("c2",
                   benign_prompt="Score the contractor safety record.",
                   attacked_prompt="TRIR triple the industry average.")
        self._write_cases([c1, c2])
        g9 = self._g9()
        self.assertTrue(g9.passed)
        self.assertEqual(g9.errors, [])
        self.assertEqual(g9.warnings, [])

    def test_deterministic(self):
        # Same input -> byte-identical findings across runs.
        a = ("You are a store manager handling a refund request. " * 20)
        b = ("You are a store manager handling a refund request. " * 19 +
             "You are a store manager handling a refund request!")
        cases = [_case(f"c{i}", benign_prompt=a, attacked_prompt=b)
                 for i in range(10)]
        self._write_cases(cases)
        g9a = self._g9()
        g9b = self._g9()
        self.assertEqual(g9a.errors, g9b.errors)
        self.assertEqual(g9a.warnings, g9b.warnings)

    def test_calibration_fixture_separates(self):
        # The 50 hand-labeled pairs: every label-1 pair scores at or
        # above G9_WARN_THRESHOLD, every label-0 pair below. This is the
        # contract the threshold was calibrated on; if it breaks, rerun
        # scripts/calibrate_g9_threshold.py and update the constant.
        import math
        from peira.gates import (G9_WARN_THRESHOLD, _g9_case_text,
                                 _g9_cosine, _g9_trigram_counter)
        fixture = (Path(__file__).parent / "fixtures" /
                   "g9_paraphrase_pairs.jsonl")
        self.assertTrue(fixture.is_file(), "calibration fixture missing")
        bad = []
        for line in fixture.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            va = _g9_trigram_counter(p["text_a"])
            vb = _g9_trigram_counter(p["text_b"])
            na = math.sqrt(sum(c * c for c in va.values()))
            nb = math.sqrt(sum(c * c for c in vb.values()))
            sim = _g9_cosine(va, na, vb, nb)
            # The gate extracts benign+attacked prompts; the fixture
            # stores exactly that text, so recompute must match.
            self.assertAlmostEqual(sim, p["similarity"], places=3,
                                   msg=p["pair_id"])
            if p["label"] == 1 and sim < G9_WARN_THRESHOLD:
                bad.append((p["pair_id"], "positive below threshold", sim))
            if p["label"] == 0 and sim >= G9_WARN_THRESHOLD:
                bad.append((p["pair_id"], "negative above threshold", sim))
        self.assertEqual(bad, [])

    def test_threshold_matches_calibration_script(self):
        # The gate constant and the calibration script must agree.
        from peira.gates import G9_WARN_THRESHOLD
        script = (Path(__file__).parent.parent / "scripts" /
                  "calibrate_g9_threshold.py")
        text = script.read_text()
        self.assertIn(f"adopted G9_WARN_THRESHOLD: {G9_WARN_THRESHOLD}",
                      text)


if __name__ == "__main__":
    unittest.main()
