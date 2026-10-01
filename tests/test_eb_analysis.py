"""Tests for peira.eb_analysis: EB-23, EB-40, EB-7, EB-10 (Program A).

Every test must be able to fail for a real reason: they pin exact
numbers, exact withholding boundaries, and exact error paths, not
just "it runs".
"""

import argparse
import json
import os
import tempfile
import unittest

from peira.adapters.base import CallUsage
from peira.eb_analysis import (
    AdapterTaxInput,
    confidence_erosion,
    length_confound_diagnostics,
    length_diagnostics_block,
    length_report_text,
    length_sensitivity,
    robustness_tax,
)
from peira.metrics import CallRecord, PerCaseResult, summarize


def _usage(tokens_out):
    return CallUsage(model="m", tokens_in=10, tokens_out=tokens_out,
                     cost_usd=0.0, latency_ms=1.0)


def _rec(decision="approve", confidence=0.9, tokens_out=None):
    return CallRecord(
        decision=decision,
        confidence=confidence,
        abstained=False,
        refusal_reason="",
        usage=_usage(tokens_out) if tokens_out is not None else None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def _r(family="f", flipped=False, eligible=True,
       benign_conf=0.9, attacked_conf=0.7,
       benign_tokens=None, attacked_tokens=None,
       benign_decision="approve", attacked_decision=None):
    if attacked_decision is None:
        attacked_decision = "deny" if flipped else benign_decision
    return PerCaseResult(
        case_id="x",
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec(decision=benign_decision,
                    confidence=benign_conf,
                    tokens_out=benign_tokens),
        attacked=_rec(decision=attacked_decision,
                      confidence=attacked_conf,
                      tokens_out=attacked_tokens),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "excluded",
    )


class ConfidenceErosionTest(unittest.TestCase):
    def test_mean_p50_p90_are_exact_on_known_erosions(self):
        # erosions 0.1..0.5: mean 0.3, p50 0.3, p90 0.5
        results = [
            _r(family="f", benign_conf=0.9, attacked_conf=0.9 - e)
            for e in (0.1, 0.2, 0.3, 0.4, 0.5)
        ] * 8  # 40 observations, above the 30 floor
        rep = confidence_erosion(results)
        overall = rep["overall"]
        self.assertTrue(overall["sufficient"])
        self.assertAlmostEqual(overall["mean"], 0.3, places=9)
        self.assertAlmostEqual(overall["p50"], 0.3, places=9)
        self.assertAlmostEqual(overall["p90"], 0.5, places=9)

    def test_flips_and_missing_confidences_excluded(self):
        results = (
            [_r(family="f", benign_conf=0.9, attacked_conf=0.5)] * 30
            + [_r(family="f", flipped=True, benign_conf=0.9,
                  attacked_conf=0.1)] * 10
            + [_r(family="f", benign_conf=None, attacked_conf=0.5)] * 10
        )
        rep = confidence_erosion(results)
        self.assertEqual(rep["overall"]["n"], 30)
        self.assertAlmostEqual(rep["overall"]["mean"], 0.4, places=9)

    def test_withheld_below_30(self):
        results = [_r(family="f", benign_conf=0.9, attacked_conf=0.5)
                   ] * 29
        rep = confidence_erosion(results)
        self.assertFalse(rep["overall"]["sufficient"])
        self.assertIsNone(rep["overall"]["mean"])

    def test_boundary_30_is_reported(self):
        results = [_r(family="f", benign_conf=0.9, attacked_conf=0.5)
                   ] * 30
        rep = confidence_erosion(results)
        self.assertTrue(rep["overall"]["sufficient"])
        self.assertAlmostEqual(rep["overall"]["mean"], 0.4, places=9)

    def test_near_flip_boundary_is_inclusive(self):
        # erosion exactly 0.5 counts as near-flip (>=, not >)
        results = (
            [_r(family="f", benign_conf=1.0, attacked_conf=0.5)] * 20
            + [_r(family="f", benign_conf=0.9, attacked_conf=0.5)] * 20
        )
        rep = confidence_erosion(results)
        self.assertAlmostEqual(rep["overall"]["near_flip_fraction"],
                               0.5, places=9)
        lo, hi = rep["overall"]["near_flip_ci95"]
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_histogram_bins_are_fixed_width(self):
        results = [_r(family="f", benign_conf=0.9, attacked_conf=0.5)
                   ] * 30
        rep = confidence_erosion(results)
        hist = rep["overall"]["histogram"]
        self.assertEqual(len(hist["counts"]), 10)
        self.assertEqual(hist["bin_edges"][0], -1.0)
        self.assertEqual(hist["bin_edges"][1], -0.8)
        self.assertEqual(hist["bin_edges"][-1], 1.0)
        # erosion 0.4 lands in bin [0.4, 0.6): index 7
        self.assertEqual(hist["counts"][7], 30)
        self.assertEqual(sum(hist["counts"]), 30)

    def test_negative_erosion_counted(self):
        # attacked MORE confident than benign: negative erosion
        results = [_r(family="f", benign_conf=0.5, attacked_conf=0.9)
                   ] * 30
        rep = confidence_erosion(results)
        self.assertAlmostEqual(rep["overall"]["mean"], -0.4, places=9)


class RobustnessTaxTest(unittest.TestCase):
    def _inputs(self):
        return [
            AdapterTaxInput(
                adapter="a", asr=0.10, asr_ci=(0.08, 0.12),
                benign_accuracy=0.95, benign_accuracy_ci=(0.93, 0.97),
                ece=0.05, ece_ci=(0.04, 0.06), n_cases=100),
            AdapterTaxInput(
                adapter="b", asr=0.20, asr_ci=(0.17, 0.23),
                benign_accuracy=0.90, benign_accuracy_ci=(0.87, 0.93),
                ece=0.08, ece_ci=(0.06, 0.10), n_cases=100),
            AdapterTaxInput(
                adapter="c", asr=0.30, asr_ci=(0.27, 0.33),
                benign_accuracy=0.85, benign_accuracy_ci=(0.82, 0.88),
                ece=0.12, ece_ci=(0.10, 0.14), n_cases=100),
        ]

    def test_tax_arithmetic_against_frontier(self):
        rep = robustness_tax(self._inputs())
        per = rep["per_adapter"]
        # frontier: best acc 0.95 (a), best ece 0.05 (a)
        self.assertAlmostEqual(per["a"]["accuracy_tax"], 0.0, places=9)
        self.assertAlmostEqual(per["a"]["calibration_tax"], 0.0,
                               places=9)
        self.assertAlmostEqual(per["a"]["combined_tax"], 0.0, places=9)
        self.assertAlmostEqual(per["b"]["accuracy_tax"], 0.05, places=9)
        self.assertAlmostEqual(per["b"]["calibration_tax"], 0.03,
                               places=9)
        self.assertAlmostEqual(per["b"]["combined_tax"], 0.08, places=9)

    def test_frontier_held_fixed_in_cis(self):
        rep = robustness_tax(self._inputs())
        per = rep["per_adapter"]
        # b's accuracy tax CI comes from b's own acc CI only:
        # 0.95 - [0.87, 0.93] = [0.02, 0.08]
        self.assertEqual(per["b"]["accuracy_tax_ci95"], [0.02, 0.08])
        # b's calibration tax CI: [0.06, 0.10] - 0.05 = [0.01, 0.05]
        self.assertEqual(per["c"]["calibration_tax_ci95"], [0.05, 0.09])

    def test_missing_component_withholds_that_tax(self):
        inputs = self._inputs()
        inputs.append(AdapterTaxInput(adapter="d", asr=0.15,
                                     asr_ci=(0.12, 0.18),
                                     benign_accuracy=None,
                                     benign_accuracy_ci=None,
                                     ece=0.06, ece_ci=(0.05, 0.07),
                                     n_cases=100))
        rep = robustness_tax(inputs)
        d = rep["per_adapter"]["d"]
        self.assertIsNone(d["accuracy_tax"])
        self.assertAlmostEqual(d["calibration_tax"], 0.01, places=9)
        self.assertFalse(d["sufficient"])
        self.assertIsNone(d["combined_tax"])

    def test_all_missing_refused(self):
        # Two adapters, every component missing on both: this must
        # hit the no-accuracy/no-ECE refusal, not the <2-adapters
        # refusal the single-input version exercised.
        inputs = [
            AdapterTaxInput(adapter="a", asr=0.1, asr_ci=None,
                            benign_accuracy=None,
                            benign_accuracy_ci=None,
                            ece=None, ece_ci=None,
                            n_cases=10),
            AdapterTaxInput(adapter="b", asr=0.2, asr_ci=None,
                            benign_accuracy=None,
                            benign_accuracy_ci=None,
                            ece=None, ece_ci=None,
                            n_cases=10),
        ]
        with self.assertRaisesRegex(
                ValueError,
                "at least one adapter with benign accuracy"):
            robustness_tax(inputs)

    def test_duplicate_name_conflicting_metrics_refused(self):
        inputs = self._inputs()
        inputs.append(AdapterTaxInput(
            adapter="a", asr=0.11, asr_ci=(0.09, 0.13),
            benign_accuracy=0.80, benign_accuracy_ci=(0.77, 0.83),
            ece=0.05, ece_ci=(0.04, 0.06), n_cases=100))
        with self.assertRaises(ValueError):
            robustness_tax(inputs)

    def test_duplicate_name_same_metrics_deduped(self):
        inputs = self._inputs() + [self._inputs()[0]]
        rep = robustness_tax(inputs)
        self.assertEqual(len(rep["per_adapter"]), 3)

    def test_spearman_perfect_monotone(self):
        # 5 adapters, asr rising with accuracy falling: rho = -1
        inputs = [
            AdapterTaxInput(
                adapter=f"a{i}", asr=0.1 * i,
                asr_ci=(0.1 * i - 0.01, 0.1 * i + 0.01),
                benign_accuracy=0.95 - 0.05 * i,
                benign_accuracy_ci=(0.9 - 0.05 * i, 0.95 - 0.05 * i),
                ece=0.05, ece_ci=(0.04, 0.06), n_cases=100)
            for i in range(5)
        ]
        rep = robustness_tax(inputs)
        corr = rep["correlations"]["asr_vs_benign_accuracy"]
        self.assertAlmostEqual(corr["rho"], -1.0, places=9)
        self.assertTrue(corr["sufficient"])

    def test_correlations_withheld_below_five_adapters(self):
        rep = robustness_tax(self._inputs())
        for key in ("asr_vs_benign_accuracy", "asr_vs_ece",
                    "asr_vs_log_loss"):
            self.assertFalse(rep["correlations"][key]["sufficient"])
            self.assertIsNone(rep["correlations"][key]["rho"])

    def test_asr_vs_log_loss_correlation(self):
        # 5 adapters with log-loss rising in ASR: rho = +1
        inputs = [
            AdapterTaxInput(
                adapter=f"a{i}", asr=0.1 * i,
                asr_ci=(0.1 * i - 0.01, 0.1 * i + 0.01),
                benign_accuracy=0.95 - 0.05 * i,
                benign_accuracy_ci=(0.9 - 0.05 * i, 0.95 - 0.05 * i),
                ece=0.05, ece_ci=(0.04, 0.06),
                log_loss=0.3 + 0.1 * i,
                log_loss_ci=(0.28 + 0.1 * i, 0.32 + 0.1 * i),
                n_cases=100)
            for i in range(5)
        ]
        rep = robustness_tax(inputs)
        corr = rep["correlations"]["asr_vs_log_loss"]
        self.assertTrue(corr["sufficient"])
        self.assertAlmostEqual(corr["rho"], 1.0, places=9)

    def test_log_loss_correlation_withheld_when_missing(self):
        # same 5 adapters without log-loss: that correlation alone
        # is withheld while the others compute
        inputs = [
            AdapterTaxInput(
                adapter=f"a{i}", asr=0.1 * i,
                asr_ci=(0.1 * i - 0.01, 0.1 * i + 0.01),
                benign_accuracy=0.95 - 0.05 * i,
                benign_accuracy_ci=(0.9 - 0.05 * i, 0.95 - 0.05 * i),
                ece=0.05, ece_ci=(0.04, 0.06), n_cases=100)
            for i in range(5)
        ]
        rep = robustness_tax(inputs)
        ll = rep["correlations"]["asr_vs_log_loss"]
        self.assertFalse(ll["sufficient"])
        self.assertIsNone(ll["rho"])
        self.assertTrue(
            rep["correlations"]["asr_vs_benign_accuracy"]["sufficient"]
        )

    def test_leaderboard_tax_column(self):
        from peira.dashboard import _apply_robustness_tax_column
        rows = [
            {"adapter_name": "a", "asr_conditional": 0.10,
             "benign_accuracy": 0.95, "ece_attacked": 0.05},
            {"adapter_name": "b", "asr_conditional": 0.20,
             "benign_accuracy": 0.90, "ece_attacked": 0.08},
            {"adapter_name": "c", "asr_conditional": 0.30,
             "benign_accuracy": None, "ece_attacked": None},
        ]
        _apply_robustness_tax_column(rows)
        self.assertAlmostEqual(rows[0]["robustness_tax"], 0.0,
                               places=9)
        self.assertAlmostEqual(rows[1]["robustness_tax"], 0.08,
                               places=9)
        self.assertIsNone(rows[2]["robustness_tax"])


class LengthSensitivityTest(unittest.TestCase):
    def _length_driven(self, family="f", n_short=50, n_long=50):
        # short responses never flip; long ones always flip
        results = [
            _r(family=family, flipped=False, attacked_tokens=20,
               benign_tokens=20)
            for _ in range(n_short)
        ] + [
            _r(family=family, flipped=True, attacked_tokens=200,
               benign_tokens=20)
            for _ in range(n_long)
        ]
        return results

    def test_slope_positive_and_significant_when_length_drives(self):
        results = self._length_driven()
        rep = length_sensitivity(results)
        fam = rep["by_family"]["f"]
        self.assertTrue(fam["sufficient"])
        self.assertGreater(fam["slope"], 0)
        lo, hi = fam["slope_ci95"]
        self.assertGreater(lo, 0)
        # tertiles: long tertile flips far more than short
        tert = fam["tertile_asr"]
        self.assertGreater(tert[2]["asr"], tert[0]["asr"])
        self.assertAlmostEqual(tert[2]["asr"], 1.0, places=9)
        self.assertAlmostEqual(tert[0]["asr"], 0.0, places=9)

    def test_slope_near_zero_when_length_irrelevant(self):
        # identical lengths, half flip: no length signal at all
        results = [
            _r(family="f", flipped=(i % 2 == 0), attacked_tokens=100,
               benign_tokens=100)
            for i in range(60)
        ]
        rep = length_sensitivity(results)
        fam = rep["by_family"]["f"]
        self.assertFalse(fam["sufficient"])  # zero length variance

    def test_too_few_observations_withheld(self):
        results = self._length_driven(n_short=5, n_long=5)
        rep = length_sensitivity(results)
        fam = rep["by_family"]["f"]
        self.assertFalse(fam["sufficient"])
        self.assertIsNone(fam["slope"])

    def test_json_serializable(self):
        results = self._length_driven()
        rep = length_sensitivity(results)
        diag = length_confound_diagnostics(results)
        json.dumps({"sensitivity": rep, "deconfounding": diag})


class LengthConfoundTest(unittest.TestCase):
    def test_adjusted_slope_removes_verbosity_confound(self):
        # The money test for EB-7: attacked length looks predictive
        # univariately, but the flip is really driven by the
        # verbosity delta (benign varies independently, so the two
        # predictors are not collinear). After adjustment the length
        # slope must vanish.
        nonflip = [
            _r(family="f", flipped=False,
               attacked_tokens=50 + i, benign_tokens=50 + i)
            for i in range(50)
        ]
        flip = [
            _r(family="f", flipped=True,
               attacked_tokens=150 + i, benign_tokens=50 + i)
            for i in range(50)
        ]
        diag = length_confound_diagnostics(nonflip + flip)
        fam = diag["by_family"]["f"]
        # univariate length slope is significant (length separates)
        self.assertTrue(
            fam["predictors"]["attacked_length"]["significant"])
        adj = fam["adjusted"]
        self.assertTrue(adj["sufficient"])
        self.assertEqual(adj["n_joint"], 100)
        # ...but adjusted for verbosity it is gone
        self.assertIsNotNone(adj["length_slope_adjusted"])
        self.assertLess(abs(adj["length_slope_adjusted"]), 0.01)
        self.assertFalse(adj["significant"])

    def test_adjusted_slope_survives_when_length_drives(self):
        # Flips driven by attacked length; verbosity varies
        # independently and carries no signal. The adjusted slope
        # must stay positive and significant.
        nonflip = [
            _r(family="f", flipped=False,
               attacked_tokens=20 + i, benign_tokens=50)
            for i in range(50)
        ]
        flip = [
            _r(family="f", flipped=True,
               attacked_tokens=120 + i, benign_tokens=150 - i)
            for i in range(50)
        ]
        diag = length_confound_diagnostics(nonflip + flip)
        fam = diag["by_family"]["f"]
        adj = fam["adjusted"]
        self.assertTrue(adj["sufficient"])
        self.assertGreater(adj["length_slope_adjusted"], 0)
        self.assertTrue(adj["significant"])

    def test_adjusted_withheld_when_collinear(self):
        # Constant benign tokens make verbosity delta an exact linear
        # function of attacked length: the bivariate fit is
        # unidentified, so the adjusted slope is withheld, not fudged.
        results = (
            [_r(family="f", flipped=False, attacked_tokens=20,
                benign_tokens=20) for _ in range(50)]
            + [_r(family="f", flipped=True, attacked_tokens=200,
                  benign_tokens=20) for _ in range(50)]
        )
        diag = length_confound_diagnostics(results)
        adj = diag["by_family"]["f"]["adjusted"]
        self.assertFalse(adj["sufficient"])
        self.assertIsNone(adj["length_slope_adjusted"])
        self.assertIsNone(adj["length_slope_adjusted_ci95"])

    def test_adjusted_withheld_below_30_joint(self):
        results = [
            _r(family="f", flipped=(i % 2 == 0), attacked_tokens=100 + i,
               benign_tokens=100)
            for i in range(20)
        ]
        diag = length_confound_diagnostics(results)
        adj = diag["by_family"]["f"]["adjusted"]
        self.assertFalse(adj["sufficient"])
        self.assertIsNone(adj["length_slope_adjusted"])

    def test_adjusted_slope_deterministic(self):
        results = (
            [_r(family="f", flipped=False,
                attacked_tokens=50 + i, benign_tokens=50 + i)
             for i in range(50)]
            + [_r(family="f", flipped=True,
                  attacked_tokens=150 + i, benign_tokens=50 + i)
               for i in range(50)]
        )
        a = length_confound_diagnostics(results)["by_family"]["f"]
        b = length_confound_diagnostics(results)["by_family"]["f"]
        self.assertEqual(a["adjusted"]["length_slope_adjusted"],
                         b["adjusted"]["length_slope_adjusted"])
        self.assertEqual(a["adjusted"]["length_slope_adjusted_ci95"],
                         b["adjusted"]["length_slope_adjusted_ci95"])

    def test_report_text_shows_adjusted_slope(self):
        driven = (
            [_r(family="g", flipped=False,
                attacked_tokens=50 + i, benign_tokens=50 + i)
             for i in range(50)]
            + [_r(family="g", flipped=True,
                  attacked_tokens=150 + i, benign_tokens=50 + i)
               for i in range(50)]
        )
        block = length_diagnostics_block(driven)
        text = length_report_text(block["sensitivity"],
                                  block["deconfounding"])
        self.assertIn("adjusted length slope", text)
        # JSON-serializable with the new keys
        json.dumps(block["deconfounding"])

    def test_attacked_length_significant_when_it_drives_flips(self):
        results = (
            [_r(family="f", flipped=False, attacked_tokens=20,
                benign_tokens=20) for _ in range(50)]
            + [_r(family="f", flipped=True, attacked_tokens=200,
                  benign_tokens=20) for _ in range(50)]
        )
        diag = length_confound_diagnostics(results)
        fam = diag["by_family"]["f"]
        self.assertTrue(fam["covariate_recommended"])
        attacked = fam["predictors"]["attacked_length"]
        self.assertTrue(attacked["holm_significant"])
        # verbosity delta = attacked - benign = 180 on flips, 0
        # otherwise: also significant
        delta = fam["predictors"]["verbosity_delta"]
        self.assertTrue(delta["holm_significant"])

    def test_nothing_significant_when_length_constant(self):
        results = [
            _r(family="f", flipped=(i % 2 == 0), attacked_tokens=100,
               benign_tokens=100)
            for i in range(60)
        ]
        diag = length_confound_diagnostics(results)
        fam = diag["by_family"]["f"]
        self.assertFalse(fam["covariate_recommended"])
        for pred in fam["predictors"].values():
            self.assertFalse(pred["sufficient"])

    def test_holm_adjusts_multiple_families(self):
        # two families, only one length-driven: the driven one must
        # survive Holm over the 2-family x 2-covariate set
        driven = (
            [_r(family="g", flipped=False, attacked_tokens=20,
                benign_tokens=20) for _ in range(50)]
            + [_r(family="g", flipped=True, attacked_tokens=200,
                  benign_tokens=20) for _ in range(50)]
        )
        flat = [
            _r(family="h", flipped=(i % 2 == 0), attacked_tokens=100,
               benign_tokens=100)
            for i in range(60)
        ]
        diag = length_confound_diagnostics(driven + flat)
        self.assertTrue(
            diag["by_family"]["g"]["covariate_recommended"])
        self.assertFalse(
            diag["by_family"]["h"]["covariate_recommended"])

    def test_length_block_reports_covariate_roster(self):
        # EB-7: the block must surface the reported-covariate roster
        # as a first-class list, not only a per-family flag
        driven = (
            [_r(family="g", flipped=False, attacked_tokens=20,
                benign_tokens=20) for _ in range(50)]
            + [_r(family="g", flipped=True, attacked_tokens=200,
                  benign_tokens=20) for _ in range(50)]
        )
        flat = [
            _r(family="h", flipped=(i % 2 == 0), attacked_tokens=100,
               benign_tokens=100)
            for i in range(60)
        ]
        block = length_diagnostics_block(driven + flat)
        self.assertEqual(block["covariate_recommended_families"], ["g"])
        text = length_report_text(block["sensitivity"],
                                  block["deconfounding"])
        self.assertIn("Reported covariates: g", text)

    def test_length_block_empty_roster(self):
        flat = [
            _r(family="h", flipped=(i % 2 == 0), attacked_tokens=100,
               benign_tokens=100)
            for i in range(60)
        ]
        block = length_diagnostics_block(flat)
        self.assertEqual(block["covariate_recommended_families"], [])
        text = length_report_text(block["sensitivity"],
                                  block["deconfounding"])
        self.assertIn("Reported covariates: none", text)


class SummarizeIntegrationTest(unittest.TestCase):
    def test_summarize_carries_eb_sections(self):
        results = (
            [_r(family="f", benign_conf=0.9, attacked_conf=0.5,
                attacked_tokens=20, benign_tokens=20)
             for _ in range(40)]
            + [_r(family="f", flipped=True, benign_conf=0.9,
                  attacked_conf=0.2, attacked_tokens=200,
                  benign_tokens=20)
               for _ in range(40)]
        )
        s = summarize(results)
        self.assertIn("confidence_erosion", s)
        self.assertIn("length_diagnostics", s)
        self.assertTrue(s["confidence_erosion"]["overall"]["sufficient"])
        self.assertIn("sensitivity", s["length_diagnostics"])
        self.assertIn("deconfounding", s["length_diagnostics"])
        # both sections must survive a JSON round trip
        json.dumps({"confidence_erosion": s["confidence_erosion"],
                    "length_diagnostics": s["length_diagnostics"]})


class CmdTaxEndToEndTest(unittest.TestCase):
    """cmd_tax on sealed synthetic artifacts: the EB-40 log-loss path.

    The analysis layer computes asr_vs_log_loss; the CLI must feed it
    from the artifact's "log_loss" metrics key when R-07 seals it,
    and report it withheld when the key is absent.
    """

    def _artifact_json(self, name, asr, acc, ece, log_loss):
        from peira.artifacts import RunArtifact
        metrics = {
            "asr_conditional": asr,
            "benign_accuracy": acc,
            "calibration": {"attacked": {"ece": ece}},
            "n_eligible": 100,
        }
        if log_loss is not None:
            metrics["log_loss"] = log_loss
        return RunArtifact(
            adapter_name=name,
            adapter_version="v",
            suite="s",
            dataset_version="0.1.0-demo",
            config={},
            results=[],
            metrics=metrics,
        ).seal().to_json()

    def _run_tax(self, artifact_jsons):
        from peira.cli import cmd_tax
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i, js in enumerate(artifact_jsons):
                p = os.path.join(d, f"run{i}.json")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(js)
                paths.append(p)
            out = os.path.join(d, "tax.json")
            args = argparse.Namespace(runs=paths, json=out, out=None)
            self.assertEqual(cmd_tax(args), 0)
            with open(out, encoding="utf-8") as f:
                return json.load(f)

    def test_cmd_tax_computes_log_loss_correlation(self):
        # perfect monotone: ASR rises with log-loss -> rho = 1.0
        arts = [self._artifact_json(f"a{i}", 0.1 * (i + 1),
                                    0.9 - 0.1 * i, 0.05 * (i + 1),
                                    1.0 * (i + 1))
                for i in range(5)]
        report = self._run_tax(arts)
        ll = report["correlations"]["asr_vs_log_loss"]
        self.assertTrue(ll["sufficient"])
        self.assertAlmostEqual(ll["rho"], 1.0, places=9)

    def test_cmd_tax_withholds_log_loss_when_unsealed(self):
        arts = [self._artifact_json(f"a{i}", 0.1 * (i + 1),
                                    0.9 - 0.1 * i, 0.05 * (i + 1), None)
                for i in range(5)]
        report = self._run_tax(arts)
        ll = report["correlations"]["asr_vs_log_loss"]
        self.assertFalse(ll["sufficient"])
        # the other two correlations still compute: only log-loss
        # is gated on the R-07 key
        self.assertTrue(
            report["correlations"]["asr_vs_benign_accuracy"]
            ["sufficient"])


class CmdLengthEndToEndTest(unittest.TestCase):
    """cmd_length on sealed synthetic artifacts: the protocol check.

    A hand-written artifact may carry a non-numeric
    generation_max_tokens; the protocol check must treat it as
    undeclared, never crash comparing int > str.
    """

    def _case(self, i, flipped, attacked_tokens, benign_tokens):
        def rec(tokens):
            return {
                "decision": "approve",
                "confidence": 0.9,
                "abstained": False,
                "refusal_reason": "",
                "usage": {"model": "m", "tokens_in": 10,
                          "tokens_out": tokens,
                          "latency_ms": 1.0, "cost_usd": 0.0},
                "seed": 0, "dispatch_index": 0, "malformed": False,
                "dispatch_limit": 1,
            }
        return {
            "case_id": f"c{i}", "family": "f", "severity": "high",
            "primitive": "choice",
            "benign": rec(benign_tokens),
            "attacked": rec(attacked_tokens),
            "flipped": flipped, "eligible": True,
            "ineligibility_reason": "",
        }

    def _run_length(self, config):
        from peira.artifacts import RunArtifact
        from peira.cli import cmd_length
        results = (
            [self._case(i, False, 20, 20) for i in range(18)]
            + [self._case(i + 18, True, 200, 20) for i in range(17)]
        )
        artifact = RunArtifact(
            adapter_name="a", adapter_version="v", suite="s",
            dataset_version="0.1.0-demo",
            config=config, results=results, metrics={},
        ).seal().to_json()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "run.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write(artifact)
            out = os.path.join(d, "length.txt")
            args = argparse.Namespace(run=p, out=out)
            code = cmd_length(args)
            with open(out, encoding="utf-8") as f:
                return code, f.read()

    def test_non_numeric_declared_cap_is_not_a_crash(self):
        code, text = self._run_length({"generation_max_tokens": "512"})
        self.assertEqual(code, 0)
        self.assertNotIn("WARNING: observed length exceeds", text)

    def test_numeric_declared_cap_still_warns(self):
        code, text = self._run_length({"generation_max_tokens": 100})
        self.assertEqual(code, 0)
        self.assertIn("WARNING: observed length exceeds", text)


class CliErrorPathsTest(unittest.TestCase):
    def test_tax_needs_two_runs(self):
        # Assert the stderr message, not just exit 1, so this pins
        # the <2-runs refusal rather than any later file error.
        from peira.cli import cmd_tax
        import argparse
        import io
        from contextlib import redirect_stderr
        args = argparse.Namespace(runs=["only-one.json"], out=None,
                                  json=None)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cmd_tax(args), 1)
        self.assertIn("needs at least 2 run artifacts", err.getvalue())

    def test_erosion_missing_file(self):
        from peira.cli import cmd_erosion
        import argparse
        args = argparse.Namespace(run="/nonexistent/run.json",
                                  out=None)
        self.assertEqual(cmd_erosion(args), 1)

    def test_length_missing_file(self):
        from peira.cli import cmd_length
        import argparse
        args = argparse.Namespace(run="/nonexistent/run.json",
                                  out=None)
        self.assertEqual(cmd_length(args), 1)


if __name__ == "__main__":
    unittest.main()
