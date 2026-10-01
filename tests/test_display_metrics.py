"""Tests for the R-15 display metrics (confidence-as-failure-predictor displays).

MCE, average precision, MCC, balanced accuracy, Friedman/Nemenyi, and
BH-FDR adjustment. All pure-Python, deterministic, xdist-safe: no shared
state, no I/O.
"""

import math
import unittest

from peira.metrics import (
    mce,
    average_precision,
    mcc,
    balanced_accuracy,
    friedman_test,
    nemenyi_cd,
    bh_adjust,
)


class TestMCE(unittest.TestCase):
    def test_perfect_calibration_is_zero(self):
        probs = [0.1, 0.2, 0.8, 0.9]
        labels = [0, 0, 1, 1]
        self.assertAlmostEqual(mce(probs, labels, bins=2), 0.15, places=9)

    def test_worst_bin_reported(self):
        # Two bins: first perfectly calibrated, second maximally off.
        probs = [0.1, 0.1, 0.9, 0.9]
        labels = [0, 0, 0, 0]
        self.assertAlmostEqual(mce(probs, labels, bins=2), 0.9, places=9)

    def test_bounded_by_one(self):
        probs = [0.0, 1.0, 0.3, 0.7]
        labels = [1, 0, 1, 0]
        v = mce(probs, labels)
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 1.0)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            mce([], [])
        with self.assertRaises(ValueError):
            mce([0.5], [1], bins=0)


class TestAveragePrecision(unittest.TestCase):
    def test_perfect_ranking_is_one(self):
        # Highest failure-probability first, all failures on top.
        probs = [0.9, 0.8, 0.2, 0.1]
        labels = [1, 1, 0, 0]
        self.assertAlmostEqual(average_precision(probs, labels), 1.0, places=9)

    def test_worst_ranking(self):
        probs = [0.1, 0.2, 0.8, 0.9]
        labels = [1, 1, 0, 0]
        ap = average_precision(probs, labels)
        # precisions at ranks 3,4: 1/3, 2/4 -> (1/3 + 1/2)/2
        self.assertAlmostEqual(ap, (1 / 3 + 2 / 4) / 2, places=9)

    def test_no_positives_raises(self):
        with self.assertRaises(ValueError):
            average_precision([0.1, 0.9], [0, 0])

    def test_rejects_non_binary_labels(self):
        with self.assertRaises(ValueError):
            average_precision([0.1, 0.9], [0, 2])


class TestMCC(unittest.TestCase):
    def test_perfect(self):
        self.assertAlmostEqual(mcc([0, 0, 1, 1], [0, 0, 1, 1]), 1.0, places=9)

    def test_chance(self):
        # Balanced wrong: tp=tn=fp=fn=1 -> 0
        self.assertAlmostEqual(mcc([0, 0, 1, 1], [0, 1, 0, 1]), 0.0, places=9)

    def test_anticorrelated(self):
        self.assertAlmostEqual(mcc([0, 0, 1, 1], [1, 1, 0, 0]), -1.0, places=9)

    def test_degenerate_returns_zero_not_nan(self):
        v = mcc([1, 1, 1], [1, 1, 1])
        self.assertEqual(v, 0.0)
        self.assertFalse(math.isnan(v))

    def test_known_value(self):
        # tp=2, tn=1, fp=1, fn=1: (2*1-1*1)/sqrt(3*3*2*2) = 1/6
        self.assertAlmostEqual(
            mcc([1, 1, 0, 0, 1], [1, 0, 0, 1, 1]), 1 / 6, places=9
        )


class TestBalancedAccuracy(unittest.TestCase):
    def test_perfect(self):
        self.assertAlmostEqual(
            balanced_accuracy([0, 0, 1, 1], [0, 0, 1, 1]), 1.0, places=9
        )

    def test_majority_class_baseline(self):
        # Always predict 1: TPR=1, TNR=0 -> 0.5 (raw accuracy would be 0.75)
        self.assertAlmostEqual(
            balanced_accuracy([0, 1, 1, 1], [1, 1, 1, 1]), 0.5, places=9
        )

    def test_missing_class_uses_chance(self):
        self.assertAlmostEqual(
            balanced_accuracy([1, 1, 1], [1, 1, 1]), 0.75, places=9
        )


class TestFriedman(unittest.TestCase):
    def test_no_difference_high_p(self):
        # Identical adapters: statistic 0, p 1.
        scores = [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]
        stat, p = friedman_test(scores)
        self.assertAlmostEqual(stat, 0.0, places=9)
        self.assertAlmostEqual(p, 1.0, places=9)

    def test_clear_difference_low_p(self):
        # Adapter A always best, C always worst, over 10 blocks.
        scores = [
            [3.0] * 10,
            [2.0] * 10,
            [1.0] * 10,
        ]
        stat, p = friedman_test(scores)
        self.assertGreater(stat, 15.0)
        self.assertLess(p, 0.01)

    def test_ties_handled(self):
        scores = [[1.0, 1.0, 2.0], [1.0, 2.0, 2.0]]
        stat, p = friedman_test(scores)
        self.assertGreaterEqual(stat, 0.0)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_rejects_degenerate(self):
        with self.assertRaises(ValueError):
            friedman_test([[1.0, 2.0]])
        with self.assertRaises(ValueError):
            friedman_test([[1.0], [2.0]])
        with self.assertRaises(ValueError):
            friedman_test([[1.0, 2.0], [1.0]])


class TestNemenyi(unittest.TestCase):
    def test_known_value(self):
        # q(0.05, k=3) = 3.314; cd = 3.314 * sqrt(3*4/60)
        self.assertAlmostEqual(
            nemenyi_cd(3, 10), 3.314 * math.sqrt(12 / 60), places=6
        )

    def test_shrinks_with_blocks(self):
        self.assertGreater(nemenyi_cd(3, 5), nemenyi_cd(3, 50))

    def test_rejects_unknown_alpha(self):
        with self.assertRaises(ValueError):
            nemenyi_cd(3, 10, alpha=0.07)

    def test_rejects_big_k(self):
        with self.assertRaises(ValueError):
            nemenyi_cd(11, 10)


class TestBHAdjust(unittest.TestCase):
    def test_monotone_and_bounded(self):
        adj = bh_adjust([0.001, 0.01, 0.02, 0.5, 0.9])
        self.assertEqual(len(adj), 5)
        for a in adj:
            self.assertGreaterEqual(a, 0.0)
            self.assertLessEqual(a, 1.0)
        self.assertEqual(adj, sorted(adj))

    def test_known_values(self):
        # n=4: adj = p*4/rank, running min from the top.
        adj = bh_adjust([0.01, 0.02, 0.03, 0.04])
        self.assertAlmostEqual(adj[0], 0.04, places=9)
        self.assertAlmostEqual(adj[3], 0.04, places=9)

    def test_empty(self):
        self.assertEqual(bh_adjust([]), [])

    def test_rejects_bad_p(self):
        with self.assertRaises(ValueError):
            bh_adjust([0.5, 1.5])


if __name__ == "__main__":
    unittest.main()
