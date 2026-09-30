"""Unit tests for the M-7 multi-seed stability protocol (peira.stability).

Run with: python -m unittest discover tests -v
"""

import json
import unittest

from peira.adapters.base import CallUsage
from peira.metrics import CallRecord, PerCaseResult
from peira.runner import _adapter_longitudinal_provenance, run_multiseed
from peira.stability import (
    MIN_SEEDS,
    StabilityArtifact,
    StabilityResult,
    drift_watch,
    flip_agreement,
)


def _rec(decision="approve"):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def _r(case_id, family="f", flipped=False, eligible=True):
    attacked = "deny" if flipped else "approve"
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec("approve"),
        attacked=_rec(attacked),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "benign_abstained",
    )


def _runs(flip_matrix, families=None, eligible=True):
    """Build per-seed result lists from a flip matrix.

    flip_matrix[seed][case] -> bool flipped. families optional list
    parallel to cases.
    """
    out = []
    for flips in flip_matrix:
        run = []
        for i, f in enumerate(flips):
            fam = families[i] if families else "f"
            run.append(_r(f"c{i}", family=fam, flipped=f,
                          eligible=eligible))
        out.append(run)
    return out


class TestFlipAgreement(unittest.TestCase):
    def test_perfect_agreement(self):
        runs = _runs([[True, False, True], [True, False, True],
                      [True, False, False]])
        # case 2 disagrees across seeds
        res = flip_agreement(runs)
        self.assertEqual(res.n_cases, 3)
        self.assertEqual(res.n_agree, 2)
        self.assertAlmostEqual(res.pass_k, 2 / 3)
        self.assertEqual(res.per_case_flip_rate["c0"], 1.0)
        self.assertEqual(res.per_case_flip_rate["c1"], 0.0)
        self.assertAlmostEqual(res.per_case_flip_rate["c2"], 2 / 3)
        self.assertEqual(res.n_churn, 1)

    def test_deterministic_adapter_pass_k_one(self):
        runs = _runs([[True, False]] * 3)
        res = flip_agreement(runs)
        self.assertEqual(res.pass_k, 1.0)
        self.assertEqual(res.n_churn, 0)
        self.assertEqual(res.run_sd, 0.0)

    def test_per_seed_asr_and_pooled(self):
        runs = _runs([[True, False, False, False],
                      [False, True, False, False],
                      [False, False, True, False]])
        res = flip_agreement(runs)
        self.assertEqual(res.per_seed_asr, [0.25, 0.25, 0.25])
        self.assertAlmostEqual(res.pooled_asr, 0.25)
        # c0..c2 each flip on exactly one seed; c3 never flips and
        # agrees on non-flip across all seeds.
        self.assertEqual(res.pass_k, 0.25)
        self.assertEqual(res.n_churn, 3)

    def test_ineligible_excluded(self):
        runs = _runs([[True, False]] * 3)
        runs = [
            [r if r.case_id != "c1"
             else _r("c1", flipped=True, eligible=False)
             for r in run]
            for run in runs
        ]
        res = flip_agreement(runs)
        self.assertEqual(res.n_cases, 1)
        self.assertEqual(res.n_cases_total, 2)
        self.assertEqual(res.pass_k, 1.0)

    def test_case_eligible_in_some_seeds_only(self):
        # c1 eligible in seed 0 only: excluded from paired stats.
        runs = _runs([[True, True], [True, True], [True, True]])
        runs[1][1] = _r("c1", flipped=True, eligible=False)
        runs[2][1] = _r("c1", flipped=True, eligible=False)
        res = flip_agreement(runs)
        self.assertEqual(res.n_cases, 1)

    def test_misaligned_case_sets_rejected(self):
        runs = _runs([[True, False]] * 2)
        runs[1] = [_r("c0", flipped=True), _r("cX", flipped=False)]
        with self.assertRaises(ValueError):
            flip_agreement(runs)

    def test_single_run_rejected(self):
        with self.assertRaises(ValueError):
            flip_agreement(_runs([[True]]))

    def test_variance_decomposition_sanity(self):
        # 100 cases, 60 flip on all seeds, 40 never: pooled ASR 0.6.
        flips = [[True] * 60 + [False] * 40] * 3
        res = flip_agreement(_runs(flips))
        lo, hi = res.wilson_ci
        self.assertLess(lo, 0.6)
        self.assertGreater(hi, 0.6)
        self.assertLess(hi - lo, 0.25)  # tight at n=300 obs
        self.assertEqual(res.run_sd, 0.0)
        # item variance: rates are 0/1 with mean 0.6 -> 0.6*0.4
        self.assertAlmostEqual(res.item_variance, 0.24, places=6)

    def test_run_sd_detects_seed_spread(self):
        runs = _runs([
            [True] * 10 + [False] * 10,
            [True] * 5 + [False] * 15,
            [True] * 15 + [False] * 5,
        ])
        res = flip_agreement(runs)
        # ASRs are 0.5, 0.25, 0.75: the documented sample sd (k-1) is
        # exactly 0.25; the population sd would be ~0.204. Pin the
        # sample-sd choice, not just "spread exists".
        self.assertAlmostEqual(res.run_sd, 0.25, places=9)

    def test_summary_text_format(self):
        res = flip_agreement(_runs([[True, False]] * 3))
        text = res.summary_text()
        self.assertIn("pass^3", text)
        self.assertIn("Wilson 95% CI", text)
        self.assertIn("run-to-run sd", text)

    def test_to_from_dict_roundtrip(self):
        res = flip_agreement(_runs([[True, False], [True, True]]))
        d = res.to_dict()
        res2 = StabilityResult.from_dict(d)
        self.assertEqual(res2.pass_k, res.pass_k)
        self.assertEqual(res2.n_churn, res.n_churn)
        self.assertEqual(res2.per_case_flip_rate, res.per_case_flip_rate)
        self.assertEqual(res2.wilson_ci, res.wilson_ci)


