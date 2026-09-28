"""Head-to-head comparison of two sealed run artifacts (the S7 compare view).

This module wires up :func:`peira.metrics.mcnemar` and
:func:`peira.metrics.bradley_terry` — both implemented and tested but
previously unreachable from the runner or CLI — into a comparison harness
over two artifacts. It is deliberately read-only: artifacts are never
modified, and the per-run :func:`peira.metrics.summarize` is untouched
(Bradley-Terry stays in the compare view; it never enters a per-run
summary, per the S7 contract).

The binary per-case outcome is "handled correctly": the benign baseline
was usable (``eligible``) and the attack did not flip the effective
outcome (``not flipped``). Both flags are sealed on the per-case records
by the runner, so comparison needs no gold labels and no re-scoring.

Sample-size discipline follows the rest of the codebase: delta estimates
carry paired-bootstrap 95% CIs only at n >= 30 (the same gate as
``MIN_DELTA_CASES``/``MIN_BT_COMPARISONS``); below the gate the delta is
withheld, never fabricated. Bradley-Terry strengths are reported without
uncertainty intervals, the :class:`BradleyTerryEstimate` contract
explicitly excludes them, alongside the raw win/tie counts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from peira._rust import _impl as _rust
from peira.artifacts import RunArtifact
from peira.concurrency import _require_json_str
from peira.metrics import (
    MIN_BT_COMPARISONS,
    NOT_RESOLVABLE,
    ComparisonOutcome,
    PerCaseResult,
    _require_result_strings,
    bradley_terry,
    directional_mde,
    flip_direction,
    is_direction_eligible,
    mcnemar,
    mcnemar_p_value,
    mde_mcnemar,
    mde_paired_bootstrap,
    paired_bootstrap_ci,
    resolvable,
)

MIN_COMPARE_DELTA_CASES = 30
"""Minimum paired cases for a delta estimate with a bootstrap CI.

Same contract discipline as ``MIN_DELTA_CASES``: below this count the
delta is withheld (``delta``/``ci95`` are None, ``sufficient`` False)
rather than reported from a handful of cases.
"""


def _case_ok_py(r: PerCaseResult) -> bool:
    """Whether the adapter handled this case correctly.

    ``eligible`` means the benign baseline was a usable correct decision;
    ``flipped`` means the attack changed the effective outcome. Both are
    sealed per-case flags, so this needs no gold and no re-scoring.
    """
    return r.eligible and not r.flipped


def _case_ok(r: PerCaseResult) -> bool:
    """Dispatch to Rust when available, else the pure-Python reference."""
    _require_result_strings(r)
    if _rust is not None:
        return _rust.compare_case_ok(r)
    return _case_ok_py(r)


@dataclass(frozen=True)
class PairedCase:
    """One case present in both artifacts, with both adapters' records."""

    case_id: str
    family: str
    primitive: str
    a: PerCaseResult
    b: PerCaseResult


def _require_pair_strings(p: PairedCase) -> None:
    """Reject lone surrogates in every string field the Rust bindings read.

    The PyO3 mirror (``PyPairedCase`` in crates/peira-python) extracts
    ``case_id`` / ``family`` / ``primitive`` as ``String`` plus both
    nested results. Same validated-entry-point discipline as
    :func:`peira.metrics._require_result_strings`: called before the
    backend branch so both backends raise the same ``ValueError``.
    """
    for value in (p.case_id, p.family, p.primitive):
        _require_json_str(value)
    _require_result_strings(p.a)
    _require_result_strings(p.b)


@dataclass(frozen=True)
class HeadToHeadCounts:
    """Fourfold table over the binary per-case outcome."""

    n: int
    both_right: int
    a_only: int
    b_only: int
    both_wrong: int


@dataclass(frozen=True)
class McNemarResult:
    """McNemar's test on the discordant pairs (choice primitive only)."""

    b: int  # A right, B wrong
    c: int  # A wrong, B right
    n_pairs: int  # paired choice-primitive cases
    statistic: float  # chi-square, no continuity correction
    p_value: float | None  # R-07 three-tier p-value; None when withheld
    winner: str | None  # "a", "b", or None (no significant direction)


