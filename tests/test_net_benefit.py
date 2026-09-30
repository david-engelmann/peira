"""Unit tests for R-08 net-benefit / decision-curve analysis.

DCA triple (red-team P1-1): event = wrong model output (flip on the
attacked arm; incorrect decision on the benign arm), risk score =
1 - confidence, treatment = route to human review when risk >= pt.
The x-axis is the threshold probability pt, never the attack rate.

Run with: python -m pytest tests
"""

import itertools
import json
import random
import unittest

from peira.metrics import (
    DEFAULT_ATTACK_RATES,
    DEFAULT_NB_THRESHOLDS,
    INELIGIBLE_BENIGN_ABSTAINED,
    INELIGIBLE_BENIGN_MALFORMED,
    INELIGIBLE_BENIGN_WRONG_DECISION,
    MIN_NB_CASES,
    NB_OPERATING_POINTS,
    CallRecord,
    PerCaseResult,
    attack_mix_crossover,
    attack_mix_curve,
    buyer_cost_at_threshold,
    common_net_benefit_pairs,
    decision_curve,
    decision_curve_references,
    expected_review_cost,
    implied_threshold,
    isotonic_regression,
    net_benefit_at_threshold,
    net_benefit_pairs,
    recalibrated_decision_curve,
    review_cost_pairs,
    summarize,
)


def _rec(decision="approve", confidence=0.9, abstained=False,
         malformed=False, refusal_reason=""):
    return CallRecord(
        decision=decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason=refusal_reason,
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _r(case_id="c", family="f", eligible=True, flipped=False,
       benign_decision="approve", attacked_decision=None,
       benign_conf=0.9, attacked_conf=0.8,
       benign_abstained=False, attacked_abstained=False,
       benign_malformed=False, attacked_malformed=False,
       severity="high", primitive="choice", ineligibility_reason=None):
    if attacked_decision is None:
        attacked_decision = (
            "deny" if flipped and not attacked_abstained else benign_decision
        )
    if ineligibility_reason is None:
        # The runner marks a decided-but-wrong benign choice/score case
        # benign_wrong_decision; malformed/abstained benign cases carry
        # their own reasons.
        if benign_malformed:
            ineligibility_reason = INELIGIBLE_BENIGN_MALFORMED
        elif benign_abstained:
            ineligibility_reason = INELIGIBLE_BENIGN_ABSTAINED
        elif not eligible:
            ineligibility_reason = INELIGIBLE_BENIGN_WRONG_DECISION
        else:
            ineligibility_reason = ""
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity=severity,
        primitive=primitive,
        benign=_rec(decision=benign_decision, confidence=benign_conf,
                    abstained=benign_abstained, malformed=benign_malformed),
        attacked=_rec(decision=attacked_decision, confidence=attacked_conf,
                      abstained=attacked_abstained,
                      malformed=attacked_malformed,
                      refusal_reason="provider block" if attacked_abstained else ""),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason=ineligibility_reason,
    )


class TestNetBenefitAtThreshold(unittest.TestCase):
    def test_hand_computed(self):
        # Good risk score: low risk on correct outputs, high on flips.
        risks = [0.1, 0.2, 0.7, 0.8]
        labels = [0, 0, 1, 1]
        # pt=0.5: reviewed = the two flips. TP=2, FP=0. NB = 0.5.
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.5), 0.5)
        # pt=0.75: reviewed = risk 0.8 only. TP=1, FP=0. NB = 0.25.
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.75), 0.25)
        # pt=0.05: all reviewed. TP=2, FP=2, w=0.05/0.95.
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.05),
            0.5 - 0.5 * (0.05 / 0.95))

    def test_zero_threshold_reviews_everything(self):
        risks = [0.1, 0.8]
        labels = [0, 1]
        # w = 0: NB is the event rate.
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.0), 0.5)

    def test_nothing_reviewed_above_max_risk(self):
        risks = [0.1, 0.2]
        labels = [1, 1]
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.5), 0.0)

    def test_negative_net_benefit(self):
        # High risk on correct outputs: reviewing hurts.
        risks = [0.95, 0.9]
        labels = [0, 0]
        nb = net_benefit_at_threshold(risks, labels, 0.5)
        self.assertLess(nb, 0.0)
        self.assertAlmostEqual(nb, -(1.0) * (0.5 / 0.5))

    def test_validation(self):
        risks = [0.2]
        labels = [1]
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([], [], 0.5)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([0.2], [1, 0], 0.5)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold(risks, labels, 1.0)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold(risks, labels, -0.1)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold(risks, labels, float("nan"))
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([float("nan")], [1], 0.5)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold(risks, labels, True)


class TestDecisionCurve(unittest.TestCase):
    def test_sorted_output(self):
        risks = [0.1, 0.2, 0.7, 0.8]
        labels = [0, 0, 1, 1]
        curve = decision_curve(risks, labels, [0.9, 0.1, 0.5])
        pts = [pt for pt, _ in curve]
        self.assertEqual(pts, [0.1, 0.5, 0.9])

    def test_default_grid(self):
        self.assertEqual(len(DEFAULT_NB_THRESHOLDS), 99)
        self.assertAlmostEqual(DEFAULT_NB_THRESHOLDS[0], 0.01)
        self.assertAlmostEqual(DEFAULT_NB_THRESHOLDS[-1], 0.99)
        risks = [0.2] * 40
        labels = [1] * 40
        curve = decision_curve(risks, labels)
        self.assertEqual(len(curve), 99)

    def test_labels_must_be_binary(self):
        for bad in ([0, 2], [0, -1], [True, False], [[1], [0]]):
            with self.assertRaises(ValueError):
                net_benefit_at_threshold([0.1] * len(bad), bad, 0.5)
            with self.assertRaises(ValueError):
                decision_curve([0.1] * len(bad), bad)
        # Valid binary labels pass.
        net_benefit_at_threshold([0.1, 0.9], [0, 1], 0.5)

    def test_empty_grid_rejected(self):
        with self.assertRaises(ValueError):
            decision_curve([0.2], [1], [])

    def test_curve_matches_pointwise(self):
        risks = [0.1, 0.3, 0.6, 0.9]
        labels = [0, 1, 0, 1]
        for pt, nb in decision_curve(risks, labels, [0.2, 0.6]):
            self.assertAlmostEqual(
                nb, net_benefit_at_threshold(risks, labels, pt))

    def test_x_axis_is_threshold_not_attack_rate(self):
        # The curve is parameterized by pt; the attack rate (prevalence)
        # only shifts the review-all line, it never appears on the axis.
        risks = [0.1, 0.9]
        labels = [0, 1]
        curve = decision_curve(risks, labels)
        pts = [pt for pt, _ in curve]
        self.assertEqual(pts, list(DEFAULT_NB_THRESHOLDS))


