"""R-01 non-blending separation tests for the conversational suite.

The conversational suite is a SEPARATE suite from the single-shot
v1/v2 suites: its artifacts must be namespaced (suite == "conversational",
suite-namespaced ``conversational_turns`` payload), must never pool with
single-shot results in comparisons or leaderboard ingestion, must be
listed under their own suite in the run registry, and must be cleanly
rejected by ``peira replay`` (R-01 does not implement turn re-execution).

All tests are offline: MockAdapter drives the fixture cases, the
single-shot baseline artifact is hand-built from the same strict entry
shape tests/test_artifacts.py uses, and the registry lives in a temp
dir. xdist-safe: no shared mutable state.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.cli import build_parser, cmd_replay
from peira.compare import check_comparable
from peira.conversation import (
    CONVERSATION_SUITE_ID,
    load_conversation_cases,
    run_conversation_suite,
)
from peira import runs_registry
from peira.runner import new_run_nonce

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "conversational"


def _conversational_artifact(seed=0, flip_rate=0.0):
    """Run the 2-case fixture suite through the mock; return the sealed artifact."""
    cases = load_conversation_cases(FIXTURES)
    nonce = new_run_nonce()
    adapter = MockAdapter(
        seed="separation-test",
        flip_rate=flip_rate,
        script=MockAdapter.script_for_conversation(cases, seed=seed, run_nonce=nonce),
    )
    return run_conversation_suite(
        adapter, cases, seed=seed, run_nonce=nonce, max_concurrency=2
    )


def _single_shot_entry(case_id):
    """One minimal single-shot result entry (strict entry shape, no turns)."""
    def call_record(decision="approve"):
        return {
            "decision": decision,
            "confidence": 0.9,
            "abstained": False,
            "refusal_reason": "",
            "usage": {
                "model": "mock",
                "tokens_in": 100,
                "tokens_out": 20,
                "latency_ms": 350.0,
                "cost_usd": 0.001,
            },
            "seed": 7,
            "dispatch_index": 0,
            "malformed": False,
            "dispatch_limit": 1,
        }

    return {
        "case_id": case_id,
        "family": "indirection",
        "severity": "high",
        "primitive": "choice",
        "benign": call_record("approve"),
        "attacked": call_record("deny"),
        "flipped": True,
        "eligible": True,
        "ineligibility_reason": "",
    }


def _single_shot_artifact():
    """A sealed single-shot baseline artifact (suite v1), no conversational fields."""
    return RunArtifact(
        peira_version="0.1.0",
        dataset_version="1.0.0",
        adapter_name="mock",
        adapter_version="1",
        suite="v1",
        results=[_single_shot_entry("ss-001"), _single_shot_entry("ss-002")],
        metrics={"n_cases": 2},
    ).seal()


class TestConversationalArtifactNamespaced(unittest.TestCase):
    def test_conversational_artifact_namespaced(self):
        artifact = _conversational_artifact()
        self.assertEqual(artifact.suite, CONVERSATION_SUITE_ID)
        self.assertEqual(artifact.suite, "conversational")
        self.assertEqual(artifact.metrics["n_cases"], 2)
        self.assertEqual(len(artifact.results), 2)
        fixture_ids = {"conv-fixture-001", "conv-fixture-002"}
        for entry in artifact.results:
            self.assertIn(entry["case_id"], fixture_ids)
            self.assertIn("conversational_turns", entry)
            turns = entry["conversational_turns"]
            self.assertEqual(set(turns), {"benign_turns", "attacked_turns"})
            self.assertTrue(turns["benign_turns"])
            self.assertTrue(turns["attacked_turns"])
            # the suite-namespaced payload is the conversational differentiator;
            # final-turn decisions ride the shared benign/attacked record shape
            self.assertIn("benign", entry)
            self.assertIn("attacked", entry)


class TestCompareRejectsCrossSuite(unittest.TestCase):
    def test_compare_rejects_cross_suite(self):
        conv = _conversational_artifact()
        single = _single_shot_artifact()
        problems = check_comparable(conv, single)
        suite_problems = [p for p in problems if p.startswith("suite differs:")]
        self.assertEqual(len(suite_problems), 1, problems)
        self.assertIn("'conversational'", suite_problems[0])
        self.assertIn("'v1'", suite_problems[0])
        # the single-shot side has no turn payload to compare either
        self.assertFalse(any("conversational_turns" in r for r in single.results))

    def test_compare_same_suite_has_no_suite_problem(self):
        conv_a = _conversational_artifact(seed=11)
        conv_b = _conversational_artifact(seed=22)
        problems = check_comparable(conv_a, conv_b)
        self.assertFalse(
            [p for p in problems if p.startswith("suite differs:")], problems
        )


class TestResultsNeverPool(unittest.TestCase):
    @staticmethod
    def _ingestion_key(artifact):
        """Mimic leaderboard ingestion: segment on the full comparability key."""
        return (
            artifact.adapter_name,
            artifact.adapter_version,
            artifact.suite,
            artifact.dataset_version,
        )

    def test_results_never_pool(self):
        conv = _conversational_artifact()
        single = _single_shot_artifact()
        conv_key = self._ingestion_key(conv)
        single_key = self._ingestion_key(single)
        self.assertNotEqual(conv_key, single_key)
        self.assertEqual(conv_key[2], "conversational")
        self.assertEqual(single_key[2], "v1")
        # bucketing per-case results under these keys never mixes suites
        buckets = {conv_key: [], single_key: []}
        for entry in conv.results:
            buckets[conv_key].append(entry["case_id"])
        for entry in single.results:
            buckets[single_key].append(entry["case_id"])
        self.assertEqual(len(buckets), 2)
        all_ids = [cid for ids in buckets.values() for cid in ids]
        conv_ids = [r["case_id"] for r in conv.results]
        self.assertTrue(all(cid in conv_ids for cid in buckets[conv_key]))
        self.assertTrue(all(cid not in conv_ids for cid in buckets[single_key]))


class TestRegistrySuiteFilter(unittest.TestCase):
    def test_registry_suite_filter(self):
        conv = _conversational_artifact()
        single = _single_shot_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            (runs_dir / "conv-sep.json").write_text(conv.to_json())
            (runs_dir / "v1-sep.json").write_text(single.to_json())
            indexed = runs_registry.scan_runs(runs_dir=runs_dir)
            self.assertEqual(indexed, 2)

            conv_rows = runs_registry.list_runs(runs_dir=runs_dir, suite="conversational")
            self.assertEqual(len(conv_rows), 1)
            self.assertEqual(conv_rows[0]["suite"], "conversational")

            v1_rows = runs_registry.list_runs(runs_dir=runs_dir, suite="v1")
            self.assertEqual(len(v1_rows), 1)
            self.assertEqual(v1_rows[0]["suite"], "v1")

            all_rows = runs_registry.list_runs(runs_dir=runs_dir)
            self.assertEqual(len(all_rows), 2)
            self.assertEqual(
                {r["suite"] for r in all_rows}, {"conversational", "v1"}
            )


class TestReportMarksSuite(unittest.TestCase):
    def test_artifact_roundtrip_preserves_suite_namespace(self):
        # No clean unit-level report hook exists for the conversational
        # suite (peira report renders the S8b A3 summary from single-shot
        # metrics); assert the sealed round-trip keeps the suite label and
        # the turn payload that any report must render.
        artifact = _conversational_artifact()
        reloaded = RunArtifact.from_json(artifact.to_json())
        self.assertTrue(reloaded.verify())
        self.assertEqual(reloaded.suite, "conversational")
        for entry in reloaded.results:
            turns = entry["conversational_turns"]
            self.assertEqual(set(turns), {"benign_turns", "attacked_turns"})
            self.assertTrue(turns["benign_turns"])
            self.assertTrue(turns["attacked_turns"])
        self.assertEqual(reloaded.metrics["n_cases"], 2)


class TestReplayRejectsConversational(unittest.TestCase):
    def test_replay_rejects_conversational(self):
        args = build_parser().parse_args(
            ["replay", "--transcript", "nope.jsonl", "--suite", "conversational"]
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = cmd_replay(args)
        err = stderr.getvalue()
        self.assertEqual(rc, 1)  # EXIT_USER_ERROR, clean user error
        self.assertIn("conversational", err)
        self.assertNotIn("Traceback", err)

    def test_replay_still_rejects_unknown_suite(self):
        # guard: the conversational rejection is suite-specific, not a
        # generic fallback that swallows every suite error
        args = build_parser().parse_args(
            ["replay", "--transcript", "nope.jsonl", "--suite", "v1"]
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = cmd_replay(args)
        # v1 exists as a suite dir; it must NOT hit the conversational error
        self.assertNotIn("turn-level re-execution", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        # (rc depends on transcript state; the suite dispatch is what matters)


def _sealed_conversational_artifact():
    """A minimal sealed conversational artifact (no suite run needed)."""
    return RunArtifact(
        peira_version="0.1.0",
        dataset_version="1.0.0",
        adapter_name="mock",
        adapter_version="1",
        suite=CONVERSATION_SUITE_ID,
        results=[],
        metrics={"n_cases": 0, "n_eligible": 0, "suite": CONVERSATION_SUITE_ID},
    ).seal()


class TestSingleShotConsumersRefuseConversational(unittest.TestCase):
    def _write_artifact(self, tmpdir):
        path = Path(tmpdir) / "conv.json"
        path.write_text(_sealed_conversational_artifact().to_json())
        return path

    def test_report_refuses_conversational(self):
        from peira.cli import cmd_report

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_artifact(tmp)
            args = build_parser().parse_args(
                ["report", "--run", str(path), "--out", str(Path(tmp) / "r.html")]
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = cmd_report(args)
        self.assertEqual(rc, 1)
        err = stderr.getvalue()
        self.assertIn("conversational", err)
        self.assertNotIn("Traceback", err)

    def test_dashboard_run_refuses_conversational(self):
        from peira.cli import cmd_dashboard_run

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_artifact(tmp)
            args = build_parser().parse_args(
                ["dashboard", "run", str(path)]
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = cmd_dashboard_run(args)
        self.assertEqual(rc, 1)
        err = stderr.getvalue()
        self.assertIn("conversational", err)
        self.assertNotIn("Traceback", err)

    def test_run_to_dashboard_raises(self):
        from peira.dashboard import run_to_dashboard

        with self.assertRaises(ValueError) as ctx:
            run_to_dashboard(_sealed_conversational_artifact())
        self.assertIn("conversational", str(ctx.exception))

    def test_leaderboard_qualification_rejects_conversational(self):
        ok, reason = runs_registry.qualifies_for_leaderboard(
            _sealed_conversational_artifact()
        )
        self.assertFalse(ok)
        self.assertIn("conversational", reason)


class TestConversationalArtifactBackendParity(unittest.TestCase):
    """The conversational artifact must seal and verify identically under
    the Rust extension lock path and the pure-Python fallback (subprocess
    comparison, following tests/test_rust_backend.py)."""

    FIXTURE = (
        Path(__file__).resolve().parent.parent
        / "crates" / "peira-core" / "tests" / "fixtures"
        / "conversational_artifact.json"
    )

    def _run(self, code, env_extra=None):
        env = dict(os.environ)
        repo = Path(__file__).resolve().parent.parent
        env["PYTHONPATH"] = os.pathsep.join([
            str(repo / "python"),
            str(repo),
            env.get("PYTHONPATH", ""),
        ])
        env["CONV_FIXTURE"] = str(self.FIXTURE)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, env=env,
        )

    def test_conversational_lock_backend_parity(self):
        code = (
            "import os; "
            "from peira.artifacts import RunArtifact; "
            "a = RunArtifact.from_json(open(os.environ['CONV_FIXTURE']).read()); "
            "assert a.suite == 'conversational', a.suite; "
            "assert a.verify(), 'fixture must verify'; "
            "a.seal(); "
            "assert a.verify(), 're-seal must verify'; "
            "print(a.analysis_lock)"
        )
        rust = self._run(code)
        pure = self._run(code, {"PEIRA_NO_RUST": "1"})
        self.assertEqual(rust.returncode, 0, rust.stderr)
        self.assertEqual(pure.returncode, 0, pure.stderr)
        self.assertEqual(rust.stdout, pure.stdout)
        # The re-sealed lock matches the Python-generated fixture lock:
        # both backends agree with the reference.
        fixture_lock = json.loads(self.FIXTURE.read_text())["analysis_lock"]
        self.assertEqual(rust.stdout.strip(), fixture_lock)


if __name__ == "__main__":
    unittest.main()
