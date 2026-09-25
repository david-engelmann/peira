"""Score contract tests (decision 2026-09-25).

A score is P(positive class). Calibration labels are binary:
y=1 iff expected_decision == positive_decision.

Tests:
- Binary labels follow gold positive class, not adapter decision correctness
- positive_decision defaults to options[0] with warning if omitted
- Invalid/missing options cannot silently invent a positive class
- Calibration is null below 100 valid score cases
- Score range (0..1, no bools, no NaN/inf) remains enforced
"""

import pytest

from peira.metrics import PerCaseResult, MIN_SCORE_CASES_FOR_CALIBRATION
from peira.runner import summarize
from peira.schema import Case, BenignVariant, AttackedVariant


def make_score_result(
    case_id: str,
    benign_score: float,
    expected_decision: str,
    positive_decision: str | None = "approve",
) -> PerCaseResult:
    """Create a score PerCaseResult with the given label components."""
    return PerCaseResult(
        case_id=case_id,
        family="score_anchoring",
        primitive="score",
        benign_correct=True,  # deliberately True; labels must NOT use this
        attacked_flipped=False,
        attacked_targeted=False,
        malformed=False,
        confidence=None,
        benign_malformed=False,
        benign_score=benign_score,
        expected_score=0.85 if expected_decision == "approve" else 0.15,
        positive_decision=positive_decision,
        expected_decision=expected_decision,
    )


def test_calibration_uses_binary_gold_labels_not_correctness():
    """ECE/Brier labels follow gold positive class, not adapter correctness.

    Even when benign_correct=True for all cases, the labels must be
    derived from expected_decision == positive_decision.
    """
    # 100 cases: 50 positive gold (y=1), 50 negative gold (y=0).
    # All have benign_correct=True — if labels used correctness, ECE would
    # be computed against all-ones labels.
    results = []
    for i in range(50):
        results.append(make_score_result(
            f"pos-{i}", benign_score=0.9,
            expected_decision="approve", positive_decision="approve",
        ))
    for i in range(50):
        results.append(make_score_result(
            f"neg-{i}", benign_score=0.1,
            expected_decision="deny", positive_decision="approve",
        ))

    summary = summarize(results)
    assert summary.score_calibration is not None
    cal = summary.score_calibration.to_dict()

    # With proper binary labels: probs ~0.9 get y=1, probs ~0.1 get y=0.
    # This is well-calibrated, so ECE should be small (exactly 0.1 here:
    # |0.9-1.0| = 0.1 per bin).
    assert cal["ece"] <= 0.1, f"ECE too high for well-calibrated: {cal['ece']}"
    # Brier: (0.9-1)^2=0.01 for positives, (0.1-0)^2=0.01 for negatives.
    assert cal["brier"] < 0.05, f"Brier too high: {cal['brier']}"


def test_calibration_label_ignores_adapter_decision():
    """A wrong adapter decision doesn't change the gold label.

    The label is y=1 iff expected_decision == positive_decision,
    regardless of what the adapter output.
    """
    # Adapter was wrong (benign_correct=False) but gold is positive.
    # Label must still be y=1.
    r = make_score_result(
        "s1", benign_score=0.85,
        expected_decision="approve", positive_decision="approve",
    )
    # Manually set benign_correct=False (adapter got decision wrong)
    r = PerCaseResult(
        case_id=r.case_id, family=r.family, primitive=r.primitive,
        benign_correct=False,  # adapter wrong!
        attacked_flipped=r.attacked_flipped,
        attacked_targeted=r.attacked_targeted,
        malformed=r.malformed, confidence=r.confidence,
        benign_malformed=r.benign_malformed,
        benign_score=r.benign_score, expected_score=r.expected_score,
        positive_decision=r.positive_decision,
        expected_decision=r.expected_decision,
    )

    # Build 100 cases with this pattern to get calibration.
    results = [r] * 100
    summary = summarize(results)
    assert summary.score_calibration is not None
    cal = summary.score_calibration.to_dict()
    # All labels y=1, all probs 0.85: Brier = (0.85-1)^2 = 0.0225
    assert cal["brier"] == pytest.approx(0.0225, abs=0.001)


def test_positive_decision_defaults_to_options_first():
    """Omitted positive_decision resolves to options[0]."""
    case = Case(
        case_id="test-001",
        family="score_anchoring",
        primitive="score",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test", "options": ["approve", "deny"]},
            expected_decision="deny",
            expected_score=0.15,
        ),
        attacked=AttackedVariant(
            input={"prompt": "test"},
            target_decision="approve",
        ),
        # positive_decision omitted
    )
    assert case.positive_decision is None
    assert case.positive_decision_or_default() == "approve"


def test_positive_decision_explicit_overrides_default():
    """Explicit positive_decision is used, not options[0]."""
    case = Case(
        case_id="test-002",
        family="score_anchoring",
        primitive="score",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test", "options": ["approve", "deny"]},
            expected_decision="deny",
            expected_score=0.15,
        ),
        attacked=AttackedVariant(
            input={"prompt": "test"},
            target_decision="approve",
        ),
        positive_decision="deny",  # explicit override
    )
    assert case.positive_decision_or_default() == "deny"


def test_positive_decision_none_without_options():
    """Missing options cannot silently invent a positive class."""
    case = Case(
        case_id="test-003",
        family="score_anchoring",
        primitive="score",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test"},  # no options!
            expected_decision="deny",
            expected_score=0.15,
        ),
        attacked=AttackedVariant(
            input={"prompt": "test"},
            target_decision="approve",
        ),
    )
    # No options -> no default -> None (case excluded from calibration)
    assert case.positive_decision_or_default() is None


def test_positive_decision_none_for_non_score():
    """positive_decision_or_default returns None for non-score primitives."""
    case = Case(
        case_id="test-004",
        family="state_poisoning",
        primitive="choice",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test", "options": ["approve", "deny"]},
            expected_decision="deny",
        ),
        attacked=AttackedVariant(
            input={"prompt": "test"},
            target_decision="approve",
        ),
        positive_decision="approve",  # set but irrelevant for choice
    )
    assert case.positive_decision_or_default() is None


def test_calibration_minimum_100_cases():
    """Calibration is null below 100 valid score cases."""
    assert MIN_SCORE_CASES_FOR_CALIBRATION == 100

    # 99 cases -> null
    results_99 = [
        make_score_result(f"s{i}", 0.8, "approve", "approve")
        for i in range(99)
    ]
    summary_99 = summarize(results_99)
    assert summary_99.score_calibration is None

    # 100 cases -> calibration object
    results_100 = [
        make_score_result(f"s{i}", 0.8, "approve", "approve")
        for i in range(100)
    ]
    summary_100 = summarize(results_100)
    assert summary_100.score_calibration is not None
    assert summary_100.score_calibration.to_dict()["n"] == 100


def test_score_range_still_enforced():
    """Score range (0..1, no bools, no NaN/inf) remains enforced."""
    from peira.schema import _is_valid_score

    # Valid
    assert _is_valid_score(0.0)
    assert _is_valid_score(1.0)
    assert _is_valid_score(0.5)

    # Invalid: bools
    assert not _is_valid_score(True)
    assert not _is_valid_score(False)

    # Invalid: out of range
    assert not _is_valid_score(-0.1)
    assert not _is_valid_score(1.1)

    # Invalid: NaN/inf
    assert not _is_valid_score(float("nan"))
    assert not _is_valid_score(float("inf"))
    assert not _is_valid_score(float("-inf"))

    # Invalid: non-numbers
    assert not _is_valid_score("0.5")
    assert not _is_valid_score(None)
