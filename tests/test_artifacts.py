"""Unit tests for strict RunArtifact.from_json validation (v2 contract).

Run with: PYTHONPATH=python python3 -m unittest discover tests
"""

import json
import unittest

from peira.artifacts import RunArtifact


def _call_record(**over):
    record = {
        "decision": "approve",
        "confidence": 0.9,
        "abstained": False,
        "refusal_reason": "",
        "usage": {
            "model": "gpt-5.6-sol",
            "tokens_in": 100,
            "tokens_out": 20,
            "latency_ms": 350.0,
            "cost_usd": 0.001,
        },
        "seed": 7,
        "dispatch_index": 0,
        "malformed": False,
        "dispatch_limit": 1,
    }
    record.update(over)
    return record


def _result_entry(**over):
    entry = {
        "case_id": "c1",
        "family": "indirection",
        "severity": "high",
        "primitive": "choice",
        "benign": _call_record(),
        "attacked": _call_record(decision="deny", dispatch_index=1),
        "flipped": True,
        "eligible": True,
        "ineligibility_reason": "",
    }
    entry.update(over)
    return entry


def _artifact_dict(**over):
    a = RunArtifact(
        peira_version="0.1.0",
        dataset_version="1.0.0",
        adapter_name="mock",
        adapter_version="1",
        suite="trial-demo",
    ).seal()
    d = json.loads(a.to_json())
    d.update(over)
    return d


