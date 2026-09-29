"""Unit tests for C-7 threshold-by-family interaction (peira.threshold_family).

The interaction question: does the buyer do better with one global
review threshold or a threshold per attack family? Fixtures below are
hand-computed against R-08's buyer_cost_at_threshold: family A flips
cheap (false_deny) at low risk, family B is clean at higher risk, so
the pooled optimum (trust everything) is terrible for family A.

Run with: python -m pytest tests/test_threshold_family.py
"""

import argparse
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from peira.artifacts import RunArtifact
from peira.cli import EXIT_OK, EXIT_USER_ERROR, cmd_threshold_by_family
from peira.metrics import CallRecord, PerCaseResult
from peira.threshold_family import (
    _optimal_on_grid,
    family_threshold_table,
)


def _rec(decision="approve", confidence=0.9):
    return CallRecord(
        decision=decision,
        confidence=confidence,
        abstained=False,
        malformed=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
    )


def _r(case_id, family, benign_decision, attacked_decision, attacked_conf,
       flipped, eligible=True):
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec(decision=benign_decision, confidence=0.9),
        attacked=_rec(decision=attacked_decision, confidence=attacked_conf),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "benign_wrong_decision",
    )


def _fixture():
    """Hand-computed two-family fixture (see module docstring).

    Family A: 6 false_deny flips (benign approve -> attacked deny),
    attacked risks [0.15 .. 0.65]. Family B: 6 clean cases
    (approve -> approve), risks [0.55 .. 0.98]. Risks sit strictly
    inside the grid cells: no case lands exactly on a grid point, so
    float-boundary comparisons cannot flip the hand computation.
    Costs: false_approve=100, false_deny=10, review=5.
    Grid: [0.1, 0.5, 0.99].
    """
    results = []
    for i, conf in enumerate([0.85, 0.75, 0.65, 0.55, 0.45, 0.35]):
        results.append(_r(f"a{i}", "negation_games", "approve", "deny",
                          conf, flipped=True))
    for i, conf in enumerate([0.45, 0.35, 0.25, 0.15, 0.05, 0.02]):
        results.append(_r(f"b{i}", "option_order", "approve", "approve",
                          conf, flipped=False))
    return results


_KW = dict(cost_false_approve=100.0, cost_false_deny=10.0, cost_review=5.0,
           thresholds=[0.1, 0.5, 0.99])


