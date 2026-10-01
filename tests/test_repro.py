"""Tests for peira.repro: determinism-verification primitives.

The primitives are the executable form of docs/Execution-Contract.md:
contract-excluded fields are blanked by normalization, everything else
must match exactly except float metrics within tolerance.
"""

import unittest

from peira.repro import (
    artifacts_reproduce,
    compare_artifacts,
    normalize_artifact,
    normalize_call_record,
    normalize_metrics,
)


def _record(**overrides):
    rec = {
        "decision": "approve",
        "confidence": 0.85,
        "abstained": False,
        "refusal_reason": "",
        "usage": {
            "model": "mock",
            "tokens_in": 10,
            "tokens_out": 2,
            "latency_ms": 12.5,
            "cost_usd": 0.0,
        },
        "seed": 7,
        "dispatch_index": 3,
        "malformed": False,
        "dispatch_limit": 8,
        "latency_ms_total": 44.1,
        "timing_ms": {
            "admission_wait_ms": 1.0,
            "adapter_execution_ms": 40.0,
            "harness_overhead_ms": 2.0,
            "backoff_ms": 1.1,
        },
    }
    rec.update(overrides)
    return rec


def _artifact(**overrides):
    art = {
        "results": [
            {"benign": _record(), "attacked": _record(decision="deny")},
        ],
        "metrics": {
            "asr_conditional": 0.4,
            "latency_ms": {"p50": 12.0},
            "timing_ms": {"total": 99.0},
        },
        "seed": 7,
        "cases_completed": 1,
        "cases_planned": 1,
        "termination": "complete",
    }
    art.update(overrides)
    return art


class NormalizeCallRecordTests(unittest.TestCase):
    def test_blanks_contract_excluded_fields(self):
        norm = normalize_call_record(_record())
        self.assertEqual(norm["dispatch_limit"], "excluded-by-contract:dispatch_limit")
        self.assertEqual(norm["latency_ms_total"], "excluded-by-contract:latency_ms_total")
        self.assertEqual(norm["timing_ms"], "excluded-by-contract:timing_ms")
        self.assertEqual(
            norm["usage"]["latency_ms"], "excluded-by-contract:latency_ms"
        )

    def test_keeps_measurement_fields(self):
        norm = normalize_call_record(_record())
        self.assertEqual(norm["decision"], "approve")
        self.assertEqual(norm["seed"], 7)
        self.assertEqual(norm["usage"]["tokens_in"], 10)

    def test_does_not_mutate_input(self):
        rec = _record()
        normalize_call_record(rec)
        self.assertEqual(rec["dispatch_limit"], 8)
        self.assertEqual(rec["usage"]["latency_ms"], 12.5)

    def test_missing_excluded_fields_are_fine(self):
        rec = _record()
        del rec["dispatch_limit"]
        del rec["timing_ms"]
        norm = normalize_call_record(rec)
        self.assertNotIn("dispatch_limit", norm)


class NormalizeMetricsTests(unittest.TestCase):
    def test_blanks_latency_rollups(self):
        norm = normalize_metrics({"asr_conditional": 0.4,
                                  "latency_ms": {"p50": 1.0},
                                  "timing_ms": {}})
        self.assertEqual(norm["asr_conditional"], 0.4)
        self.assertEqual(norm["latency_ms"], "excluded-by-contract:latency_ms")
        self.assertEqual(norm["timing_ms"], "excluded-by-contract:timing_ms")


class CompareArtifactsTests(unittest.TestCase):
    def test_identical_reruns_reproduce(self):
        a = normalize_artifact(_artifact())
        b = normalize_artifact(_artifact())
        self.assertTrue(artifacts_reproduce(a, b))
        self.assertEqual(compare_artifacts(a, b), [])

    def test_decision_change_is_a_mismatch(self):
        a = normalize_artifact(_artifact())
        other = _artifact()
        other["results"][0]["attacked"]["decision"] = "approve"
        b = normalize_artifact(other)
        self.assertFalse(artifacts_reproduce(a, b))
        mismatches = compare_artifacts(a, b)
        self.assertTrue(any("decision" in m for m in mismatches))

    def test_seed_change_is_a_mismatch(self):
        a = normalize_artifact(_artifact())
        b = normalize_artifact(_artifact(seed=8))
        self.assertFalse(artifacts_reproduce(a, b))

    def test_float_noise_within_tolerance_reproduces(self):
        a = normalize_artifact(_artifact())
        other = _artifact()
        other["metrics"]["asr_conditional"] = 0.4 + 1e-12
        b = normalize_artifact(other)
        self.assertTrue(artifacts_reproduce(a, b))

    def test_real_metric_divergence_is_a_mismatch(self):
        a = normalize_artifact(_artifact())
        other = _artifact()
        other["metrics"]["asr_conditional"] = 0.5
        b = normalize_artifact(other)
        self.assertFalse(artifacts_reproduce(a, b))
        mismatches = compare_artifacts(a, b)
        self.assertTrue(any("asr_conditional" in m for m in mismatches))

    def test_bool_never_equals_int(self):
        a = normalize_artifact(_artifact())
        other = _artifact()
        other["results"][0]["benign"]["abstained"] = 0
        b = normalize_artifact(other)
        self.assertFalse(artifacts_reproduce(a, b))

    def test_length_mismatch_reported(self):
        a = normalize_artifact(_artifact())
        other = _artifact(results=[])
        b = normalize_artifact(other)
        mismatches = compare_artifacts(a, b)
        self.assertTrue(any("length" in m for m in mismatches))

    def test_timing_only_difference_reproduces(self):
        # The whole point of normalization: reruns that differ only in
        # wall-clock timing are the same measurement.
        a = normalize_artifact(_artifact())
        other = _artifact()
        other["results"][0]["benign"]["latency_ms_total"] = 999.9
        other["results"][0]["benign"]["dispatch_limit"] = 1
        other["metrics"]["latency_ms"] = {"p50": 999.0}
        b = normalize_artifact(other)
        self.assertTrue(artifacts_reproduce(a, b))


if __name__ == "__main__":
    unittest.main()