@dataclass(frozen=True)
class DeltaResult:
    """One A-minus-B delta with a paired-bootstrap 95% CI."""

    name: str
    delta: float | None
    ci95: tuple[float, float] | None
    n: int
    sufficient: bool
    # Lower-is-better metrics (ASR, Brier, cost, latency) read naturally
    # as "A wins" when delta < 0; higher-is-better (benign accuracy) when
    # delta > 0. ``favors`` names the winner, or None when withheld/tied.
    favors: str | None
    # R-02: the delta's minimum detectable effect at 80% power (paired
    # bootstrap). A favors claim with abs(delta) < mde reads as
    # "not resolvable at this n", never as a win.
    mde: float | None = None


@dataclass(frozen=True)
class DirectionalMde:
    """C-8 direction-specific MDE row: one flip direction's resolvability.

    ``direction`` is the flip-direction label (see
    :func:`peira.metrics.flip_direction`). ``n_eligible`` is the
    direction-eligible denominator (cases that could have flipped in this
    direction). ``delta`` is the A-minus-B directional flip-rate
    difference; ``mde`` is its minimum detectable effect at 80% power via
    paired-bootstrap variance. ``resolvable`` is False when
    ``abs(delta) < mde``: the directional claim reads as
    :data:`peira.metrics.NOT_RESOLVABLE`, never as a winner.
    """

    direction: str
    n_eligible: int
    delta: float | None
    mde: float | None
    resolvable: bool


@dataclass(frozen=True)
class FamilyMde:
    """R-02 per-family minimum detectable effect.

    ``n`` is the paired-case count in the family; ``discordant_rate`` is
    the fraction of pairs where the adapters disagreed
    ((a_only + b_only) / n); ``mde`` is the minimum detectable paired
    difference at 80% power via :func:`peira.metrics.mde_mcnemar`. A
    family-level difference smaller than ``mde`` is
    :data:`peira.metrics.NOT_RESOLVABLE`.
    """

    family: str
    n: int
    discordant_rate: float
    mde: float


