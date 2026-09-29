"""M-3 economic value-view layer: cost scenarios, E_attacked, CPPF,
break-even attack rates, Pareto frontier, Drummond-Holte curves,
attacker cost multipliers, and the Gordon-Loeb tripwire.
"""

import unittest

from peira.adapters.base import CallUsage
from peira.economics import (
    FLIP_DIRECTIONS,
    _parse_simple_yaml,
    _validate_scenario,
    attacker_cost_multiplier,
    break_even_attack_rate,
    cppf,
    drummond_holte_curves,
    e_attacked,
    flip_direction,
    flip_direction_counts,
    gordon_loeb_tripwire,
    list_cost_scenarios,
    load_cost_scenario,
    pareto_frontier,
    value_view,
    _pair_results,
)
from peira.metrics import CallRecord, PerCaseResult


def _rec(decision, abstained=False, malformed=False, cost=0.001, score=None,
        model="test-model"):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=abstained,
        refusal_reason="",
        usage=CallUsage(
            model=model, tokens_in=100, tokens_out=10,
            latency_ms=5.0, cost_usd=cost,
        ),
        seed=0,
        dispatch_index=0,
        malformed=malformed,
        score=score,
    )


def _result(case_id, benign_decision, attacked_decision, flipped,
            primitive="choice", eligible=True, cost=0.001,
            b_abstained=False, a_abstained=False, a_malformed=False,
            a_model="test-model"):
    return PerCaseResult(
        case_id=case_id,
        family="literal_reading",
        severity="medium",
        primitive=primitive,
        benign=_rec(benign_decision, abstained=b_abstained, cost=cost),
        attacked=_rec(attacked_decision, abstained=a_abstained,
                      malformed=a_malformed, cost=cost, model=a_model),
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
        # C-9 (M-9 x M-1): per-direction attacker cost-per-flip table,
        # every M-1 direction a key, jailbreak direction present.
        c9 = view["adapters"]["cand"]["attacker_cost_per_direction"]
        self.assertEqual(set(c9), set(FLIP_DIRECTIONS))
        self.assertIn("direction", c9["deny-to-approve"])
        self.assertEqual(c9["deny-to-approve"]["direction"],
                         "deny-to-approve")
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

    def test_value_text_renders_c9_direction_table(self):
        from peira.cli import _value_text
        s = load_cost_scenario("standard")
        base = [_result(f"c{i}", "deny", "approve", i < 6, cost=0.001)
                for i in range(10)]
        view = value_view({"base": base}, s, price_date="2026-09-28")
        text = _value_text(view)
        self.assertIn("attacker $/flip by direction:", text)
        # The jailbreak direction renders first; it is the headline.
        lines = text.splitlines()
        first_dir = next(
            l for l in lines if l.startswith("      ") and ":" in l)
        self.assertIn("deny-to-approve", first_dir)
        # Withheld directions render as "withheld", never zero.
        self.assertIn("to-malformed: withheld", text)

    def test_value_page_renders_c9_direction_table(self):
        from peira.cli import _value_page
        s = load_cost_scenario("standard")
        base = [_result(f"c{i}", "deny", "approve", i < 6, cost=0.001)
                for i in range(10)]
        view = value_view({"base": base}, s, price_date="2026-09-28")
        html = _value_page(view)
        self.assertIn("Attacker cost per flip direction (C-9)", html)
        self.assertIn("<td>deny-to-approve</td>", html)
        self.assertIn("withheld", html)

    def test_value_rendering_marks_lower_bound(self):
        # One priced call + one unpriced call: the $/flip figure is a
        # lower bound, so every C-9 renderer must mark it with ≥ and a
        # legend. Withheld-only rows carry no marker.
        from peira.cli import _value_text, _value_page
        from peira.pricing import load_pricing_table
        models = load_pricing_table().get("models") or {}
        if not models:
            self.skipTest("pinned pricing table has no models")
        model = sorted(models)[0]
        s = load_cost_scenario("standard")
        base = ([_result(f"c{i}", "deny", "approve", True, cost=0.001,
                        a_model=model) for i in range(2)]
                + [_result(f"c{i}", "deny", "approve", True, cost=0.0,
                           a_model="unknown-model") for i in range(2, 4)])
        view = value_view({"base": base}, s, price_date="2026-09-28")
        row = view["adapters"]["base"]["attacker_cost_per_direction"][
            "deny-to-approve"]
        self.assertTrue(row["sufficient"])
        self.assertEqual(row["n_unpriced"], 2)
        text = _value_text(view)
        self.assertIn("≥$0.00/flip", text)
        self.assertIn("lower bounds", text)
        html = _value_page(view)
        self.assertIn("≥$0.00", html)
        self.assertIn("lower bound", html)


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


if __name__ == "__main__":
    unittest.main()
