"""Backend-parity tests for Wave 3 item 9 (rust-max metrics prereqs).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python reference on identical inputs.
Floats use ``assertAlmostEqual(places=12)`` (the documented ~1 ulp
precedent); strings and dicts compare by equality.

``test_backend_under_test`` records which backend ran so the gate
report can confirm Rust-active mode actually exercised the core.
"""

import os
import unittest

import peira.metrics as metrics_mod
from peira._rust import _impl as _rust
from peira.metrics import (
    FLIP_DIRECTIONS,
    PerCaseResult,
    _flip_direction_py,
    _net_benefit_at_threshold_py,
    flip_direction,
    flip_direction_counts,
    net_benefit_at_threshold,
)


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        self.assertIs(metrics_mod._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\nmetrics-prereqs parity backend: {'rust' if _rust is not None else 'python'}")


def _rec(decision="approve", abstained=False, malformed=False, score=None):
    return {
        "decision": decision,
        "confidence": 0.9,
        "abstained": abstained,
        "refusal_reason": "",
        "seed": 0,
        "dispatch_index": 0,
        "malformed": malformed,
        "dispatch_limit": 1,
        "score": score,
        "usage": {
            "model": "test-model",
            "tokens_in": 10,
            "tokens_out": 5,
            "latency_ms": 50.0,
            "cost_usd": 0.001,
        },
    }


def _case(
    case_id="c1",
    primitive="choice",
    flipped=False,
    eligible=True,
    benign_decision="approve",
    attacked_decision="approve",
    attacked_malformed=False,
    attacked_abstained=False,
    benign_score=None,
    attacked_score=None,
    _benign_abstained=False,
):
    benign = _rec(decision=benign_decision, score=benign_score,
                  abstained=_benign_abstained)
    attacked = _rec(
        decision=attacked_decision,
        abstained=attacked_abstained,
        malformed=attacked_malformed,
        score=attacked_score,
    )
    return PerCaseResult.from_dict({
        "case_id": case_id,
        "family": "fam",
        "severity": "high",
        "primitive": primitive,
        "benign": benign,
        "attacked": attacked,
        "flipped": flipped,
        "eligible": eligible,
        "ineligibility_reason": "" if eligible else "benign_wrong_decision",
    })


def _flip_direction_corpus():
    """One case per priority-order branch of flip_direction."""
    cases = [
        # 1. not flipped -> "none"
        _case("d-none", flipped=False),
        # 1b. not flipped + material score shift -> "score-shifted"
        _case("d-shift", primitive="score", flipped=False,
              benign_score=0.2, attacked_score=0.5),
        # 1c. not flipped + sub-threshold shift -> "none"
        _case("d-noshift", primitive="score", flipped=False,
              benign_score=0.2, attacked_score=0.25),
        # 2. attacked malformed -> "to-malformed"
        _case("d-malf", flipped=True, attacked_decision="garbage",
              attacked_malformed=True),
        # 3. attack-induced silence -> "to-abstain"
        _case("d-abstain", flipped=True, attacked_decision="abstain",
              attacked_abstained=True),
        # 4. both silent -> "other"
        _case("d-bothsilent", flipped=True, benign_decision="abstain",
              attacked_decision="abstain", attacked_abstained=True,
              _benign_abstained=True),
        # 5. score primitive flipped -> "score-shifted"
        _case("d-score", primitive="score", flipped=True,
              benign_decision="approve", attacked_decision="deny"),
        # 6a. deny-to-approve
        _case("d-dta", flipped=True, benign_decision="deny",
              attacked_decision="approve"),
        # 6b. approve-to-deny
        _case("d-atd", flipped=True, benign_decision="approve",
              attacked_decision="deny"),
        # 7a. unknown polarity -> "other"
        _case("d-unknown", flipped=True, benign_decision="choose A",
              attacked_decision="choose B"),
        # 7b. lateral move within one pole -> "other"
        _case("d-lateral", flipped=True, benign_decision="approve",
              attacked_decision="hire"),
        # compound labels on the frozen pole sets
        _case("d-compound", flipped=True, benign_decision="deny the order",
              attacked_decision="approve appeal"),
        # abstain label without the abstained flag (abstain primitive)
        _case("d-abstainlabel", flipped=True, benign_decision="approve",
              attacked_decision="abstain"),
    ]
    return cases


class TestFlipDirectionParity(unittest.TestCase):
    def test_every_branch_matches_reference(self):
        for case in _flip_direction_corpus():
            got = flip_direction(case)
            want = _flip_direction_py(case)
            self.assertEqual(got, want, f"case {case.case_id}")
            self.assertIn(got, FLIP_DIRECTIONS)

    def test_flip_direction_counts_matches_reference(self):
        cases = _flip_direction_corpus()
        # Add an ineligible case: excluded from counts in both backends.
        cases.append(_case("d-inelig", flipped=True, eligible=False,
                           benign_decision="deny", attacked_decision="approve"))
        got = flip_direction_counts(cases)
        want = {}
        for d in FLIP_DIRECTIONS:
            want[d] = 0
        for c in cases:
            if c.eligible:
                want[_flip_direction_py(c)] += 1
        self.assertEqual(got, want)
        # Shape: every direction present as a key.
        self.assertEqual(set(got.keys()), set(FLIP_DIRECTIONS))

    def test_flip_direction_rejects_surrogates(self):
        bad_dict = {
            "case_id": "x\ud800y",
            "family": "fam",
            "severity": "high",
            "primitive": "choice",
            "benign": _rec(),
            "attacked": _rec(),
            "flipped": False,
            "eligible": True,
            "ineligibility_reason": "",
        }
        bad = PerCaseResult.from_dict(bad_dict)
        with self.assertRaises(ValueError):
            flip_direction(bad)

    def test_usage_optional_strings_reject_surrogates(self):
        # Slice-5 follow-up: _require_result_strings now validates the
        # optional CallUsage string fields (price_table_ref,
        # finish_reason, provider_response_id). A lone surrogate in any
        # of them must raise ValueError from the dispatched entry point
        # in both backends, exactly like every other string field the
        # PyO3 mirrors extract as String.
        for field in ("price_table_ref", "finish_reason",
                      "provider_response_id"):
            rec = _rec()
            rec["usage"] = {
                "model": "test-model",
                "tokens_in": 10,
                "tokens_out": 5,
                "latency_ms": 50.0,
                "cost_usd": 0.001,
                field: "x\ud800y",
            }
            bad_dict = {
                "case_id": "c1",
                "family": "fam",
                "severity": "high",
                "primitive": "choice",
                "benign": rec,
                "attacked": _rec(),
                "flipped": False,
                "eligible": True,
                "ineligibility_reason": "",
            }
            bad = PerCaseResult.from_dict(bad_dict)
            with self.assertRaisesRegex(ValueError, "lone surrogates",
                                        msg=field):
                flip_direction(bad)


class TestNetBenefitParity(unittest.TestCase):
    def test_grids_match_reference(self):
        risks = [0.95, 0.8, 0.6, 0.4, 0.2, 0.05]
        labels = [1, 0, 1, 0, 1, 0]
        for pt in [0.0, 0.01, 0.1, 0.5, 0.85, 0.99]:
            got = net_benefit_at_threshold(risks, labels, pt)
            want = _net_benefit_at_threshold_py(risks, labels, pt)
            self.assertAlmostEqual(got, want, places=12, msg=f"pt={pt}")

    def test_all_reviewed_and_none_reviewed(self):
        risks = [0.9, 0.1]
        labels = [1, 0]
        # pt=0 reviews everything: NB = event rate = 0.5
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.0), 0.5, places=12)
        # pt above all risks: nothing reviewed: NB = 0.0
        self.assertAlmostEqual(
            net_benefit_at_threshold(risks, labels, 0.95), 0.0, places=12)

    def test_validation_errors_match(self):
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([], [], 0.5)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([0.5], [1, 0], 0.5)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([0.5], [2], 0.5)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([0.5], [1], 1.0)
        with self.assertRaises(ValueError):
            net_benefit_at_threshold([float("nan")], [1], 0.5)


if __name__ == "__main__":
    unittest.main()
