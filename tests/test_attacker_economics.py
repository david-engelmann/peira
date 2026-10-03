"""EB-37x attacker economics: per-case budget accounting, the two
views ($/flip marginal vs $/incident amortized), the ROI model, and
winning-perturbation edit distance.
"""

import json
import math

import pytest

from peira.attacker_economics import (
    DEFAULT_INCIDENT_VALUES,
    AttackerCaseSpend,
    attacker_roi,
    case_spend_from_record,
    perturbation_edit_distance,
    roi_grid,
    summarize_attacker_economics,
    summarize_family,
)


def _attempt(cost, tokens_in=100, tokens_out=10, usage=True):
    if not usage:
        return {"usage": None}
    return {
        "usage": {
            "model": "test-model",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": 5.0,
            "cost_usd": cost,
        }
    }


def _record(case_id, family="f1", flipped_at=None, n_attempts=3,
            eligible=True, costs=(0.001, 0.002, 0.004),
            unpriced=()):
    """Sweep artifact per-case result dict (the to_dict() shape)."""
    attempts = [
        _attempt(costs[i], usage=(i not in unpriced))
        for i in range(n_attempts)
    ]
    attempt_flipped = [False] * n_attempts
    if flipped_at is not None:
        for i in range(flipped_at - 1, n_attempts):
            attempt_flipped[i] = True
    return {
        "case_id": case_id,
        "family": family,
        "severity": "high",
        "primitive": "choice",
        "eligible": eligible,
        "attempts": attempts,
        "attempt_flipped": attempt_flipped,
        "budget_to_first_flip": flipped_at,
    }


# ---------------------------------------------------------------------------
# Per-case spend accounting
# ---------------------------------------------------------------------------


def test_to_flip_window_sums_only_winning_attempts():
    s = case_spend_from_record(_record("c1", flipped_at=2))
    assert s.flipped
    assert s.queries_to_flip == 2
    # Attempts 0 and 1 only: 2 x 110 tokens, $0.001 + $0.002.
    assert s.tokens_to_flip == 220
    assert s.cost_usd_to_flip == pytest.approx(0.003)
    assert s.to_flip_complete
    # Totals cover all three attempts.
    assert s.queries_spent == 3
    assert s.tokens_spent == 330
    assert s.cost_usd_spent == pytest.approx(0.007)
    assert not s.cost_spent_is_lower_bound


def test_never_flipped_case_has_no_to_flip_but_full_totals():
    s = case_spend_from_record(_record("c1", flipped_at=None))
    assert not s.flipped
    assert s.queries_to_flip is None
    assert s.tokens_to_flip is None
    assert s.cost_usd_to_flip is None
    assert s.queries_spent == 3
    assert s.cost_usd_spent == pytest.approx(0.007)


def test_unpriced_window_attempt_withholds_cost_not_queries():
    s = case_spend_from_record(
        _record("c1", flipped_at=2, unpriced=(1,)))
    # Queries are known even when the price is not.
    assert s.queries_to_flip == 2
    # Unknown cost is withheld, never reported as $0.00.
    assert s.cost_usd_to_flip is None
    assert s.tokens_to_flip is None
    assert not s.to_flip_complete
    assert s.cost_spent_is_lower_bound
    assert s.n_priced_attempts == 2


def test_fully_unpriced_case_marks_lower_bound():
    s = case_spend_from_record(
        _record("c1", flipped_at=None, unpriced=(0, 1, 2)))
    assert s.cost_usd_spent == 0.0
    assert s.cost_spent_is_lower_bound
    assert s.tokens_spent is None


def test_rejects_empty_attempts():
    d = _record("c1", flipped_at=None, n_attempts=0)
    d["attempts"] = []
    d["attempt_flipped"] = []
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_mismatched_attempt_lengths():
    d = _record("c1", flipped_at=2)
    d["attempt_flipped"] = [True]
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_flip_level_with_no_flipped_attempt():
    d = _record("c1", flipped_at=None)
    d["budget_to_first_flip"] = 2  # claims a flip; none recorded
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_flip_marker_with_no_flip_level():
    d = _record("c1", flipped_at=None)
    d["attempt_flipped"] = [False, True, False]  # a flip, but level None
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_flip_level_beyond_attempts():
    d = _record("c1", flipped_at=None, n_attempts=2)
    d["attempt_flipped"] = [False, True]
    d["budget_to_first_flip"] = 5
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_non_positive_flip_level():
    d = _record("c1", flipped_at=2)
    d["budget_to_first_flip"] = 0
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_negative_cost():
    d = _record("c1", flipped_at=1)
    d["attempts"][0]["usage"]["cost_usd"] = -0.5
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_bool_tokens():
    d = _record("c1", flipped_at=1)
    d["attempts"][0]["usage"]["tokens_in"] = True
    with pytest.raises(ValueError):
        case_spend_from_record(d)