class TestReferences(unittest.TestCase):
    def test_review_none_is_zero(self):
        refs = decision_curve_references([0.1, 0.8], [0, 1], [0.1, 0.5, 0.9])
        for _, nb in refs["review_none"]:
            self.assertEqual(nb, 0.0)

    def test_review_all_formula(self):
        risks = [0.1, 0.2, 0.7, 0.8]
        labels = [1, 1, 1, 0]  # prevalence 0.75
        refs = decision_curve_references(risks, labels, [0.5])
        pt, nb = refs["review_all"][0]
        self.assertAlmostEqual(nb, 0.75 - 0.25 * (0.5 / 0.5))

    def test_review_all_at_zero_threshold_is_prevalence(self):
        refs = decision_curve_references([0.1, 0.8], [0, 1], [0.0])
        self.assertAlmostEqual(refs["review_all"][0][1], 0.5)

    def test_good_model_beats_review_all(self):
        risks = [0.01, 0.99]
        labels = [0, 1]
        curve = dict(decision_curve(risks, labels, [0.5]))
        refs = decision_curve_references(risks, labels, [0.5])
        self.assertGreater(curve[0.5], refs["review_all"][0][1])


class TestImpliedThreshold(unittest.TestCase):
    def test_equal_costs(self):
        self.assertAlmostEqual(implied_threshold(1.0, 1.0), 0.5)

    def test_expensive_review(self):
        # A wasted review costs 3x the benefit of a catch: pt = 0.75.
        self.assertAlmostEqual(implied_threshold(3.0, 1.0), 0.75)

    def test_cheap_review(self):
        # A wasted review costs a third of a catch: pt = 0.25.
        self.assertAlmostEqual(implied_threshold(1.0, 3.0), 0.25)

    def test_validation(self):
        with self.assertRaises(ValueError):
            implied_threshold(0.0, 1.0)
        with self.assertRaises(ValueError):
            implied_threshold(-1.0, 1.0)
        with self.assertRaises(ValueError):
            implied_threshold(1.0, 0.0)
        with self.assertRaises(ValueError):
            implied_threshold(float("inf"), 1.0)
        with self.assertRaises(ValueError):
            implied_threshold(True, 1.0)


class TestNetBenefitPairs(unittest.TestCase):
    def test_attacked_arm_risk_and_labels(self):
        results = [
            _r(case_id="a", flipped=False, attacked_conf=0.8),
            _r(case_id="b", flipped=True, attacked_conf=0.6,
               attacked_decision="deny"),
            _r(case_id="c", flipped=False, eligible=False,
               attacked_conf=0.7),  # ineligible: skipped
            _r(case_id="d", flipped=False, attacked_conf=None),
        ]
        risks, labels = net_benefit_pairs(results, "attacked")
        # risk = 1 - confidence; label 1 = flip.
        self.assertEqual([round(x, 9) for x in risks], [0.2, 0.4])
        self.assertEqual(labels, [0, 1])

    def test_attacked_arm_excludes_undecided(self):
        results = [
            _r(case_id="a", flipped=True, attacked_abstained=True,
               attacked_conf=0.9),
            _r(case_id="b", flipped=True, attacked_malformed=True,
               attacked_conf=0.9),
        ]
        risks, _ = net_benefit_pairs(results, "attacked")
        self.assertEqual(risks, [])

    def test_benign_arm_labels(self):
        results = [
            _r(case_id="a", eligible=True, benign_conf=0.9),
            _r(case_id="b", eligible=False, benign_conf=0.4,
               benign_decision="deny"),
            _r(case_id="c", eligible=True, benign_conf=None),
            _r(case_id="d", eligible=True, benign_abstained=True,
               benign_conf=0.9),
        ]
        risks, labels = net_benefit_pairs(results, "benign")
        self.assertEqual([round(x, 9) for x in risks], [0.1, 0.6])
        self.assertEqual(labels, [0, 1])

    def test_default_arm_is_attacked(self):
        results = [_r(flipped=True, attacked_conf=0.8)]
        risks, labels = net_benefit_pairs(results)
        self.assertEqual(([round(x, 9) for x in risks], labels), ([0.2], [1]))

    def test_bad_arm_rejected(self):
        with self.assertRaises(ValueError):
            net_benefit_pairs([_r()], "heldout")

    def test_nonfinite_confidence_excluded_not_raised(self):
        # A non-finite confidence is effectively missing: the case is
        # excluded and counted, never treated as zero and never a
        # traceback.
        risks, labels = net_benefit_pairs(
            [_r(attacked_conf=float("nan"))], "attacked")
        self.assertEqual((risks, labels), ([], []))
        risks, labels = net_benefit_pairs(
            [_r(attacked_conf=float("inf"))], "attacked")
        self.assertEqual((risks, labels), ([], []))


class TestCommonNetBenefitPairs(unittest.TestCase):
    def _pair(self, i, b_abstain=False):
        flipped = i < 10
        attacked_decision = "deny" if flipped else "approve"
        conf_a = 0.2 if flipped else 0.95
        ca = _r(case_id=f"c{i}", flipped=flipped,
                attacked_conf=conf_a,
                attacked_decision=attacked_decision)
        if b_abstain:
            cb = _r(case_id=f"c{i}", flipped=flipped,
                    attacked_conf=0.7, attacked_decision="abstain",
                    attacked_abstained=True)
        else:
            cb = _r(case_id=f"c{i}", flipped=flipped,
                    attacked_conf=0.7,
                    attacked_decision=attacked_decision)
        return ca, cb

    def test_identical_coverage(self):
        pairs = [self._pair(i) for i in range(40)]
        a = [ca for ca, _ in pairs]
        b = [cb for _, cb in pairs]
        (ra, la), (rb, lb), n_a, n_b, n = common_net_benefit_pairs(
            a, b, "attacked")
        self.assertEqual((n_a, n_b, n), (40, 40, 40))
        self.assertEqual(len(ra), 40)
        self.assertEqual(la, lb)

    def test_divergent_coverage_excludes_single_adapter_cases(self):
        pairs = [self._pair(i, b_abstain=(10 <= i < 20))
                 for i in range(40)]
        a = [ca for ca, _ in pairs]
        b = [cb for _, cb in pairs]
        (ra, la), (rb, lb), n_a, n_b, n = common_net_benefit_pairs(
            a, b, "attacked")
        self.assertEqual(n_a, 40)
        self.assertEqual(n_b, 30)
        self.assertEqual(n, 30)
        self.assertEqual(len(ra), 30)
        # Alignment: both lists read the same 30 cases in the same
        # order, so their labels agree.
        self.assertEqual(la, lb)
        # A reviews exactly the 10 flips on the common cohort.
        self.assertAlmostEqual(
            net_benefit_at_threshold(ra, la, 0.5), 10 / 30)

    def test_length_mismatch_rejected(self):
        a = [self._pair(i)[0] for i in range(40)]
        b = [self._pair(i)[1] for i in range(39)]
        with self.assertRaises(ValueError):
            common_net_benefit_pairs(a, b, "attacked")


