"""Tests for the trial-manifest version pin check (scripts/check_trial_version_pins.py)."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_trial_version_pins  # noqa: E402


class TestTrialVersionPins(unittest.TestCase):
    def test_live_repo_agrees(self):
        manifest_version = json.loads(
            (REPO_ROOT / "dataset" / "trial" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )["dataset_version"]
        version, problems = check_trial_version_pins.check()
        self.assertEqual(version, manifest_version)
        self.assertEqual(problems, [])

    def _sandbox_copy(self) -> Path:
        """Copy the manifest plus every pinned file into a temp dir."""
        tmp = Path(tempfile.mkdtemp())
        rels = [rel for rel, _ in check_trial_version_pins.PINS]
        rels.append("dataset/trial/manifest.json")
        for rel in rels:
            src = REPO_ROOT / rel
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        return tmp

    def _check_in(self, tmp: Path):
        orig = check_trial_version_pins.REPO_ROOT
        check_trial_version_pins.REPO_ROOT = tmp
        try:
            _, problems = check_trial_version_pins.check()
            return problems
        finally:
            check_trial_version_pins.REPO_ROOT = orig

    def _bump_manifest(self, tmp: Path, version: str):
        path = tmp / "dataset" / "trial" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["dataset_version"] = version
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_stale_pins_all_detected(self):
        tmp = self._sandbox_copy()
        try:
            self._bump_manifest(tmp, "9.9.9")
            problems = self._check_in(tmp)
            self.assertEqual(len(problems), len(check_trial_version_pins.PINS))
            for rel, _ in check_trial_version_pins.PINS:
                self.assertTrue(
                    any(rel in p and "9.9.9" in p for p in problems),
                    problems,
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_pin_detected(self):
        tmp = self._sandbox_copy()
        try:
            # Derive the pin text live: hardcoding today's version would make
            # this replace() a no-op (and the test a false red) after a bump.
            version = check_trial_version_pins.manifest_version()
            glossary = tmp / "docs" / "Glossary.md"
            glossary.write_text(
                glossary.read_text(encoding="utf-8").replace(
                    f"Manifest `{version}`", "Manifest `VERSION`"
                ),
                encoding="utf-8",
            )
            problems = self._check_in(tmp)
            self.assertTrue(
                any(
                    "docs/Glossary.md" in p and "no trial-manifest version pin" in p
                    for p in problems
                ),
                problems,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_file_detected(self):
        tmp = self._sandbox_copy()
        try:
            (tmp / "dataset" / "README.md").unlink()
            problems = self._check_in(tmp)
            self.assertTrue(
                any("dataset/README.md" in p and "missing" in p for p in problems),
                problems,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_manifest_reported(self):
        tmp = self._sandbox_copy()
        try:
            (tmp / "dataset" / "trial" / "manifest.json").unlink()
            problems = self._check_in(tmp)
            self.assertEqual(len(problems), 1)
            self.assertIn("manifest", problems[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_malformed_manifest_version_reported(self):
        tmp = self._sandbox_copy()
        try:
            self._bump_manifest(tmp, "not-a-version")
            problems = self._check_in(tmp)
            self.assertEqual(len(problems), 1)
            self.assertIn("dataset_version", problems[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
