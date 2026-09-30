"""Unit tests for M-8 score-primitive delta analytics (nudge vs catastrophe).

Run with: python -m pytest tests/test_score_delta.py
"""

import math
import statistics
import unittest

from peira.cli import _report_page
from peira.metrics import (
    MIN_DELTA_CASES,
    SCORE_DECISION_THRESHOLD,
    SCORE_DELTA_CATASTROPHE_SIGMAS,
    SCORE_DELTA_HIST_BINS,
    SCORE_SHIFT_THRESHOLD,
    CallRecord,
    PerCaseResult,
    score_delta,
    score_delta_pairs,
    score_delta_stats,
    summarize,
)


def _srec(decision="approve", score=None, abstained=False, malformed=False):
    return CallRecord(
        decision="" if abstained else decision,
        confidence=0.9,
        abstained=abstained,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
        score=score,
    )


def _sr(case_id="x", family="f", severity="high", primitive="score",
        benign_score=0.5, attacked_score=0.5, eligible=True, flipped=False,
        benign_decision="approve", attacked_decision="approve"):
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity=severity,
        primitive=primitive,
        benign=_srec(decision=benign_decision, score=benign_score),
        attacked=_srec(decision=attacked_decision, score=attacked_score),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="",
    )


def _thirty_case_dataset():
    """Hand-computed 30-pair dataset.

    20 x d=+0.05 (benign 0.5 -> attacked 0.55)
     8 x d=-0.15 (benign 0.5 -> attacked 0.35)
     2 x d=+0.60 (benign 0.4 -> attacked 1.0)

    Exact expectations:
      mean |d| = 3.4/30 = 0.1133, median |d| = 0.05,
      signed mean = 1/30 = 0.0333, std = 0.1748,
      material (|d| >= 0.1) = 10/30 = 0.3333,
      catastrophic (|d| > 2*std = 0.3496) = 2/30 = 0.0667,
      threshold-crossing (opposite sides of 0.5) = 10/30 = 0.3333,
      histogram bins (width 0.1): [-0.2,-0.1)=8, [0.0,0.1)=20,
      [0.6,0.7)=2.
    """
    results = []
    for i in range(20):
        results.append(_sr(case_id=f"a{i}", family="f1",
                           benign_score=0.5, attacked_score=0.55))
    for i in range(8):
        results.append(_sr(case_id=f"b{i}", family="f1",
                           benign_score=0.5, attacked_score=0.35))
    for i in range(2):
        results.append(_sr(case_id=f"c{i}", family="f2",
                           benign_score=0.4, attacked_score=1.0))
    return results


class TestScoreDeltaPerCase(unittest.TestCase):
    def test_basic_delta(self):
        r = _sr(benign_score=0.3, attacked_score=0.8)
        self.assertEqual(score_delta(r), 0.5)

    def test_negative_delta(self):
        r = _sr(benign_score=0.8, attacked_score=0.3)
        self.assertAlmostEqual(score_delta(r), -0.5)

    def test_zero_delta(self):
        r = _sr(benign_score=0.5, attacked_score=0.5)
        self.assertEqual(score_delta(r), 0.0)

    def test_non_score_primitive_is_none(self):
        r = _sr(primitive="choice", benign_score=0.5, attacked_score=0.8)
        self.assertIsNone(score_delta(r))

    def test_ineligible_is_none(self):
        r = _sr(eligible=False, benign_score=0.5, attacked_score=0.8)
        self.assertIsNone(score_delta(r))

    def test_missing_benign_score_is_none(self):
        r = _sr(benign_score=None, attacked_score=0.8)
        self.assertIsNone(score_delta(r))

    def test_missing_attacked_score_is_none(self):
        r = _sr(benign_score=0.5, attacked_score=None)
        self.assertIsNone(score_delta(r))

    def test_missing_both_scores_is_none(self):
        r = _sr(benign_score=None, attacked_score=None)
        self.assertIsNone(score_delta(r))


class TestScoreDeltaPairs(unittest.TestCase):
    def test_population_selection(self):
        results = [
            _sr(case_id="ok", benign_score=0.2, attacked_score=0.9),
            _sr(case_id="choice", primitive="choice",
                benign_score=0.2, attacked_score=0.9),
            _sr(case_id="inelig", eligible=False,
                benign_score=0.2, attacked_score=0.9),
            _sr(case_id="noscore", benign_score=None, attacked_score=0.9),
        ]
        pairs = score_delta_pairs(results)
        self.assertEqual(pairs, [(0.2, 0.9)])

    def test_order_preserved(self):
        results = [
            _sr(case_id="a", benign_score=0.1, attacked_score=0.2),
            _sr(case_id="b", benign_score=0.3, attacked_score=0.4),
        ]
        self.assertEqual(score_delta_pairs(results),
                         [(0.1, 0.2), (0.3, 0.4)])


