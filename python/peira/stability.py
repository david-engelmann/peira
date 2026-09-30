"""M-7 multi-seed stability protocol + longitudinal drift watch.

Why this exists: "we ran it three times" is what lets peira's numbers
survive vendor pushback. A single-seed ASR is a point estimate with no
run-to-run story; a vendor whose model looks bad can always claim the
seed was unlucky. The k-seed protocol (k >= 3) re-runs the suite under
different run seeds and reports:

- ``pass^k``: the fraction of eligible cases whose flip outcome agrees
  across all k seeds. The headline stability number: pass^3 = 0.94
  means 94% of cases flip (or don't) identically on all three seeds.
- Variance decomposition, never one collapsed std: sampling variance
  (Wilson CI on the pooled ASR), run variance (sd of per-seed ASRs),
  and item variance (heterogeneity of per-case flip rates + the churn
  count of cases with 0 < flip rate < 1).

Layered randomness must not be compressed into one std: the Wilson
interval answers "what if we ran more cases", the run sd answers
"what if we ran more seeds", and the item heterogeneity answers
"do flips concentrate on a stable subset of cases or churn".

Drift watch compares two runs of the same adapter id (e.g. before and
after a model version bump) with per-family McNemar tests on paired
flip outcomes. It reports newly-flipping vs newly-fixed cases, never
net deltas: aggregates can rise while a large share of items reliably
deteriorate, and the net hides that.

Cost gate: the k-seed commitment multiplies priced spend by k. The
machinery here is cost-agnostic, but enabling multi-seed runs on paid
adapters requires a ledger-planned cost pilot first (see
``docs/Methodology.md`` M-7). Mock/local pilots cost nothing.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from peira.metrics import PerCaseResult, mcnemar_p_value, wilson_ci

#: Minimum seed count for a stability claim. k = 2 can only report
#: agreement, not stability; the protocol requires k >= 3.
MIN_SEEDS = 3

#: Significance level for drift-watch degradation flags.
DRIFT_ALPHA = 0.05


def _eligible_flip_map(results: list[PerCaseResult]) -> dict[str, bool]:
    """case_id -> flipped for eligible results only."""
    return {r.case_id: r.flipped for r in results if r.eligible}


@dataclass(frozen=True)
class StabilityResult:
    """The k-seed stability analysis over one adapter x suite."""

    seeds: list[int]
    #: Number of seed runs k. Set by flip_agreement; seeds (the actual
    #: values) is filled by the caller afterwards.
    k: int
    #: Eligible cases analyzed (must be identical across seeds).
    n_cases: int
    #: All cases per run, including ineligible ones.
    n_cases_total: int
    #: Per-seed ASR over eligible cases, in seed order.
    per_seed_asr: list[float]
    #: Pooled ASR over all seed x case observations.
    pooled_asr: float
    #: Fraction of eligible cases with identical flip outcomes on all
    #: k seeds. The headline stability number.
    pass_k: float
    #: Eligible cases with full agreement (numerator of pass_k).
    n_agree: int
    #: case_id -> fraction of seeds on which the case flipped.
    per_case_flip_rate: dict[str, float] = field(default_factory=dict)
    # -- variance decomposition (never one collapsed std) --
    #: Sampling variance: Wilson 95% CI on the pooled ASR.
    wilson_ci: tuple[float, float] = (0.0, 0.0)
    #: Run variance: sample sd of the per-seed ASRs.
    run_sd: float = 0.0
    #: Item variance: variance of per-case flip rates across cases.
    item_variance: float = 0.0
    #: Cases with 0 < flip rate < 1: the unstable subset.
    n_churn: int = 0
    #: Seeds excluded from the analysis because their run did not
    #: complete (e.g. budget termination). A terminated seed is
    #: dropped, never counted as a quiet non-flip.
    excluded_seeds: list[int] = field(default_factory=list)

    def summary_text(self) -> str:
        """One-line human-readable stability summary."""
        k = self.k or len(self.seeds)
        lo, hi = self.wilson_ci
        if self.n_cases == 0:
            # No eligible cases: pass^k is undefined, not zero.
            # Reporting 0.0% would read as measured zero agreement.
            agreement = f"pass^{k} withheld (no eligible cases)"
        else:
            agreement = (
                f"pass^{k} = {self.pass_k:.1%} case agreement"
            )
        return (
            f"ASR = {self.pooled_asr:.1%} "
            f"(Wilson 95% CI [{lo:.1%}, {hi:.1%}]; "
            f"run-to-run sd {self.run_sd:.1%} across {k} seeds; "
            f"{agreement}; "
            f"{self.n_churn} churn cases)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": list(self.seeds),
            "k": self.k,
            "n_cases": self.n_cases,
            "n_cases_total": self.n_cases_total,
            "per_seed_asr": list(self.per_seed_asr),
            "pooled_asr": self.pooled_asr,
            "pass_k": self.pass_k,
            "n_agree": self.n_agree,
            "per_case_flip_rate": dict(self.per_case_flip_rate),
            "wilson_ci": [self.wilson_ci[0], self.wilson_ci[1]],
            "run_sd": self.run_sd,
            "item_variance": self.item_variance,
            "n_churn": self.n_churn,
            "excluded_seeds": list(self.excluded_seeds),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StabilityResult":
        ci = d.get("wilson_ci", [0.0, 0.0])
        return cls(
            seeds=list(d.get("seeds", [])),
            # Older artifacts predate the explicit k field; fall back to
            # the seed list length.
            k=int(d.get("k", 0)) or len(d.get("seeds", [])),
            n_cases=int(d.get("n_cases", 0)),
            n_cases_total=int(d.get("n_cases_total", 0)),
            per_seed_asr=[float(x) for x in d.get("per_seed_asr", [])],
            pooled_asr=float(d.get("pooled_asr", 0.0)),
            pass_k=float(d.get("pass_k", 0.0)),
            n_agree=int(d.get("n_agree", 0)),
            per_case_flip_rate={
                str(k): float(v)
                for k, v in d.get("per_case_flip_rate", {}).items()
            },
            wilson_ci=(float(ci[0]), float(ci[1])),
            run_sd=float(d.get("run_sd", 0.0)),
            item_variance=float(d.get("item_variance", 0.0)),
            n_churn=int(d.get("n_churn", 0)),
            excluded_seeds=[int(s) for s in d.get("excluded_seeds", [])],
        )


def _check_seed_alignment(
    results_by_seed: list[list[PerCaseResult]],
) -> list[str]:
    """Validate that every seed run scored the same case set.

    Returns the canonical case-id order (from the first run). Raises
    ValueError on any misalignment: stability over different case sets
    is meaningless.
    """
    if len(results_by_seed) < 2:
        raise ValueError(
            f"stability needs >= 2 seed runs, got {len(results_by_seed)}"
        )
    canonical = [r.case_id for r in results_by_seed[0]]
    if len(set(canonical)) != len(canonical):
        raise ValueError("duplicate case ids in the first seed run")
    canonical_set = set(canonical)
    for i, results in enumerate(results_by_seed[1:], start=1):
        ids = [r.case_id for r in results]
        if set(ids) != canonical_set or len(set(ids)) != len(ids):
            raise ValueError(
                f"seed run {i} scored a different case set than seed "
                f"run 0 ({len(ids)} cases vs {len(canonical)})"
            )
    return canonical


def flip_agreement(
    results_by_seed: list[list[PerCaseResult]],
) -> StabilityResult:
    """Compute the k-seed stability analysis.

    ``results_by_seed`` is one per-seed list of PerCaseResult, in seed
    order. All runs must cover the same case set (checked). Only
    eligible cases enter the agreement statistics; ineligible cases
    are counted in ``n_cases_total`` but excluded from pass^k, ASRs,
    and the variance decomposition, because a case with no usable
    benign baseline has no flip outcome to agree on.
    """
    canonical = _check_seed_alignment(results_by_seed)
    k = len(results_by_seed)
    seeds_flips = [_eligible_flip_map(r) for r in results_by_seed]
    # Eligible in ALL runs: a case eligible in one seed but not another
    # has no paired outcome to agree on.
    eligible_ids = [
        cid for cid in canonical if all(cid in m for m in seeds_flips)
    ]
    n_total = len(canonical)

    per_case_flip_rate: dict[str, float] = {}
    n_agree = 0
    for cid in eligible_ids:
        outcomes = [m[cid] for m in seeds_flips]
        rate = sum(outcomes) / k
        per_case_flip_rate[cid] = rate
        if all(o == outcomes[0] for o in outcomes):
            n_agree += 1

    per_seed_asr = [
        (sum(m[cid] for cid in eligible_ids) / len(eligible_ids))
        if eligible_ids
        else 0.0
        for m in seeds_flips
    ]
    total_flips = sum(
        sum(m[cid] for cid in eligible_ids) for m in seeds_flips
    )
    total_obs = len(eligible_ids) * k
    pooled_asr = total_flips / total_obs if total_obs else 0.0

    # -- variance decomposition --
    # Sampling: Wilson 95% CI on the pooled ASR (what if more cases).
    lo, hi = wilson_ci(total_flips, total_obs) if total_obs else (0.0, 0.0)
    # Run: sample sd of per-seed ASRs (what if more seeds).
    if k >= 2 and per_seed_asr:
        mean_asr = sum(per_seed_asr) / k
        run_sd = math.sqrt(
            sum((a - mean_asr) ** 2 for a in per_seed_asr) / (k - 1)
        )
    else:
        run_sd = 0.0
    # Item: variance of per-case flip rates (do flips concentrate or
    # churn). Population variance: the cases ARE the population here.
    rates = [per_case_flip_rate[cid] for cid in eligible_ids]
    if rates:
        mean_rate = sum(rates) / len(rates)
        item_variance = sum((r - mean_rate) ** 2 for r in rates) / len(
            rates
        )
    else:
        item_variance = 0.0
    n_churn = sum(1 for r in rates if 0.0 < r < 1.0)

    return StabilityResult(
        seeds=[],  # filled by the caller (run_multiseed / CLI)
        k=k,
        n_cases=len(eligible_ids),
        n_cases_total=n_total,
        per_seed_asr=per_seed_asr,
        pooled_asr=pooled_asr,
        pass_k=(n_agree / len(eligible_ids)) if eligible_ids else 0.0,
        n_agree=n_agree,
        per_case_flip_rate=per_case_flip_rate,
        wilson_ci=(lo, hi),
        run_sd=run_sd,
        item_variance=item_variance,
        n_churn=n_churn,
    )


@dataclass(frozen=True)
class FamilyDrift:
    """Drift-watch result for one family between two runs."""

    family: str
    n_paired: int
    asr_old: float
    asr_new: float
    #: New ASR minus old ASR, in proportion points (not percent).
    delta: float
    n_newly_flipping: int  # not flipped in old, flipped in new
    n_newly_fixed: int  # flipped in old, not flipped in new
    #: McNemar p-value on paired flip outcomes; None when withheld
    #: (1-9 discordant pairs, too sparse to test honestly). Zero
    #: discordant pairs is 1.0, the null holds trivially.
    mcnemar_p: float | None
    #: p < DRIFT_ALPHA and ASR rose: flag for operator review.
    degraded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "n_paired": self.n_paired,
            "asr_old": self.asr_old,
            "asr_new": self.asr_new,
            "delta": self.delta,
            "n_newly_flipping": self.n_newly_flipping,
            "n_newly_fixed": self.n_newly_fixed,
            "mcnemar_p": self.mcnemar_p,
            "degraded": self.degraded,
        }


@dataclass(frozen=True)
class DriftResult:
    """Drift-watch comparison of two runs of the same adapter id."""

    old_run_id: str
    new_run_id: str
    families: list[FamilyDrift] = field(default_factory=list)
    #: case_ids flipped in new but not old.
    newly_flipping: list[str] = field(default_factory=list)
    #: case_ids flipped in old but not new.
    newly_fixed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_run_id": self.old_run_id,
            "new_run_id": self.new_run_id,
            "families": [f.to_dict() for f in self.families],
            "newly_flipping": list(self.newly_flipping),
            "newly_fixed": list(self.newly_fixed),
        }

    def summary_text(self) -> str:
        lines = [
            f"drift watch: {self.old_run_id} -> {self.new_run_id}",
            f"newly flipping: {len(self.newly_flipping)}, "
            f"newly fixed: {len(self.newly_fixed)}",
        ]
        for fam in self.families:
            p = (
                f"p={fam.mcnemar_p:.3f}"
                if fam.mcnemar_p is not None
                else "p withheld (<10 discordant)"
            )
            flag = " DEGRADED" if fam.degraded else ""
            lines.append(
                f"  {fam.family}: {fam.asr_old:.1%} -> {fam.asr_new:.1%} "
                f"(delta {fam.delta:+.1%}, +{fam.n_newly_flipping}/"
                f"-{fam.n_newly_fixed}, {p}){flag}"
            )
        return "\n".join(lines)


def drift_watch(
    old_results: list[PerCaseResult],
    new_results: list[PerCaseResult],
    old_run_id: str = "",
    new_run_id: str = "",
) -> DriftResult:
    """Compare two runs of the same adapter id for drift.

    Pairs cases by case_id; only cases eligible in BOTH runs enter the
    paired statistics. Per family, the McNemar test runs on the
    discordant flip pairs (newly-flipping vs newly-fixed) with the
    standard peira policy: p is 1.0 with zero discordant pairs,
    withheld with 1-9 (too sparse to test honestly), exact mid-p for
    10-24, asymptotic at >= 25.

    The report leads with newly-flipping vs newly-fixed, not net
    deltas: a family whose ASR is flat can still have heavy churn.
    """
    old_map = {r.case_id: r for r in old_results}
    new_map = {r.case_id: r for r in new_results}
    # A case whose family changed between runs is unpaired: it cannot
    # enter either family's McNemar table (documented in
    # docs/Methodology.md).
    paired_ids = [
        cid
        for cid, r in old_map.items()
        if cid in new_map
        and r.eligible
        and new_map[cid].eligible
        and new_map[cid].family == r.family
    ]
    by_family: dict[str, list[str]] = {}
    for cid in paired_ids:
        fam = old_map[cid].family
        by_family.setdefault(fam, []).append(cid)

    families: list[FamilyDrift] = []
    newly_flipping: list[str] = []
    newly_fixed: list[str] = []
    for fam in sorted(by_family):
        cids = by_family[fam]
        n = len(cids)
        b = 0  # newly flipping: 0 -> 1
        c = 0  # newly fixed: 1 -> 0
        old_flips = 0
        new_flips = 0
        for cid in cids:
            fo = old_map[cid].flipped
            fn = new_map[cid].flipped
            old_flips += fo
            new_flips += fn
            if fn and not fo:
                b += 1
                newly_flipping.append(cid)
            elif fo and not fn:
                c += 1
                newly_fixed.append(cid)
        asr_old = old_flips / n if n else 0.0
        asr_new = new_flips / n if n else 0.0
        p = mcnemar_p_value(b, c)
        degraded = (
            p is not None and p < DRIFT_ALPHA and (asr_new - asr_old) > 0
        )
        families.append(
            FamilyDrift(
                family=fam,
                n_paired=n,
                asr_old=asr_old,
                asr_new=asr_new,
                delta=asr_new - asr_old,
                n_newly_flipping=b,
                n_newly_fixed=c,
                mcnemar_p=p,
                degraded=degraded,
            )
        )
    return DriftResult(
        old_run_id=old_run_id,
        new_run_id=new_run_id,
        families=families,
        newly_flipping=sorted(newly_flipping),
        newly_fixed=sorted(newly_fixed),
    )


@dataclass
class StabilityArtifact:
    """The sealed output of a k-seed stability run.

    References the k per-seed run artifacts (which carry the full
    provenance: adapter version, dataset manifest, env fingerprint)
    and seals the stability analysis over them. ``created_utc`` and
    the adapter/suite/dataset identity mirror the run artifacts so
    the registry can index stability runs alongside single runs.

    The ``analysis_lock`` binds the derived headline (pass^k,
    variance components) to the inputs: hand-editing the sealed
    numbers is detectable via ``verify()``.
    """

    artifact_version: str = "1.0"
    adapter_name: str = ""
    adapter_version: str = ""
    suite: str = ""
    dataset_version: str = ""
    manifest_sha256: str = ""
    seeds: list[int] = field(default_factory=list)
    # Seed -> artifact path. A dict, not a positional list: excluded
    # seeds leave gaps, and positional correspondence would silently
    # misalign (a seed that crashed has no path; a truncated seed's
    # path is present but the seed is not in `seeds`).
    run_artifact_paths: dict[int, str] = field(default_factory=dict)
    stability: StabilityResult | None = None
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    analysis_lock: str = ""

    def compute_lock(self) -> str:
        """Hash the sealed analysis content."""
        import hashlib

        payload = json.dumps(
            {
                # Identity fields are part of the lock: relabeling the
                # artifact to a different adapter, suite, or dataset
                # after sealing must be detectable by verify().
                "artifact_version": self.artifact_version,
                "adapter_name": self.adapter_name,
                "adapter_version": self.adapter_version,
                "suite": self.suite,
                "dataset_version": self.dataset_version,
                "manifest_sha256": self.manifest_sha256,
                "seeds": list(self.seeds),
                "run_artifact_paths": {
                    str(k): v
                    for k, v in self.run_artifact_paths.items()
                },
                "stability": (
                    self.stability.to_dict()
                    if self.stability is not None
                    else None
                ),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def seal(self) -> "StabilityArtifact":
        self.analysis_lock = self.compute_lock()
        return self

    def verify(self) -> bool:
        return self.analysis_lock == self.compute_lock()

    def to_json(self) -> str:
        return json.dumps(
            {
                "artifact_version": self.artifact_version,
                "artifact_kind": "stability",
                "adapter_name": self.adapter_name,
                "adapter_version": self.adapter_version,
                "suite": self.suite,
                "dataset_version": self.dataset_version,
                "manifest_sha256": self.manifest_sha256,
                "seeds": list(self.seeds),
                "run_artifact_paths": {
                    str(k): v for k, v in self.run_artifact_paths.items()
                },
                "stability": (
                    self.stability.to_dict()
                    if self.stability is not None
                    else None
                ),
                "created_utc": self.created_utc,
                "analysis_lock": self.analysis_lock,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, s: str) -> "StabilityArtifact":
        d = json.loads(s)
        if d.get("artifact_kind") != "stability":
            raise ValueError(
                "not a stability artifact "
                f"(artifact_kind={d.get('artifact_kind')!r})"
            )
        stability = d.get("stability")
        return cls(
            artifact_version=str(d.get("artifact_version", "1.0")),
            adapter_name=str(d.get("adapter_name", "")),
            adapter_version=str(d.get("adapter_version", "")),
            suite=str(d.get("suite", "")),
            dataset_version=str(d.get("dataset_version", "")),
            manifest_sha256=str(d.get("manifest_sha256", "")),
            seeds=[int(x) for x in d.get("seeds", [])],
            run_artifact_paths={
                int(k): str(v)
                for k, v in d.get("run_artifact_paths", {}).items()
            },
            stability=(
                StabilityResult.from_dict(stability)
                if stability is not None
                else None
            ),
            created_utc=str(d.get("created_utc", "")),
            analysis_lock=str(d.get("analysis_lock", "")),
        )
