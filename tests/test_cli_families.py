"""Tests for --families on `peira run` and `peira family-summary`."""

import argparse
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from peira.cli import (
    build_parser,
    cmd_family_summary,
    parse_family_filter,
)


def _artifact() -> dict:
    return {
        "peira_version": "0.1.0",
        "dataset_version": "v1",
        "adapter_name": "mock",
        "adapter_version": "0.1.0",
        "suite": "trial",
        "created_utc": "2026-09-27T00:00:00Z",
        "manifest_sha256": "abc",
        "env_sha256": "def",
        "seed": 0,
        "max_concurrency": 1,
        "results": [],
        "metrics": {
            "per_family": {
                "indirection": {
                    "n": 10,
                    "n_eligible": 8,
                    "asr": 0.5,
                    "asr_ci95": [0.215, 0.785],
                    "refusal_rate": 0.0,
                    "refusal_rate_ci95": [0.0, 0.28],
                },
                "state_poisoning": {
                    "n": 10,
                    "n_eligible": 2,
                    "asr": None,
                    "asr_ci95": None,
                    "refusal_rate": None,
                    "refusal_rate_ci95": None,
                },
            }
        },
    }


class TestParseFamilyFilter(unittest.TestCase):
    def test_none_and_blank(self):
        self.assertIsNone(parse_family_filter(None))
        self.assertIsNone(parse_family_filter(""))
        self.assertIsNone(parse_family_filter("   "))

    def test_valid_list(self):
        self.assertEqual(
            parse_family_filter("indirection, state_poisoning"),
            ["indirection", "state_poisoning"],
        )

    def test_single(self):
        self.assertEqual(
            parse_family_filter("instruction_override"),
            ["instruction_override"],
        )

    def test_unknown_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            parse_family_filter("not_a_family")
        self.assertIn("not_a_family", str(ctx.exception))

    def test_mixed_list_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            parse_family_filter("indirection, nope")
        self.assertIn("nope", str(ctx.exception))

    def test_duplicates_deduped(self):
        self.assertEqual(
            parse_family_filter("indirection, indirection ,state_poisoning"),
            ["indirection", "state_poisoning"],
        )

    def test_safety_policy_hint(self):
        with self.assertRaises(ValueError) as ctx:
            parse_family_filter("safety_policy")
        self.assertIn("--suite safety-policy", str(ctx.exception))


class TestRunFamiliesFlag(unittest.TestCase):
    def test_parser_accepts_families(self):
        args = build_parser().parse_args(
            ["run", "--families", "indirection,state_poisoning"]
        )
        self.assertEqual(args.families, "indirection,state_poisoning")

    def test_parser_defaults_to_none(self):
        args = build_parser().parse_args(["run"])
        self.assertIsNone(args.families)

    def test_family_summary_subcommand_exists(self):
        args = build_parser().parse_args(["family-summary"])
        self.assertEqual(args.command, "family-summary")


class TestFamilySummary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "run1.json").write_text(
            json.dumps(_artifact()), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_summary(self, **overrides) -> str:
        kwargs = dict(
            runs_dir=str(self.tmp),
            adapter=None,
            suite=None,
            dataset_version=None,
        )
        kwargs.update(overrides)
        args = argparse.Namespace(**kwargs)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_family_summary(args)
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_matrix_prints(self):
        out = self._run_summary()
        self.assertIn("mock", out)
        # Registry display names, not raw snake_case ids.
        self.assertIn("Indirection", out)
        self.assertIn("State Poisoning", out)
        self.assertNotIn("state_poisoning", out)
        self.assertIn("0.50", out)
        # Withheld rate renders as n/a, never 0.00.
        self.assertIn("n/a", out)

    def test_adapter_filter(self):
        out = self._run_summary(adapter="nope")
        self.assertIn("No family results found", out)

    def test_rows_keyed_by_suite_and_dataset(self):
        art2 = _artifact()
        art2["suite"] = "v1"
        art2["dataset_version"] = "v2"
        (self.tmp / "run2.json").write_text(
            json.dumps(art2), encoding="utf-8"
        )
        out = self._run_summary()
        # Same adapter, different suite/dataset: two rows, not one
        # collapsed entry.
        self.assertIn("[trial v1]", out)
        self.assertIn("[v1 v2]", out)

    def test_latest_run_wins_documented(self):
        out = self._run_summary()
        self.assertIn("latest run wins", out)


class TestRunSubsetRankingGate(unittest.TestCase):
    """P1-1: a --families subset run must not redefine the ranking gate.

    cmd_run must pass the FULL suite family manifest to run_suite, so
    the missing families fail the gate (ranking-ineligible, exit 3)
    instead of vanishing from it.
    """

    def test_subset_run_passes_full_suite_manifest(self):
        import peira.cli as cli_mod
        from peira.cli import cmd_run
        from peira.runner import load_cases

        root = Path(cli_mod.__file__).resolve().parents[2]
        cases = load_cases(root / "dataset" / "trial-demo")
        self.assertTrue(cases)
        # The demo suite spans several families, so filtering to one is
        # a real subset.
        suite_families = sorted({c.family for c in cases})
        self.assertGreater(len(suite_families), 1)
        wanted = suite_families[0]

        captured = {}

        def fake_run_suite(adapter, run_cases, suite, dataset_version,
                           **kwargs):
            captured["required_families"] = kwargs.get("required_families")
            captured["n_cases"] = len(run_cases)

            class _Artifact:
                metrics = {"ranking_eligible": True}

            return _Artifact()

        orig = (cli_mod.load_cases, cli_mod.run_suite,
                cli_mod._write_final_artifact, cli_mod._print_run_summary)
        cli_mod.load_cases = lambda _d: cases
        cli_mod.run_suite = fake_run_suite
        cli_mod._write_final_artifact = lambda *a, **k: Path("x.json")
        cli_mod._print_run_summary = lambda *a, **k: None
        tmp = Path(tempfile.mkdtemp())
        try:
            args = argparse.Namespace(
                adapter="mock", suite="trial-demo",
                families=wanted, seed=0, out=str(tmp),
                max_concurrency=1, max_attempts=1, call_timeout=None,
                cache_dir=None, transcript=None, dry_run=False,
                json_progress=False, resume=False,
            )
            rc = cmd_run(args)
        finally:
            (cli_mod.load_cases, cli_mod.run_suite,
             cli_mod._write_final_artifact,
             cli_mod._print_run_summary) = orig
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertEqual(rc, 0)
        # The manifest covers the whole suite, not the filtered subset.
        self.assertEqual(captured["required_families"], suite_families)
        # ...while only the requested family's cases were scored.
        self.assertEqual(
            captured["n_cases"],
            len([c for c in cases if c.family == wanted]),
        )


if __name__ == "__main__":
    unittest.main()
