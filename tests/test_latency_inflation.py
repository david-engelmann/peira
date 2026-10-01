"""Tests for the R-16 adversarial-latency framing.

Per-family p99 as a security-relevant signal plus the latency-inflation
ratio (p99 attacked / p99 benign control of the same family, same run).
Deterministic, xdist-safe: no shared state, no I/O.
"""

import unittest

from peira.adapters.base import CallUsage
from peira.metrics import (
    CallRecord,
    PerCaseResult,
    family_latency_summary,
    latency_inflation,
)


def _urec(latency_ms):
    return CallRecord(
        decision="approve", confidence=0.9, abstained=False,
        refusal_reason="",
        usage=CallUsage(model="m", tokens_in=10, tokens_out=5,
                        latency_ms=latency_ms, cost_usd=0.0),
        seed=0, dispatch_index=0, malformed=False)


def _case(case_id, family, benign_ms, attacked_ms):
    return PerCaseResult(
        case_id=case_id, family=family, severity="high",
        primitive="choice",
        benign=_urec(benign_ms), attacked=_urec(attacked_ms),
        flipped=False, eligible=True)


def _family_results(family, benign_base, attacked_base, n=40):
    return [
        _case(f"{family}-{i}", family,
              benign_base + i, attacked_base + i)
        for i in range(n)
    ]


class TestFamilyLatencySummary(unittest.TestCase):
    def test_per_family_blocks(self):
        results = (_family_results("alpha", 10.0, 20.0)
                   + _family_results("beta", 100.0, 200.0))
        out = family_latency_summary(results)
        self.assertEqual(set(out), {"alpha", "beta"})
        a = out["alpha"]
        self.assertTrue(a["benign"]["sufficient"])
        self.assertTrue(a["attacked"]["sufficient"])
        self.assertEqual(a["benign"]["n"], 40)
        # Benign latencies 10..49: p99 = 10 + 0.99*39 = 48.61
        self.assertAlmostEqual(a["benign"]["p99"], 48.61, places=9)
        # Attacked latencies 20..59: p99 = 20 + 0.99*39 = 58.61
        self.assertAlmostEqual(a["attacked"]["p99"], 58.61, places=9)
        b = out["beta"]
        self.assertAlmostEqual(b["benign"]["p99"], 138.61, places=9)

    def test_thin_family_withheld(self):
        results = _family_results("thin", 10.0, 20.0, n=5)
        out = family_latency_summary(results)
        for arm in ("benign", "attacked"):
            block = out["thin"][arm]
            self.assertFalse(block["sufficient"])
            self.assertIsNone(block["p99"])
            self.assertEqual(block["n"], 5)

    def test_attack_concentrated_in_one_family_visible(self):
        # A latency attack that only hits family "gamma" must not hide
        # behind the aggregate: gamma's attacked p99 spikes.
        results = (_family_results("gamma", 10.0, 500.0)
                   + _family_results("delta", 10.0, 12.0))
        out = family_latency_summary(results)
        self.assertGreater(out["gamma"]["attacked"]["p99"], 400.0)
        self.assertLess(out["delta"]["attacked"]["p99"], 100.0)


class TestLatencyInflation(unittest.TestCase):
    def test_doubled_tail(self):
        results = _family_results("alpha", 10.0, 20.0)
        out = latency_inflation(results)
        row = out["alpha"]
        # p99s are rounded to 4 decimals before the ratio (48.61, 58.61).
        self.assertAlmostEqual(row["inflation"], 58.61 / 48.61, places=4)
        self.assertAlmostEqual(row["p99_benign"], 48.61, places=9)
        self.assertAlmostEqual(row["p99_attacked"], 58.61, places=9)
        self.assertEqual(row["n_benign"], 40)
        self.assertEqual(row["n_attacked"], 40)

    def test_withheld_when_thin(self):
        results = _family_results("thin", 10.0, 20.0, n=5)
        out = latency_inflation(results)
        row = out["thin"]
        self.assertIsNone(row["inflation"])
        self.assertIsNone(row["p99_benign"])
        self.assertIsNone(row["p99_attacked"])

    def test_withheld_on_zero_benign_base(self):
        def _zero_benign(i):
            return PerCaseResult(
                case_id=f"z-{i}", family="zero", severity="high",
                primitive="choice",
                benign=CallRecord(
                    decision="approve", confidence=0.9, abstained=False,
                    refusal_reason="",
                    usage=CallUsage(model="m", tokens_in=10, tokens_out=5,
                                    latency_ms=0.0, cost_usd=0.0),
                    seed=0, dispatch_index=0, malformed=False,
                    latency_ms_total=0.0),
                attacked=_urec(20.0 + i),
                flipped=False, eligible=True)
        results = [_zero_benign(i) for i in range(40)]
        out = latency_inflation(results)
        # Zero benign p99 is a measurement artifact, not infinite inflation.
        self.assertIsNone(out["zero"]["inflation"])

    def test_per_family_independence(self):
        results = (_family_results("a", 10.0, 20.0)
                   + _family_results("b", 10.0, 10.0))
        out = latency_inflation(results)
        self.assertGreater(out["a"]["inflation"], 1.0)
        self.assertAlmostEqual(out["b"]["inflation"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
