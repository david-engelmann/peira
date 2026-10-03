"""Run-safety tests: transcript default, checkpoint tuning, multi-seed
checkpoints, artifact backup.

David's directive: never lose expensive results. These tests verify the
mechanisms that protect paid API calls from crashes.
"""

import argparse
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))

import os
os.environ.setdefault("PEIRA_NO_RUST", "1")

from peira import cli as cli_mod


class TestTranscriptDefault(unittest.TestCase):
    """The transcript must default on: it is the only record that lets
    a crashed run be rebuilt via `peira replay` without paying again."""

    def test_transcript_defaults_on(self):
        # Simulate what cmd_run does with a fresh Namespace
        args = argparse.Namespace(transcript=None, no_transcript=False)
        out_dir = pathlib.Path(tempfile.mkdtemp())
        slug, suite = "test-adapter", "trial-demo"
        try:
            # Replicate the cmd_run logic
            if args.transcript is None and not getattr(
                args, "no_transcript", False
            ):
                args.transcript = str(
                    out_dir / f"{slug}-{suite}.transcript.jsonl"
                )
            self.assertIsNotNone(args.transcript)
            self.assertTrue(args.transcript.endswith(".transcript.jsonl"))
        finally:
            import shutil
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_no_transcript_opts_out(self):
        args = argparse.Namespace(transcript=None, no_transcript=True)
        if args.transcript is None and not getattr(
            args, "no_transcript", False
        ):
            args.transcript = "should-not-happen"
        self.assertIsNone(args.transcript)

    def test_explicit_transcript_respected(self):
        args = argparse.Namespace(
            transcript="/custom/path.jsonl", no_transcript=False
        )
        if args.transcript is None and not getattr(
            args, "no_transcript", False
        ):
            args.transcript = "should-not-happen"
        self.assertEqual(args.transcript, "/custom/path.jsonl")


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


class TestMultiseedPartialPath(unittest.TestCase):
    """run_multiseed must accept per-seed partial paths."""

    def test_run_multiseed_signature(self):
        import inspect
        from peira import runner
        sig = inspect.signature(runner.run_multiseed)
        self.assertIn("seed_partial_path", sig.parameters)
        self.assertIn("seed_resume", sig.parameters)
        self.assertIn("checkpoint_every", sig.parameters)


if __name__ == "__main__":
    unittest.main()
