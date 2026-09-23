"""peira validate: malformed JSON is an exit-1 user error with file:line
(never a traceback), and case files are read as UTF-8 on every platform.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from peira.cli import EXIT_USER_ERROR, cmd_validate

REPO_ROOT = Path(__file__).resolve().parents[1]


def _case(**over):
    d = {
        "case_id": "c1",
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": "low",
        "benign": {"input": {"q": "caf\u00e9"}, "expected_decision": "a"},
        "attacked": {"input": {"q": "caf\u00e9!"}, "target_decision": "b"},
        "notes": "na\u00efve caf\u00e9 notes",
    }
    d.update(over)
    return d


def _write(tmp, name, text):
    p = Path(tmp) / name
    p.write_bytes(text.encode("utf-8"))
    return p


class TestValidateMalformedJson(unittest.TestCase):
    def _run(self, tmp):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cmd_validate(argparse.Namespace(dataset=tmp))
        return rc, out.getvalue(), err.getvalue()

    def test_malformed_json_is_exit_1_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "c.jsonl",
                   json.dumps(_case()) + "\nnot json at all\n")
            rc, out, err = self._run(tmp)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("c.jsonl:2: invalid JSON", out)
            self.assertIn("validated 2 cases, 1 invalid", out)
            self.assertNotIn("Traceback", out + err)

    def test_scalar_json_line_is_user_error_not_crash(self):
        # Valid JSON, wrong shape: a bare scalar used to crash
        # _validate_case_dict_py outright (d["case_id"] on an int).
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "c.jsonl", "5\n")
            rc, out, err = self._run(tmp)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("missing required key: case_id", out)
            self.assertNotIn("Traceback", out + err)
        with tempfile.TemporaryDirectory() as tmp:
            bad = _case(case_id=42)
            _write(tmp, "c.jsonl", json.dumps(bad) + "\n")
            rc, out, _ = self._run(tmp)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("bad case_id: expected string", out)

    def test_valid_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "c.jsonl", json.dumps(_case()) + "\n")
            rc, out, _ = self._run(tmp)
            self.assertEqual(rc, 0)
            self.assertIn("validated 1 cases, 0 invalid", out)


class TestCaseFilesReadAsUtf8(unittest.TestCase):
    """Regression: case files must decode as UTF-8 even where the platform
    default can't (Windows cp1252, POSIX C locale).

    Runs the real CLI in a subprocess under LC_ALL=C with UTF-8 mode off,
    so the locale default is ASCII: without the explicit encoding="utf-8"
    the read fails (UnicodeDecodeError) or mojibakes.
    """

    def _c_locale_env(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "python") + os.pathsep + env.get(
            "PYTHONPATH", "")
        env["LC_ALL"] = "C"
        env["PYTHONUTF8"] = "0"
        return env

    def test_validate_reads_utf8_under_c_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "c.jsonl", json.dumps(_case(), ensure_ascii=False) + "\n")
            r = subprocess.run(
                [sys.executable, "-m", "peira.cli", "validate",
                 "--dataset", tmp],
                capture_output=True, text=True, env=self._c_locale_env(),
                cwd=REPO_ROOT)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("validated 1 cases, 0 invalid", r.stdout)

    def test_load_cases_reads_utf8_under_c_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "c.jsonl", json.dumps(_case(), ensure_ascii=False) + "\n")
            # The child source stays ASCII-only (\\u escapes): under
            # LC_ALL=C the -c argument itself can't carry non-ASCII.
            code = (
                "from peira.runner import load_cases;"
                f"cases = load_cases(__import__('pathlib').Path({tmp!r}));"
                "c = cases[0];"
                "assert c.case_id == 'c1', c.case_id;"
                "assert c.benign.input == {'q': 'caf\\u00e9'}, c.benign.input;"
                "assert c.notes == 'na\\u00efve caf\\u00e9 notes', c.notes;"
                "print('utf8 ok')"
            )
            r = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, env=self._c_locale_env(),
                cwd=REPO_ROOT)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("utf8 ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
