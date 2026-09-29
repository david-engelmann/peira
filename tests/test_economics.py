"""M-3 economic value-view layer: cost scenarios, E_attacked, CPPF,
break-even attack rates, Pareto frontier, Drummond-Holte curves,
attacker cost multipliers, and the Gordon-Loeb tripwire.
"""

import unittest

from peira.adapters.base import CallUsage
from peira.economics import (
    DEFAULT_DEFENSE_THRESHOLDS,
    FLIP_DIRECTIONS,
    CostScenario,
    DefenseOptimum,
    _parse_simple_yaml,
    _validate_scenario,
    attacker_cost_multiplier,
    break_even_attack_rate,
    cppf,
    defense_curve,
    drummond_holte_curves,
    e_attacked,
    flip_direction,
    flip_direction_counts,
    gordon_loeb_tripwire,
    list_cost_scenarios,
    load_cost_scenario,
    optimal_threshold,
    pareto_frontier,
    risk_coverage_curve,
    threshold_defense_report,
    value_view,
    _pair_results,
)
from peira.metrics import (
    MIN_PER_CONDITION_CASES,
    CallRecord,
    PerCaseResult,
    net_benefit_at_threshold,
    net_benefit_pairs,
)


def _rec(decision, abstained=False, malformed=False, cost=0.001, score=None):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=abstained,
        refusal_reason="",
        usage=CallUsage(
            model="test-model", tokens_in=100, tokens_out=10,
            latency_ms=5.0, cost_usd=cost,
        ),
        seed=0,
        dispatch_index=0,
        malformed=malformed,
        score=score,
    )


def _result(case_id, benign_decision, attacked_decision, flipped,
            primitive="choice", eligible=True, cost=0.001,
            b_abstained=False, a_abstained=False, a_malformed=False):
    return PerCaseResult(
        case_id=case_id,
        family="literal_reading",
        severity="medium",
        primitive=primitive,
        benign=_rec(benign_decision, abstained=b_abstained, cost=cost),
        attacked=_rec(attacked_decision, abstained=a_abstained,
                      malformed=a_malformed, cost=cost),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "benign_wrong_decision",
    )


class ScenarioLoadingTest(unittest.TestCase):
    def test_standard_scenario_loads(self):
        s = load_cost_scenario("standard")
        self.assertEqual(s.version, 1)
        self.assertEqual(s.scenario_id, "standard")
        for d in FLIP_DIRECTIONS:
            self.assertIn(d, s.flip_cost_usd)
            self.assertGreaterEqual(s.flip_cost_usd[d], 0.0)
        self.assertEqual(s.flip_cost_usd["none"], 0.0)

    def test_three_scenarios_listed(self):
        ids = list_cost_scenarios()
        self.assertEqual(sorted(ids), ["high-stakes", "low-stakes", "standard"])

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            load_cost_scenario("nope")

    def test_none_cost_must_be_zero(self):
        # e_attacked assumes non-flips cost 0; validation must enforce it.
        s = load_cost_scenario("standard")
        bad = {
            "description": s.description,
            "flip_cost_usd": {**s.flip_cost_usd, "none": 1.0},
            "flips_per_incident": s.flips_per_incident,
            "baseline_attack_rate": s.baseline_attack_rate,
        }
        with self.assertRaises(ValueError):
            _validate_scenario("standard", 1, bad)

    def test_jailbreak_costs_most(self):
        for sid in list_cost_scenarios():
            s = load_cost_scenario(sid)
            self.assertGreater(
                s.flip_cost_usd["deny-to-approve"],
                s.flip_cost_usd["approve-to-deny"],
            )


class YamlParserTest(unittest.TestCase):
    def test_hash_inside_quoted_string_preserved(self):
        # Regression: comments are stripped only outside quotes, so a #
        # inside a quoted string must survive parsing.
        parsed = _parse_simple_yaml(
            'description: "low-stakes #1 choice"\n'
            "value: 3\n"
            "# a full-line comment\n"
            "other: 'it is #2'  # trailing comment\n"
        )
        self.assertEqual(parsed["description"], "low-stakes #1 choice")
        self.assertEqual(parsed["value"], 3)
        self.assertEqual(parsed["other"], "it is #2")


