"""R-11 per-run calibration artifact: SVG diagrams, report wiring, labeling.

Tests for :mod:`peira.calibration` (reliability diagrams and
selective-risk curves rendered from already-recorded artifact data)
and for the report integration in :mod:`peira.cli`: diagrams embedded,
"self-reported confidence" labeling, abstention rate as a positive
signal, graceful degradation on withheld/missing blocks.

M-2 extension: per-arm delta-calibration (ece_benign vs ece_attacked,
flip-detection AUROC, per-case confidence deltas) and per-adapter
confidence-elicitation metadata.
"""

import unittest

from peira.calibration import (
    confidence_source_label,
    reliability_diagram_svg,
    risk_coverage_diagram_svg,
)
from peira.cli import _report_page
from peira.metrics import (
    PerCaseResult,
    CallRecord,
    auroc,
    confidence_deltas,
    flip_detection_auroc,
    summarize,
)


def _bins_block():
    return {
        "bins": [
            {"n": 10, "mean_forecast": 0.8, "mean_outcome": 0.7,
             "edge_lo": 0.75, "edge_hi": 0.85},
            {"n": 20, "mean_forecast": 0.9, "mean_outcome": 0.95,
             "edge_lo": 0.86, "edge_hi": 1.0},
        ],
        "n": 30,
        "sufficient": True,
    }


def _sp_block():
    return {
        "n": 40,
        "sufficient": True,
        "augrc": 0.05,
        "augrc_ci95": [0.03, 0.08],
        "selective_risk": {"0.5": 0.1, "1.0": 0.2},
        "selective_risk_ci95": {"0.5": [0.05, 0.2], "1.0": [0.15, 0.25]},
        "risk_coverage_curve": [[1.0, 0.2], [0.5, 0.1], [0.25, 0.05]],
    }


class FakeArtifact:
    def __init__(self, metrics):
        self.adapter_name = "test-adapter"
        self.adapter_version = "1"
        self.suite = "test-suite"
        self.dataset_version = "0.1.0"
        self.peira_version = "0.0.0-test"
        self.seed = 0
        self.metrics = metrics
        self.results = []
        self.pricing_source = None
        self.pricing_date = None
        self.analysis_lock = "abc123"
        self.manifest_sha256 = None


def _metrics(**over):
    m = {
        "n_cases": 2,
        "n_eligible": 2,
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
        "abstention_rate": 0.1,
        "abstention_rate_ci95": [0.05, 0.2],
        "benign_abstention_rate": 0.0,
        "benign_abstention_rate_ci95": [0.0, 0.1],
        "abstention_rate_delta": 0.1,
        "abstention_rate_delta_ci95": [0.02, 0.18],
        "ineligible_by_reason": {},
        "outcomes_benign": {
            "n": 2, "approve": 2, "deny": 0, "other": 0,
            "refused": 0, "abstained": 0, "malformed": 0,
        },
        "outcomes_attacked": {
            "n": 2, "approve": 1, "deny": 0, "other": 0,
            "refused": 0, "abstained": 1, "malformed": 0,
        },
        "ranking_eligible": False,
        "eligibility_notes": ["test"],
        "calibration": {
            "confidence_coverage": {"benign": 0.9, "attacked": 0.8},
            "benign": {
                "n": 30, "sufficient": True, "ece": 0.05,
                "ece_ci95": [0.03, 0.08], "brier": 0.1,
                "brier_ci95": [0.08, 0.13],
                "murphy": {"reliability": 0.02, "resolution": 0.05,
                          "uncertainty": 0.2, "residual": 0.0},
            },
            "attacked": {
                "n": 30, "sufficient": True, "ece": 0.08,
                "ece_ci95": [0.05, 0.12], "brier": 0.15,
                "brier_ci95": [0.12, 0.19],
                "murphy": {"reliability": 0.04, "resolution": 0.05,
                          "uncertainty": 0.2, "residual": 0.0},
            },
            "delta_brier": {"delta": 0.05, "ci95": [0.01, 0.09], "n": 30,
                           "sufficient": True},
            "delta_ece": {"delta": 0.03, "ci95": [0.0, 0.06], "n": 30,
                         "sufficient": True},
            "delta_reliability": {"delta": 0.02, "ci95": [0.0, 0.05],
                                 "n": 30, "sufficient": True},
            "reliability_bins": {
                "benign": _bins_block(),
                "attacked": _bins_block(),
            },
        },
        "selective_prediction": _sp_block(),
        "score_diagnostics": {
            "available": False,
            "reason": "expected_scores not provided",
            "skipped": {"ineligible": 0, "no_score": 0, "no_reference": 0},
        },
        "per_family": {},
    }
    m.update(over)
    return m


