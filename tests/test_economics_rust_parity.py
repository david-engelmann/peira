"""Rust-parity tests for the economics numeric core (rust-max slice 4).

Each test compares the dispatched public function against its
pure-Python ``_xxx_py`` reference twin with assertAlmostEqual(places=12).
The twins are the PEIRA_NO_RUST=1 fallback, so this file proves the Rust
core agrees with the fallback path on real-shaped data.
"""

import unittest

from peira._rust import _impl as _rust
from peira.adapters.base import CallUsage
from peira.economics import (
    CostScenario,
    _attacker_cost_multiplier_py,
    _defense_curve_py,
    _drummond_holte_points_py,
    _e_attacked_py,
    _gordon_loeb_tripwire_py,
    _mean_cost_per_decision_py,
    _optimal_threshold_py,
    _pareto_frontier_py,
    _risk_coverage_curve_py,
    attacker_cost_multiplier,
    defense_curve,
    drummond_holte_curves,
    e_attacked,
    gordon_loeb_tripwire,
    load_cost_scenario,
    optimal_threshold,
    pareto_frontier,
    risk_coverage_curve,
)
from peira.metrics import CallRecord, PerCaseResult


def _rec(decision, confidence=0.9, cost=0.001, abstained=False,
         malformed=False):
    return CallRecord(
        decision=decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason="",
        usage=CallUsage(
            model="m", tokens_in=100, tokens_out=10,
            latency_ms=5.0, cost_usd=cost,
        ),
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _result(case_id, benign_decision, attacked_decision, flipped,
            confidence=0.9, cost=0.001, eligible=True,
            a_abstained=False, a_malformed=False):
    return PerCaseResult(
        case_id=case_id,
        family="literal_reading",
        severity="medium",
        primitive="choice",
        benign=_rec(benign_decision, cost=cost),
        attacked=_rec(attacked_decision, confidence=confidence, cost=cost,
                      abstained=a_abstained, malformed=a_malformed),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "benign_wrong",
    )


def _mixed_results():
    """20 eligible cases: flips in several directions, confidences
    spread across [0.05, 0.95], one abstain, one malformed."""
    out = []
    specs = [
        ("c00", "deny", "approve", True, 0.95),   # jailbreak
        ("c01", "deny", "approve", True, 0.80),
        ("c02", "deny", "approve", True, 0.60),
        ("c03", "approve", "deny", True, 0.70),   # wrong block
        ("c04", "approve", "deny", True, 0.30),
        ("c05", "approve", "approve", False, 0.90),
        ("c06", "approve", "approve", False, 0.85),
        ("c07", "deny", "deny", False, 0.75),
        ("c08", "deny", "deny", False, 0.65),
        ("c09", "approve", "approve", False, 0.55),
        ("c10", "deny", "approve", True, 0.45),
        ("c11", "approve", "deny", True, 0.40),
        ("c12", "approve", "approve", False, 0.35),
        ("c13", "deny", "deny", False, 0.25),
        ("c14", "deny", "approve", True, 0.15),
        ("c15", "approve", "approve", False, 0.10),
        ("c16", "deny", "deny", False, 0.05),
        ("c17", "approve", "approve", False, 0.50),
    ]
    for cid, b, a, f, conf in specs:
        out.append(_result(cid, b, a, f, confidence=conf,
                           cost=0.001 + 0.0001 * int(cid[1:])))
    out.append(_result("c18", "approve", "abstain", False,
                       a_abstained=True))
    out.append(_result("c19", "deny", "deny", False, a_malformed=True))
    return out


def _scenario():
    return load_cost_scenario("standard")


class BackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        # Records which backend the parity suite exercised; the suite
        # must run in both modes (Rust-active and PEIRA_NO_RUST=1).
        # Also verifies the Rust gate: clean data passes, dirty data
        # (None cost, non-finite cost, lone-surrogate string) falls back.
        from peira.economics import _require_economics_rust_input
        print(f"\n[parity] rust backend active: {_rust is not None}")
        results = _mixed_results()
        s = _scenario()
        self.assertTrue(_require_economics_rust_input(results, s))

        def _with_dirty_cost(cost):
            dirty = _mixed_results()
            r = dirty[0]
            usage = CallUsage(
                model="m", tokens_in=100, tokens_out=10,
                latency_ms=5.0, cost_usd=cost,
            )
            attacked = CallRecord(
                decision=r.attacked.decision,
                confidence=r.attacked.confidence,
                abstained=r.attacked.abstained,
                refusal_reason="",
                usage=usage,
                seed=0,
                dispatch_index=0,
                malformed=r.attacked.malformed,
            )
            dirty[0] = PerCaseResult(
                case_id=r.case_id,
                family=r.family,
                severity=r.severity,
                primitive=r.primitive,
                benign=r.benign,
                attacked=attacked,
                flipped=r.flipped,
                eligible=r.eligible,
                ineligibility_reason=r.ineligibility_reason,
            )
            return dirty

        # None cost_usd gates out (PyO3 cannot extract None to f64).
        self.assertFalse(
            _require_economics_rust_input(_with_dirty_cost(None), s))
        # Non-finite cost gates out.
        self.assertFalse(
            _require_economics_rust_input(
                _with_dirty_cost(float("inf")), s))
        # Lone surrogate in a string field gates out.
        dirty = _mixed_results()
        r = dirty[0]
        dirty[0] = PerCaseResult(
            case_id="\ud800",
            family=r.family,
            severity=r.severity,
            primitive=r.primitive,
            benign=r.benign,
            attacked=r.attacked,
            flipped=r.flipped,
            eligible=r.eligible,
            ineligibility_reason=r.ineligibility_reason,
        )
        self.assertFalse(_require_economics_rust_input(dirty, s))


class EAttackedParity(unittest.TestCase):
    def test_matches_reference(self):
        results = _mixed_results()
        s = _scenario()
        for rate in (None, 0.0, 0.1, 1.0):
            got = e_attacked(results, s, rate)
            want = _e_attacked_py(results, s, rate)
            self.assertAlmostEqual(got.e_attacked, want.e_attacked, places=12)
            self.assertAlmostEqual(got.per_flip, want.per_flip, places=12)
            self.assertAlmostEqual(
                got.per_incident, want.per_incident, places=12)
            self.assertEqual(got.direction_counts, want.direction_counts)
            self.assertEqual(got.n, want.n)
            self.assertEqual(got.scenario_id, want.scenario_id)

    def test_empty_matches_reference(self):
        s = _scenario()
        got = e_attacked([], s, 0.5)
        want = _e_attacked_py([], s, 0.5)
        self.assertEqual(got.e_attacked, want.e_attacked)
        self.assertEqual(got.per_flip, want.per_flip)
        self.assertEqual(got.n, 0)


class MeanCostParity(unittest.TestCase):
    def test_matches_reference(self):
        from peira.economics import _mean_cost_per_decision
        results = _mixed_results()
        self.assertAlmostEqual(
            _mean_cost_per_decision(results),
            _mean_cost_per_decision_py(results),
            places=12,
        )
        self.assertEqual(
            _mean_cost_per_decision([]), _mean_cost_per_decision_py([]))


class ParetoFrontierParity(unittest.TestCase):
    def test_matches_reference(self):
        adapters = {
            "cheap": _mixed_results(),
            "pricey": [
                _result(f"p{i:02d}", "deny", "approve", i % 3 == 0,
                        confidence=0.5 + 0.01 * i, cost=0.01)
                for i in range(12)
            ],
            "empty": [],
        }
        got = pareto_frontier(adapters, "2026-10-02")
        want = _pareto_frontier_py(adapters, "2026-10-02")
        self.assertEqual([p.adapter for p in got],
                         [p.adapter for p in want])
        for g, w in zip(got, want):
            self.assertAlmostEqual(
                g.cost_per_decision_usd, w.cost_per_decision_usd, places=12)
            self.assertAlmostEqual(g.asr, w.asr, places=12)
            self.assertAlmostEqual(g.asr_ci95[0], w.asr_ci95[0], places=12)
            self.assertAlmostEqual(g.asr_ci95[1], w.asr_ci95[1], places=12)
            self.assertEqual(g.n, w.n)
            self.assertEqual(g.on_frontier, w.on_frontier)


class DrummondHolteParity(unittest.TestCase):
    def test_points_match_reference(self):
        adapters = {
            "a": _mixed_results(),
            "b": [
                _result(f"q{i:02d}", "approve", "deny", i % 2 == 0,
                        confidence=0.6)
                for i in range(10)
            ],
        }
        ratios = [1, 2, 5, 10, 40]
        got_points, got_stmts = drummond_holte_curves(
            adapters, list(ratios))
        want_points = _drummond_holte_points_py(adapters, list(ratios))
        self.assertEqual(len(got_points), len(want_points))
        for g, w in zip(got_points, want_points):
            self.assertEqual(g.adapter, w.adapter)
            self.assertEqual(g.cost_ratio, w.cost_ratio)
            self.assertAlmostEqual(
                g.normalized_cost, w.normalized_cost, places=12)
        # Crossover statements are pure Python on both paths.
        self.assertEqual(
            got_stmts,
            drummond_holte_curves(adapters, list(ratios))[1],
        )
        self.assertTrue(all(isinstance(s, str) for s in got_stmts))


class AttackerCostMultiplierParity(unittest.TestCase):
    def test_matches_reference(self):
        results = _mixed_results()
        for direction in ("deny-to-approve", "approve-to-deny", "other"):
            got = attacker_cost_multiplier(results, direction)
            want = _attacker_cost_multiplier_py(results, direction)
            if want is None:
                self.assertIsNone(got)
            else:
                self.assertAlmostEqual(got, want, places=12)
        self.assertIsNone(attacker_cost_multiplier([], "deny-to-approve"))
        self.assertIsNone(
            _attacker_cost_multiplier_py([], "deny-to-approve"))

    def test_unknown_direction_raises_both(self):
        results = _mixed_results()
        with self.assertRaises(ValueError):
            attacker_cost_multiplier(results, "sideways")
        with self.assertRaises(ValueError):
            _attacker_cost_multiplier_py(results, "sideways")


class GordonLoebParity(unittest.TestCase):
    def test_matches_reference(self):
        base = _mixed_results()
        cand = [
            _result(f"k{i:02d}", "deny", "deny", False, confidence=0.7,
                    cost=0.002)
            for i in range(20)
        ]
        s = _scenario()
        got = gordon_loeb_tripwire(base, cand, s, 1_000_000.0, 0.1)
        want = _gordon_loeb_tripwire_py(base, cand, s, 1_000_000.0, 0.1)
        self.assertEqual(got.tripped, want.tripped)
        self.assertAlmostEqual(
            got.annualized_extra_cost, want.annualized_extra_cost,
            places=9)
        self.assertAlmostEqual(
            got.expected_loss_reduction, want.expected_loss_reduction,
            places=9)
        if want.ratio is None:
            self.assertIsNone(got.ratio)
        else:
            self.assertAlmostEqual(got.ratio, want.ratio, places=12)

    def test_never_trips_when_no_savings(self):
        base = _mixed_results()
        s = _scenario()
        got = gordon_loeb_tripwire(base, base, s, 1_000_000.0, 0.1)
        want = _gordon_loeb_tripwire_py(base, base, s, 1_000_000.0, 0.1)
        self.assertEqual(got.tripped, want.tripped)
        self.assertIsNone(got.ratio)
        self.assertIsNone(want.ratio)


class DefenseCurveParity(unittest.TestCase):
    def test_matches_reference(self):
        results = _mixed_results()
        s = _scenario()
        thresholds = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9]
        got = defense_curve(results, s, 0.5, 0.2, thresholds)
        want = _defense_curve_py(results, s, 0.5, 0.2, thresholds)
        self.assertEqual(got.n_eligible, want.n_eligible)
        self.assertEqual(got.n_analyzed, want.n_analyzed)
        self.assertEqual(got.n_always_review, want.n_always_review)
        self.assertAlmostEqual(
            got.e_attacked_undefended, want.e_attacked_undefended,
            places=12)
        self.assertEqual(len(got.points), len(want.points))
        for g, w in zip(got.points, want.points):
            self.assertEqual(g.pt, w.pt)
            self.assertEqual(g.n_reviewed, w.n_reviewed)
            self.assertAlmostEqual(g.review_rate, w.review_rate, places=12)
            self.assertAlmostEqual(
                g.residual_e_attacked, w.residual_e_attacked, places=12)
            self.assertAlmostEqual(
                g.review_spend_per_decision,
                w.review_spend_per_decision, places=12)
            self.assertAlmostEqual(
                g.total_defender_cost_per_decision,
                w.total_defender_cost_per_decision, places=12)
            self.assertAlmostEqual(
                g.net_benefit, w.net_benefit, places=12)

    def test_default_grid_matches_reference(self):
        results = _mixed_results()
        s = _scenario()
        got = defense_curve(results, s, 1.0)
        want = _defense_curve_py(results, s, 1.0)
        self.assertEqual(len(got.points), len(want.points))
        for g, w in zip(got.points, want.points):
            self.assertAlmostEqual(
                g.total_defender_cost_per_decision,
                w.total_defender_cost_per_decision, places=12)

    def test_no_eligible_raises_both(self):
        s = _scenario()
        bad = [_result("x", "approve", "approve", False, eligible=False)]
        with self.assertRaises(ValueError):
            defense_curve(bad, s, 1.0)
        with self.assertRaises(ValueError):
            _defense_curve_py(bad, s, 1.0)


