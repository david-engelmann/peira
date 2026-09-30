"""Unit tests for the named ResourceGovernor (R-03, Program A).

Covers validation, the child-process nproc fork-bomb guard, the
"last words" death handlers, and the CLI validation for
``--rlimit-nproc``. ``setrlimit`` is never called in the test process
itself: apply/child tests run in throwaway ``python -c`` subprocesses
(rlimits are inherited and cannot be raised again, so touching them
in-process would poison the test runner).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from peira.cli import EXIT_USER_ERROR, build_parser, cmd_run
from peira.resource_governor import (
    ResourceGovernor,
    get_active_governor,
    reset_active_governor,
    set_active_governor,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run_child(script: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "python")
    return subprocess.run(
        [PY, "-c", script], capture_output=True, text=True, env=env, timeout=60
    )


class TestValidation(unittest.TestCase):
    def test_all_none_is_not_configured(self):
        g = ResourceGovernor()
        self.assertFalse(g.configured)
        # apply() with nothing configured is a no-op (never touches rlimits)
        with mock.patch("resource.setrlimit") as m:
            g.apply()
        m.assert_not_called()

    def test_rejects_non_positive(self):
        for kwargs in (
            {"cpu_seconds": 0},
            {"cpu_seconds": -1.5},
            {"as_mb": 0},
            {"as_mb": -10},
            {"nproc": 0},
            {"nproc": -3},
            {"fsize_mb": 0},
            {"fsize_mb": -0.5},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ResourceGovernor(**kwargs)

    def test_nproc_must_be_int_sized(self):
        # nproc is a process count: 1 is the smallest sane value.
        with self.assertRaises(ValueError):
            ResourceGovernor(nproc=0)


class TestApplyInChild(unittest.TestCase):
    def test_apply_sets_cpu_as_fsize(self):
        proc = _run_child(
            "import resource\n"
            "from peira.resource_governor import ResourceGovernor\n"
            "ResourceGovernor(cpu_seconds=60, as_mb=1024, "
            "fsize_mb=100).apply()\n"
            "print(resource.getrlimit(resource.RLIMIT_CPU))\n"
            "print(resource.getrlimit(resource.RLIMIT_AS))\n"
            "print(resource.getrlimit(resource.RLIMIT_FSIZE))\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(lines[0], "(60, 60)")
        self.assertEqual(lines[1], f"({1024 * 1024 * 1024}, {1024 * 1024 * 1024})")
        self.assertEqual(lines[2], f"({100 * 1024 * 1024}, {100 * 1024 * 1024})")

    def test_apply_never_sets_nproc_on_current_process(self):
        # RLIMIT_NPROC counts per UID, not per process: applying it to
        # the runner would throttle the operator's whole session. The
        # governor must leave the current process's nproc alone.
        proc = _run_child(
            "import resource\n"
            "from peira.resource_governor import ResourceGovernor\n"
            "before = resource.getrlimit(resource.RLIMIT_NPROC)\n"
            "ResourceGovernor(nproc=8).apply()\n"
            "after = resource.getrlimit(resource.RLIMIT_NPROC)\n"
            "print(before == after)\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "True")

    def test_child_preexec_applies_nproc(self):
        proc = _run_child(
            "import resource, subprocess, sys, os\n"
            "from peira.resource_governor import ResourceGovernor\n"
            "gov = ResourceGovernor(nproc=16)\n"
            "env = dict(os.environ)\n"
            "env['PYTHONPATH'] = os.environ['PYTHONPATH']\n"
            "p = subprocess.run(\n"
            "    [sys.executable, '-c',\n"
            "     'import resource; print(resource.getrlimit('\n"
            "     'resource.RLIMIT_NPROC))'],\n"
            "    capture_output=True, text=True, env=env,\n"
            "    preexec_fn=gov.child_preexec())\n"
            "print(p.stdout.strip())\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "(16, 16)")

    def test_fractional_values_round_up(self):
        proc = _run_child(
            "import resource\n"
            "from peira.resource_governor import ResourceGovernor\n"
            "ResourceGovernor(cpu_seconds=0.5).apply()\n"
            "print(resource.getrlimit(resource.RLIMIT_CPU))\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Regression: int(0.5) truncated to 0, and RLIMIT_CPU (0, 0)
        # kills the process immediately. math.ceil gives (1, 1).
        self.assertEqual(proc.stdout.strip(), "(1, 1)")

    def test_snapshot_reports_current_limits(self):
        g = ResourceGovernor(cpu_seconds=30)
        snap = g.snapshot()
        # Keys name the rlimit in native units (seconds/bytes/count),
        # not the constructor's MB units.
        self.assertIn("cpu", snap)
        self.assertIn("as_bytes", snap)
        self.assertIn("nproc", snap)
        self.assertIn("fsize_bytes", snap)
        self.assertIn("soft", snap["cpu"])
        self.assertIn("hard", snap["cpu"])


class TestDeathHandlers(unittest.TestCase):
    def test_sigterm_writes_last_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "last_words.jsonl")
            proc = _run_child(
                "import os, signal, time\n"
                "from peira.resource_governor import ResourceGovernor\n"
                "ResourceGovernor().install_death_handlers("
                f"{path!r})\n"
                "os.kill(os.getpid(), signal.SIGTERM)\n"
                "time.sleep(5)\n"  # never reached
            )
            # Killed by SIGTERM: negative returncode is the convention.
            self.assertEqual(proc.returncode, -signal.SIGTERM, proc.stderr)
            record = json.loads(Path(path).read_text().strip())
            self.assertEqual(record["event"], "peira_last_words")
            self.assertEqual(record["signal"], "SIGTERM")
            self.assertEqual(record["signum"], signal.SIGTERM)
            self.assertIn("pid", record)
            self.assertIn("ts", record)

    def test_sigkill_cannot_be_caught(self):
        # Documents the diagnostic boundary: a SIGKILL death leaves no
        # last-words record. (No test process is actually killed here;
        # the point is that install_death_handlers only arms SIGTERM
        # and SIGINT.)
        with mock.patch("signal.signal") as m:
            ResourceGovernor().install_death_handlers("/tmp/x.jsonl")
        armed = {c.args[0] for c in m.call_args_list}
        self.assertIn(signal.SIGTERM, armed)
        self.assertIn(signal.SIGINT, armed)
        self.assertNotIn(signal.SIGKILL, armed)


class TestActiveGovernor(unittest.TestCase):
    def test_set_get_reset_roundtrip(self):
        g = ResourceGovernor(nproc=32)
        self.assertIsNone(get_active_governor())
        token = set_active_governor(g)
        try:
            self.assertIs(get_active_governor(), g)
        finally:
            reset_active_governor(token)
        self.assertIsNone(get_active_governor())


class TestRlimitNprocCli(unittest.TestCase):
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

    def test_zero_nproc_rejected(self):
        rc, err = self._run(["--rlimit-nproc", "0"])
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("--rlimit-nproc must be >= 1", err)

    def test_error_string_in_troubleshooting(self):
        doc = (REPO_ROOT / "docs" / "Troubleshooting.md").read_text()
        self.assertIn("--rlimit-nproc", doc)


if __name__ == "__main__":
    unittest.main()
