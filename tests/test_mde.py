"""Tests for R-02 minimum detectable effects and C-8 directional MDEs.

Covers the MDE power formulas (verified against the eval-science deep
dive: n=400/pd=20% -> 6.3pp, n=200/pd=20% -> 8.9pp, 5pp at pd=20% needs
n~=630), the "not resolvable at this n" convention, the flip-direction
machinery, and the compare-view integration (per-family MDE rows and
directional MDE rows).
"""

import math
import unittest

from peira.metrics import (
    DIR_NONE,
    DIR_OTHER,
    DIR_SCORE_SHIFTED,
    DIR_TO_ABSTAIN,
    DIR_TO_MALFORMED,
    NOT_RESOLVABLE,
    CallRecord,
    PerCaseResult,
    directional_mde,
    flip_direction,
    is_direction_eligible,
    mde_from_se,
    mde_mcnemar,
    mde_paired_bootstrap,
    paired_bootstrap_ci,
    paired_bootstrap_se,
    resolvable,
)


def _rec(decision="approve", abstained=False, malformed=False, score=None):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=abstained,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
        score=score,
    )


def _result(benign_dec="approve", attacked_dec="deny", flipped=True,
            eligible=True, primitive="choice", attacked_abstained=False,
            attacked_malformed=False, benign_score=None, attacked_score=None):
    return PerCaseResult(
        case_id="c1",
        family="f",
        severity="medium",
        primitive=primitive,
        benign=_rec(decision=benign_dec, score=benign_score),
        attacked=_rec(
            decision=attacked_dec,
            abstained=attacked_abstained,
            malformed=attacked_malformed,
            score=attacked_score,
        ),
        flipped=flipped,
        eligible=eligible,
    )


class TestMdeFromSe(unittest.TestCase):
    def test_multiplier_at_defaults(self):
        # (z_0.975 + z_0.8) = 2.8016 at alpha=0.05, power=0.8.
        self.assertAlmostEqual(mde_from_se(1.0), 2.8016, places=4)

    def test_scales_linearly_with_se(self):
        self.assertAlmostEqual(mde_from_se(2.0), 2 * mde_from_se(1.0))

    def test_zero_se_gives_zero(self):
        self.assertEqual(mde_from_se(0.0), 0.0)

    def test_rejects_bad_inputs(self):
        for kwargs in (
            {"se": -0.1},
            {"se": 1.0, "alpha": 0.0},
            {"se": 1.0, "alpha": 1.0},
            {"se": 1.0, "power": 0.0},
            {"se": 1.0, "power": 1.0},
        ):
            with self.assertRaises(ValueError):
                mde_from_se(**kwargs)

    def test_higher_power_needs_bigger_effect(self):
        self.assertGreater(mde_from_se(1.0, power=0.9), mde_from_se(1.0, power=0.8))

    def test_lower_alpha_needs_bigger_effect(self):
        self.assertGreater(mde_from_se(1.0, alpha=0.01), mde_from_se(1.0, alpha=0.05))


class TestMdeMcNemar(unittest.TestCase):
    def test_research_n400(self):
        # Eval-science deep dive: n=400/pd=20% -> 6.3pp at 80% power.
        self.assertAlmostEqual(mde_mcnemar(400, 0.20), 0.063, places=3)

    def test_research_n200(self):
        # Eval-science deep dive: n=200/pd=20% -> 8.9pp at 80% power.
        self.assertAlmostEqual(mde_mcnemar(200, 0.20), 0.089, places=3)

    def test_research_n_for_5pp(self):
        # Resolving 5pp at pd=20% needs n ~= 630: the MDE at n=628
        # brackets 0.05 from both sides.
        self.assertLessEqual(mde_mcnemar(630, 0.20), 0.05)
        self.assertGreater(mde_mcnemar(620, 0.20), 0.05)

    def test_zero_discordant_rate_gives_zero(self):
        self.assertEqual(mde_mcnemar(400, 0.0), 0.0)

    def test_rejects_bad_inputs(self):
        for n, pd in ((0, 0.2), (-5, 0.2), (100, -0.1), (100, 1.1)):
            with self.assertRaises(ValueError):
                mde_mcnemar(n, pd)

    def test_v2_family_size_sanity(self):
        # v2 ships at 400/family: at a 20% discordant rate the family MDE
        # is 6.3pp, so sub-6pp leaderboard gaps are not resolvable there.
        self.assertAlmostEqual(mde_mcnemar(400, 0.20), 0.063, places=3)


