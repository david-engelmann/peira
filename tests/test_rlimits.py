"""Unit tests for S-2: rlimit backstops and their CLI validation.

Covers ``_apply_rlimits`` (no-op, rejection, and the fractional-value
rounding that used to truncate sub-second values to a SIGKILL-inducing
zero limit) and the ``--rlimit-*`` CLI validation branches. ``setrlimit``
is mocked so the tests never touch the test process's own limits.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from peira.cli import EXIT_USER_ERROR, build_parser, cmd_run
from peira.runner import _apply_rlimits

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestApplyRlimits(unittest.TestCase):
    def test_all_none_is_noop(self):
        with mock.patch("resource.setrlimit") as m:
            _apply_rlimits(None, None, None)
        m.assert_not_called()

    def test_rejects_non_positive(self):
        for kwargs in (
            {"cpu_seconds": 0},
            {"cpu_seconds": -1.5},
            {"as_mb": 0},
            {"as_mb": -10},
            {"fsize_mb": 0},
            {"fsize_mb": -0.5},
        ):
            args = {"cpu_seconds": None, "as_mb": None, "fsize_mb": None}
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), mock.patch("resource.setrlimit"):
                with self.assertRaises(ValueError):
                    _apply_rlimits(**args)

    def test_fractional_cpu_seconds_round_up(self):
        # Regression: int(0.5) truncated to 0, and RLIMIT_CPU (0, 0)
        # kills the process immediately. math.ceil gives (1, 1).
        import resource

        with mock.patch("resource.setrlimit") as m:
            _apply_rlimits(0.5, None, None)
        m.assert_called_once_with(resource.RLIMIT_CPU, (1, 1))

    def test_fractional_mb_values_round_up(self):
        import resource

        with mock.patch("resource.setrlimit") as m:
            _apply_rlimits(None, 0.5, None)
        m.assert_called_once_with(resource.RLIMIT_AS, (524288, 524288))
        with mock.patch("resource.setrlimit") as m:
            _apply_rlimits(None, None, 0.5)
        m.assert_called_once_with(resource.RLIMIT_FSIZE, (524288, 524288))

    def test_integer_values_pass_through(self):
        import resource

        with mock.patch("resource.setrlimit") as m:
            _apply_rlimits(60, 1024, 100)
        m.assert_has_calls(
            [
                mock.call(resource.RLIMIT_CPU, (60, 60)),
                mock.call(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2),
                mock.call(resource.RLIMIT_FSIZE, (100 * 1024 * 1024,) * 2),
            ]
        )
        self.assertEqual(m.call_count, 3)


class TestRlimitCliValidation(unittest.TestCase):
    def _run(self, extra):
        parser = build_parser()
        with TemporaryDirectory() as tmp:
            argv = [
                "run",
                "--adapter",
                "mock",
                "--suite",
                "trial-demo",
                "--out",
                tmp,
            ] + extra
            args = parser.parse_args(argv)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cmd_run(args)
        return rc, err.getvalue()

    def test_zero_cpu_seconds_rejected(self):
        rc, err = self._run(["--rlimit-cpu-seconds", "0"])
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("--rlimit-cpu-seconds must be > 0", err)

    def test_negative_as_mb_rejected(self):
        rc, err = self._run(["--rlimit-as-mb", "-5"])
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("--rlimit-as-mb must be > 0", err)

    def test_negative_fsize_mb_rejected(self):
        rc, err = self._run(["--rlimit-fsize-mb", "-0.5"])
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("--rlimit-fsize-mb must be > 0", err)

    def test_error_strings_match_troubleshooting(self):
        # House rule: every user-facing CLI error string appears in
        # docs/Troubleshooting.md. Check the flag names are documented.
        doc = (REPO_ROOT / "docs" / "Troubleshooting.md").read_text()
        for flag in ("--rlimit-cpu-seconds", "--rlimit-as-mb", "--rlimit-fsize-mb"):
            self.assertIn(flag, doc)


if __name__ == "__main__":
    unittest.main()