def test_rejects_non_mapping_record():
    with pytest.raises(ValueError):
        case_spend_from_record(["not", "a", "mapping"])


def test_perturbation_kwarg_attaches_to_case():
    s = case_spend_from_record(
        _record("c1", flipped_at=1), perturbation=(7, 0.35))
    assert s.perturbation_edit_distance == 7
    assert s.perturbation_edit_distance_norm == pytest.approx(0.35)


def test_perturbation_kwarg_rejects_bad_values():
    with pytest.raises(ValueError):
        case_spend_from_record(
            _record("c1", flipped_at=1), perturbation=(-1, 0.5))
    with pytest.raises(ValueError):
        case_spend_from_record(
            _record("c1", flipped_at=1), perturbation=(3, 1.5))
    with pytest.raises(ValueError):
        case_spend_from_record(
            _record("c1", flipped_at=1), perturbation=(True, 0.5))


# ---------------------------------------------------------------------------
# The two views
# ---------------------------------------------------------------------------


def _family_spends():
    return [
        case_spend_from_record(_record("c1", flipped_at=2)),
        case_spend_from_record(_record("c2", flipped_at=3)),
        case_spend_from_record(_record("c3", flipped_at=None)),
        # Ineligible cases never contribute to either view.
        case_spend_from_record(
            _record("c4", flipped_at=1, eligible=False)),
    ]


def test_marginal_view_covers_flipped_cases_only():
    f = summarize_family(_family_spends(), "f1")
    assert f.n_eligible == 3
    assert f.n_flipped == 2
    assert f.flip_rate == pytest.approx(2 / 3)
    q = f.marginal.queries_to_flip
    # Statistical median of [2, 3], per the shared EB-35 sweep protocol.
    assert q["median"] == 2.5
    assert q["mean"] == pytest.approx(2.5)
    assert f.marginal.n_complete == 2
    assert f.marginal.withheld_reason is None


def test_amortized_view_includes_failed_attempts():
    f = summarize_family(_family_spends(), "f1")
    a = f.amortized
    # 3 cases x 3 attempts = 9 queries; 2 flips.
    assert a.total_queries_spent == 9
    assert a.n_flips == 2
    assert a.queries_per_incident == pytest.approx(4.5)
    # Total spend $0.007 x 3 = $0.021 over 2 flips.
    assert a.total_cost_usd_spent == pytest.approx(0.021)
    assert a.cost_usd_per_incident == pytest.approx(0.0105)
    assert not a.cost_is_lower_bound


def test_no_flips_withholds_per_incident_and_breakeven():
    spends = [case_spend_from_record(_record("c1", flipped_at=None))]
    f = summarize_family(spends, "f1")
    assert f.marginal.queries_to_flip is None
    assert f.amortized.cost_usd_per_incident is None
    assert f.amortized.queries_per_incident is None
    assert f.breakeven_incident_value_usd is None
    for p in f.roi_points:
        assert p.roi is None
        assert "nothing flipped" in (p.withheld_reason or "")


def test_unpriced_spend_marks_amortized_lower_bound():
    spends = [
        case_spend_from_record(
            _record("c1", flipped_at=1, unpriced=(0,))),
        case_spend_from_record(_record("c2", flipped_at=2)),
    ]
    f = summarize_family(spends, "f1")
    assert f.amortized.cost_is_lower_bound
    assert f.breakeven_is_lower_bound
    # The unpriced window withholds that flip's to-flip figures, so the
    # marginal cost triple covers only the fully-priced flip.
    assert f.marginal.n_complete == 1
    assert f.marginal.cost_usd_to_flip == {
        "median": pytest.approx(0.003),
        "p90": pytest.approx(0.003),
        "mean": pytest.approx(0.003),
    }
    assert f.marginal.withheld_reason is None
    # The spend behind the ROI points is a lower bound: profit and ROI
    # are kept as upper bounds and flagged, not silently rounded.
    for p in f.roi_points:
        assert p.spend_is_lower_bound
        assert p.roi is not None


