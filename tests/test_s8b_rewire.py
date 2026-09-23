"""S8b: production artifact/report pipeline rewired onto
``peira.metrics.summarize()``.

Covers: the rewired ``_summarize_artifact`` produces the canonical A3
schema, ``expected_scores`` wiring (score diagnostics available vs
unavailable), the report page rendering the new schema (withheld values
as "insufficient data", never 0), and the analysis lock still verifying
after the rewiring.
"""

import json
import unittest
from types import SimpleNamespace

from peira.artifacts import RunArtifact, results_to_dicts
from peira.cli import _report_page
from peira.metrics import CallRecord, PerCaseResult
from peira.runner import _summarize_artifact


def _rec(**kw):
    base = dict(decision="approve", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0, dispatch_index=0,
                malformed=False)
    base.update(kw)
    return CallRecord(**base)


def _r(case_id="c1", **kw):
    benign_kw = {k[7:]: v for k, v in kw.items() if k.startswith("benign_")}
    attacked_kw = {k[9:]: v for k, v in kw.items() if k.startswith("attacked_")}
    rest = {k: v for k, v in kw.items()
            if not (k.startswith("benign_") or k.startswith("attacked_"))}
    base = dict(case_id=case_id, family="state_poisoning", severity="high",
                primitive="choice",
                benign=_rec(**benign_kw), attacked=_rec(**attacked_kw),
                flipped=False, eligible=True, ineligibility_reason="")
    base.update(rest)
    return PerCaseResult(**base)


def _cases(*ids, expected_score=None):
    return [SimpleNamespace(case_id=i,
                            benign=SimpleNamespace(
                                expected_score=expected_score))
            for i in ids]


def _sealed(results, metrics):
    return RunArtifact(
        adapter_name="mock", adapter_version="1", suite="trial-demo",
        dataset_version="0.1.0-demo", config={},
        results=results_to_dicts(results), metrics=metrics,
    ).seal()


class TestRewireSchema(unittest.TestCase):
    def test_new_schema_sections_exist(self):
        results = [_r(f"c{i}", flipped=(i % 3 == 0)) for i in range(35)]
        m = _summarize_artifact(results, ["state_poisoning"],
                                _cases(*[f"c{i}" for i in range(35)]),
                                seed=7)
        for key in ("calibration", "selective_prediction",
                    "score_diagnostics", "severity_weighted_asr",
                    "severity_weighted_asr_ci95", "benign_refusal_rate",
                    "refusal_rate_delta", "outcomes_benign",
                    "outcomes_attacked"):
            self.assertIn(key, m, f"missing section: {key}")
        self.assertIn("delta_brier", m["calibration"])
        self.assertIn("delta_ece", m["calibration"])
        self.assertIn("augrc", m["selective_prediction"])
        # Legacy keys the CLI still reads are preserved.
        for key in ("n_cases", "n_eligible", "asr_conditional", "asr_ci95",
                    "benign_accuracy", "malformed_rate", "refusal_rate",
                    "ineligible_by_reason", "ranking_eligible",
                    "eligibility_notes", "per_family"):
            self.assertIn(key, m, f"missing legacy key: {key}")

    def test_expected_scores_wired_available(self):
        # Score-primitive cases with author references: diagnostics run.
        results = []
        for i in range(35):
            r = _r(f"s{i}", primitive="score",
                   benign_score=0.8, attacked_score=0.6)
            results.append(r)
        cases = _cases(*[f"s{i}" for i in range(35)], expected_score=0.75)
        m = _summarize_artifact(results, ["state_poisoning"], cases, seed=7)
        sd = m["score_diagnostics"]
        self.assertTrue(sd["available"])
        self.assertIsNone(sd["reason"])
        self.assertIsNotNone(sd["benign_mae"]["value"])
        self.assertTrue(sd["benign_mae"]["sufficient"])

    def test_expected_scores_missing_unavailable(self):
        # No cases passed (replay without references, or a bare call):
        # the section reports itself unavailable, never guesses.
        results = [_r(f"c{i}") for i in range(35)]
        m = _summarize_artifact(results, ["state_poisoning"], None, seed=7)
        sd = m["score_diagnostics"]
        self.assertFalse(sd["available"])
        self.assertIn("expected_score", sd["reason"])
        # The reference-free compression index is still reported.
        self.assertIn("benign", sd["compression_index"])
        self.assertIn("attacked", sd["compression_index"])

    def test_runner_function_is_private_not_summarize(self):
        import peira.runner as runner_mod
        self.assertFalse(hasattr(runner_mod, "summarize"),
                         "runner must not expose a public summarize() — "
                         "that collision is what S8b was built to avoid")
        self.assertTrue(callable(runner_mod._summarize_artifact))

    def test_deterministic_for_fixed_seed(self):
        results = [_r(f"c{i}", flipped=(i % 2 == 0)) for i in range(40)]
        cases = _cases(*[f"c{i}" for i in range(40)])
        m1 = _summarize_artifact(results, ["state_poisoning"], cases, seed=7)
        m2 = _summarize_artifact(results, ["state_poisoning"], cases, seed=7)
        self.assertEqual(json.dumps(m1, sort_keys=True),
                         json.dumps(m2, sort_keys=True))