class TestDriftWatch(unittest.TestCase):
    def test_no_drift(self):
        old = [_r("c0", flipped=True), _r("c1", flipped=False)]
        new = [_r("c0", flipped=True), _r("c1", flipped=False)]
        res = drift_watch(old, new, "old", "new")
        self.assertEqual(res.newly_flipping, [])
        self.assertEqual(res.newly_fixed, [])
        self.assertEqual(len(res.families), 1)
        fam = res.families[0]
        self.assertEqual(fam.delta, 0.0)
        self.assertFalse(fam.degraded)

    def test_newly_flipping_vs_fixed_reported(self):
        old = [_r(f"c{i}", flipped=(i < 5)) for i in range(10)]
        # flip 3 new ones, fix 1 old one: net +2 but churn is 4
        new = [_r(f"c{i}", flipped=(i < 4 or 5 <= i < 8))
               for i in range(10)]
        res = drift_watch(old, new)
        self.assertEqual(
            sorted(res.newly_flipping), ["c5", "c6", "c7"])
        self.assertEqual(res.newly_fixed, ["c4"])
        fam = res.families[0]
        self.assertEqual(fam.n_newly_flipping, 3)
        self.assertEqual(fam.n_newly_fixed, 1)
        self.assertAlmostEqual(fam.delta, 0.2)
        # 4 discordant pairs < 10: p withheld, no degradation flag
        self.assertIsNone(fam.mcnemar_p)
        self.assertFalse(fam.degraded)

    def test_degradation_flagged_with_enough_discordant(self):
        # 30 cases: 20 newly flipping, 2 newly fixed -> significant.
        old = [_r(f"c{i}", flipped=False) for i in range(30)]
        new = [_r(f"c{i}", flipped=(i < 20)) for i in range(30)]
        # make 2 of them fixed instead: flip old for c20, c21
        old[20] = _r("c20", flipped=True)
        old[21] = _r("c21", flipped=True)
        new[20] = _r("c20", flipped=False)
        new[21] = _r("c21", flipped=False)
        res = drift_watch(old, new)
        fam = res.families[0]
        self.assertEqual(fam.n_newly_flipping, 20)
        self.assertEqual(fam.n_newly_fixed, 2)
        self.assertIsNotNone(fam.mcnemar_p)
        self.assertLess(fam.mcnemar_p, 0.05)
        self.assertTrue(fam.degraded)

    def test_improvement_not_flagged_degraded(self):
        old = [_r(f"c{i}", flipped=(i < 20)) for i in range(30)]
        new = [_r(f"c{i}", flipped=False) for i in range(30)]
        res = drift_watch(old, new)
        fam = res.families[0]
        self.assertFalse(fam.degraded)
        self.assertLess(fam.delta, 0)

    def test_per_family_split(self):
        fams = ["a", "a", "b", "b"]
        old = [_r(f"c{i}", family=fams[i], flipped=False)
               for i in range(4)]
        new = [_r(f"c{i}", family=fams[i], flipped=(i == 0))
               for i in range(4)]
        res = drift_watch(old, new)
        by_fam = {f.family: f for f in res.families}
        self.assertEqual(by_fam["a"].n_newly_flipping, 1)
        self.assertEqual(by_fam["b"].n_newly_flipping, 0)

    def test_unpaired_cases_ignored(self):
        old = [_r("c0", flipped=True)]
        new = [_r("c0", flipped=True), _r("c1", flipped=True)]
        res = drift_watch(old, new)
        self.assertEqual(res.families[0].n_paired, 1)

    def test_summary_text_lists_counts(self):
        old = [_r("c0", flipped=False)]
        new = [_r("c0", flipped=True)]
        text = drift_watch(old, new, "o", "n").summary_text()
        self.assertIn("newly flipping: 1", text)
        self.assertIn("newly fixed: 0", text)


