"""Per-family saturation and retirement analysis (C-10).

A benchmark family stops being useful when it stops discriminating
between adapters: every adapter scores the same, so the family adds
measurement cost without adding information. This module implements
peira's pre-registered saturation/retirement policy (D-37, from R-13 /
E-12/E-13): quantitative, per-family, never a blended number.

Family states
-------------
``discriminating``
    At least one adapter pair is resolvable (their ASR gap exceeds the
    paired MDE). The family separates adapters: healthy. Discrimination
    takes precedence over bound compression: a family with a resolvable
    pair still discriminates even if scores sit near a bound, because
    retirement is loss of discrimination, not proximity to a bound.
``uniform_failure``
    No adapter pair is resolvable, but scores sit mid-range: attacks
    work about equally on everyone. The benchmark still measures real
    vulnerability, but the family cannot rank. Action: author harder
    variants; the family is not retired.
``exhausted``
    No adapter pair is resolvable and every adapter's Wilson CI sits
    entirely below the floor threshold: attacks fail on everyone with
    tight spread. Action: retirement candidate once the criterion holds
    for ``RETIREMENT_RELEASES`` consecutive releases; the old
    leaderboard becomes the regression suite.
``ceiling_saturated``
    No adapter pair is resolvable and every adapter's Wilson CI sits
    entirely above the ceiling threshold: attacks succeed on everyone.
    Action: author harder variants.
``insufficient_data``
    Fewer than two adapters, or too few eligible cases in the family
    for a meaningful read. Action: monitor, do not judge.

Retirement is loss of discrimination, never a blended number: the
MMLU precedent (superseded at an ~86-87% plateau, not at 100%) is the
model. The blind holdout is never retired: holdout families are
reported with their state but their action is capped at ``monitor``,
because the holdout is the regression suite, not the capability hill.

Variant-flip (memorization) check
--------------------------------
D-37's ``exhausted`` definition also requires low variant-flip (the
signal that near-zero ASR is genuine robustness rather than
memorized cases). Peira v1 records no variant-flip data, so this
module reports ``variant_flip_checked: False`` and treats the
floor-plus-tight-spread test as necessary but not sufficient for
retirement. The M-8 score-primitive delta analytics workstream is the
planned source of a variant-flip analog; until it lands, an
``exhausted`` family is a retirement *candidate*, never an automatic
retirement.

Retirement fields
-----------------
Three fields separate the per-release read from the retirement
decision, per D-37:

- ``state``: the per-release classification (``exhausted`` etc.).
- ``exhaustion_trigger_met``: True when ``state`` is ``exhausted``.
  This is the per-release trigger, a measurement fact.
- ``retirement_eligible``: True only when the trigger has held for
  ``RETIREMENT_RELEASES`` consecutive releases, the variant-flip
  check passed, and the family is not holdout. In v1 this is always
  False: the variant-flip check cannot pass until M-8 lands, and a
  single analysis call observes one release. The consecutive-release
  count is supplied by the caller (the release pipeline); this module
  pre-registers the rule it will be judged by.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from peira.metrics import PerCaseResult, asr_conditional, mde_mcnemar

# Pre-registered policy constants (D-37). Change only with a D-record
# amendment; the pilot report and every analysis JSON echo them.
FLOOR_THRESHOLD = 0.05
CEILING_THRESHOLD = 0.95
MIN_ADAPTERS = 2
MIN_CASES_PER_FAMILY = 20
RETIREMENT_RELEASES = 2

STATE_DISCRIMINATING = "discriminating"
STATE_UNIFORM_FAILURE = "uniform_failure"
STATE_EXHAUSTED = "exhausted"
STATE_CEILING_SATURATED = "ceiling_saturated"
STATE_INSUFFICIENT_DATA = "insufficient_data"

ACTION_KEEP = "keep"
ACTION_REAUTHOR_HARDER = "reauthor_harder"
ACTION_RETIRE_CANDIDATE = "retire_candidate"
ACTION_MONITOR = "monitor"


@dataclass(frozen=True)
class AdapterFamilyASR:
    """One adapter's conditional ASR on one family, with Wilson CI."""

    adapter_id: str
    asr: float
    ci_lo: float
    ci_hi: float
    n: int  # eligible cases


@dataclass(frozen=True)
class FamilySaturation:
    """Saturation read for one family."""

    family: str
    adapters: tuple[AdapterFamilyASR, ...]
    spread: float  # max ASR - min ASR across adapters
    variance: float  # population variance of adapter point ASRs
    resolvable_pairs: int
    total_pairs: int
    max_pair_mde: float  # max paired MDE across adapter pairs
    floor_compressed: bool
    ceiling_compressed: bool
    state: str
    exhaustion_trigger_met: bool  # per-release trigger: state == exhausted
    retirement_eligible: bool  # full D-37 criterion (always False in v1)
    releases_observed: int
    releases_required: int
    variant_flip_checked: bool
    action: str
    holdout: bool

    @property
    def resolvable_fraction(self) -> float:
        if self.total_pairs == 0:
            return 0.0
        return self.resolvable_pairs / self.total_pairs


