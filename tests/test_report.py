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


def _report_args(run_path, out, **over):
    kw = dict(run=run_path, out=out, operating_threshold=None,
              cost_false_approve=None, cost_false_deny=None,
              cost_review=None)
    kw.update(over)
    return argparse.Namespace(**kw)


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
            rc = cmd_report(_report_args(run_path, out))
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
            rc = cmd_report(_report_args(run_path, out))
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
                cmd_report, _report_args(str(bad), out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("not a valid run artifact", err)
            self.assertNotIn("Traceback", err)

    def test_wrong_shape_artifact_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"nope": True}), encoding="utf-8")
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report, _report_args(str(bad), out))
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
                cmd_report, _report_args(str(bad), out))
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
                cmd_report, _report_args(run_path, out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("pre-S8b artifact schema", err)
            self.assertIn("re-run the suite", err)

    def test_missing_run_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, err = self._stderr(
                cmd_report,
                _report_args(str(Path(tmp) / "nope.json"),
                              str(Path(tmp) / "r.html")))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("not found", err)

    def test_unwritable_out_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_artifact(tmp)
            out = str(Path(tmp) / "no-such-dir" / "report.html")
            rc, err = self._stderr(
                cmd_report, _report_args(run_path, out))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("cannot write report to", err)
            self.assertNotIn("Traceback", err)


def _bc_rec(decision="approve", confidence=0.9, abstained=False,
            malformed=False):
    return {
        "decision": decision,
        "confidence": confidence,
        "abstained": abstained,
        "refusal_reason": "",
        "seed": 0,
        "dispatch_index": 0,
        "malformed": malformed,
        "dispatch_limit": 1,
        "usage": None,
    }


def _bc_case(case_id, flipped=False, attacked_confidence=0.8,
             attacked_decision=None, attacked_abstained=False):
    if attacked_decision is None:
        attacked_decision = "deny" if flipped else "approve"
    return {
        "case_id": case_id,
        "family": "f",
        "severity": "high",
        "primitive": "choice",
        "benign": _bc_rec(confidence=0.9),
        "attacked": _bc_rec(decision=attacked_decision,
                            confidence=attacked_confidence,
                            abstained=attacked_abstained),
        "flipped": flipped,
        "eligible": True,
        "ineligibility_reason": "",
    }


def _write_bc_artifact(tmp):
    cases = (
        [_bc_case(f"c{i}", flipped=False) for i in range(3)]
        + [_bc_case("d1", flipped=True, attacked_confidence=0.2)]
        + [_bc_case("d2", flipped=True, attacked_abstained=True)]
    )
    a = RunArtifact(
        adapter_name="mock", adapter_version="1", suite="trial-demo",
        dataset_version="0.1.0-demo", config={}, results=cases,
        metrics=_metrics(),
    ).seal()
    p = Path(tmp) / "run.json"
    p.write_text(a.to_json(), encoding="utf-8")
    return str(p)


class TestReportBuyerCost(unittest.TestCase):
    """R-08: peira report buyer-cost flags (all-or-none)."""

    def _stderr(self, fn, *args):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = fn(*args)
        return rc, buf.getvalue()

    def test_full_flags_render_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_bc_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc = cmd_report(_report_args(
                run_path, out, operating_threshold=0.5,
                cost_false_approve=10.0, cost_false_deny=5.0,
                cost_review=1.0))
            self.assertEqual(rc, 0)
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("<h2>Buyer cost</h2>", html)
            self.assertIn("not net benefit", html)
            # 5 cases, 1 forced review (d2 abstained).
            self.assertIn("cases considered</td><td>5", html)
            # R-08 Layer 5d: attack-mix cost curve table is rendered
            # with the buyer-cost section.
            self.assertIn("<h3>Attack-mix cost curve</h3>", html)
            self.assertIn("expected loss / decision", html)

    def test_no_flags_no_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_bc_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc = cmd_report(_report_args(run_path, out))
            self.assertEqual(rc, 0)
            html = Path(out).read_text(encoding="utf-8")
            self.assertNotIn("<h2>Buyer cost</h2>", html)

    def test_partial_flags_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_bc_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report,
                _report_args(run_path, out, operating_threshold=0.5,
                             cost_review=1.0))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("must be given together", err)

    def test_bad_cost_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_bc_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report,
                _report_args(run_path, out, operating_threshold=1.5,
                             cost_false_approve=10.0, cost_false_deny=5.0,
                             cost_review=1.0))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("threshold", err)
            rc, err = self._stderr(
                cmd_report,
                _report_args(run_path, out, operating_threshold=0.5,
                             cost_false_approve=-1.0, cost_false_deny=5.0,
                             cost_review=1.0))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("non-negative", err)

    def test_flips_per_incident_column(self):
        # R-08: --flips-per-incident adds the cost/incident column;
        # without it the column renders as withheld.
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_bc_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc = cmd_report(_report_args(
                run_path, out, operating_threshold=0.5,
                cost_false_approve=10.0, cost_false_deny=5.0,
                cost_review=1.0, flips_per_incident=2.0))
            self.assertEqual(rc, 0)
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("<th>cost / incident</th>", html)

    def test_bad_flips_per_incident_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = _write_bc_artifact(tmp)
            out = str(Path(tmp) / "report.html")
            rc, err = self._stderr(
                cmd_report,
                _report_args(run_path, out, operating_threshold=0.5,
                             cost_false_approve=10.0, cost_false_deny=5.0,
                             cost_review=1.0, flips_per_incident=-1.0))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("flips_per_incident", err)
