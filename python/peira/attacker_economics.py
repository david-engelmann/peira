"""EB-37x: attacker economics (analysis layer).

The attacker-side complement to the M-9/C-9 defender-side cost
accounting. M-9 prices what a flip costs the defender (the deployer's
loss model) and C-9 models attacker cost per flip from single-shot list
prices with an assumed query count. This module measures what the
attacker actually spent: per-case budget consumption recorded by
multi-attempt attack protocols.

Protocol
--------
The input is per-case multi-attempt records in the shape the EB-35
sweep protocol seals on the artifact (``attempts``,
``attempt_flipped``, ``budget_to_first_flip``, ``eligible``): one
attacked-arm call record per attacker query, in order. The module
reads that shape structurally from plain dicts, so it works on the
sealed artifact JSON without importing the sweep driver. The field
contract is documented on :func:`case_spend_from_record`.

Only the attacked arm counts as attacker spend. The benign call is the
harness's measurement, not the attacker's budget: the attacker does
not pay to establish the baseline they are trying to flip.

Two views, never blended
------------------------
Both views are reported because both are useful. The family
summary carries them side by side.

- ``marginal`` ($/flip): over flipped cases only. "When a flip
  happens, what did the attacker pay for it." Median/p90/mean of
  queries-to-flip, attacker tokens per flip, attacker cost per flip.
- ``amortized`` ($/incident): all eligible attacked-arm spend divided
  by the number of flips. The fully-loaded cost of producing one
  incident, including every failed attempt and every never-flipped
  case. "What does one flip cost the attacker once the misses are
  paid for."

Attacker ROI
------------
Given the amortized spend, the module models the attacker's return on
investment as a function of the per-incident value ``v``: the dollar
value one flip is worth to the attacker. Peira cannot know ``v``; the
model reports the breakeven incident value (the ``v`` at which the
campaign breaks even) and ROI at caller-chosen values. A breakeven of
$4.20 says flips are profitable for any attacker who values them above
$4.20. ROI is withheld, never zeroed, when spend is zero or nothing
flipped. When no attempt was priced, spend is unknown rather than
zero, so the cost per incident, the breakeven, and every ROI point are
withheld. When some attempts were unpriced, the spend is a lower bound
and the ROI points say so: profit and ROI are upper bounds,
flips-to-breakeven a lower bound.

Withholding
-----------
Unknown cost is never reported as $0.00 (the M-9 convention). A
to-flip window with any unpriced attempt withholds the case's
cost-to-flip; the amortized totals are then marked as lower bounds.
Cost per flip/incident is undefined when nothing flipped and withheld
as None. When no attempt anywhere was priced, the totals are 0.0 only
by construction of the sum, so cost per incident, the breakeven, and
every ROI point are withheld as unknown instead.

Ranking
-------
Like the sweep runs it analyzes, attacker economics is analyzable but
never rankable: the per-case call count differs from the standard
protocol, so these numbers must not pool with single-shot
leaderboard runs. The sealed summary says so explicitly.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping

#: Canonical incident values (USD) the report evaluates ROI at. The
#: attacker's true per-flip payoff is private; these are reference
#: points, not estimates.
DEFAULT_INCIDENT_VALUES: tuple[float, ...] = (1.0, 10.0, 100.0, 1000.0)

#: Protocol version sealed on the summary dict.
ECONOMICS_PROTOCOL_VERSION = "eb37x/attacker-economics-v1"


# ---------------------------------------------------------------------------
# Small statistics helpers
# ---------------------------------------------------------------------------
#
# The distribution summaries use the exact conventions of the EB-35
# sweep protocol, which seals the multi-attempt shape this module
# analyzes: the statistical median (average of the two middle values
# on even n) and the nearest-rank 90th percentile
# (``math.ceil(0.9 * n)``, the smallest value at or below which 90% of
# the observations fall). The two lanes share the protocol, so the
# summaries must agree. Duplicated rather than imported so this
# module has no dependency on peira.sweep.


def _p90_sorted(vals: list[float]) -> float:
    """Nearest-rank 90th percentile of a sorted non-empty list."""
    rank = max(1, math.ceil(0.9 * len(vals)))
    return vals[rank - 1]


def _dist_stats(vals: list[float]) -> dict[str, float]:
    """Median/p90/mean triple for a non-empty value list.

    Median is the statistical median (not the upper-middle pick); p90
    is the nearest-rank 90th percentile. Both match the EB-35 sweep
    protocol.
    """
    s = sorted(vals)
    return {
        "median": statistics.median(s),
        "p90": _p90_sorted(s),
        "mean": math.fsum(vals) / len(vals),
    }


def _round4(x: float) -> float:
    return round(x, 4)


# ---------------------------------------------------------------------------
# Per-attempt spend parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptSpend:
    """Attacker spend of one attacked-arm attempt.

    ``priced`` is False when the record carries no usage (the call was
    never priced under the run's pricing table). Unpriced attempts
    contribute their query and token counts only when known; their cost
    is unknown, never zero.
    """

    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    priced: bool


def _parse_attempt(rec: Any, case_id: str, index: int) -> AttemptSpend:
    """Parse one attempt record's spend from hostile input.

    ``rec`` is a mapping in the CallRecord dict shape (``usage`` is a
    CallUsage dict or None). Anything else fails closed: spend
    accounting must never silently coerce a corrupt record.
    """
    where = f"case {case_id!r} attempt {index}"
    if not isinstance(rec, Mapping):
        raise ValueError(f"{where}: attempt must be a mapping")
    usage = rec.get("usage")
    if usage is None:
        return AttemptSpend(None, None, None, False)
    if not isinstance(usage, Mapping):
        raise ValueError(f"{where}: usage must be a mapping or None")
    tokens: dict[str, int | None] = {}
    for key in ("tokens_in", "tokens_out"):
        v = usage.get(key)
        if v is None:
            tokens[key] = None
        elif isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(
                f"{where}: usage {key!r} must be a non-negative int, "
                f"got {v!r}"
            )
        else:
            tokens[key] = v
    cost = usage.get("cost_usd")
    if cost is None:
        # Usage present but unpriced: tokens may still be known.
        return AttemptSpend(tokens["tokens_in"], tokens["tokens_out"],
                            None, False)
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise ValueError(
            f"{where}: usage cost_usd must be a finite non-negative "
            f"number, got {cost!r}"
        )
    return AttemptSpend(tokens["tokens_in"], tokens["tokens_out"],
                        float(cost), True)


# ---------------------------------------------------------------------------
# Per-case budget consumption
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttackerCaseSpend:
    """Attacker-side budget consumption of one case's multi-attempt run.

    ``queries_to_flip`` is the budget level of the first flip (None
    when the attack never flipped within the recorded attempts).
    ``tokens_to_flip`` / ``cost_usd_to_flip`` sum the to-flip window:
    attempts 0 through queries_to_flip-1 inclusive, i.e. every query
    the attacker paid for up to and including the winning one.
    ``to_flip_complete`` is False when any window attempt is unpriced
    or lacks token counts; then tokens/cost to flip are None (unknown,
    never zero).

    ``queries_spent`` / ``tokens_spent`` / ``cost_usd_spent`` cover all
    attacked attempts and feed the amortized ($/incident) view.
    ``cost_spent_is_lower_bound`` is True when any attempt was
    unpriced: the total is then a floor, not a figure.

    ``perturbation_edit_distance`` is the winning perturbation's token
    edit distance (benign vs attacked input), attached by the caller
    when the case inputs are available; None when not measured.
    """

    case_id: str
    family: str
    severity: str
    primitive: str
    eligible: bool
    flipped: bool
    queries_to_flip: int | None
    tokens_to_flip: int | None
    cost_usd_to_flip: float | None
    to_flip_complete: bool
    queries_spent: int
    tokens_spent: int | None
    cost_usd_spent: float
    cost_spent_is_lower_bound: bool
    n_attempts: int
    n_priced_attempts: int
    perturbation_edit_distance: int | None = None
    perturbation_edit_distance_norm: float | None = None


def _require_str(d: Mapping[str, Any], key: str, case: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise ValueError(
            f"case {case!r}: field {key!r} must be a non-empty string"
        )
    return v


def case_spend_from_record(
    d: Mapping[str, Any],
    *,
    perturbation: tuple[int, float] | None = None,
) -> AttackerCaseSpend:
    """Build per-case attacker spend from a sweep artifact result dict.

    Field contract (the EB-35 sweep protocol's sealed shape):
    ``case_id``, ``family``, ``severity``, ``primitive`` (non-empty
    strings), ``eligible`` (bool), ``attempts`` (list of CallRecord
    dicts in attack order), ``attempt_flipped`` (parallel list of
    bools), ``budget_to_first_flip`` (positive int grid level, or None
    when nothing flipped; None is inconsistent with any True in
    ``attempt_flipped`` and is rejected). The benign record is ignored: the benign
    arm is the harness's measurement, not attacker spend.

    ``perturbation`` optionally carries the winning perturbation's
    (edit_distance, normalized) pair; see
    :func:`perturbation_edit_distance`.

    Raises ValueError on any shape violation (fail closed).
    """
    if not isinstance(d, Mapping):
        raise ValueError("sweep result must be a mapping")
    case_id = d.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("sweep result needs a non-empty case_id")
    family = _require_str(d, "family", case_id)
    severity = _require_str(d, "severity", case_id)
    primitive = _require_str(d, "primitive", case_id)
    eligible = d.get("eligible")
    if not isinstance(eligible, bool):
        raise ValueError(
            f"case {case_id!r}: eligible must be a boolean"
        )
    attempts = d.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError(
            f"case {case_id!r}: attempts must be a list"
        )
    if not attempts:
        raise ValueError(
            f"case {case_id!r}: attempts must be non-empty"
        )
    attempt_flipped = d.get("attempt_flipped")
    if (
        not isinstance(attempt_flipped, list)
        or len(attempt_flipped) != len(attempts)
        or any(not isinstance(f, bool) for f in attempt_flipped)
    ):
        raise ValueError(
            f"case {case_id!r}: attempt_flipped must be a bool list "
            f"parallel to attempts"
        )
    btf = d.get("budget_to_first_flip")
    if btf is None and any(attempt_flipped):
        raise ValueError(
            f"case {case_id!r}: attempt_flipped records a flip but "
            f"budget_to_first_flip is None"
        )
    if btf is not None:
        if isinstance(btf, bool) or not isinstance(btf, int) or btf <= 0:
            raise ValueError(
                f"case {case_id!r}: budget_to_first_flip must be a "
                f"positive int or None, got {btf!r}"
            )
        if btf > len(attempts):
            raise ValueError(
                f"case {case_id!r}: budget_to_first_flip {btf} exceeds "
                f"the {len(attempts)} recorded attempts"
            )
        # Cumulative invariant: a flip at grid level b means some
        # attempt in the first b flipped.
        if not any(attempt_flipped[:btf]):
            raise ValueError(
                f"case {case_id!r}: budget_to_first_flip={btf} but no "
                f"attempt in the first {btf} flipped"
            )
    flipped = btf is not None

    spends = [
        _parse_attempt(rec, case_id, i)
        for i, rec in enumerate(attempts)
    ]
    queries_spent = len(spends)
    n_priced = sum(1 for s in spends if s.priced)
    tokens_spent: int | None = None
    if all(s.tokens_in is not None and s.tokens_out is not None
           for s in spends):
        tokens_spent = sum(
            s.tokens_in + s.tokens_out  # type: ignore[operator]
            for s in spends
        )
    cost_usd_spent = math.fsum(s.cost_usd for s in spends if s.priced)
    cost_lower_bound = n_priced < len(spends)

    queries_to_flip: int | None = None
    tokens_to_flip: int | None = None
    cost_usd_to_flip: float | None = None
    to_flip_complete = False
    if flipped:
        assert btf is not None
        queries_to_flip = btf
        window = spends[:btf]
        to_flip_complete = all(
            s.priced and s.tokens_in is not None
            and s.tokens_out is not None
            for s in window
        )
        if to_flip_complete:
            tokens_to_flip = sum(
                s.tokens_in + s.tokens_out  # type: ignore[operator]
                for s in window
            )
            cost_usd_to_flip = math.fsum(s.cost_usd for s in window)

    edit: int | None = None
    edit_norm: float | None = None
    if perturbation is not None:
        edit, edit_norm = perturbation
        if (
            isinstance(edit, bool) or not isinstance(edit, int)
            or edit < 0
        ):
            raise ValueError(
                f"case {case_id!r}: perturbation edit distance must be "
                f"a non-negative int, got {edit!r}"
            )
        if (
            isinstance(edit_norm, bool)
            or not isinstance(edit_norm, (int, float))
            or not math.isfinite(edit_norm)
            or not 0.0 <= edit_norm <= 1.0
        ):
            raise ValueError(
                f"case {case_id!r}: perturbation normalized distance "
                f"must be a finite number in [0, 1], got {edit_norm!r}"
            )
        edit_norm = float(edit_norm)

    return AttackerCaseSpend(
        case_id=case_id,
        family=family,
        severity=severity,
        primitive=primitive,
        eligible=bool(eligible),
        flipped=flipped,
        queries_to_flip=queries_to_flip,
        tokens_to_flip=tokens_to_flip,
        cost_usd_to_flip=cost_usd_to_flip,
        to_flip_complete=to_flip_complete,
        queries_spent=queries_spent,
        tokens_spent=tokens_spent,
        cost_usd_spent=cost_usd_spent,
        cost_spent_is_lower_bound=cost_lower_bound,
        n_attempts=len(spends),
        n_priced_attempts=n_priced,
        perturbation_edit_distance=edit,
        perturbation_edit_distance_norm=edit_norm,
    )


# ---------------------------------------------------------------------------
# Winning-perturbation edit distance
# ---------------------------------------------------------------------------


def perturbation_edit_distance(
    benign_text: str, attacked_text: str
) -> tuple[int, float]:
    """Token-level edit distance between two input texts.

    Both arguments are the serialized case inputs (the caller
    serializes deterministically, e.g. JSON with sorted keys). Returns
    ``(distance, normalized)`` where ``normalized`` is
    ``distance / max(len(benign), len(attacked))`` in tokens, 0.0 when
    both are empty. Tokenization is whitespace splitting; the distance
    is the Levenshtein distance over token sequences, computed in
    O(min(m, n)) space with no third-party dependencies.

    For the ``attacker_queries`` sweep dimension the perturbation is
    fixed per case (every attempt queries the same attacked input), so
    the winning perturbation is the case's attacked-vs-benign input
    difference. Dimensions that vary the perturbation per attempt will
    pass the winning attempt's input pair instead.
    """
    if not isinstance(benign_text, str):
        raise ValueError(
            f"benign_text must be a string, got {type(benign_text).__name__}"
        )
    if not isinstance(attacked_text, str):
        raise ValueError(
            f"attacked_text must be a string, "
            f"got {type(attacked_text).__name__}"
        )
    a = benign_text.split()
    b = attacked_text.split()
    if not a and not b:
        return (0, 0.0)
    # Ensure b is the shorter row for the O(min(m,n)) bound.
    if len(b) > len(a):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, tok_a in enumerate(a, 1):
        cur = [i]
        for j, tok_b in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,          # deletion
                cur[j - 1] + 1,      # insertion
                prev[j - 1] + (tok_a != tok_b),  # substitution
            ))
        prev = cur
    dist = prev[-1]
    norm = dist / max(len(a), len(b))
    return (dist, norm)


# ---------------------------------------------------------------------------
# Family summary: marginal ($/flip) and amortized ($/incident) views
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarginalView:
    """$/flip: what a flip that happened cost the attacker.

    Statistics run over flipped eligible cases only. Token and cost
    triples withhold (None) when no flipped case has a complete
    to-flip window; ``withheld_reason`` names the cause. Query counts
    never withhold: every attempt is a query by construction.
    """

    n_flipped: int
    n_complete: int
    queries_to_flip: dict[str, float] | None
    tokens_to_flip: dict[str, float] | None
    cost_usd_to_flip: dict[str, float] | None
    withheld_reason: str | None


@dataclass(frozen=True)
class AmortizedView:
    """$/incident: fully-loaded attacker cost of producing one flip.

    Totals cover every attacked attempt on eligible cases, flipped or
    not: the misses are part of the price. Per-incident figures divide
    by the flip count and are None when nothing flipped (undefined,
    never $0.00). ``cost_is_lower_bound`` marks totals that exclude
    unpriced attempts.
    """

    total_queries_spent: int
    total_tokens_spent: int | None
    total_cost_usd_spent: float
    cost_is_lower_bound: bool
    n_flips: int
    queries_per_incident: float | None
    tokens_per_incident: float | None
    cost_usd_per_incident: float | None


@dataclass(frozen=True)
class RoiPoint:
    """Attacker ROI at one assumed per-incident value.

    ``spend_is_lower_bound`` is True when the spend behind the point
    excludes unpriced attempts: ``profit_usd`` and ``roi`` are then
    upper bounds (the true spend can only be higher) and
    ``flips_to_breakeven`` a lower bound. The bound is flagged, never
    silently dropped.
    """

    incident_value_usd: float
    profit_usd: float | None
    roi: float | None
    flips_to_breakeven: int | None
    withheld_reason: str | None
    spend_is_lower_bound: bool = False


@dataclass(frozen=True)
class FamilyAttackerEconomics:
    """Both economics views for one family, side by side."""

    family: str
    n_eligible: int
    n_flipped: int
    flip_rate: float
    marginal: MarginalView
    amortized: AmortizedView
    breakeven_incident_value_usd: float | None
    breakeven_is_lower_bound: bool
    roi_points: tuple[RoiPoint, ...]
    perturbation_edit_distance: dict[str, float] | None
    perturbation_edit_distance_norm: dict[str, float] | None
    n_perturbations_measured: int


def _eligible(spends: list[AttackerCaseSpend]) -> list[AttackerCaseSpend]:
    return [s for s in spends if s.eligible]


def _summarize_spends(
    fam: list[AttackerCaseSpend],
    label: str,
    incident_values: tuple[float, ...],
) -> FamilyAttackerEconomics:
    """Core summary over a pre-filtered eligible spend list."""
    flipped = [s for s in fam if s.flipped]
    complete = [s for s in flipped if s.to_flip_complete]

    queries = [float(s.queries_to_flip) for s in flipped
               if s.queries_to_flip is not None]
    marginal = MarginalView(
        n_flipped=len(flipped),
        n_complete=len(complete),
        queries_to_flip=(_dist_stats(queries) if queries else None),
        tokens_to_flip=(
            _dist_stats([float(s.tokens_to_flip) for s in complete
                         if s.tokens_to_flip is not None])
            if complete else None
        ),
        cost_usd_to_flip=(
            _dist_stats([s.cost_usd_to_flip for s in complete
                         if s.cost_usd_to_flip is not None])
            if complete else None
        ),
        withheld_reason=(
            None if complete
            else "no flipped case has a complete to-flip window "
                 "(unpriced attempts); token/cost per flip withheld"
        ),
    )

    total_queries = sum(s.queries_spent for s in fam)
    tokens_known = all(s.tokens_spent is not None for s in fam)
    total_tokens = (
        sum(s.tokens_spent for s in fam if s.tokens_spent is not None)
        if tokens_known else None
    )
    total_cost = math.fsum(s.cost_usd_spent for s in fam)
    lower_bound = any(s.cost_spent_is_lower_bound for s in fam)
    any_priced = any(s.n_priced_attempts > 0 for s in fam)
    n_flips = len(flipped)
    amortized = AmortizedView(
        total_queries_spent=total_queries,
        total_tokens_spent=total_tokens,
        total_cost_usd_spent=total_cost,
        cost_is_lower_bound=lower_bound,
        n_flips=n_flips,
        queries_per_incident=(
            total_queries / n_flips if n_flips else None),
        tokens_per_incident=(
            total_tokens / n_flips
            if n_flips and total_tokens is not None else None),
        cost_usd_per_incident=(
            total_cost / n_flips if n_flips and any_priced else None),
    )

    # Unknown spend is withheld, never zeroed: with no priced attempt
    # the totals are 0.0 by construction of the sum, not by
    # measurement, so the breakeven and every ROI point are unknown.
    breakeven = total_cost / n_flips if n_flips and any_priced else None
    breakeven_lower_bound = lower_bound if breakeven is not None else False
    if any_priced or n_flips == 0:
        roi_points = tuple(
            attacker_roi(total_cost, n_flips, float(v),
                         spend_is_lower_bound=lower_bound)
            for v in incident_values
        )
    else:
        roi_points = tuple(
            RoiPoint(float(v), None, None, None,
                     "no priced attempts: attacker spend unknown")
            for v in incident_values
        )

    measured = [
        s for s in flipped
        if s.perturbation_edit_distance is not None
    ]
    if measured:
        dist: dict[str, float] | None = _dist_stats([
            float(s.perturbation_edit_distance)  # type: ignore[arg-type]
            for s in measured
        ])
        norm: dict[str, float] | None = _dist_stats([
            float(s.perturbation_edit_distance_norm)  # type: ignore[arg-type]
            for s in measured
            if s.perturbation_edit_distance_norm is not None
        ])
    else:
        dist = None
        norm = None

    return FamilyAttackerEconomics(
        family=label,
        n_eligible=len(fam),
        n_flipped=n_flips,
        flip_rate=n_flips / len(fam),
        marginal=marginal,
        amortized=amortized,
        breakeven_incident_value_usd=breakeven,
        breakeven_is_lower_bound=breakeven_lower_bound,
        roi_points=roi_points,
        perturbation_edit_distance=dist,
        perturbation_edit_distance_norm=norm,
        n_perturbations_measured=len(measured),
    )


def summarize_family(
    spends: list[AttackerCaseSpend],
    family: str,
    *,
    incident_values: tuple[float, ...] = DEFAULT_INCIDENT_VALUES,
) -> FamilyAttackerEconomics:
    """Build the two-view economics summary for one family.

    ``spends`` may cover many families; only ``family`` (eligible
    cases) contributes. Raises ValueError on an empty or unknown
    family and on non-finite incident values.
    """
    for v in incident_values:
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
        ):
            raise ValueError(
                f"incident values must be finite non-negative numbers, "
                f"got {v!r}"
            )
    fam = [s for s in _eligible(spends) if s.family == family]
    if not fam:
        raise ValueError(
            f"no eligible cases for family {family!r}"
        )
    return _summarize_spends(fam, family, incident_values)


# ---------------------------------------------------------------------------
# Attacker ROI model
# ---------------------------------------------------------------------------


def attacker_roi(
    total_spend_usd: float,
    n_flips: int,
    incident_value_usd: float,
    *,
    spend_is_lower_bound: bool = False,
) -> RoiPoint:
    """Attacker return on investment at one assumed incident value.

    ``incident_value_usd`` is the dollar value one flip is worth to
    the attacker: a private parameter peira cannot observe, so the
    model takes it as an input, never an estimate. ``roi`` is
    ``(n_flips * v - spend) / spend``. ``flips_to_breakeven`` is the
    flip count at which cumulative value covers the spend.

    ``spend_is_lower_bound`` marks spend that excludes unpriced
    attempts: ``profit_usd`` and ``roi`` are then upper bounds and
    ``flips_to_breakeven`` a lower bound, flagged on the returned
    point rather than silently rounded.

    Withholding, never silent: no flips means ROI is undefined (not
    zero); zero spend means ROI is undefined (not infinite); a zero
    incident value can never break even. Each case names its reason.
    """
    for name, v in (("total_spend_usd", total_spend_usd),
                    ("incident_value_usd", incident_value_usd)):
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
        ):
            raise ValueError(
                f"{name} must be a finite non-negative number, got {v!r}"
            )
    if isinstance(n_flips, bool) or not isinstance(n_flips, int) \
            or n_flips < 0:
        raise ValueError(f"n_flips must be a non-negative int, got {n_flips!r}")
    if not isinstance(spend_is_lower_bound, bool):
        raise ValueError(
            f"spend_is_lower_bound must be a bool, "
            f"got {spend_is_lower_bound!r}"
        )
    spend = float(total_spend_usd)
    value = float(incident_value_usd)

    if n_flips == 0:
        return RoiPoint(value, None, None, None,
                        "nothing flipped: ROI undefined")
    if spend == 0.0:
        if spend_is_lower_bound:
            # Priced attempts cost nothing but some were unpriced: the
            # spend is unknown (at least zero), not measured zero.
            return RoiPoint(
                value, None, None, None,
                "attacker spend unknown: some attempts unpriced",
                spend_is_lower_bound,
            )
        # The attacker paid nothing and got flips: profitable at any
        # positive value, but ROI as a ratio is undefined (division by
        # zero is not a finding). Callers must never route unknown
        # spend here: zero means measured zero, not unpriced.
        return RoiPoint(value, n_flips * value, None, 0,
                        "zero attacker spend: ROI undefined",
                        spend_is_lower_bound)
    profit = n_flips * value - spend
    roi = profit / spend
    to_breakeven = (
        math.ceil(spend / value) if value > 0
        else None
    )
    reason = (
        None if value > 0
        else "zero incident value never breaks even"
    )
    return RoiPoint(value, profit, roi, to_breakeven, reason,
                    spend_is_lower_bound)


def roi_grid(
    total_spend_usd: float,
    n_flips: int,
    incident_values: tuple[float, ...] = DEFAULT_INCIDENT_VALUES,
    *,
    spend_is_lower_bound: bool = False,
) -> tuple[RoiPoint, ...]:
    """ROI points over a grid of assumed incident values.

    ``spend_is_lower_bound`` is passed through to every point, so
    lower-bound spend stays flagged (see :func:`attacker_roi`).
    """
    return tuple(
        attacker_roi(total_spend_usd, n_flips, float(v),
                     spend_is_lower_bound=spend_is_lower_bound)
        for v in incident_values
    )


# ---------------------------------------------------------------------------
# Sealed summary (JSON-safe)
# ---------------------------------------------------------------------------


def _marginal_dict(m: MarginalView) -> dict[str, Any]:
    return {
        "n_flipped": m.n_flipped,
        "n_complete": m.n_complete,
        "queries_to_flip": m.queries_to_flip,
        "tokens_to_flip": m.tokens_to_flip,
        "cost_usd_to_flip": (
            {k: _round4(v) for k, v in m.cost_usd_to_flip.items()}
            if m.cost_usd_to_flip is not None else None
        ),
        "withheld_reason": m.withheld_reason,
    }


def _amortized_dict(a: AmortizedView) -> dict[str, Any]:
    return {
        "total_queries_spent": a.total_queries_spent,
        "total_tokens_spent": a.total_tokens_spent,
        "total_cost_usd_spent": _round4(a.total_cost_usd_spent),
        "cost_is_lower_bound": a.cost_is_lower_bound,
        "n_flips": a.n_flips,
        "queries_per_incident": a.queries_per_incident,
        "tokens_per_incident": a.tokens_per_incident,
        "cost_usd_per_incident": (
            _round4(a.cost_usd_per_incident)
            if a.cost_usd_per_incident is not None else None
        ),
    }


def _roi_point_dict(p: RoiPoint) -> dict[str, Any]:
    return {
        "incident_value_usd": p.incident_value_usd,
        "profit_usd": (
            _round4(p.profit_usd) if p.profit_usd is not None else None
        ),
        "roi": p.roi,
        "flips_to_breakeven": p.flips_to_breakeven,
        "withheld_reason": p.withheld_reason,
        "spend_is_lower_bound": p.spend_is_lower_bound,
    }


def _family_dict(f: FamilyAttackerEconomics) -> dict[str, Any]:
    return {
        "n_eligible": f.n_eligible,
        "n_flipped": f.n_flipped,
        "flip_rate": f.flip_rate,
        # Both views, side by side, never blended.
        "marginal_usd_per_flip": _marginal_dict(f.marginal),
        "amortized_usd_per_incident": _amortized_dict(f.amortized),
        "breakeven_incident_value_usd": (
            _round4(f.breakeven_incident_value_usd)
            if f.breakeven_incident_value_usd is not None else None
        ),
        "breakeven_is_lower_bound": f.breakeven_is_lower_bound,
        "roi_points": [_roi_point_dict(p) for p in f.roi_points],
        "perturbation_edit_distance": f.perturbation_edit_distance,
        "perturbation_edit_distance_norm": (
            {k: _round4(v)
             for k, v in f.perturbation_edit_distance_norm.items()}
            if f.perturbation_edit_distance_norm is not None else None
        ),
        "n_perturbations_measured": f.n_perturbations_measured,
    }


def summarize_attacker_economics(
    spends: list[AttackerCaseSpend],
    *,
    incident_values: tuple[float, ...] = DEFAULT_INCIDENT_VALUES,
    strength_dimension: str = "attacker_queries",
) -> dict[str, Any]:
    """Sealed attacker-economics summary over per-case spends.

    Returns per-family and overall summaries, each carrying the
    marginal ($/flip) and amortized ($/incident) views plus the ROI
    model. Pure analysis: no adapter calls, no I/O. Like the sweep
    runs it analyzes, the summary is analyzable but never rankable.
    """
    if not isinstance(strength_dimension, str) or not strength_dimension:
        raise ValueError("strength_dimension must be a non-empty string")
    eligible = _eligible(spends)
    families = sorted({s.family for s in eligible})
    if not families:
        raise ValueError("no eligible cases to summarize")
    fam_dicts = {
        family: _family_dict(
            summarize_family(spends, family,
                             incident_values=incident_values)
        )
        for family in families
    }
    overall = _family_dict(
        _summarize_spends(eligible, "overall", incident_values)
    )
    return {
        "protocol": ECONOMICS_PROTOCOL_VERSION,
        "strength_dimension": strength_dimension,
        "ranking_eligible": False,
        "ranking_ineligible_reason": (
            "attacker economics is measured on multi-attempt sweep runs; "
            "analyzable, never rankable"
        ),
        "families": fam_dicts,
        "overall": overall,
    }