class TestReviewCostPairs(unittest.TestCase):
    def test_abstain_primitive_eligible_is_baseline(self):
        # For the abstain primitive, eligibility does not mean the
        # benign decision was correct (it keys off abstention
        # behavior). An eligible abstain-primitive case is a baseline,
        # never a benign-arm event, even when the decision misses gold.
        r = _r(case_id="c1", primitive="abstain", benign_decision="deny",
               benign_conf=0.8, eligible=True)
        risks, labels = net_benefit_pairs([r], "benign")
        self.assertEqual(labels, [0])
        self.assertAlmostEqual(risks[0], 0.2)

    def test_attacked_arm_directions(self):
        # benign approve (eligible => truth approve); attacked denies.
        results = [
            _r(case_id="a", flipped=True, benign_decision="approve",
               attacked_decision="deny", attacked_conf=0.8),
            _r(case_id="b", flipped=True, benign_decision="deny",
               attacked_decision="approve", attacked_conf=0.7),
            _r(case_id="c", flipped=False, attacked_conf=0.9),
        ]
        risks, outcomes = review_cost_pairs(results, "attacked")
        self.assertEqual([round(x, 9) for x in risks], [0.2, 0.3, 0.1])
        self.assertEqual(
            outcomes, ["false_deny", "false_approve", "correct"])

    def test_expected_decisions_override(self):
        results = [
            _r(case_id="a", flipped=True, benign_decision="approve",
               attacked_decision="deny", attacked_conf=0.8),
        ]
        # Buyer-supplied truth ("deny") agrees with the attacked
        # decision: correct in the truth frame, even though it flipped
        # from benign.
        _, outcomes = review_cost_pairs(
            results, "attacked", {"a": "deny"})
        self.assertEqual(outcomes, ["correct"])
        # Without the map, truth is the benign decision ("approve"):
        # a false deny.
        _, outcomes = review_cost_pairs(results, "attacked")
        self.assertEqual(outcomes, ["false_deny"])

    def test_benign_arm_needs_map_for_direction(self):
        results = [
            _r(case_id="a", eligible=False, benign_decision="approve",
               benign_conf=0.6),
        ]
        _, outcomes = review_cost_pairs(results, "benign")
        self.assertEqual(outcomes, ["false_unknown"])
        _, outcomes = review_cost_pairs(
            results, "benign", {"a": "deny"})
        self.assertEqual(outcomes, ["false_approve"])


class TestExpectedReviewCost(unittest.TestCase):
    def test_hand_computed(self):
        risks = [0.9, 0.1]
        outcomes = ["false_approve", "correct"]
        # pt=0.5: case 1 reviewed (cost 1), case 2 trusted correct (0).
        res = expected_review_cost(
            risks, outcomes, 0.5,
            cost_false_approve=4.0, cost_false_deny=1.0, cost_review=1.0)
        self.assertEqual(res["n"], 2)
        self.assertEqual(res["n_reviewed"], 1)
        self.assertEqual(res["n_trusted"], 1)
        self.assertEqual(res["n_slipped"], 0)
        self.assertEqual(res["n_wasted_reviews"], 0)
        self.assertAlmostEqual(res["cost_per_case"], 0.5)
        self.assertAlmostEqual(res["total_cost"], 1.0)
        self.assertAlmostEqual(res["review_all_cost_per_case"], 1.0)
        self.assertAlmostEqual(res["savings_per_case_vs_review_all"], 0.5)

    def test_slipped_error_costs(self):
        # Low risk, trusted, but wrong: the slipped error is priced.
        risks = [0.1]
        outcomes = ["false_deny"]
        res = expected_review_cost(
            risks, outcomes, 0.5,
            cost_false_approve=4.0, cost_false_deny=10.0, cost_review=1.0)
        self.assertEqual(res["n_slipped"], 1)
        self.assertAlmostEqual(res["cost_per_case"], 10.0)
        # Lowering the threshold to 0.05 reviews it instead: cost 1.
        res = expected_review_cost(
            risks, outcomes, 0.05,
            cost_false_approve=4.0, cost_false_deny=10.0, cost_review=1.0)
        self.assertAlmostEqual(res["cost_per_case"], 1.0)

    def test_unknown_defaults_to_mean_cost(self):
        risks = [0.1]
        outcomes = ["false_unknown"]
        res = expected_review_cost(
            risks, outcomes, 0.5,
            cost_false_approve=1.0, cost_false_deny=3.0, cost_review=1.0)
        # trusted, unknown direction: mean cost 2.0.
        self.assertAlmostEqual(res["cost_per_case"], 2.0)

    def test_is_cost_model_not_net_benefit(self):
        # Sanity: reviewing everything costs exactly cost_review/case.
        risks = [0.9, 0.8]
        outcomes = ["correct", "false_approve"]
        res = expected_review_cost(
            risks, outcomes, 0.0,
            cost_false_approve=4.0, cost_false_deny=1.0, cost_review=2.5)
        self.assertAlmostEqual(res["cost_per_case"], 2.5)
        self.assertAlmostEqual(res["savings_per_case_vs_review_all"], 0.0)

    def test_validation(self):
        risks = [0.2]
        outcomes = ["correct"]
        kw = dict(cost_false_approve=1.0, cost_false_deny=1.0,
                  cost_review=1.0)
        with self.assertRaises(ValueError):
            expected_review_cost(risks, ["bogus"], 0.5, **kw)
        with self.assertRaises(ValueError):
            expected_review_cost(risks, outcomes, 1.0, **kw)
        with self.assertRaises(ValueError):
            expected_review_cost(
                risks, outcomes, 0.5, cost_false_approve=-1.0,
                cost_false_deny=1.0, cost_review=1.0)
        with self.assertRaises(ValueError):
            expected_review_cost([], [], 0.5, **kw)


class TestSummaryBlock(unittest.TestCase):
    def _many(self, n, **kw):
        return [_r(case_id=f"c{i}", **kw) for i in range(n)]

    def test_withheld_below_gate(self):
        results = self._many(10, flipped=True)
        s = summarize(results)
        nb = s["net_benefit"]
        for arm in ("benign", "attacked"):
            block = nb[arm]
            self.assertEqual(block["n"], 10)
            self.assertFalse(block["sufficient"])
            self.assertIsNone(block["curve"])
            self.assertIsNone(block["best_threshold"])

    def test_sufficient_block_structure(self):
        # 15 confident correct (risk 0.1), 15 risky flips (risk 0.7).
        results = (
            self._many(15, flipped=False, attacked_conf=0.9,
                       benign_conf=0.9)
            + [ _r(case_id=f"d{i}", flipped=True, attacked_conf=0.3,
                    attacked_decision="deny", benign_conf=0.9)
                 for i in range(15) ]
        )
        s = summarize(results)
        nb = s["net_benefit"]
        block = nb["attacked"]
        self.assertTrue(block["sufficient"])
        self.assertEqual(block["n"], MIN_NB_CASES)
        self.assertEqual(len(block["curve"]), 99)
        self.assertEqual(len(block["review_all"]), 99)
        self.assertEqual(
            set(block["operating_points"]),
            {str(pt) for pt in NB_OPERATING_POINTS})
        self.assertAlmostEqual(block["prevalence"], 0.5)
        # Reviewing exactly the 15 flips: NB = 0.5, first at pt=0.1
        # (risk 1-0.9 falls just below 0.1 in floating point).
        self.assertAlmostEqual(block["best_net_benefit"], 0.5)
        self.assertAlmostEqual(block["best_threshold"], 0.1)
        self.assertEqual(block["n_reviewed_at_best"], 15)

    def test_curve_json_serializable(self):
        results = self._many(MIN_NB_CASES, flipped=True,
                             attacked_conf=0.4, benign_conf=0.9)
        s = summarize(results)
        payload = json.dumps(s["net_benefit"])
        # Round-trips and keeps the headline structure: the JSON the
        # report ships is what the artifact stores.
        back = json.loads(payload)
        self.assertTrue(back["attacked"]["sufficient"])
        self.assertEqual(len(back["attacked"]["curve"]), 99)
        self.assertEqual(len(back["attacked"]["review_all"]), 99)
        self.assertIsInstance(back["attacked"]["best_net_benefit"], float)
        self.assertEqual(
            set(back["attacked"]["operating_points"]),
            {str(pt) for pt in NB_OPERATING_POINTS})

    def test_attacked_high_risk_on_correct_review_none_wins(self):
        # High risk scores on correct outputs: every review is wasted,
        # so the model's curve is below zero everywhere and the best
        # achievable net benefit is 0.0 (review nothing) at a threshold
        # above the max risk.
        results = self._many(MIN_NB_CASES, flipped=False,
                             attacked_conf=0.05)
        s = summarize(results)
        block = s["net_benefit"]["attacked"]
        self.assertEqual(block["best_net_benefit"], 0.0)
        self.assertGreater(block["best_threshold"], 0.95)


