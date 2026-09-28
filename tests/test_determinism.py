"""Determinism contract tests: the executable form of docs/Execution-Contract.md.

Runs the mock adapter twice with different --max-concurrency values and
asserts the sealed results arrays are identical modulo the documented
non-deterministic fields (usage.latency_ms and dispatch_limit on each
call record). Also asserts dispatch_limit really does differ between the
caps, so the exclusion is not vacuous.

Run with: python -m unittest discover tests
"""

import unittest
from pathlib import Path

from peira.adapters.mock import MockAdapter
from peira.runner import load_cases, run_suite

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED = 7


def _run(cases, nonce, max_concurrency):
    """One full suite execution under an explicit run nonce."""
    script = MockAdapter.script_for(cases, seed=SEED, run_nonce=nonce)
    adapter = MockAdapter(script=script)
    return run_suite(
        adapter, cases, "trial-demo", "0.1.0-demo",
        seed=SEED, max_concurrency=max_concurrency, run_nonce=nonce,
    )


def _normalize_call_record(rec):
    """Blank the documented non-deterministic fields of one record dict."""
    rec = dict(rec)
    # The AIMD controller's live limit at dispatch time: timing-dependent
    # operational telemetry, excluded by the contract.
    rec["dispatch_limit"] = 0
    # Wall-clock timing, excluded by the contract (Phase 0 measurement
    # sidecar; usage.latency_ms is the legacy field).
    rec["latency_ms_total"] = 0.0
    usage = rec.get("usage")
    if usage is not None:
        usage = dict(usage)
        # Wall-clock timing, excluded by the contract.
        usage["latency_ms"] = 0.0
        rec["usage"] = usage
    return rec


def _normalize_results(results):
    norm = []
    for entry in results:
        entry = dict(entry)
        entry["benign"] = _normalize_call_record(entry["benign"])
        entry["attacked"] = _normalize_call_record(entry["attacked"])
        norm.append(entry)
    return norm


def _normalize_metrics(metrics):
    metrics = dict(metrics)
    # The latency sidecar summarizes wall-clock measurements; the rest of
    # the summary is a pure function of (results, seed).
    metrics["latency_ms"] = "excluded-by-contract"
    return metrics


def _dispatch_limits(artifact):
    return [
        (e["benign"]["dispatch_limit"], e["attacked"]["dispatch_limit"])
        for e in artifact.results
    ]


class TestDeterminismContract(unittest.TestCase):
    def test_results_identical_across_concurrency(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
        self.assertGreater(len(cases), 0)
        low = _run(cases, "determinism-nonce-low", max_concurrency=1)
        high = _run(cases, "determinism-nonce-high", max_concurrency=8)

        # Suite order is sealed, not completion order.
        self.assertEqual(
            [e["case_id"] for e in low.results],
            [c.case_id for c in cases],
        )
        self.assertEqual(
            [e["case_id"] for e in high.results],
            [c.case_id for c in cases],
        )
        # Dispatch indices are suite-positioned in both runs.
        for i, entry in enumerate(low.results):
            self.assertEqual(entry["benign"]["dispatch_index"], 2 * i)
            self.assertEqual(entry["attacked"]["dispatch_index"], 2 * i + 1)
        for i, entry in enumerate(high.results):
            self.assertEqual(entry["benign"]["dispatch_index"], 2 * i)
            self.assertEqual(entry["attacked"]["dispatch_index"], 2 * i + 1)

        # The contract: byte-identical results modulo the documented
        # non-deterministic fields.
        self.assertEqual(
            _normalize_results(low.results),
            _normalize_results(high.results),
        )
        # The metric summary likewise, modulo the latency sidecar.
        self.assertEqual(
            _normalize_metrics(low.metrics),
            _normalize_metrics(high.metrics),
        )

        # The exclusions are real, not vacuous: the AIMD observation
        # differs between the caps (1 is pinned at max_concurrency=1;
        # the higher cap slow-starts 1 -> 2 -> ... on completions).
        self.assertNotEqual(
            _dispatch_limits(low), _dispatch_limits(high),
            "dispatch_limit did not differ between concurrency caps; "
            "if the runner changed, update docs/Execution-Contract.md",
        )

    def test_same_config_rerun_matches(self):
        # Identical config, fresh nonces: normalized results agree.
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
        first = _run(cases, "determinism-nonce-r1", max_concurrency=4)
        second = _run(cases, "determinism-nonce-r2", max_concurrency=4)
        self.assertEqual(
            _normalize_results(first.results),
            _normalize_results(second.results),
        )


if __name__ == "__main__":
    unittest.main()
