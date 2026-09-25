"""Suite registry tests (run with: python -m unittest discover tests).

Every SUITE_DIRS entry must resolve to a real suite directory, and every
suite directory that ships a manifest.json must verify clean against it.
This pins the version-wiring: a future refactor that mispoints a suite
(e.g. at dataset/v1 instead of dataset/v1/cases, where the flat manifest
lives) breaks these tests before it breaks runs.

dataset/trial-demo ships no manifest by design — it is quickstart
scaffolding, explicitly exempt from gates (see docs/Dataset.md). The
runner binds it explicitly unbound (manifest_sha256 == ""), and that
intended state is pinned here so it can only change deliberately.
"""

import unittest
from pathlib import Path

from peira.dataset import verify_manifest
from peira.runner import SUITE_DIRS

ROOT = Path(__file__).resolve().parents[1]


class TestSuiteDirs(unittest.TestCase):
    def test_every_suite_resolves_to_a_directory(self):
        for suite, rel in SUITE_DIRS.items():
            with self.subTest(suite=suite):
                self.assertTrue(
                    (ROOT / rel).is_dir(),
                    f"suite {suite!r} points at {rel}, which is not a directory",
                )

    def test_manifests_verify(self):
        for suite, rel in SUITE_DIRS.items():
            suite_dir = ROOT / rel
            with self.subTest(suite=suite):
                manifest_path = suite_dir / "manifest.json"
                if manifest_path.is_file():
                    self.assertEqual(
                        verify_manifest(suite_dir), [],
                        f"manifest in {rel} does not verify",
                    )
                else:
                    # Only trial-demo may ship no manifest (explicitly
                    # unbound by design). Any other suite without a manifest
                    # is a wiring bug.
                    self.assertEqual(
                        suite, "trial-demo",
                        f"suite {suite!r} ({rel}) ships no manifest",
                    )


if __name__ == "__main__":
    unittest.main()