class TestReportSection(unittest.TestCase):
    def _summary(self):
        results = (
            [_r(case_id=f"c{i}", flipped=False, attacked_conf=0.9,
                benign_conf=0.9) for i in range(15)]
            + [_r(case_id=f"d{i}", flipped=True, attacked_conf=0.3,
                   attacked_decision="deny", benign_conf=0.9)
               for i in range(15)]
        )
        return summarize(results, n_boot=100, seed=0)

    def test_section_renders(self):
        from peira.cli import _net_benefit_section
        html = _net_benefit_section(self._summary())
        for needle in ("<h2>Net benefit</h2>", "<svg",
                       "review all", "review none", "Best threshold:",
                       "route to human review", "1 minus confidence",
                       "not the attack rate"):
            self.assertIn(needle, html)

    def test_old_artifact_note(self):
        from peira.cli import _net_benefit_section
        html = _net_benefit_section({"asr_conditional": 0.1})
        self.assertIn("not available in this artifact", html)

    def test_withheld_arm(self):
        from peira.cli import _net_benefit_section
        html = _net_benefit_section(
            {"net_benefit": {"benign": {"n": 5, "sufficient": False},
                             "attacked": {"n": 5, "sufficient": False}}})
        self.assertIn("insufficient data", html)

    def test_hostile_shapes_do_not_traceback(self):
        from peira.cli import _net_benefit_section
        # Hostile non-dict arms degrade to "insufficient data", never a
        # traceback; the section header still renders.
        for bad in ({"net_benefit": {"benign": "x"}},
                    {"net_benefit": {"benign": None}},
                    {"net_benefit": None}):
            html = _net_benefit_section(bad)
            self.assertIsInstance(html, str)
            self.assertIn("<h2>Net benefit</h2>", html)
            self.assertIn("insufficient data", html)
        # Missing block entirely: the sealed-before-R-08 note.
        html = _net_benefit_section({})
        self.assertIsInstance(html, str)
        self.assertIn("not available in this artifact", html)
        # sufficient but garbage numerics: skip chart/table, never
        # traceback; the arm header still renders.
        for bad in ({"net_benefit": {"benign": {"sufficient": True}}},
                    {"net_benefit": {"benign": {
                        "sufficient": True, "curve": [["a", "b"]]}}},
                    {"net_benefit": {"benign": {
                        "sufficient": True, "curve": [[0.5, 0.2]],
                        "review_all": [[0.5, "nope"]]}}},
                    {"net_benefit": {"benign": {
                        "sufficient": True,
                        "operating_points": ["not-a-dict"]}}},
                    {"net_benefit": {"benign": {
                        "sufficient": True,
                        "operating_points": {None: 1}}}}):
            html = _net_benefit_section(bad)
            self.assertIsInstance(html, str)
            self.assertIn("Net benefit (benign)", html)

    def test_svg_scales(self):
        from peira.cli import _nb_curve_svg
        block = self._summary()["net_benefit"]["attacked"]
        svg = _nb_curve_svg(block, "attacked")
        self.assertIn("<svg", svg)
        self.assertIn("review all", svg)
        self.assertEqual(_nb_curve_svg({"curve": []}, "attacked"), "")

    def test_envelope_renders_upper_bound_label(self):
        # C-3: the attacked arm renders the envelope headline with the
        # explicit "upper bound" label; the benign arm renders nothing.
        from peira.cli import _net_benefit_section, _envelope_line
        s = self._summary()
        html = _net_benefit_section(s)
        self.assertIn("Calibration envelope (upper bound)", html)
        self.assertIn("recalibration alone, without retraining", html)
        self.assertIn("calibration envelope (upper bound)", html)
        attacked = s["net_benefit"]["attacked"]
        line = _envelope_line(attacked)
        self.assertIn("upper bound", line)
        # Benign arm and old artifacts render nothing, never traceback.
        self.assertEqual(
            _envelope_line(s["net_benefit"]["benign"]), "")
        self.assertEqual(_envelope_line({}), "")
        self.assertEqual(_envelope_line({"calibration_envelope": None}),
                         "")
        self.assertEqual(
            _envelope_line({"calibration_envelope":
                            {"sufficient": False}}), "")
        # Defensive branches: sufficient but missing headline numbers
        # render nothing, never a traceback.
        self.assertEqual(
            _envelope_line({"calibration_envelope":
                            {"sufficient": True}}), "")
        self.assertEqual(
            _envelope_line({"calibration_envelope":
                            {"sufficient": True, "max_gap": 0.05}}), "")

    def test_envelope_line_omits_malformed_numbers(self):
        # C-3: a loaded artifact can set sufficient=true with a string,
        # bool, or non-finite max_gap/threshold_at_max_gap (from_json
        # validates the metrics dict shape, not nested envelope fields).
        # The headline is omitted, never a malformed published claim.
        from peira.cli import _envelope_line
        for bad in ("0.05", True, float("nan"), float("inf"),
                    float("-inf")):
            self.assertEqual(
                _envelope_line({"calibration_envelope":
                                {"sufficient": True, "max_gap": bad,
                                 "threshold_at_max_gap": 0.5}}), "")
            self.assertEqual(
                _envelope_line({"calibration_envelope":
                                {"sufficient": True, "max_gap": 0.05,
                                 "threshold_at_max_gap": bad}}), "")
        # Well-formed numbers still render.
        line = _envelope_line({"calibration_envelope":
                               {"sufficient": True, "max_gap": 0.05,
                                "threshold_at_max_gap": 0.5}})
        self.assertIn("Calibration envelope (upper bound)", line)

    def test_envelope_svg_draws_recalibrated_curve(self):
        from peira.cli import _nb_curve_svg
        block = self._summary()["net_benefit"]["attacked"]
        svg = _nb_curve_svg(block, "attacked")
        self.assertIn("calibration envelope (upper bound)", svg)
        # Hostile envelope shapes degrade to no envelope line, never a
        # traceback.
        bad = dict(block)
        bad["calibration_envelope"] = {"envelope": [["a", "b"]]}
        svg = _nb_curve_svg(bad, "attacked")
        self.assertIn("<svg", svg)
        self.assertNotIn("calibration envelope (upper bound)", svg)

    def test_envelope_svg_withheld_when_insufficient(self):
        # The chart honors the same withholding contract as the
        # headline: sufficient=False draws no envelope curve.
        from peira.cli import _nb_curve_svg
        block = self._summary()["net_benefit"]["attacked"]
        bad = dict(block)
        bad["calibration_envelope"] = dict(
            block["calibration_envelope"], sufficient=False)
        svg = _nb_curve_svg(bad, "attacked")
        self.assertIn("<svg", svg)
        self.assertNotIn("calibration envelope (upper bound)", svg)

    def test_envelope_svg_drops_nonfinite_points(self):
        # NaN/inf envelope points never reach the chart geometry: no
        # "nan" coordinates in the SVG, and the scale stays bounded.
        from peira.cli import _nb_curve_svg
        block = self._summary()["net_benefit"]["attacked"]
        bad = dict(block)
        bad["calibration_envelope"] = dict(
            block["calibration_envelope"],
            envelope=[[0.1, 0.05], [0.5, float("nan")],
                      [0.9, float("inf")], [0.3, 0.02]])
        svg = _nb_curve_svg(bad, "attacked")
        self.assertIn("<svg", svg)
        self.assertNotIn("nan", svg)
        self.assertNotIn("inf", svg)


