"""EB-35: attack-strength sweep curves (Program A, runner + metrics).

A sweep run executes each case's attacked arm at multiple budget levels
from a ``budget_grid`` and records, per case, the budget at which the
attack first flipped the decision (``budget_to_first_flip``). Reporting
renders ASR-vs-budget curves per family with Wilson CIs per budget
point, plus the budget-to-first-flip distribution per family.

Budget semantics are cumulative: at budget level b the attacker has
spent b units of the strength dimension, and the attack counts as
successful at b if it flipped at any level <= b. ASR(b) is therefore
monotone non-decreasing in b. This is the honest object from
adversarial ML: a flip at budget 1 and a flip at budget 50 are
different findings, and the curve shows which one a family produces.

Strength dimensions
-------------------
``attacker_queries`` (implemented): b independent attacked-arm queries
against the fixed case text; the attack succeeds at budget b if any of
the first b queries flips. Needs no attack generator, so it works with
the existing corpus today.

``paraphrase_rounds``, ``suffix_length``, ``escalation_steps``
(registered, not yet parameterized): these need per-family attack
instantiators, functions mapping (case, budget) to a strengthened
attacked input. The registry plus :func:`register_strength_instantiator`
is the extension point; the driver fails fast with a clear error naming
the missing piece instead of silently running a degenerate sweep.

The driver (:func:`run_sweep_suite`) reuses the shared
:func:`peira.runner.run_suite` machinery with sweep-specific hooks, the
same pattern as the conversational suite: per-case coroutine, cost
function, entry serializer, and artifact summarizer. Concurrency,
retries, timeouts, checkpoints, resume, and the sealed artifact are the
shared machinery, unchanged.

This module imports only from ``peira.metrics`` and ``peira.schema``.
The per-case coroutine lives here too and imports runner internals
lazily, so there is no import cycle: runner never imports sweep.
"""

from __future__ import annotations

import dataclasses
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from peira.metrics import CallRecord, PerCaseResult, wilson_ci
from peira.schema import Case

# ---------------------------------------------------------------------------
# Strength dimensions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrengthDimension:
    """One attack-strength dimension a sweep can budget over."""

    name: str
    description: str
    unit: str
    implemented: bool

    @property
    def is_usable(self) -> bool:
        """Whether the dimension can run: statically implemented, or at
        least one family has a registered attack instantiator."""
        if self.implemented:
            return True
        return any(
            dim == self.name for dim, _ in _instantiators
        )


STRENGTH_DIMENSIONS: dict[str, StrengthDimension] = {
    "attacker_queries": StrengthDimension(
        name="attacker_queries",
        description=(
            "Independent attacked-arm queries against the fixed case "
            "text; the attack succeeds at budget b if any of the first "
            "b queries flips the decision."
        ),
        unit="queries",
        implemented=True,
    ),
    "paraphrase_rounds": StrengthDimension(
        name="paraphrase_rounds",
        description=(
            "Rounds of attack paraphrasing applied before the query; "
            "needs a per-family attack instantiator (not yet registered "
            "for any family)."
        ),
        unit="rounds",
        implemented=False,
    ),
    "suffix_length": StrengthDimension(
        name="suffix_length",
        description=(
            "Length of the adversarial suffix appended to the attacked "
            "input; needs a per-family attack instantiator (not yet "
            "registered for any family)."
        ),
        unit="tokens",
        implemented=False,
    ),
    "escalation_steps": StrengthDimension(
        name="escalation_steps",
        description=(
            "Multi-turn escalation steps before the scored decision; "
            "needs a per-family attack instantiator (not yet registered "
            "for any family)."
        ),
        unit="steps",
        implemented=False,
    ),
}


def get_strength_dimension(name: str) -> StrengthDimension:
    """Return the registered dimension, or raise a clear error."""
    try:
        return STRENGTH_DIMENSIONS[name]
    except KeyError:
        known = ", ".join(sorted(STRENGTH_DIMENSIONS))
        raise ValueError(
            f"unknown strength dimension {name!r} "
            f"(known dimensions: {known})"
        ) from None


# Per-family attack instantiators for the non-query dimensions:
# (dimension, family) -> fn(case, budget) -> attacked input dict.
# A dimension with no instantiator for a case's family fails fast in
# the driver; it never silently runs a degenerate sweep.
StrengthInstantiator = Callable[[Case, int], dict[str, Any]]