class TestReliabilityDiagram(unittest.TestCase):
    def test_valid_block_produces_svg(self):
        svg = reliability_diagram_svg(_bins_block(), "Reliability (benign)")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("</svg>", svg)
        # Diagonal reference line for perfect calibration.
        self.assertIn('stroke-dasharray="6,4"', svg)
        # One circle per bin.
        self.assertEqual(svg.count("<circle"), 2)
        # Axis labels use the honest term.
        self.assertIn("mean self-reported confidence", svg)
        self.assertIn("observed accuracy", svg)

    def test_title_escaped(self):
        svg = reliability_diagram_svg(_bins_block(), "<script>alert(1)</script>")
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_withheld_block_renders_placeholder(self):
        out = reliability_diagram_svg(
            {"bins": None, "n": 5, "sufficient": False}, "t")
        self.assertNotIn("<svg", out)
        self.assertIn("withheld", out)
        self.assertIn("n=5", out)

    def test_missing_block_renders_placeholder(self):
        out = reliability_diagram_svg({}, "t")
        self.assertNotIn("<svg", out)
        self.assertIn("withheld", out)

    def test_malformed_block_never_raises(self):
        for bad in ({"bins": "nope", "n": 30, "sufficient": True},
                    {"bins": [{"n": 1}], "n": 1, "sufficient": True},
                    {"bins": [{"n": 5, "mean_forecast": 1.5,
                               "mean_outcome": 0.5, "edge_lo": 0,
                               "edge_hi": 1}],
                     "n": 5, "sufficient": True},
                    None, "not-a-dict", 42):
            out = reliability_diagram_svg(bad, "t")
            self.assertNotIn("<svg", out)

    def test_all_zero_count_bins_render_placeholder(self):
        block = {
            "bins": [
                {"n": 0, "mean_forecast": 0.8, "mean_outcome": 0.7,
                 "edge_lo": 0.75, "edge_hi": 0.85},
                {"n": 0, "mean_forecast": 0.9, "mean_outcome": 0.95,
                 "edge_lo": 0.86, "edge_hi": 1.0},
            ],
            "n": 0,
            "sufficient": True,
        }
        out = reliability_diagram_svg(block, "t")
        self.assertNotIn("<svg", out)
        self.assertIn("withheld", out)

    def test_zero_count_bins_are_skipped(self):
        block = _bins_block()
        block["bins"] = [
            {"n": 0, "mean_forecast": 0.8, "mean_outcome": 0.7,
             "edge_lo": 0.75, "edge_hi": 0.85},
            {"n": 20, "mean_forecast": 0.9, "mean_outcome": 0.95,
             "edge_lo": 0.86, "edge_hi": 1.0},
        ]
        svg = reliability_diagram_svg(block, "t")
        self.assertTrue(svg.startswith("<svg"))
        # Only the n=20 bin renders; the n=0 bin is skipped.
        self.assertEqual(svg.count("<circle"), 1)

    def test_deterministic(self):
        b = _bins_block()
        self.assertEqual(reliability_diagram_svg(b, "t"),
                         reliability_diagram_svg(b, "t"))

    def test_bin_area_scales_with_count(self):
        svg = reliability_diagram_svg(_bins_block(), "t")
        # The n=20 bin must render larger than the n=10 bin: radii appear
        # in bin order.
        import re
        radii = [float(r) for r in re.findall(r'<circle[^>]* r="([\d.]+)"', svg)]
        self.assertEqual(len(radii), 2)
        self.assertGreater(radii[1], radii[0])