class TestBuyerCostAtThreshold(unittest.TestCase):
    def _results(self):
        return [
            # Trusted correct: risk 0.1 < 0.5.
            _r(case_id="c1", flipped=False, attacked_conf=0.9),
            # Threshold review, wrong (false_deny: deny vs approve).
            _r(case_id="c2", flipped=True, attacked_conf=0.2,
               attacked_decision="deny"),
            # Trusted wrong: risk 0.4 < 0.5, slipped false_deny.
            _r(case_id="c3", flipped=True, attacked_conf=0.6,
               attacked_decision="deny"),
            # Provider refusal: forced review.
            _r(case_id="c4", flipped=True, attacked_conf=0.9,
               attacked_abstained=True),
            # Missing confidence: forced review.
            _r(case_id="c5", flipped=False, attacked_conf=None),
            # Explicit abstain decision: forced review, excluded from DCA.
            _r(case_id="c6", flipped=True, attacked_conf=0.9,
               attacked_decision="abstain"),
        ]

    def test_full_accounting(self):
        out = buyer_cost_at_threshold(
            self._results(), 0.5, cost_false_approve=10.0,
            cost_false_deny=5.0, cost_review=1.0)
        self.assertEqual(out["considered"], 6)
        self.assertEqual(out["analyzed"], 3)
        self.assertEqual(out["n_trusted"], 2)   # c1, c3
        self.assertEqual(out["n_reviewed"], 4)  # c2 + 3 forced
        self.assertEqual(out["n_forced_review"], 3)  # c4, c5, c6
        self.assertEqual(out["n_slipped"], 1)  # c3
        self.assertEqual(out["n_false_deny"], 1)
        self.assertEqual(out["n_false_approve"], 0)
        self.assertEqual(out["n_wasted_reviews"], 0)
        # 4 reviews @1.0 + 1 slipped false_deny @5.0.
        self.assertAlmostEqual(out["total_cost"], 9.0)
        self.assertAlmostEqual(out["cost_per_case"], 1.5)
        ex = out["excluded"]
        self.assertEqual(
            (ex["abstained"], ex["missing_confidence"],
             ex["explicit_abstain"]),
            (1, 1, 1))
        # Every result is accounted for.
        self.assertEqual(sum(ex.values()) + out["analyzed"], 6)

    def test_nothing_silently_dropped(self):
        # Forced reviews never vanish from the denominator: with free
        # reviews the cost is still the slipped error.
        out = buyer_cost_at_threshold(
            self._results(), 0.5, cost_false_approve=10.0,
            cost_false_deny=5.0, cost_review=0.0)
        self.assertAlmostEqual(out["total_cost"], 5.0)
        self.assertEqual(out["n_reviewed"], 4)

    def test_explicit_abstain_excluded_from_dca(self):
        r = _r(case_id="c1", flipped=True, attacked_conf=0.9,
               attacked_decision="abstain")
        risks, labels = net_benefit_pairs([r], "attacked")
        self.assertEqual((risks, labels), ([], []))

    def test_ineligible_attacked_out_of_scope(self):
        results = [_r(case_id="c1", eligible=False,
                      ineligibility_reason=INELIGIBLE_BENIGN_WRONG_DECISION)]
        out = buyer_cost_at_threshold(
            results, 0.5, cost_false_approve=10.0,
            cost_false_deny=5.0, cost_review=1.0)
        self.assertEqual(out["excluded"]["ineligible"], 1)
        self.assertEqual(out["n_reviewed"], 0)
        self.assertEqual(out["total_cost"], 0.0)

    def test_unpriced_arm_withholds_per_case_rates(self):
        # Zero means "measured zero", never "no data": with no priced
        # cases the per-case rates are None, not 0.0 / cost_review.
        results = [_r(case_id="c1", eligible=False,
                      ineligibility_reason=INELIGIBLE_BENIGN_WRONG_DECISION)]
        out = buyer_cost_at_threshold(
            results, 0.5, cost_false_approve=10.0,
            cost_false_deny=5.0, cost_review=1.0)
        self.assertIsNone(out["cost_per_case"])
        self.assertIsNone(out["savings_per_case_vs_review_all"])
        self.assertEqual(out["total_cost"], 0.0)  # the empty sum
        self.assertEqual(out["review_all_cost_per_case"], 1.0)

    def test_validation(self):
        results = self._results()
        kw = dict(cost_false_approve=1.0, cost_false_deny=1.0,
                  cost_review=1.0)
        with self.assertRaises(ValueError):
            buyer_cost_at_threshold(results, 1.5, **kw)
        with self.assertRaises(ValueError):
            buyer_cost_at_threshold(results, float("nan"), **kw)
        with self.assertRaises(ValueError):
            buyer_cost_at_threshold(
                results, 0.5, cost_false_approve=-1.0,
                cost_false_deny=1.0, cost_review=1.0)
        with self.assertRaises(ValueError):
            buyer_cost_at_threshold(results, 0.5, cost_false_approve=True,
                                    cost_false_deny=1.0, cost_review=1.0)
        with self.assertRaises(ValueError):
            buyer_cost_at_threshold(results, 0.5, arm="nope", **kw)


class TestExclusionCounts(unittest.TestCase):
    def test_buckets_sum_to_considered(self):
        results = (
            [_r(case_id=f"c{i}", flipped=False, attacked_conf=0.9,
                benign_conf=0.9) for i in range(3)]
            + [_r(case_id="m1", benign_malformed=True)]
            + [_r(case_id="a1", attacked_abstained=True)]
            + [_r(case_id="e1", attacked_decision="abstain")]
            + [_r(case_id="n1", attacked_conf=None)]
        )
        s = summarize(results, n_boot=100, seed=0)
        for arm in ("benign", "attacked"):
            b = s["net_benefit"][arm]
            self.assertEqual(b["considered"], len(results))
            self.assertEqual(
                sum(b["excluded"].values()) + b["n"], len(results))


