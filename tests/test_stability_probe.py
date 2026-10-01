"""R-04: the small multi-trial stability probe.

Covers :mod:`peira.stability_probe`: per-case flip rates, the
attacked-arm pass^k headline (Anthropic semantics: P(all k succeed)),
the agreement-based stability score, Wilson CIs, borderline
detection, and the report/schema round-trip.
"""

import unittest

from peira.metrics import CallRecord, PerCaseResult
from peira.stability_probe import (
    DEFAULT_PROBE_CASES,
    DEFAULT_PROBE_TRIALS,
    MIN_PROBE_TRIALS,
    ProbeCaseResult,
    StabilityProbeResult,
    align_trials,
    analyze_probe,
)


def _result(case_id, flipped, eligible=True, family="f"):
    record = CallRecord(
        decision="deny",
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=record,
        attacked=record,
        flipped=flipped,
        eligible=eligible,
    )


def _trials(matrix):
    """Build k trials from a case_id -> [flip per trial] matrix."""
    case_ids = list(matrix)
    k = len(matrix[case_ids[0]])
    trials = []
    for t in range(k):
        trials.append(
            [_result(cid, matrix[cid][t]) for cid in case_ids]
        )
    return trials


class AlignTrialsTests(unittest.TestCase):
    def test_aligns_flip_outcomes_per_case(self):
        aligned = align_trials(
            _trials({"c1": [True, False, True], "c2": [False, False, False]})
        )
        by_id = {c.case_id: c for c in aligned}
        self.assertEqual(by_id["c1"].trial_flips, (True, False, True))
        self.assertEqual(by_id["c2"].trial_flips, (False, False, False))

    def test_ineligible_trial_contributes_none(self):
        t0 = [_result("c1", True, eligible=True)]
        t1 = [_result("c1", False, eligible=False)]
        (aligned,) = align_trials([t0, t1])
        self.assertEqual(aligned.trial_flips, (True, None))
        self.assertEqual(aligned.eligible_trials, 1)

    def test_case_missing_from_later_trial_contributes_none(self):
        t0 = [_result("c1", True), _result("c2", False)]
        t1 = [_result("c1", False)]  # c2 absent
        by_id = {c.case_id: c for c in align_trials([t0, t1])}
        self.assertEqual(by_id["c2"].trial_flips, (False, None))

    def test_empty_trials_raise(self):
        with self.assertRaises(ValueError):
            align_trials([])


class ProbeCaseResultTests(unittest.TestCase):
    def test_flip_rate(self):
        c = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(True, False, True)
        )
        self.assertAlmostEqual(c.flip_rate, 2 / 3)

    def test_flip_rate_ignores_ineligible_trials(self):
        c = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(True, None)
        )
        self.assertEqual(c.flip_rate, 1.0)
        self.assertEqual(c.eligible_trials, 1)

    def test_flip_rate_none_when_no_eligible_trials(self):
        c = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(None, None)
        )
        self.assertIsNone(c.flip_rate)

    def test_borderline_is_strictly_between(self):
        borderline = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(True, False, False)
        )
        self.assertTrue(borderline.is_borderline)
        for flips in ((True, True, True), (False, False), (None, None)):
            c = ProbeCaseResult(case_id="c", family="f",
                                trial_flips=flips)
            self.assertFalse(c.is_borderline, flips)

    def test_held_all_trials(self):
        held = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(False, False, False)
        )
        self.assertTrue(held.held_all_trials)
        broken = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(False, True, False)
        )
        self.assertFalse(broken.held_all_trials)

    def test_agrees_all_trials(self):
        # Agreement, not success: always-flipped is perfectly stable.
        for flips in ((True, True), (False, False, False)):
            c = ProbeCaseResult(case_id="c", family="f",
                                trial_flips=flips)
            self.assertTrue(c.agrees_all_trials, flips)
        c = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(True, False)
        )
        self.assertFalse(c.agrees_all_trials)

    def test_round_trip(self):
        c = ProbeCaseResult(
            case_id="c", family="f", trial_flips=(True, None, False)
        )
        self.assertEqual(ProbeCaseResult.from_dict(c.to_dict()), c)


def _probe(matrix, **kw):
    trials = _trials(matrix)
    k = len(trials)
    params = dict(
        adapter_name="a",
        adapter_version="1",
        suite="trial",
        dataset_version="1.0",
        manifest_sha256="m",
        seeds=list(range(k)),
        sampling_configs=[{"temperature": 0.0} for _ in range(k)],
        trial_results=trials,
    )
    params.update(kw)
    return analyze_probe(**params)


