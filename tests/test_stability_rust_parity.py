"""Rust-parity tests for the stability numeric core (rust-max slice 5).

Each test compares the dispatched public function against its
pure-Python ``_xxx_py`` reference twin with assertAlmostEqual(places=12).
The twins are the PEIRA_NO_RUST=1 fallback, so this file proves the Rust
core agrees with the fallback path on real-shaped data.
"""

import random
import unittest

from peira._rust import _impl as _rust
from peira.metrics import CallRecord, PerCaseResult
from peira.stability import (
    _drift_watch_py,
    _flip_agreement_py,
    drift_watch,
    flip_agreement,
)


def _rec(decision="approve"):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def _r(case_id, family="f", flipped=False, eligible=True):
    attacked = "deny" if flipped else "approve"
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec("approve"),
        attacked=_rec(attacked),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "benign_abstained",
    )


def _runs(flip_matrix, families=None, eligible=True):
    """Build per-seed result lists from a flip matrix.

    flip_matrix[seed][case] -> bool flipped. families optional list
    parallel to cases.
    """
    out = []
    for flips in flip_matrix:
        run = []
        for i, f in enumerate(flips):
            fam = families[i] if families else "f"
            run.append(_r(f"c{i}", family=fam, flipped=f,
                          eligible=eligible))
        out.append(run)
    return out


def _assert_stability_equal(tc, got, want):
    tc.assertEqual(got.k, want.k)
    tc.assertEqual(got.n_cases, want.n_cases)
    tc.assertEqual(got.n_cases_total, want.n_cases_total)
    tc.assertEqual(len(got.per_seed_asr), len(want.per_seed_asr))
    for g, w in zip(got.per_seed_asr, want.per_seed_asr):
        tc.assertAlmostEqual(g, w, places=12)
    tc.assertAlmostEqual(got.pooled_asr, want.pooled_asr, places=12)
    tc.assertAlmostEqual(got.pass_k, want.pass_k, places=12)
    tc.assertEqual(got.n_agree, want.n_agree)
    tc.assertEqual(set(got.per_case_flip_rate), set(want.per_case_flip_rate))
    for cid in want.per_case_flip_rate:
        tc.assertAlmostEqual(
            got.per_case_flip_rate[cid], want.per_case_flip_rate[cid],
            places=12,
        )
    tc.assertAlmostEqual(got.wilson_ci[0], want.wilson_ci[0], places=12)
    tc.assertAlmostEqual(got.wilson_ci[1], want.wilson_ci[1], places=12)
    tc.assertAlmostEqual(got.run_sd, want.run_sd, places=12)
    tc.assertAlmostEqual(got.item_variance, want.item_variance, places=12)
    tc.assertEqual(got.n_churn, want.n_churn)
    tc.assertEqual(got.seeds, want.seeds)
    tc.assertEqual(got.excluded_seeds, want.excluded_seeds)


def _assert_drift_equal(tc, got, want):
    tc.assertEqual(got.old_run_id, want.old_run_id)
    tc.assertEqual(got.new_run_id, want.new_run_id)
    tc.assertEqual(len(got.families), len(want.families))
    for g, w in zip(got.families, want.families):
        tc.assertEqual(g.family, w.family)
        tc.assertEqual(g.n_paired, w.n_paired)
        tc.assertAlmostEqual(g.asr_old, w.asr_old, places=12)
        tc.assertAlmostEqual(g.asr_new, w.asr_new, places=12)
        tc.assertAlmostEqual(g.delta, w.delta, places=12)
        tc.assertEqual(g.n_newly_flipping, w.n_newly_flipping)
        tc.assertEqual(g.n_newly_fixed, w.n_newly_fixed)
        if w.mcnemar_p is None:
            tc.assertIsNone(g.mcnemar_p)
        else:
            tc.assertAlmostEqual(g.mcnemar_p, w.mcnemar_p, places=12)
        tc.assertEqual(g.degraded, w.degraded)
    tc.assertEqual(got.newly_flipping, want.newly_flipping)
    tc.assertEqual(got.newly_fixed, want.newly_fixed)


