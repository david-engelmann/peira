"""Unit tests for strict RunArtifact.from_json validation
(run with: python -m unittest discover tests)."""

import json
import unittest

from peira.artifacts import RunArtifact


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
        # under changed semantics; the frozen format loads strictly.
        d = _artifact_dict(bogus=1)
        with self.assertRaisesRegex(ValueError, "unknown artifact field"):
            RunArtifact.from_json(json.dumps(d))

    def test_wrong_field_type(self):
        for key, bad, want in [
            ("config", "nope", "dict"),
            ("results", {"x": 1}, "list"),
            ("metrics", [], "dict"),
            ("peira_version", 5, "str"),
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
        self.assertEqual(a.artifact_version, "1")
        self.assertEqual(a.config, {})
        self.assertEqual(a.metrics, {})
        self.assertEqual(a.results, [])
        self.assertEqual(a.analysis_lock, "")

    def test_scalar_and_bad_json_rejected(self):
        for s in ('[1, 2]', '"x"', "42", "{bad"):
            with self.subTest(s=s):
                with self.assertRaises(ValueError):
                    RunArtifact.from_json(s)


def _result_entry(**over):
    entry = {
        "case_id": "c1",
        "family": "indirection",
        "primitive": "choice",
        "benign_correct": True,
        "attacked_flipped": False,
        "attacked_targeted": False,
        "malformed": False,
        "confidence": 0.9,
    }
    entry.update(over)
    return entry


class TestResultEntryValidation(unittest.TestCase):
    """Result entries validate like Rust's `Vec<PerCaseResult>`."""

    def test_valid_entries_load(self):
        d = _artifact_dict(results=[_result_entry()])
        a = RunArtifact.from_json(json.dumps(d))
        self.assertEqual(a.results[0]["case_id"], "c1")
        self.assertEqual(a.results[0]["confidence"], 0.9)

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
            ValueError, "artifact results entry 0 is missing required field: 'family'"
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_wrong_typed_entry_field(self):
        d = _artifact_dict(results=[_result_entry(benign_correct="yes")])
        with self.assertRaisesRegex(
            ValueError,
            "artifact results entry 0 field 'benign_correct' must be bool, got str",
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_bool_confidence_rejected(self):
        # bool is a subclass of int; a JSON `true` is not a number.
        d = _artifact_dict(results=[_result_entry(confidence=True)])
        with self.assertRaisesRegex(
            ValueError, "artifact results entry 0 field 'confidence'"
        ):
            RunArtifact.from_json(json.dumps(d))

    def test_null_or_missing_confidence_ok(self):
        # `confidence` is optional and nullable (Rust: Option<f64>).
        null_entry = _result_entry(confidence=None)
        missing_entry = _result_entry()
        del missing_entry["confidence"]
        for entry in (null_entry, missing_entry):
            with self.subTest(entry=entry):
                d = _artifact_dict(results=[entry])
                a = RunArtifact.from_json(json.dumps(d))
                self.assertIsNone(a.results[0]["confidence"])

    def test_unknown_entry_fields_ignored_but_break_lock(self):
        # Unknown entry fields are ignored (serde parity), but the lock
        # still binds the full entry: an entry with an extra field loads,
        # then fails verification — fail-closed, never silent.
        d = _artifact_dict(results=[_result_entry(extra_future=1)])
        a = RunArtifact.from_json(json.dumps(d))
        self.assertNotIn("extra_future", a.results[0])
        self.assertFalse(a.verify())


if __name__ == "__main__":
    unittest.main()
