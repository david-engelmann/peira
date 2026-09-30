"""Tests for the attack-family registry (peira/families.py)."""

import unittest

from peira.families import (
    FAMILIES,
    FAMILY_IDS,
    FamilyInfo,
    display_name,
    get,
    is_known,
)

EXPECTED_V1 = (
    "state_poisoning",
    "criteria_smuggling",
    "option_order",
    "distractor_flooding",
    "score_anchoring",
    "literal_reading",
    "negation_games",
    "policy_paraphrase",
    "indirection",
    "confidence_spoofing",
)
EXPECTED_TIER1 = (
    "instruction_override",
    "indirect_injection",
    "authority_fabrication",
    "self_advocacy",
    "criteria_order",
    "precedent_stacking",
)
EXPECTED_TIER2 = (
    "contradiction_injection",
    "temporal_numeric_traps",
    "encoding_evasion",
    "abstain_forcing",
)
# Post-v2 families: no cap on family count (David 2026-09-28).
EXPECTED_POST_V2 = (
    "verbosity_inflation",
    "retrieval_poisoning",
    "evidence_positioning",
)


class TestFamilyRegistry(unittest.TestCase):
    def test_family_count(self):
        # No cap on families (David 2026-09-28): assert the known set,
        # not a fixed total.
        self.assertEqual(
            set(FAMILIES),
            set(EXPECTED_V1 + EXPECTED_TIER1 + EXPECTED_TIER2 + EXPECTED_POST_V2),
        )
        self.assertEqual(len(FAMILIES), len(FAMILY_IDS))

    def test_ids_unique_and_well_formed(self):
        self.assertEqual(len(set(FAMILY_IDS)), len(FAMILY_IDS))
        for fid in FAMILY_IDS:
            self.assertRegex(fid, r"^[a-z0-9_]+$")

    def test_canonical_order(self):
        self.assertEqual(
            FAMILY_IDS,
            EXPECTED_V1 + EXPECTED_TIER1 + EXPECTED_TIER2 + EXPECTED_POST_V2,
        )
        self.assertEqual(list(FAMILIES), list(FAMILY_IDS))

    def test_tiers(self):
        for fid in EXPECTED_V1:
            self.assertEqual(FAMILIES[fid].tier, "v1", fid)
        for fid in EXPECTED_TIER1:
            self.assertEqual(FAMILIES[fid].tier, "1", fid)
        for fid in EXPECTED_TIER2:
            self.assertEqual(FAMILIES[fid].tier, "2", fid)

    def test_metadata_complete(self):
        for fid, info in FAMILIES.items():
            self.assertIsInstance(info, FamilyInfo)
            self.assertEqual(info.id, fid)
            self.assertTrue(info.display_name.strip(), fid)
            self.assertTrue(info.description.strip(), fid)
            self.assertTrue(info.mechanism.strip(), fid)
            self.assertTrue(info.anchor.strip(), fid)
            self.assertIn(info.tier, ("v1", "1", "2"), fid)

    def test_display_names_human(self):
        self.assertEqual(display_name("state_poisoning"), "State Poisoning")
        self.assertEqual(display_name("abstain_forcing"), "Abstain Forcing")
        for fid in FAMILY_IDS:
            self.assertNotIn("_", display_name(fid), fid)

    def test_lookup_helpers(self):
        self.assertIs(get("indirection"), FAMILIES["indirection"])
        self.assertIsNone(get("not_a_family"))
        self.assertTrue(is_known("criteria_order"))
        self.assertFalse(is_known("not_a_family"))
        # Unknown ids pass through display_name unchanged.
        self.assertEqual(display_name("custom_fam"), "custom_fam")


if __name__ == "__main__":
    unittest.main()