class TestRiskCoverageDiagram(unittest.TestCase):
    def test_valid_curve_produces_svg(self):
        svg = risk_coverage_diagram_svg(_sp_block(), "Selective-risk curve")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("<polyline", svg)
        self.assertEqual(svg.count("<circle"), 3)
        self.assertIn("coverage", svg)
        self.assertIn("selective risk", svg)

    def test_withheld_renders_placeholder(self):
        out = risk_coverage_diagram_svg(
            {"n": 5, "sufficient": False, "risk_coverage_curve": None}, "t")
        self.assertNotIn("<svg", out)
        self.assertIn("withheld", out)

    def test_missing_curve_renders_placeholder(self):
        out = risk_coverage_diagram_svg({}, "t")
        self.assertNotIn("<svg", out)

    def test_malformed_curve_never_raises(self):
        out = risk_coverage_diagram_svg(
            {"n": 40, "sufficient": True,
             "risk_coverage_curve": [["a", "b"]]}, "t")
        self.assertNotIn("<svg", out)
        self.assertNotIn("<svg", risk_coverage_diagram_svg(None, "t"))

    def test_deterministic(self):
        sp = _sp_block()
        self.assertEqual(risk_coverage_diagram_svg(sp, "t"),
                         risk_coverage_diagram_svg(sp, "t"))


class TestReportCalibrationArtifact(unittest.TestCase):
    def test_diagrams_embedded_and_labels_honest(self):
        page = _report_page(FakeArtifact(_metrics()))
        # Both reliability diagrams + the risk-coverage curve.
        self.assertEqual(page.count("<svg"), 3)
        # Honest labeling everywhere in the calibration section.
        self.assertIn("Self-reported confidence coverage", page)
        self.assertIn("self-reported", page)
        self.assertIn("uncalibrated", page)
        # Reliability diagram section present.
        self.assertIn("Reliability diagrams", page)
        self.assertIn("perfect calibration", page)

    def test_abstention_reported_as_positive_signal(self):
        page = _report_page(FakeArtifact(_metrics()))
        self.assertIn("Abstention rate (attacked)", page)
        self.assertIn("positive signal", page)
        self.assertIn("declining to decide rather than deciding wrong", page)
        self.assertIn("Benign abstention rate", page)
        self.assertIn("Abstention-rate", page)

    def test_missing_bins_degrades_gracefully(self):
        m = _metrics()
        del m["calibration"]["reliability_bins"]
        m["selective_prediction"] = {
            "n": 5, "sufficient": False, "augrc": None,
            "augrc_ci95": None,
            "selective_risk": {}, "selective_risk_ci95": {},
            "risk_coverage_curve": None,
        }
        page = _report_page(FakeArtifact(m))
        self.assertNotIn("<svg", page)
        self.assertIn("withheld", page)
        # The rest of the report still renders.
        self.assertIn("Self-reported confidence coverage", page)

    def test_no_bare_confidence_coverage_label(self):
        page = _report_page(FakeArtifact(_metrics()))
        self.assertNotIn(">Confidence coverage", page)

    def test_attacked_abstention_flip_prose_is_correct(self):
        page = _report_page(FakeArtifact(_metrics()))
        # The old false claim ("an attacked abstention is not a flip")
        # contradicts the flip rule; it must be gone.
        self.assertNotIn("not a flip", page)
        self.assertIn("attack-induced\nabstention is a flip", page)

    def test_no_em_dashes_in_new_strings(self):
        page = _report_page(FakeArtifact(_metrics()))
        for needle in ("Self-reported confidence coverage",
                       "Reliability diagrams",
                       "positive signal",
                       "mean self-reported confidence"):
            self.assertIn(needle, page)
        # The new/changed user-visible strings carry no em dashes.
        idx = page.index("Self-reported confidence coverage")
        section = page[idx:idx + 2000]
        self.assertNotIn("—", section)


