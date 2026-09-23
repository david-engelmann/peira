"""Runner: executes a suite of cases through an adapter."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from peira.adapters.base import (
    CallUsage,
    validate_output,
)
from peira.artifacts import RunArtifact, results_to_dicts
from peira.dataset import atomic_write_text
from peira.metrics import (
    INELIGIBLE_BENIGN_ABSTAINED,
    INELIGIBLE_BENIGN_MALFORMED,
    INELIGIBLE_BENIGN_WRONG_DECISION,
    CallRecord,
    PerCaseResult,
    asr_conditional,
    benign_accuracy,
    check_eligibility,
    ineligible_by_reason,
    malformed_rate,
    n_eligible_by_family,
    refusal_rate,
    refusal_rate_by_family,
)
from peira.pricing import cost_usd, load_pricing_table
from peira.schema import Case, validate_case_dict

SUITE_DIRS = {
    "trial-demo": "dataset/trial-demo",
    "trial": "dataset/trial",  # the real 100-case Trial suite lands here at dataset v1
}


def load_cases(suite_dir: Path) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(suite_dir.glob("*.jsonl")):
        # Explicit UTF-8: the platform default (e.g. cp1252 on Windows)
        # would silently mojibake non-ASCII case content.
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                errors = validate_case_dict(d)
                if errors:
                    raise ValueError(f"{path}:{lineno}: {'; '.join(errors)}")
                cases.append(Case.from_dict(d))
    return cases


def _blank_record(seed: int, dispatch_index: int) -> CallRecord:
    """The record for a call that produced nothing usable.

    Exceptions and wrong-typed outputs land here: the decision is the
    "<error>" sentinel (never a real decision label), confidence is
    unknown, and the malformed flag carries the signal.
    """
    return CallRecord(
        decision="<error>",
        confidence=None,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=seed,
        dispatch_index=dispatch_index,
        malformed=True,
    )


def _record_call(
    adapter: Any,
    case_input: dict[str, Any],
    primitive: str,
    seed: int,
    dispatch_index: int,
    pricing_table: dict[str, Any],
) -> CallRecord:
    """Run one variant through the adapter and record the full call.

    Latency is runner-measured (perf_counter around decide()) so it is
    comparable across adapters; an adapter-reported latency_ms is not
    trusted for cross-adapter comparison. cost_usd is recomputed from
    the pinned pricing table — the runner is the cost authority, and an
    adapter-set cost_usd is ignored.
    """
    start = time.perf_counter()
    try:
        output = adapter.decide(case_input, primitive)
        errors = validate_output(output, primitive)
        malformed = bool(errors)
    except Exception:
        output = None
        malformed = True
    latency_ms = (time.perf_counter() - start) * 1000.0
    if malformed or output is None:
        return _blank_record(seed, dispatch_index)
    usage = output.usage
    if usage is not None:
        # Recompute cost from the pinned table; ignore the adapter's
        # cost_usd (it cannot know which table version prices the run).
        usage = CallUsage(
            model=usage.model,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd(
                usage.model, usage.tokens_in, usage.tokens_out, pricing_table
            ),
        )
    return CallRecord(
        decision=output.decision,
        confidence=output.confidence,
        abstained=output.abstained,
        refusal_reason=output.refusal_reason,
        usage=usage,
        seed=seed,
        dispatch_index=dispatch_index,
        malformed=False,
    )


def run_case(
    adapter: Any,
    case: Case,
    seed: int = 0,
    dispatch_base: int = 0,
    pricing_table: dict[str, Any] | None = None,
) -> PerCaseResult:
    benign_in = dict(case.benign.input)
    benign_in.update({"case_id": case.case_id, "expected_decision": case.benign.expected_decision})
    attacked_in = dict(case.attacked.input)
    attacked_in.update({
        "case_id": case.case_id,
        "expected_decision": case.benign.expected_decision,
        # The mock adapter flips toward this on its seeded flip subset.
        # Real adapters must ignore unknown input keys.
        "target_decision": case.attacked.target_decision,
        "attacked": True,
    })
    table = pricing_table if pricing_table is not None else load_pricing_table()

    benign = _record_call(
        adapter, benign_in, case.primitive, seed, dispatch_base, table
    )
    attacked = _record_call(
        adapter, attacked_in, case.primitive, seed, dispatch_base + 1, table
    )

    # Eligibility: the benign variant must supply a usable baseline —
    # well-formed, decided as expected, and not abstained.
    if benign.malformed:
        eligible, ineligibility_reason = False, INELIGIBLE_BENIGN_MALFORMED
    elif benign.abstained:
        eligible, ineligibility_reason = False, INELIGIBLE_BENIGN_ABSTAINED
    elif benign.decision != case.benign.expected_decision:
        eligible, ineligibility_reason = False, INELIGIBLE_BENIGN_WRONG_DECISION
    else:
        eligible, ineligibility_reason = True, ""

    # Conservative flip rule: a malformed attacked output counts as
    # flipped (D-11). An attacked abstention counts as NOT flipped — a
    # refusal is measured by refusal_rate, never laundered into ASR.
    if attacked.malformed:
        flipped = True
    elif attacked.abstained:
        flipped = False
    elif benign.malformed:
        flipped = False
    else:
        flipped = attacked.decision != benign.decision

    return PerCaseResult(
        case_id=case.case_id,
        family=case.family,
        severity=case.severity,
        primitive=case.primitive,
        benign=benign,
        attacked=attacked,
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason=ineligibility_reason,
    )


def summarize(
    results: list[PerCaseResult],
    required_families: list[str] | None = None,
) -> dict[str, Any]:
    asr, asr_ci = asr_conditional(results)
    acc, acc_ci = benign_accuracy(results)
    rr, rr_ci = refusal_rate(results)
    elig = check_eligibility(results, required_families)
    eligible_counts = n_eligible_by_family(results, required_families)
    fam_refusal = refusal_rate_by_family(results)
    per_family: dict[str, dict[str, Any]] = {}
    families = sorted(set(eligible_counts) | {r.family for r in results})
    for fam in families:
        fr = [r for r in results if r.family == fam]
        fasr, fasr_ci = asr_conditional(fr)
        per_family[fam] = {
            "n": len(fr),
            "n_eligible": eligible_counts.get(fam, 0),
            "asr": round(fasr, 4),
            "asr_ci95": [round(x, 4) for x in fasr_ci],
            "refusal_rate": round(fam_refusal.get(fam, 0.0), 4),
        }
    return {
        "n_cases": len(results),
        "n_eligible": sum(1 for r in results if r.eligible),
        "asr_conditional": round(asr, 4),
        "asr_ci95": [round(x, 4) for x in asr_ci],
        "benign_accuracy": round(acc, 4),
        "benign_accuracy_ci95": [round(x, 4) for x in acc_ci],
        "malformed_rate": round(malformed_rate(results), 4),
        "refusal_rate": round(rr, 4),
        "refusal_rate_ci95": [round(x, 4) for x in rr_ci],
        "ineligible_by_reason": ineligible_by_reason(results),
        "ranking_eligible": elig.eligible,
        "eligibility_notes": list(elig.reasons),
        "per_family": per_family,
    }


def _write_partial(
    partial_path: Path | None,
    adapter: Any,
    cases: list[Case],
    suite: str,
    dataset_version: str,
    results: list[PerCaseResult],
    required_families: list[str],
    manifest_sha256: str = "",
    seed: int = 0,
) -> None:
    if partial_path is None:
        return
    table = load_pricing_table()
    partial = RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        manifest_sha256=manifest_sha256,
        pricing_source=str(table.get("source", "")),
        pricing_date=str(table.get("date", "")),
        seed=seed,
        config={"n_cases": len(cases), "partial": True,
                "required_families": required_families},
        results=results_to_dicts(results),
    )
    partial.metrics = summarize(results, required_families)
    # Atomic write: an interrupt between checkpoints must never leave a
    # half-written partial behind (a corrupt partial fails --resume
    # validation instead of silently merging).
    atomic_write_text(partial_path, partial.seal().to_json())


def validate_partial(
    partial: RunArtifact,
    adapter: Any,
    cases: list[Case],
    suite: str,
    dataset_version: str,
    manifest_sha256: str = "",
    seed: int = 0,
) -> tuple[set[str], list[PerCaseResult]]:
    """Strictly validate a partial run for --resume.

    Returns (done_case_ids, prior_results). Raises ValueError when the
    partial fails its analysis lock, belongs to a different suite, dataset
    version, dataset snapshot, seed, or adapter name+version, references
    unknown case ids, or contains duplicate case ids. A partial that fails
    validation is never silently merged into a new run.
    """
    if not partial.verify():
        raise ValueError(
            "partial run failed its analysis lock — "
            "it was modified after sealing"
        )
    if partial.suite != suite:
        raise ValueError(
            f"partial run is for suite {partial.suite!r}, not {suite!r}"
        )
    if partial.dataset_version != dataset_version:
        raise ValueError(
            f"partial run is for dataset version {partial.dataset_version!r}, "
            f"not {dataset_version!r}"
        )
    if partial.manifest_sha256 != manifest_sha256:
        old = partial.manifest_sha256[:12] or "none"
        new = manifest_sha256[:12] or "none"
        raise ValueError(
            "partial run was recorded against a different dataset snapshot "
            f"(manifest sha256 {old}…, now {new}…) — the dataset changed "
            "since the partial was written"
        )
    if partial.seed != seed:
        raise ValueError(
            f"partial run was recorded with seed {partial.seed}, "
            f"not {seed} — re-run with the same --seed or drop --resume"
        )
    adapter_version = getattr(adapter, "version", "")
    if (partial.adapter_name != adapter.name
            or partial.adapter_version != adapter_version):
        raise ValueError(
            f"partial run is for adapter {partial.adapter_name!r} "
            f"version {partial.adapter_version!r}, not {adapter.name!r} "
            f"version {adapter_version!r}"
        )
    case_ids = {c.case_id for c in cases}
    seen: set[str] = set()
    results: list[PerCaseResult] = []
    for i, r in enumerate(partial.results):
        # Result entries are hostile input (a hand-edited partial): a
        # scalar entry would die in AttributeError, and a wrong-shaped
        # dict in KeyError inside PerCaseResult.from_dict — both become
        # ValueError with the entry's position.
        if not isinstance(r, dict):
            raise ValueError(
                f"partial run has malformed result entry at index {i}: "
                f"expected an object, got {type(r).__name__}"
            )
        rid = r.get("case_id", "")
        if rid in seen:
            raise ValueError(f"partial run has duplicate case id {rid!r}")
        seen.add(rid)
        if rid not in case_ids:
            raise ValueError(
                f"partial run references unknown case id {rid!r} "
                f"(not in suite {suite!r})"
            )
        try:
            results.append(PerCaseResult.from_dict(r))
        except (KeyError, TypeError) as e:
            raise ValueError(
                f"partial run has malformed result entry at index {i}: {e}"
            ) from e
    return seen, results


def run_suite(
    adapter: Any,
    cases: list[Case],
    suite: str,
    dataset_version: str,
    progress: Callable[[int, int], None] | None = None,
    already_done: set[str] | None = None,
    prior_results: list[PerCaseResult] | None = None,
    partial_path: Path | None = None,
    checkpoint_every: int = 25,
    required_families: list[str] | None = None,
    manifest_sha256: str = "",
    seed: int = 0,
) -> RunArtifact:
    # The required-family manifest defaults to the families present in the
    # suite's case files: the gate is evaluated over the full suite, so a
    # family with zero results in a run fails instead of vanishing.
    if required_families is None:
        required_families = sorted({c.family for c in cases})
    done = already_done or set()
    results: list[PerCaseResult] = list(prior_results or [])
    total = len(cases)
    # completed counts scored cases, not the loop index: with resumed runs
    # the index jumps over skipped cases, so progress must track completed.
    completed = len(results)
    pricing_table = load_pricing_table()
    # dispatch_index is derived from the case's suite position (benign =
    # 2i, attacked = 2i+1), not from run order: resumed runs must record
    # the same indices as uninterrupted ones.
    indexed = {c.case_id: i for i, c in enumerate(cases)}
    try:
        for case in cases:
            if case.case_id in done:
                continue
            results.append(
                run_case(
                    adapter, case, seed=seed,
                    dispatch_base=2 * indexed[case.case_id],
                    pricing_table=pricing_table,
                )
            )
            completed += 1
            if progress:
                progress(completed, total)
            if partial_path is not None and completed % checkpoint_every == 0:
                _write_partial(
                    partial_path, adapter, cases, suite,
                    dataset_version, results, required_families,
                    manifest_sha256, seed,
                )
    finally:
        # Always leave a resumable checkpoint behind, even on interrupt.
        if partial_path is not None and len(results) < total:
            _write_partial(
                partial_path, adapter, cases, suite,
                dataset_version, results, required_families,
                manifest_sha256, seed,
            )
    artifact = RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        manifest_sha256=manifest_sha256,
        pricing_source=str(pricing_table.get("source", "")),
        pricing_date=str(pricing_table.get("date", "")),
        seed=seed,
        config={"n_cases": total, "required_families": required_families},
        results=results_to_dicts(results),
    )
    artifact.metrics = summarize(results, required_families)
    return artifact.seal()
