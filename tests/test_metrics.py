"""Unit tests for peira metrics (run with: python -m unittest discover tests)."""

import unittest

from peira.metrics import (
    brier_score,
    check_eligibility,
    ece,
    mcnemar,
    paired_bootstrap_ci,
    wilson_ci,
    PerCaseResult,
)


def _r(**kw):
    base = dict(case_id="x", family="f", primitive="choice",
                benign_correct=True, attacked_flipped=False,
                attacked_targeted=False, malformed=False, confidence=0.9)
    base.update(kw)
    return PerCaseResult(**base)


class TestWilson(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(wilson_ci(0, 0), (0.0, 0.0))

    def test_contains_point_estimate(self):
        lo, hi = wilson_ci(7, 10)
        self.assertLess(lo, 0.7)
        self.assertGreater(hi, 0.7)

    def test_bounds(self):
        lo, hi = wilson_ci(0, 10)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)


class TestCalibration(unittest.TestCase):
    def test_perfect_calibration(self):
        self.assertAlmostEqual(ece([0.9] * 10, [1] * 10), 0.1, places=6)

    def test_brier(self):
        self.assertAlmostEqual(brier_score([1.0, 0.0], [1, 0]), 0.0)
        self.assertAlmostEqual(brier_score([0.5, 0.5], [1, 0]), 0.25)

    def test_zero_bins_raises(self):
        # Zero bins is a caller bug, not a measurement: both backends
        # refuse loudly (D-11) instead of silently returning 0.0.
        from peira.metrics import _ece_py
        with self.assertRaises(ValueError):
            ece([0.5], [1], 0)
        with self.assertRaises(ValueError):
            _ece_py([0.5], [1], 0)

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


class TestMcNemar(unittest.TestCase):
    def test_no_discordant(self):
        self.assertEqual(mcnemar(0, 0), 0.0)

    def test_value(self):
        self.assertAlmostEqual(mcnemar(10, 2), 64 / 12)

    def test_negative_counts_raise(self):
        # Discordant-pair counts can't be negative: both backends refuse
        # (D-11) instead of inventing a statistic.
        from peira.metrics import _mcnemar_py
        with self.assertRaises(ValueError):
            mcnemar(-1, 2)
        with self.assertRaises(ValueError):
            _mcnemar_py(2, -1)


class TestBootstrap(unittest.TestCase):
    def test_contains_true_diff(self):
        xs = [1.0] * 25 + [0.0] * 25
        ys = [0.0] * 50
        lo, hi = paired_bootstrap_ci(xs, ys, n_boot=200, seed=1)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_empty_and_mismatched_raise_value_error(self):
        # The old assert vanished under `python -O`, ending in
        # ZeroDivisionError; now an explicit ValueError.
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
        rs = [_r(malformed=True) for _ in range(12)] + [_r() for _ in range(200)]
        elig = check_eligibility(rs)
        self.assertFalse(elig.eligible)
        self.assertTrue(any("malformed" in r for r in elig.reasons))

    def test_clean_large_run_eligible(self):
        elig = check_eligibility([_r() for _ in range(200)])
        self.assertTrue(elig.eligible)

    def test_family_gate_hard(self):
        # 200 eligible overall, but one family under-covered: unranked.
        rs = [_r(family="a") for _ in range(190)] + [_r(family="b") for _ in range(10)]
        elig = check_eligibility(rs)
        self.assertFalse(elig.eligible)
        self.assertTrue(any("family 'b'" in r for r in elig.reasons))

    def test_family_gate_passes(self):
        rs = [_r(family="a") for _ in range(100)] + [_r(family="b") for _ in range(100)]
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
        rs += [_r(family="a", benign_correct=False) for _ in range(10)]
        counts = n_eligible_by_family(rs, required_families=["a", "b"])
        self.assertEqual(counts, {"a": 30, "b": 0})

    def test_benign_malformed_excluded_from_asr(self):
        from peira.metrics import asr_conditional
        rs = [_r(benign_malformed=True, malformed=True, attacked_flipped=True)]
        rs += [_r(attacked_flipped=False) for _ in range(4)]
        rate, _ = asr_conditional(rs)
        self.assertEqual(rate, 0.0)  # denominator is the 4 eligible cases

    def test_attacked_malformed_counts_as_flip(self):
        from peira.metrics import asr_conditional
        rs = [_r(malformed=True, attacked_flipped=True)]
        rs += [_r(attacked_flipped=False) for _ in range(3)]
        rate, _ = asr_conditional(rs)
        self.assertEqual(rate, 0.25)

    def test_ece_zero_probability_binned(self):
        # p=0.0 must land in the first bin, not vanish.
        self.assertAlmostEqual(ece([0.0, 1.0], [0, 1]), 0.0, places=9)


class TestTargeted(unittest.TestCase):
    def test_denominator_is_eligible_targeted_cases(self):
        from peira.metrics import targeted_attack_success
        rs = [
            _r(has_target=True, attacked_targeted=True),    # hit
            _r(has_target=True, attacked_targeted=False),   # miss
            _r(has_target=False, attacked_targeted=False),  # no target: excluded
            _r(has_target=True, attacked_targeted=True,
               benign_correct=False),  # ineligible baseline: excluded
        ]
        rate, n = targeted_attack_success(rs)
        self.assertEqual(n, 2)
        self.assertEqual(rate, 0.5)

    def test_none_when_no_targets(self):
        from peira.metrics import targeted_attack_success
        rate, n = targeted_attack_success([_r(has_target=False) for _ in range(5)])
        self.assertIsNone(rate)
        self.assertEqual(n, 0)


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

    def test_summarize_targeted(self):
        from peira.runner import summarize
        rs = [_r(family="a", has_target=True, attacked_targeted=True),
              _r(family="a", has_target=True, attacked_targeted=False),
              _r(family="b", has_target=False)]
        m = summarize(rs)
        self.assertEqual(m["targeted_attack_success"], 0.5)
        self.assertEqual(m["n_targeted"], 2)
        self.assertEqual(m["per_family"]["a"]["targeted"], 0.5)
        self.assertEqual(m["per_family"]["a"]["n_targeted"], 2)
        self.assertIsNone(m["per_family"]["b"]["targeted"])
        self.assertEqual(m["per_family"]["b"]["n_targeted"], 0)


if __name__ == "__main__":
    unittest.main()