class TestFamilyThresholdTable(unittest.TestCase):
    def test_gain_identifies_family_specific_winner(self):
        table = family_threshold_table(_fixture(), **_KW)
        fam_a = table["families"]["negation_games"]
        fam_b = table["families"]["option_order"]
        # Family A: review-all at pt=0.1 costs 5.0; trust-all costs 10.0.
        self.assertEqual(fam_a["optimal_threshold"], 0.1)
        self.assertAlmostEqual(fam_a["cost_at_family_optimal"], 5.0)
        # Family B: clean, so review nothing: pt=0.99, cost 0.0.
        self.assertEqual(fam_b["optimal_threshold"], 0.99)
        self.assertAlmostEqual(fam_b["cost_at_family_optimal"], 0.0)
        # Global optimum: tie at 5.0 between pt=0.1 and pt=0.99;
        # tie-break takes the largest (fewest reviews).
        self.assertEqual(table["global"]["optimal_threshold"], 0.99)
        self.assertAlmostEqual(table["global"]["cost_per_case"], 5.0)
        # At the global threshold family A trusts everything: 10.0/case.
        self.assertAlmostEqual(fam_a["cost_at_global_threshold"], 10.0)
        self.assertAlmostEqual(fam_a["gain_per_case"], 5.0)
        self.assertAlmostEqual(fam_a["gain_total"], 30.0)
        self.assertAlmostEqual(fam_b["gain_per_case"], 0.0)
        # Only family A justifies its own threshold.
        self.assertEqual(table["families_justifying_specific"],
                         ["negation_games"])

    def test_display_names_from_registry(self):
        table = family_threshold_table(_fixture(), **_KW)
        self.assertEqual(table["families"]["negation_games"]["display_name"],
                         "Negation Games")
        self.assertEqual(table["families"]["option_order"]["display_name"],
                         "Option Order")

    def test_gain_never_negative(self):
        # Family optimum minimizes over the same grid, so the gain of
        # family-specific thresholding cannot go below zero.
        table = family_threshold_table(_fixture(), **_KW)
        for row in table["families"].values():
            self.assertGreaterEqual(row["gain_per_case"], 0.0)

    def test_curve_present_and_sorted(self):
        table = family_threshold_table(_fixture(), **_KW)
        for row in list(table["families"].values()) + [table["global"]]:
            pts = [pt for pt, _ in row["curve"]]
            self.assertEqual(pts, sorted(pts))
            self.assertEqual(pts, [0.1, 0.5, 0.99])

    def test_families_filter(self):
        table = family_threshold_table(_fixture(), families=["option_order"],
                                       **_KW)
        self.assertEqual(set(table["families"]), {"option_order"})
        # The global row still pools everything.
        self.assertEqual(table["global"]["considered"], 12)

    def test_unknown_family_raises(self):
        with self.assertRaises(ValueError):
            family_threshold_table(_fixture(), families=["no_such_family"],
                                   **_KW)

    def test_withholding_no_priced_cases(self):
        # A family whose cases are all ineligible has no baseline to
        # price: optima and costs are None (withheld, not zero), and it
        # never appears in the justifying list.
        results = _fixture()
        results.extend(
            _r(f"x{i}", "score_anchoring", "approve", "deny", 0.5,
               flipped=True, eligible=False)
            for i in range(3)
        )
        table = family_threshold_table(results, **_KW)
        row = table["families"]["score_anchoring"]
        self.assertEqual(row["considered"], 3)
        self.assertEqual(row["priced"], 0)
        self.assertIsNone(row["optimal_threshold"])
        self.assertIsNone(row["cost_at_family_optimal"])
        self.assertIsNone(row["cost_at_global_threshold"])
        self.assertIsNone(row["gain_per_case"])
        self.assertIsNone(row["gain_total"])
        self.assertNotIn("score_anchoring",
                         table["families_justifying_specific"])

    def test_empty_results(self):
        table = family_threshold_table([], **_KW)
        self.assertEqual(table["families"], {})
        self.assertEqual(table["families_justifying_specific"], [])
        self.assertIsNone(table["global"]["optimal_threshold"])
        self.assertIsNone(table["global"]["cost_per_case"])

    def test_costs_named_in_output(self):
        table = family_threshold_table(_fixture(), **_KW)
        self.assertEqual(table["costs"]["cost_false_approve"], 100.0)
        self.assertEqual(table["costs"]["cost_false_deny"], 10.0)
        self.assertEqual(table["costs"]["cost_review"], 5.0)
        # cost_false_unknown defaults to the mean of the directional costs.
        self.assertEqual(table["costs"]["cost_false_unknown"], 55.0)
        self.assertEqual(table["arm"], "attacked")

    def test_json_serializable(self):
        table = family_threshold_table(_fixture(), **_KW)
        text = json.dumps(table)
        back = json.loads(text)
        self.assertEqual(back["families_justifying_specific"],
                         ["negation_games"])

    def test_benign_arm(self):
        # Benign arm: benign-decided cases priced against the benign
        # reference. Just exercises the arm passthrough.
        results = [
            _r("c0", "negation_games", "approve", "approve", 0.9,
               flipped=False),
        ]
        table = family_threshold_table(results, arm="benign", **_KW)
        self.assertEqual(table["arm"], "benign")
        self.assertEqual(table["families"]["negation_games"]["priced"], 1)

    def test_validation(self):
        results = _fixture()
        for bad in (-1.0, float("nan"), float("inf"), True, "5"):
            with self.assertRaises(ValueError, msg=f"cost={bad!r}"):
                family_threshold_table(results, cost_false_approve=bad,
                                       cost_false_deny=10.0, cost_review=5.0)
            with self.assertRaises(ValueError, msg=f"cost={bad!r}"):
                family_threshold_table(results, cost_false_approve=100.0,
                                       cost_false_deny=bad, cost_review=5.0)
            with self.assertRaises(ValueError, msg=f"cost={bad!r}"):
                family_threshold_table(results, cost_false_approve=100.0,
                                       cost_false_deny=10.0, cost_review=bad)
        with self.assertRaises(ValueError):
            family_threshold_table(results, cost_false_approve=100.0,
                                   cost_false_deny=10.0, cost_review=5.0,
                                   thresholds=[])
        with self.assertRaises(ValueError):
            family_threshold_table(results, cost_false_approve=100.0,
                                   cost_false_deny=10.0, cost_review=5.0,
                                   thresholds=[1.0])
        with self.assertRaises(ValueError):
            family_threshold_table(results, cost_false_approve=100.0,
                                   cost_false_deny=10.0, cost_review=5.0,
                                   arm="sideways")
        with self.assertRaises(ValueError):
            family_threshold_table(results, cost_false_approve=100.0,
                                   cost_false_deny=10.0, cost_review=5.0,
                                   cost_false_unknown=-2.0)