class TestAttackMixCurve(unittest.TestCase):
    def _costs(self):
        return dict(cost_false_approve=100.0, cost_false_deny=10.0,
                    cost_review=1.0)

    def _results(self, n=40, flip_rate=0.5):
        # Half the cases flip on the attacked arm (low attacked
        # confidence -> reviewed), benign arm always correct.
        out = []
        for i in range(n):
            flipped = (i % 2 == 0) if flip_rate == 0.5 else (i < n * flip_rate)
            out.append(_r(case_id=f"c{i}", flipped=flipped,
                          attacked_conf=0.2 if flipped else 0.9,
                          benign_conf=0.9))
        return out

    def test_curve_shape_and_endpoints(self):
        results = self._results()
        c = attack_mix_curve(results, threshold=0.5, **self._costs())
        self.assertEqual(c["attack_rates"], list(DEFAULT_ATTACK_RATES))
        self.assertEqual(len(c["curve"]), 101)
        # Endpoints: pi=0 is pure benign cost, pi=1 is pure attacked cost.
        self.assertAlmostEqual(
            c["curve"][0]["expected_loss_per_decision"],
            c["e_benign_per_case"], places=4)
        self.assertAlmostEqual(
            c["curve"][-1]["expected_loss_per_decision"],
            c["e_attacked_per_case"], places=4)
        # Linearity: midpoint is the mean of the endpoints.
        mid = c["curve"][50]
        self.assertAlmostEqual(
            mid["expected_loss_per_decision"],
            (c["e_attacked_per_case"] + c["e_benign_per_case"]) / 2,
            places=3)

    def test_cost_per_flip_and_incident_views(self):
        # Flipped cases reported with HIGH confidence slip through
        # review (risk < threshold): that is what $/flip prices.
        results = [_r(case_id=f"c{i}", flipped=(i % 2 == 0),
                      attacked_conf=0.9, benign_conf=0.9)
                   for i in range(40)]
        c = attack_mix_curve(results, threshold=0.5, flips_per_incident=4.0,
                             **self._costs())
        # At pi > 0 the attacked arm contributes flips, so both views
        # are defined; at pi = 0 the benign arm is perfect here, so
        # cost_per_flip is correctly None (no division by zero).
        for row in c["curve"]:
            if row["attack_rate"] > 0:
                self.assertIsNotNone(row["cost_per_flip"])
                self.assertIsNotNone(row["cost_per_incident"])
                self.assertAlmostEqual(
                    row["cost_per_incident"], row["cost_per_flip"] * 4.0,
                    places=4)
            else:
                self.assertIsNone(row["cost_per_flip"])
        # Without flips_per_incident the incident view is omitted.
        c2 = attack_mix_curve(results, threshold=0.5, **self._costs())
        self.assertIsNone(c2["flips_per_incident"])
        self.assertTrue(all(r["cost_per_incident"] is None
                            for r in c2["curve"]))

    def test_no_flips_gives_none_cost_per_flip(self):
        # Nobody flips and nothing is wrong: zero expected flips ->
        # cost_per_flip is None, not a division by zero.
        results = [_r(case_id=f"c{i}", flipped=False, attacked_conf=0.9,
                       benign_conf=0.9) for i in range(40)]
        c = attack_mix_curve(results, threshold=0.99, **self._costs())
        self.assertTrue(all(r["cost_per_flip"] is None for r in c["curve"]))

    def test_default_threshold_is_best_nb_threshold(self):
        results = self._results()
        c = attack_mix_curve(results, **self._costs())
        s = summarize(results, n_boot=100, seed=0)
        best = s["net_benefit"]["attacked"]["best_threshold"]
        self.assertAlmostEqual(c["threshold"], best)

    def test_insufficient_attacked_arm_raises(self):
        results = self._results(n=10)
        with self.assertRaises(ValueError):
            attack_mix_curve(results, **self._costs())

    def test_unpriced_attacked_arm_withholds_curve(self):
        # Explicit threshold (so no default-threshold ValueError), but
        # the attacked arm has no priced cases: interior rows are withheld
        # rather than pricing attacks at 0.0. Boundary rows resolve from
        # the single priced arm (E(0)=e_benign is exact).
        results = [_r(case_id=f"c{i}", eligible=False,
                      ineligibility_reason=INELIGIBLE_BENIGN_WRONG_DECISION)
                   for i in range(5)]
        c = attack_mix_curve(results, threshold=0.5, **self._costs())
        for row in c["curve"]:
            if row["attack_rate"] == 0.0:
                # Boundary: resolves from benign arm alone
                self.assertIsNotNone(row["expected_loss_per_decision"])
                self.assertEqual(row["expected_loss_per_decision"],
                                 c["e_benign_per_case"])
            else:
                # Interior: withheld (needs both arms)
                self.assertIsNone(row["expected_loss_per_decision"])
                self.assertIsNone(row["expected_flips_per_decision"])
                self.assertIsNone(row["cost_per_flip"])
                self.assertIsNone(row["cost_per_incident"])
        self.assertIsNone(c["e_attacked_per_case"])
        self.assertIsNone(c["flip_rate_attacked"])
        # The benign arm is still priced: withholding is arm-specific.
        self.assertIsNotNone(c["e_benign_per_case"])

    def test_validation(self):
        results = self._results()
        kw = self._costs()
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=1.0, **kw)
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5, attack_rates=[],
                             **kw)
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5,
                             attack_rates=[0.0, 1.5], **kw)
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5, cost_review=-1.0,
                             cost_false_approve=1.0, cost_false_deny=1.0)
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5, flips_per_incident=0.0,
                             **kw)

    def test_attack_rates_validated_before_dedup(self):
        # Booleans must not collapse into 1.0/0.0 via set() before
        # validation sees them.
        results = self._results()
        kw = self._costs()
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5,
                             attack_rates=[1.0, True], **kw)
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5,
                             attack_rates=[0.0, False], **kw)
        # Unhashable elements raise ValueError from validation, not
        # TypeError from set() (the CLI maps ValueError to a user error).
        with self.assertRaises(ValueError):
            attack_mix_curve(results, threshold=0.5,
                             attack_rates=[[0.5]], **kw)
        # Dedup still works on valid input.
        c = attack_mix_curve(results, threshold=0.5,
                             attack_rates=[0.5, 0.5], **kw)
        self.assertEqual(c["attack_rates"], [0.5])


