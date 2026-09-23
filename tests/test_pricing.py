"""Pricing table and runner cost/latency authority (v2 contract).

The runner is the authority on cost and latency: it overwrites the
adapter-reported `latency_ms` with its own wall-clock measurement and
recomputes `cost_usd` from the pinned pricing table, ignoring any
adapter-reported cost. Unknown models price at 0.0 — explicitly
unaccounted, never silently estimated.
"""

import time
import unittest

from peira.adapters.base import ChoiceOutput, CallUsage
from peira import pricing
from peira.pricing import cost_usd, load_pricing_table
from peira.runner import run_case
from peira.schema import Case


def _case(case_id="p1"):
    return Case.from_dict({
        "case_id": case_id,
        "family": "literal_reading",
        "primitive": "choice",
        "severity": "medium",
        "benign": {"input": {"prompt": "b"}, "expected_decision": "approve"},
        "attacked": {"input": {"prompt": "b+"}, "target_decision": "deny"},
    })


class PricedAdapter:
    """Reports a bogus cost and latency the runner must ignore."""

    name = "priced"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        time.sleep(0.001)
        return ChoiceOutput(
            decision="approve", confidence=0.9,
            usage=CallUsage(model="gpt-5.6-sol", tokens_in=1000,
                            tokens_out=500, latency_ms=99999.0,
                            cost_usd=12345.67),
        )


class TestPricingTable(unittest.TestCase):
    def test_table_is_package_data(self):
        self.assertTrue(pricing._TABLE_PATH.is_file(), pricing._TABLE_PATH)
        table = load_pricing_table()
        self.assertIn("models", table)
        self.assertIn("date", table)
        self.assertIn("source", table)

    def test_known_model_calculation(self):
        table = load_pricing_table()
        # gpt-5.6-sol: 4.0/1M in, 20.0/1M out.
        got = cost_usd("gpt-5.6-sol", 1_000_000, 500_000, table)
        self.assertAlmostEqual(got, 4.0 + 10.0, places=9)

    def test_unknown_model_costs_zero(self):
        table = load_pricing_table()
        self.assertEqual(cost_usd("no-such-model", 10_000, 5_000, table), 0.0)

    def test_negative_tokens_raise(self):
        table = load_pricing_table()
        with self.assertRaises(ValueError):
            cost_usd("gpt-5.6-sol", -1, 0, table)
        with self.assertRaises(ValueError):
            cost_usd("gpt-5.6-sol", 0, -1, table)

    def test_missing_table_raises_runtime_error(self):
        orig = pricing._TABLE_PATH
        try:
            pricing._TABLE_PATH = orig.parent / "does-not-exist.json"
            with self.assertRaises(RuntimeError):
                load_pricing_table()
        finally:
            pricing._TABLE_PATH = orig


class TestRunnerCostAuthority(unittest.TestCase):
    def test_runner_overwrites_cost_and_latency(self):
        r = run_case(PricedAdapter(), _case())
        usage = r.benign.usage
        self.assertIsNotNone(usage)
        # Adapter claimed $12345.67 and 99999 ms; the runner recomputed.
        self.assertNotEqual(usage.cost_usd, 12345.67)
        self.assertNotEqual(usage.latency_ms, 99999.0)
        # Cost matches the pinned table: 1000 in + 500 out of gpt-5.6-sol.
        self.assertAlmostEqual(usage.cost_usd, 0.004 + 0.01, places=9)
        # Latency is a real wall-clock reading (tiny, not the adapter's).
        self.assertGreaterEqual(usage.latency_ms, 0.0)
        self.assertLess(usage.latency_ms, 1000.0)
        # Token counts pass through untouched.
        self.assertEqual((usage.tokens_in, usage.tokens_out), (1000, 500))

    def test_unknown_model_prices_zero_in_run(self):
        class UnknownModel:
            name = "unknown-model"
            version = "0.1.0"
            supported_primitives = frozenset({"choice"})

            def decide(self, case_input, primitive):
                return ChoiceOutput(
                    decision="approve", confidence=0.9,
                    usage=CallUsage(model="future-model-9", tokens_in=100,
                                    tokens_out=50, latency_ms=1.0,
                                    cost_usd=0.0))

        r = run_case(UnknownModel(), _case())
        self.assertEqual(r.benign.usage.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