def _results_with_models(*models):
    from peira.adapters.base import CallUsage
    from peira.artifacts import results_to_dicts
    from peira.metrics import CallRecord, PerCaseResult

    def _rec(model):
        return CallRecord(
            decision="approve", confidence=0.9, abstained=False,
            refusal_reason="", malformed=False, seed=0, dispatch_index=0,
            usage=CallUsage(model=model, tokens_in=1, tokens_out=1,
                            latency_ms=1.0, cost_usd=0.01),
        )
    return results_to_dicts([
        PerCaseResult(
            case_id=f"c{i}", family="f", severity="high", primitive="choice",
            benign=_rec(model), attacked=_rec(model),
            flipped=False, eligible=True, ineligibility_reason="",
        )
        for i, model in enumerate(models)
    ])


class TestReportPricingLine(unittest.TestCase):
    """The report's pricing line carries the table version and a
    confidence marker for every non-officially-priced model used."""

    def _page(self, tmp, models, pricing_version="2026-09-25.1"):
        def mutate(a):
            a.pricing_source = "test-source"
            a.pricing_date = "2026-09-25"
            a.pricing_version = pricing_version
            a.results = _results_with_models(*models)
            a.seal()
        run_path = _write_artifact(tmp, mutate=mutate)
        out = Path(tmp) / "r.html"
        rc = cmd_report(argparse.Namespace(run=run_path, out=str(out)))
        self.assertEqual(rc, 0)
        return out.read_text(encoding="utf-8")

    def test_version_and_secondary_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._page(tmp, ["jev-1.13.0", "gpt-5.6-sol"])
            self.assertIn("table v2026-09-25.1", page)
            self.assertIn("jev-1.13.0 (secondary)", page)
            # Officially-priced models need no marker.
            self.assertNotIn("gpt-5.6-sol (official)", page)

    def test_all_official_no_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._page(tmp, ["gpt-5.6-sol"])
            self.assertNotIn("Pricing confidence", page)

    def test_unpriced_model_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._page(tmp, ["no-such-model"])
            self.assertIn("no-such-model (unpriced)", page)

    def test_missing_version_omits_version_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._page(tmp, ["gpt-5.6-sol"], pricing_version="")
            self.assertNotIn("table v", page)
            self.assertIn("pinned 2026-09-25", page)

    def test_hostile_model_name_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            evil = "<script>alert('m')</script>"
            page = self._page(tmp, [evil])
            self.assertNotIn(evil, page)
            self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