class TestPairedBootstrapSe(unittest.TestCase):
    def test_matches_ci_stream(self):
        # Same draws as paired_bootstrap_ci: the SE of the bootstrap
        # distribution must be consistent with the percentile interval.
        xs = [float(i % 3) for i in range(60)]
        ys = [float((i + 1) % 3) for i in range(60)]
        se = paired_bootstrap_se(xs, ys, n_boot=2000, seed=7)
        lo, hi = paired_bootstrap_ci(xs, ys, n_boot=2000, seed=7)
        # For a roughly normal bootstrap distribution, the 95% interval
        # width is ~3.92 * SE.
        self.assertAlmostEqual((hi - lo) / (2 * 1.96), se, delta=0.02)

    def test_zero_when_no_variation(self):
        xs = [1.0] * 40
        ys = [1.0] * 40
        self.assertEqual(paired_bootstrap_se(xs, ys, n_boot=500, seed=0), 0.0)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_se([], [])
        with self.assertRaises(ValueError):
            paired_bootstrap_se([1.0], [1.0, 2.0])
        with self.assertRaises(ValueError):
            paired_bootstrap_se([float("nan")], [1.0])

    def test_seed_reproducible(self):
        xs = [float(i) for i in range(50)]
        ys = [float(i % 2) for i in range(50)]
        a = paired_bootstrap_se(xs, ys, n_boot=1000, seed=3)
        b = paired_bootstrap_se(xs, ys, n_boot=1000, seed=3)
        self.assertEqual(a, b)


class TestMdePairedBootstrap(unittest.TestCase):
    def test_agrees_with_closed_form_on_binary(self):
        # On unweighted binary paired data, the bootstrap MDE should be
        # close to the McNemar closed form (same estimand, SE estimated
        # by resampling instead of sqrt(pd/n)).
        import random
        rng = random.Random(11)
        n, pd = 400, 0.2
        xs, ys = [], []
        for _ in range(n):
            if rng.random() < pd:
                # Discordant: random split.
                if rng.random() < 0.6:
                    xs.append(1.0); ys.append(0.0)
                else:
                    xs.append(0.0); ys.append(1.0)
            else:
                v = 1.0 if rng.random() < 0.5 else 0.0
                xs.append(v); ys.append(v)
        boot = mde_paired_bootstrap(xs, ys, n_boot=5000, seed=5)
        closed = mde_mcnemar(n, pd)
        self.assertAlmostEqual(boot, closed, delta=0.02)

    def test_weights_change_the_mde(self):
        # C-8 scope note: severity weights change estimator variance, so
        # the weighted MDE differs from the headline MDE.
        xs = [1.0, 0.0, 1.0, 0.0] * 25
        ys = [0.0, 0.0, 0.0, 0.0] * 25
        plain = mde_paired_bootstrap(xs, ys, n_boot=2000, seed=1)
        # Weight the discordant cases up: variance rises, MDE rises.
        xw = [3.0 if x == 1.0 else 1.0 for x in xs]
        yw = [3.0 if y == 1.0 else 1.0 for y in ys]
        weighted = mde_paired_bootstrap(xw, yw, n_boot=2000, seed=1)
        self.assertNotAlmostEqual(plain, weighted, delta=1e-9)


class TestResolvable(unittest.TestCase):
    def test_at_and_above_mde_resolves(self):
        self.assertTrue(resolvable(0.063, 0.063))
        self.assertTrue(resolvable(0.10, 0.063))
        self.assertTrue(resolvable(-0.10, 0.063))

    def test_below_mde_does_not_resolve(self):
        self.assertFalse(resolvable(0.062, 0.063))
        self.assertFalse(resolvable(-0.01, 0.063))

    def test_none_is_never_resolvable(self):
        self.assertFalse(resolvable(None, 0.063))
        self.assertFalse(resolvable(0.10, None))
        self.assertFalse(resolvable(None, None))

    def test_convention_string(self):
        self.assertEqual(NOT_RESOLVABLE, "not resolvable at this n")


