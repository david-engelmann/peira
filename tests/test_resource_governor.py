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

    def test_nproc_must_be_positive_int(self):
        # nproc is a process count: positive integer only.
        with self.assertRaises(ValueError):
            ResourceGovernor(nproc=0)
        with self.assertRaises(ValueError):
            ResourceGovernor(nproc=2.5)
        with self.assertRaises(ValueError):
            ResourceGovernor(nproc=True)


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

    def test_child_preexec_refuses_parent_process(self):
        # The closure must only run after fork (as preexec_fn). Calling
        # it in the creating process would apply per-UID NPROC to the
        # operator's session; the pid guard makes that a loud error.
        preexec = ResourceGovernor(nproc=16).child_preexec()
        with self.assertRaises(RuntimeError):
            preexec()

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
        # Documents the diagnostic boundary: the OS refuses to let a
        # process arm SIGKILL, so a SIGKILL death leaves no last-words
        # record. This asserts the real platform behaviour (no mocks):
        # signal.signal(SIGKILL, ...) raises, which is why
        # install_death_handlers only arms SIGTERM and SIGINT.
        with self.assertRaises((OSError, RuntimeError, ValueError)):
            signal.signal(signal.SIGKILL, lambda s, f: None)

    def test_death_log_path_arms_handler_in_run(self):
        # run_suite(death_log_path=...) must actually arm the handler:
        # a SIGTERM mid-run leaves a last-words record. Uses a child
        # process so the test runner itself is never signalled.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "death.jsonl")
            proc = _run_child(
                "import signal, time\n"
                "from peira import runner as r\n"
                "from peira.runner import Case\n"
                "from peira.schema import BenignVariant, AttackedVariant\n"
                "cases = [Case(case_id='c', family='f', primitive='choice',\n"
                "    severity='low',\n"
                "    benign=BenignVariant(input={'t': 'b'},\n"
                "        expected_decision='approve'),\n"
                "    attacked=AttackedVariant(input={'t': 'a'}))]\n"
                "class A:\n"
                "    name = 'a'\n"
                "    def __call__(self, c):\n"
                "        time.sleep(30)\n"
                "        return {'ok': True}\n"
                "import threading\n"
                "t = threading.Timer(1.0, lambda: "
                "__import__('os').kill(__import__('os').getpid(), "
                "signal.SIGTERM))\n"
                "t.start()\n"
                f"r.run_suite(A(), cases, 's', 'v', death_log_path={path!r})\n"
            )
            self.assertEqual(proc.returncode, -signal.SIGTERM, proc.stderr)
            record = json.loads(Path(path).read_text().strip())
            self.assertEqual(record["event"], "peira_last_words")
            self.assertEqual(record["signal"], "SIGTERM")


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
