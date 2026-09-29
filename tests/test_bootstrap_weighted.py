"""Tests for C-2: paired-bootstrap inference for weighted metrics.

Covers ``paired_bootstrap_weighted_ci`` (the statistical primitive),
``weighted_delta`` / ``delta_severity_weighted_asr`` (the comparison
API), ``validate_no_weighted_mcnemar`` (the CI lint validator), and the
integration into ``compare_artifacts`` / ``comparison_to_dict``.
"""

import math
import random
import unittest

from peira.compare import (
    PairedCase,
    WEIGHTED_METRIC_NAMES,
    compare_artifacts,
    comparison_to_dict,
    delta_severity_weighted_asr,
    validate_no_weighted_mcnemar,
    weighted_delta,
)
from peira.metrics import (
    SEVERITY_WEIGHTS,
    CallRecord,
    PerCaseResult,
    paired_bootstrap_ci,
    paired_bootstrap_weighted_ci,
)


def _wmean(weights, values):
    return math.fsum(w * v for w, v in zip(weights, values)) / math.fsum(weights)


class TestPairedBootstrapWeightedCI(unittest.TestCase):
    def test_equal_weights_matches_unweighted(self):
        rng = random.Random(42)
        xs = [rng.gauss(0.5, 0.2) for _ in range(100)]
        ys = [rng.gauss(0.3, 0.2) for _ in range(100)]
        ones = [1.0] * 100
        lo_w, hi_w = paired_bootstrap_weighted_ci(ones, xs, ones, ys, seed=7)
        lo_u, hi_u = paired_bootstrap_ci(xs, ys, seed=7)
        # Same resample indices (same seed, same stream discipline) and
        # weights of 1 make the weighted mean the plain mean.
        self.assertAlmostEqual(lo_w, lo_u, places=12)
        self.assertAlmostEqual(hi_w, hi_u, places=12)

    def test_ci_covers_known_weighted_difference(self):
        # True weighted-mean difference is exactly 0.2 by construction.
        rng = random.Random(1234)
        n = 400
        weights = [rng.choice([1.0, 2.0, 3.0]) for _ in range(n)]
        base = [rng.gauss(0.0, 1.0) for _ in range(n)]
        xs = [b + 0.2 for b in base]
        ys = list(base)
        point = _wmean(weights, xs) - _wmean(weights, ys)
        self.assertAlmostEqual(point, 0.2, places=10)
        lo, hi = paired_bootstrap_weighted_ci(weights, xs, weights, ys, seed=99)
        self.assertLess(lo, 0.2)
        self.assertGreater(hi, 0.2)
        # And the interval is sensibly tight around the truth.
        self.assertLess(hi - lo, 0.5)

    def test_paired_structure_preserved(self):
        # Identical arms: every resample difference is exactly 0.
        xs = [0.5] * 50
        ys = [0.5] * 50
        w = [2.0] * 50
        lo, hi = paired_bootstrap_weighted_ci(w, xs, w, ys, seed=1)
        self.assertEqual((lo, hi), (0.0, 0.0))

    def test_deterministic_seed(self):
        rng = random.Random(5)
        xs = [rng.random() for _ in range(60)]
        ys = [rng.random() for _ in range(60)]
        w = [1.0, 2.0, 3.0] * 20
        r1 = paired_bootstrap_weighted_ci(w, xs, w, ys, seed=11)
        r2 = paired_bootstrap_weighted_ci(w, xs, w, ys, seed=11)
        self.assertEqual(r1, r2)
        r3 = paired_bootstrap_weighted_ci(w, xs, w, ys, seed=12)
        self.assertNotEqual(r1, r3)

    def test_asymmetric_weights(self):
        # Different weight vectors per arm are allowed (e.g. different
        # severity mixes); the point estimate must follow the weights.
        xs = [1.0, 0.0]
        ys = [0.0, 0.0]
        w_xs = [3.0, 1.0]  # weighted mean of xs = 0.75
        w_ys = [1.0, 1.0]  # weighted mean of ys = 0.0
        lo, hi = paired_bootstrap_weighted_ci(
            w_xs, xs, w_ys, ys, n_boot=2000, seed=3)
        self.assertLess(lo, 0.75)
        self.assertGreater(hi, 0.75)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci([], [], [], [])

    def test_rejects_mismatched(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci([1.0], [1.0], [1.0, 2.0], [1.0, 2.0])
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci([1.0, 2.0], [1.0], [1.0, 2.0], [1.0, 2.0])

    def test_rejects_nonfinite(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci(
                [1.0, float("nan")], [1.0, 2.0], [1.0, 1.0], [1.0, 1.0])
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci(
                [1.0, 1.0], [1.0, float("inf")], [1.0, 1.0], [1.0, 1.0])
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci(
                [1.0, float("inf")], [1.0, 2.0], [1.0, 1.0], [1.0, 1.0])

    def test_rejects_negative_weights(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci(
                [1.0, -1.0], [1.0, 2.0], [1.0, 1.0], [1.0, 1.0])

    def test_rejects_all_zero_weights(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci(
                [0.0, 0.0], [1.0, 2.0], [1.0, 1.0], [1.0, 1.0])

    def test_sparse_but_supported_weights_redraw(self):
        # One positive weight: every non-degenerate resample is pinned
        # to the same weighted mean, so the interval is exactly the
        # point estimate. Resamples that draw only the zero-weight case
        # are discarded and redrawn; never returned as a degenerate
        # result. Fully deterministic: the valid resample set admits a
        # single value.
        xs = [1.0, 999.0]
        ys = [0.0, 0.0]
        w = [1.0, 0.0]
        lo, hi = paired_bootstrap_weighted_ci(w, xs, w, ys,
                                             n_boot=100, seed=0)
        self.assertEqual((lo, hi), (1.0, 1.0))

    def test_sparse_weights_have_defined_behavior(self):
        # One positive weight among 49 zeros: every non-degenerate
        # resample is pinned to the same weighted mean, so the interval
        # is exactly the point estimate. Resamples that draw only
        # zero-weight indices are discarded and redrawn; the result is
        # a defined (zero-width) interval, never silent garbage and
        # never a mid-loop failure. Deterministic for any seed: the
        # valid resample set admits a single value.
        n = 50
        w = [3.0] + [0.0] * (n - 1)
        xs = [1.0] * n
        ys = [0.0] * n
        lo, hi = paired_bootstrap_weighted_ci(w, xs, w, ys,
                                             n_boot=200, seed=0)
        self.assertEqual((lo, hi), (1.0, 1.0))

    def test_rejects_bad_n_boot(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_weighted_ci(
                [1.0], [1.0], [1.0], [1.0], n_boot=0)


def _call_record():
    return CallRecord(
        decision="approve",
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def _per_case_result(case_id, severity, flipped, eligible=True):
    return PerCaseResult(
        case_id=case_id,
        family="fam",
        severity=severity,
        primitive="choice",
        benign=_call_record(),
        attacked=_call_record(),
        flipped=flipped,
        eligible=eligible,
    )


def _pairs(specs):
    """specs: list of (severity, a_flipped, b_flipped)."""
    pairs = []
    for i, (sev, af, bf) in enumerate(specs):
        pairs.append(PairedCase(
            case_id=f"c{i}",
            family="fam",
            primitive="choice",
            a=_per_case_result(f"c{i}", sev, af),
            b=_per_case_result(f"c{i}", sev, bf),
        ))
    return pairs


class TestWeightedDelta(unittest.TestCase):
    def test_withheld_below_gate(self):
        n = 29
        d = weighted_delta(
            "severity_weighted_asr",
            [1.0] * n, [1.0] * n, [1.0] * n, [0.0] * n,
            lower_is_better=True, seed=0,
        )
        self.assertFalse(d.sufficient)
        self.assertIsNone(d.delta)
        self.assertIsNone(d.ci95)
        self.assertIsNone(d.favors)
        self.assertEqual(d.n, n)

    def test_mismatched_lengths_raise_instead_of_withholding(self):
        # Validation runs before the minimum-sample gate: a length
        # mismatch is a caller bug, not an insufficient-data withhold.
        # (zip would silently truncate and compute over the wrong pairs.)
        with self.assertRaises(ValueError):
            weighted_delta("m", [1.0, 1.0], [1.0, 1.0],
                           [1.0], [1.0, 1.0],
                           lower_is_better=True, seed=0)

    def test_nonfinite_values_raise_before_computation(self):
        # NaN must be rejected before the point estimate is computed,
        # not left to detonate inside the bootstrap.
        n = 30
        xs = [1.0] * n
        xs[0] = float("nan")
        with self.assertRaises(ValueError):
            weighted_delta("m", [1.0] * n, xs, [1.0] * n, [0.0] * n,
                           lower_is_better=True, seed=0)

    def test_favors_when_ci_excludes_zero(self):
        n = 100
        # A flips everything, B flips nothing: delta = 1.0, CI far from 0.
        d = weighted_delta(
            "severity_weighted_asr",
            [1.0] * n, [1.0] * n, [1.0] * n, [0.0] * n,
            lower_is_better=True, seed=0,
        )
        self.assertTrue(d.sufficient)
        self.assertAlmostEqual(d.delta, 1.0)
        self.assertGreater(d.ci95[0], 0.0)
        # Lower is better and A is worse (higher ASR): favors B.
        self.assertEqual(d.favors, "b")

    def test_no_favors_when_ci_covers_zero(self):
        rng = random.Random(77)
        n = 100
        xs = [1.0 if rng.random() < 0.5 else 0.0 for _ in range(n)]
        ys = [1.0 if rng.random() < 0.5 else 0.0 for _ in range(n)]
        d = weighted_delta(
            "severity_weighted_asr",
            [1.0] * n, xs, [1.0] * n, ys,
            lower_is_better=True, seed=0,
        )
        self.assertTrue(d.sufficient)
        self.assertLessEqual(d.ci95[0], 0.0)
        self.assertGreaterEqual(d.ci95[1], 0.0)
        self.assertIsNone(d.favors)


class TestDeltaSeverityWeightedASR(unittest.TestCase):
    def test_point_estimate_matches_manual(self):
        # 40 critical (w=3), 40 high (w=2), 40 medium (w=1).
        # A flips all critical; B flips all medium.
        specs = ([("critical", True, False)] * 40
                 + [("high", False, False)] * 40
                 + [("medium", False, True)] * 40)
        pairs = _pairs(specs)
        d = delta_severity_weighted_asr(pairs, seed=0)
        self.assertTrue(d.sufficient)
        self.assertEqual(d.name, "severity_weighted_asr")
        # A: (40*3)/(40*3+40*2+40*1) = 120/240 = 0.5
        # B: (40*1)/240 = 40/240
        expected = 0.5 - 40.0 / 240.0
        self.assertAlmostEqual(d.delta, expected, places=10)
        # CI must contain the point estimate.
        self.assertLessEqual(d.ci95[0], d.delta)
        self.assertGreaterEqual(d.ci95[1], d.delta)

    def test_uses_frozen_severity_weights(self):
        # A single-severity slice: weighted ASR equals the flip rate, so
        # the delta must equal the plain flip-rate difference.
        specs = [("high", True, False)] * 50 + [("high", False, False)] * 50
        pairs = _pairs(specs)
        d = delta_severity_weighted_asr(pairs, seed=0)
        self.assertAlmostEqual(d.delta, 0.5, places=10)

    def test_doubly_eligible_only(self):
        # Ineligible cases contribute no weight to either arm. The
        # ineligible pairs are built directly with eligible=False
        # instead of mutating shared fixtures in place.
        pairs = []
        for i in range(40):
            pairs.append(PairedCase(
                case_id=f"c{i}",
                family="fam",
                primitive="choice",
                a=_per_case_result(f"c{i}", "critical", True,
                                   eligible=(i >= 10)),
                b=_per_case_result(f"c{i}", "critical", False),
            ))
        d = delta_severity_weighted_asr(pairs, seed=0)
        # 30 doubly-eligible pairs remain: at the gate, sufficient.
        self.assertTrue(d.sufficient)
        self.assertEqual(d.n, 30)

    def test_unknown_severity_raises(self):
        pairs = _pairs([("bogus", True, False)] * 40)
        with self.assertRaises(ValueError):
            delta_severity_weighted_asr(pairs)

    def test_withheld_below_gate(self):
        pairs = _pairs([("high", True, False)] * 20)
        d = delta_severity_weighted_asr(pairs)
        self.assertFalse(d.sufficient)
        self.assertIsNone(d.delta)

    def test_no_doubly_eligible_pairs_withholds(self):
        # Zero doubly-eligible pairs: no pair carries a flip signal
        # for both adapters, so the delta is withheld (sufficient=False,
        # n=0) instead of raising on the empty filtered lists.
        pairs = []
        for i in range(30):
            pairs.append(PairedCase(
                case_id=f"c{i}",
                family="fam",
                primitive="choice",
                a=_per_case_result(f"c{i}", "critical", True,
                                   eligible=False),
                b=_per_case_result(f"c{i}", "critical", False),
            ))
        d = delta_severity_weighted_asr(pairs)
        self.assertEqual(d.name, "severity_weighted_asr")
        self.assertFalse(d.sufficient)
        self.assertIsNone(d.delta)
        self.assertIsNone(d.ci95)
        self.assertIsNone(d.favors)
        self.assertEqual(d.n, 0)


class TestValidateNoWeightedMcNemar(unittest.TestCase):
    def test_clean_report_passes(self):
        report = {
            "mcnemar": {"b": 12, "c": 4, "p_value": 0.03, "winner": "a"},
            "weighted_deltas": [
                {"name": "severity_weighted_asr", "delta": 0.07,
                 "ci95": [0.01, 0.13], "n": 200}
            ],
        }
        self.assertEqual(validate_no_weighted_mcnemar(report), [])

    def test_top_level_mcnemar_never_violation(self):
        # The headline McNemar block is unweighted by construction.
        report = {"mcnemar": {"p_value": 0.001}}
        self.assertEqual(validate_no_weighted_mcnemar(report), [])

    def test_catches_mcnemar_p_value_key(self):
        bad = {"d": {"name": "severity_weighted_asr",
                     "mcnemar_p_value": 0.03}}
        violations = validate_no_weighted_mcnemar(bad)
        self.assertEqual(len(violations), 1)
        self.assertIn("severity_weighted_asr", violations[0])

    def test_catches_all_p_value_spellings(self):
        for key in ("mcnemar_p_value", "mcnemar_p", "p_value"):
            bad = {"x": [{"name": "severity_weighted_asr", key: 0.01}]}
            self.assertTrue(validate_no_weighted_mcnemar(bad), key)

    def test_catches_weighted_substring_names(self):
        bad = {"x": {"name": "my_weighted_metric", "p_value": 0.04}}
        self.assertTrue(validate_no_weighted_mcnemar(bad))

    def test_catches_nested_violations(self):
        bad = {"a": {"b": {"c": [{"name": "cost_weighted_asr",
                                  "mcnemar_p": 0.02}]}}}
        self.assertTrue(validate_no_weighted_mcnemar(bad))

    def test_none_p_value_not_violation(self):
        # A withheld (None) p-value key is not a claim.
        ok = {"x": {"name": "severity_weighted_asr", "p_value": None}}
        self.assertEqual(validate_no_weighted_mcnemar(ok), [])

    def test_unweighted_metric_with_p_value_ok(self):
        ok = {"x": {"name": "asr", "p_value": 0.03}}
        self.assertEqual(validate_no_weighted_mcnemar(ok), [])

    def test_guarded_names_enforced(self):
        # Every name in WEIGHTED_METRIC_NAMES must actually drive the
        # validator: attaching a p-value to any guarded name is a
        # violation. (Checking bare set membership would pass without
        # exercising the enforcement path.)
        for name in WEIGHTED_METRIC_NAMES:
            bad = {"x": {"name": name, "p_value": 0.01}}
            violations = validate_no_weighted_mcnemar(bad)
            self.assertTrue(violations, name)
            self.assertIn(name, violations[0])

    def test_regression_nested_p_value_dict(self):
        # Red-team P1: {"name": "severity_weighted_asr",
        #               "stats": {"p_value": 0.01}} slipped past the
        # validator before the nested-dict bypass fix.
        bad = {"x": {"name": "severity_weighted_asr",
                     "stats": {"p_value": 0.01}}}
        violations = validate_no_weighted_mcnemar(bad)
        self.assertTrue(violations)
        self.assertIn("severity_weighted_asr", violations[0])

    def test_regression_metric_name_as_key(self):
        # Red-team P1: {"severity_weighted_asr": {"p_value": 0.01}}
        # slipped past the validator before the name-as-key bypass fix.
        bad = {"x": {"severity_weighted_asr": {"p_value": 0.01}}}
        violations = validate_no_weighted_mcnemar(bad)
        self.assertTrue(violations)
        self.assertIn("severity_weighted_asr", violations[0])


class TestComparisonIntegration(unittest.TestCase):
    def _artifact_dict(self, name, flip_every):
        from peira.artifacts import RunArtifact
        cases = []
        for i in range(40):
            cases.append({
                "case_id": f"c{i}",
                "family": "fam",
                "severity": "high",
                "primitive": "choice",
                "benign": {
                    "decision": "approve", "confidence": 0.9,
                    "abstained": False, "refusal_reason": "",
                    "seed": 0, "dispatch_index": 0,
                    "malformed": False, "dispatch_limit": 1,
                    "usage": None,
                },
                "attacked": {
                    "decision": "approve", "confidence": 0.9,
                    "abstained": False, "refusal_reason": "",
                    "seed": 0, "dispatch_index": 0,
                    "malformed": False, "dispatch_limit": 1,
                    "usage": None,
                },
                "flipped": (i % flip_every == 0),
                "eligible": True,
                "ineligibility_reason": "",
            })
        art = RunArtifact(
            adapter_name=name,
            adapter_version="1.0",
            suite="trial-demo",
            dataset_version="0.1.0-demo",
            manifest_sha256="abc123",
            results=cases,
            metrics={},
        )
        art.seal()
        return art

    def test_compare_artifacts_has_weighted_deltas(self):
        a = self._artifact_dict("A", flip_every=2)  # 50% flip
        b = self._artifact_dict("B", flip_every=4)  # 25% flip
        comp = compare_artifacts(a, b, seed=0)
        self.assertEqual(len(comp.weighted_deltas), 1)
        wd = comp.weighted_deltas[0]
        self.assertEqual(wd.name, "severity_weighted_asr")
        self.assertTrue(wd.sufficient)
        # All-high severity: weighted delta == plain flip-rate delta.
        self.assertAlmostEqual(wd.delta, 0.25, places=10)

    def test_comparison_dict_validates_clean(self):
        a = self._artifact_dict("A", flip_every=2)
        b = self._artifact_dict("B", flip_every=4)
        comp = compare_artifacts(a, b, seed=0)
        d = comparison_to_dict(comp)
        self.assertIn("weighted_deltas", d)
        self.assertEqual(len(d["weighted_deltas"]), 1)
        wd = d["weighted_deltas"][0]
        self.assertNotIn("p_value", wd)
        self.assertNotIn("mcnemar_p_value", wd)
        self.assertNotIn("mcnemar_p", wd)
        self.assertEqual(validate_no_weighted_mcnemar(d), [])


if __name__ == "__main__":
    unittest.main()
