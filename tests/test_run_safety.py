"""Run-safety tests: transcript default, checkpoint tuning, multi-seed
checkpoints, artifact backup.

David's directive: never lose expensive results. These tests verify the
mechanisms that protect paid API calls from crashes.
"""

import argparse
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))

import os
os.environ.setdefault("PEIRA_NO_RUST", "1")

from peira import cli as cli_mod
from peira.cli import EXIT_USER_ERROR
from peira.runner import per_seed_budget


class TestTranscriptDefault(unittest.TestCase):
    """The transcript must default on: it is the only record that lets
    a crashed run be rebuilt via `peira replay` without paying again.

    These tests call the real defaulting helper
    (_default_transcript_path), the same function cmd_run uses."""

    def test_transcript_defaults_on(self):
        args = argparse.Namespace(transcript=None, no_transcript=False)
        out_dir = pathlib.Path(tempfile.mkdtemp())
        try:
            path = cli_mod._default_transcript_path(
                args, out_dir, "test-adapter", "trial-demo"
            )
            self.assertEqual(
                path,
                str(out_dir / "test-adapter-trial-demo.transcript.jsonl"),
            )
        finally:
            import shutil
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_no_transcript_opts_out(self):
        args = argparse.Namespace(transcript=None, no_transcript=True)
        self.assertIsNone(
            cli_mod._default_transcript_path(
                args, pathlib.Path("/tmp"), "test-adapter", "trial-demo"
            )
        )

    def test_explicit_transcript_respected(self):
        args = argparse.Namespace(
            transcript="/custom/path.jsonl", no_transcript=False
        )
        self.assertEqual(
            cli_mod._default_transcript_path(
                args, pathlib.Path("/tmp"), "test-adapter", "trial-demo"
            ),
            "/custom/path.jsonl",
        )


class TestSeedTranscriptPaths(unittest.TestCase):
    """Multi-seed runs must wire the transcript through per seed: each
    seed gets its own file so seeds never share (and overwrite) one."""

    def test_default_path_gets_seed_suffix(self):
        path = cli_mod._derive_seed_transcript_path(
            pathlib.Path("/out/mock-trial-demo.transcript.jsonl"), 42
        )
        self.assertEqual(
            path,
            pathlib.Path("/out/mock-trial-demo-seed42.transcript.jsonl"),
        )

    def test_explicit_path_gets_seed_suffix(self):
        path = cli_mod._derive_seed_transcript_path("/tmp/my.jsonl", 3)
        self.assertEqual(path, pathlib.Path("/tmp/my-seed3.jsonl"))

    def test_explicit_transcript_jsonl_keeps_convention(self):
        path = cli_mod._derive_seed_transcript_path(
            "/tmp/custom.transcript.jsonl", 7
        )
        self.assertEqual(
            path, pathlib.Path("/tmp/custom-seed7.transcript.jsonl")
        )


class TestPerSeedBudget(unittest.TestCase):
    """Resume validation must use the same per-seed budget the run
    sealed each partial under (budget_usd / num_seeds), or resume
    always rejects with a budget mismatch."""

    def test_divides_evenly(self):
        self.assertEqual(per_seed_budget(30.0, 3), 10.0)

    def test_none_stays_none(self):
        self.assertIsNone(per_seed_budget(None, 3))


class TestCheckpointEvery(unittest.TestCase):
    """--checkpoint-every must be accepted and passed through."""

    def test_cli_accepts_checkpoint_every(self):
        # Verify the arg is registered
        import io
        from contextlib import redirect_stderr
        # Just check the parser has it
        parser = cli_mod.build_parser()
        # Find the run subparser and check for --checkpoint-every
        # (build_parser may not exist; try parse_args)
        try:
            args = parser.parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--checkpoint-every", "10"]
            )
            self.assertEqual(args.checkpoint_every, 10)
        except AttributeError:
            # build_parser doesn't exist, skip
            self.skipTest("build_parser not available")

    def test_checkpoint_every_default(self):
        parser = cli_mod.build_parser()
        try:
            args = parser.parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo"]
            )
            self.assertEqual(args.checkpoint_every, 25)
        except AttributeError:
            self.skipTest("build_parser not available")