class TestFlipDirection(unittest.TestCase):
    def test_clean_transition(self):
        r = _result(benign_dec="approve", attacked_dec="deny", flipped=True)
        self.assertEqual(flip_direction(r), "approve-to-deny")

    def test_reverse_transition(self):
        r = _result(benign_dec="deny", attacked_dec="approve", flipped=True)
        self.assertEqual(flip_direction(r), "deny-to-approve")

    def test_not_flipped_is_none(self):
        r = _result(flipped=False)
        self.assertEqual(flip_direction(r), DIR_NONE)

    def test_to_abstain(self):
        r = _result(flipped=True, attacked_abstained=True)
        self.assertEqual(flip_direction(r), DIR_TO_ABSTAIN)

    def test_to_malformed(self):
        r = _result(flipped=True, attacked_malformed=True)
        self.assertEqual(flip_direction(r), DIR_TO_MALFORMED)

    def test_score_shifted_without_decision_flip(self):
        r = _result(
            flipped=False, primitive="score",
            benign_score=0.9, attacked_score=0.5,
        )
        self.assertEqual(flip_direction(r), DIR_SCORE_SHIFTED)

    def test_small_score_shift_is_none(self):
        r = _result(
            flipped=False, primitive="score",
            benign_score=0.9, attacked_score=0.85,
        )
        self.assertEqual(flip_direction(r), DIR_NONE)

    def test_unparseable_decisions_is_other(self):
        r = _result(benign_dec="", attacked_dec="", flipped=True)
        self.assertEqual(flip_direction(r), DIR_OTHER)

    def test_non_approve_deny_transition_is_other(self):
        # The six categories are never expanded with ad-hoc labels: a
        # flipped case outside approve/deny lands in "other", not a new
        # "{x}-to-{y}" bucket.
        r = _result(benign_dec="maybe", attacked_dec="yes", flipped=True)
        self.assertEqual(flip_direction(r), DIR_OTHER)

    def test_six_failure_categories_constant(self):
        from peira.metrics import FAILURE_DIRECTIONS
        self.assertEqual(
            set(FAILURE_DIRECTIONS),
            {
                "approve-to-deny", "deny-to-approve", "to-abstain",
                "to-malformed", "score-shifted", "other",
            },
        )


class TestIsDirectionEligible(unittest.TestCase):
    def test_ineligible_case_eligible_for_nothing(self):
        r = _result(eligible=False)
        for d in ("approve-to-deny", DIR_TO_ABSTAIN, DIR_SCORE_SHIFTED, DIR_OTHER):
            self.assertFalse(is_direction_eligible(r, d))

    def test_none_is_never_eligible(self):
        r = _result()
        self.assertFalse(is_direction_eligible(r, DIR_NONE))

    def test_transition_eligible_on_source_decision(self):
        r = _result(benign_dec="approve")
        self.assertTrue(is_direction_eligible(r, "approve-to-deny"))
        self.assertFalse(is_direction_eligible(r, "deny-to-approve"))
        r2 = _result(benign_dec="deny")
        self.assertTrue(is_direction_eligible(r2, "deny-to-approve"))
        self.assertFalse(is_direction_eligible(r2, "approve-to-deny"))

    def test_abstain_malformed_other_eligible_everywhere(self):
        r = _result(benign_dec="deny")
        for d in (DIR_TO_ABSTAIN, DIR_TO_MALFORMED, DIR_OTHER):
            self.assertTrue(is_direction_eligible(r, d))

    def test_score_shifted_only_on_score_primitive(self):
        r_score = _result(primitive="score")
        r_choice = _result(primitive="choice")
        self.assertTrue(is_direction_eligible(r_score, DIR_SCORE_SHIFTED))
        self.assertFalse(is_direction_eligible(r_choice, DIR_SCORE_SHIFTED))


