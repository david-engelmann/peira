"""Tests for `peira reproduce` and `peira contamination-check`.

The reproduce command resolves a leaderboard row id to a run artifact,
verifies provenance completeness, and (with --execute) re-runs the
adapter to compare ASR. contamination-check scans public case files
for the permanent canary GUID.
"""

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import (
    EXIT_INFRA_ERROR,
    EXIT_OK,
    EXIT_USER_ERROR,
    _canary_scan,
    _provenance_bundle,
    _provenance_gaps,
    _repro_matches,
    cmd_contamination_check,
    cmd_reproduce,
)
from peira.dataset import CANARY_GUID

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cmd(func, ns):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = func(ns)
    return rc, out.getvalue(), err.getvalue()


def _ns(**kw):
    return argparse.Namespace(**kw)


def _make_artifact(**overrides):
    """Minimal sealed artifact with complete provenance."""
    from peira.env_fingerprint import collect_and_fingerprint

    env, env_sha256 = collect_and_fingerprint()
    fields = {
        "adapter_name": "mock",
        "adapter_version": "0.2.0",
        "suite": "trial-demo",
        "dataset_version": "0.1.0-demo",
        "manifest_sha256": "a" * 64,
        "seed": 7,
        "max_concurrency": 8,
        "env": env,
        "env_sha256": env_sha256,
        "config": {"cache_enabled": False, "adapter_revision": "rev-123"},
        "results": [],
        "metrics": {"ranking_eligible": True, "eligibility_notes": []},
    }
    fields.update(overrides)
    return RunArtifact(**fields).seal()


def _mock_trial_artifact(seed=7):
    """Real sealed mock-adapter artifact over the trial suite."""
    from peira.adapters.mock import MockAdapter
    from peira.cli import _suite_dataset_identity
    from peira.runner import load_cases, new_run_nonce, run_suite

    suite_dir = REPO_ROOT / "dataset" / "trial"
    dataset_version, manifest_sha256 = _suite_dataset_identity(suite_dir)
    cases = load_cases(suite_dir)
    nonce = new_run_nonce()
    adapter = MockAdapter(
        script=MockAdapter.script_for(cases, seed=seed, run_nonce=nonce))
    return run_suite(adapter, cases, "trial", dataset_version, seed=seed,
                     manifest_sha256=manifest_sha256, run_nonce=nonce)


class TestReproduceUnknownRow(unittest.TestCase):
    def test_unknown_row_id_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _out, err = _run_cmd(
                cmd_reproduce,
                _ns(leaderboard_row_id="nope/0.0/none/0.0.0",
                    runs_dir=tmp, execute=False),
            )
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("unknown leaderboard row", err)

    def test_malformed_row_id_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _out, err = _run_cmd(
                cmd_reproduce,
                _ns(leaderboard_row_id="not-a-row-id",
                    runs_dir=tmp, execute=False),
            )
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("malformed leaderboard row id", err)


class TestProvenanceGaps(unittest.TestCase):
    def test_complete_bundle_has_no_gaps(self):
        bundle = _provenance_bundle(_make_artifact())
        self.assertEqual(_provenance_gaps(bundle), [])

    def test_missing_field_is_named(self):
        bundle = _provenance_bundle(
            _make_artifact(manifest_sha256="", adapter_version=""))
        gaps = _provenance_gaps(bundle)
        self.assertIn("manifest_sha256", gaps)
        # adapter_version falls back from config.adapter_revision here
        self.assertNotIn("adapter_revision", gaps)

    def test_missing_adapter_revision_and_manifest(self):
        art = _make_artifact(adapter_version="")
        art.config.pop("adapter_revision")
        gaps = _provenance_gaps(_provenance_bundle(art))
        self.assertIn("adapter_revision", gaps)

    def test_missing_seed_is_a_gap(self):
        bundle = _provenance_bundle(_make_artifact())
        bundle["seed"] = None
        self.assertIn("seed", _provenance_gaps(bundle))

    def test_reproduce_incomplete_provenance_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifact(manifest_sha256="")
            (Path(tmp) / "run.json").write_text(art.to_json())
            rc, _out, err = _run_cmd(
                cmd_reproduce,
                _ns(leaderboard_row_id="mock/0.2.0/trial-demo/0.1.0-demo",
                    runs_dir=tmp, execute=False),
            )
        self.assertEqual(rc, EXIT_INFRA_ERROR)
        self.assertIn("missing field 'manifest_sha256'", err)


class TestReproduceHappyPath(unittest.TestCase):
    def test_complete_provenance_prints_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "run.json").write_text(
                _make_artifact().to_json())
            rc, out, _err = _run_cmd(
                cmd_reproduce,
                _ns(leaderboard_row_id="mock/0.2.0/trial-demo/0.1.0-demo",
                    runs_dir=tmp, execute=False),
            )
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("Provenance bundle (complete).", out)
        self.assertIn("peira run --adapter mock --suite trial-demo "
                      "--seed 7 --out runs", out)

    def test_execute_mock_reproduces(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _mock_trial_artifact(seed=7)
            (Path(tmp) / "run.json").write_text(art.to_json())
            row_id = (f"mock/{art.adapter_version}/trial/"
                      f"{art.dataset_version}")
            rc, out, _err = _run_cmd(
                cmd_reproduce,
                _ns(leaderboard_row_id=row_id, runs_dir=tmp,
                    execute=True),
            )
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("Reproduction matches.", out)


class TestReproMatches(unittest.TestCase):
    def test_within_ci_matches(self):
        self.assertTrue(_repro_matches(0.5, 0.4, 0.6, 0.55))

    def test_outside_ci_mismatches(self):
        self.assertFalse(_repro_matches(0.5, 0.4, 0.6, 0.7))

    def test_no_ci_requires_equality(self):
        self.assertTrue(_repro_matches(0.5, None, None, 0.5))
        self.assertFalse(_repro_matches(0.5, None, None, 0.51))

    def test_withheld_reported_is_no_match(self):
        self.assertFalse(_repro_matches(None, 0.4, 0.6, 0.5))


class TestContaminationCheck(unittest.TestCase):
    def _fixture(self, tmp, with_canary):
        p = Path(tmp) / "cases.jsonl"
        line = '{"case_id": "x"'
        if with_canary:
            line += f', "canary": "{CANARY_GUID}"'
        p.write_text(line + "}\n")
        return p

    def test_scan_finds_canary_in_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._fixture(tmp, with_canary=True)
            rows = _canary_scan(Path(tmp), CANARY_GUID)
        self.assertEqual(rows, [(str(p), True)])

    def test_scan_reports_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._fixture(tmp, with_canary=False)
            rows = _canary_scan(Path(tmp), CANARY_GUID)
        self.assertEqual(rows, [(str(p), False)])

    def test_all_present_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._fixture(tmp, with_canary=True)
            rc, out, _err = _run_cmd(
                cmd_contamination_check, _ns(dataset=tmp))
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("carry the canary", out)
        self.assertIn("assumed contaminated from day one", out)

    def test_any_missing_exits_1_and_prints_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._fixture(tmp, with_canary=True)
            (Path(tmp) / "other.jsonl").write_text("{}\n")
            rc, out, err = _run_cmd(
                cmd_contamination_check, _ns(dataset=tmp))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("MISSING", out)
        self.assertIn("assumed contaminated from day one", out)
        self.assertIn("never published, not even as IDs", out)
        self.assertIn(CANARY_GUID, err)


if __name__ == "__main__":
    unittest.main()
