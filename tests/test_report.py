"""peira report hardening: hostile artifacts render inert, corrupt
artifacts and unwritable outputs exit 1 with a message (never a
traceback).
"""

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import EXIT_USER_ERROR, cmd_report


def _metrics(**over):
    m = {
        "n_cases": 1,
        "n_eligible": 1,
        "asr_conditional": 0.5,
        "asr_ci95": [0.1, 0.9],
        "severity_weighted_asr": 0.5,
        "severity_weighted_asr_ci95": [0.1, 0.9],
        "benign_accuracy": 1.0,
        "benign_accuracy_ci95": [1.0, 1.0],
        "malformed_rate": 0.0,
        "refusal_rate": 0.0,
        "refusal_rate_ci95": [0.0, 0.5],
        "benign_refusal_rate": 0.0,
        "benign_refusal_rate_ci95": [0.0, 0.5],
        "refusal_rate_delta": 0.0,
        "refusal_rate_delta_ci95": [0.0, 0.5],
        "ineligible_by_reason": {
            "benign_malformed": 0,
            "benign_wrong_decision": 0,
            "benign_abstained": 0,
        },
        "outcomes_benign": {
            "n": 1, "approve": 1, "deny": 0, "other": 0,
            "refused": 0, "abstained": 0, "malformed": 0,
        },
        "outcomes_attacked": {
            "n": 1, "approve": 1, "deny": 0, "other": 0,
            "refused": 0, "abstained": 0, "malformed": 0,
        },
        "ranking_eligible": False,
        "eligibility_notes": ["only 1 case"],
        "calibration": {
            "confidence_coverage": {"benign": 0.9, "attacked": 0.8},
            "benign": {
                "n": 1, "sufficient": False, "ece": None,
                "ece_ci95": None, "brier": None, "brier_ci95": None,
                "murphy": None,
            },
            "attacked": {
                "n": 1, "sufficient": False, "ece": None,
                "ece_ci95": None, "brier": None, "brier_ci95": None,
                "murphy": None,
            },
            "delta_brier": {"delta": None, "ci95": None, "n": 1,
                            "sufficient": False},
            "delta_ece": {"delta": None, "ci95": None, "n": 1,
                          "sufficient": False},
            "delta_reliability": {"delta": None, "ci95": None, "n": 1,
                                  "sufficient": False},
        },
        "selective_prediction": {
            "n": 1, "sufficient": False, "augrc": None, "augrc_ci95": None,
            "selective_risk": {"0.5": None, "0.8": None, "0.9": None, "1.0": None},
            "selective_risk_ci95": {"0.5": None, "0.8": None, "0.9": None, "1.0": None},
            "risk_coverage_curve": None,
        },
        "score_diagnostics": {
            "available": False,
            "reason": "expected_scores not provided",
            "skipped": {"ineligible": 0, "no_score": 0, "no_reference": 0},
            "benign_mae": {"value": None, "ci95": None, "n": 0,
                           "sufficient": False},
            "attacked_mae": {"value": None, "ci95": None, "n": 0,
                             "sufficient": False},
            "displacement": {"value": None, "ci95": None, "n": 0,
                             "sufficient": False},
            "compression_index": {
                "benign": {"value": None, "ci95": None, "n": 0,
                           "sufficient": False},
                "attacked": {"value": None, "ci95": None, "n": 0,
                             "sufficient": False},
            },
        },
        "per_family": {
            "state_poisoning": {
                "n": 1, "n_eligible": 1, "asr": 0.5,
                "asr_ci95": [0.1, 0.9], "refusal_rate": 0.0,
            },
        },
    }
    m.update(over)
    return m


def _write_artifact(tmp, mutate=None):
    a = RunArtifact(
        adapter_name="mock", adapter_version="1", suite="trial-demo",
        dataset_version="0.1.0-demo", config={}, results=[],
        metrics=_metrics(),
    ).seal()
    if mutate:
        mutate(a)
    p = Path(tmp) / "run.json"
    p.write_text(a.to_json(), encoding="utf-8")
    return str(p)


