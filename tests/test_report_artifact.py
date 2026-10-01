"""Tests for peira.report_artifact and `peira report --json-out`.

The report artifact is a versioned, sealed provenance record of a
rendered report: source artifact identity and lock, report
parameters, and the metric payload. Tampering must break verify();
the loader must reject unknown fields and wrong schema versions.
"""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from peira.report_artifact import REPORT_SCHEMA_VERSION, ReportArtifact

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_artifact_like(**overrides):
    class Fake:
        artifact_version = "2"
        analysis_lock = "a" * 64
        env_sha256 = "b" * 64
        manifest_sha256 = "c" * 64
        adapter_name = "mock"
        adapter_version = "0.2.0"
        suite = "trial-demo"
        dataset_version = "0.1.0-demo"
        seed = 7
        metrics = {"asr_conditional": 0.4}

    for k, v in overrides.items():
        setattr(Fake, k, v)
    return Fake()


class BuilderTests(unittest.TestCase):
    def test_binds_source_provenance(self):
        art = ReportArtifact.from_run_artifact(
            _run_artifact_like(),
            report_params={"buyer_cost": {"threshold": 0.5}},
            source_path="runs/mock-trial-demo.json",
        ).seal()
        self.assertEqual(art.artifact_kind, "report")
        self.assertEqual(art.report_schema_version, REPORT_SCHEMA_VERSION)
        self.assertEqual(art.source["analysis_lock"], "a" * 64)
        self.assertEqual(art.source["env_sha256"], "b" * 64)
        self.assertEqual(art.source["manifest_sha256"], "c" * 64)
        self.assertEqual(art.source["seed"], 7)
        self.assertEqual(
            art.report_params, {"buyer_cost": {"threshold": 0.5}}
        )
        self.assertEqual(art.metrics, {"asr_conditional": 0.4})
        self.assertTrue(art.verify())

    def test_empty_params_default(self):
        art = ReportArtifact.from_run_artifact(
            _run_artifact_like(), report_params=None, source_path="x.json"
        )
        self.assertEqual(art.report_params, {})


class SealVerifyTests(unittest.TestCase):
    def test_round_trip(self):
        art = ReportArtifact.from_run_artifact(
            _run_artifact_like(), report_params={}, source_path="x.json"
        ).seal()
        loaded = ReportArtifact.from_json(art.to_json())
        self.assertTrue(loaded.verify())
        self.assertEqual(loaded.analysis_lock, art.analysis_lock)

    def test_tamper_breaks_verify(self):
        art = ReportArtifact.from_run_artifact(
            _run_artifact_like(), report_params={}, source_path="x.json"
        ).seal()
        d = json.loads(art.to_json())
        d["metrics"]["asr_conditional"] = 0.9
        loaded = ReportArtifact.from_json(json.dumps(d))
        self.assertFalse(loaded.verify())

    def test_param_tamper_breaks_verify(self):
        art = ReportArtifact.from_run_artifact(
            _run_artifact_like(),
            report_params={"buyer_cost": {"threshold": 0.5}},
            source_path="x.json",
        ).seal()
        d = json.loads(art.to_json())
        d["report_params"]["buyer_cost"]["threshold"] = 0.9
        loaded = ReportArtifact.from_json(json.dumps(d))
        self.assertFalse(loaded.verify())


class StrictLoaderTests(unittest.TestCase):
    def _sealed_dict(self):
        art = ReportArtifact.from_run_artifact(
            _run_artifact_like(), report_params={}, source_path="x.json"
        ).seal()
        return json.loads(art.to_json())

    def test_rejects_unknown_field(self):
        d = self._sealed_dict()
        d["future_field"] = 1
        with self.assertRaises(ValueError):
            ReportArtifact.from_json(json.dumps(d))

    def test_rejects_wrong_kind(self):
        d = self._sealed_dict()
        d["artifact_kind"] = "run"
        with self.assertRaises(ValueError):
            ReportArtifact.from_json(json.dumps(d))

    def test_rejects_future_schema_version(self):
        d = self._sealed_dict()
        d["report_schema_version"] = "2"
        with self.assertRaises(ValueError):
            ReportArtifact.from_json(json.dumps(d))

    def test_rejects_missing_required_field(self):
        d = self._sealed_dict()
        del d["source"]
        with self.assertRaises(ValueError):
            ReportArtifact.from_json(json.dumps(d))

    def test_rejects_bad_json(self):
        with self.assertRaises(ValueError):
            ReportArtifact.from_json("{not json")

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            ReportArtifact.from_json("[1, 2]")


class CliJsonOutTests(unittest.TestCase):
    """`peira report --json-out` writes a sealed report artifact."""

    def _run_cmd(self, func, ns):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = func(ns)
        return rc, out.getvalue(), err.getvalue()

    def test_json_out_writes_sealed_artifact(self):
        from peira.adapters.mock import MockAdapter
        from peira.cli import EXIT_OK, cmd_report
        from peira.runner import (
            load_cases,
            new_run_nonce,
            run_suite,
        )

        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")[:4]
        nonce = new_run_nonce()
        adapter = MockAdapter(
            script=MockAdapter.script_for(cases, seed=7, run_nonce=nonce)
        )
        artifact = run_suite(
            adapter, cases, "trial-demo", "0.1.0-demo",
            seed=7, run_nonce=nonce,
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp) / "run.json"
            run_path.write_text(artifact.to_json(), encoding="utf-8")
            html_path = Path(tmp) / "report.html"
            json_path = Path(tmp) / "report.json"
            ns = argparse.Namespace(
                run=str(run_path),
                out=str(html_path),
                json_out=str(json_path),
                operating_threshold=None,
                cost_false_approve=None,
                cost_false_deny=None,
                cost_review=None,
                flips_per_incident=None,
            )
            rc, out, _err = self._run_cmd(cmd_report, ns)
            self.assertEqual(rc, EXIT_OK)
            self.assertTrue(html_path.exists())
            loaded = ReportArtifact.from_json(
                json_path.read_text(encoding="utf-8")
            )
            self.assertTrue(loaded.verify())
            self.assertEqual(
                loaded.source["analysis_lock"], artifact.analysis_lock
            )
            self.assertIn("report artifact", out)


if __name__ == "__main__":
    unittest.main()