class FlipDirectionTest(unittest.TestCase):
    def test_deny_to_approve(self):
        r = _result("c1", "deny", "approve", True)
        self.assertEqual(flip_direction(r), "deny-to-approve")

    def test_approve_to_deny(self):
        r = _result("c1", "approve", "deny", True)
        self.assertEqual(flip_direction(r), "approve-to-deny")

    def test_to_abstain(self):
        r = _result("c1", "approve", "", True, a_abstained=True)
        self.assertEqual(flip_direction(r), "to-abstain")

    def test_to_malformed(self):
        r = _result("c1", "approve", "approve", True, a_malformed=True)
        self.assertEqual(flip_direction(r), "to-malformed")

    def test_none_when_not_flipped(self):
        r = _result("c1", "approve", "approve", False)
        self.assertEqual(flip_direction(r), "none")

    def test_score_shifted(self):
        r = _result("c1", "approve", "approve", True, primitive="score")
        self.assertEqual(flip_direction(r), "score-shifted")

    def test_other_for_unknown_polarity(self):
        r = _result("c1", "choose A", "choose B", True)
        self.assertEqual(flip_direction(r), "other")

    def test_counts_cover_full_taxonomy(self):
        results = [
            _result("c1", "deny", "approve", True),
            _result("c2", "approve", "approve", False),
        ]
        counts = flip_direction_counts(results)
        self.assertEqual(set(counts), set(FLIP_DIRECTIONS))
        self.assertEqual(counts["deny-to-approve"], 1)
        self.assertEqual(counts["none"], 1)

    def test_ineligible_excluded(self):
        results = [_result("c1", "deny", "approve", True, eligible=False)]
        counts = flip_direction_counts(results)
        self.assertEqual(sum(counts.values()), 0)


class EAttackedTest(unittest.TestCase):
    def test_expected_cost(self):
        s = load_cost_scenario("standard")
        # 4 cases: 1 jailbreak ($1000), 1 false block ($50), 2 clean
        results = [
            _result("c1", "deny", "approve", True),
            _result("c2", "approve", "deny", True),
            _result("c3", "approve", "approve", False),
            _result("c4", "deny", "deny", False),
        ]
        est = e_attacked(results, s, attack_rate=1.0)
        self.assertAlmostEqual(est.e_attacked, (1000.0 + 50.0) / 4)
        self.assertEqual(est.n, 4)
        self.assertEqual(est.direction_counts["deny-to-approve"], 1)
        self.assertEqual(est.direction_counts["approve-to-deny"], 1)
        self.assertEqual(est.direction_counts["none"], 2)

    def test_per_flip_and_per_incident_views(self):
        s = load_cost_scenario("standard")  # flips_per_incident = 10
        results = [
            _result("c1", "deny", "approve", True),
            _result("c2", "approve", "approve", False),
        ]
        est = e_attacked(results, s, attack_rate=1.0)
        self.assertAlmostEqual(est.per_flip, 1000.0)
        self.assertAlmostEqual(est.per_incident, 10000.0)

    def test_per_flip_unscaled_by_attack_rate(self):
        # Regression: per_flip is the mean flip cost, not scaled by the
        # attack rate. One $1000 jailbreak among 2 eligible cases at
        # baseline pi=0.05 must report $/flip = $1000, and the identity
        # per_flip x flip_rate x pi == e_attacked must hold exactly.
        s = load_cost_scenario("standard")  # baseline_attack_rate = 0.05
        results = [
            _result("c1", "deny", "approve", True),
            _result("c2", "approve", "approve", False),
        ]
        est = e_attacked(results, s)  # attack_rate defaults to baseline
        self.assertAlmostEqual(est.per_flip, 1000.0)
        self.assertAlmostEqual(
            est.per_incident, 1000.0 * s.flips_per_incident
        )
        flip_rate = 1 / 2
        self.assertAlmostEqual(
            est.per_flip * flip_rate * s.baseline_attack_rate,
            est.e_attacked,
        )

    def test_attack_rate_scales(self):
        s = load_cost_scenario("standard")
        results = [_result("c1", "deny", "approve", True)]
        full = e_attacked(results, s, attack_rate=1.0)
        half = e_attacked(results, s, attack_rate=0.5)
        self.assertAlmostEqual(half.e_attacked, full.e_attacked / 2)

    def test_no_flips_zero_cost(self):
        s = load_cost_scenario("standard")
        results = [_result("c1", "approve", "approve", False)]
        est = e_attacked(results, s)
        self.assertEqual(est.e_attacked, 0.0)
        self.assertEqual(est.per_flip, 0.0)

    def test_bad_attack_rate_raises(self):
        s = load_cost_scenario("standard")
        with self.assertRaises(ValueError):
            e_attacked([], s, attack_rate=1.5)