class AnalyzeProbeTests(unittest.TestCase):
    def test_pass_k_is_fraction_holding_all_trials(self):
        result = _probe({
            "c1": [False, False, False],  # held
            "c2": [False, False, False],  # held
            "c3": [True, False, False],   # flipped once
            "c4": [True, True, True],     # flipped always
        })
        self.assertAlmostEqual(result.pass_k, 0.5)
        lo, hi = result.pass_k_ci
        self.assertLessEqual(lo, 0.5)
        self.assertGreaterEqual(hi, 0.5)
        self.assertLess(lo, hi)

    def test_pass_k_is_not_mean_flip_rate(self):
        # Mean flip rate would be 4/12 = 1/3; pass^k is the fraction
        # with zero flips anywhere: 1/2. The two must not be confused.
        result = _probe({
            "c1": [False, False, False],
            "c2": [True, True, True],
        })
        self.assertAlmostEqual(result.pass_k, 0.5)

    def test_stability_score_is_agreement(self):
        result = _probe({
            "c1": [False, False, False],  # agrees
            "c2": [True, True, True],     # agrees (stable + vulnerable)
            "c3": [True, False, False],   # disagrees
        })
        self.assertAlmostEqual(result.stability_score, 2 / 3)

    def test_borderline_case_ids(self):
        result = _probe({
            "c1": [True, False, False],
            "c2": [False, False, False],
            "c3": [True, True, True],
        })
        self.assertEqual(result.borderline_case_ids, ["c1"])

    def test_ineligible_everywhere_cases_do_not_score(self):
        t0 = [_result("c1", True, eligible=False)]
        t1 = [_result("c1", True, eligible=False)]
        result = analyze_probe(
            adapter_name="a",
            adapter_version="1",
            suite="trial",
            dataset_version="1.0",
            manifest_sha256="m",
            seeds=[0, 1],
            sampling_configs=[{}, {}],
            trial_results=[t0, t1],
        )
        self.assertIsNone(result.pass_k)
        self.assertIsNone(result.pass_k_ci)
        self.assertIsNone(result.stability_score)
        # Accuracy is the per-trial eligible rate, not the scored-set
        # rate: zero eligible in every trial is a well-defined 0.0.
        self.assertAlmostEqual(result.accuracy, 0.0)

    def test_accuracy_is_mean_per_trial_eligible_rate(self):
        # 2 cases x 3 trials. Trial 0: both eligible (1.0); trial 1:
        # one eligible (0.5); trial 2: both eligible (1.0).
        trials = [
            [_result("c1", False, eligible=True),
             _result("c2", False, eligible=True)],
            [_result("c1", True, eligible=True),
             _result("c2", True, eligible=False)],
            [_result("c1", False, eligible=True),
             _result("c2", False, eligible=True)],
        ]
        result = analyze_probe(
            adapter_name="a",
            adapter_version="1",
            suite="trial",
            dataset_version="1.0",
            manifest_sha256="m",
            seeds=[0, 1, 2],
            sampling_configs=[{}, {}, {}],
            trial_results=trials,
        )
        self.assertAlmostEqual(result.accuracy, (1.0 + 0.5 + 1.0) / 3)
        # The report carries accuracy next to the stability numbers.
        d = result.to_dict()
        self.assertAlmostEqual(d["accuracy"], result.accuracy)
        self.assertIn("benign-arm accuracy", result.summary_text())

    def test_too_few_trials_raise(self):
        with self.assertRaises(ValueError):
            analyze_probe(
                adapter_name="a",
                adapter_version="1",
                suite="trial",
                dataset_version="1.0",
                manifest_sha256="m",
                seeds=[0],
                sampling_configs=[{}],
                trial_results=[[_result("c1", True)]],
            )

    def test_mismatched_seeds_raise(self):
        with self.assertRaises(ValueError):
            _probe({"c1": [True, False]}, seeds=[0])

    def test_report_round_trip(self):
        result = _probe({
            "c1": [True, False, False],
            "c2": [False, False, False],
        })
        d = result.to_dict()
        self.assertEqual(d["schema_ref"], "peira/stability-probe/v1")
        # Determinism is explicitly not claimed.
        self.assertFalse(d["determinism_claimed"])
        self.assertEqual(d["borderline_case_ids"], ["c1"])
        restored = StabilityProbeResult.from_dict(d)
        self.assertEqual(restored.pass_k, result.pass_k)
        self.assertEqual(restored.stability_score, result.stability_score)
        self.assertEqual(
            restored.borderline_case_ids, result.borderline_case_ids
        )

    def test_summary_text_names_pass_k(self):
        result = _probe({"c1": [False, False, False]})
        text = result.summary_text()
        self.assertIn("pass^3", text)
        self.assertIn("borderline cases: 0", text)

    def test_defaults(self):
        self.assertEqual(DEFAULT_PROBE_CASES, 100)
        self.assertEqual(DEFAULT_PROBE_TRIALS, 3)
        self.assertEqual(MIN_PROBE_TRIALS, 2)


if __name__ == "__main__":
    unittest.main()