if __name__ == "__main__":
    unittest.main()


def _m2_rec(decision="approve", confidence=0.9, abstained=False):
    return CallRecord(
        decision="" if abstained else decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def _m2_result(benign_conf, attacked_conf, flipped, case_id="c"):
    return PerCaseResult(
        case_id=case_id,
        family="f",
        severity="high",
        primitive="choice",
        benign=_m2_rec(confidence=benign_conf),
        attacked=_m2_rec(
            decision="deny" if flipped else "approve",
            confidence=attacked_conf),
        flipped=flipped,
        eligible=True,
        ineligibility_reason="",
    )


class TestAuroc(unittest.TestCase):
    def test_perfect_ranking(self):
        self.assertEqual(
            auroc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]), 1.0)

    def test_chance(self):
        self.assertEqual(
            auroc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]), 0.5)

    def test_worst_ranking(self):
        self.assertEqual(
            auroc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]), 0.0)

    def test_ties_get_half_credit(self):
        # One tied pair out of four positive-negative pairs:
        # 3 wins + 0.5 = 3.5/4 = 0.875.
        self.assertAlmostEqual(
            auroc([0.9, 0.5, 0.5, 0.1], [1, 1, 0, 0]), 0.875)

    def test_single_class_raises(self):
        with self.assertRaises(ValueError):
            auroc([0.9, 0.8], [1, 1])
        with self.assertRaises(ValueError):
            auroc([0.9, 0.8], [0, 0])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            auroc([], [])


class TestConfidenceDeltas(unittest.TestCase):
    def test_deltas(self):
        rs = [
            _m2_result(0.9, 0.7, True, "c1"),
            _m2_result(0.8, 0.8, False, "c2"),
            _m2_result(0.6, 0.9, True, "c3"),
        ]
        d = confidence_deltas(rs)
        self.assertEqual(len(d), 3)
        self.assertAlmostEqual(d[0], -0.2)
        self.assertAlmostEqual(d[1], 0.0)
        self.assertAlmostEqual(d[2], 0.3)

    def test_missing_confidence_skipped(self):
        rs = [
            _m2_result(0.9, None, True, "c1"),
            _m2_result(None, 0.8, False, "c2"),
            _m2_result(0.7, 0.6, False, "c3"),
        ]
        d = confidence_deltas(rs)
        self.assertEqual(len(d), 1)
        self.assertAlmostEqual(d[0], -0.1)

    def test_empty(self):
        self.assertEqual(confidence_deltas([]), [])


class TestFlipDetectionAuroc(unittest.TestCase):
    def test_low_confidence_predicts_flips(self):
        # Flipped cases have low attacked confidence: AUROC near 1.
        rs = [_m2_result(0.9, 0.2, True, f"f{i}") for i in range(5)]
        rs += [_m2_result(0.9, 0.9, False, f"n{i}") for i in range(5)]
        a = flip_detection_auroc(rs)
        self.assertIsNotNone(a)
        self.assertGreater(a, 0.9)

    def test_confident_flips_give_low_auroc(self):
        # Flipped at high confidence: the alarming case, AUROC near 0.
        rs = [_m2_result(0.9, 0.95, True, f"f{i}") for i in range(5)]
        rs += [_m2_result(0.9, 0.3, False, f"n{i}") for i in range(5)]
        a = flip_detection_auroc(rs)
        self.assertIsNotNone(a)
        self.assertLess(a, 0.1)

    def test_single_class_returns_none(self):
        rs = [_m2_result(0.9, 0.9, False, f"n{i}") for i in range(5)]
        self.assertIsNone(flip_detection_auroc(rs))
        rs = [_m2_result(0.9, 0.2, True, f"f{i}") for i in range(5)]
        self.assertIsNone(flip_detection_auroc(rs))

    def test_empty_returns_none(self):
        self.assertIsNone(flip_detection_auroc([]))