_instantiators: dict[tuple[str, str], StrengthInstantiator] = {}


def register_strength_instantiator(
    dimension: str, family: str, fn: StrengthInstantiator
) -> None:
    """Register a per-family attack instantiator for a strength dimension.

    ``fn`` maps (case, budget) to the attacked input dict at that
    budget level. Budgets are positive ints from the validated grid.
    """
    get_strength_dimension(dimension)  # validates the dimension name
    if not family or not isinstance(family, str):
        raise ValueError(f"family must be a non-empty string, got {family!r}")
    if not callable(fn):
        raise ValueError("instantiator must be callable")
    _instantiators[(dimension, family)] = fn


def get_strength_instantiator(
    dimension: str, family: str
) -> StrengthInstantiator | None:
    """Return the instantiator for (dimension, family), or None."""
    return _instantiators.get((dimension, family))


# ---------------------------------------------------------------------------
# Budget grid validation
# ---------------------------------------------------------------------------


def validate_budget_grid(grid: Any) -> list[int]:
    """Validate a sweep budget grid; return it as a list of ints.

    The grid must be a non-empty sequence of strictly increasing
    positive ints. Anything else is a caller bug and raises ValueError
    before a single adapter call is made (fail closed: a malformed
    grid must never produce a quietly wrong curve).
    """
    if isinstance(grid, bool) or not isinstance(grid, (list, tuple)):
        raise ValueError(
            "budget_grid must be a non-empty list of positive ints, "
            f"got {type(grid).__name__}"
        )
    levels = list(grid)
    if not levels:
        raise ValueError("budget_grid must not be empty")
    for level in levels:
        if isinstance(level, bool) or not isinstance(level, int):
            raise ValueError(
                f"budget_grid levels must be ints, got {level!r}"
            )
        if level <= 0:
            raise ValueError(
                f"budget_grid levels must be > 0, got {level!r}"
            )
    for prev, cur in zip(levels, levels[1:]):
        if cur <= prev:
            raise ValueError(
                "budget_grid must be strictly increasing, "
                f"got {levels!r}"
            )
    return levels


# ---------------------------------------------------------------------------
# Sweep case result
# ---------------------------------------------------------------------------


