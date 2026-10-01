"""Tests for the family/doc consistency check (scripts/check_families.py)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_families  # noqa: E402


class TestCheckFamilies(unittest.TestCase):
    def test_live_repo_agrees(self):
        problems = check_families.check()
        self.assertEqual(problems, [])

    def _taxonomy_copy(self, tmp: Path, transform) -> Path:
        src = REPO_ROOT / "docs" / "Taxonomy.md"
        dst = tmp / "docs" / "Taxonomy.md"
        dst.write_text(transform(src.read_text(encoding="utf-8")),
                       encoding="utf-8")
        return dst

    def _check_against(self, taxonomy: Path):
        # check() is rooted at the script location; monkeypatch the root.
        orig = check_families.REPO_ROOT
        check_families.REPO_ROOT = taxonomy.parent.parent
        try:
            return check_families.check()
        finally:
            check_families.REPO_ROOT = orig

    def test_missing_family_detected(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "docs").mkdir()
            tax = self._taxonomy_copy(
                tmp,
                lambda s: s.replace(
                    "11. **instruction_override** (Tier 1)",
                    "11. **instruction_override_missing** (Tier 1)",
                ),
            )
            problems = self._check_against(tax)
            self.assertTrue(
                any("instruction_override" in p and "docs/Taxonomy.md" in p
                    for p in problems),
                problems,
            )
            self.assertTrue(
                any("instruction_override_missing" in p for p in problems),
                problems,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wrong_tier_marker_detected(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "docs").mkdir()
            tax = self._taxonomy_copy(
                tmp,
                lambda s: s.replace(
                    "11. **instruction_override** (Tier 1)",
                    "11. **instruction_override** (Tier 2)",
                ),
            )
            problems = self._check_against(tax)
            self.assertTrue(
                any("instruction_override" in p and "Tier" in p
                    for p in problems),
                problems,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_documented_families_parser(self):
        documented = check_families.documented_families(
            REPO_ROOT / "docs" / "Taxonomy.md"
        )
        # No cap on families (David 2026-09-28).
        self.assertEqual(len(documented), 26)
        numbers = [n for n, _, _ in documented]
        self.assertEqual(numbers, list(range(1, 27)))
        tiers = {fam: tier for _, fam, tier in documented}
        self.assertEqual(tiers["state_poisoning"], "v1")
        self.assertEqual(tiers["instruction_override"], "1")
        self.assertEqual(tiers["abstain_forcing"], "2")
        self.assertEqual(tiers["verbosity_inflation"], "1")
        self.assertEqual(tiers["retrieval_poisoning"], "1")
        self.assertEqual(tiers["evidence_positioning"], "1")
        self.assertEqual(tiers["crosslingual_shift"], "1")
        self.assertEqual(tiers["judge_sycophancy"], "1")

    def test_entry_prose_drift_detected(self):
        # A meaning change to one family's entry must fail the check.
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "docs").mkdir()
            tax = self._taxonomy_copy(
                tmp,
                lambda text: text.replace(
                    "payload buried behind multi-hop indirection",
                    "payload buried behind multi-hop indirection (reworded)",
                ),
            )
            problems = self._check_against(tax)
            self.assertTrue(
                any("indirection" in p and "changed" in p for p in problems),
                f"expected a drift problem, got: {problems}",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_entry_hashes_cover_all_families(self):
        self.assertEqual(
            set(check_families.EXPECTED_ENTRY_HASHES),
            set(check_families.FAMILIES),
        )


if __name__ == "__main__":
    unittest.main()
