"""Tests for peira.lottery (R-09 leave-one-family-out ranking stability)."""

import unittest

from peira.lottery import (
    kendall_tau,
    lottery_analysis,
    pairwise_swap_fraction,
    rank_runs,
    stability_verdict,
)
from peira.metrics import CallRecord, PerCaseResult


def _rec(decision="approve", malformed=False):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _case(family, flipped, case_id):
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec(decision="approve"),
        attacked=_rec(decision="deny" if flipped else "approve"),
        flipped=flipped,
        eligible=True,
    )


def _make_run(family_asr, per_family=200):
    """Build a run's results with the given per-family ASR.

    200 cases per family keeps every run ranking-eligible, including
    under leave-one-out (2 families x 200 = 400 total; removing one
    leaves 200, which still clears the >= 200 total and >= 20
    per-family gates; benign accuracy is 1.0, malformed rate 0).
    """
    results = []
    for fam, asr in family_asr.items():
        n_flip = int(round(asr * per_family))
        for i in range(per_family):
            results.append(_case(fam, i < n_flip, f"{fam}-{i}"))
    return results


class TestKendallTau(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(
            kendall_tau(["a", "b", "c"], ["a", "b", "c"]), 1.0
        )

    def test_reversed(self):
        self.assertEqual(
            kendall_tau(["a", "b", "c"], ["c", "b", "a"]), -1.0
        )

    def test_single_swap(self):
        # One discordant pair out of three: (2-1)/3.
        tau = kendall_tau(["a", "b", "c"], ["a", "c", "b"])
        self.assertAlmostEqual(tau, 1 / 3, places=9)

    def test_partial_overlap(self):
        # Only a,b common and in the same order.
        self.assertEqual(kendall_tau(["a", "b", "c"], ["a", "b"]), 1.0)

    def test_insufficient_overlap_none(self):
        self.assertIsNone(kendall_tau(["a"], ["a"]))
        self.assertIsNone(kendall_tau(["a", "b"], ["c", "d"]))
        self.assertIsNone(kendall_tau([], []))

    def test_two_items(self):
        self.assertEqual(kendall_tau(["a", "b"], ["b", "a"]), -1.0)
        self.assertEqual(kendall_tau(["a", "b"], ["a", "b"]), 1.0)


class TestPairwiseSwapFraction(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(
            pairwise_swap_fraction(["a", "b", "c"], ["a", "b", "c"]), 0.0
        )

    def test_reversed(self):
        self.assertEqual(
            pairwise_swap_fraction(["a", "b", "c"], ["c", "b", "a"]), 1.0
        )

    def test_single_swap(self):
        self.assertAlmostEqual(
            pairwise_swap_fraction(["a", "b", "c"], ["a", "c", "b"]),
            1 / 3,
            places=9,
        )

    def test_insufficient_overlap_none(self):
        self.assertIsNone(pairwise_swap_fraction(["a"], ["a"]))


class TestRankRuns(unittest.TestCase):
    def test_orders_by_asr_ascending(self):
        runs = {
            "run-high": _make_run({"f1": 0.8, "f2": 0.8}),
            "run-low": _make_run({"f1": 0.1, "f2": 0.1}),
            "run-mid": _make_run({"f1": 0.5, "f2": 0.5}),
        }
        ranked = rank_runs(runs, ["f1", "f2"])
        self.assertEqual(
            [r.run_id for r in ranked], ["run-low", "run-mid", "run-high"]
        )
        self.assertTrue(all(r.eligible for r in ranked))
        self.assertAlmostEqual(ranked[0].asr, 0.1, places=9)

    def test_ties_broken_by_run_id(self):
        runs = {
            "b-run": _make_run({"f1": 0.3, "f2": 0.3}),
            "a-run": _make_run({"f1": 0.3, "f2": 0.3}),
        }
        ranked = rank_runs(runs, ["f1", "f2"])
        self.assertEqual([r.run_id for r in ranked], ["a-run", "b-run"])

    def test_filters_to_given_families(self):
        runs = {"r": _make_run({"f1": 0.0, "f2": 1.0})}
        ranked = rank_runs(runs, ["f1"])
        self.assertAlmostEqual(ranked[0].asr, 0.0, places=9)

    def test_ineligible_run_excluded_with_reasons(self):
        # Only 10 eligible cases per family: fails the >= 20 gate and
        # the >= 200 total gate.
        small = []
        for fam in ("f1", "f2"):
            for i in range(10):
                small.append(_case(fam, False, f"{fam}-{i}"))
        ranked = rank_runs({"tiny": small}, ["f1", "f2"])
        self.assertFalse(ranked[0].eligible)
        self.assertIsNone(ranked[0].asr)
        self.assertTrue(ranked[0].reasons)

    def test_empty_families_raises(self):
        with self.assertRaises(ValueError):
            rank_runs({"r": _make_run({"f1": 0.5})}, [])

    def test_empty_run_id_raises(self):
        with self.assertRaises(ValueError):
            rank_runs({"": _make_run({"f1": 0.5})}, ["f1"])


class TestStabilityVerdict(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(stability_verdict(1.0), "stable")
        self.assertEqual(stability_verdict(0.9), "stable")
        self.assertEqual(stability_verdict(0.8999), "mostly stable")
        self.assertEqual(stability_verdict(0.7), "mostly stable")
        self.assertEqual(stability_verdict(0.6999), "fragile")
        self.assertEqual(stability_verdict(-1.0), "fragile")
        self.assertEqual(stability_verdict(None), "undefined")


class TestLotteryAnalysis(unittest.TestCase):
    def test_stable_rankings_index_one(self):
        # Every run has the same ASR in every family: removing any
        # family cannot move the ranking.
        runs = {
            "a": _make_run({"f1": 0.1, "f2": 0.1}),
            "b": _make_run({"f1": 0.5, "f2": 0.5}),
            "c": _make_run({"f1": 0.9, "f2": 0.9}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        self.assertEqual(out["full_ranking"], ["a", "b", "c"])
        self.assertEqual(out["lottery_index"], 1.0)
        self.assertEqual(out["verdict"], "stable")
        self.assertEqual(out["min_tau"], 1.0)
        for fam in ("f1", "f2"):
            self.assertEqual(out["per_family"][fam]["tau"], 1.0)
            self.assertEqual(out["per_family"][fam]["swap_fraction"], 0.0)
            self.assertEqual(out["per_family"][fam]["max_rank_displacement"], 0)

    def test_detects_influential_family(self):
        # A: strong on f1, weak on f2. B: weak on f1, strong on f2.
        # C: middling on both. Full ranking ties A/B on 0.25, broken
        # by run id -> [a, b, c].
        runs = {
            "a": _make_run({"f1": 0.0, "f2": 0.5}),
            "b": _make_run({"f1": 0.5, "f2": 0.0}),
            "c": _make_run({"f1": 0.4, "f2": 0.4}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        self.assertEqual(out["full_ranking"], ["a", "b", "c"])
        # Remove f1 -> [b, c, a]: pairs (a,b) and (a,c) discordant.
        # (taus are rounded to 4 decimals in the report dict.)
        self.assertAlmostEqual(
            out["per_family"]["f1"]["tau"], round(-1 / 3, 4), places=9
        )
        # Remove f2 -> [a, c, b]: only (b,c) discordant.
        self.assertAlmostEqual(
            out["per_family"]["f2"]["tau"], round(1 / 3, 4), places=9
        )
        self.assertAlmostEqual(out["lottery_index"], 0.0, places=9)
        self.assertAlmostEqual(out["min_tau"], round(-1 / 3, 4), places=9)
        self.assertEqual(out["most_influential_family"], "f1")
        self.assertEqual(
            out["per_family"]["f1"]["ranking"], ["b", "c", "a"]
        )
        self.assertEqual(
            out["per_family"]["f1"]["max_rank_displacement"], 2
        )

    def test_leave_one_out_regates_eligibility(self):
        # Run "thin" has 200 eligible cases in f1 but only 25 in f2:
        # eligible overall (225 total >= 200, both families >= 20),
        # but dropping f1 leaves it under the total gate -> it drops
        # out of that reduced ranking honestly.
        thin = _make_run({"f1": 0.2}, per_family=200)
        for i in range(25):
            thin.append(_case("f2", False, f"f2-{i}"))
        runs = {
            "thin": thin,
            "solid": _make_run({"f1": 0.6, "f2": 0.6}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        # Full ranking: thin (asr ~0.178) beats solid (0.6).
        self.assertEqual(out["full_ranking"], ["thin", "solid"])
        drop_f1 = out["per_family"]["f1"]
        self.assertEqual(drop_f1["ranking"], ["solid"])
        self.assertEqual(drop_f1["dropped_runs"], ["thin"])
        # Only "solid" is common to both rankings: tau undefined.
        self.assertIsNone(drop_f1["tau"])
        # f2's removal keeps both runs: tau defined.
        self.assertIsNotNone(out["per_family"]["f2"]["tau"])

    def test_result_is_json_serializable(self):
        import json

        runs = {
            "a": _make_run({"f1": 0.2, "f2": 0.3}),
            "b": _make_run({"f1": 0.7, "f2": 0.6}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        json.dumps(out)  # must not raise

    def test_empty_families_raises(self):
        with self.assertRaises(ValueError):
            lottery_analysis({"a": _make_run({"f1": 0.5})}, [])

    def test_single_family(self):
        # Degenerate but honest: one family, removing it leaves no
        # families -> rank_runs raises ValueError. Surface it plainly.
        runs = {"a": _make_run({"f1": 0.2})}
        with self.assertRaises(ValueError):
            lottery_analysis(runs, ["f1"])


if __name__ == "__main__":
    unittest.main()
