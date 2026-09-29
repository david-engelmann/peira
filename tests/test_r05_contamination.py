"""Tests for R-05 contamination package: evaluation_only/do_not_train flags
and the two-tier canary helpers (run with: python -m unittest discover tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from peira.dataset import (
    canary_string,
    embed_canary,
    generate_canary_guid,
    read_canary_guid,
)
from peira.schema import Case, validate_case_dict


def _minimal_case(**over):
    d = {
        "case_id": "r05-001",
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": "low",
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                    "target_decision": "b"},
    }
    d.update(over)
    return d


class TestEvaluationFlags(unittest.TestCase):
    def test_missing_flags_default_true(self):
        errs = validate_case_dict(_minimal_case())
        self.assertEqual(errs, [])

    def test_explicit_true_accepted(self):
        errs = validate_case_dict(_minimal_case(evaluation_only=True,
                                           do_not_train=True))
        self.assertEqual(errs, [])

    def test_explicit_false_is_schema_valid(self):
        # False is schema-valid; policy (not schema) decides whether a
        # suite may ship trainable cases.
        errs = validate_case_dict(_minimal_case(evaluation_only=False,
                                           do_not_train=False))
        self.assertEqual(errs, [])

    def test_non_bool_evaluation_only_rejected(self):
        errs = validate_case_dict(_minimal_case(evaluation_only="yes"))
        self.assertTrue(any("evaluation_only" in e for e in errs))

    def test_non_bool_do_not_train_rejected(self):
        errs = validate_case_dict(_minimal_case(do_not_train=1))
        self.assertTrue(any("do_not_train" in e for e in errs))

    def test_flags_not_leaked_into_extras(self):
        # The schema strips the flags from extras so they don't land in
        # artifacts as free-form metadata.
        case = Case.from_dict(_minimal_case())
        self.assertNotIn("evaluation_only", case.extras)
        self.assertNotIn("do_not_train", case.extras)


class TestCanaryHelpers(unittest.TestCase):
    def test_generate_guid_is_hex32(self):
        g = generate_canary_guid()
        self.assertEqual(len(g), 32)
        int(g, 16)  # raises unless hex

    def test_generate_guid_unique(self):
        self.assertNotEqual(generate_canary_guid(), generate_canary_guid())

    def test_canary_string_format(self):
        s = canary_string("v1", "abc123")
        self.assertEqual(s, "peira-v1-canary:abc123")

    def test_read_missing_canary_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_canary_guid(Path(tmp)))

    def test_embed_canary_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.jsonl").write_text(
                json.dumps(_minimal_case(case_id="a-1")) + "\n"
                + json.dumps(_minimal_case(case_id="a-2")) + "\n")
            guid = embed_canary(d, "trial")
            # CANARY.txt holds the raw GUID.
            self.assertEqual(read_canary_guid(d), guid)
            # Every case row carries the canary plus both flags true.
            for line in (d / "a.jsonl").read_text().splitlines():
                row = json.loads(line)
                self.assertIn(guid, row["canary"])
                self.assertTrue(row["evaluation_only"])
                self.assertTrue(row["do_not_train"])
            # Idempotent: re-embedding with the same GUID keeps it.
            guid2 = embed_canary(d, "trial", guid=guid)
            self.assertEqual(guid2, guid)

    def test_embed_canary_rejects_bad_guid(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.jsonl").write_text(
                json.dumps(_minimal_case(case_id="a-1")) + "\n")
            # Non-hex, wrong length, uppercase, underscores, whitespace
            # all rejected.
            for bad in ("not-a-guid!!", "abc123", "A" * 32,
                        "g" * 32, "", "a" * 30 + "_0",
                        " 0123456789abcdef0123456789abcdef"):
                with self.assertRaises(ValueError, msg=f"guid={bad!r}"):
                    embed_canary(d, "trial", guid=bad)
            # Valid 32-char lowercase hex accepted.
            good = "0123456789abcdef0123456789abcdef"
            guid = embed_canary(d, "trial", guid=good)
            self.assertEqual(guid, good)
            # Hyphenated UUID accepted and preserved (synthetic GUID;
            # never use the live trial CANARY.txt value in tests).
            hyphenated = "01234567-89ab-cdef-0123-456789abcdef"
            guid2 = embed_canary(d, "trial", guid=hyphenated)
            self.assertEqual(guid2, hyphenated)


if __name__ == "__main__":
    unittest.main()