class TestDirectionalMde(unittest.TestCase):
    def test_basic(self):
        dir_a = ["approve-to-deny", "none", "approve-to-deny", "to-abstain"]
        dir_b = ["none", "none", "approve-to-deny", "none"]
        eligible = [True, True, True, True]
        mde, n = directional_mde(
            dir_a, dir_b, "approve-to-deny", eligible, seed=0
        )
        self.assertEqual(n, 4)
        self.assertIsNotNone(mde)
        self.assertGreater(mde, 0.0)

    def test_no_eligible_cases_withholds(self):
        mde, n = directional_mde(
            ["none"], ["none"], "approve-to-deny", [False], seed=0
        )
        self.assertEqual((mde, n), (None, 0))

    def test_eligibility_masks_cases(self):
        # Varying data: A flips in the direction on half the cases.
        dir_a = (["approve-to-deny", "none"] * 5) + (["none"] * 0)
        dir_a = dir_a * 2  # 20 cases, 10 directional flips
        dir_b = ["none"] * 20
        full = directional_mde(
            dir_a, dir_b, "approve-to-deny", [True] * 20, seed=0
        )
        half = directional_mde(
            dir_a, dir_b, "approve-to-deny",
            [True] * 10 + [False] * 10, seed=0,
        )
        self.assertEqual(full[1], 20)
        self.assertEqual(half[1], 10)
        self.assertGreater(full[0], 0.0)
        self.assertGreater(half[0], 0.0)
        # Fewer eligible cases: larger MDE.
        self.assertGreater(half[0], full[0])

    def test_weights_change_mde(self):
        dir_a = ["approve-to-deny", "none"] * 20
        dir_b = ["none", "none"] * 20
        eligible = [True] * 40
        plain = directional_mde(
            dir_a, dir_b, "approve-to-deny", eligible, seed=0
        )[0]
        weighted = directional_mde(
            dir_a, dir_b, "approve-to-deny", eligible,
            weights=[2.0] * 40, seed=0,
        )[0]
        self.assertNotAlmostEqual(plain, weighted, delta=1e-9)

    def test_rejects_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            directional_mde(["a"], ["a", "b"], "a", [True, True])
        with self.assertRaises(ValueError):
            directional_mde(
                ["a"], ["a"], "a", [True], weights=[1.0, 2.0]
            )


class TestCompareIntegration(unittest.TestCase):
    def _paired(self, a_flipped, b_flipped, family="fam",
                a_dec=("approve", "deny"), b_dec=("approve", "approve")):
        from peira.compare import PairedCase
        return PairedCase(
            case_id="c1",
            family=family,
            primitive="choice",
            a=_result(
                benign_dec=a_dec[0], attacked_dec=a_dec[1],
                flipped=a_flipped,
            ),
            b=_result(
                benign_dec=b_dec[0], attacked_dec=b_dec[1],
                flipped=b_flipped,
            ),
        )

    def test_family_mdes_present(self):
        from peira.compare import _family_mdes, _head_to_head_py
        pairs = [self._paired(True, False) for _ in range(20)]
        pairs += [self._paired(False, False) for _ in range(20)]
        per_fam = {"fam": _head_to_head_py(pairs)}
        fms = _family_mdes(per_fam)
        self.assertEqual(len(fms), 1)
        fm = fms[0]
        self.assertEqual(fm.family, "fam")
        self.assertEqual(fm.n, 40)
        # 20 discordant of 40 -> rate 0.5.
        self.assertAlmostEqual(fm.discordant_rate, 0.5)
        self.assertAlmostEqual(fm.mde, mde_mcnemar(40, 0.5))

    def test_directional_mdes_present(self):
        from peira.compare import _directional_mdes
        pairs = [
            self._paired(True, False, a_dec=("approve", "deny"))
            for _ in range(10)
        ]
        pairs += [
            self._paired(False, False, b_dec=("approve", "approve"))
            for _ in range(10)
        ]
        rows = _directional_mdes(pairs, seed=0)
        by_dir = {r.direction: r for r in rows}
        self.assertIn("approve-to-deny", by_dir)
        row = by_dir["approve-to-deny"]
        # All 20 cases have benign "approve": eligible for approve-to-*.
        self.assertEqual(row.n_eligible, 20)
        self.assertIsNotNone(row.mde)
        # A flipped 10/20 in this direction, B 0/20: delta 0.5.
        self.assertAlmostEqual(row.delta, 0.5)
        self.assertTrue(row.resolvable)

    def test_small_directional_delta_not_resolvable(self):
        from peira.compare import _directional_mdes
        # A and B differ by a single directional flip in 40 cases.
        pairs = [
            self._paired(True, False, a_dec=("approve", "deny")),
        ]
        pairs += [self._paired(False, False) for _ in range(39)]
        rows = _directional_mdes(pairs, seed=0)
        by_dir = {r.direction: r for r in rows}
        row = by_dir["approve-to-deny"]
        self.assertAlmostEqual(row.delta, 1 / 40)
        self.assertFalse(row.resolvable)


if __name__ == "__main__":
    unittest.main()