class TestReportEscapesHostileMetrics(unittest.TestCase):
    def test_metric_cells_cannot_smuggle_markup(self):
        with tempfile.TemporaryDirectory() as tmp:
            def poison(a):
                a.metrics["asr_conditional"] = "<script>alert('asr')</script>"
                a.metrics["asr_ci95"] = ["</p><script>alert('ci')</script>", 0.9]
                a.metrics["benign_accuracy"] = "<img src=x onerror=alert('acc')>"
                a.metrics["malformed_rate"] = "<b>zero</b>"
                a.metrics["refusal_rate"] = "<script>alert('ref')</script>"
                a.metrics["ranking_eligible"] = "<i>yes</i>"
                a.metrics["ineligible_by_reason"] = {
                    "<script>alert('reason')</script>": 1,
                }
                fam = a.metrics["per_family"]["state_poisoning"]
                fam["asr"] = "<script>alert('fam')</script>"
                fam["asr_ci95"] = [0.1, "<svg onload=alert('ci2')>"]
                fam["refusal_rate"] = "<script>alert('famref')</script>"
                # S8b A3 sections: hostile values must land inert here too.
                a.metrics["severity_weighted_asr"] = "<script>alert('swasr')</script>"
                a.metrics["refusal_rate_delta"] = "<script>alert('rrd')</script>"
                a.metrics["outcomes_benign"]["approve"] = "<script>alert('ob')</script>"
                cal = a.metrics["calibration"]
                cal["benign"]["ece"] = "<img src=x onerror=alert('ece')>"
                cal["delta_brier"]["delta"] = "<script>alert('db')</script>"
                sp = a.metrics["selective_prediction"]
                sp["augrc"] = "<script>alert('augrc')</script>"
                sp["selective_risk"] = {"<script>alert('cov')</script>": 0.1}
                # The artifact strings render raw in the template.
                a.peira_version = "9.9.9</title><script>alert('v')</script>"
                a.analysis_lock = "</code><script>alert('lock')</script>"
                a.manifest_sha256 = "<script>alert('sha')</script>"
                a.pricing_source = "<script>alert('price')</script>"
            run_path = _write_artifact(tmp, poison)
            out = str(Path(tmp) / "report.html")
            rc = cmd_report(argparse.Namespace(run=run_path, out=out))
            self.assertEqual(rc, 0)
            html = Path(out).read_text(encoding="utf-8")
            for raw in (
                "<script>alert('asr')</script>",
                "</p><script>alert('ci')</script>",
                "<img src=x onerror=alert('acc')>",
                "<b>zero</b>",
                "<i>yes</i>",
                "<script>alert('ref')</script>",
                "<script>alert('reason')</script>",
                "<script>alert('fam')</script>",
                "<svg onload=alert('ci2')>",
                "<script>alert('famref')</script>",
                "<script>alert('swasr')</script>",
                "<script>alert('rrd')</script>",
                "<script>alert('ob')</script>",
                "<img src=x onerror=alert('ece')>",
                "<script>alert('db')</script>",
                "<script>alert('augrc')</script>",
                "<script>alert('cov')</script>",
                "</title><script>alert('v')</script>",
                "</code><script>alert('lock')</script>",
                "<script>alert('sha')</script>",
                "<script>alert('price')</script>",
            ):
                self.assertNotIn(raw, html, f"unescaped payload: {raw}")
            # Spot-check the escaped forms actually render.
            self.assertIn("&lt;script&gt;alert(&#x27;asr&#x27;)&lt;/script&gt;", html)
            self.assertIn("&lt;img src=x onerror=alert(&#x27;acc&#x27;)&gt;", html)

    def test_numeric_cells_still_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc = cmd_report(argparse.Namespace(run=run_path, out=out))
            self.assertEqual(rc, 0)
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("0.5000", html)  # floats: four decimals
            self.assertIn("Ranking eligible: False", html)  # bool passthrough


class TestReportUserErrors(unittest.TestCase):
    def _stderr(self, fn, *args):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = fn(*args)
        return rc, buf.getvalue()

    def test_corrupt_artifact_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("not json{{{", encoding="utf-8")
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report, argparse.Namespace(run=str(bad), out=out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("not a valid run artifact", err)
            self.assertNotIn("Traceback", err)

    def test_wrong_shape_artifact_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"nope": True}), encoding="utf-8")
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report, argparse.Namespace(run=str(bad), out=out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("not a valid run artifact", err)

    def test_valid_json_wrong_nested_shape_exits_1(self):
        # Well-formed JSON with the wrong nested shape: hostile, not
        # corrupt. Metric access happens after parsing, so this
        # exercises the page-construction guard too.
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"metrics": {"n_cases": 1},
                                       "results": []}), encoding="utf-8")
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report, argparse.Namespace(run=str(bad), out=out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("not a valid run artifact", err)
            self.assertNotIn("Traceback", err)

    def test_pre_s8b_schema_gets_actionable_error(self):
        # An artifact sealed before the S8b rewiring is structurally
        # valid but lacks the A3 summary: the report must refuse with
        # an actionable message, not render a half-empty page and not
        # claim the artifact is corrupt.
        with tempfile.TemporaryDirectory() as tmp:
            def strip_a3(a):
                for key in ("calibration", "selective_prediction",
                            "score_diagnostics", "severity_weighted_asr",
                            "outcomes_benign", "outcomes_attacked"):
                    a.metrics.pop(key, None)
            run_path = _write_artifact(tmp, strip_a3)
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report, argparse.Namespace(run=run_path, out=out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("pre-S8b artifact schema", err)
            self.assertIn("re-run the suite", err)

    def test_missing_run_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, err = self._stderr(
                cmd_report,
                argparse.Namespace(run=str(Path(tmp) / "nope.json"),
                                   out=str(Path(tmp) / "r.html")))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("not found", err)

    def test_unwritable_out_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_artifact(tmp)
            out = str(Path(tmp) / "no-such-dir" / "report.html")
            rc, err = self._stderr(
                cmd_report, argparse.Namespace(run=run_path, out=out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("cannot write report to", err)
            self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