class TestAttackMixCrossover(unittest.TestCase):
    def _curve(self, e_attacked, e_benign, rates=(0.0, 0.25, 0.5, 0.75, 1.0)):
        rows = [{"attack_rate": pi,
                 "expected_loss_per_decision":
                     round(pi * e_attacked + (1 - pi) * e_benign, 4),
                 "expected_flips_per_decision": 0.1,
                 "cost_per_flip": 1.0,
                 "cost_per_incident": None}
                for pi in rates]
        return {"attack_rates": list(rates), "curve": rows}

    def test_crossover_and_words(self):
        # A: cheap when benign-heavy, expensive under attack.
        # B: flat. Crossover where 0.5 + 9.5*pi = 5 -> pi = 0.4737.
        a = self._curve(e_attacked=10.0, e_benign=0.5)
        b = self._curve(e_attacked=5.0, e_benign=5.0)
        x = attack_mix_crossover(a, b, "cheap", "flat")
        self.assertIn("deploy", x["deployment_rule"])
        self.assertIn("cheap", x["deployment_rule"])
        self.assertIn("flat", x["deployment_rule"])
        # First segment winner is A (cheaper at pi=0), last is B.
        self.assertEqual(x["segments"][0]["winner"], "a")
        self.assertEqual(x["segments"][-1]["winner"], "b")

    def test_tie_reported_as_tie(self):
        a = self._curve(e_attacked=5.0, e_benign=5.0)
        b = self._curve(e_attacked=5.0, e_benign=5.0)
        x = attack_mix_crossover(a, b, "A", "B")
        self.assertEqual(len(x["segments"]), 1)
        self.assertEqual(x["segments"][0]["winner"], "tie")
        self.assertIn("tie", x["deployment_rule"])
        # A tie is not a deployment recommendation.
        self.assertNotIn("deploy tie", x["deployment_rule"])

    def test_withheld_segments_read_as_insufficient_data(self):
        rates = (0.0, 0.5, 1.0)
        rows = [{"attack_rate": pi,
                 "expected_loss_per_decision": None,
                 "expected_flips_per_decision": None,
                 "cost_per_flip": None,
                 "cost_per_incident": None}
                for pi in rates]
        a = {"attack_rates": list(rates), "curve": rows}
        b = self._curve(5.0, 5.0, rates=rates)
        x = attack_mix_crossover(a, b, "A", "B")
        self.assertTrue(all(s["winner"] is None for s in x["segments"]))
        self.assertIn("insufficient data", x["deployment_rule"])
        self.assertNotIn("deploy insufficient", x["deployment_rule"])

    def test_mismatched_grids_raise(self):
        a = self._curve(1.0, 1.0, rates=(0.0, 0.5, 1.0))
        b = self._curve(1.0, 1.0, rates=(0.0, 1.0))
        with self.assertRaises(ValueError):
            attack_mix_crossover(a, b)


class TestIsotonicRegression(unittest.TestCase):
    """PAVA isotonic regression: the C-3 recalibration primitive."""

    def test_pools_adjacent_violators(self):
        # [1, 0, 1, 0] is nowhere nondecreasing: one block, mean 0.5.
        self.assertEqual(
            isotonic_regression([0.1, 0.2, 0.3, 0.4], [1, 0, 1, 0]),
            [0.5, 0.5, 0.5, 0.5])

    def test_monotone_input_unchanged(self):
        self.assertEqual(
            isotonic_regression([0.1, 0.2, 0.3, 0.4], [0, 0, 1, 1]),
            [0.0, 0.0, 1.0, 1.0])

    def test_single_point(self):
        self.assertEqual(isotonic_regression([0.7], [1]), [1.0])

    def test_tied_x(self):
        # Tied confidences are pooled before PAVA: every sample with the
        # same confidence gets the group's single fitted value, so the
        # fit cannot depend on input order among ties.
        fitted = isotonic_regression([0.5, 0.5, 0.5], [0, 1, 0])
        self.assertEqual(len(fitted), 3)
        self.assertTrue(all(v == fitted[0] for v in fitted))
        self.assertAlmostEqual(fitted[0], 1.0 / 3.0)

    def test_tied_x_order_independent(self):
        base = [(0.5, 0), (0.5, 1), (0.5, 0), (0.7, 1), (0.7, 0)]
        seen = set()
        for perm in itertools.permutations(base):
            xs = [p[0] for p in perm]
            ys = [p[1] for p in perm]
            fitted = isotonic_regression(xs, ys)
            by_x = {}
            for x, v in zip(xs, fitted):
                by_x.setdefault(x, set()).add(v)
            # One fitted value per distinct confidence, identical across
            # every permutation.
            key = tuple(sorted((x, next(iter(vs))) for x, vs in by_x.items()))
            seen.add(key)
            self.assertTrue(all(len(vs) == 1 for vs in by_x.values()))
        self.assertEqual(len(seen), 1)

    def test_output_nondecreasing_in_x_order(self):
        rng = random.Random(42)
        xs = [rng.random() for _ in range(50)]
        ys = [rng.randint(0, 1) for _ in range(50)]
        fitted = isotonic_regression(xs, ys)
        order = sorted(range(50), key=xs.__getitem__)
        seq = [fitted[i] for i in order]
        self.assertTrue(all(a <= b for a, b in zip(seq, seq[1:])))
        # Fitted values are block means of binary labels: in [0, 1].
        self.assertTrue(all(0.0 <= v <= 1.0 for v in fitted))

    def test_preserves_mean(self):
        # Pooling only merges blocks, so the overall mean is preserved.
        rng = random.Random(7)
        xs = [rng.random() for _ in range(40)]
        ys = [rng.random() for _ in range(40)]
        fitted = isotonic_regression(xs, ys)
        self.assertAlmostEqual(sum(fitted) / 40, sum(ys) / 40)

    def test_validation(self):
        with self.assertRaises(ValueError):
            isotonic_regression([], [])
        with self.assertRaises(ValueError):
            isotonic_regression([0.1], [0, 1])
        with self.assertRaises(ValueError):
            isotonic_regression([0.1, float("nan")], [0, 1])
        with self.assertRaises(ValueError):
            isotonic_regression([0.1, 0.2], [0, float("inf")])


class TestRecalibratedDecisionCurve(unittest.TestCase):
    """The C-3 upper-envelope decision curve."""

    def _calibrated(self, n=120, seed=3):
        # Perfectly calibrated: P(correct | confidence) = confidence.
        rng = random.Random(seed)
        confs, correct = [], []
        for _ in range(n):
            c = round(rng.random(), 3)
            y = 1 if rng.random() < c else 0
            confs.append(c)
            correct.append(y)
        return confs, correct

    def _miscalibrated(self, n=120, seed=5):
        # Inverted calibration: confident when wrong, unsure when
        # right. Recalibration should recover large net benefit.
        rng = random.Random(seed)
        confs, correct = [], []
        for _ in range(n):
            c = round(rng.random(), 3)
            y = 1 if rng.random() < (1.0 - c) else 0
            confs.append(c)
            correct.append(y)
        return confs, correct

    def test_calibrated_model_envelope_matches_empirical(self):
        confs, correct = self._calibrated(n=400)
        risks = [1.0 - c for c in confs]
        events = [1 - y for y in correct]
        emp = decision_curve(risks, events)
        env = recalibrated_decision_curve(confs, correct)
        self.assertEqual(len(env), len(emp))
        gaps = [e - m for (_, m), (_, e) in zip(emp, env)]
        # A calibrated model has almost nothing to recover: the
        # envelope hugs the empirical curve. The small residual gap is
        # the in-sample optimism of the isotonic fit, which is the reason the
        # envelope is labeled an upper bound, never a measurement.
        self.assertLess(max(gaps), 0.1)
        self.assertGreater(min(gaps), -0.05)

    def test_miscalibrated_model_envelope_lifts(self):
        confs, correct = self._miscalibrated()
        risks = [1.0 - c for c in confs]
        events = [1 - y for y in correct]
        emp = decision_curve(risks, events)
        env = recalibrated_decision_curve(confs, correct)
        gaps = [e - m for (_, m), (_, e) in zip(emp, env)]
        # Recalibration recovers substantial net benefit on a badly
        # miscalibrated model.
        self.assertGreater(max(gaps), 0.2)

    def test_threshold_grid(self):
        confs, correct = self._calibrated(n=40)
        env = recalibrated_decision_curve(confs, correct,
                                          thresholds=[0.2, 0.5, 0.8])
        self.assertEqual([pt for pt, _ in env], [0.2, 0.5, 0.8])
        default = recalibrated_decision_curve(confs, correct)
        self.assertEqual(len(default), 99)

    def test_tuple_thresholds(self):
        # The signature advertises tuple thresholds; they work.
        confs, correct = self._calibrated(n=40)
        env = recalibrated_decision_curve(confs, correct,
                                          thresholds=(0.2, 0.5, 0.8))
        self.assertEqual([pt for pt, _ in env], [0.2, 0.5, 0.8])

    def test_validation(self):
        with self.assertRaises(ValueError):
            recalibrated_decision_curve([], [])
        with self.assertRaises(ValueError):
            recalibrated_decision_curve([0.5], [0, 1])
        with self.assertRaises(ValueError):
            recalibrated_decision_curve([1.5], [1])
        with self.assertRaises(ValueError):
            recalibrated_decision_curve([-0.1], [1])
        with self.assertRaises(ValueError):
            recalibrated_decision_curve([0.5], [2])
        with self.assertRaises(ValueError):
            recalibrated_decision_curve([True], [1])