def test_all_unpriced_family_withholds_cost_derived_figures():
    spends = [
        case_spend_from_record(
            _record("c1", flipped_at=1, unpriced=(0, 1, 2))),
        case_spend_from_record(
            _record("c2", flipped_at=2, unpriced=(0, 1, 2))),
    ]
    f = summarize_family(spends, "f1")
    assert f.n_flipped == 2
    # Spend is unknown, not zero: every cost-derived figure withholds.
    assert f.amortized.cost_is_lower_bound
    assert f.amortized.cost_usd_per_incident is None
    assert f.breakeven_incident_value_usd is None
    # A withheld breakeven carries no bound flag.
    assert not f.breakeven_is_lower_bound
    for p in f.roi_points:
        assert p.roi is None
        assert p.profit_usd is None
        assert "no priced attempts" in (p.withheld_reason or "")
    # Queries are known even when nothing is priced.
    assert f.marginal.queries_to_flip["median"] == 1.5
    assert f.amortized.queries_per_incident == pytest.approx(3.0)


def test_unknown_family_raises():
    with pytest.raises(ValueError):
        summarize_family(_family_spends(), "nope")


def test_bad_incident_value_raises():
    with pytest.raises(ValueError):
        summarize_family(_family_spends(), "f1",
                         incident_values=(10.0, float("nan")))


# ---------------------------------------------------------------------------
# ROI model
# ---------------------------------------------------------------------------


def test_roi_profitable_campaign():
    p = attacker_roi(10.0, 2, 10.0)
    assert p.profit_usd == pytest.approx(10.0)
    assert p.roi == pytest.approx(1.0)
    assert p.flips_to_breakeven == 1
    assert p.withheld_reason is None


def test_roi_losing_campaign():
    p = attacker_roi(10.0, 2, 1.0)
    assert p.profit_usd == pytest.approx(-8.0)
    assert p.roi == pytest.approx(-0.8)
    assert p.flips_to_breakeven == 10


def test_roi_zero_spend_withholds_ratio():
    p = attacker_roi(0.0, 3, 10.0)
    assert p.profit_usd == pytest.approx(30.0)
    assert p.roi is None
    assert "zero attacker spend" in (p.withheld_reason or "")
    # Already profitable: no flips needed to break even.
    assert p.flips_to_breakeven == 0


def test_roi_zero_measured_spend_with_unpriced_attempts_withholds():
    # Priced attempts cost nothing but some were unpriced: spend is
    # unknown (at least zero), not measured zero.
    p = attacker_roi(0.0, 2, 10.0, spend_is_lower_bound=True)
    assert p.profit_usd is None
    assert p.roi is None
    assert "unknown" in (p.withheld_reason or "")


def test_roi_lower_bound_flag_marks_point_as_upper_bound():
    p = attacker_roi(10.0, 2, 10.0, spend_is_lower_bound=True)
    assert p.spend_is_lower_bound
    assert p.profit_usd == pytest.approx(10.0)
    assert p.roi == pytest.approx(1.0)


def test_roi_rejects_non_bool_lower_bound_flag():
    with pytest.raises(ValueError):
        attacker_roi(10.0, 2, 10.0, spend_is_lower_bound=1)


def test_roi_no_flips_undefined():
    p = attacker_roi(5.0, 0, 100.0)
    assert p.roi is None
    assert p.profit_usd is None
    assert "nothing flipped" in (p.withheld_reason or "")


def test_roi_zero_value_never_breaks_even():
    p = attacker_roi(5.0, 2, 0.0)
    assert p.roi == pytest.approx(-1.0)
    assert p.flips_to_breakeven is None
    assert "never breaks even" in (p.withheld_reason or "")


def test_roi_rejects_negative_inputs():
    with pytest.raises(ValueError):
        attacker_roi(-1.0, 2, 10.0)
    with pytest.raises(ValueError):
        attacker_roi(1.0, 2, -10.0)
    with pytest.raises(ValueError):
        attacker_roi(1.0, -2, 10.0)