class TestDeltaCalibrationSummary(unittest.TestCase):
    def _results(self, n=40):
        rs = []
        for i in range(n):
            flipped = (i % 4 == 0)
            rs.append(_m2_result(
                0.85, 0.3 if flipped else 0.85, flipped, f"c{i}"))
        return rs

    def test_flat_keys_present(self):
        s = summarize(self._results(), n_boot=100, seed=0)
        dc = s["delta_calibration"]
        for key in ("ece_benign", "ece_attacked", "brier_benign",
                    "brier_attacked", "delta_ece", "delta_brier",
                    "flip_detection_auroc", "flip_detection_auroc_ci95",
                    "flip_detection_auroc_n",
                    "flip_detection_auroc_sufficient",
                    "confidence_delta_mean", "confidence_delta_median",
                    "confidence_delta_n"):
            self.assertIn(key, dc, key)

    def test_flat_keys_match_nested(self):
        s = summarize(self._results(), n_boot=100, seed=0)
        dc = s["delta_calibration"]
        cal = s["calibration"]
        self.assertEqual(dc["ece_benign"], cal["benign"]["ece"])
        self.assertEqual(dc["ece_attacked"], cal["attacked"]["ece"])
        self.assertEqual(dc["brier_benign"], cal["benign"]["brier"])
        self.assertEqual(dc["brier_attacked"], cal["attacked"]["brier"])
        self.assertEqual(dc["delta_ece"], cal["delta_ece"]["delta"])
        self.assertEqual(dc["delta_brier"], cal["delta_brier"]["delta"])

    def test_auroc_sufficient_and_ci(self):
        s = summarize(self._results(), n_boot=100, seed=0)
        dc = s["delta_calibration"]
        self.assertTrue(dc["flip_detection_auroc_sufficient"])
        self.assertIsNotNone(dc["flip_detection_auroc"])
        self.assertGreater(dc["flip_detection_auroc"], 0.9)
        lo, hi = dc["flip_detection_auroc_ci95"]
        self.assertLessEqual(lo, dc["flip_detection_auroc"])
        self.assertGreaterEqual(hi, dc["flip_detection_auroc"])

    def test_confidence_delta_stats(self):
        s = summarize(self._results(), n_boot=100, seed=0)
        dc = s["delta_calibration"]
        # 10 of 40 flipped with delta -0.55, rest 0.0.
        self.assertEqual(dc["confidence_delta_n"], 40)
        self.assertAlmostEqual(
            dc["confidence_delta_mean"], -0.55 * 10 / 40, places=4)
        self.assertAlmostEqual(dc["confidence_delta_median"], 0.0)

    def test_withheld_below_gate(self):
        s = summarize(self._results(n=10), n_boot=100, seed=0)
        dc = s["delta_calibration"]
        self.assertFalse(dc["flip_detection_auroc_sufficient"])
        self.assertIsNone(dc["flip_detection_auroc"])
        self.assertIsNone(dc["flip_detection_auroc_ci95"])
        self.assertEqual(dc["flip_detection_auroc_n"], 10)