class TestStabilityArtifact(unittest.TestCase):
    def test_roundtrip(self):
        res = flip_agreement(_runs([[True, False]] * 3))
        art = StabilityArtifact(
            adapter_name="mock",
            adapter_version="0.2.0",
            suite="trial-demo",
            dataset_version="1.0.0",
            manifest_sha256="abc",
            seeds=[0, 1, 2],
            run_artifact_paths={0: "a.json", 1: "b.json", 2: "c.json"},
            stability=res,
        )
        art2 = StabilityArtifact.from_json(art.to_json())
        self.assertEqual(art2.adapter_name, "mock")
        self.assertEqual(art2.seeds, [0, 1, 2])
        self.assertEqual(
            art2.run_artifact_paths,
            {0: "a.json", 1: "b.json", 2: "c.json"},
        )
        assert art2.stability is not None
        self.assertEqual(art2.stability.pass_k, res.pass_k)
        self.assertEqual(art2.stability.k, 3)

    def test_excluded_seeds_roundtrip(self):
        res = flip_agreement(_runs([[True, False]] * 3))
        import dataclasses
        res = dataclasses.replace(res, excluded_seeds=[2])
        art = StabilityArtifact(
            adapter_name="mock",
            adapter_version="0.2.0",
            suite="trial-demo",
            dataset_version="1.0.0",
            manifest_sha256="abc",
            seeds=[0, 1],
            run_artifact_paths={0: "a.json", 1: "b.json", 2: "c.json"},
            stability=res,
        )
        art2 = StabilityArtifact.from_json(art.to_json())
        assert art2.stability is not None
        self.assertEqual(art2.stability.excluded_seeds, [2])
        # Excluded seed 2's path is present but not in seeds.
        self.assertEqual(art2.seeds, [0, 1])
        self.assertIn(2, art2.run_artifact_paths)

    def test_wrong_kind_rejected(self):
        with self.assertRaises(ValueError):
            StabilityArtifact.from_json(
                json.dumps({"artifact_kind": "run"}))

    def test_analysis_lock_detects_tampering(self):
        res = flip_agreement(_runs([[True, False]] * 3))
        art = StabilityArtifact(
            seeds=[0, 1, 2],
            run_artifact_paths={0: "a.json"},
            stability=res,
        ).seal()
        self.assertTrue(art.verify())
        art2 = StabilityArtifact.from_json(art.to_json())
        self.assertTrue(art2.verify())
        # Tamper with the sealed headline.
        import dataclasses
        tampered = dataclasses.replace(
            art2,
            stability=dataclasses.replace(
                art2.stability, pass_k=0.999
            ),
        )
        self.assertFalse(tampered.verify())

    def test_analysis_lock_detects_identity_relabeling(self):
        # The lock covers the identity fields, not just the analysis:
        # relabeling the artifact to a different adapter after sealing
        # must be detectable.
        res = flip_agreement(_runs([[True, False]] * 3))
        art = StabilityArtifact(
            adapter_name="mock",
            adapter_version="0.2.0",
            suite="trial-demo",
            dataset_version="1.0.0",
            manifest_sha256="abc",
            seeds=[0, 1, 2],
            run_artifact_paths={0: "a.json", 1: "b.json", 2: "c.json"},
            stability=res,
        ).seal()
        self.assertTrue(art.verify())
        import dataclasses
        relabeled = dataclasses.replace(art, adapter_name="other-adapter")
        self.assertFalse(relabeled.verify())
        relabeled2 = dataclasses.replace(art, dataset_version="9.9.9")
        self.assertFalse(relabeled2.verify())

    def test_pass_k_withheld_when_no_eligible_cases(self):
        # All cases ineligible: pass^k is undefined, not 0.0.
        res = flip_agreement(_runs([[True, False]] * 3, eligible=False))
        self.assertEqual(res.n_cases, 0)
        self.assertIn("withheld", res.summary_text())
        self.assertNotIn("pass^3 = 0.0%", res.summary_text())


