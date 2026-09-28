"""peira run exit codes: ranking-ineligible completed runs exit 3, not 0.

EXIT_GATE_NOTE (3) means "ran fine, but the run is not ranking-eligible."
A --families subset run is ineligible by design (the gate is evaluated
over the full suite's family manifest, so missing families fail it).
This test pins the exact exit codes: 3 for ineligible, 0 for eligible.
Accepting (0, 3) would let a regression flip the codes silently.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from peira.cli import EXIT_GATE_NOTE, EXIT_OK, build_parser, cmd_run

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli_subprocess(tmp, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "python")
    return subprocess.run(
        [sys.executable, "-m", "peira.cli", "run", *args,
         "--adapter", "mock", "--suite", "trial-demo",
         "--out", tmp, "--seed", "42"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )


def _fake_artifact(eligible):
    art = mock.MagicMock()
    art.metrics = {"ranking_eligible": eligible}
    return art


def _cmd_run_args(tmp):
    parser = build_parser()
    return parser.parse_args([
        "run", "--adapter", "mock", "--suite", "trial-demo",
        "--out", tmp, "--seed", "42",
    ])


class TestRunExitCodes(unittest.TestCase):
    def test_families_subset_exits_3_end_to_end(self):
        # A --families subset run completes but is ranking-ineligible:
        # the gate is evaluated over the full suite manifest. This is
        # the end-to-end proof via subprocess.
        with tempfile.TemporaryDirectory() as tmp:
            r = _run_cli_subprocess(tmp, "--families", "state_poisoning")
            self.assertEqual(
                r.returncode, EXIT_GATE_NOTE,
                f"expected exit 3 for ineligible run, got {r.returncode}\n"
                f"stderr: {r.stderr[-2000:]}",
            )
            self.assertEqual(r.returncode, 3)

    def test_ineligible_artifact_exits_3(self):
        # Unit-level: cmd_run maps ranking_eligible=False to exit 3 exactly.
        with tempfile.TemporaryDirectory() as tmp:
            args = _cmd_run_args(tmp)
            with mock.patch(
                "peira.cli.run_suite",
                return_value=_fake_artifact(eligible=False),
            ), mock.patch(
                "peira.cli._write_final_artifact",
            ), mock.patch(
                "peira.cli._print_run_summary",
            ):
                rc = cmd_run(args)
            self.assertEqual(rc, EXIT_GATE_NOTE)
            self.assertEqual(rc, 3)

    def test_eligible_artifact_exits_0(self):
        # Unit-level: cmd_run maps ranking_eligible=True to exit 0 exactly.
        # (The trial-demo fixture has only 12 cases, below the 200-case
        # eligibility threshold, so a real eligible run cannot be built
        # from it; the eligibility computation itself is covered in
        # test_metrics.py.)
        with tempfile.TemporaryDirectory() as tmp:
            args = _cmd_run_args(tmp)
            with mock.patch(
                "peira.cli.run_suite",
                return_value=_fake_artifact(eligible=True),
            ), mock.patch(
                "peira.cli._write_final_artifact",
            ), mock.patch(
                "peira.cli._print_run_summary",
            ):
                rc = cmd_run(args)
            self.assertEqual(rc, EXIT_OK)
            self.assertEqual(rc, 0)


class TestRunFlags(unittest.TestCase):
    """O-6: CLI flags with no direct test coverage."""

    def test_transcript_flag_writes_jsonl(self):
        # --transcript writes a JSONL transcript of every request/response.
        with tempfile.TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(
                out, "--transcript", tpath, "--families", "state_poisoning",
            )
            # Exit 3 (ineligible) is fine; we care about the transcript.
            self.assertIn(r.returncode, (0, 3))
            lines = Path(tpath).read_text().splitlines()
            # 4 cases in state_poisoning x 2 variants = 8 lines.
            self.assertEqual(len(lines), 8)
            for line in lines:
                entry = json.loads(line)
                self.assertIn("request", entry)
                self.assertIn("response", entry)

    def test_cache_dir_flag_uses_cache(self):
        # --cache-dir enables the response cache; a second run with the
        # same cache dir must hit the cache (every result arm marked
        # cached: True, i.e. no provider call was made).
        with tempfile.TemporaryDirectory() as tmp:
            cdir = str(Path(tmp) / "cache")
            out1 = str(Path(tmp) / "out1")
            out2 = str(Path(tmp) / "out2")
            r1 = _run_cli_subprocess(
                out1, "--cache-dir", cdir, "--families", "state_poisoning",
            )
            self.assertIn(r1.returncode, (0, 3))
            # Cache dir should contain entries after the first run.
            cache_files = list(Path(cdir).rglob("*"))
            self.assertGreater(len(cache_files), 0,
                               "cache dir is empty after run")
            r2 = _run_cli_subprocess(
                out2, "--cache-dir", cdir, "--families", "state_poisoning",
            )
            self.assertIn(r2.returncode, (0, 3))

            def _cached_flags(out_dir):
                flags = []

                def walk(node):
                    if isinstance(node, dict):
                        for key, value in node.items():
                            if key == "cached":
                                flags.append(value)
                            walk(value)
                    elif isinstance(node, list):
                        for item in node:
                            walk(item)

                for artifact in Path(out_dir).glob("*.json"):
                    walk(json.loads(artifact.read_text()))
                return flags

            flags = _cached_flags(out2)
            self.assertGreater(len(flags), 0,
                               "no cached flags in second-run artifact")
            self.assertTrue(
                all(flags),
                f"second run did not hit the cache: {flags!r}",
            )

    def test_json_progress_flag_emits_json(self):
        # --json-progress emits machine-readable progress lines.
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(
                out, "--json-progress", "--families", "state_poisoning",
            )
            self.assertIn(r.returncode, (0, 3))
            # stdout should contain JSON progress objects.
            json_lines = [
                line for line in r.stdout.splitlines()
                if line.strip().startswith("{")
            ]
            self.assertGreater(len(json_lines), 0,
                               "no JSON progress lines in stdout")
            for line in json_lines:
                json.loads(line)  # must be valid JSON

    def test_max_attempts_flag_accepted(self):
        # --max-attempts is plumbed through: a valid value runs fine.
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(
                out, "--max-attempts", "2", "--families", "state_poisoning",
            )
            self.assertIn(r.returncode, (0, 3))

    def test_call_timeout_flag_accepted(self):
        # --call-timeout is plumbed through: a valid value runs fine.
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(
                out, "--call-timeout", "60", "--families", "state_poisoning",
            )
            self.assertIn(r.returncode, (0, 3))

    def test_max_concurrency_zero_rejected(self):
        # --max-concurrency < 1 is rejected with exit 1 and a clear message.
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(out, "--max-concurrency", "0")
            self.assertEqual(r.returncode, 1)
            self.assertIn("--max-concurrency must be >= 1", r.stderr)

    def test_max_attempts_zero_rejected(self):
        # --max-attempts < 1 is rejected with exit 1 and a clear message.
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(out, "--max-attempts", "0")
            self.assertEqual(r.returncode, 1)
            self.assertIn("--max-attempts must be >= 1", r.stderr)

    def test_call_timeout_zero_rejected(self):
        # --call-timeout <= 0 is rejected with exit 1 and a clear message.
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            r = _run_cli_subprocess(out, "--call-timeout", "0")
            self.assertEqual(r.returncode, 1)
            self.assertIn("--call-timeout must be > 0", r.stderr)


if __name__ == "__main__":
    unittest.main()