class RiskCoverageParity(unittest.TestCase):
    def test_matches_reference(self):
        results = _mixed_results()
        s = _scenario()
        curve = defense_curve(results, s, 0.5, 0.2)
        got = risk_coverage_curve(curve)
        want = _risk_coverage_curve_py(curve)
        self.assertEqual(len(got), len(want))
        for (gr, gres), (wr, wres) in zip(got, want):
            self.assertAlmostEqual(gr, wr, places=12)
            self.assertAlmostEqual(gres, wres, places=12)


class OptimalThresholdParity(unittest.TestCase):
    def test_matches_reference(self):
        results = _mixed_results()
        s = _scenario()
        curve = defense_curve(results, s, 0.5, 0.2)
        got = optimal_threshold(curve)
        want = _optimal_threshold_py(curve)
        self.assertEqual(got.pt, want.pt)
        self.assertAlmostEqual(got.review_rate, want.review_rate, places=12)
        self.assertAlmostEqual(
            got.residual_e_attacked, want.residual_e_attacked, places=12)
        self.assertAlmostEqual(
            got.total_defender_cost_per_decision,
            want.total_defender_cost_per_decision, places=12)
        if want.prevention_value_per_review_dollar is None:
            self.assertIsNone(got.prevention_value_per_review_dollar)
        else:
            self.assertAlmostEqual(
                got.prevention_value_per_review_dollar,
                want.prevention_value_per_review_dollar, places=12)


if __name__ == "__main__":
    unittest.main()