class TestRunMultiseedValidation(unittest.TestCase):
    def test_num_seeds_below_minimum_rejected(self):
        with self.assertRaises(ValueError):
            run_multiseed(
                adapter=None, cases=[], suite="s",
                dataset_version="1.0.0", num_seeds=2,
            )
        with self.assertRaises(ValueError):
            run_multiseed(
                adapter=None, cases=[], suite="s",
                dataset_version="1.0.0", num_seeds=1,
            )

    def test_min_seeds_constant(self):
        self.assertEqual(MIN_SEEDS, 3)


def _fake_seed_artifact(termination, flips):
    """Minimal stand-in for a RunArtifact: termination + result dicts."""
    from unittest.mock import Mock

    def _rec_dict(decision):
        return {"decision": decision, "confidence": 0.9}

    art = Mock()
    art.termination = termination
    art.results = [
        {
            "case_id": f"c{i}",
            "family": "f",
            "severity": "high",
            "primitive": "choice",
            "benign": _rec_dict("approve"),
            "attacked": _rec_dict("deny" if f else "approve"),
            "flipped": f,
            "eligible": True,
        }
        for i, f in enumerate(flips)
    ]
    return art


class TestRunMultiseedTermination(unittest.TestCase):
    def _run(self, terminations):
        from unittest.mock import patch

        artifacts = [
            _fake_seed_artifact(t, [True, False]) for t in terminations
        ]
        with patch("peira.runner.run_suite", side_effect=artifacts):
            return run_multiseed(
                adapter=object(), cases=[], suite="s",
                dataset_version="1.0.0", num_seeds=len(terminations),
            )

    def test_budget_terminated_seed_excluded(self):
        artifacts, stability = self._run(
            ["complete", "budget", "complete", "complete"])
        self.assertEqual(len(artifacts), 4)
        assert stability is not None
        # Only the three complete seeds enter the analysis.
        self.assertEqual(stability.seeds, [0, 2, 3])
        self.assertEqual(stability.k, 3)
        self.assertEqual(stability.excluded_seeds, [1])
        self.assertEqual(stability.pass_k, 1.0)

    def test_too_few_complete_seeds_withholds_stability(self):
        artifacts, stability = self._run(
            ["complete", "budget", "budget"])
        self.assertEqual(len(artifacts), 3)
        self.assertIsNone(stability)

    def test_crashed_seed_does_not_lose_completed_artifacts(self):
        from unittest.mock import patch

        good = _fake_seed_artifact("complete", [True, False])
        side_effects = [
            good,
            RuntimeError("provider exploded"),
            _fake_seed_artifact("complete", [True, False]),
            _fake_seed_artifact("complete", [True, False]),
        ]
        with patch("peira.runner.run_suite", side_effect=side_effects):
            artifacts, stability = run_multiseed(
                adapter=object(), cases=[], suite="s",
                dataset_version="1.0.0", num_seeds=4,
            )
        # Three artifacts survive; the crashed seed is excluded.
        self.assertEqual(len(artifacts), 3)
        assert stability is not None
        self.assertEqual(stability.seeds, [0, 2, 3])
        self.assertEqual(stability.excluded_seeds, [1])


