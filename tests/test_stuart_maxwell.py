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
        # Adapter B: approve -> approve... no flip. Use abstain instead.
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

    def test_known_value_against_scipy(self):
        # Cross-check the statistic and p-value against scipy's
        # chi-square survival function on a fixed table.
        from scipy.stats import chi2
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
        self.assertGreater(stat, 0.0)
        self.assertEqual(df, 2)
        # Our p-value must match scipy's chi2.sf.
        p = stuart_maxwell_p_value(table)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, chi2.sf(stat, df), places=6)

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
        # arrangement: homogeneity holds.
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 8,
            ("deny-to-approve", "to-abstain"): 4,
            ("to-abstain", "deny-to-approve"): 4,
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

    def test_single_live_category_raises(self):
        table = _table_from_counts({
            ("deny-to-approve", "deny-to-approve"): 10,
        })
        with self.assertRaises(ValueError):
            stuart_maxwell(table)


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

    def test_chi2_sf_against_scipy(self):
        from scipy.stats import chi2
        for df in (1, 2, 5):
            for stat in (0.5, 3.84, 11.07, 20.0):
                self.assertAlmostEqual(
                    _chi2_sf_py(stat, df), chi2.sf(stat, df), places=6,
                    msg=f"df={df} stat={stat}")

    def test_chi2_sf_zero_stat(self):
        self.assertEqual(_chi2_sf_py(0.0, 3), 1.0)
        self.assertEqual(_chi2_sf_py(-1.0, 3), 1.0)


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
