"""CLI- and runner-level regression tests for the M-7 stability protocol.

Red-team findings on PR #221 (2026-09-30):
- P1-1: the mock's flip decisions were hashed from a constant seed, so
  every --seeds run produced identical outcomes and pass^k was
  vacuously 1.0. The constructor seed must vary per seed.
- P2-2: peira drift-watch compared runs across different suites or
  dataset versions, and accepted truncated runs. Identity and
  completeness are now enforced like peira stability.
- P1-4: per-seed persistence via the on_artifact callback must fire
  immediately after each seed completes (so a Ctrl-C or crash cannot
  lose completed seeds).
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from peira.artifacts import RunArtifact
from peira.cli import (
    EXIT_GATE_NOTE,
    EXIT_OK,
    EXIT_USER_ERROR,
    build_parser,
    cmd_drift_watch,
    cmd_stability,
)
from peira.runner import run_multiseed

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_artifact(tmp, name, *, suite="trial-demo",
                    dataset_version="1.0.0", adapter_name="mock",
                    adapter_version="1", termination="complete",
                    seed=0):
    art = RunArtifact(
        peira_version="0.1.0",
        dataset_version=dataset_version,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        suite=suite,
        seed=seed,
        termination=termination,
    ).seal()
    p = Path(tmp) / name
    p.write_text(art.to_json(), encoding="utf-8")
    return str(p)


def _drift_args(old, new):
    return build_parser().parse_args(
        ["drift-watch", "--old", old, "--new", new])


class TestMockSeedIndependence(unittest.TestCase):
    def test_different_seeds_flip_differently(self):
        # The mock is a deterministic hash-based test double: two
        # instances built with different seeds must not decide
        # identically, or the multi-seed protocol measures nothing.
        from peira.adapters.mock import MockAdapter
        a = MockAdapter(seed="3")
        b = MockAdapter(seed="4")
        ids = [f"case-{i:03d}" for i in range(50)]
        fa = [a._flips(h) for h in ids]
        fb = [b._flips(h) for h in ids]
        self.assertTrue(
            any(x != y for x, y in zip(fa, fb)),
            "seeds 3 and 4 flipped identically on 50 ids: "
            "multi-seed mock runs would be k copies of one decision",
        )

    def test_multiseed_mock_run_shows_churn_end_to_end(self):
        # End-to-end wiring: peira run --seeds 3 with the mock must
        # produce per-seed artifacts whose outcomes actually differ,
        # and peira stability must report churn > 0.
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "python")
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, "-m", "peira.cli", "run",
                 "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--seed", "42", "--seeds", "3"],
                capture_output=True, text=True, env=env, cwd=REPO_ROOT,
            )
            self.assertIn(
                r.returncode, (EXIT_OK, EXIT_GATE_NOTE),
                f"multi-seed mock run failed: {r.stderr[-2000:]}",
            )
            seeds = sorted(Path(tmp).glob("*-seed*.json"))
            self.assertEqual(len(seeds), 3,
                             f"expected 3 per-seed artifacts, got {seeds}")
            r = subprocess.run(
                [sys.executable, "-m", "peira.cli", "stability",
                 *[str(s) for s in seeds]],
                capture_output=True, text=True, env=env, cwd=REPO_ROOT,
            )
            self.assertEqual(
                r.returncode, EXIT_OK,
                f"peira stability failed: {r.stderr[-2000:]}",
            )
            churn = None
            for line in r.stdout.splitlines():
                m = re.search(r"(\d+) churn cases", line)
                if m:
                    churn = int(m.group(1))
                    break
            self.assertIsNotNone(churn, "no churn line in stability output")
            self.assertGreater(
                churn, 0,
                "mock multi-seed run showed zero churn cases: seeds are "
                "not independent measurements",
            )


class TestDriftWatchIdentity(unittest.TestCase):
    def test_accepts_same_suite_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_artifact(tmp, "old.json")
            new = _write_artifact(tmp, "new.json")
            self.assertEqual(
                cmd_drift_watch(_drift_args(old, new)), EXIT_OK)

    def test_rejects_different_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_artifact(tmp, "old.json", suite="trial-demo")
            new = _write_artifact(tmp, "new.json", suite="other-suite")
            self.assertEqual(
                cmd_drift_watch(_drift_args(old, new)), EXIT_USER_ERROR)

    def test_rejects_different_dataset_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_artifact(tmp, "old.json", dataset_version="1.0.0")
            new = _write_artifact(tmp, "new.json", dataset_version="2.0.0")
            self.assertEqual(
                cmd_drift_watch(_drift_args(old, new)), EXIT_USER_ERROR)

    def test_rejects_truncated_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_artifact(tmp, "old.json")
            new = _write_artifact(tmp, "new.json", termination="budget")
            self.assertEqual(
                cmd_drift_watch(_drift_args(old, new)), EXIT_USER_ERROR)

    def test_out_write_failure_is_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_artifact(tmp, "old.json")
            new = _write_artifact(tmp, "new.json")
            args = build_parser().parse_args([
                "drift-watch", "--old", old, "--new", new,
                "--out", str(Path(tmp) / "no-such-dir" / "out.json"),
            ])
            self.assertEqual(cmd_drift_watch(args), EXIT_USER_ERROR)


class TestStabilityIdentity(unittest.TestCase):
    def _stability_args(self, runs, out=None):
        argv = ["stability", *runs]
        if out:
            argv += ["--out", out]
        return build_parser().parse_args(argv)

    def test_rejects_adapter_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _write_artifact(tmp, "r1.json", adapter_version="1", seed=0)
            r2 = _write_artifact(tmp, "r2.json", adapter_version="2", seed=1)
            self.assertEqual(
                cmd_stability(self._stability_args([r1, r2])),
                EXIT_USER_ERROR)

    def test_accepts_matching_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _write_artifact(tmp, "r1.json", seed=0)
            r2 = _write_artifact(tmp, "r2.json", seed=1)
            self.assertEqual(
                cmd_stability(self._stability_args([r1, r2])), EXIT_OK)

    def test_out_write_failure_is_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _write_artifact(tmp, "r1.json", seed=0)
            r2 = _write_artifact(tmp, "r2.json", seed=1)
            args = self._stability_args(
                [r1, r2],
                out=str(Path(tmp) / "no-such-dir" / "out.json"),
            )
            self.assertEqual(cmd_stability(args), EXIT_USER_ERROR)


class TestOnArtifactCallback(unittest.TestCase):
    def test_fires_immediately_per_completed_seed(self):
        # A crash mid-way must not lose the seeds that already
        # finished: the callback fires after each seed, in order.
        from tests.test_stability import _fake_seed_artifact
        good = _fake_seed_artifact("complete", [True, False])
        side_effects = [
            _fake_seed_artifact("complete", [True, True]),
            good,
            RuntimeError("provider exploded"),
        ]
        seen = []
        with patch("peira.runner.run_suite", side_effect=side_effects):
            artifacts, _ = run_multiseed(
                adapter=object(), cases=[], suite="s",
                dataset_version="1.0.0", num_seeds=3,
                on_artifact=lambda i, a: seen.append((i, a)),
            )
        self.assertEqual([i for i, _ in seen], [0, 1])
        self.assertIs(seen[0][1], artifacts[0])
        self.assertIs(seen[1][1], artifacts[1])


class TestMultiseedValidation(unittest.TestCase):
    def test_seeds_zero_rejected(self):
        from peira.cli import cmd_run
        with tempfile.TemporaryDirectory() as tmp:
            args = build_parser().parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--seed", "42", "--seeds", "0"])
            self.assertEqual(cmd_run(args), EXIT_USER_ERROR)

    def test_transcript_with_multiseed_rejected(self):
        from peira.cli import cmd_run
        with tempfile.TemporaryDirectory() as tmp:
            t = str(Path(tmp) / "t.jsonl")
            args = build_parser().parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--seed", "42", "--seeds", "3",
                 "--transcript", t])
            self.assertEqual(cmd_run(args), EXIT_USER_ERROR)

    def test_cache_dir_with_multiseed_rejected(self):
        from peira.cli import cmd_run
        with tempfile.TemporaryDirectory() as tmp:
            args = build_parser().parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--out", tmp, "--seed", "42", "--seeds", "3",
                 "--cache-dir", str(Path(tmp) / "cache")])
            self.assertEqual(cmd_run(args), EXIT_USER_ERROR)


if __name__ == "__main__":
    unittest.main()