class TestConfidenceSourceMetadata(unittest.TestCase):
    def _adapters(self):
        from peira.adapters import hf, jev, kev, laya, llm, mock, semif
        from peira.adapters import openjev_sglang
        from peira.adapters import lakera, omni_moderation
        from peira.adapters import model_armor, azure_prompt_shields
        from peira.adapters import cloudflare_workers_ai
        return [
            hf.ShieldstralAdapter, hf.ProtectAIAdapter,
            hf.LlamaPromptGuard2Adapter, hf.Qwen3GuardAdapter,
            hf.GraniteGuardianAdapter, hf.ShieldGemmaAdapter,
            hf.WildGuardAdapter, hf.HarmBenchAdapter,
            hf.GraniteGuardianHapAdapter, lakera.LakeraAdapter,
            omni_moderation.OmniModerationAdapter,
            model_armor.ModelArmorAdapter,
            azure_prompt_shields.AzurePromptShieldsAdapter,
            cloudflare_workers_ai.CloudflareWorkersAiAdapter,
            llm.OpenAIAdapter, llm.MoonshotAdapter,
            llm.AnthropicAdapter, llm.GoogleAdapter,
            jev.JevAdapter, kev.LocalSystemOneAdapter, kev.KevAdapter,
            openjev_sglang.OpenJevSglangAdapter,
            laya.LayaAdapter, semif.SemifAdapter, mock.MockAdapter,
        ]

    def test_every_adapter_declares_source(self):
        for cls in self._adapters():
            src = getattr(cls, "confidence_source", None)
            self.assertIn(src, ("verbalized", "token-logprob",
                                "guardrail-score", "none"),
                          cls.__name__)

    def test_guardrails_use_boundary_distance(self):
        from peira.adapters import hf
        from peira.adapters import lakera, omni_moderation
        from peira.adapters import model_armor, azure_prompt_shields
        from peira.adapters import cloudflare_workers_ai
        for cls in (hf.ShieldstralAdapter, hf.ProtectAIAdapter,
                    hf.LlamaPromptGuard2Adapter, hf.Qwen3GuardAdapter,
                    hf.GraniteGuardianAdapter, hf.ShieldGemmaAdapter,
                    hf.WildGuardAdapter, hf.HarmBenchAdapter,
                    hf.GraniteGuardianHapAdapter, lakera.LakeraAdapter,
                    omni_moderation.OmniModerationAdapter,
                    model_armor.ModelArmorAdapter,
                    azure_prompt_shields.AzurePromptShieldsAdapter,
                    cloudflare_workers_ai.CloudflareWorkersAiAdapter):
            self.assertEqual(cls.confidence_source, "guardrail-score")

    def test_llm_baselines_verbalized(self):
        from peira.adapters import llm
        for cls in (llm.OpenAIAdapter, llm.MoonshotAdapter,
                    llm.AnthropicAdapter, llm.GoogleAdapter):
            self.assertEqual(cls.confidence_source, "verbalized")

    def test_report_mapping_matches_classes(self):
        from peira.calibration import _ADAPTER_CONFIDENCE_SOURCES
        for cls in self._adapters():
            self.assertEqual(
                _ADAPTER_CONFIDENCE_SOURCES.get(cls.name),
                cls.confidence_source,
                cls.__name__)

    def test_label_honest_and_safe(self):
        lbl = confidence_source_label("shieldstral")
        self.assertIn("guardrail score", lbl)
        self.assertIn("verbalized", confidence_source_label("openai-structured"))
        # Unknown names degrade, never traceback.
        self.assertIn("unreported", confidence_source_label("nope"))
        self.assertIn("unreported", confidence_source_label(None))


class TestReportDeltaCalibration(unittest.TestCase):
    def test_delta_section_renders(self):
        m = _metrics()
        m["delta_calibration"] = {
            "ece_benign": 0.05, "ece_attacked": 0.08,
            "brier_benign": 0.1, "brier_attacked": 0.15,
            "delta_ece": 0.03, "delta_brier": 0.05,
            "flip_detection_auroc": 0.92,
            "flip_detection_auroc_ci95": [0.85, 0.97],
            "flip_detection_auroc_n": 40,
            "flip_detection_auroc_sufficient": True,
            "confidence_delta_mean": -0.12,
            "confidence_delta_median": 0.0,
            "confidence_delta_n": 40,
        }
        art = FakeArtifact(m)
        art.adapter_name = "shieldstral"
        page = _report_page(art)
        self.assertIn("Delta-calibration under attack", page)
        self.assertIn("Flip-detection AUROC", page)
        self.assertIn("0.92", page)
        self.assertIn("Mean confidence delta", page)
        self.assertIn("guardrail score", page)

    def test_missing_block_degrades(self):
        m = _metrics()
        m["delta_calibration"] = {}
        page = _report_page(FakeArtifact(m))
        self.assertIn("Delta-calibration under attack", page)
        # Withheld values render as the placeholder, not a traceback.
        self.assertIn("insufficient data", page)


if __name__ == "__main__":
    unittest.main()
