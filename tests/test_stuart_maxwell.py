"""Unit tests for C-1 Stuart-Maxwell directional comparison.

Run with: python -m unittest discover tests
"""

import math
import unittest

from peira.metrics import (
    DIRECTION_CATEGORIES,
    CallRecord,
    PerCaseResult,
    _chi2_sf_py,
    direction_square_table,
    flip_direction,
    stuart_maxwell,
    stuart_maxwell_p_value,
)


def _rec(decision="approve", confidence=0.9, abstained=False,
         malformed=False):
    return CallRecord(
        decision="" if abstained else decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _r(case_id="x", benign_decision="approve", attacked_decision="deny",
       benign_abstained=False, attacked_abstained=False,
       attacked_malformed=False, eligible=True, primitive="choice"):
    """Build a PerCaseResult with explicit benign/attacked outcomes."""
    return PerCaseResult(
        case_id=case_id,
        family="f",
        severity="high",
        primitive=primitive,
        benign=_rec(decision=benign_decision, abstained=benign_abstained),
        attacked=_rec(decision=attacked_decision,
                      abstained=attacked_abstained,
                      malformed=attacked_malformed),
        flipped=(
            benign_decision != attacked_decision
            or benign_abstained != attacked_abstained
            or attacked_malformed
        ),
        eligible=eligible,
    )


def _table_from_counts(counts):
    """Build a square table dict from a {(row, col): n} mapping."""
    table = {d: {e: 0 for e in DIRECTION_CATEGORIES}
             for d in DIRECTION_CATEGORIES}
    for (r, c), n in counts.items():
        table[r][c] = n
    return table


class TestDirectionCategories(unittest.TestCase):
    def test_six_categories_no_none(self):
        self.assertEqual(len(DIRECTION_CATEGORIES), 6)
        self.assertNotIn("none", DIRECTION_CATEGORIES)
        for d in ("approve-to-deny", "deny-to-approve", "to-abstain",
                  "to-malformed", "score-shifted", "other"):
            self.assertIn(d, DIRECTION_CATEGORIES)


class TestDirectionSquareTable(unittest.TestCase):
    def test_both_flipped_counts(self):
        # Adapter A: deny -> approve (fail open).
        # Adapter B: approve -> abstain (fail closed).
        ra = [_r("c1", benign_decision="deny", attacked_decision="approve"),
              _r("c2", benign_decision="deny", attacked_decision="approve")]
        rb = [_r("c1", benign_decision="approve", attacked_decision="approve",
                 attacked_abstained=True),
              _r("c2", benign_decision="deny", attacked_decision="approve")]
        # c1: A deny-to-approve, B to-abstain. c2: both deny-to-approve.
        table = direction_square_table(ra, rb)
        self.assertEqual(table["deny-to-approve"]["to-abstain"], 1)
        self.assertEqual(table["deny-to-approve"]["deny-to-approve"], 1)

    def test_single_sided_flip_excluded(self):
        # Only A flips; B holds. Excluded from the directional table.
        ra = [_r("c1", benign_decision="deny", attacked_decision="approve")]
        rb = [_r("c1", benign_decision="deny", attacked_decision="deny")]
        table = direction_square_table(ra, rb)
        total = sum(sum(row.values()) for row in table.values())
        self.assertEqual(total, 0)

    def test_neither_flipped_excluded(self):
        ra = [_r("c1", benign_decision="approve", attacked_decision="approve")]
        rb = [_r("c1", benign_decision="approve", attacked_decision="approve")]
        table = direction_square_table(ra, rb)
        total = sum(sum(row.values()) for row in table.values())
        self.assertEqual(total, 0)

    def test_ineligible_skipped(self):
        ra = [_r("c1", benign_decision="deny", attacked_decision="approve",
                 eligible=False)]
        rb = [_r("c1", benign_decision="deny", attacked_decision="approve",
                 eligible=False)]
        table = direction_square_table(ra, rb)
        total = sum(sum(row.values()) for row in table.values())
        self.assertEqual(total, 0)

    def test_mismatched_case_ids_raise(self):
        ra = [_r("c1")]
        rb = [_r("c2")]
        with self.assertRaises(ValueError):
            direction_square_table(ra, rb)

    def test_duplicate_case_ids_raise(self):
        ra = [_r("c1"), _r("c1")]
        rb = [_r("c1")]
        with self.assertRaises(ValueError):
            direction_square_table(ra, rb)
        rb2 = [_r("c1"), _r("c1")]
        with self.assertRaises(ValueError):
            direction_square_table([_r("c1")], rb2)

    def test_fixed_shape(self):
        ra = [_r("c1", benign_decision="deny", attacked_decision="approve")]
        rb = [_r("c1", benign_decision="deny", attacked_decision="approve")]
        table = direction_square_table(ra, rb)
        self.assertEqual(set(table.keys()), set(DIRECTION_CATEGORIES))
        for d in DIRECTION_CATEGORIES:
            self.assertEqual(set(table[d].keys()), set(DIRECTION_CATEGORIES))


class TestStuartMaxwellStat(unittest.TestCase):
    def test_reduces_to_mcnemar_for_2x2(self):
        # With only two live categories, Stuart-Maxwell == McNemar.
        # b = (A=dta, B=atd) = 8, c = (A=atd, B=dta) = 2.
        table = _table_from_counts({
            ("deny-to-approve", "approve-to-deny"): 8,
            ("approve-to-deny", "deny-to-approve"): 2,
            ("deny-to-approve", "deny-to-approve"): 5,
            ("approve-to-deny", "approve-to-deny"): 5,
        })
        stat, df = stuart_maxwell(table)
        expected = (8 - 2) ** 2 / (8 + 2)
        self.assertEqual(df, 1)
        self.assertAlmostEqual(stat, expected, places=9)

    def test_perfect_homogeneity_zero_stat(self):
        # Diagonal table: both adapters always agree on direction.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 10,
            ("to-abstain", "to-abstain"): 10,
        })
        stat, df = stuart_maxwell(table)
        self.assertAlmostEqual(stat, 0.0, places=9)

    def test_known_value_fixed_reference(self):
        # Fixed reference values, cross-validated against scipy 1.11.4
        # (scipy.stats.chi2.sf). scipy is not a peira dependency, so
        # the reference values are frozen here instead of imported.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 12,
            ("deny-to-approve", "to-abstain"): 8,
            ("deny-to-approve", "approve-to-deny"): 2,
            ("to-abstain", "deny-to-approve"): 3,
            ("to-abstain", "to-abstain"): 15,
            ("to-abstain", "approve-to-deny"): 1,
            ("approve-to-deny", "deny-to-approve"): 4,
            ("approve-to-deny", "to-abstain"): 2,
            ("approve-to-deny", "approve-to-deny"): 9,
        })
        stat, df = stuart_maxwell(table)
        self.assertEqual(df, 2)
        self.assertAlmostEqual(stat, 2.923076923077, places=9)
        # The p-value must match scipy's chi2.sf on the same inputs.
        p = stuart_maxwell_p_value(table)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, 0.231879262848, places=6)

    def test_rejects_directional_difference(self):
        # Adapter A fails open (deny-to-approve), B fails closed
        # (to-abstain): marginals differ strongly.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 2,
            ("deny-to-approve", "to-abstain"): 18,
            ("to-abstain", "deny-to-approve"): 1,
            ("to-abstain", "to-abstain"): 3,
        })
        p = stuart_maxwell_p_value(table)
        self.assertIsNotNone(p)
        self.assertLess(p, 0.01)

    def test_holds_when_marginals_match(self):
        # Same marginal direction distribution, different joint
        # arrangement: homogeneity holds. 12 discordant flips clears
        # the <10 floor.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 8,
            ("deny-to-approve", "to-abstain"): 6,
            ("to-abstain", "deny-to-approve"): 6,
            ("to-abstain", "to-abstain"): 8,
        })
        p = stuart_maxwell_p_value(table)
        self.assertIsNotNone(p)
        self.assertGreater(p, 0.05)

    def test_negative_counts_raise(self):
        table = _table_from_counts({("deny-to-approve", "deny-to-approve"): 5})
        table["deny-to-approve"]["to-abstain"] = -1
        with self.assertRaises(ValueError):
            stuart_maxwell(table)

    def test_non_square_raises(self):
        table = {"a": {"a": 1, "b": 2}}
        with self.assertRaises(ValueError):
            stuart_maxwell(table)

    def test_unknown_categories_raise(self):
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 10,
        })
        table["none"] = {d: 0 for d in DIRECTION_CATEGORIES}
        for d in DIRECTION_CATEGORIES:
            table[d]["none"] = 0
        with self.assertRaises(ValueError):
            stuart_maxwell(table)

    def test_single_live_category_returns_zero(self):
        # Fewer than two informative categories: nothing to test.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 10,
        })
        stat, df = stuart_maxwell(table)
        self.assertEqual(stat, 0.0)
        self.assertEqual(df, 0)

    def test_diagonal_only_category_ignored(self):
        # A category seen only on the diagonal carries no directional
        # information. It must not singularize the solve, and the
        # result must match the table without it.
        with_diag = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 10,
            ("deny-to-approve", "to-abstain"): 8,
            ("to-abstain", "deny-to-approve"): 2,
            ("to-abstain", "to-abstain"): 10,
            ("to-malformed", "to-malformed"): 7,
        })
        without_diag = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 10,
            ("deny-to-approve", "to-abstain"): 8,
            ("to-abstain", "deny-to-approve"): 2,
            ("to-abstain", "to-abstain"): 10,
        })
        stat_d, df_d = stuart_maxwell(with_diag)
        stat_w, df_w = stuart_maxwell(without_diag)
        self.assertEqual(df_d, df_w)
        self.assertAlmostEqual(stat_d, stat_w, places=9)
        # Reduces to McNemar on the informative pair.
        self.assertAlmostEqual(stat_d, (8 - 2) ** 2 / (8 + 2), places=9)

    def test_disconnected_components_sum(self):
        # Two off-diagonal pairs that never co-occur are independent
        # subproblems. The statistic and df sum across components.
        table = _table_from_counts({
            ("deny-to-approve", "to-abstain"): 8,
            ("to-abstain", "deny-to-approve"): 2,
            ("to-malformed", "score-shifted"): 6,
            ("score-shifted", "to-malformed"): 4,
        })
        stat, df = stuart_maxwell(table)
        self.assertEqual(df, 2)
        expected = (8 - 2) ** 2 / (8 + 2) + (6 - 4) ** 2 / (6 + 4)
        self.assertAlmostEqual(stat, expected, places=9)