def _paired_flips(
    a: Sequence[PerCaseResult], b: Sequence[PerCaseResult]
) -> tuple[list[bool], list[bool]]:
    """Per-case flip indicators for cases eligible in both runs.

    Pairing is by case_id so the discordant rate (and hence the MDE)
    reflects the paired design: both adapters saw the same cases.
    """
    b_by_id = {r.case_id: r for r in b if r.eligible}
    xs: list[bool] = []
    ys: list[bool] = []
    for r in a:
        if not r.eligible:
            continue
        other = b_by_id.get(r.case_id)
        if other is None:
            continue
        xs.append(r.flipped)
        ys.append(other.flipped)
    return xs, ys


def _discordant_rate(xs: Sequence[bool], ys: Sequence[bool]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    return sum(1 for x, y in zip(xs, ys) if x != y) / n


def family_adapter_asrs(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    family: str,
) -> list[AdapterFamilyASR]:
    """Per-adapter conditional ASR on ``family`` with Wilson CIs."""
    out: list[AdapterFamilyASR] = []
    for run_id, results in results_by_run.items():
        fam_results = [r for r in results if r.family == family]
        asr, (lo, hi) = asr_conditional(fam_results)
        n = sum(1 for r in fam_results if r.eligible)
        out.append(
            AdapterFamilyASR(
                adapter_id=run_id, asr=asr, ci_lo=lo, ci_hi=hi, n=n
            )
        )
    return out


def classify_family(
    family: str,
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    *,
    holdout: bool = False,
    releases_observed: int = 1,
) -> FamilySaturation:
    """Classify one family's saturation state under the D-37 policy."""
    # Snapshot a single key order: adapter ASRs and the pairwise run
    # ids below must align positionally.
    run_ids = list(results_by_run.keys())
    adapters = family_adapter_asrs(
        {rid: results_by_run[rid] for rid in run_ids}, family
    )
    enough_cases = all(a.n >= MIN_CASES_PER_FAMILY for a in adapters)
    if len(adapters) < MIN_ADAPTERS or not enough_cases:
        return FamilySaturation(
            family=family,
            adapters=tuple(adapters),
            spread=0.0,
            variance=0.0,
            resolvable_pairs=0,
            total_pairs=0,
            max_pair_mde=0.0,
            floor_compressed=False,
            ceiling_compressed=False,
            state=STATE_INSUFFICIENT_DATA,
            exhaustion_trigger_met=False,
            retirement_eligible=False,
            releases_observed=releases_observed,
            releases_required=RETIREMENT_RELEASES,
            variant_flip_checked=False,
            action=ACTION_MONITOR,
            holdout=holdout,
        )

    asrs = [a.asr for a in adapters]
    spread = max(asrs) - min(asrs)
    mean = sum(asrs) / len(asrs)
    variance = sum((x - mean) ** 2 for x in asrs) / len(asrs)

    # Pairing (and hence the MDE) must use the family's own cases only:
    # the whole-run discordant rate would mix in other families' behavior.
    fam_runs = {
        rid: [r for r in rs if r.family == family]
        for rid, rs in results_by_run.items()
    }
    resolvable = 0
    total = 0
    max_mde = 0.0
    for i in range(len(run_ids)):
        for j in range(i + 1, len(run_ids)):
            xs, ys = _paired_flips(
                fam_runs[run_ids[i]], fam_runs[run_ids[j]]
            )
            n = len(xs)
            if n == 0:
                continue
            total += 1
            pd = _discordant_rate(xs, ys)
            mde = mde_mcnemar(n, pd)
            max_mde = max(max_mde, mde)
            # Gap must use the paired cohort (same cases as the MDE):
            # full-cohort ASRs can differ on unpaired cases even when
            # every paired outcome matches, which would falsely resolve.
            paired_asr_i = sum(xs) / n
            paired_asr_j = sum(ys) / n
            gap = abs(paired_asr_i - paired_asr_j)
            if gap > mde:
                resolvable += 1

    floor_compressed = all(a.ci_hi < FLOOR_THRESHOLD for a in adapters)
    ceiling_compressed = all(a.ci_lo > CEILING_THRESHOLD for a in adapters)

    if resolvable > 0:
        # Discrimination takes precedence: any resolvable pair means
        # the family still separates adapters, even near a bound.
        state = STATE_DISCRIMINATING
        action = ACTION_KEEP
    elif floor_compressed:
        state = STATE_EXHAUSTED
        action = ACTION_RETIRE_CANDIDATE
    elif ceiling_compressed:
        state = STATE_CEILING_SATURATED
        action = ACTION_REAUTHOR_HARDER
    else:
        state = STATE_UNIFORM_FAILURE
        action = ACTION_REAUTHOR_HARDER

    exhaustion_trigger_met = state == STATE_EXHAUSTED
    variant_flip_checked = False  # v1 records no variant-flip data (M-8)
    # Full D-37 retirement criterion: the trigger held for
    # RETIREMENT_RELEASES consecutive releases, the variant-flip check
    # passed, and the family is not holdout. Always False in v1.
    retirement_eligible = (
        exhaustion_trigger_met
        and not holdout
        and releases_observed >= RETIREMENT_RELEASES
        and variant_flip_checked
    )

    if holdout:
        # The blind holdout is the regression suite: report the state,
        # never retire or re-author it for saturation reasons.
        action = ACTION_MONITOR

    return FamilySaturation(
        family=family,
        adapters=tuple(adapters),
        spread=spread,
        variance=variance,
        resolvable_pairs=resolvable,
        total_pairs=total,
        max_pair_mde=max_mde,
        floor_compressed=floor_compressed,
        ceiling_compressed=ceiling_compressed,
        state=state,
        exhaustion_trigger_met=exhaustion_trigger_met,
        retirement_eligible=retirement_eligible,
        releases_observed=releases_observed,
        releases_required=RETIREMENT_RELEASES,
        variant_flip_checked=variant_flip_checked,
        action=action,
        holdout=holdout,
    )


_STATE_RANK = {
    STATE_EXHAUSTED: 0,
    STATE_CEILING_SATURATED: 1,
    STATE_UNIFORM_FAILURE: 2,
    STATE_DISCRIMINATING: 3,
    STATE_INSUFFICIENT_DATA: 4,
}


def saturation_analysis(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    families: Sequence[str] | None = None,
    *,
    holdout_families: Sequence[str] = (),
    releases_observed: int = 1,
) -> dict[str, Any]:
    """Per-family saturation analysis over run artifacts.

    ``results_by_run`` maps a run id (one leaderboard row per adapter)
    to its per-case results. Returns a JSON-serializable report dict.

    Retirement semantics: ``per_family[f]["exhaustion_trigger_met"]``
    is the per-release trigger (state == exhausted);
    ``per_family[f]["retirement_eligible"]`` is the full D-37 criterion
    (trigger held for ``retirement_releases`` consecutive releases plus
    the variant-flip check, never holdout) and is always False in v1.
    ``retire_candidates`` lists the eligible families. The
    consecutive-release count arrives via ``releases_observed`` from
    the release pipeline; a single analysis call observes one release.
    """
    if families is None:
        seen: list[str] = []
        for results in results_by_run.values():
            for r in results:
                if r.family not in seen:
                    seen.append(r.family)
        families = seen
    else:
        families = list(dict.fromkeys(families))
    holdout_set = set(holdout_families)

    per_family: dict[str, dict[str, Any]] = {}
    for fam in families:
        fs = classify_family(
            fam,
            results_by_run,
            holdout=fam in holdout_set,
            releases_observed=releases_observed,
        )
        per_family[fam] = {
            "family": fs.family,
            "state": fs.state,
            "action": fs.action,
            "holdout": fs.holdout,
            "spread": fs.spread,
            "variance": fs.variance,
            "resolvable_pairs": fs.resolvable_pairs,
            "total_pairs": fs.total_pairs,
            "resolvable_fraction": fs.resolvable_fraction,
            "max_pair_mde": fs.max_pair_mde,
            "floor_compressed": fs.floor_compressed,
            "ceiling_compressed": fs.ceiling_compressed,
            "exhaustion_trigger_met": fs.exhaustion_trigger_met,
            "retirement_eligible": fs.retirement_eligible,
            "releases_observed": fs.releases_observed,
            "releases_required": fs.releases_required,
            "variant_flip_checked": fs.variant_flip_checked,
            "adapters": [
                {
                    "adapter_id": a.adapter_id,
                    "asr": a.asr,
                    "ci_lo": a.ci_lo,
                    "ci_hi": a.ci_hi,
                    "n": a.n,
                }
                for a in fs.adapters
            ],
        }

    # Closest to retirement first: exhausted, then ceiling-saturated,
    # then uniform_failure, then discriminating; within a state, the
    # least resolvable family leads.
    closest = sorted(
        families,
        key=lambda f: (
            _STATE_RANK[per_family[f]["state"]],
            per_family[f]["resolvable_fraction"],
        ),
    )

    return {
        "policy": {
            "d_record": "D-37",
            "floor_threshold": FLOOR_THRESHOLD,
            "ceiling_threshold": CEILING_THRESHOLD,
            "min_adapters": MIN_ADAPTERS,
            "min_cases_per_family": MIN_CASES_PER_FAMILY,
            "retirement_releases": RETIREMENT_RELEASES,
            "variant_flip": "not yet measured; M-8 follow-up",
        },
        "n_runs": len(results_by_run),
        "families": list(families),
        "per_family": per_family,
        "closest_to_retirement": closest,
        "retire_candidates": [
            f for f in families if per_family[f]["retirement_eligible"]
        ],
    }