class TestArtifactBackup(unittest.TestCase):
    """_write_final_artifact must write a backup copy."""

    def test_backup_written(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            # Create a minimal mock artifact
            class FakeArtifact:
                def to_json(self):
                    return json.dumps({"test": "data"})

            out_path = cli_mod._write_final_artifact(
                tmp, "test-adapter", "trial-demo", FakeArtifact()
            )
            self.assertTrue(out_path.exists())
            backup = tmp / "test-adapter-trial-demo.backup.json"
            self.assertTrue(backup.exists())
            self.assertEqual(
                json.loads(backup.read_text()),
                json.loads(out_path.read_text()),
            )
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_backup_keyboard_interrupt_is_warning(self):
        # A KeyboardInterrupt landing during the backup write must not
        # fail the run: the primary is already safe. Exercises the real
        # _write_final_artifact with a failing backup write.
        tmp = pathlib.Path(tempfile.mkdtemp())
        real_write = cli_mod.atomic_write_text
        calls = []

        def flaky_write(path, content):
            calls.append(str(path))
            if str(path).endswith(".backup.json"):
                raise KeyboardInterrupt()
            return real_write(path, content)

        class FakeArtifact:
            def to_json(self):
                return json.dumps({"test": "data"})

        try:
            with mock.patch.object(
                cli_mod, "atomic_write_text", side_effect=flaky_write
            ):
                err = io.StringIO()
                with redirect_stderr(err):
                    out_path = cli_mod._write_final_artifact(
                        tmp, "test-adapter", "trial-demo", FakeArtifact()
                    )
            # The run "succeeded": primary written, no exception.
            self.assertTrue(out_path.exists())
            self.assertEqual(len(calls), 2)
            self.assertIn("warning: could not write backup artifact",
                          err.getvalue())
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestCheckpointEveryValidation(unittest.TestCase):
    """--checkpoint-every 0 must fail fast with a clear message, not
    ZeroDivisionError at `completed % checkpoint_every` in the runner."""

    def test_checkpoint_every_zero_rejected(self):
        parser = cli_mod.build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            args = parser.parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--checkpoint-every", "0", "--dry-run"]
            )
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli_mod.cmd_run(args)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("--checkpoint-every must be >= 1", err.getvalue())

    def test_checkpoint_every_negative_rejected(self):
        parser = cli_mod.build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            args = parser.parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--checkpoint-every", "-5", "--dry-run"]
            )
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli_mod.cmd_run(args)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("--checkpoint-every must be >= 1", err.getvalue())

    def test_checkpoint_every_valid_passes_validation(self):
        # A valid value must sail through validation to the dry-run
        # return (exit 0), proving the check only fires on bad input.
        parser = cli_mod.build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            args = parser.parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--checkpoint-every", "10", "--dry-run"]
            )
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli_mod.cmd_run(args)
            self.assertEqual(rc, cli_mod.EXIT_OK)


class TestMultiseedResumeBudget(unittest.TestCase):
    """Regression: _cmd_run_multiseed must validate each seed's partial
    against the PER-SEED budget (budget_usd / num_seeds), the same value
    run_multiseed seals the partial under. Validating against the full
    budget made every multiseed resume reject its own partials."""

    def test_resume_validates_per_seed_budget(self):
        from unittest import mock as _mock

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp)
            parser = cli_mod.build_parser()
            args = parser.parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--seed", "42", "--seeds", "3",
                 "--budget-usd", "30", "--resume"]
            )
            # A partial for seed 42 exists; the rest start fresh.
            (out_dir / "mock-trial-demo-seed42.partial.json").write_text(
                '{"sealed": true}'
            )
            seen = {}

            def fake_validate(partial, adapter, cases, suite,
                              dataset_version, manifest_sha256, **kwargs):
                seen.update(kwargs)
                return set(), []

            adapter = _mock.MagicMock()
            with _mock.patch(
                "peira.runner.validate_partial",
                side_effect=fake_validate,
            ), _mock.patch(
                "peira.artifacts.RunArtifact.from_json",
                return_value=_mock.MagicMock(),
            ), _mock.patch(
                "peira.cli.run_multiseed", return_value=([], None),
            ):
                err = io.StringIO()
                with redirect_stderr(err):
                    cli_mod._cmd_run_multiseed(
                        args, adapter, [], "trial-demo", [],
                        "0.1.0-trial", "abc", out_dir, "mock",
                        3, None, 30.0, lambda i, t: None,
                    )
            # The partial was sealed under 30/3 = 10.0 per seed, not 30.
            self.assertEqual(seen.get("budget_usd"), 10.0)
            self.assertEqual(seen.get("seed"), 42)
    """run_multiseed must accept per-seed partial paths."""

class TestMultiseedPartialPath(unittest.TestCase):
    """run_multiseed must accept per-seed partial paths."""

    def test_run_multiseed_signature(self):
        import inspect
        from peira import runner
        sig = inspect.signature(runner.run_multiseed)
        self.assertIn("seed_partial_path", sig.parameters)
        self.assertIn("seed_resume", sig.parameters)
        self.assertIn("checkpoint_every", sig.parameters)
        self.assertIn("seed_transcript_path", sig.parameters)


if __name__ == "__main__":
    unittest.main()