class CppfTest(unittest.TestCase):
    def _paired(self, n_base_flips, n_cand_flips, base_cost=0.001, cand_cost=0.002):
        base, cand = [], []
        for i in range(10):
            b_flip = i < n_base_flips
            c_flip = i < n_cand_flips
            base.append(_result(
                f"c{i}", "deny" if b_flip else "approve",
                "approve" if b_flip else "approve",
                b_flip, cost=base_cost))
            cand.append(_result(
                f"c{i}", "deny" if c_flip else "approve",
                "approve" if c_flip else "approve",
                c_flip, cost=cand_cost))
        return base, cand

    def test_cppf_point_estimate(self):
        base, cand = self._paired(6, 2)
        est = cppf(base, cand, n_boot=200, seed=1)
        self.assertTrue(est.prevents_flips)
        # delta cost per decision = 2*(0.002-0.001) = 0.002
        # (benign + attacked calls); flips prevented = 0.4
        self.assertAlmostEqual(est.cppf, 0.002 / 0.4)
        self.assertIsNotNone(est.cppf_ci95)
        lo, hi = est.cppf_ci95
        self.assertLess(lo, est.cppf)
        self.assertGreater(hi, est.cppf)

    def test_no_prevention_returns_none(self):
        base, cand = self._paired(2, 6)  # candidate flips MORE
        est = cppf(base, cand, n_boot=200, seed=1)
        self.assertFalse(est.prevents_flips)
        self.assertIsNone(est.cppf)

    def test_missing_candidate_match_raises(self):
        with self.assertRaises(ValueError):
            cppf([_result("c1", "a", "a", False)], [])

    def test_pair_results_pairs_by_case_id_regardless_of_order(self):
        base = [
            _result("c1", "deny", "approve", True),
            _result("c2", "approve", "approve", False),
            _result("c3", "deny", "deny", False),
        ]
        cand = [
            _result("c3", "deny", "approve", True),
            _result("c1", "deny", "deny", False),
            _result("c2", "approve", "deny", True),
        ]
        pairs = _pair_results(base, cand)
        self.assertEqual([b.case_id for b, _ in pairs], ["c1", "c2", "c3"])
        self.assertEqual(
            [c.case_id for _, c in pairs], ["c1", "c2", "c3"]
        )
        # c1: base flipped, candidate did not; c2: reverse; c3: both
        # unflipped here but candidate flipped.
        self.assertTrue(pairs[0][0].flipped)
        self.assertFalse(pairs[0][1].flipped)
        self.assertFalse(pairs[1][0].flipped)
        self.assertTrue(pairs[1][1].flipped)


class BreakEvenTest(unittest.TestCase):
    def test_break_even_in_range(self):
        s = load_cost_scenario("standard")
        base, cand = [], []
        # baseline: cheap ($0.001/call), flips 8/10 jailbreaks
        # candidate: 10x cost, flips 2/10 jailbreaks
        for i in range(10):
            b_flip = i < 8
            c_flip = i < 2
            base.append(_result(
                f"c{i}", "deny" if b_flip else "approve",
                "approve" if b_flip else "approve",
                b_flip, cost=0.001))
            cand.append(_result(
                f"c{i}", "deny" if c_flip else "approve",
                "approve" if c_flip else "approve",
                c_flip, cost=0.010))
        est = break_even_attack_rate(base, cand, s, n_boot=200, seed=1)
        self.assertEqual(est.verdict, "at")
        self.assertIsNotNone(est.pi_star)
        self.assertGreaterEqual(est.pi_star, 0.0)
        self.assertLessEqual(est.pi_star, 1.0)

    def test_never_when_no_savings(self):
        s = load_cost_scenario("standard")
        base = [_result(f"c{i}", "approve", "approve", False, cost=0.001)
                for i in range(10)]
        cand = [_result(f"c{i}", "approve", "approve", False, cost=0.002)
                for i in range(10)]
        est = break_even_attack_rate(base, cand, s, n_boot=200, seed=1)
        self.assertEqual(est.verdict, "never")


class ParetoTest(unittest.TestCase):
    def test_frontier_marks_off_frontier(self):
        cheap_weak = [_result(f"c{i}", "deny", "approve", i < 8, cost=0.001)
                      for i in range(10)]
        pricey_strong = [_result(f"c{i}", "deny", "approve", i < 2, cost=0.010)
                         for i in range(10)]
        off_frontier = [_result(f"c{i}", "deny", "approve", i < 8, cost=0.010)
                        for i in range(10)]
        pts = pareto_frontier(
            {"cheap": cheap_weak, "pricey": pricey_strong, "dom": off_frontier},
            price_date="2026-09-28",
        )
        by_name = {p.adapter: p for p in pts}
        self.assertTrue(by_name["cheap"].on_frontier)
        self.assertTrue(by_name["pricey"].on_frontier)
        self.assertFalse(by_name["dom"].on_frontier)
        self.assertEqual(by_name["cheap"].price_date, "2026-09-28")
        # Wilson CI present on every point
        for p in pts:
            lo, hi = p.asr_ci95
            self.assertLessEqual(lo, p.asr)
            self.assertGreaterEqual(hi, p.asr)


class CostCurveTest(unittest.TestCase):
    def test_crossover_in_words(self):
        # A: jailbreak-prone (high deny-to-approve), B: block-prone
        a = [_result(f"c{i}", "deny", "approve", True, cost=0.001)
             for i in range(10)]
        b = [_result(f"c{i}", "approve", "deny", True, cost=0.001)
             for i in range(10)]
        points, statements = drummond_holte_curves({"a": a, "b": b})
        self.assertTrue(points)
        # At r=1 the two tie; as r grows, B (block-prone) pulls ahead
        # because jailbreaks get expensive. Expect a crossover statement.
        self.assertTrue(statements)
        self.assertIn("jailbreak", statements[0])


