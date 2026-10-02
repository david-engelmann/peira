"""Tests for the family/suite id split in peira/schema.py and gates.py."""

import unittest
from pathlib import Path

from peira import gates
from peira.schema import (
    CANONICAL_FAMILIES,
    GATE_KNOWN_IDS,
    SUITE_IDS,
)


def _case(family: str) -> tuple:
    return (Path("cases.jsonl"), 1, {"family": family})


class TestSchemaFamilySplit(unittest.TestCase):
    def test_canonical_families(self):
        # No cap on families (David 2026-09-28).
        self.assertEqual(len(CANONICAL_FAMILIES), 29)
        self.assertIn("verbosity_inflation", CANONICAL_FAMILIES)
        self.assertIn("retrieval_poisoning", CANONICAL_FAMILIES)
        self.assertIn("evidence_positioning", CANONICAL_FAMILIES)
        self.assertIn("crosslingual_shift", CANONICAL_FAMILIES)
        self.assertIn("judge_sycophancy", CANONICAL_FAMILIES)
        self.assertIn("threshold_edge_hunting", CANONICAL_FAMILIES)
        self.assertIn("question_pair_incoherence", CANONICAL_FAMILIES)
        self.assertIn("cryptographic_payload", CANONICAL_FAMILIES)
        self.assertIn("frequency_salience", CANONICAL_FAMILIES)
        self.assertNotIn("safety_policy", CANONICAL_FAMILIES)

    def test_suite_ids_separate(self):
        self.assertEqual(SUITE_IDS, ("safety_policy",))
        self.assertNotIn("safety_policy", CANONICAL_FAMILIES)

    def test_gate_known_ids_backwards_compatible(self):
        # G4 keeps accepting the old suite id after the split.
        self.assertIn("safety_policy", GATE_KNOWN_IDS)
        self.assertEqual(
            set(GATE_KNOWN_IDS), set(CANONICAL_FAMILIES) | set(SUITE_IDS)
        )


class TestGateFamilies(unittest.TestCase):
    def test_new_family_passes(self):
        result = gates.gate_families([_case("instruction_override")])
        self.assertEqual(result.errors, [])

    def test_safety_policy_still_passes(self):
        result = gates.gate_families([_case("safety_policy")])
        self.assertEqual(result.errors, [])

    def test_unknown_family_fails(self):
        result = gates.gate_families([_case("definitely_not_a_family")])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("definitely_not_a_family", result.errors[0])


if __name__ == "__main__":
    unittest.main()