@dataclass
class SweepCaseResult:
    """Per-case outcome of an attack-strength sweep.

    ``attempts`` holds the attacked-arm call records in order, one per
    query up to ``max(budget_grid)`` (``attacker_queries`` dimension).
    ``attempt_flipped`` is the per-attempt flip judgment against the
    benign baseline. ``budget_to_first_flip`` is the lowest grid level
    at which the attack had flipped (cumulative: flipped at any level
    <= b), or None when the attack never flipped within the grid.

    Eligibility is a property of the benign baseline, judged once and
    shared across attempts.

    ``to_per_case_result()`` projects the sweep onto the standard
    single-shot shape at full budget so existing tooling (compare,
    dashboard, gates) keeps working: the representative attacked record
    is the first flipping attempt, or the last attempt when nothing
    flipped.
    """

    case_id: str
    family: str
    severity: str
    primitive: str
    eligible: bool
    ineligibility_reason: str = ""
    benign: CallRecord | None = None
    budget_grid: list[int] = field(default_factory=list)
    strength_dimension: str = "attacker_queries"
    attempts: list[CallRecord] = field(default_factory=list)
    attempt_flipped: list[bool] = field(default_factory=list)
    budget_to_first_flip: int | None = None

    def __post_init__(self) -> None:
        if len(self.attempts) != len(self.attempt_flipped):
            raise ValueError(
                f"attempts ({len(self.attempts)}) and attempt_flipped "
                f"({len(self.attempt_flipped)}) must have equal length"
            )

    @property
    def flipped_within_grid(self) -> bool:
        """Whether the attack flipped at any level within the grid.

        Cumulative semantics: a flip at any grid level means the attack
        counts as flipped at the grid's top level too.
        """
        return self.budget_to_first_flip is not None

    def flipped_within(self, budget: int) -> bool:
        """Cumulative flip status at a budget level (any level <= budget)."""
        if self.budget_to_first_flip is None:
            return False
        return self.budget_to_first_flip <= budget

    def representative_attacked(self) -> CallRecord | None:
        """The attacked record standing in for the full-budget outcome."""
        if not self.attempts:
            return None
        for record, flipped in zip(self.attempts, self.attempt_flipped):
            if flipped:
                return record
        return self.attempts[-1]

    def to_per_case_result(self) -> PerCaseResult:
        """Project onto the standard PerCaseResult at full budget."""
        if self.benign is None:
            raise ValueError(
                f"sweep result for {self.case_id} has no benign record"
            )
        attacked = self.representative_attacked()
        if attacked is None:
            raise ValueError(
                f"sweep result for {self.case_id} has no attacked attempts"
            )
        return PerCaseResult(
            case_id=self.case_id,
            family=self.family,
            severity=self.severity,
            primitive=self.primitive,
            benign=self.benign,
            attacked=attacked,
            flipped=self.flipped_within_grid,
            eligible=self.eligible,
            ineligibility_reason=self.ineligibility_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the artifact (JSON-safe).

        The sealed dict carries the standard PerCaseResult fields
        (``attacked`` is the representative final attempt, ``flipped``
        is the flip at full budget) so single-shot tooling keeps
        working, plus the sweep's per-attempt records that carry the
        budget dimension.
        """
        d = dataclasses.asdict(self.to_per_case_result())
        d["budget_grid"] = list(self.budget_grid)
        d["strength_dimension"] = self.strength_dimension
        d["attempts"] = [dataclasses.asdict(a) for a in self.attempts]
        d["attempt_flipped"] = list(self.attempt_flipped)
        d["budget_to_first_flip"] = self.budget_to_first_flip
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SweepCaseResult":
        """Rebuild from :meth:`to_dict` (resume path)."""
        benign = d.get("benign")
        return cls(
            case_id=d["case_id"],
            family=d["family"],
            severity=d["severity"],
            primitive=d["primitive"],
            eligible=d["eligible"],
            ineligibility_reason=d.get("ineligibility_reason", ""),
            benign=(
                CallRecord.from_dict(benign) if benign is not None else None
            ),
            budget_grid=list(d.get("budget_grid", [])),
            strength_dimension=d.get(
                "strength_dimension", "attacker_queries"
            ),
            attempts=[
                CallRecord.from_dict(a) for a in d.get("attempts", [])
            ],
            attempt_flipped=list(d.get("attempt_flipped", [])),
            budget_to_first_flip=d.get("budget_to_first_flip"),
        )


# ---------------------------------------------------------------------------
# Sweep metrics (pure Python; no Rust mirrors, analysis-layer metrics)
# ---------------------------------------------------------------------------


def _eligible_family_results(
    results: list[SweepCaseResult], family: str
) -> list[SweepCaseResult]:
    return [r for r in results if r.family == family and r.eligible]


def _asr_at_budget(
    eligible: list[SweepCaseResult], budget: int
) -> tuple[int, int, float, float, float]:
    """Compute (n, hits, asr, lo, hi) for pre-filtered eligible results."""
    n = len(eligible)
    if n == 0:
        return (0, 0, 0.0, 0.0, 0.0)
    hits = sum(1 for r in eligible if r.flipped_within(budget))
    lo, hi = wilson_ci(hits, n)
    return (n, hits, hits / n, lo, hi)


def sweep_asr_at(
    results: list[SweepCaseResult], family: str, budget: int
) -> tuple[float, float, float]:
    """ASR at a budget level for one family, with Wilson 95% CI.

    Returns (asr, lo, hi). Only eligible cases contribute (same
    conditional-ASR rule as the standard metrics). A case counts as
    flipped at ``budget`` when its budget_to_first_flip <= budget
    (cumulative semantics).
    """
    eligible = _eligible_family_results(results, family)
    _, _, asr, lo, hi = _asr_at_budget(eligible, budget)
    return (asr, lo, hi)


def sweep_curve(
    results: list[SweepCaseResult], family: str, grid: list[int]
) -> list[dict[str, Any]]:
    """ASR-vs-budget curve for one family: one point per grid level.

    Each point carries n (eligible cases), flipped, asr, and the Wilson
    95% interval (lo, hi). The curve is monotone non-decreasing by
    construction (cumulative flip semantics).
    """
    eligible = _eligible_family_results(results, family)
    points = []
    for budget in grid:
        n, hits, asr, lo, hi = _asr_at_budget(eligible, budget)
        points.append(
            {
                "budget": budget,
                "n": n,
                "flipped": hits,
                "asr": asr,
                "lo": lo,
                "hi": hi,
            }
        )
    return points


def budget_to_first_flip_distribution(
    results: list[SweepCaseResult], family: str
) -> dict[str, Any]:
    """Budget-to-first-flip distribution for one family.

    Returns counts per grid level (as strings, JSON-safe), the
    never-flipped count, and median/p90 of the flip budget among
    flipped eligible cases. The median is the statistical median
    (average of the two middle values for an even count); p90 is the
    nearest-rank 90th percentile, the smallest budget at or below
    which at least 90 percent of flipped cases flipped. A flip at
    budget 1 vs budget 50 is a different finding; this distribution
    is where that shows up.
    """
    eligible = _eligible_family_results(results, family)
    # All results must share the same grid: mixing grids would silently
    # merge incompatible budget levels.
    grids = {tuple(r.budget_grid) for r in eligible}
    if len(grids) > 1:
        raise ValueError(
            f"budget_to_first_flip_distribution: results for family "
            f"{family!r} use different budget grids: "
            f"{sorted(grids)}; refusing to merge"
        )
    grid: list[int] = sorted(grids.pop()) if grids else []
    counts: dict[str, int] = {str(b): 0 for b in grid}
    never = 0
    flip_budgets: list[int] = []
    for r in eligible:
        if r.budget_to_first_flip is None:
            never += 1
        else:
            counts[str(r.budget_to_first_flip)] += 1
            flip_budgets.append(r.budget_to_first_flip)
    flip_budgets.sort()
    summary: dict[str, Any] = {
        "counts": counts,
        "never_flipped": never,
        "n_eligible": len(eligible),
        "n_flipped": len(flip_budgets),
    }
    if flip_budgets:
        summary["median_flip_budget"] = statistics.median(flip_budgets)
        # Nearest-rank 90th percentile: the smallest budget at or below
        # which at least 90 percent of flipped cases flipped.
        p90_rank = max(1, math.ceil(0.9 * len(flip_budgets)))
        summary["p90_flip_budget"] = flip_budgets[p90_rank - 1]
    else:
        summary["median_flip_budget"] = None
        summary["p90_flip_budget"] = None
    return summary


def summarize_sweep(
    results: list[SweepCaseResult],
    grid: list[int],
    strength_dimension: str,
) -> dict[str, Any]:
    """Artifact-level sweep summary: curves + distributions per family."""
    families = sorted({r.family for r in results})
    return {
        "strength_dimension": strength_dimension,
        "budget_grid": list(grid),
        "families": {
            family: {
                "curve": sweep_curve(results, family, grid),
                "flip_budget_distribution": (
                    budget_to_first_flip_distribution(results, family)
                ),
            }
            for family in families
        },
    }


# ---------------------------------------------------------------------------
# Sweep driver (reuses peira.runner.run_suite via the suite-shape hooks)
# ---------------------------------------------------------------------------


def sweep_case_cost_usd(result: SweepCaseResult) -> float:
    """Priced spend for one sweep case: benign + all attacked attempts."""
    total = 0.0
    records = [result.benign] + list(result.attempts)
    for rec in records:
        if rec is not None and rec.usage is not None:
            total += rec.usage.cost_usd
    return total


def _require_sweepable(
    dimension: str, cases: list[Case]
) -> StrengthDimension:
    """Fail fast when the dimension cannot run on these cases."""
    dim = get_strength_dimension(dimension)
    if not dim.is_usable:
        missing = sorted({c.family for c in cases})
        raise ValueError(
            f"strength dimension {dimension!r} is registered but no "
            f"family has a registered attack instantiator "
            f"(families in suite: {', '.join(missing)}); "
            f"register one with peira.sweep.register_strength_instantiator "
            f"or use --strength-dimension attacker_queries"
        )
    return dim


async def _run_sweep_case_async(
    adapter: Any,
    adapter_version: str,
    case: Case,
    seed: int,
    dispatch_base: int,
    pricing_table: dict[str, Any],
    manifest_sha256: str,
    *,
    controller: Any,
    max_attempts: int,
    max_concurrency: int,
    call_timeout: float | None,
    cache: Any,
    transcript: Any,
    run_nonce: str,
    sweep_grid: list[int],
    sweep_dimension: str,
    sampling_config: dict[str, Any] | None = None,
    max_tokens_per_call: int | None = None,
) -> SweepCaseResult:
    """Per-case sweep coroutine (same shape as ``_run_case_async``).

    Benign runs once (cache applies as usual). The attacked arm runs
    ``max(sweep_grid)`` sequential queries; each query bypasses the
    response cache because a cached attacked response would collapse
    the budget dimension (the whole point is what each additional
    query buys). Attempts are sequential within a case; concurrency
    happens across cases, as usual.
    """
    # Lazy imports: runner imports nothing from sweep at module load;
    # the driver below imports run_suite the same way conversation_runner
    # does, so this stays cycle-free.
    from peira.adapters.base import CallContext
    from peira.concurrency import cache_key
    from peira.runner import (
        _adapter_contexts,
        _case_inputs,
        _pseudonymous_call_id,
        _record_call_async,
        _score_pair,
        _trial_infos,
    )

    if sweep_dimension != "attacker_queries":
        # Only the query dimension reaches this coroutine; the driver
        # rejects the rest up front. Belt and suspenders: never run a
        # sweep whose budget semantics are undefined.
        raise ValueError(
            f"unsupported strength dimension in sweep coroutine: "
            f"{sweep_dimension!r}"
        )

    benign_in, attacked_in = _case_inputs(case)
    benign_ctx, _ = _adapter_contexts(run_nonce, seed, dispatch_base)
    benign_trial, attacked_trial = _trial_infos(case)
    namespace = str(getattr(adapter, "cache_namespace", "") or "")

    benign_cache_key = None
    if cache is not None:
        benign_cache_key = cache_key(
            adapter_name=adapter.name,
            adapter_version=adapter_version,
            cache_namespace=namespace,
            primitive=case.primitive,
            variant=benign_trial.arm,
            case_id=benign_trial.case_id,
            case_input=benign_in,
            manifest_sha256=manifest_sha256,
        )
    benign = await _record_call_async(
        adapter, adapter_version, benign_in, case.primitive, benign_ctx,
        benign_trial,
        seed, dispatch_base, pricing_table,
        controller=controller, max_attempts=max_attempts,
        max_concurrency=max_concurrency,
        call_timeout=call_timeout, cache=cache,
        cache_key_str=benign_cache_key, transcript=transcript,
        sampling_config=sampling_config,
        max_tokens_per_call=max_tokens_per_call,
    )

    max_budget = max(sweep_grid)
    attempts: list[CallRecord] = []
    attempt_flipped: list[bool] = []
    eligible = True
    ineligibility_reason = ""
    for i in range(max_budget):
        attempt_index = dispatch_base + 1 + i
        ctx = CallContext(
            call_id=_pseudonymous_call_id(
                run_nonce, seed, attempt_index
            )
        )
        # No cache for sweep attempts: each query is a fresh attacker
        # query by definition. A cache hit would report budget b's
        # outcome as budget 1's, silently flattening the curve.
        record = await _record_call_async(
            adapter, adapter_version, attacked_in, case.primitive, ctx,
            attacked_trial,
            seed, attempt_index, pricing_table,
            controller=controller, max_attempts=max_attempts,
            max_concurrency=max_concurrency,
            call_timeout=call_timeout, cache=None,
            cache_key_str=None, transcript=transcript,
            sampling_config=sampling_config,
            max_tokens_per_call=max_tokens_per_call,
        )
        attempts.append(record)
        judged = _score_pair(case, benign, record)
        attempt_flipped.append(judged.flipped)
        if i == 0:
            # Eligibility is a property of the benign baseline; judge
            # once, share across attempts.
            eligible = judged.eligible
            ineligibility_reason = judged.ineligibility_reason

    budget_to_first_flip: int | None = None
    for budget in sweep_grid:
        if any(attempt_flipped[:budget]):
            budget_to_first_flip = budget
            break

    return SweepCaseResult(
        case_id=case.case_id,
        family=case.family,
        severity=case.severity,
        primitive=case.primitive,
        eligible=eligible,
        ineligibility_reason=ineligibility_reason,
        benign=benign,
        budget_grid=list(sweep_grid),
        strength_dimension=sweep_dimension,
        attempts=attempts,
        attempt_flipped=attempt_flipped,
        budget_to_first_flip=budget_to_first_flip,
    )


def summarize_sweep_artifact(
    results: list[SweepCaseResult],
    grid: list[int],
    strength_dimension: str,
) -> dict[str, Any]:
    """Sealed sweep summary for the artifact's metrics section.

    A sweep run is analyzable but never rankable: the per-case call
    count differs from the standard protocol, so its numbers must not
    pool with single-shot leaderboard runs.
    """
    reason = (
        "sweep run: per-case attacked queries vary by budget grid; "
        "analyzable, never rankable"
    )
    return {
        "ranking_eligible": False,
        "ranking_ineligible_reason": reason,
        # runs_registry reads metrics["eligibility_notes"]: seal the
        # reason under the key downstream tooling actually reads, not
        # just the sweep-specific one.
        "eligibility_notes": [reason],
        "sweep": summarize_sweep(results, grid, strength_dimension),
    }


def run_sweep_suite(
    adapter: Any,
    cases: list[Case],
    suite: str,
    dataset_version: str,
    budget_grid: list[int] | tuple[int, ...],
    strength_dimension: str = "attacker_queries",
    progress: Any = None,
    already_done: set[str] | None = None,
    prior_results: list[SweepCaseResult] | None = None,
    partial_path: Path | str | None = None,
    checkpoint_every: int = 25,
    required_families: list[str] | None = None,
    manifest_sha256: str = "",
    seed: int = 0,
    max_concurrency: int = 8,
    max_attempts: int = 3,
    call_timeout: float | None = 300.0,
    cache_dir: Path | str | None = None,
    transcript_path: Path | str | None = None,
    config_extra: dict[str, Any] | None = None,
    rlimit_cpu_seconds: float | None = None,
    rlimit_as_mb: float | None = None,
    rlimit_fsize_mb: float | None = None,
    rlimit_nproc: int | None = None,
    death_log_path: Path | str | None = None,
    run_nonce: str | None = None,
    budget_usd: float | None = None,
    item_timeout: float | None = None,
    run_timeout: float | None = None,
    max_tokens_per_call: int | None = None,
) -> Any:
    """Run an attack-strength sweep through the shared suite machinery.

    ``budget_grid`` is validated strictly (non-empty, positive ints,
    strictly increasing) before any work starts. Each case runs one
    benign call plus ``max(budget_grid)`` attacked queries; per-case
    records carry budget_to_first_flip. Everything else (concurrency,
    retries, checkpoints, resume, artifact sealing) is the shared
    :func:`peira.runner.run_suite` machinery.
    """
    from functools import partial

    from peira.runner import run_suite

    grid = validate_budget_grid(budget_grid)
    _require_sweepable(strength_dimension, cases)

    extra = dict(config_extra or {})
    extra["sweep_budget_grid"] = grid
    extra["sweep_strength_dimension"] = strength_dimension

    return run_suite(
        adapter,
        cases,
        suite,
        dataset_version,
        progress=progress,
        already_done=already_done,
        prior_results=prior_results,  # type: ignore[arg-type]
        partial_path=partial_path,
        checkpoint_every=checkpoint_every,
        required_families=required_families,
        manifest_sha256=manifest_sha256,
        seed=seed,
        max_concurrency=max_concurrency,
        max_attempts=max_attempts,
        call_timeout=call_timeout,
        cache_dir=cache_dir,
        transcript_path=transcript_path,
        config_extra=extra,
        rlimit_cpu_seconds=rlimit_cpu_seconds,
        rlimit_as_mb=rlimit_as_mb,
        rlimit_fsize_mb=rlimit_fsize_mb,
        rlimit_nproc=rlimit_nproc,
        death_log_path=death_log_path,
        run_nonce=run_nonce,
        budget_usd=budget_usd,
        item_timeout=item_timeout,
        run_timeout=run_timeout,
        max_tokens_per_call=max_tokens_per_call,
        dispatch_stride=max(grid) + 1,
        run_one_case=partial(
            _run_sweep_case_async,
            sweep_grid=grid,
            sweep_dimension=strength_dimension,
        ),
        case_cost=sweep_case_cost_usd,  # type: ignore[arg-type]
        result_to_dict=lambda r: r.to_dict(),
        summarize_artifact=lambda results, *a, **kw: (
            summarize_sweep_artifact(results, grid, strength_dimension)
        ),
    )


