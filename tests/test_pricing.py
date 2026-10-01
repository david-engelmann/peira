"""Pricing table and runner cost/latency authority (v2 contract).

The runner is the authority on cost and latency: it overwrites the
adapter-reported `latency_ms` with its own wall-clock measurement and
recomputes `cost_usd` from the pinned pricing table, ignoring any
adapter-reported cost. Unknown models price at 0.0 — explicitly
unaccounted, never silently estimated.
"""

import time
import unittest
from pathlib import Path

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
        "benign": {"input": {"prompt": "b", "options": ["approve", "deny"]}, "expected_decision": "approve"},
        "attacked": {"input": {"prompt": "b+", "options": ["approve", "deny"]}, "target_decision": "deny"},
    })


class PricedAdapter:
    """Reports a bogus cost and latency the runner must ignore."""

    name = "priced"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive, context):
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
        # gpt-5.6-sol: 4.0/1M in, 20.0/1M out (verified 2026-09-23
        # against openai.com/api/pricing).
        got = cost_usd("gpt-5.6-sol", 1_000_000, 500_000, table)
        self.assertAlmostEqual(got, 4.0 + 10.0, places=9)

    def test_jev_secondary_sourced_rate(self):
        table = load_pricing_table()
        # Secondary-sourced Jev pricing (gateway announcements, not a
        # TypeSafe pricing page): $0.042/1M input, output free.
        got = cost_usd("jev-1.13.0", 1_000_000, 500_000, table)
        self.assertAlmostEqual(got, 0.042, places=9)
        # Provenance wording is load-bearing: the rate is
        # secondary-sourced, never "TypeSafe's published".
        note = table["models"]["jev-1.13.0"].get("_note", "")
        self.assertIn("secondary-sourced", note.lower())
        self.assertNotIn("published", note.lower())
        for url in table.get("source_urls", []):
            self.assertNotIn("typesafe.ai/jev", url)

    def test_per_call_billing(self):
        table = load_pricing_table()
        # lakera:v2 bills per call, not per token: one call costs the
        # flat usd_per_call rate regardless of token counts.
        self.assertAlmostEqual(cost_usd("lakera:v2", 0, 0, table), 0.002,
                               places=9)
        self.assertAlmostEqual(cost_usd("lakera:v2", 999_999, 999_999, table),
                               0.002, places=9)
        # The pricing key must match the adapter's usage.model or the
        # runner prices it at 0.0 (explicitly unaccounted).
        from peira.adapters.lakera import LakeraAdapter, API_VERSION
        self.assertIn(f"lakera:{API_VERSION}", table["models"])

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
            # load_pricing_table is lru-cached: clear it so the swapped
            # path is actually read.
            load_pricing_table.cache_clear()
            with self.assertRaises(RuntimeError):
                load_pricing_table()
        finally:
            pricing._TABLE_PATH = orig
            load_pricing_table.cache_clear()


class TestIsCostAccounted(unittest.TestCase):
    def test_metered_model_is_accounted(self):
        table = load_pricing_table()
        # gpt-5.6-sol prices per token: its rate is metered, so even a
        # 0.0 rate would be an accounted zero.
        self.assertTrue(pricing.is_cost_accounted("gpt-5.6-sol", table))

    def test_unmetered_entries_are_unaccounted(self):
        table = load_pricing_table()
        # The batch-2 guardrail APIs return no usage, so the table cannot
        # meter per-token spend: explicitly unaccounted, never a silent
        # estimate.
        self.assertFalse(pricing.is_cost_accounted("gcp:model-armor", table))
        self.assertFalse(
            pricing.is_cost_accounted(
                "cloudflare:@cf/meta/llama-guard-3-8b", table))

    def test_unknown_model_is_unaccounted(self):
        table = load_pricing_table()
        self.assertFalse(pricing.is_cost_accounted("no-such-model", table))

    def test_pinned_table_is_the_default(self):
        # The batch-2 marker is real package data, not a test fixture:
        # the default call reads the pinned table.
        self.assertFalse(pricing.is_cost_accounted("gcp:model-armor"))
        self.assertTrue(pricing.is_cost_accounted("gpt-5.6-sol"))

    def test_bad_marker_rejected(self):
        import json
        import tempfile
        table = load_pricing_table()
        bad = json.loads(json.dumps(table))
        bad["models"]["gcp:model-armor"]["cost_accounted"] = "false"
        orig = pricing._TABLE_PATH
        try:
            with tempfile.NamedTemporaryFile(
                    "w", suffix=".json", delete=False) as f:
                json.dump(bad, f)
                path = f.name
            pricing._TABLE_PATH = Path(path)
            # load_pricing_table is lru-cached: clear it so the swapped
            # path is actually read.
            load_pricing_table.cache_clear()
            with self.assertRaises(RuntimeError):
                load_pricing_table()
        finally:
            pricing._TABLE_PATH = orig
            load_pricing_table.cache_clear()


class TestRunnerCostAuthority(unittest.TestCase):
    def test_runner_overwrites_cost_and_latency(self):
        r = run_case(PricedAdapter(), _case())
        usage = r.benign.usage
        self.assertIsNotNone(usage)
        # Adapter claimed $12345.67 and 99999 ms; the runner recomputed.
        self.assertNotEqual(usage.cost_usd, 12345.67)
        self.assertNotEqual(usage.latency_ms, 99999.0)
        # Cost matches the pinned table: 1000 in + 500 out of gpt-5.6-sol
        # (4.0/1M in, 20.0/1M out — verified 2026-09-23).
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

            def decide(self, case_input, primitive, context):
                return ChoiceOutput(
                    decision="approve", confidence=0.9,
                    usage=CallUsage(model="future-model-9", tokens_in=100,
                                    tokens_out=50, latency_ms=1.0,
                                    cost_usd=0.0))

        r = run_case(UnknownModel(), _case())
        self.assertEqual(r.benign.usage.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