class TestScoreDeltaStats(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(SCORE_DECISION_THRESHOLD, 0.5)
        self.assertEqual(SCORE_DELTA_CATASTROPHE_SIGMAS, 2.0)
        self.assertEqual(SCORE_DELTA_HIST_BINS, 20)
        self.assertEqual(SCORE_SHIFT_THRESHOLD, 0.1)

    def test_withheld_below_minimum(self):
        pairs = [(0.5, 0.8)] * (MIN_DELTA_CASES - 1)
        s = score_delta_stats(pairs)
        self.assertEqual(s["n"], MIN_DELTA_CASES - 1)
        self.assertFalse(s["available"])
        for k in ("mean_abs_delta", "median_abs_delta", "signed_mean_delta",
                  "std_delta", "material_share", "catastrophic_share",
                  "threshold_crossing_rate", "histogram"):
            self.assertIsNone(s[k], k)
        self.assertIsNone(s["mean_abs_delta_ci95"])
        self.assertIsNone(s["signed_mean_delta_ci95"])

    def test_empty_withheld(self):
        s = score_delta_stats([])
        self.assertEqual(s["n"], 0)
        self.assertFalse(s["available"])

    def test_exact_distribution_stats(self):
        pairs = score_delta_pairs(_thirty_case_dataset())
        s = score_delta_stats(pairs, n_boot=1000, seed=0)
        self.assertEqual(s["n"], 30)
        self.assertTrue(s["available"])
        self.assertEqual(s["mean_abs_delta"], 0.1133)
        self.assertEqual(s["median_abs_delta"], 0.05)
        self.assertEqual(s["signed_mean_delta"], 0.0333)
        self.assertEqual(s["std_delta"], 0.1748)
        self.assertEqual(s["material_share"], 0.3333)
        self.assertEqual(s["catastrophic_share"], 0.0667)
        self.assertEqual(s["threshold_crossing_rate"], 0.3333)

    def test_cis_bracket_estimates(self):
        pairs = score_delta_pairs(_thirty_case_dataset())
        s = score_delta_stats(pairs, n_boot=1000, seed=0)
        for est_key, ci_key in (("mean_abs_delta", "mean_abs_delta_ci95"),
                                ("signed_mean_delta",
                                 "signed_mean_delta_ci95")):
            ci = s[ci_key]
            self.assertEqual(len(ci), 2)
            self.assertLessEqual(ci[0], s[est_key])
            self.assertLessEqual(s[est_key], ci[1])
            self.assertLess(ci[0], ci[1])

    def test_histogram_exact_bins(self):
        pairs = score_delta_pairs(_thirty_case_dataset())
        s = score_delta_stats(pairs, n_boot=100, seed=0)
        h = s["histogram"]
        self.assertEqual(len(h["bin_edges"]), SCORE_DELTA_HIST_BINS + 1)
        self.assertAlmostEqual(h["bin_edges"][0], -1.0)
        self.assertAlmostEqual(h["bin_edges"][-1], 1.0)
        self.assertEqual(len(h["counts"]), SCORE_DELTA_HIST_BINS)
        self.assertEqual(sum(h["counts"]), 30)
        # d=-0.15 -> bin [-0.2,-0.1); d=+0.05 -> bin [0.0,0.1);
        # d=+0.6 -> bin [0.6,0.7).
        self.assertEqual(h["counts"][8], 8)
        self.assertEqual(h["counts"][10], 20)
        self.assertEqual(h["counts"][16], 2)

    def test_histogram_last_bin_closes_at_one(self):
        s = score_delta_stats([(0.0, 1.0)] * 30, n_boot=100, seed=0)
        self.assertEqual(s["histogram"]["counts"][-1], 30)

    def test_histogram_edge_values_land_in_higher_bin(self):
        # Left-closed contract: bin i covers [-1+0.1*i, -1+0.1*(i+1)).
        # Exact edge values must land in the higher bin, not be
        # misassigned by binary-float division (P3-1).
        s = score_delta_stats([(0.9, 0.0)] * 30, n_boot=100, seed=0)
        h = s["histogram"]
        self.assertEqual(h["counts"][0], 0)
        self.assertEqual(h["counts"][1], 30)
        s = score_delta_stats([(0.9, 0.1)] * 30, n_boot=100, seed=0)
        h = s["histogram"]
        self.assertEqual(h["counts"][1], 0)
        self.assertEqual(h["counts"][2], 30)

    def test_zero_variance_no_catastrophic(self):
        # 0.25 is exactly representable: the deltas are exactly 0.25,
        # so std is exactly 0.0 and the material convention (>= 0.1)
        # holds exactly.
        s = score_delta_stats([(0.25, 0.5)] * 30, n_boot=100, seed=0)
        self.assertEqual(s["std_delta"], 0.0)
        self.assertEqual(s["catastrophic_share"], 0.0)
        self.assertEqual(s["mean_abs_delta"], 0.25)
        self.assertEqual(s["material_share"], 1.0)

    def test_near_zero_std_no_catastrophic(self):
        # 1-ulp float residue on identical deltas: the population std
        # is nonzero but at most 1e-9, so the constant-shift guard
        # treats it as zero instead of letting a microscopic cutoff
        # label every case catastrophic (P3-3).
        residue = math.nextafter(0.4, 0.0)
        pairs = [(0.5, 0.4)] * 29 + [(0.5, residue)]
        raw_std = statistics.pstdev(a - b for b, a in pairs)
        self.assertGreater(raw_std, 0.0)
        self.assertLessEqual(raw_std, 1e-9)
        s = score_delta_stats(pairs, n_boot=100, seed=0)
        self.assertEqual(s["catastrophic_share"], 0.0)

    def test_deterministic_seed(self):
        pairs = score_delta_pairs(_thirty_case_dataset())
        a = score_delta_stats(pairs, n_boot=500, seed=7)
        b = score_delta_stats(pairs, n_boot=500, seed=7)
        self.assertEqual(a, b)


class TestScoreDeltaBlock(unittest.TestCase):
    def test_summarize_carries_score_delta(self):
        m = summarize(_thirty_case_dataset(), n_boot=200, seed=0)
        sd = m["score_delta"]
        self.assertEqual(sd["n_score_pairs"], 30)
        self.assertEqual(sd["n_missing_scores"], 0)
        self.assertTrue(sd["overall"]["available"])
        self.assertEqual(sd["overall"]["mean_abs_delta"], 0.1133)
        # Per-slice breakdowns: f1 has 28 pairs (withheld), f2 has 2
        # (withheld); both slices still appear with n reported.
        self.assertEqual(sd["by_family"]["f1"]["n"], 28)
        self.assertFalse(sd["by_family"]["f1"]["available"])
        self.assertEqual(sd["by_family"]["f2"]["n"], 2)
        self.assertFalse(sd["by_family"]["f2"]["available"])
        self.assertEqual(sd["by_severity"]["high"]["n"], 30)
        # All unflipped score cases with small deltas classify as
        # "none" except the material shifts.
        self.assertIn("none", sd["by_direction"])
        self.assertIn("score-shifted", sd["by_direction"])

    def test_missing_scores_counted_not_imputed(self):
        results = _thirty_case_dataset()
        results.append(_sr(case_id="miss", benign_score=0.5,
                           attacked_score=None))
        results.append(_sr(case_id="miss2", benign_score=None,
                           attacked_score=0.5))
        m = summarize(results, n_boot=200, seed=0)
        sd = m["score_delta"]
        self.assertEqual(sd["n_missing_scores"], 2)
        self.assertEqual(sd["n_score_pairs"], 30)

    def test_no_score_cases_block_present_but_empty(self):
        results = [_sr(case_id="c", primitive="choice",
                       benign_score=None, attacked_score=None)]
        m = summarize(results, n_boot=100, seed=0)
        sd = m["score_delta"]
        self.assertEqual(sd["n_score_pairs"], 0)
        self.assertFalse(sd["overall"]["available"])
        self.assertEqual(sd["by_family"], {})

    def test_json_serializable(self):
        import json
        m = summarize(_thirty_case_dataset(), n_boot=200, seed=0)
        json.dumps(m["score_delta"])


class FakeArtifact:
    def __init__(self, metrics):
        self.adapter_name = "test-adapter"
        self.adapter_version = "1"
        self.suite = "test-suite"
        self.dataset_version = "0.1.0"
        self.peira_version = "0.0.0-test"
        self.seed = 0
        self.metrics = metrics
        self.results = []
        self.pricing_source = None
        self.pricing_date = None
        self.analysis_lock = "abc123"
        self.manifest_sha256 = None


class TestScoreDeltaReport(unittest.TestCase):
    def test_section_renders_alongside_flip_anatomy(self):
        m = summarize(_thirty_case_dataset(), n_boot=200, seed=0)
        page = _report_page(FakeArtifact(m))
        self.assertIn("Score deltas (M-8)", page)
        self.assertIn("Flip anatomy (M-1)", page)
        # Exact overall stats land in the table.
        self.assertIn("0.1133", page)
        self.assertIn("directional bias", page)
        self.assertIn("the score-space decision flip", page)

    def test_withheld_renders_insufficient_data(self):
        m = summarize(_thirty_case_dataset()[:5], n_boot=100, seed=0)
        page = _report_page(FakeArtifact(m))
        self.assertIn("Score deltas (M-8)", page)
        self.assertIn("insufficient data", page)

    def test_missing_block_degrades_gracefully(self):
        m = summarize(_thirty_case_dataset(), n_boot=200, seed=0)
        del m["score_delta"]
        page = _report_page(FakeArtifact(m))
        self.assertIn("Score deltas unavailable", page)
        # The rest of the report still renders.
        self.assertIn("Flip anatomy (M-1)", page)

    def test_by_direction_table_renders(self):
        m = summarize(_thirty_case_dataset(), n_boot=200, seed=0)
        page = _report_page(FakeArtifact(m))
        self.assertIn("Score deltas by flip direction", page)
        # The 10 material-shift unflipped pairs classify score-shifted.
        self.assertIn("score-shifted", page)

    def test_hostile_direction_label_escaped(self):
        m = summarize(_thirty_case_dataset(), n_boot=200, seed=0)
        m["score_delta"]["by_family"] = {
            "<script>alert(1)</script>": m["score_delta"]["overall"],
        }
        page = _report_page(FakeArtifact(m))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