class AttackerMultiplierTest(unittest.TestCase):
    def test_jailbreak_headline(self):
        results = [
            _result("c1", "deny", "approve", True),
            _result("c2", "approve", "approve", False),
            _result("c3", "deny", "deny", False),
            _result("c4", "approve", "approve", False),
        ]
        self.assertAlmostEqual(
            attacker_cost_multiplier(results, "deny-to-approve"), 4.0)

    def test_none_when_never(self):
        results = [_result("c1", "approve", "approve", False)]
        self.assertIsNone(attacker_cost_multiplier(results, "deny-to-approve"))

    def test_unknown_direction_raises(self):
        with self.assertRaises(ValueError):
            attacker_cost_multiplier([], "sideways")


class GordonLoebTest(unittest.TestCase):
    def test_tripwire_trips(self):
        s = load_cost_scenario("standard")
        base, cand = [], []
        # approve-to-deny flips cost $50 each: preventing 1 in 10 saves
        # $5/decision = $5M/yr at 1M decisions; the candidate costs
        # ~$2/decision more = $2M/yr extra. Ratio 0.4 > 0.37: trips.
        for i in range(10):
            b_flip = i < 5
            c_flip = i < 4
            base.append(_result(
                f"c{i}", "approve" if not b_flip else "approve",
                "deny" if b_flip else "approve",
                b_flip, cost=0.001))
            cand.append(_result(
                f"c{i}", "approve" if not c_flip else "approve",
                "deny" if c_flip else "approve",
                c_flip, cost=1.0))
        res = gordon_loeb_tripwire(
            base, cand, s, decisions_per_year=1_000_000, attack_rate=1.0)
        self.assertTrue(res.tripped)
        self.assertGreater(res.ratio, 0.37)

    def test_bad_volume_raises(self):
        s = load_cost_scenario("standard")
        with self.assertRaises(ValueError):
            gordon_loeb_tripwire([], [], s, decisions_per_year=0)

    def test_nan_volume_raises(self):
        # NaN <= 0 is False, so an explicit guard is needed: NaN would
        # otherwise poison the tripwire silently.
        s = load_cost_scenario("standard")
        results = [_result("c1", "deny", "approve", True)]
        with self.assertRaises(ValueError):
            gordon_loeb_tripwire(results, results, s, float("nan"))


class ValueViewTest(unittest.TestCase):
    def test_full_summary(self):
        s = load_cost_scenario("standard")
        base = [_result(f"c{i}", "deny", "approve", i < 6, cost=0.001)
                for i in range(10)]
        cand = [_result(f"c{i}", "deny", "approve", i < 2, cost=0.005)
                for i in range(10)]
        view = value_view(
            {"base": base, "cand": cand}, s,
            baseline_adapter="base", price_date="2026-09-28",
        )
        self.assertEqual(view["scenario"], "standard")
        self.assertIn("base", view["adapters"])
        # Both dollar views present
        self.assertIn("cost_per_flip", view["adapters"]["cand"])
        self.assertIn("cost_per_incident", view["adapters"]["cand"])
        # Raw breakdown present for re-weighting
        self.assertEqual(
            set(view["adapters"]["cand"]["flip_direction_counts"]),
            set(FLIP_DIRECTIONS),
        )
        self.assertTrue(view["pareto_frontier"])
        self.assertIn("cand", view["comparisons"])
        comp = view["comparisons"]["cand"]
        self.assertIsNotNone(comp["cppf"])
        self.assertIn(comp["break_even_verdict"], ("at", "always", "never"))

    def test_no_blended_score(self):
        s = load_cost_scenario("standard")
        base = [_result(f"c{i}", "deny", "approve", i < 6, cost=0.001)
                for i in range(10)]
        view = value_view({"base": base}, s)
        # Nothing called "score", "value", or "rating" anywhere
        import json
        blob = json.dumps(view).lower()
        self.assertNotIn("value_score", blob)
        self.assertNotIn("blended", blob)


