"""Unit tests for scripts/holdout_query_log.py (run with: python -m unittest discover tests).

Tests run against a temporary copy of the log so the real
docs/Holdout-Query-Log.md is never touched.
"""

import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "holdout_query_log.py"
REAL_LOG = REPO / "docs" / "Holdout-Query-Log.md"


def _today():
    """Today as YYYY-MM-DD: the holdout log rotates on the wall clock,
    so tests that interact with rotations must be date-relative, not
    hardcoded (a hardcoded 'rotation date' rots at the next midnight)."""
    return date.today().isoformat()


def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat()


class TestHoldoutQueryLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "Holdout-Query-Log.md"
        # Point the script at the temp log by copying the script and
        # rewriting LOG_PATH. Simpler: copy real log content, then run
        # the script with a patched LOG_PATH via sitecustomize-style
        # env var. Cleanest: copy script to tmp and patch the path.
        src = SCRIPT.read_text()
        patched = src.replace(
            'LOG_PATH = Path(__file__).parent.parent / "docs" / "Holdout-Query-Log.md"',
            f'LOG_PATH = Path(r"{self.log}")')
        self.script = Path(self.tmp.name) / "holdout_query_log.py"
        self.script.write_text(patched)
        self.log.write_text(REAL_LOG.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        proc = subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout + proc.stderr

    def test_status_empty(self):
        code, out = self._run("status")
        self.assertEqual(code, 0, out)
        self.assertIn("0 total executions", out)

    def test_log_and_status(self):
        code, out = self._run("log", "--adapter", "demo-adapter 1.0",
                              "--date", "2026-09-28")
        self.assertEqual(code, 0, out)
        self.assertIn("execution 1 of 12", out)
        code, out = self._run("status", "--adapter", "demo-adapter 1.0",
                              "--year", "2026")
        self.assertIn("1 of 12 used", out)
        self.assertIn("11 remaining", out)

    def test_budget_exhaustion_blocks(self):
        for i in range(12):
            code, _ = self._run("log", "--adapter", "busy-adapter 2.0",
                                "--date", "2026-09-28")
            self.assertEqual(code, 0)
        code, out = self._run("log", "--adapter", "busy-adapter 2.0",
                              "--date", "2026-09-29")
        self.assertEqual(code, 1, out)
        self.assertIn("exhausted", out)

    def test_new_year_resets(self):
        code, _ = self._run("log", "--adapter", "yearly 1.0",
                            "--date", "2025-12-31")
        self.assertEqual(code, 0)
        # 2026 is a new budget year; the script uses --date's year.
        code, out = self._run("log", "--adapter", "yearly 1.0",
                              "--date", "2026-01-01")
        self.assertEqual(code, 0, out)
        self.assertIn("execution 1 of 12 in 2026", out)

    def test_rotation_logged(self):
        code, out = self._run("rotation", "--kind", "scheduled")
        self.assertEqual(code, 0, out)
        self.assertIn("scheduled", out)
        code, out = self._run("status")
        self.assertIn("1 rotations logged", out)

    def test_log_reveals_no_case_details(self):
        self._run("log", "--adapter", "quiet 1.0", "--date", "2026-09-28")
        text = self.log.read_text()
        # No real case identifiers or blind bundle IDs may appear.
        for banned in ("v1-b-", "v1-p-", "expected_decision",
                       "target_decision"):
            self.assertNotIn(banned, text)

    def test_real_log_untouched(self):
        before = REAL_LOG.read_text()
        self._run("log", "--adapter", "should-not-appear 9.9",
                  "--date", "2026-09-28")
        self.assertEqual(REAL_LOG.read_text(), before)
        self.assertNotIn("should-not-appear", before)

    def test_invalid_date_rejected(self):
        code, out = self._run("log", "--adapter", "baddate 1.0",
                              "--date", "2026-99-99")
        self.assertEqual(code, 1, out)
        self.assertIn("bad --date", out)

    def test_future_date_rejected(self):
        code, out = self._run("log", "--adapter", "future 1.0",
                              "--date", "2099-01-01")
        self.assertEqual(code, 1, out)
        self.assertIn("bad --date", out)

    def test_empty_adapter_rejected(self):
        code, out = self._run("log", "--adapter", "   ",
                              "--date", "2026-09-28")
        self.assertEqual(code, 1, out)
        self.assertIn("--adapter must not be empty", out)

    def test_angle_brackets_in_adapter_rejected(self):
        # An adapter name containing <!-- would let the HTML-comment
        # strip in _read_entries() hide prior entries and bypass the
        # 12/year budget. Reject < and > outright.
        for hostile in ("victim-adapter <!-- ", "evil <adapter>",
                        "adapter > name"):
            code, out = self._run("log", "--adapter", hostile,
                                  "--date", "2026-09-28")
            self.assertEqual(code, 1, out)
            self.assertIn("must not contain '<' or '>'", out)

    def test_first_entry_removes_placeholder(self):
        code, out = self._run("log", "--adapter", "first 1.0",
                              "--date", "2026-09-28")
        self.assertEqual(code, 0, out)
        text = self.log.read_text()
        self.assertNotIn("No blind re-executions have been run yet.", text)
        self.assertIn("first 1.0", text)
        self.assertIn("## 2026", text)

    def test_rotation_resets_budget(self):
        for _ in range(12):
            code, _ = self._run("log", "--adapter", "rot 1.0",
                                "--date", _yesterday())
            self.assertEqual(code, 0)
        # Exhausted.
        code, _ = self._run("log", "--adapter", "rot 1.0",
                            "--date", _yesterday())
        self.assertEqual(code, 1)
        # Rotation resets the budget.
        code, out = self._run("rotation", "--kind", "scheduled")
        self.assertEqual(code, 0, out)
        # Log with the rotation date (pre-rotation dates are rejected).
        code, out = self._run("log", "--adapter", "rot 1.0",
                              "--date", _today())
        self.assertEqual(code, 0, out)
        self.assertIn("execution 1 of 12", out)

    def test_backdated_entry_after_rotation_counts(self):
        # A same-year backdated entry logged AFTER a rotation must count
        # toward the post-rotation budget (not vanish). Note: dates
        # before the rotation are now rejected (see next test), so this
        # uses a date AFTER the rotation.
        code, out = self._run("log", "--adapter", "backdate 1.0",
                              "--date", _yesterday())
        self.assertEqual(code, 0, out)
        code, out = self._run("rotation", "--kind", "scheduled")
        self.assertEqual(code, 0, out)
        # Log with the rotation date (not before it).
        code, out = self._run("log", "--adapter", "backdate 1.0",
                              "--date", _today())
        self.assertEqual(code, 0, out)
        # Must count: status shows 1 used (the pre-rotation entry is
        # excluded, the post-rotation entry counts).
        code, out = self._run("status", "--adapter", "backdate 1.0",
                              "--year", str(date.today().year))
        self.assertEqual(code, 0, out)
        self.assertIn("1 of 12 used", out)

    def test_pre_rotation_backdate_rejected(self):
        # A --date before the most recent rotation is rejected: it would
        # evade the post-rotation budget (especially cross-year).
        code, out = self._run("log", "--adapter", "reject 1.0",
                              "--date", "2026-09-28")
        self.assertEqual(code, 0, out)
        code, out = self._run("rotation", "--kind", "scheduled")
        self.assertEqual(code, 0, out)
        # Backdate to before the rotation: rejected.
        code, out = self._run("log", "--adapter", "reject 1.0",
                              "--date", "2026-09-28")
        self.assertEqual(code, 1)
        self.assertIn("before the most recent rotation", out)


if __name__ == "__main__":
    unittest.main()
