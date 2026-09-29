"""Unit tests for scripts/audit_holdout_separation.py (run with: python -m unittest discover tests).

Uses synthetic holdout fixtures only. Never touches the real holdout.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "audit_holdout_separation.py"

FAKE_CASE = {
    "case_id": "synth-h-0001",
    "family": "state_poisoning",
    "primitive": "choice",
    "severity": "low",
    "benign": {"input": {"prompt": "Synthetic holdout prompt about a "
                                   "fictional widget factory with enough "
                                   "length to pass the thirty two char "
                                   "minimum for fingerprinting.",
                         "options": ["a", "b"]},
               "expected_decision": "a"},
    "attacked": {"input": {"prompt": "Synthetic attacked prompt about a "
                                     "fictional widget factory with extra "
                                     "adversarial content appended here.",
                           "options": ["a", "b"]},
                "target_decision": "b"},
}


def _write_holdout(root: Path):
    d = root / "holdout"
    d.mkdir(parents=True)
    (d / "cases.jsonl").write_text(json.dumps(FAKE_CASE) + "\n")
    (d / "CANARY.txt").write_text("deadbeef" * 8 + "\n")
    return d


def _write_public(root: Path):
    d = root / "public"
    d.mkdir(parents=True)
    (d / "README.md").write_text("# Public repo\n\nNothing sensitive.\n")
    (d / "data.jsonl").write_text(
        json.dumps({"case_id": "public-001"}) + "\n")
    return d


class TestHoldoutSeparationAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.holdout = _write_holdout(self.root)
        self.public = _write_public(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--holdout-dir", str(self.holdout),
             "--public-dir", str(self.public)],
            capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout, proc.stderr

    def test_clean_public_passes(self):
        code, out, err = self._run()
        self.assertEqual(code, 0, (out, err))
        self.assertIn("clean", out)

    def test_leaked_case_id_fails(self):
        (self.public / "leak.md").write_text(
            "oops the id synth-h-0001 got pasted here\n")
        code, out, err = self._run()
        self.assertEqual(code, 1, (out, err))
        self.assertIn("SEPARATION VIOLATION", out)
        self.assertIn("leak.md", out)

    def test_leaked_prompt_text_fails(self):
        (self.public / "notes.txt").write_text(
            "Synthetic holdout prompt about a fictional widget factory\n")
        code, out, err = self._run()
        self.assertEqual(code, 1, (out, err))
        self.assertIn("SEPARATION VIOLATION", out)

    def test_leaked_canary_guid_fails(self):
        (self.public / "docs.md").write_text(
            "guid: " + "deadbeef" * 8 + "\n")
        code, out, err = self._run()
        self.assertEqual(code, 1, (out, err))
        self.assertIn("SEPARATION VIOLATION", out)

    def test_mid_prompt_paste_is_caught(self):
        # A paste from the middle of a long prompt (not the head) must
        # be caught by the strided 40-char needles.
        long_prompt = " ".join(f"word{i:04d}" for i in range(200))
        case = dict(FAKE_CASE)
        case["benign"] = {"input": {"prompt": long_prompt,
                                    "options": ["a", "b"]},
                          "expected_decision": "a"}
        (self.holdout / "cases.jsonl").write_text(json.dumps(case) + "\n")
        # Paste chars from the middle (offset ~300).
        mid = " ".join(long_prompt.split()[60:80])
        (self.public / "leak.txt").write_text(f"stolen: {mid}\n")
        code, out, err = self._run()
        self.assertEqual(code, 1, (out, err))
        self.assertIn("SEPARATION VIOLATION", out)

    def test_misaligned_short_paste_is_caught(self):
        # A short paste that straddles the old non-overlapping window
        # boundaries must still be caught. With stride 40, a 50-char
        # paste at offset 20 contains no full 40-char window and was
        # missed; stride 10 guarantees any 50+ char paste contains a
        # full window regardless of alignment.
        prompt = ("You are a helpful assistant. The user asks about "
                  "investment advice for retirement planning with "
                  "specific questions about 401k allocations.")
        case = dict(FAKE_CASE)
        case["benign"] = {"input": {"prompt": prompt,
                                    "options": ["a", "b"]},
                          "expected_decision": "a"}
        (self.holdout / "cases.jsonl").write_text(json.dumps(case) + "\n")
        # 50-char slice starting at offset 20: straddles windows.
        misaligned = prompt[20:70]
        self.assertEqual(len(misaligned), 50)
        (self.public / "notes.md").write_text(
            f"Discussion. The key phrase was: \"{misaligned}\" in context.\n")
        code, out, err = self._run()
        self.assertEqual(code, 1, (out, err))
        self.assertIn("SEPARATION VIOLATION", out)

    def test_sub40_char_fragment_is_caught(self):
        # A 39-char fragment inside a single 40-char window must be
        # caught by the 20-char strided needles (stride 5). Fragments
        # under 20 chars are below the documented detection floor.
        prompt = ("You are a helpful assistant. The user asks about "
                  "investment advice for retirement planning with "
                  "specific questions about 401k allocations.")
        case = dict(FAKE_CASE)
        case["benign"] = {"input": {"prompt": prompt,
                                    "options": ["a", "b"]},
                          "expected_decision": "a"}
        (self.holdout / "cases.jsonl").write_text(json.dumps(case) + "\n")
        # 39-char fragment: fits inside one 40-char window.
        fragment = prompt[5:44]
        self.assertEqual(len(fragment), 39)
        (self.public / "frag.md").write_text(f"Note: {fragment}\n")
        code, out, err = self._run()
        self.assertEqual(code, 1, (out, err))
        self.assertIn("SEPARATION VIOLATION", out)

    def test_malformed_variant_does_not_crash(self):
        # A row with a non-dict variant must not crash the audit.
        bad = {"case_id": "bad-001", "benign": "not-a-dict"}
        (self.holdout / "cases.jsonl").write_text(
            json.dumps(bad) + "\n" + json.dumps(FAKE_CASE) + "\n")
        code, out, err = self._run()
        # Should complete (0=clean or 1=violation), not crash (2=usage).
        # Must not emit a traceback.
        self.assertIn(code, (0, 1), (out, err))
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)

    def test_non_dict_row_does_not_crash(self):
        # A JSON row that is not an object (list, string) must not crash.
        (self.holdout / "cases.jsonl").write_text(
            "[1,2,3]\n" + json.dumps(FAKE_CASE) + "\n")
        code, out, err = self._run()
        self.assertIn(code, (0, 1), (out, err))
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)

    def test_output_never_prints_holdout_content(self):
        # Even on violation, the output must not contain holdout IDs,
        # prompt text, or GUIDs.
        (self.public / "leak.md").write_text(
            "oops the id synth-h-0001 got pasted here\n")
        (self.public / "leak2.md").write_text(
            "guid: " + "deadbeef" * 8 + "\n")
        code, out, err = self._run()
        self.assertEqual(code, 1)
        combined = out + err
        self.assertNotIn("synth-h-0001", combined)
        self.assertNotIn("deadbeef" * 8, combined)
        self.assertNotIn("fictional widget factory", combined)

    def test_missing_dirs_are_usage_error(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--holdout-dir", "/nonexistent",
             "--public-dir", str(self.public)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
