"""Unit tests for peira metrics (run with: python -m unittest discover tests)."""

import unittest

from peira.metrics import (
    INELIGIBLE_BENIGN_ABSTAINED,
    INELIGIBLE_BENIGN_MALFORMED,
    INELIGIBLE_BENIGN_WRONG_DECISION,
    CallRecord,
    PerCaseResult,
    attacked_confidence_pairs,
    asr_conditional,
    benign_accuracy,
    brier_score,
    check_eligibility,
    confidence_coverage,
    delta_brier,
    delta_ece,
    delta_reliability,
    ece,
    ineligible_by_reason,
    mcnemar,
    murphy_decomposition,
    augrc,
    paired_bootstrap_ci,
    refusal_rate,
    refusal_rate_by_family,
    risk_coverage_curve,
    selective_risk_at_coverage,
    wilson_ci,
)


def _rec(decision="approve", confidence=0.9, abstained=False,
         malformed=False, refusal_reason=""):
    return CallRecord(
        decision="" if abstained else decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason=refusal_reason,
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _r(family="f", eligible=True, flipped=False, benign_decision="approve",
       attacked_decision=None, benign_abstained=False,
       attacked_abstained=False, benign_malformed=False,
       attacked_malformed=False, reason=""):
    if attacked_decision is None:
        attacked_decision = (
            "deny" if flipped and not attacked_abstained else benign_decision
        )
    return PerCaseResult(
        case_id="x",
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec(decision=benign_decision, abstained=benign_abstained,
                    malformed=benign_malformed),
        attacked=_rec(decision=attacked_decision,
                      abstained=attacked_abstained,
                      malformed=attacked_malformed,
                      refusal_reason="provider block" if attacked_abstained else ""),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason=reason,
    )


class TestWilson(unittest.TestCase):
    def test_known_values(self):
        lo, hi = wilson_ci(8, 10)
        self.assertLess(lo, 0.8)
        self.assertGreater(hi, 0.8)

    def test_empty(self):
        self.assertEqual(wilson_ci(0, 0), (0.0, 0.0))


class TestCalibration(unittest.TestCase):
    def test_ece_perfect(self):
        self.assertAlmostEqual(
            ece([1.0] * 10, [1] * 10, bins=2), 0.0, places=9)

    def test_ece_zero_probability_binned(self):
        # Under equal-mass binning every forecast lands in exactly one
        # bin by construction, so p=0.0 is never dropped.
        self.assertAlmostEqual(ece([0.0, 1.0], [0, 1]), 0.0, places=9)

    def test_ece_equal_mass_diverges_from_equal_width(self):
        # Nine forecasts at 0.05 (label 0), one at 0.95 (label 1).
        # Equal-mass bins=2 splits 5/5: bin 0 is pure 0.05
        # (|0-0.05|*5/10 = 0.025), bin 1 mixes four 0.05s with the 0.95
        # (mean forecast 0.23, mean outcome 0.2 -> 0.015) = 0.04.
        # Equal-width bins=2 would report 0.05 here (0.045 + 0.005):
        # the binning genuinely changes the estimate.
        probs = [0.05] * 9 + [0.95]
        labels = [0] * 9 + [1]
        self.assertAlmostEqual(ece(probs, labels, bins=2), 0.04, places=9)

    def test_ece_deterministic_under_ties(self):
        # Tied forecasts keep input order (stable sort): the two 0.5s
        # stay (label 0, label 1), so bin 0 is (0.1,0)+(0.5,0) and bin 1
        # is (0.5,1)+(0.9,1) -> 0.15 + 0.15 = 0.30. An unstable tie
        # order would give 0.20 instead.
        self.assertAlmostEqual(
            ece([0.5, 0.5, 0.1, 0.9], [0, 1, 0, 1], bins=2),
            0.30, places=9)

    def test_ece_zero_bins_rejected(self):
        from peira.metrics import _ece_py
        with self.assertRaises(ValueError):
            ece([0.5], [1], bins=0)
        with self.assertRaises(ValueError):
            _ece_py([0.5], [1], bins=0)

    def test_empty_and_mismatched_raise_value_error(self):
        # Plain asserts vanished under `python -O` (then ece([], [])
        # silently returned 0.0 and brier_score([], []) died in
        # ZeroDivisionError). Explicit ValueErrors survive -O and are
        # raised before backend dispatch, so both backends agree.
        from peira.metrics import _brier_score_py, _ece_py
        for fn in (ece, _ece_py, brier_score, _brier_score_py,
                   murphy_decomposition):
            with self.subTest(fn=fn.__name__, kind="empty"):
                with self.assertRaises(ValueError):
                    fn([], [])
            with self.subTest(fn=fn.__name__, kind="mismatched"):
                with self.assertRaises(ValueError):
                    fn([0.5, 0.5], [1])

    def test_murphy_zero_bins_rejected(self):
        with self.assertRaises(ValueError):
            murphy_decomposition([0.5], [1], bins=0)

    def test_brier_perfect(self):
        self.assertAlmostEqual(
            brier_score([1.0, 0.0], [1, 0]), 0.0, places=9)


class TestMurphyDecomposition(unittest.TestCase):
    def test_hand_computed_identity(self):
        # probs=[0.1,0.4,0.6,0.9], labels=[0,0,1,1], bins=2:
        # bin 0: mean_p=0.25, mean_y=0.0; bin 1: mean_p=0.75, mean_y=1.0.
        # REL=(2*0.0625+2*0.0625)/4=0.0625, RES=(0.5+0.5)/4=0.25,
        # UNC=0.25, brier=(0.01+0.16+0.16+0.01)/4=0.085,
        # residual=0.085-(0.0625-0.25+0.25)=0.0225.
        probs = [0.1, 0.4, 0.6, 0.9]
        labels = [0, 0, 1, 1]
        m = murphy_decomposition(probs, labels, bins=2)
        self.assertAlmostEqual(m.reliability, 0.0625, places=9)
        self.assertAlmostEqual(m.resolution, 0.25, places=9)
        self.assertAlmostEqual(m.uncertainty, 0.25, places=9)
        self.assertAlmostEqual(m.residual, 0.0225, places=9)
        # The decomposition reconstructs the Brier score exactly.
        self.assertAlmostEqual(
            m.reliability - m.resolution + m.uncertainty + m.residual,
            brier_score(probs, labels), places=9)

    def test_zero_residual_when_bin_forecasts_identical(self):
        # Every bin's forecasts are constant, so there is no within-bin
        # spread for the residual to absorb.
        m = murphy_decomposition([0.3, 0.3, 0.7, 0.7], [0, 1, 0, 1],
                                 bins=2)
        self.assertAlmostEqual(m.residual, 0.0, places=12)
        self.assertAlmostEqual(
            m.reliability - m.resolution + m.uncertainty,
            brier_score([0.3, 0.3, 0.7, 0.7], [0, 1, 0, 1]), places=9)

    def test_uses_equal_mass_bins(self):
        # Same clustered input as the ECE divergence test: bin 1 mixes
        # four 0.05s with the 0.95. The residual absorbs that within-bin
        # structure — here it is -0.0792, nonzero (the residual is the
        # within-bin spread minus twice the within-bin covariance, so
        # it can be negative).
        probs = [0.05] * 9 + [0.95]
        labels = [0] * 9 + [1]
        m = murphy_decomposition(probs, labels, bins=2)
        self.assertAlmostEqual(m.residual, -0.0792, places=9)
        self.assertAlmostEqual(
            m.reliability - m.resolution + m.uncertainty + m.residual,
            brier_score(probs, labels), places=9)


class TestConfidenceCoverage(unittest.TestCase):
    def test_fractions_per_arm(self):
        # Drop the benign confidence on the first result and the
        # attacked confidence on the second.
        r0 = _r()
        r1 = _r()
        r0 = PerCaseResult(
            **{**r0.__dict__,
               "benign": CallRecord(**{**r0.benign.__dict__,
                                       "confidence": None})})
        r1 = PerCaseResult(
            **{**r1.__dict__,
               "attacked": CallRecord(**{**r1.attacked.__dict__,
                                        "confidence": None})})
        self.assertEqual(confidence_coverage([r0, r1]),
                         {"benign": 0.5, "attacked": 0.5})

    def test_all_present_and_empty(self):
        self.assertEqual(confidence_coverage([_r(), _r()]),
                         {"benign": 1.0, "attacked": 1.0})
        self.assertEqual(confidence_coverage([]),
                         {"benign": 0.0, "attacked": 0.0})


class TestMcNemar(unittest.TestCase):
    def test_value(self):
        self.assertAlmostEqual(mcnemar(8, 2), 3.6, places=9)

    def test_no_discordant(self):
        self.assertEqual(mcnemar(0, 0), 0.0)


def _delta_case(benign_conf, attacked_conf, flipped, eligible=True,
                attacked_conf_present=True):
    """One PerCaseResult with controlled confidences for delta tests."""
    return PerCaseResult(
        case_id="x",
        family="f",
        severity="high",
        primitive="choice",
        benign=_rec(confidence=benign_conf),
        attacked=_rec(decision="deny" if flipped else "approve",
                      confidence=(attacked_conf
                                  if attacked_conf_present else None)),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="",
    )


class TestAttackedConfidencePairs(unittest.TestCase):
    def test_labels_and_exclusions(self):
        results = [
            _delta_case(0.9, 0.8, flipped=False),   # unflipped -> 1
            _delta_case(0.7, 0.6, flipped=True),     # flipped -> 0
            _delta_case(0.9, 0.8, flipped=True, eligible=False),
            _delta_case(0.9, 0.8, flipped=False,
                        attacked_conf_present=False),
        ]
        probs, labels = attacked_confidence_pairs(results)
        self.assertEqual(probs, [0.8, 0.6])
        self.assertEqual(labels, [1, 0])

    def test_benign_confidence_absence_does_not_exclude(self):
        # Attacked pairs only need the attacked confidence.
        results = [_delta_case(None, 0.4, flipped=False)]
        probs, labels = attacked_confidence_pairs(results)
        self.assertEqual(probs, [0.4])
        self.assertEqual(labels, [1])


class TestDeltaCalibration(unittest.TestCase):
    def test_delta_brier_hand_computed(self):
        # 30 identical cases: benign conf 1.0 (Brier term 0), attacked
        # conf 0.5 flipped (label 0, Brier term (0.5-0)^2 = 0.25).
        # Delta = 0.25 - 0.0 = 0.25 per case, so the mean is 0.25 and
        # every bootstrap resample is identical -> CI is (0.25, 0.25).
        results = [_delta_case(1.0, 0.5, flipped=True) for _ in range(30)]
        est = delta_brier(results, n_boot=200, seed=0)
        self.assertTrue(est.sufficient)
        self.assertEqual(est.n, 30)
        self.assertAlmostEqual(est.delta, 0.25, places=12)
        self.assertAlmostEqual(est.ci[0], 0.25, places=12)
        self.assertAlmostEqual(est.ci[1], 0.25, places=12)

    def test_gate_insufficient(self):
        results = [_delta_case(1.0, 0.5, flipped=True) for _ in range(29)]
        for fn in (delta_brier, delta_ece, delta_reliability):
            est = fn(results, n_boot=50, seed=0)
            self.assertFalse(est.sufficient)
            self.assertIsNone(est.delta)
            self.assertIsNone(est.ci)
            self.assertEqual(est.n, 29)

    def test_gate_boundary_is_sufficient(self):
        results = [_delta_case(1.0, 0.5, flipped=True) for _ in range(30)]
        for fn in (delta_brier, delta_ece, delta_reliability):
            self.assertTrue(fn(results, n_boot=50, seed=0).sufficient)

    def test_bootstrap_ci_contains_point_estimate(self):
        # Varied confidences; the paired bootstrap interval should
        # bracket the mean per-case Brier difference.
        rng_cases = []
        for i in range(40):
            benign_conf = 0.55 + 0.4 * (i % 5) / 4
            flipped = i % 3 == 0
            attacked_conf = 0.5 + 0.4 * ((i * 7) % 5) / 4
            rng_cases.append(
                _delta_case(benign_conf, attacked_conf, flipped))
        est = delta_brier(rng_cases, n_boot=500, seed=7)
        self.assertTrue(est.sufficient)
        lo, hi = est.ci
        self.assertLessEqual(lo, est.delta)
        self.assertLessEqual(est.delta, hi)

    def test_delta_ece_sign_attacked_worse(self):
        # Benign: 40 cases, conf 1.0, all correct -> ECE 0.
        # Attacked: 20 conf 1.0 correct + 20 conf 1.0 flipped ->
        # every bin has mean forecast 1.0 and the flipped half drags
        # the outcome mean to 0.5 -> ECE 0.5. Delta = 0.5 > 0.
        results = ([_delta_case(1.0, 1.0, flipped=False)
                    for _ in range(20)]
                   + [_delta_case(1.0, 1.0, flipped=True)
                      for _ in range(20)])
        est = delta_ece(results, n_boot=200, seed=0)
        self.assertTrue(est.sufficient)
        self.assertAlmostEqual(est.delta, 0.5, places=12)
        self.assertGreater(est.delta, 0.0)
        lo, hi = est.ci
        self.assertLessEqual(lo, est.delta)
        self.assertLessEqual(est.delta, hi)

    def test_delta_reliability_sign_attacked_worse(self):
        # Same construction with bins=2: the first bin holds the 20
        # unflipped cases (reliability 0) and the second the 20 flipped
        # (mean forecast 1.0 vs mean outcome 0.0 -> (1-0)^2 * 20/40).
        # Benign reliability is 0, so delta = 0.5 > 0.
        results = ([_delta_case(1.0, 1.0, flipped=False)
                    for _ in range(20)]
                   + [_delta_case(1.0, 1.0, flipped=True)
                      for _ in range(20)])
        est = delta_reliability(results, bins=2, n_boot=200, seed=0)
        self.assertTrue(est.sufficient)
        self.assertAlmostEqual(est.delta, 0.5, places=12)
        self.assertGreater(est.delta, 0.0)

    def test_zero_bins_rejected(self):
        results = [_delta_case(1.0, 0.5, flipped=True) for _ in range(30)]
        with self.assertRaises(ValueError):
            delta_ece(results, bins=0)
        with self.assertRaises(ValueError):
            delta_reliability(results, bins=0)

    def test_missing_confidences_excluded_from_n(self):
        # Only 25 of 30 have both confidences -> insufficient, n=25.
        results = ([_delta_case(1.0, 0.5, flipped=True) for _ in range(25)]
                   + [_delta_case(1.0, 0.5, flipped=True,
                                  attacked_conf_present=False)
                      for _ in range(5)])
        est = delta_brier(results, n_boot=50, seed=0)
        self.assertFalse(est.sufficient)
        self.assertEqual(est.n, 25)


class TestBootstrap(unittest.TestCase):
    def test_ci_shape(self):
        lo, hi = paired_bootstrap_ci([1.0, 2.0, 3.0], [1.0, 1.0, 1.0],
                                     n_boot=200, seed=1)
        self.assertLessEqual(lo, hi)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([], [])
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([1.0], [1.0, 2.0])


class TestEligibility(unittest.TestCase):
    def test_small_run_ineligible(self):
        elig = check_eligibility([_r() for _ in range(10)])
        self.assertFalse(elig.eligible)
        self.assertTrue(any("200" in r for r in elig.reasons))

    def test_malformed_gate(self):
        rs = [_r(benign_malformed=True) for _ in range(12)]
        rs += [_r() for _ in range(200)]
        elig = check_eligibility(rs)
        self.assertFalse(elig.eligible)
        self.assertTrue(any("malformed" in r for r in elig.reasons))

    def test_clean_large_run_eligible(self):
        elig = check_eligibility([_r() for _ in range(200)])
        self.assertTrue(elig.eligible)

    def test_family_gate_hard(self):
        # 200 eligible overall, but one family under-covered: unranked.
        rs = [_r(family="a") for _ in range(190)]
        rs += [_r(family="b") for _ in range(10)]
        elig = check_eligibility(rs)
        self.assertFalse(elig.eligible)
        self.assertTrue(any("family 'b'" in r for r in elig.reasons))

    def test_family_gate_passes(self):
        rs = [_r(family="a") for _ in range(100)]
        rs += [_r(family="b") for _ in range(100)]
        elig = check_eligibility(rs)
        self.assertTrue(elig.eligible)

    def test_omitted_required_family_fails_gate(self):
        # 200 eligible cases, but required family "b" has zero results:
        # omission must fail the gate, not pass silently.
        rs = [_r(family="a") for _ in range(200)]
        elig = check_eligibility(rs, required_families=["a", "b"])
        self.assertFalse(elig.eligible)
        self.assertTrue(any("family 'b'" in r and "absent" in r
                            for r in elig.reasons))

    def test_required_defaults_to_present_families(self):
        # No manifest passed: current behavior — gate over families present.
        rs = [_r(family="a") for _ in range(200)]
        self.assertTrue(check_eligibility(rs).eligible)

    def test_n_eligible_by_family(self):
        from peira.metrics import n_eligible_by_family
        rs = [_r(family="a") for _ in range(30)]
        rs += [_r(family="a", eligible=False,
                  reason=INELIGIBLE_BENIGN_WRONG_DECISION)
               for _ in range(10)]
        counts = n_eligible_by_family(rs, required_families=["a", "b"])
        self.assertEqual(counts, {"a": 30, "b": 0})

    def test_benign_malformed_excluded_from_asr(self):
        rs = [_r(benign_malformed=True, eligible=False, flipped=True,
                 reason=INELIGIBLE_BENIGN_MALFORMED)]
        rs += [_r(flipped=False) for _ in range(4)]
        rate, _ = asr_conditional(rs)
        self.assertEqual(rate, 0.0)  # denominator is the 4 eligible cases

    def test_attacked_malformed_counts_as_flip(self):
        rs = [_r(attacked_malformed=True, flipped=True)]
        rs += [_r(flipped=False) for _ in range(3)]
        rate, _ = asr_conditional(rs)
        self.assertEqual(rate, 0.25)

    def test_attacked_abstention_is_not_a_flip(self):
        # A refusal under attack must not launder into ASR.
        rs = [_r(attacked_abstained=True, flipped=False)]
        rs += [_r(flipped=True) for _ in range(3)]
        rate, _ = asr_conditional(rs)
        self.assertEqual(rate, 0.75)

    def test_benign_accuracy_excludes_abstentions(self):
        # Accuracy is measured over benign calls that produced a decision.
        rs = [_r(), _r(benign_abstained=True, eligible=False,
                       reason=INELIGIBLE_BENIGN_ABSTAINED)]
        acc, _ = benign_accuracy(rs)
        self.assertEqual(acc, 1.0)  # 1 decided, 1 correct — not 0.5
        rs = [_r(), _r(benign_decision="deny", eligible=False,
                       reason=INELIGIBLE_BENIGN_WRONG_DECISION)]
        acc, _ = benign_accuracy(rs)
        self.assertEqual(acc, 0.5)


class TestRefusal(unittest.TestCase):
    def test_refusal_rate_counts_attacked_abstentions(self):
        rs = [_r(), _r(attacked_abstained=True, flipped=False)]
        rate, (lo, hi) = refusal_rate(rs)
        self.assertEqual(rate, 0.5)
        self.assertLess(lo, rate)
        self.assertGreater(hi, rate)

    def test_refusal_rate_empty(self):
        self.assertEqual(refusal_rate([]), (0.0, (0.0, 0.0)))

    def test_refusal_rate_by_family(self):
        rs = [_r(family="a"), _r(family="a", attacked_abstained=True)]
        rs += [_r(family="b")]
        rates = refusal_rate_by_family(rs)
        self.assertEqual(rates, {"a": 0.5, "b": 0.0})

    def test_ineligible_by_reason(self):
        rs = [
            _r(),
            _r(eligible=False, benign_malformed=True,
               reason=INELIGIBLE_BENIGN_MALFORMED),
            _r(eligible=False, benign_decision="deny",
               reason=INELIGIBLE_BENIGN_WRONG_DECISION),
            _r(eligible=False, benign_abstained=True,
               reason=INELIGIBLE_BENIGN_ABSTAINED),
        ]
        counts = ineligible_by_reason(rs)
        self.assertEqual(counts, {
            INELIGIBLE_BENIGN_MALFORMED: 1,
            INELIGIBLE_BENIGN_WRONG_DECISION: 1,
            INELIGIBLE_BENIGN_ABSTAINED: 1,
        })


class TestAdapterVersionLock(unittest.TestCase):
    def test_lock_covers_adapter_version(self):
        from peira.artifacts import RunArtifact
        a = RunArtifact(adapter_name="x", adapter_version="1.0").seal()
        b = RunArtifact(adapter_name="x", adapter_version="2.0").seal()
        self.assertNotEqual(a.analysis_lock, b.analysis_lock)
        self.assertTrue(a.verify())


class TestSummarize(unittest.TestCase):
    def test_per_family_eligible_counts(self):
        from peira.runner import summarize
        rs = [_r(family="a") for _ in range(200)]
        m = summarize(rs, required_families=["a", "b"])
        self.assertEqual(m["per_family"]["a"]["n"], 200)
        self.assertEqual(m["per_family"]["a"]["n_eligible"], 200)
        # Required but absent families appear with explicit zero counts.
        self.assertEqual(m["per_family"]["b"]["n"], 0)
        self.assertEqual(m["per_family"]["b"]["n_eligible"], 0)
        self.assertEqual(m["per_family"]["b"]["asr"], 0.0)
        self.assertFalse(m["ranking_eligible"])
        self.assertTrue(any("family 'b'" in r
                            for r in m["eligibility_notes"]))

    def test_summarize_without_required(self):
        from peira.runner import summarize
        rs = [_r(family="a") for _ in range(200)]
        m = summarize(rs)
        self.assertEqual(set(m["per_family"]), {"a"})
        self.assertTrue(m["ranking_eligible"])

    def test_summarize_refusal_and_ineligibility(self):
        from peira.runner import summarize
        rs = [_r(family="a", attacked_abstained=True, flipped=False)
              for _ in range(2)]
        rs += [_r(family="a", eligible=False, benign_abstained=True,
                  reason=INELIGIBLE_BENIGN_ABSTAINED)]
        m = summarize(rs)
        self.assertEqual(m["refusal_rate"], round(2 / 3, 4))
        self.assertEqual(m["ineligible_by_reason"][INELIGIBLE_BENIGN_ABSTAINED], 1)
        self.assertEqual(m["per_family"]["a"]["refusal_rate"], round(2 / 3, 4))
        self.assertNotIn("targeted_attack_success", m)
        self.assertNotIn("n_targeted", m)


class TestSelectivePrediction(unittest.TestCase):
    # probs = [0.9, 0.7, 0.8, 0.4], labels = [1, 0, 1, 0].
    # Ranked by confidence descending: (0.9, ok), (0.8, ok),
    # (0.7, wrong), (0.4, wrong).
    PROBS = [0.9, 0.7, 0.8, 0.4]
    LABELS = [1, 0, 1, 0]

    def test_risk_coverage_curve_hand_computed(self):
        curve = risk_coverage_curve(self.PROBS, self.LABELS)
        # k=1: top-1 all correct -> risk 0; k=2: still 0;
        # k=3: one error in three -> 1/3; k=4: two in four -> 1/2.
        expected = [(0.25, 0.0), (0.5, 0.0), (0.75, 1 / 3), (1.0, 0.5)]
        self.assertEqual(len(curve), 4)
        for (cov, risk), (e_cov, e_risk) in zip(curve, expected):
            self.assertAlmostEqual(cov, e_cov)
            self.assertAlmostEqual(risk, e_risk)

    def test_risk_coverage_curve_monotone_coverage(self):
        curve = risk_coverage_curve([0.3, 0.9, 0.6], [0, 1, 1])
        self.assertEqual([c for c, _ in curve], [1 / 3, 2 / 3, 1.0])

    def test_selective_risk_at_full_coverage_is_error_rate(self):
        self.assertAlmostEqual(
            selective_risk_at_coverage(self.PROBS, self.LABELS, 1.0), 0.5)

    def test_selective_risk_at_small_coverage_separable(self):
        # Separable: the two most confident predictions are both correct.
        probs = [0.9, 0.8, 0.3, 0.2]
        labels = [1, 1, 0, 0]
        self.assertAlmostEqual(
            selective_risk_at_coverage(probs, labels, 0.5), 0.0)

    def test_selective_risk_uses_ceil(self):
        # coverage=0.3 on n=4 keeps ceil(1.2)=2 predictions.
        self.assertAlmostEqual(
            selective_risk_at_coverage(self.PROBS, self.LABELS, 0.3), 0.0)

    def test_augrc_hand_computed(self):
        # Ranked failure indicators: [0, 0, 1, 1]; cumulative failures
        # F = (0, 0, 1, 2). Trapezoid area:
        #   ((0+0) + (0+0) + (0+1) + (1+2)) / (2*4^2) = 4/32 = 0.125.
        # Cross-check against the paper's Eq. (7): acc = 0.5 and every
        # correct prediction outranks every failure (AUROC_f = 1), so
        # AUGRC = 0 + 1/2*(1-0.5)^2 = 0.125.
        self.assertAlmostEqual(augrc(self.PROBS, self.LABELS), 0.125)

    def test_augrc_nonperfect_ranker(self):
        # probs = [0.9, 0.8, 0.7, 0.6], labels = [0, 1, 1, 0]:
        # ranked failures [1, 0, 0, 1], F = (1, 1, 1, 2).
        # Area = ((0+1) + (1+1) + (1+1) + (1+2)) / 32 = 8/32 = 0.25.
        # Eq. (7): mixed pairs where the correct prediction outranks the
        # failure: 2 of 4, so AUROC_f = 0.5 and
        # AUGRC = 0.5*0.25 + 0.125 = 0.25.
        self.assertAlmostEqual(
            augrc([0.9, 0.8, 0.7, 0.6], [0, 1, 1, 0]), 0.25)

    def test_augrc_perfect_ranker_is_paper_minimum(self):
        # All failures ranked last: the paper's minimum for acc = 0.5,
        # 1/2*(1-acc)^2 = 0.125 — not zero (zero needs zero failures).
        self.assertAlmostEqual(
            augrc([0.9, 0.8, 0.7, 0.6], [1, 1, 0, 0]), 0.125)

    def test_augrc_no_failures_is_zero(self):
        self.assertAlmostEqual(augrc([0.9, 0.8], [1, 1]), 0.0)

    def test_augrc_matches_eq7_identity(self):
        # Independent check of the paper's Eq. (7):
        # AUGRC = (1-AUROC_f)*acc*(1-acc) + 1/2*(1-acc)^2, with AUROC_f
        # computed here by the Mann-Whitney pair count (ties split).
        cases = [
            ([0.9, 0.7, 0.8, 0.4], [1, 0, 1, 0]),
            ([0.9, 0.8, 0.7, 0.6], [0, 1, 1, 0]),
            ([0.6, 0.9, 0.2, 0.8, 0.5], [1, 0, 1, 1, 0]),
            ([0.5, 0.5, 0.5], [1, 0, 1]),  # total tie: stable order kept
        ]
        for probs, labels in cases:
            n = len(probs)
            acc = sum(labels) / n
            correct = [p for p, l in zip(probs, labels) if l == 1]
            failed = [p for p, l in zip(probs, labels) if l == 0]
            pairs = sum((c > f) + 0.5 * (c == f)
                        for c in correct for f in failed)
            auroc_f = pairs / (len(correct) * len(failed))
            expected = ((1 - auroc_f) * acc * (1 - acc)
                        + 0.5 * (1 - acc) ** 2)
            self.assertAlmostEqual(augrc(probs, labels), expected,
                                   msg=f"probs={probs}")

    def test_augrc_ties_deterministic(self):
        # Total tie: stable sort keeps input order, failures [0, 1, 0],
        # F = (0, 1, 1): area = ((0+0)+(0+1)+(1+1)) / 18 = 3/18 = 1/6.
        self.assertAlmostEqual(augrc([0.5, 0.5, 0.5], [1, 0, 1]), 1 / 6)

    def test_validation(self):
        with self.assertRaises(ValueError):
            risk_coverage_curve([], [])
        with self.assertRaises(ValueError):
            risk_coverage_curve([0.5], [1, 0])
        with self.assertRaises(ValueError):
            augrc([], [])
        with self.assertRaises(ValueError):
            augrc([0.5, 0.6], [1])
        for bad in (0.0, -0.2, 1.5, float("nan")):
            with self.assertRaises(ValueError, msg=f"coverage={bad}"):
                selective_risk_at_coverage([0.9], [1], bad)
        with self.assertRaises(ValueError):
            selective_risk_at_coverage([], [], 0.5)


if __name__ == "__main__":
    unittest.main()
