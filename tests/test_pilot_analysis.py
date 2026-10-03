"""Tests for the pilot analysis framework (python/peira/pilot_analysis.py).

Uses synthetic dashboard payloads (dicts shaped like
``dashboard.run_to_dashboard`` output) so the pure analysis functions
are tested without building sealed artifacts.
"""

import unittest

from peira.pilot_analysis import (
    family_matrix,
    attack_effectiveness,
    ranking_analysis,
    cost_effectiveness,
)


def _rec(name, families, headline=None):
    """Minimal analysis record with a synthetic dashboard payload."""
    return {
        "adapter_name": name,
        "adapter_version": "1.0",
        "run_id": f"run-{name}",
        "dashboard": {
            "headline": headline or {},
            "families": families,
        },
    }


def _fam(asr, n=100, n_elig=90):
    return {
        "asr": asr,
        "asr_ci95": [asr - 0.05, asr + 0.05],
        "n": n,
        "n_eligible": n_elig,
    }


class TestFamilyMatrix(unittest.TestCase):
    def test_matrix_shape(self):
        recs = [
            _rec("a", {"f1": _fam(0.2), "f2": _fam(0.4)}),
            _rec("b", {"f1": _fam(0.3), "f2": _fam(0.5)}),
        ]
        m = family_matrix(recs)
        self.assertEqual(m["families"], ["f1", "f2"])
        self.assertEqual(len(m["rows"]), 2)
        self.assertAlmostEqual(m["column_mean_asr"]["f1"], 0.25)
        self.assertAlmostEqual(m["column_mean_asr"]["f2"], 0.45)

    def test_missing_family_cell(self):
        # Model b has no f2; the column mean uses only model a.
        recs = [
            _rec("a", {"f1": _fam(0.2), "f2": _fam(0.4)}),
            _rec("b", {"f1": _fam(0.3)}),
        ]
        m = family_matrix(recs)
        self.assertEqual(m["families"], ["f1", "f2"])
        self.assertIsNone(m["rows"][1]["cells"]["f2"]["asr"])
        self.assertAlmostEqual(m["column_mean_asr"]["f2"], 0.4)

    def test_empty(self):
        m = family_matrix([])
        self.assertEqual(m["families"], [])
        self.assertEqual(m["rows"], [])

    def test_deterministic_order(self):
        recs = [
            _rec("zeta", {"f1": _fam(0.2)}),
            _rec("alpha", {"f1": _fam(0.3)}),
        ]
        m = family_matrix(recs)
        # Input order preserved (load_pilot_runs sorts; the matrix does not).
        self.assertEqual(m["rows"][0]["adapter_name"], "zeta")


class TestAttackEffectiveness(unittest.TestCase):
    def test_ranking(self):
        recs = [
            _rec("a", {"f1": _fam(0.8), "f2": _fam(0.2), "f3": _fam(0.5)}),
            _rec("b", {"f1": _fam(0.6), "f2": _fam(0.1), "f3": _fam(0.4)}),
        ]
        eff = attack_effectiveness(recs)
        ranked = [r["family"] for r in eff["most_effective_attacks"]]
        self.assertEqual(ranked, ["f1", "f3", "f2"])

    def test_per_model_weakest(self):
        recs = [
            _rec("a", {"f1": _fam(0.8), "f2": _fam(0.2), "f3": _fam(0.5)}),
        ]
        eff = attack_effectiveness(recs)
        pm = eff["per_model"][0]
        self.assertEqual(pm["adapter_name"], "a")
        self.assertEqual(pm["weakest_families"][0]["family"], "f1")
        self.assertEqual(pm["strongest_families"][0]["family"], "f2")