def test_roi_grid_covers_default_values():
    pts = roi_grid(3.0, 2)
    assert [p.incident_value_usd for p in pts] == list(
        DEFAULT_INCIDENT_VALUES)
    # At $1 the campaign loses money; at $1000 it is wildly profitable.
    assert pts[0].roi < 0
    assert pts[-1].roi > 100
    # The lower-bound flag passes through to every point.
    lb = roi_grid(3.0, 2, spend_is_lower_bound=True)
    assert all(p.spend_is_lower_bound for p in lb)
    assert not any(p.spend_is_lower_bound for p in pts)


# ---------------------------------------------------------------------------
# Edit distance
# ---------------------------------------------------------------------------


def test_edit_distance_known_pair():
    dist, norm = perturbation_edit_distance("a b c", "a x c")
    assert dist == 1
    assert norm == pytest.approx(1 / 3)


def test_edit_distance_identical_is_zero():
    assert perturbation_edit_distance("same text", "same text") == (0, 0.0)


def test_edit_distance_empty_is_zero():
    assert perturbation_edit_distance("", "") == (0, 0.0)


def test_edit_distance_insertion():
    dist, norm = perturbation_edit_distance("a b", "a b c d")
    assert dist == 2
    assert norm == pytest.approx(0.5)


def test_edit_distance_rejects_non_string():
    with pytest.raises(ValueError):
        perturbation_edit_distance(None, "x")
    with pytest.raises(ValueError):
        perturbation_edit_distance("x", 42)


def test_edit_distance_is_symmetric():
    fwd = perturbation_edit_distance("alpha beta", "alpha gamma delta")
    rev = perturbation_edit_distance("alpha gamma delta", "alpha beta")
    assert fwd == rev


# ---------------------------------------------------------------------------
# Sealed summary
# ---------------------------------------------------------------------------


def test_summary_is_json_safe_and_never_rankable():
    spends = _family_spends()
    summ = summarize_attacker_economics(spends)
    text = json.dumps(summ)  # must not raise
    back = json.loads(text)
    assert back["ranking_eligible"] is False
    fam = back["families"]["f1"]
    assert "marginal_usd_per_flip" in fam
    assert "amortized_usd_per_incident" in fam
    assert "roi_points" in fam
    assert len(fam["roi_points"]) == len(DEFAULT_INCIDENT_VALUES)
    # Overall aggregates the eligible cases across families.
    assert back["overall"]["n_eligible"] == 3
    assert back["overall"]["amortized_usd_per_incident"][
        "total_queries_spent"] == 9


def test_summary_roi_points_carry_lower_bound_flag():
    spends = [
        case_spend_from_record(
            _record("c1", flipped_at=1, unpriced=(0,))),
        case_spend_from_record(_record("c2", flipped_at=2)),
    ]
    summ = summarize_attacker_economics(spends)
    json.dumps(summ)  # the flag is JSON-safe
    pts = summ["families"]["f1"]["roi_points"]
    assert all(p["spend_is_lower_bound"] for p in pts)
    assert all(p["withheld_reason"] is None for p in pts)


def test_summary_multiple_families_stay_separate():
    spends = [
        case_spend_from_record(_record("c1", family="f1", flipped_at=1)),
        case_spend_from_record(_record("c2", family="f2", flipped_at=2)),
    ]
    summ = summarize_attacker_economics(spends)
    assert set(summ["families"]) == {"f1", "f2"}
    assert summ["families"]["f1"]["marginal_usd_per_flip"][
        "queries_to_flip"]["median"] == 1.0
    assert summ["families"]["f2"]["marginal_usd_per_flip"][
        "queries_to_flip"]["median"] == 2.0


def test_summary_no_eligible_raises():
    spends = [case_spend_from_record(
        _record("c1", flipped_at=1, eligible=False))]
    with pytest.raises(ValueError):
        summarize_attacker_economics(spends)


def test_summary_perturbation_stats_flow_through():
    spends = [
        case_spend_from_record(
            _record("c1", flipped_at=1), perturbation=(4, 0.2)),
        case_spend_from_record(
            _record("c2", flipped_at=1), perturbation=(6, 0.3)),
    ]
    summ = summarize_attacker_economics(spends)
    fam = summ["families"]["f1"]
    assert fam["n_perturbations_measured"] == 2
    assert fam["perturbation_edit_distance"]["median"] == 5.0


def test_per_case_spend_is_immutable():
    s = case_spend_from_record(_record("c1", flipped_at=1))
    assert isinstance(s, AttackerCaseSpend)
    with pytest.raises(Exception):
        s.flipped = False  # frozen dataclass
