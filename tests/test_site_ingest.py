"""Tests for site/scripts/ingest.py, the sealed run-artifact ingestion gates.

Covers the fail-closed behavior the display pipeline depends on: broken
locks, mock/real mixups, dataset-version and manifest disagreement,
invalid suites, duplicate run identities, non-finite metrics, and the
verbatim-metrics contract. Fixtures are built with the real peira
artifact code path.
"""

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INGEST = REPO / "site" / "scripts" / "ingest.py"
sys.path.insert(0, str(REPO / "python"))

from peira.artifacts import RunArtifact, results_to_dicts  # noqa: E402
from peira.metrics import CallRecord, PerCaseResult, summarize  # noqa: E402


def _record(decision, malformed=False):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=1,
        dispatch_index=0,
        malformed=malformed,
    )


def _result(i, attacked_decision):
    attacked = _record(attacked_decision)
    flipped = attacked_decision != "deny"
    return PerCaseResult(
        case_id=f"ingest-test-{i:04d}",
        family="prompt_injection",
        severity="high",
        primitive="choice",
        benign=_record("deny"),
        attacked=attacked,
        flipped=flipped,
        eligible=True,
    )


def make_artifact(path, *, mock=True, suite="public", dataset_version="1.1.1",
                   corrupt_lock=False, manifest_sha256="mock",
                   adapter_name="mock-test", adapter_version="mock-1",
                   metrics_tweak=None):
    results = [_result(i, "allow" if i % 2 else "deny") for i in range(24)]
    summary = summarize(results, n_boot=50)
    if metrics_tweak:
        metrics_tweak(summary)
    art = RunArtifact(
        artifact_version="2",
        peira_version="0.1.0",
        dataset_version=dataset_version,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        suite=suite,
        created_utc="2026-09-29T00:00:00+00:00",
        config={"mock": mock},
        results=results_to_dicts(results),
        metrics=summary,
        manifest_sha256=manifest_sha256,
        model_class="mock",
        confidence_source="verbalized",
        termination="complete",
        cases_completed=24,
        cases_planned=24,
        seed=7,
    )
    art.seal()
    data = json.loads(art.to_json())
    if corrupt_lock:
        data["analysis_lock"] = "0" * 64
    path.write_text(json.dumps(data))


def run_ingest(artifacts_dir, out_path, extra=()):
    cmd = [sys.executable, str(INGEST), *extra, str(artifacts_dir),
           "--out", str(out_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


class IngestGatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.arts = self.dir / "arts"
        self.arts.mkdir()
        self.out = self.dir / "results.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _one(self, **kw):
        make_artifact(self.arts / "a.json", **kw)

    def test_valid_mock_ingest(self):
        self._one(mock=True, suite="public")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self.out.read_text())
        # top-level contract
        self.assertEqual(data["schema_version"], "1")
        self.assertTrue(data["mock_data"])
        self.assertEqual(data["dataset"]["version"], "1.1.1")
        self.assertEqual(data["dataset"]["manifest_sha256"], "mock")
        self.assertEqual(len(data["runs"]), 1)
        run = data["runs"][0]
        self.assertEqual(run["adapter_name"], "mock-test")
        self.assertEqual(run["suite"], "public")
        # metrics are verbatim from the sealed artifact: recompute and compare
        results = [_result(i, "allow" if i % 2 else "deny") for i in range(24)]
        expected_metrics = summarize(results, n_boot=50)
        self.assertEqual(run["metrics"], expected_metrics)
        # case rows carry the documented schema keys, nothing else
        self.assertEqual(len(run["cases"]), 24)
        for c in run["cases"]:
            self.assertEqual(
                sorted(c.keys()),
                ["attacked_decision", "benign_decision", "case_id", "eligible",
                 "family", "flipped", "primitive", "severity"],
            )

    def test_broken_lock_rejected(self):
        self._one(mock=True, corrupt_lock=True)
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lock", r.stderr.lower())

    def test_mock_rejected_without_flag(self):
        self._one(mock=True)
        r = run_ingest(self.arts, self.out)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mock", r.stderr.lower())

    def test_real_rejected_with_mock_flag(self):
        self._one(mock=False)
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mock", r.stderr.lower())

    def test_dataset_version_mismatch(self):
        make_artifact(self.arts / "a.json", mock=True, dataset_version="1.1.1")
        make_artifact(self.arts / "b.json", mock=True, dataset_version="9.9.9",
                      adapter_name="mock-test-2")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dataset", r.stderr.lower())

    def test_invalid_suite_rejected(self):
        self._one(mock=True, suite="staging")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)

    def test_manifest_sha_mismatch_rejected(self):
        make_artifact(self.arts / "a.json", mock=True, manifest_sha256="aaa")
        make_artifact(self.arts / "b.json", mock=True, manifest_sha256="bbb",
                      adapter_name="mock-test-2")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("manifest", r.stderr.lower())

    def test_non_boolean_mock_rejected(self):
        self._one(mock="false")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("boolean", r.stderr.lower())

    def test_duplicate_run_identity_rejected(self):
        make_artifact(self.arts / "a.json", mock=True)
        make_artifact(self.arts / "b.json", mock=True)  # same name/version/suite
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("duplicate", r.stderr.lower())

    def test_nan_metric_rejected(self):
        def inject_nan(summary):
            summary["asr_conditional"] = math.nan
        self._one(mock=True, metrics_tweak=inject_nan)
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("non-finite", r.stderr.lower())


if __name__ == "__main__":
    unittest.main()