class ValueCliTest(unittest.TestCase):
    def _artifact(self, name, flips, cost=0.001):
        from peira.artifacts import RunArtifact
        cases = []
        for i in range(10):
            f = i < flips
            cases.append({
                "case_id": f"c{i}",
                "family": "literal_reading",
                "severity": "medium",
                "primitive": "choice",
                "benign": {
                    "decision": "deny" if f else "approve",
                    "confidence": 0.9, "abstained": False,
                    "refusal_reason": "", "seed": 0, "dispatch_index": 0,
                    "malformed": False, "dispatch_limit": 1,
                    "usage": {"model": "m", "tokens_in": 10,
                              "tokens_out": 5, "latency_ms": 5.0,
                              "cost_usd": cost},
                },
                "attacked": {
                    "decision": "approve",
                    "confidence": 0.9, "abstained": False,
                    "refusal_reason": "", "seed": 0, "dispatch_index": 0,
                    "malformed": False, "dispatch_limit": 1,
                    "usage": {"model": "m", "tokens_in": 10,
                              "tokens_out": 5, "latency_ms": 5.0,
                              "cost_usd": cost},
                },
                "flipped": f, "eligible": True, "ineligibility_reason": "",
            })
        art = RunArtifact(
            adapter_name=name, adapter_version="1.0", suite="trial-demo",
            dataset_version="0.1.0-demo", manifest_sha256="abc123",
            results=cases, metrics={},
        )
        art.seal()
        return art

    def _write(self, art):
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8")
        tmp.write(art.to_json())
        tmp.close()
        return tmp.name

    def _ns(self, **kw):
        import argparse
        ns = argparse.Namespace(
            runs=[], scenario="standard", baseline=None,
            price_date=None, out=None,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_value_stdout(self):
        from peira.cli import EXIT_OK, cmd_value
        import io
        from contextlib import redirect_stdout
        a = self._write(self._artifact("mock-a", 6))
        b = self._write(self._artifact("mock-b", 2, cost=0.005))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_value(self._ns(runs=[a, b], baseline="mock-a"))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("value view", out)
        self.assertIn("E_attacked", out)
        self.assertIn("Pareto frontier", out)
        self.assertIn("CPPF", out)
        self.assertIn("break-even", out)

    def test_value_out_file(self):
        from peira.cli import EXIT_OK, cmd_value
        import tempfile
        from pathlib import Path
        a = self._write(self._artifact("mock-a", 6))
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "value.html")
            rc = cmd_value(self._ns(runs=[a], out=out))
            self.assertEqual(rc, EXIT_OK)
            html = Path(out).read_text()
            self.assertIn("peira value view", html)
            self.assertIn("Pareto frontier", html)

    def test_value_bad_scenario(self):
        from peira.cli import EXIT_USER_ERROR, cmd_value
        a = self._write(self._artifact("mock-a", 6))
        rc = cmd_value(self._ns(runs=[a], scenario="nope"))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_value_missing_file(self):
        from peira.cli import EXIT_USER_ERROR, cmd_value
        rc = cmd_value(self._ns(runs=["/nonexistent/x.json"]))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_value_duplicate_adapter(self):
        from peira.cli import EXIT_USER_ERROR, cmd_value
        a = self._write(self._artifact("mock-a", 6))
        rc = cmd_value(self._ns(runs=[a, a]))
        self.assertEqual(rc, EXIT_USER_ERROR)


class DefenseCliTest(unittest.TestCase):
    def _artifact(self, name, n):
        from peira.artifacts import RunArtifact
        cases = []
        for i in range(n):
            f = (i % 2 == 0)
            cases.append({
                "case_id": f"dc{i}",
                "family": "literal_reading",
                "severity": "medium",
                "primitive": "choice",
                "benign": {
                    "decision": "deny",
                    "confidence": 0.9, "abstained": False,
                    "refusal_reason": "", "seed": 0, "dispatch_index": 0,
                    "malformed": False, "dispatch_limit": 1,
                    "usage": None,
                },
                "attacked": {
                    "decision": "approve" if f else "deny",
                    "confidence": round(0.05 + (i * 0.0137 % 0.9), 4),
                    "abstained": False,
                    "refusal_reason": "", "seed": 0, "dispatch_index": 1,
                    "malformed": False, "dispatch_limit": 1,
                    "usage": None,
                },
                "flipped": f, "eligible": True, "ineligibility_reason": "",
            })
        art = RunArtifact(
            adapter_name=name, adapter_version="1.0", suite="trial-demo",
            dataset_version="0.1.0-demo", manifest_sha256="abc123",
            results=cases, metrics={},
        )
        art.seal()
        return art

    def _write(self, art):
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8")
        tmp.write(art.to_json())
        tmp.close()
        return tmp.name

    def _ns(self, **kw):
        import argparse
        ns = argparse.Namespace(
            runs=[], scenario="standard", review_cost_usd=1.0,
            attack_rate=None, out=None,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_defense_stdout(self):
        from peira.cli import EXIT_OK, cmd_defense
        import io
        from contextlib import redirect_stdout
        a = self._write(self._artifact("mock-a", 40))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_defense(self._ns(runs=[a]))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("defense view", out)
        self.assertIn("mock-a", out)
        self.assertIn("optimum:", out)
        self.assertIn("risk-coverage", out)
        self.assertIn("attacked-arm ECE", out)

    def test_defense_withheld_small_n(self):
        from peira.cli import EXIT_OK, cmd_defense
        import io
        from contextlib import redirect_stdout
        a = self._write(self._artifact("mock-a", 10))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_defense(self._ns(runs=[a]))
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("WITHHELD", buf.getvalue())

    def test_defense_out_json(self):
        from peira.cli import EXIT_OK, cmd_defense
        import json
        import tempfile
        from pathlib import Path
        a = self._write(self._artifact("mock-a", 40))
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "defense.json")
            rc = cmd_defense(self._ns(runs=[a], out=out))
            self.assertEqual(rc, EXIT_OK)
            report = json.loads(Path(out).read_text())
            self.assertIn("adapters", report)
            self.assertFalse(report["adapters"]["mock-a"]["withheld"])
            self.assertIn("optimum",
                          report["adapters"]["mock-a"])

    def test_defense_bad_scenario(self):
        from peira.cli import EXIT_USER_ERROR, cmd_defense
        a = self._write(self._artifact("mock-a", 40))
        rc = cmd_defense(self._ns(runs=[a], scenario="nope"))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_defense_missing_file(self):
        from peira.cli import EXIT_USER_ERROR, cmd_defense
        rc = cmd_defense(self._ns(runs=["/nonexistent/x.json"]))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_defense_negative_review_cost(self):
        from peira.cli import EXIT_USER_ERROR, cmd_defense
        a = self._write(self._artifact("mock-a", 40))
        rc = cmd_defense(self._ns(runs=[a], review_cost_usd=-1.0))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_defense_free_review_message(self):
        # review_cost_usd=0 with a reviewing optimum: the prevention
        # value is n/a because review is free, not because nothing is
        # reviewed.
        from peira.cli import EXIT_OK, cmd_defense
        import io
        from contextlib import redirect_stdout
        a = self._write(self._artifact("mock-a", 40))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_defense(self._ns(runs=[a], review_cost_usd=0.0))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("n/a (review is free)", out)
        self.assertNotIn("reviews nothing", out)

    def test_defense_duplicate_adapter(self):
        from peira.cli import EXIT_USER_ERROR, cmd_defense
        a = self._write(self._artifact("mock-a", 40))
        rc = cmd_defense(self._ns(runs=[a, a]))
        self.assertEqual(rc, EXIT_USER_ERROR)