class TestRankingAnalysis(unittest.TestCase):
    def _recs(self):
        # a is consistently better (lower ASR) than b across families.
        return [
            _rec("a", {"f1": _fam(0.1), "f2": _fam(0.2), "f3": _fam(0.15)}),
            _rec("b", {"f1": _fam(0.5), "f2": _fam(0.6), "f3": _fam(0.55)}),
            _rec("c", {"f1": _fam(0.3), "f2": _fam(0.35), "f3": _fam(0.32)}),
        ]

    def test_mean_ranks(self):
        r = ranking_analysis(self._recs())
        ranks = {m["adapter_name"]: m["mean_rank"] for m in r["mean_ranks"]}
        self.assertLess(ranks["a"], ranks["c"])
        self.assertLess(ranks["c"], ranks["b"])
        self.assertEqual(r["n_models"], 3)
        self.assertEqual(r["n_blocks"], 3)

    def test_friedman_detects_difference(self):
        r = ranking_analysis(self._recs())
        # With a strictly better model across 3 blocks, Friedman should
        # reject at 0.05.
        self.assertIsNotNone(r["friedman_p_value"])
        self.assertLess(r["friedman_p_value"], 0.05)

    def test_nemenyi_cd_present(self):
        r = ranking_analysis(self._recs())
        self.assertIsNotNone(r["nemenyi_cd_05"])
        self.assertGreater(r["nemenyi_cd_05"], 0)

    def test_needs_two_models(self):
        r = ranking_analysis([_rec("a", {"f1": _fam(0.1)})])
        self.assertIn("error", r)

    def test_ties_get_average_rank(self):
        recs = [
            _rec("a", {"f1": _fam(0.2)}),
            _rec("b", {"f1": _fam(0.2)}),
        ]
        r = ranking_analysis(recs)
        ranks = {m["adapter_name"]: m["mean_rank"] for m in r["mean_ranks"]}
        self.assertAlmostEqual(ranks["a"], 1.5)
        self.assertAlmostEqual(ranks["b"], 1.5)


class TestCostEffectiveness(unittest.TestCase):
    def _rec(self, name, cost, n_elig=1000, benign_acc=0.9, asr=0.2):
        return _rec(
            name,
            {"f1": _fam(asr, n=n_elig, n_elig=n_elig)},
            headline={
                "total_cost_usd": cost,
                "n_eligible": n_elig,
                "benign_accuracy": benign_acc,
                "asr_conditional": asr,
            },
        )

    def test_cost_per_decision(self):
        recs = [self._rec("a", 10.0), self._rec("b", 20.0)]
        ce = cost_effectiveness(recs)
        rows = {r["adapter_name"]: r for r in ce["rows"]}
        self.assertAlmostEqual(rows["a"]["cost_per_decision"], 0.01)
        self.assertAlmostEqual(rows["b"]["cost_per_decision"], 0.02)

    def test_cost_per_correct(self):
        # n_elig=1000, benign_acc=0.9, asr=0.2:
        # n_correct = 1000*0.9 + 1000*0.8 = 1700. cost 10 -> 10/1700.
        recs = [self._rec("a", 10.0)]
        ce = cost_effectiveness(recs)
        self.assertAlmostEqual(
            ce["rows"][0]["cost_per_correct"], 10.0 / 1700.0
        )

    def test_sorted_by_cost_per_correct(self):
        recs = [self._rec("expensive", 100.0), self._rec("cheap", 1.0)]
        ce = cost_effectiveness(recs)
        self.assertEqual(ce["rows"][0]["adapter_name"], "cheap")

    def test_missing_cost(self):
        recs = [_rec("a", {"f1": _fam(0.2)}, headline={})]
        ce = cost_effectiveness(recs)
        self.assertIsNone(ce["rows"][0]["cost_per_decision"])
        self.assertIsNone(ce["rows"][0]["cost_per_correct"])

    def test_flips_prevented_relative(self):
        recs = [self._rec("good", 10.0, asr=0.1), self._rec("bad", 10.0, asr=0.5)]
        ce = cost_effectiveness(recs)
        rows = {r["adapter_name"]: r for r in ce["rows"]}
        # Worst ASR is 0.5 (bad). good prevents 0.4 points per $10.
        self.assertAlmostEqual(rows["good"]["flips_prevented_per_dollar"], 0.04)
        self.assertAlmostEqual(rows["bad"]["flips_prevented_per_dollar"], 0.0)


if __name__ == "__main__":
    unittest.main()