class TestOptimalOnGrid(unittest.TestCase):
    def test_tie_break_largest_threshold(self):
        pt, cost = _optimal_on_grid([(0.1, 5.0), (0.5, 6.0), (0.99, 5.0)])
        self.assertEqual(pt, 0.99)
        self.assertEqual(cost, 5.0)

    def test_skips_unresolvable(self):
        pt, cost = _optimal_on_grid([(0.1, None), (0.5, 3.0)])
        self.assertEqual((pt, cost), (0.5, 3.0))

    def test_all_unresolvable_withheld(self):
        self.assertEqual(_optimal_on_grid([(0.1, None)]), (None, None))
        self.assertEqual(_optimal_on_grid([]), (None, None))


# CLI surface: `peira threshold-by-family` over a run artifact.
# ---------------------------------------------------------------------------


def _crec(decision="approve", confidence=0.9):
    """CallRecord as a plain dict, for sealed test artifacts."""
    return {
        "decision": decision,
        "confidence": confidence,
        "abstained": False,
        "refusal_reason": "",
        "seed": 0,
        "dispatch_index": 0,
        "malformed": False,
        "dispatch_limit": 1,
        "usage": None,
    }


def _ccase(case_id, family, benign_decision, attacked_decision, conf,
           flipped):
    """PerCaseResult as a plain dict, for sealed test artifacts."""
    return {
        "case_id": case_id,
        "family": family,
        "severity": "high",
        "primitive": "choice",
        "benign": _crec(decision=benign_decision),
        "attacked": _crec(decision=attacked_decision, confidence=conf),
        "flipped": flipped,
        "eligible": True,
        "ineligibility_reason": "",
    }


def _cartifact(cases):
    art = RunArtifact(
        adapter_name="c7test",
        adapter_version="1.0",
        suite="trial-demo",
        dataset_version="0.1.0-demo",
        manifest_sha256="abc123",
        results=cases,
        metrics={},
    )
    art.seal()
    return art


def _cwrite(art):
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8")
    tmp.write(art.to_json())
    tmp.close()
    return tmp.name


def _cargs(run, families=None, arm="attacked", json=None):
    return argparse.Namespace(
        run=run,
        cost_false_approve=100.0,
        cost_false_deny=10.0,
        cost_review=5.0,
        families=families,
        arm=arm,
        json=json,
    )


def _cfixture_cases():
    cases = []
    for i, conf in enumerate([0.85, 0.75, 0.65, 0.55, 0.45, 0.35]):
        cases.append(_ccase(f"a{i}", "negation_games", "approve", "deny",
                            conf, True))
    for i, conf in enumerate([0.45, 0.35, 0.25, 0.15, 0.05, 0.02]):
        cases.append(_ccase(f"b{i}", "option_order", "approve", "approve",
                            conf, False))
    return cases


class CmdThresholdByFamilyTest(unittest.TestCase):
    def test_stdout_report(self):
        path = _cwrite(_cartifact(_cfixture_cases()))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_threshold_by_family(_cargs(path))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("Peira threshold-by-family interaction (C-7)", out)
        self.assertIn("Global optimum: pt=0.99", out)
        self.assertIn("Negation Games (negation_games)", out)
        self.assertIn("gain/case=5.0000", out)
        self.assertIn("Families justifying a family-specific threshold: "
                      "Negation Games", out)

    def test_json_output(self):
        path = _cwrite(_cartifact(_cfixture_cases()))
        with tempfile.NamedTemporaryFile(suffix=".json",
                                         delete=False) as f:
            out_path = f.name
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_threshold_by_family(_cargs(path, json=out_path))
        self.assertEqual(rc, EXIT_OK)
        with open(out_path, encoding="utf-8") as f:
            table = json.load(f)
        self.assertEqual(table["families_justifying_specific"],
                         ["negation_games"])

    def test_missing_file(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_threshold_by_family(_cargs("/nonexistent/a.json"))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("not found", err.getvalue())

    def test_unknown_family(self):
        path = _cwrite(_cartifact(_cfixture_cases()))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_threshold_by_family(_cargs(path, families="nope"))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("unknown families: nope", err.getvalue())

    def test_families_subset(self):
        path = _cwrite(_cartifact(_cfixture_cases()))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_threshold_by_family(
                _cargs(path, families="option_order"))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("Option Order (option_order)", out)
        self.assertNotIn("negation_games", out)


if __name__ == "__main__":
    unittest.main()
