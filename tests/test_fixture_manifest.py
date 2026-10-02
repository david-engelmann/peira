"""Coverage-pinning test for the test-fixture manifest.

The manifest (tests/fixtures/manifest.json) records, per fixture file,
its purpose, family/area, expected gate outcome, and the EXACT set of
test files that reference it. This test pins that record: it fails when
a fixture is added without a manifest entry, removed without updating
the manifest, left unreferenced by every test, or gains/loses a
referencing test without the manifest being updated (run
scripts/regen_fixture_manifest.py to rebuild the skeleton, then fill in
the hand-written fields).

What "referenced" means: a tests/test_*.py file (other than this one,
which is not a fixture consumer) references a fixture when its source
contains the fixture's path segments under tests/fixtures, either as a
slash-joined path (``fixtures/g9_paraphrase_pairs.jsonl``) or as adjacent
path segments (``Path(__file__).parent / "fixtures" /
"g9_paraphrase_pairs.jsonl"``, ``os.path.join(...,
"fixtures", "judge_validation_sample.jsonl")``). Fixtures consumed via
their whole directory -- loaded by load_conversation_cases /
run_conversation_gates, which glob ``*.jsonl`` -- count as referenced by
any test mentioning the directory path (``fixtures/conversational``).
The detection rule lives in scripts/regen_fixture_manifest.py and is
shared verbatim here.

Why the invariant is "exact recorded set", not "exactly once": two
fixtures are each consumed by exactly one test file, and the manifest
records that singleton set, so for them this IS an exactly-once pin.
But tests/fixtures/conversational/cases.jsonl is a small shared corpus
legitimately loaded by three test files (loader/gate tests, metrics
tests, suite-separation tests) through the same directory loader;
forcing exactly-once there would forbid a legitimate pattern. The
recorded-set invariant pins all three against silent drift instead.

All read-only and deterministic: no shared mutable state, xdist-safe.
"""

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import regen_fixture_manifest  # noqa: E402


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class TestFixtureManifest(unittest.TestCase):
    def test_every_fixture_file_has_manifest_entry(self):
        """A new fixture without a manifest entry fails here."""
        manifest = _load_manifest()
        on_disk = {str(p) for p in regen_fixture_manifest.iter_fixture_files()}
        in_manifest = set(manifest["fixtures"])
        missing = sorted(on_disk - in_manifest)
        self.assertEqual(
            missing, [],
            "fixture files without a manifest entry: "
            f"{missing} (run scripts/regen_fixture_manifest.py)",
        )

    def test_every_manifest_entry_points_at_real_file(self):
        """A manifest entry for a deleted fixture fails here."""
        manifest = _load_manifest()
        dangling = sorted(
            key for key in manifest["fixtures"]
            if not (FIXTURES_DIR / key).is_file()
        )
        self.assertEqual(
            dangling, [],
            f"manifest entries with no file on disk: {dangling}",
        )

    def test_referenced_by_sets_match_detected(self):
        """The recorded referencing-test set must equal reality, exactly.

        Fails when a fixture gains or loses a referencing test without
        the manifest being regenerated -- this is the drift pin.
        """
        manifest = _load_manifest()
        detected = regen_fixture_manifest.detect_references()
        problems = []
        for key in sorted(manifest["fixtures"]):
            recorded = manifest["fixtures"][key].get("referenced_by", [])
            actual = detected.get(key, [])
            if recorded != actual:
                problems.append(
                    f"{key}: manifest records {recorded}, "
                    f"suite actually references from {actual}"
                )
        self.assertEqual(
            problems, [],
            "manifest referenced_by drift:\n" + "\n".join(problems)
            + "\n(run scripts/regen_fixture_manifest.py)",
        )

    def test_no_orphan_fixtures(self):
        """Every fixture must be referenced by at least one test."""
        detected = regen_fixture_manifest.detect_references()
        orphans = sorted(
            str(p) for p in regen_fixture_manifest.iter_fixture_files()
            if not detected.get(str(p))
        )
        self.assertEqual(
            orphans, [],
            f"fixtures no test references (fixture rot): {orphans}",
        )

    def test_referenced_by_entries_are_real_test_files(self):
        """Manifest must not pin references to files that do not exist."""
        manifest = _load_manifest()
        bogus = sorted(
            f"{key} -> {t}"
            for key, entry in manifest["fixtures"].items()
            for t in entry.get("referenced_by", [])
            if not (REPO_ROOT / t).is_file()
            or Path(t).name == regen_fixture_manifest.SELF_TEST
        )
        self.assertEqual(
            bogus, [],
            f"manifest references non-test files: {bogus}",
        )


if __name__ == "__main__":
    unittest.main()