class TestStrictFromJson(unittest.TestCase):
    def test_roundtrip(self):
        a = RunArtifact(
            peira_version="0.1.0",
            dataset_version="1.0.0",
            adapter_name="mock",
            adapter_version="1",
            suite="trial-demo",
            results=[_result_entry()],
        ).seal()
        b = RunArtifact.from_json(a.to_json())
        self.assertEqual(a, b)
        self.assertTrue(b.verify())

    def test_missing_required_field(self):
        for key in ("peira_version", "dataset_version"):
            d = _artifact_dict()
            del d[key]
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    ValueError, f"missing required field: {key!r}"
                ):
                    RunArtifact.from_json(json.dumps(d))

    def test_unknown_field_rejected(self):
        # Silently accepting a newer/renamed field could verify a lock
        # under changed semantics; the format loads strictly.
        d = _artifact_dict(bogus=1)
        with self.assertRaisesRegex(ValueError, "unknown artifact field"):
            RunArtifact.from_json(json.dumps(d))

    def test_wrong_field_type(self):
        for key, bad, want in [
            ("config", "nope", "dict"),
            ("results", {"x": 1}, "list"),
            ("metrics", [], "dict"),
            ("peira_version", 5, "str"),
            ("seed", "7", "an integer"),
        ]:
            d = _artifact_dict(**{key: bad})
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, f"must be {want}"):
                    RunArtifact.from_json(json.dumps(d))

    def test_minimal_artifact_gets_rust_matching_defaults(self):
        # Only the two required lock identifiers: every optional field
        # defaults exactly like the Rust core (config/metrics -> {}, not
        # null), so minimal artifacts load identically on both backends.
        a = RunArtifact.from_json(
            json.dumps({"peira_version": "x", "dataset_version": "y"})
        )
        self.assertEqual(a.artifact_version, "2")
        self.assertEqual(a.config, {})
        self.assertEqual(a.metrics, {})
        self.assertEqual(a.results, [])
        self.assertEqual(a.analysis_lock, "")
        self.assertEqual(a.seed, 0)
        self.assertEqual(a.pricing_source, "")
        self.assertEqual(a.pricing_date, "")

    def test_scalar_and_bad_json_rejected(self):
        for s in ('[1, 2]', '"x"', "42", "{bad"):
            with self.subTest(s=s):
                with self.assertRaises(ValueError):
                    RunArtifact.from_json(s)

    def test_v1_artifacts_rejected_with_clear_error(self):
        # v1 artifacts predate the v2 measurement contract: no migration,
        # no silent acceptance.
        d = _artifact_dict()
        d["artifact_version"] = "1"
        with self.assertRaisesRegex(
            ValueError, "v1 artifacts.*cannot be loaded or migrated"
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_missing_version_defaults_to_v2(self):
        # A hand-written artifact that predates the version field is
        # assumed v2: there is no other format to be.
        d = _artifact_dict()
        del d["artifact_version"]
        a = RunArtifact.from_json(json.dumps(d))
        self.assertEqual(a.artifact_version, "2")

    def test_lock_covers_pricing_and_seed(self):
        # Pricing provenance and seed are measurement inputs: changing
        # them must change the lock.
        a = RunArtifact(
            peira_version="0.1.0", dataset_version="1.0.0",
            pricing_source="s", pricing_date="2026-09-23", seed=7,
        ).seal()
        b = RunArtifact(
            peira_version="0.1.0", dataset_version="1.0.0",
            pricing_source="s", pricing_date="2026-09-24", seed=7,
        ).seal()
        self.assertNotEqual(a.analysis_lock, b.analysis_lock)
        c = RunArtifact(
            peira_version="0.1.0", dataset_version="1.0.0",
            pricing_source="s", pricing_date="2026-09-23", seed=8,
        ).seal()
        self.assertNotEqual(a.analysis_lock, c.analysis_lock)

    def test_lock_covers_metrics(self):
        # P0-1 (2026-09-25): headline metrics are lock-covered. Forging
        # metrics after sealing must invalidate the lock.
        a = RunArtifact(
            peira_version="0.1.0", dataset_version="1.0.0",
            metrics={"asr_conditional": 0.5},
        ).seal()
        self.assertTrue(a.verify())
        a.metrics = {"asr_conditional": 1.0}
        self.assertFalse(a.verify())


class TestResultEntryValidation(unittest.TestCase):
    """Result entries validate like Rust's `Vec<PerCaseResult>`."""

    def test_valid_entries_load(self):
        d = _artifact_dict(results=[_result_entry()])
        a = RunArtifact.from_json(json.dumps(d))
        self.assertEqual(a.results[0]["case_id"], "c1")
        self.assertEqual(a.results[0]["benign"]["decision"], "approve")
        self.assertEqual(a.results[0]["attacked"]["decision"], "deny")
        self.assertTrue(a.results[0]["flipped"])
        self.assertTrue(a.results[0]["eligible"])

    def test_scalar_entry_rejected(self):
        d = _artifact_dict(results=[42])
        with self.assertRaisesRegex(
            ValueError, "artifact results entry 0 must be an object, got int"
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_missing_required_entry_field(self):
        entry = _result_entry()
        del entry["family"]
        d = _artifact_dict(results=[entry])
        with self.assertRaisesRegex(
            ValueError,
            "artifact results entry 0 is missing required field: 'family'",
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_wrong_typed_entry_field(self):
        d = _artifact_dict(results=[_result_entry(eligible="yes")])
        with self.assertRaisesRegex(
            ValueError,
            "artifact results entry 0 field 'eligible' must be bool, got str",
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_unknown_entry_fields_rejected(self):
        # Unlike the v1 loader, v2 rejects unknown entry fields: silently
        # dropping a newer field could verify a lock under changed
        # semantics.
        d = _artifact_dict(results=[_result_entry(extra_future=1)])
        with self.assertRaisesRegex(
            ValueError, "artifact results entry 0 has unknown field"
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_unknown_call_record_fields_rejected(self):
        entry = _result_entry()
        entry["benign"]["bogus"] = 1
        d = _artifact_dict(results=[entry])
        with self.assertRaisesRegex(ValueError, "has unknown field"):
            RunArtifact.from_json(json.dumps(d))

    def test_missing_call_record_field_rejected(self):
        entry = _result_entry()
        del entry["attacked"]["malformed"]
        d = _artifact_dict(results=[entry])
        with self.assertRaisesRegex(ValueError, "is missing field"):
            RunArtifact.from_json(json.dumps(d))

    def test_null_or_missing_confidence_ok(self):
        # `confidence` is the one nullable record field besides `usage`:
        # a malformed call has no confidence to report.
        for record in (
            _call_record(confidence=None),
            {k: v for k, v in _call_record().items() if k != "confidence"},
        ):
            entry = _result_entry(benign=record)
            d = _artifact_dict(results=[entry])
            a = RunArtifact.from_json(json.dumps(d))
            self.assertIsNone(a.results[0]["benign"].get("confidence"))

    def test_bool_confidence_rejected(self):
        # bool is a subclass of int; a JSON `true` is not a number.
        entry = _result_entry()
        entry["benign"]["confidence"] = True
        d = _artifact_dict(results=[entry])
        with self.assertRaisesRegex(
            ValueError, "field 'confidence' must be a number or null"
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_bad_score_rejected(self):
        # A3 S6: `score` is a number or null, like `confidence`; a
        # string or bool in a call record fails the strict loader.
        for bad in ("0.5", True, [0.5]):
            entry = _result_entry()
            entry["benign"]["score"] = bad
            d = _artifact_dict(results=[entry])
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(
                    ValueError, r"field 'score': score must be a number in 0\.\.1"
                ):
                    RunArtifact.from_json(json.dumps(d))

    def test_hostile_score_rejected(self):
        # A3 S6 review P1: the strict loader enforces the unit-interval
        # rule both backends agree on. Python's json accepts
        # NaN/Infinity (serde_json rejects them at parse) and never
        # range-checked, so a crafted artifact must fail here with a
        # clean error — never load into the diagnostics.
        for bad in (2.5, -0.5, float("nan"), float("inf"), float("-inf")):
            entry = _result_entry()
            entry["benign"]["score"] = bad
            d = _artifact_dict(results=[entry])
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(
                    ValueError, r"field 'score': score .* outside 0\.\.1"
                ):
                    RunArtifact.from_json(json.dumps(d))

    def test_score_boundaries_ok(self):
        # 0.0 and 1.0 are legitimate scores and load cleanly.
        for good in (0.0, 1.0, 0.5):
            entry = _result_entry()
            entry["benign"]["score"] = good
            d = _artifact_dict(results=[entry])
            with self.subTest(good=good):
                a = RunArtifact.from_json(json.dumps(d))
                self.assertEqual(a.results[0]["benign"]["score"], good)

    def test_null_score_ok(self):
        # Non-score primitives seal `score: null`; absent in pre-S6
        # artifacts.
        entry = _result_entry()
        entry["benign"]["score"] = None
        d = _artifact_dict(results=[entry])
        a = RunArtifact.from_json(json.dumps(d))
        self.assertIsNone(a.results[0]["benign"]["score"])

    def test_null_usage_ok(self):
        # The mock reports no usage: null is the honest value.
        entry = _result_entry()
        entry["benign"]["usage"] = None
        d = _artifact_dict(results=[entry])
        a = RunArtifact.from_json(json.dumps(d))
        self.assertIsNone(a.results[0]["benign"]["usage"])

    def test_usage_missing_field_rejected(self):
        entry = _result_entry()
        del entry["benign"]["usage"]["cost_usd"]
        d = _artifact_dict(results=[entry])
        with self.assertRaisesRegex(ValueError, "usage is missing field"):
            RunArtifact.from_json(json.dumps(d))

    def test_usage_negative_tokens_rejected(self):
        entry = _result_entry()
        entry["benign"]["usage"]["tokens_in"] = -1
        d = _artifact_dict(results=[entry])
        with self.assertRaises(ValueError):
            RunArtifact.from_json(json.dumps(d))

    def test_malformed_record_loads(self):
        # Malformed records carry confidence=None and the "<error>"
        # sentinel decision: they must round-trip through strict loading.
        record = _call_record(decision="<error>", confidence=None,
                             malformed=True, usage=None)
        entry = _result_entry(benign=record, eligible=False,
                              ineligibility_reason="benign_malformed")
        d = _artifact_dict(results=[entry])
        a = RunArtifact.from_json(json.dumps(d))
        self.assertTrue(a.results[0]["benign"]["malformed"])

    def test_non_object_config_or_metrics_rejected(self):
        for key, bad in [("config", "x"), ("metrics", [1])]:
            d = _artifact_dict(**{key: bad})
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    ValueError, f"artifact field '{key}' must be dict"
                ):
                    RunArtifact.from_json(json.dumps(d))


if __name__ == "__main__":
    unittest.main()