class TestReportNewSchema(unittest.TestCase):
    def test_report_renders_new_schema(self):
        results = [_r(f"c{i}", flipped=(i % 2 == 0)) for i in range(35)]
        cases = _cases(*[f"c{i}" for i in range(35)])
        m = _summarize_artifact(results, ["state_poisoning"], cases, seed=7)
        page = _report_page(_sealed(results, m))
        for heading in ("Calibration", "Selective prediction",
                        "Score diagnostics", "Outcome accounting",
                        "Per-family ASR", "Per-case results"):
            self.assertIn(f"<h2>{heading}</h2>", page)

    def test_withheld_renders_insufficient_data_not_zero(self):
        # 5 cases: every derived metric is withheld (n < 30).
        results = [_r(f"c{i}") for i in range(5)]
        m = _summarize_artifact(results, ["state_poisoning"],
                                _cases(*[f"c{i}" for i in range(5)]), seed=7)
        self.assertIsNone(m["refusal_rate_delta"])
        self.assertIsNone(m["calibration"]["delta_brier"]["delta"])
        page = _report_page(_sealed(results, m))
        self.assertIn("insufficient data", page)
        # Withheld metric values render as "insufficient data" — the
        # refusal-rate delta line must not claim a measured 0.0000.
        self.assertIn(
            "Refusal-rate Δ (attacked−benign): insufficient data", page)
        self.assertIn("ΔBrier (attacked−benign)</td>"
                      "<td>insufficient data", page)

    def test_report_escapes_hostile_a3_values(self):
        results = [_r(f"c{i}") for i in range(35)]
        m = _summarize_artifact(results, ["state_poisoning"],
                                _cases(*[f"c{i}" for i in range(35)]), seed=7)
        m["severity_weighted_asr"] = "<script>alert('swasr')</script>"
        m["calibration"]["delta_ece"]["delta"] = "<b>evil</b>"
        m["selective_prediction"]["augrc"] = "<img src=x onerror=alert(1)>"
        page = _report_page(_sealed(results, m))
        for raw in ("<script>alert('swasr')</script>", "<b>evil</b>",
                    "<img src=x onerror=alert(1)>"):
            self.assertNotIn(raw, page)


class TestLockStillVerifies(unittest.TestCase):
    def test_seal_verify_roundtrip(self):
        results = [_r(f"c{i}", flipped=(i % 3 == 0)) for i in range(35)]
        cases = _cases(*[f"c{i}" for i in range(35)])
        m = _summarize_artifact(results, ["state_poisoning"], cases, seed=7)
        artifact = _sealed(results, m)
        self.assertTrue(artifact.verify())
        # JSON round-trip (what the CLI reads back) still verifies.
        rt = RunArtifact.from_json(artifact.to_json())
        self.assertTrue(rt.verify())
        self.assertIn("calibration", rt.metrics)

    def test_metrics_json_serializable(self):
        results = [_r(f"c{i}") for i in range(10)]
        m = _summarize_artifact(results, ["state_poisoning"],
                                _cases(*[f"c{i}" for i in range(10)]), seed=7)
        json.dumps(m)  # raises TypeError on non-serializable values


if __name__ == "__main__":
    unittest.main()