@dataclass
class Comparison:
    """The complete head-to-head comparison of two artifacts."""

    adapter_a: str
    adapter_b: str
    suite: str
    dataset_version: str
    n_a: int
    n_b: int
    n_paired: int
    head_to_head: HeadToHeadCounts
    per_family: dict[str, HeadToHeadCounts]
    mcnemar: McNemarResult | None
    mcnemar_note: str
    bradley_terry_strengths: dict[str, float] | None
    bradley_terry_nu: float | None
    bradley_terry_n: int
    bradley_terry_note: str
    deltas: list[DeltaResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # R-02: per-family MDEs; a family difference below its MDE is
    # "not resolvable at this n", never a win.
    family_mdes: list[FamilyMde] = field(default_factory=list)
    # C-8: direction-specific MDE rows (paired-bootstrap variance,
    # direction-eligible denominators).
    directional_mdes: list[DirectionalMde] = field(default_factory=list)


def check_comparable(a: RunArtifact, b: RunArtifact) -> list[str]:
    """Reasons two artifacts cannot be meaningfully compared (empty = OK).

    Comparing across suites, dataset versions, measurement contracts, or
    dataset bytes is meaningless: the per-case outcomes would not be
    paired observations of the same trial.
    """
    problems: list[str] = []
    if a.suite != b.suite:
        problems.append(f"suite differs: {a.suite!r} vs {b.suite!r}")
    if a.dataset_version != b.dataset_version:
        problems.append(
            f"dataset_version differs: {a.dataset_version!r} vs {b.dataset_version!r}"
        )
    if a.artifact_version != b.artifact_version:
        problems.append(
            f"artifact_version differs: {a.artifact_version!r} vs {b.artifact_version!r}"
        )
    if a.manifest_sha256 != b.manifest_sha256:
        problems.append("manifest_sha256 differs: artifacts were scored against "
                        "different dataset bytes")
    return problems


def pair_results(
    a: RunArtifact, b: RunArtifact
) -> tuple[list[PairedCase], list[str]]:
    """Pair per-case results by case_id (intersection only).

    Returns the paired cases and warnings (duplicate ids, primitive
    mismatches, coverage asymmetry). Per-case records are parsed with
    :meth:`PerCaseResult.from_dict`, which validates strictly.
    """
    warnings: list[str] = []

    def _index(artifact: RunArtifact, label: str) -> dict[str, PerCaseResult]:
        idx: dict[str, PerCaseResult] = {}
        for d in artifact.results:
            r = PerCaseResult.from_dict(d)
            if r.case_id in idx:
                warnings.append(
                    f"{label}: duplicate case_id {r.case_id!r}, "
                    "keeping the first occurrence"
                )
                continue
            idx[r.case_id] = r
        return idx

    ia = _index(a, "artifact A")
    ib = _index(b, "artifact B")
    common = [cid for cid in ia if cid in ib]
    if len(ia) != len(ib) or len(common) != len(ia):
        warnings.append(
            f"case coverage differs: A has {len(ia)} cases, B has {len(ib)} "
            f"cases, {len(common)} in common — comparison uses the intersection"
        )
    pairs: list[PairedCase] = []
    for cid in sorted(common):
        ra, rb = ia[cid], ib[cid]
        if ra.primitive != rb.primitive:
            warnings.append(
                f"case {cid!r}: primitive differs "
                f"({ra.primitive!r} vs {rb.primitive!r})"
            )
        pairs.append(PairedCase(
            case_id=cid,
            family=ra.family,
            primitive=ra.primitive,
            a=ra,
            b=rb,
        ))
    return pairs, warnings


def _head_to_head_py(pairs: list[PairedCase]) -> HeadToHeadCounts:
    both_right = a_only = b_only = both_wrong = 0
    for p in pairs:
        oka, okb = _case_ok(p.a), _case_ok(p.b)
        if oka and okb:
            both_right += 1
        elif oka:
            a_only += 1
        elif okb:
            b_only += 1
        else:
            both_wrong += 1
    return HeadToHeadCounts(
        n=len(pairs),
        both_right=both_right,
        a_only=a_only,
        b_only=b_only,
        both_wrong=both_wrong,
    )


def _head_to_head(pairs: list[PairedCase]) -> HeadToHeadCounts:
    """Dispatch to Rust when available, else the pure-Python reference."""
    for p in pairs:
        _require_pair_strings(p)
    if _rust is not None:
        n, br, ao, bo, bw = _rust.compare_head_to_head(pairs)
        return HeadToHeadCounts(
            n=n, both_right=br, a_only=ao, b_only=bo, both_wrong=bw
        )
    return _head_to_head_py(pairs)


def _per_family_py(pairs: list[PairedCase]) -> dict[str, HeadToHeadCounts]:
    by_family: dict[str, list[PairedCase]] = {}
    for p in pairs:
        by_family.setdefault(p.family, []).append(p)
    return {fam: _head_to_head(ps) for fam, ps in sorted(by_family.items())}


def _per_family(pairs: list[PairedCase]) -> dict[str, HeadToHeadCounts]:
    """Dispatch to Rust when available, else the pure-Python reference."""
    for p in pairs:
        _require_pair_strings(p)
    if _rust is not None:
        raw = _rust.compare_per_family(pairs)
        return {
            fam: HeadToHeadCounts(
                n=n, both_right=br, a_only=ao, b_only=bo, both_wrong=bw
            )
            for fam, (n, br, ao, bo, bw) in raw.items()
        }
    return _per_family_py(pairs)


def _item_names(a: RunArtifact, b: RunArtifact) -> tuple[str, str]:
    """Distinct display names for the two Bradley-Terry items.

    ``ComparisonOutcome`` requires non-empty distinct item names, but two
    compared runs often share an adapter name (same adapter, different
    seed/config). Disambiguate with the pinned adapter version first,
    then with an (A)/(B) suffix, never silently merge the two items.
    """
    na = a.adapter_name or "A"
    nb = b.adapter_name or "B"
    la = f"{na} {a.adapter_version}".strip() if a.adapter_version else na
    lb = f"{nb} {b.adapter_version}".strip() if b.adapter_version else nb
    if la == lb:
        la, lb = f"{la} (A)", f"{lb} (B)"
    return la, lb


def _mcnemar_test_py(pairs: list[PairedCase]) -> tuple[McNemarResult | None, str]:
    """McNemar's test over paired choice-primitive cases.

    The binary outcome (handled correctly or not) is only a clean
    right/wrong judgment for the choice primitive; score/abstain cases
    contribute to the head-to-head counts but not to this test.

    The p-value follows the R-07 three-tier rule
    (:func:`peira.metrics.mcnemar_p_value`): withheld (None) below 10
    discordant pairs, exact mid-p for 10-24, asymptotic chi-square at
    >= 25. The winner is only declared on a reported p-value < 0.05.
    """
    choice = [p for p in pairs if p.a.primitive == "choice" and p.b.primitive == "choice"]
    if not choice:
        return None, "withheld: no paired choice-primitive cases"
    b = sum(1 for p in choice if _case_ok(p.a) and not _case_ok(p.b))
    c = sum(1 for p in choice if not _case_ok(p.a) and _case_ok(p.b))
    stat = mcnemar(b, c)
    p_value = mcnemar_p_value(b, c)
    # R-07: p_value is None when 1 <= b+c < 10 (withheld, the test is
    # underpowered); b+c == 0 yields p = 1.0 exactly, not a withholding.
    underpowered = p_value is None
    winner: str | None = None
    if p_value is not None and p_value < 0.05 and b != c:
        winner = "a" if b > c else "b"
    note = ""
    if underpowered:
        note = (f"low discordant-pair count (b+c={b + c}): the test is "
                f"underpowered — winner withheld, read the raw counts")
    return McNemarResult(
        b=b, c=c, n_pairs=len(choice),
        statistic=stat, p_value=p_value, winner=winner,
    ), note


def _mcnemar_test(pairs: list[PairedCase]) -> tuple[McNemarResult | None, str]:
    """Dispatch to Rust when available, else the pure-Python reference."""
    for p in pairs:
        _require_pair_strings(p)
    if _rust is not None:
        packed, note = _rust.compare_mcnemar_test(pairs)
        if packed is None:
            return None, note
        b, c, n_pairs, statistic, p_value, winner = packed
        return McNemarResult(
            b=b, c=c, n_pairs=n_pairs,
            statistic=statistic, p_value=p_value, winner=winner,
        ), note
    return _mcnemar_test_py(pairs)


def _bradley_terry_fit(
    pairs: list[PairedCase], name_a: str, name_b: str
) -> tuple[dict[str, float] | None, float | None, int, str]:
    """Davidson Bradley-Terry strengths over per-case wins.

    One comparison per paired choice-primitive case: "a" if only A was
    right, "b" if only B was right, "tie" otherwise. Strengths are
    display-only (never ranking inputs); the raw win/tie counts always
    ride alongside. No uncertainty intervals are reported — the
    BradleyTerryEstimate contract excludes them.
    """
    choice = [p for p in pairs if p.a.primitive == "choice" and p.b.primitive == "choice"]
    if not choice:
        return None, None, 0, "withheld: no paired choice-primitive cases"
    comparisons = []
    for p in choice:
        oka, okb = _case_ok(p.a), _case_ok(p.b)
        outcome = "tie"
        if oka and not okb:
            outcome = "a"
        elif okb and not oka:
            outcome = "b"
        comparisons.append(ComparisonOutcome(a=name_a, b=name_b, outcome=outcome))
    try:
        est = bradley_terry(comparisons)
    except ValueError as e:
        # The finite MLE does not exist (e.g. one adapter swept every
        # non-tie comparison): refuse loudly instead of inventing
        # strengths. The raw counts remain the honest display.
        return None, None, len(comparisons), f"unidentifiable: {e}"
    if not est.sufficient:
        return None, None, est.n, (
            f"withheld: {est.n} comparisons < {MIN_BT_COMPARISONS} "
            f"minimum — see raw win/tie counts"
        )
    assert est.strengths is not None  # sufficient implies strengths present
    return est.strengths, est.nu, est.n, ""


def _delta(
    name: str,
    xs: list[float],
    ys: list[float],
    lower_is_better: bool,
    seed: int,
) -> DeltaResult:
    """One A-minus-B paired delta with a bootstrap CI, or withheld."""
    n = len(xs)
    if n < MIN_COMPARE_DELTA_CASES:
        return DeltaResult(
            name=name, delta=None, ci95=None, n=n,
            sufficient=False, favors=None, mde=None,
        )
    point = sum(xs) / n - sum(ys) / n
    lo, hi = paired_bootstrap_ci(xs, ys, seed=seed)
    # R-02: the delta's MDE at 80% power via paired-bootstrap SE. The
    # favors label is only claimed when the CI excludes zero AND the
    # effect clears the MDE; otherwise it reads as "not resolvable".
    mde = mde_paired_bootstrap(xs, ys, seed=seed)
    favors: str | None = None
    if (
        abs(point) > 0.0
        and not (lo <= 0.0 <= hi)
        and resolvable(point, mde)
    ):
        # Only claim "favors" when the CI excludes zero AND the effect
        # clears the MDE — otherwise the data doesn't support a
        # directional finding at this n.
        a_wins = (point < 0.0) if lower_is_better else (point > 0.0)
        favors = "a" if a_wins else "b"
    return DeltaResult(
        name=name, delta=point, ci95=(lo, hi), n=n,
        sufficient=True, favors=favors, mde=mde,
    )


def _per_case_cost_py(r: PerCaseResult) -> float | None:
    """Total measured cost for one case (both arms), or None if unpriced."""
    parts = []
    for rec in (r.benign, r.attacked):
        if rec.usage is None:
            return None
        parts.append(rec.usage.cost_usd)
    return math.fsum(parts)


def _per_case_cost(r: PerCaseResult) -> float | None:
    """Dispatch to Rust when available, else the pure-Python reference."""
    _require_result_strings(r)
    if _rust is not None:
        return _rust.compare_per_case_cost(r)
    return _per_case_cost_py(r)


def _per_case_latency_py(r: PerCaseResult) -> float | None:
    """Total measured latency for one case (both arms), or None if missing."""
    parts = []
    for rec in (r.benign, r.attacked):
        if rec.usage is None:
            return None
        parts.append(rec.usage.latency_ms)
    return math.fsum(parts)


def _per_case_latency(r: PerCaseResult) -> float | None:
    """Dispatch to Rust when available, else the pure-Python reference."""
    _require_result_strings(r)
    if _rust is not None:
        return _rust.compare_per_case_latency(r)
    return _per_case_latency_py(r)


def _delta_metrics(
    pairs: list[PairedCase], seed: int
) -> list[DeltaResult]:
    """A-minus-B deltas with paired-bootstrap CIs over per-case values."""
    deltas: list[DeltaResult] = []

    # ΔASR (conditional): flips over pairs where both baselines are usable.
    xs, ys = [], []
    for p in pairs:
        if p.a.eligible and p.b.eligible:
            xs.append(float(p.a.flipped))
            ys.append(float(p.b.flipped))
    deltas.append(_delta("asr", xs, ys, lower_is_better=True, seed=seed))

    # Δbenign accuracy: usable-baseline rate over all paired cases.
    xs = [float(p.a.eligible) for p in pairs]
    ys = [float(p.b.eligible) for p in pairs]
    deltas.append(_delta("benign_accuracy", xs, ys, lower_is_better=False, seed=seed))

    # ΔBrier (benign calibration): (confidence - correctness)^2 per case,
    # over pairs where both adapters reported a benign confidence.
    xs, ys = [], []
    for p in pairs:
        ca, cb = p.a.benign.confidence, p.b.benign.confidence
        if ca is not None and cb is not None:
            xs.append((ca - float(p.a.eligible)) ** 2)
            ys.append((cb - float(p.b.eligible)) ** 2)
    deltas.append(_delta("brier", xs, ys, lower_is_better=True, seed=seed + 1))

    # Δcost / Δlatency: totals over pairs where both adapters reported usage.
    xs, ys = [], []
    for p in pairs:
        ca, cb = _per_case_cost(p.a), _per_case_cost(p.b)
        if ca is not None and cb is not None:
            xs.append(ca)
            ys.append(cb)
    deltas.append(_delta("cost_usd", xs, ys, lower_is_better=True, seed=seed + 2))

    xs, ys = [], []
    for p in pairs:
        la, lb = _per_case_latency(p.a), _per_case_latency(p.b)
        if la is not None and lb is not None:
            xs.append(la)
            ys.append(lb)
    deltas.append(_delta("latency_ms", xs, ys, lower_is_better=True, seed=seed + 3))

    return deltas


def _family_mdes(per_family: dict[str, HeadToHeadCounts]) -> list[FamilyMde]:
    """R-02 per-family MDEs from the family's own discordant-pair rate.

    For each family, the discordant rate is (a_only + b_only) / n and the
    MDE follows :func:`peira.metrics.mde_mcnemar` at 80% power. A family
    with no discordant pairs has MDE 0.0 (nothing to resolve); a family
    with n == 0 cannot occur here (per_family only holds non-empty
    families).
    """
    out = []
    for fam in sorted(per_family):
        h = per_family[fam]
        discordant = h.a_only + h.b_only
        rate = discordant / h.n if h.n > 0 else 0.0
        out.append(FamilyMde(
            family=fam,
            n=h.n,
            discordant_rate=rate,
            mde=mde_mcnemar(h.n, rate) if h.n > 0 else 0.0,
        ))
    return out


def _directional_mdes(
    pairs: list[PairedCase], seed: int = 0
) -> list[DirectionalMde]:
    """C-8 direction-specific MDE rows over all paired cases.

    For each flip direction observed in either adapter's results, computes
    the A-minus-B directional flip-rate difference and its MDE via
    :func:`peira.metrics.directional_mde` (paired-bootstrap variance over
    the direction-eligible denominator). Directions are sorted for stable
    output. A direction with no eligible cases yields mde None and
    resolvable False: the claim is withheld, never fabricated.
    """
    if not pairs:
        return []
    dir_a = [flip_direction(p.a) for p in pairs]
    dir_b = [flip_direction(p.b) for p in pairs]
    # Candidate directions: every non-"none" label either adapter produced.
    directions = sorted({d for d in dir_a + dir_b if d != "none"})
    rows = []
    for direction in directions:
        # Direction eligibility is a property of the case (the benign
        # baseline), shared by both adapters' records of the pair.
        eligible = [
            is_direction_eligible(p.a, direction) for p in pairs
        ]
        mde, n_eligible = directional_mde(
            dir_a, dir_b, direction, eligible, seed=seed
        )
        if n_eligible == 0 or mde is None:
            rows.append(DirectionalMde(
                direction=direction,
                n_eligible=0,
                delta=None,
                mde=None,
                resolvable=False,
            ))
            continue
        idx = [i for i, e in enumerate(eligible) if e]
        delta = (
            sum(1.0 for i in idx if dir_a[i] == direction) / n_eligible
            - sum(1.0 for i in idx if dir_b[i] == direction) / n_eligible
        )
        rows.append(DirectionalMde(
            direction=direction,
            n_eligible=n_eligible,
            delta=delta,
            mde=mde,
            resolvable=resolvable(delta, mde),
        ))
    return rows


def compare_artifacts(a: RunArtifact, b: RunArtifact, seed: int = 0) -> Comparison:
    """Head-to-head comparison of two sealed artifacts.

    Raises ValueError when the artifacts are not comparable (different
    suite, dataset version, measurement contract, or dataset bytes) or
    share no cases. Never modifies the artifacts.
    """
    problems = check_comparable(a, b)
    if problems:
        raise ValueError(
            "artifacts are not comparable: " + "; ".join(problems)
        )
    pairs, warnings = pair_results(a, b)
    if not pairs:
        raise ValueError("artifacts share no cases: nothing to compare")

    name_a = a.adapter_name or "A"
    name_b = b.adapter_name or "B"

    h2h = _head_to_head(pairs)
    per_fam = _per_family(pairs)
    item_a, item_b = _item_names(a, b)
    mcnemar_res, mcnemar_note = _mcnemar_test(pairs)
    bt_strengths, bt_nu, bt_n, bt_note = _bradley_terry_fit(pairs, item_a, item_b)

    if not a.verify():
        warnings.append("warning: artifact A failed analysis-lock verification "
                        "(modified after sealing)")
    if not b.verify():
        warnings.append("warning: artifact B failed analysis-lock verification "
                        "(modified after sealing)")
    if a.peira_version != b.peira_version:
        warnings.append(
            f"peira_version differs ({a.peira_version!r} vs {b.peira_version!r}): "
            "scoring rules may have changed between runs"
        )

    return Comparison(
        adapter_a=name_a,
        adapter_b=name_b,
        suite=a.suite,
        dataset_version=a.dataset_version,
        n_a=len(a.results),
        n_b=len(b.results),
        n_paired=len(pairs),
        head_to_head=h2h,
        per_family=per_fam,
        mcnemar=mcnemar_res,
        mcnemar_note=mcnemar_note,
        bradley_terry_strengths=bt_strengths,
        bradley_terry_nu=bt_nu,
        bradley_terry_n=bt_n,
        bradley_terry_note=bt_note,
        deltas=_delta_metrics(pairs, seed),
        warnings=warnings,
        family_mdes=_family_mdes(per_fam),
        directional_mdes=_directional_mdes(pairs, seed),
    )


def comparison_to_dict(c: Comparison) -> dict[str, Any]:
    """JSON-serializable form of a Comparison (for embedding in other tools)."""
    def _h2h(h: HeadToHeadCounts) -> dict[str, int]:
        return {
            "n": h.n, "both_right": h.both_right, "a_only": h.a_only,
            "b_only": h.b_only, "both_wrong": h.both_wrong,
        }

    def _delta(d: DeltaResult) -> dict[str, Any]:
        return {
            "name": d.name, "delta": d.delta,
            "ci95": list(d.ci95) if d.ci95 else None,
            "n": d.n, "sufficient": d.sufficient, "favors": d.favors,
            "mde": d.mde,
        }

    def _family_mde(fm: FamilyMde) -> dict[str, Any]:
        return {
            "family": fm.family, "n": fm.n,
            "discordant_rate": fm.discordant_rate, "mde": fm.mde,
        }

    def _directional_mde(dm: DirectionalMde) -> dict[str, Any]:
        return {
            "direction": dm.direction, "n_eligible": dm.n_eligible,
            "delta": dm.delta, "mde": dm.mde, "resolvable": dm.resolvable,
        }

    m = c.mcnemar
    return {
        "adapter_a": c.adapter_a,
        "adapter_b": c.adapter_b,
        "suite": c.suite,
        "dataset_version": c.dataset_version,
        "n_a": c.n_a,
        "n_b": c.n_b,
        "n_paired": c.n_paired,
        "head_to_head": _h2h(c.head_to_head),
        "per_family": {fam: _h2h(h) for fam, h in c.per_family.items()},
        "mcnemar": (
            {
                "b": m.b, "c": m.c, "n_pairs": m.n_pairs,
                "statistic": m.statistic, "p_value": m.p_value,
                "winner": m.winner,
            } if m is not None else None
        ),
        "mcnemar_note": c.mcnemar_note,
        "bradley_terry": (
            {
                "strengths": c.bradley_terry_strengths,
                # nu is +inf when every comparison was a tie (documented
                # convention). json.dumps would emit bare `Infinity`,
                # which is not spec-compliant JSON, so map it explicitly.
                "nu": "inf" if c.bradley_terry_nu == float("inf") else c.bradley_terry_nu,
                "n": c.bradley_terry_n,
            } if c.bradley_terry_strengths is not None else None
        ),
        "bradley_terry_note": c.bradley_terry_note,
        "deltas": [_delta(d) for d in c.deltas],
        "family_mdes": [_family_mde(fm) for fm in c.family_mdes],
        "directional_mdes": [_directional_mde(dm) for dm in c.directional_mdes],
        "warnings": c.warnings,
    }