class TestFlipAgreementParity(unittest.TestCase):
    def test_perfect_agreement(self):
        runs = _runs([[True, False, True]] * 3)
        _assert_stability_equal(
            self, flip_agreement(runs), _flip_agreement_py(runs))

    def test_churn(self):
        runs = _runs([
            [True, False, True, False],
            [False, False, True, True],
            [True, True, False, False],
        ])
        _assert_stability_equal(
            self, flip_agreement(runs), _flip_agreement_py(runs))

    def test_ineligible_cases(self):
        runs = _runs([[True, True, False], [True, False, False]])
        runs[0][1] = _r("c1", flipped=True, eligible=False)
        runs[1][2] = _r("c2", flipped=False, eligible=False)
        _assert_stability_equal(
            self, flip_agreement(runs), _flip_agreement_py(runs))

    def test_no_eligible_cases(self):
        runs = _runs([[True], [False]], eligible=False)
        _assert_stability_equal(
            self, flip_agreement(runs), _flip_agreement_py(runs))

    def test_misaligned_rejected_both(self):
        runs = _runs([[True, False]] * 2)
        runs[1] = [_r("c0", flipped=True), _r("cX", flipped=False)]
        with self.assertRaises(ValueError):
            flip_agreement(runs)
        with self.assertRaises(ValueError):
            _flip_agreement_py(runs)

    def test_single_run_rejected_both(self):
        runs = _runs([[True]])
        with self.assertRaises(ValueError):
            flip_agreement(runs)
        with self.assertRaises(ValueError):
            _flip_agreement_py(runs)

    def test_randomized_corpus(self):
        rng = random.Random(20261002)
        families = [f"fam{i % 5}" for i in range(40)]
        matrix = [
            [rng.random() < 0.3 for _ in range(40)]
            for _ in range(5)
        ]
        runs = _runs(matrix, families=families)
        # Sprinkle ineligibility: case eligible in some seeds only.
        for s in range(5):
            for i in range(0, 40, 7):
                if (s + i) % 3 == 0:
                    runs[s][i] = _r(
                        f"c{i}", family=families[i],
                        flipped=matrix[s][i], eligible=False)
        _assert_stability_equal(
            self, flip_agreement(runs), _flip_agreement_py(runs))


class TestDriftWatchParity(unittest.TestCase):
    def _pair(self, old_flips, new_flips, families=None, n=12):
        fams = families or ["f"] * n
        old = [_r(f"c{i}", family=fams[i], flipped=old_flips[i])
               for i in range(n)]
        new = [_r(f"c{i}", family=fams[i], flipped=new_flips[i])
               for i in range(n)]
        return old, new

    def test_no_drift(self):
        flips = [i % 3 == 0 for i in range(12)]
        old, new = self._pair(flips, list(flips))
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )

    def test_withheld_p_small_discordant(self):
        old, new = self._pair(
            [False] * 12,
            [True, True, False, False, True] + [False] * 7,
        )
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )

    def test_mid_p_region_degraded(self):
        # 30 pairs, 15 newly flipping, 0 fixed: mid-p, significant.
        old, new = self._pair(
            [False] * 30, [i < 15 for i in range(30)], n=30)
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )

    def test_asymptotic_region(self):
        # 40 pairs, 30 newly flipping, 5 fixed: 35 discordant.
        old, new = self._pair(
            [i >= 35 for i in range(40)],
            [i < 30 or i >= 35 for i in range(40)],
            n=40,
        )
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )

    def test_per_family_split(self):
        fams = ["a"] * 12 + ["b"] * 12
        old, new = self._pair(
            [False] * 24,
            [i < 4 for i in range(24)],
            families=fams, n=24,
        )
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )

    def test_family_change_unpairs(self):
        old = [_r("c0", family="f1", flipped=True)]
        new = [_r("c0", family="f2", flipped=True)]
        _assert_drift_equal(
            self,
            drift_watch(old, new),
            _drift_watch_py(old, new),
        )

    def test_unpaired_and_ineligible_ignored(self):
        old = [
            _r("c0", flipped=True),
            _r("c1", flipped=False, eligible=False),
            _r("c2", flipped=True),
        ]
        new = [
            _r("c0", flipped=False),
            _r("c1", flipped=True, eligible=False),
            _r("c3", flipped=True),
        ]
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )

    def test_randomized_corpus(self):
        rng = random.Random(777)
        n = 60
        fams = [f"fam{i % 4}" for i in range(n)]
        old = [
            _r(f"c{i}", family=fams[i], flipped=rng.random() < 0.4,
               eligible=rng.random() > 0.1)
            for i in range(n)
        ]
        new = [
            _r(f"c{i}", family=fams[i], flipped=rng.random() < 0.45,
               eligible=rng.random() > 0.1)
            for i in range(n)
        ]
        _assert_drift_equal(
            self,
            drift_watch(old, new, "r1", "r2"),
            _drift_watch_py(old, new, "r1", "r2"),
        )


class BackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        # Records which backend the parity suite exercised; the suite
        # must run in both modes (Rust-active and PEIRA_NO_RUST=1).
        # Also verifies the validation gate: clean data passes, dirty
        # data (lone-surrogate string) raises ValueError on the
        # dispatched entry points in both modes.
        from peira.metrics import _require_result_strings

        print(f"\n[parity] rust backend active: {_rust is not None}")
        runs = _runs([[True, False], [False, True]])
        for results in runs:
            for r in results:
                _require_result_strings(r)  # must not raise

        dirty = _runs([[True], [True]])
        bad = dirty[0][0]
        dirty[0][0] = PerCaseResult(
            case_id="c\ud800",
            family=bad.family,
            severity=bad.severity,
            primitive=bad.primitive,
            benign=bad.benign,
            attacked=bad.attacked,
            flipped=bad.flipped,
            eligible=bad.eligible,
            ineligibility_reason=bad.ineligibility_reason,
        )
        with self.assertRaises(ValueError):
            flip_agreement(dirty)
        with self.assertRaises(ValueError):
            drift_watch(dirty[0], dirty[1])


if __name__ == "__main__":
    unittest.main()