class TestStuartMaxwellPValue(unittest.TestCase):
    def test_withheld_below_10(self):
        table = _table_from_counts({
            ("deny-to-approve", "to-abstain"): 5,
            ("to-abstain", "deny-to-approve"): 4,
        })
        self.assertIsNone(stuart_maxwell_p_value(table))

    def test_exactly_10_not_withheld(self):
        table = _table_from_counts({
            ("deny-to-approve", "to-abstain"): 6,
            ("to-abstain", "deny-to-approve"): 4,
        })
        p = stuart_maxwell_p_value(table)
        self.assertIsNotNone(p)

    def test_diagonal_mass_does_not_count_toward_floor(self):
        # 10 total paired flips but only 2 discordant: the floor is
        # on discordant flips (R-07's b + c), so this withholds.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 8,
            ("deny-to-approve", "to-abstain"): 1,
            ("to-abstain", "deny-to-approve"): 1,
        })
        self.assertIsNone(stuart_maxwell_p_value(table))

    def test_chi2_sf_fixed_references(self):
        # Frozen against scipy 1.11.4 (scipy.stats.chi2.sf). scipy is
        # not a peira dependency, so the references are hardcoded.
        refs = {
            (1, 0.5): 0.479500122187,
            (1, 3.84): 0.050043521249,
            (1, 11.07): 0.000877356823,
            (1, 20.0): 0.000007744216,
            (2, 0.5): 0.778800783071,
            (2, 3.84): 0.146606962130,
            (2, 11.07): 0.003946208636,
            (2, 20.0): 0.000045399930,
            (5, 0.5): 0.992123293233,
            (5, 3.84): 0.572674459832,
            (5, 11.07): 0.050009618622,
            (5, 20.0): 0.001249730563,
        }
        for (df, stat), expected in refs.items():
            self.assertAlmostEqual(
                _chi2_sf_py(stat, df), expected, places=6,
                msg=f"df={df} stat={stat}")

    def test_chi2_sf_zero_stat(self):
        self.assertEqual(_chi2_sf_py(0.0, 3), 1.0)
        self.assertEqual(_chi2_sf_py(-1.0, 3), 1.0)

    def test_chi2_sf_zero_df(self):
        # Degenerate: no informative degrees of freedom.
        self.assertEqual(_chi2_sf_py(5.0, 0), 1.0)
        self.assertEqual(_chi2_sf_py(0.0, 0), 1.0)


class TestEndToEnd(unittest.TestCase):
    def test_fail_open_vs_fail_closed(self):
        # Adapter A (baseline): flips deny->approve (fail open).
        # Adapter B (guardrail): flips to abstain (fail closed).
        # The test should detect the directional difference.
        ra, rb = [], []
        for i in range(30):
            cid = f"c{i}"
            ra.append(_r(cid, benign_decision="deny",
                         attacked_decision="approve"))
            rb.append(_r(cid, benign_decision="approve",
                         attacked_decision="approve",
                         attacked_abstained=True))
        for r in ra:
            self.assertEqual(flip_direction(r), "deny-to-approve")
        for r in rb:
            self.assertEqual(flip_direction(r), "to-abstain")
        table = direction_square_table(ra, rb)
        self.assertEqual(table["deny-to-approve"]["to-abstain"], 30)
        p = stuart_maxwell_p_value(table)
        self.assertIsNotNone(p)
        self.assertLess(p, 0.001)


if __name__ == "__main__":
    unittest.main()