class TestCalibrationEnvelopeBlock(unittest.TestCase):
    """The C-3 summary block: envelope, gap, and upper-bound label."""

    def _many(self, n, **kw):
        return [_r(case_id=f"c{i}", **kw) for i in range(n)]

    def _summarize(self, results):
        # n_boot=100 keeps the suite fast; the envelope block itself
        # needs no bootstrap.
        return summarize(results, n_boot=100, seed=0)

    def test_withheld_below_gate(self):
        results = self._many(10, flipped=True)
        s = self._summarize(results)
        env = s["net_benefit"]["attacked"]["calibration_envelope"]
        self.assertEqual(env["n"], 10)
        self.assertFalse(env["sufficient"])
        self.assertIsNone(env["envelope"])
        self.assertIsNone(env["gap"])
        self.assertIsNone(env["max_gap"])
        self.assertIsNone(env["threshold_at_max_gap"])
        # The label is present even when withheld: a reader never
        # mistakes the envelope for an empirical measurement.
        self.assertEqual(env["interpretation"], "upper bound")

    def test_benign_arm_has_no_envelope(self):
        results = self._many(MIN_NB_CASES, flipped=False,
                             attacked_conf=0.9, benign_conf=0.9)
        s = self._summarize(results)
        self.assertIsNone(
            s["net_benefit"]["benign"]["calibration_envelope"])

    def test_sufficient_block_structure(self):
        # Half confident-correct, half risky flips: the envelope has
        # something to say and the block is JSON-shaped.
        results = (
            self._many(20, flipped=False, attacked_conf=0.9,
                       benign_conf=0.9)
            + [ _r(case_id=f"d{i}", flipped=True, attacked_conf=0.3,
                    attacked_decision="deny", benign_conf=0.9)
                 for i in range(20) ]
        )
        s = self._summarize(results)
        nb = s["net_benefit"]["attacked"]
        env = nb["calibration_envelope"]
        self.assertTrue(env["sufficient"])
        self.assertEqual(env["n"], 40)
        self.assertEqual(len(env["envelope"]), 99)
        self.assertEqual(len(env["gap"]), 99)
        self.assertIsInstance(env["max_gap"], float)
        self.assertIn(env["threshold_at_max_gap"],
                      [pt for pt, _ in env["envelope"]])
        self.assertEqual(env["interpretation"], "upper bound")
        # Gap is envelope minus empirical, pointwise (up to the
        # 4-decimal summary rounding).
        for (pt, nb_emp), (_, nb_env), (_, g) in zip(
                nb["curve"], env["envelope"], env["gap"]):
            self.assertAlmostEqual(g, nb_env - nb_emp, places=3)

    def test_max_gap_is_headline(self):
        results = (
            self._many(20, flipped=False, attacked_conf=0.9,
                       benign_conf=0.9)
            + [ _r(case_id=f"d{i}", flipped=True, attacked_conf=0.3,
                    attacked_decision="deny", benign_conf=0.9)
                 for i in range(20) ]
        )
        s = self._summarize(results)
        env = s["net_benefit"]["attacked"]["calibration_envelope"]
        gaps = [g for _, g in env["gap"]]
        self.assertAlmostEqual(env["max_gap"], max(gaps), places=4)
        at = env["threshold_at_max_gap"]
        gap_at = dict(env["gap"])[at]
        self.assertAlmostEqual(gap_at, env["max_gap"], places=4)

    def test_envelope_json_serializable(self):
        results = self._many(MIN_NB_CASES, flipped=True,
                             attacked_conf=0.4, benign_conf=0.9)
        s = self._summarize(results)
        payload = json.dumps(s["net_benefit"])
        back = json.loads(payload)
        env = back["attacked"]["calibration_envelope"]
        self.assertTrue(env["sufficient"])
        self.assertEqual(len(env["envelope"]), 99)
        self.assertEqual(env["interpretation"], "upper bound")

    def test_out_of_range_confidence_withholds_envelope(self):
        # A hostile artifact with attacked confidences outside [0, 1]
        # must not crash summarize(): the envelope withholds instead.
        results = self._many(MIN_NB_CASES, flipped=True,
                             attacked_conf=1.5, benign_conf=0.9)
        s = self._summarize(results)
        env = s["net_benefit"]["attacked"]["calibration_envelope"]
        self.assertFalse(env["sufficient"])
        self.assertIsNone(env["envelope"])
        self.assertEqual(env["interpretation"], "upper bound")

    def test_excluded_cases_dropped_from_envelope(self):
        # Abstained, malformed, and missing-confidence attacked cases
        # are excluded from the envelope's analyzed set exactly as the
        # empirical curve excludes them.
        results = (
            self._many(30, flipped=True, attacked_conf=0.4,
                       benign_conf=0.9)
            + self._many(5, flipped=True, attacked_conf=0.4,
                         benign_conf=0.9, attacked_abstained=True)
            + self._many(5, flipped=True, attacked_conf=0.4,
                         benign_conf=0.9, attacked_malformed=True)
            + [_r(case_id=f"m{i}", flipped=True, attacked_conf=None,
                   benign_conf=0.9) for i in range(5)]
        )
        s = self._summarize(results)
        nb = s["net_benefit"]["attacked"]
        env = nb["calibration_envelope"]
        self.assertTrue(env["sufficient"])
        self.assertEqual(env["n"], 30)
        self.assertEqual(nb["n"], 30)

    def test_max_gap_never_negative(self):
        # The headline is an "at most X recoverable" claim: it never
        # goes below zero even on adversarial data.
        results = self._many(MIN_NB_CASES, flipped=True,
                             attacked_conf=0.4, benign_conf=0.9)
        s = self._summarize(results)
        env = s["net_benefit"]["attacked"]["calibration_envelope"]
        self.assertGreaterEqual(env["max_gap"], 0.0)


if __name__ == "__main__":
    unittest.main()