class FakeAdapter:
    name = "fake"
    version = "1.0"
    model_class = "guardrail"
    confidence_source = "guardrail-score"
    checkpoint_hash = "deadbeef"
    api_version = "v2"
    decode_params = {"temperature": 0.0, "max_tokens": 16}
    template_hash = "abc123"


class TestLongitudinalProvenance(unittest.TestCase):
    def test_fields_populated(self):
        prov = _adapter_longitudinal_provenance(FakeAdapter(), "trial")
        self.assertEqual(prov["model_class"], "guardrail")
        self.assertEqual(prov["confidence_source"], "guardrail-score")
        self.assertEqual(prov["checkpoint_hash"], "deadbeef")
        self.assertEqual(prov["api_version"], "v2")
        self.assertEqual(prov["template_hash"], "abc123")
        self.assertEqual(prov["case_set_tag"], "trial")
        self.assertRegex(prov["call_date"], r"^\d{4}-\d{2}-\d{2}$")
        decoded = json.loads(prov["decode_params"])
        self.assertEqual(decoded["temperature"], 0.0)

    def test_unknown_fields_default_empty(self):
        class Bare:
            name = "bare"
        prov = _adapter_longitudinal_provenance(Bare(), "trial")
        self.assertEqual(prov["model_class"], "")
        self.assertEqual(prov["checkpoint_hash"], "")
        self.assertEqual(prov["decode_params"], "")
        # runner-owned fields are always set
        self.assertEqual(prov["case_set_tag"], "trial")
        self.assertRegex(prov["call_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_non_string_attrs_ignored(self):
        class Weird:
            name = "weird"
            model_class = 123  # hostile: must not leak into the artifact
        prov = _adapter_longitudinal_provenance(Weird(), "trial")
        self.assertEqual(prov["model_class"], "")

    def test_nonserializable_decode_params_falls_back_empty(self):
        class BadParams:
            name = "bad"
            decode_params = {"temperature": 0.0, "weird": object()}
        prov = _adapter_longitudinal_provenance(BadParams(), "trial")
        self.assertEqual(prov["decode_params"], "")


class DriftFamilyChangeTests(unittest.TestCase):
    def _result(self, cid, family, flipped):
        rec = _rec()
        return PerCaseResult(
            case_id=cid,
            family=family,
            severity="low",
            primitive="choice",
            benign=rec,
            attacked=rec,
            flipped=flipped,
            eligible=True,
        )

    def test_family_change_unpairs_case(self):
        # A case relabeled to a new family between runs must not enter
        # either family's McNemar table.
        old = [self._result("c1", "f1", False)]
        new = [self._result("c1", "f2", True)]
        res = drift_watch(old, new)
        self.assertEqual(res.families, [])
        self.assertEqual(res.newly_flipping, [])
        self.assertEqual(res.newly_fixed, [])

    def test_same_family_still_pairs(self):
        old = [self._result("c1", "f1", False)]
        new = [self._result("c1", "f1", True)]
        res = drift_watch(old, new)
        self.assertEqual(len(res.families), 1)
        self.assertEqual(res.families[0].family, "f1")


class WithSeedTests(unittest.TestCase):
    def test_with_seed_rekeys_cache_namespace(self):
        from peira.adapters.llm import _StructuredLLMBase

        class Probe(_StructuredLLMBase):
            name = "probe"
            _supports_seed = True

            def __init__(self, seed):
                # Bypass provider init; only the seed machinery matters.
                self._model = "m"
                self._temperature = 0.0
                self._seed = seed
                self._max_tokens = 512
                self.cache_namespace = f"probe:m:t0.0:mt512:s{seed}"

        a = Probe(3)
        b = a.with_seed(4)
        self.assertEqual(b._seed, 4)
        self.assertIn(":s4", b.cache_namespace)
        self.assertNotIn(":s4", a.cache_namespace)
        # The original is untouched.
        self.assertEqual(a._seed, 3)


if __name__ == "__main__":
    unittest.main()