# ---------------------------------------------------------------------------
# C-4: threshold-defense economics
# ---------------------------------------------------------------------------


def _crec(decision, confidence, abstained=False, malformed=False):
    return CallRecord(
        decision=decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _cresult(case_id, benign_decision, attacked_decision, flipped,
             confidence, eligible=True, a_abstained=False,
             a_malformed=False):
    return PerCaseResult(
        case_id=case_id,
        family="literal_reading",
        severity="medium",
        primitive="choice",
        benign=_crec(benign_decision, 0.95),
        attacked=_crec(attacked_decision, confidence,
                       abstained=a_abstained, malformed=a_malformed),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "benign_wrong_decision",
    )


def _defense_results(n, flip_every=2, confidence_step=0.02):
    """n eligible choice cases; every flip_every-th flips deny->approve.

    Confidences cycle so risks spread across the threshold grid.
    """
    out = []
    for i in range(n):
        flipped = (i % flip_every == 0)
        conf = 0.05 + (i * confidence_step % 0.9)
        out.append(_cresult(
            f"d{i}", "deny", "approve" if flipped else "deny",
            flipped, round(conf, 4),
        ))
    return out


class DefenseCurveTest(unittest.TestCase):
    def test_default_grid_includes_zero(self):
        self.assertEqual(DEFAULT_DEFENSE_THRESHOLDS[0], 0.0)
        curve = defense_curve(
            _defense_results(40), load_cost_scenario("standard"), 1.0,
        )
        self.assertEqual(curve.points[0].pt, 0.0)

    def test_review_everything_endpoints(self):
        results = _defense_results(40)
        curve = defense_curve(
            results, load_cost_scenario("standard"), 2.5,
            attack_rate=1.0,
        )
        p0 = curve.points[0]
        self.assertEqual(p0.review_rate, 1.0)
        self.assertEqual(p0.residual_e_attacked, 0.0)
        self.assertAlmostEqual(p0.review_spend_per_decision, 2.5)
        self.assertAlmostEqual(
            p0.total_defender_cost_per_decision, 2.5)

    def test_population_mirror_matches_dca(self):
        # The analyzed filter must mirror R-08's attacked-arm rule:
        # analyzed count equals net_benefit_pairs output length, even
        # with abstains, malformed, and missing confidences mixed in.
        results = _defense_results(40)
        results.append(_cresult("ax1", "deny", "abstain", True, 0.4,
                               a_abstained=True))
        results.append(_cresult("ax2", "deny", "approve", True, 0.4,
                               a_malformed=True))
        results.append(_cresult("ax3", "deny", "deny", False, None))
        results.append(_cresult("ax4", "deny", "deny", False, 0.8,
                               eligible=False))
        curve = defense_curve(
            results, load_cost_scenario("standard"), 1.0,
        )
        risks, _ = net_benefit_pairs(results, "attacked")
        self.assertEqual(curve.n_analyzed, len(risks))
        self.assertEqual(curve.n_eligible, 43)
        self.assertEqual(curve.n_always_review, 3)
        self.assertEqual(
            curve.n_eligible, curve.n_analyzed + curve.n_always_review)

    def test_always_review_routed_at_every_threshold(self):
        results = _defense_results(20)
        results.append(_cresult("ax1", "deny", "abstain", True, 0.99,
                                a_abstained=True))
        curve = defense_curve(
            results, load_cost_scenario("standard"), 1.0,
            thresholds=[0.99],
        )
        # The abstained case has risk 0.01 < 0.99 but must still be
        # reviewed: buyer cost modeling cannot auto-trust it.
        self.assertEqual(curve.points[0].n_reviewed, 1)
        self.assertAlmostEqual(
            curve.points[0].review_rate, 1 / 21)

    def test_residual_monotone_in_threshold(self):
        curve = defense_curve(
            _defense_results(60), load_cost_scenario("standard"), 1.0,
        )
        pts = curve.points
        for a, b in zip(pts, pts[1:]):
            # Higher pt: less review, no less residual, no more spend.
            self.assertLessEqual(b.review_rate, a.review_rate)
            self.assertGreaterEqual(b.residual_e_attacked,
                                    a.residual_e_attacked)
            self.assertLessEqual(b.review_spend_per_decision,
                                 a.review_spend_per_decision)

    def test_undefended_matches_e_attacked(self):
        results = _defense_results(50)
        scenario = load_cost_scenario("standard")
        curve = defense_curve(results, scenario, 1.0, attack_rate=0.7)
        expected = e_attacked(results, scenario,
                              attack_rate=0.7).e_attacked
        self.assertAlmostEqual(curve.e_attacked_undefended, expected)

    def test_undefended_matches_e_attacked_on_score_primitive(self):
        # Score-primitive cases with a material score shift are priced
        # ("score-shifted") even without a decision flip: the defense
        # curve's priced baseline must match e_attacked there too.
        results = []
        for i in range(10):
            benign = CallRecord(
                decision="deny", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0, dispatch_index=0,
                malformed=False, score=0.2,
            )
            attacked = CallRecord(
                decision="deny", confidence=round(0.1 + i * 0.05, 4),
                abstained=False, refusal_reason="", usage=None, seed=0,
                dispatch_index=1, malformed=False, score=0.8,
            )
            results.append(PerCaseResult(
                case_id=f"s{i}", family="literal_reading",
                severity="medium", primitive="score",
                benign=benign, attacked=attacked,
                flipped=False, eligible=True, ineligibility_reason="",
            ))
        scenario = load_cost_scenario("standard")
        curve = defense_curve(results, scenario, 1.0, attack_rate=0.7)
        expected = e_attacked(results, scenario,
                              attack_rate=0.7).e_attacked
        self.assertGreater(expected, 0.0)
        self.assertAlmostEqual(curve.e_attacked_undefended, expected)

    def test_net_benefit_column_matches_r08(self):
        results = _defense_results(40)
        curve = defense_curve(
            results, load_cost_scenario("standard"), 1.0,
            thresholds=[0.1, 0.5, 0.9],
        )
        risks, labels = net_benefit_pairs(results, "attacked")
        for p in curve.points:
            self.assertAlmostEqual(
                p.net_benefit,
                net_benefit_at_threshold(risks, labels, p.pt),
            )

    def test_thresholds_sorted_and_deduplicated(self):
        curve = defense_curve(
            _defense_results(20), load_cost_scenario("standard"), 1.0,
            thresholds=[0.5, 0.1, 0.5, 0.9],
        )
        self.assertEqual(
            [p.pt for p in curve.points], [0.1, 0.5, 0.9])

    def test_validation(self):
        results = _defense_results(20)
        scenario = load_cost_scenario("standard")
        with self.assertRaises(ValueError):
            defense_curve([], scenario, 1.0)
        with self.assertRaises(ValueError):
            defense_curve(results, scenario, -1.0)
        with self.assertRaises(ValueError):
            defense_curve(results, scenario, True)
        with self.assertRaises(ValueError):
            defense_curve(results, scenario, 1.0, attack_rate=1.5)
        with self.assertRaises(ValueError):
            defense_curve(results, scenario, 1.0, thresholds=[])
        with self.assertRaises(ValueError):
            defense_curve(results, scenario, 1.0, thresholds=[1.0])
        with self.assertRaises(ValueError):
            defense_curve(results, scenario, float("nan"))


class RiskCoverageCurveTest(unittest.TestCase):
    def test_sorted_ascending_with_full_coverage_endpoint(self):
        curve = defense_curve(
            _defense_results(40), load_cost_scenario("standard"), 1.0,
        )
        rc = risk_coverage_curve(curve)
        self.assertEqual(len(rc), len(curve.points))
        for (r1, _), (r2, _) in zip(rc, rc[1:]):
            self.assertLessEqual(r1, r2)
        # Full coverage buys zero residual priced risk.
        self.assertEqual(rc[-1], (1.0, 0.0))


class OptimalThresholdTest(unittest.TestCase):
    def test_optimum_minimizes_total_cost(self):
        curve = defense_curve(
            _defense_results(60), load_cost_scenario("standard"), 1.0,
        )
        opt = optimal_threshold(curve)
        self.assertIsInstance(opt, DefenseOptimum)
        self.assertAlmostEqual(
            opt.total_defender_cost_per_decision,
            min(p.total_defender_cost_per_decision
                for p in curve.points),
        )

    def test_tie_breaks_toward_least_review(self):
        # No flips anywhere and free review: every threshold has total
        # cost 0.0, a genuine tie, so the optimum must be the highest
        # pt (least review at equal cost).
        results = [
            _cresult(f"n{i}", "deny", "deny", False, 0.5 + 0.01 * i)
            for i in range(20)
        ]
        curve = defense_curve(
            results, load_cost_scenario("standard"), 0.0,
            thresholds=[0.1, 0.5, 0.9],
        )
        totals = {p.total_defender_cost_per_decision for p in curve.points}
        self.assertEqual(totals, {0.0})
        opt = optimal_threshold(curve)
        self.assertEqual(opt.pt, 0.9)
        self.assertEqual(opt.review_spend_per_decision, 0.0)
        self.assertIsNone(opt.prevention_value_per_review_dollar)

    def test_attacker_cost_aware_optimum(self):
        # Same adapter, same confidences: expensive flips pull the
        # optimum toward review, cheap flips toward auto-trust.
        results = _defense_results(60, flip_every=2)
        pricey = load_cost_scenario("standard")  # deny-to-approve $1000
        cheap = CostScenario(
            scenario_id="cheap-test",
            version=1,
            description="test",
            flip_cost_usd={d: (0.0 if d == "none" else 0.01)
                           for d in FLIP_DIRECTIONS},
            flips_per_incident=1.0,
            baseline_attack_rate=0.5,
        )
        opt_pricey = optimal_threshold(defense_curve(
            results, pricey, 1.0, attack_rate=0.5))
        opt_cheap = optimal_threshold(defense_curve(
            results, cheap, 1.0, attack_rate=0.5))
        self.assertLess(opt_pricey.pt, opt_cheap.pt)
        self.assertLess(opt_pricey.residual_e_attacked,
                        opt_cheap.residual_e_attacked)

    def test_prevention_value_per_review_dollar(self):
        results = _defense_results(60, flip_every=2)
        scenario = load_cost_scenario("standard")
        curve = defense_curve(results, scenario, 1.0, attack_rate=0.5)
        opt = optimal_threshold(curve)
        self.assertGreater(opt.review_spend_per_decision, 0.0)
        self.assertAlmostEqual(
            opt.prevention_value_per_review_dollar,
            (curve.e_attacked_undefended - opt.residual_e_attacked)
            / opt.review_spend_per_decision,
        )
        self.assertGreaterEqual(
            opt.prevention_value_per_review_dollar, 0.0)


class ThresholdDefenseReportTest(unittest.TestCase):
    def test_withholds_below_calibration_minimum(self):
        # Layer-4 gate: no reported attacked-arm calibration, no
        # threshold defense claim.
        report = threshold_defense_report(
            {"a": _defense_results(MIN_PER_CONDITION_CASES - 1)},
            load_cost_scenario("standard"),
            1.0,
        )
        section = report["adapters"]["a"]
        self.assertTrue(section["withheld"])
        self.assertIn("calibration", section["reason"])
        self.assertIsNone(section["attacked_ece"])
        self.assertNotIn("curve", section)
        self.assertNotIn("optimum", section)

    def test_withholds_no_eligible_cases(self):
        results = [
            _cresult(f"x{i}", "deny", "deny", False, 0.7, eligible=False)
            for i in range(10)
        ]
        report = threshold_defense_report(
            {"a": results}, load_cost_scenario("standard"), 1.0,
        )
        section = report["adapters"]["a"]
        self.assertTrue(section["withheld"])
        self.assertIn("no eligible cases", section["reason"])

    def test_bad_attack_rate_raises_even_when_all_withheld(self):
        # The attack rate is validated before the report is built: an
        # invalid rate must raise even when every adapter is withheld
        # and defense_curve never runs.
        with self.assertRaisesRegex(ValueError, "attack_rate"):
            threshold_defense_report(
                {"a": _defense_results(5)},
                load_cost_scenario("standard"),
                1.0,
                attack_rate=1.5,
            )

    def test_reports_with_calibration(self):
        report = threshold_defense_report(
            {"a": _defense_results(40), "b": _defense_results(10)},
            load_cost_scenario("standard"),
            1.0,
        )
        good = report["adapters"]["a"]
        self.assertFalse(good["withheld"])
        self.assertGreaterEqual(good["attacked_ece"], 0.0)
        self.assertEqual(good["ece_n"], 40)
        self.assertIn("optimum", good)
        self.assertIn("risk_coverage_curve", good)
        self.assertEqual(len(good["curve"]), len(report["thresholds"]))
        # AUROC is context, present but never the claim.
        self.assertIsNotNone(good["flip_detection_auroc"])
        self.assertTrue(report["adapters"]["b"]["withheld"])

    def test_report_metadata(self):
        report = threshold_defense_report(
            {"a": _defense_results(40)},
            load_cost_scenario("high-stakes"),
            2.0,
            attack_rate=0.3,
        )
        self.assertEqual(report["scenario"], "high-stakes")
        self.assertEqual(report["scenario_version"], 1)
        self.assertEqual(report["review_cost_usd"], 2.0)
        self.assertEqual(report["attack_rate"], 0.3)

    def test_report_json_serializable(self):
        import json
        report = threshold_defense_report(
            {"a": _defense_results(40), "b": _defense_results(5)},
            load_cost_scenario("standard"),
            1.0,
        )
        blob = json.dumps(report)
        self.assertIsInstance(blob, str)
        self.assertEqual(json.loads(blob), report)


if __name__ == "__main__":
    unittest.main()
