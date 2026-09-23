"""Unit tests for peira metrics (run with: python -m unittest discover tests)."""

import unittest

from peira.metrics import (
    INELIGIBLE_BENIGN_ABSTAINED,
    INELIGIBLE_BENIGN_MALFORMED,
    INELIGIBLE_BENIGN_WRONG_DECISION,
    CallRecord,
    PerCaseResult,
    asr_conditional,
    benign_accuracy,
    brier_score,
    check_eligibility,
    ece,
    ineligible_by_reason,
    mcnemar,
    paired_bootstrap_ci,
    refusal_rate,
    refusal_rate_by_family,
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
        # p=0.0 must land in the first bin, not vanish.
        self.assertAlmostEqual(ece([0.0, 1.0], [0, 1]), 0.0, places=9)

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
        for fn in (ece, _ece_py, brier_score, _brier_score_py):
            with self.subTest(fn=fn.__name__, kind="empty"):
                with self.assertRaises(ValueError):
                    fn([], [])
            with self.subTest(fn=fn.__name__, kind="mismatched"):
                with self.assertRaises(ValueError):
                    fn([0.5, 0.5], [1])

    def test_brier_perfect(self):
        self.assertAlmostEqual(
            brier_score([1.0, 0.0], [1, 0]), 0.0, places=9)


class TestMcNemar(unittest.TestCase):
    def test_value(self):
        self.assertAlmostEqual(mcnemar(8, 2), 3.6, places=9)

    def test_no_discordant(self):
        self.assertEqual(mcnemar(0, 0), 0.0)


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


if __name__ == "__main__":
    unittest.main()
