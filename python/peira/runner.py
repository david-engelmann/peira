"""Runner: executes a suite of cases through an adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from peira.adapters.base import (
    AdapterOutput,
    ChoiceOutput,
    NoulOutput,
    ScoreOutput,
    validate_output,
)
from peira.artifacts import RunArtifact, results_to_dicts
from peira.metrics import (
    PerCaseResult,
    asr_conditional,
    benign_accuracy,
    check_eligibility,
    malformed_rate,
    n_eligible_by_family,
    targeted_attack_success,
)
from peira.schema import Case, validate_case_dict

SUITE_DIRS = {
    "trial-demo": "dataset/trial-demo",
    "trial": "dataset/trial",  # the real 100-case Trial suite lands here at dataset v1
}


def load_cases(suite_dir: Path) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(suite_dir.glob("*.jsonl")):
        with open(path) as f:
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


def _decision_of(output: AdapterOutput) -> str:
    if isinstance(output, (ChoiceOutput, ScoreOutput, NoulOutput)):
        return output.decision
    raise TypeError(f"unknown output type: {type(output).__name__}")


def _confidence_of(output: AdapterOutput) -> float | None:
    if isinstance(output, ChoiceOutput):
        return output.confidence
    if isinstance(output, ScoreOutput):
        return output.score
    return None


def run_case(adapter: Any, case: Case) -> PerCaseResult:
    benign_in = dict(case.benign.input)
    benign_in.update({"case_id": case.case_id, "expected_decision": case.benign.expected_decision})
    attacked_in = dict(case.attacked.input)
    attacked_in.update({"case_id": case.case_id, "expected_decision": case.benign.expected_decision, "attacked": True})

    benign_malformed = False
    attacked_malformed = False
    try:
        benign_out = adapter.decide(benign_in, case.primitive)
        benign_malformed = bool(validate_output(benign_out, case.primitive))
        benign_decision = _decision_of(benign_out)
    except Exception:
        benign_malformed = True
        benign_decision = "<error>"

    try:
        attacked_out = adapter.decide(attacked_in, case.primitive)
        attacked_malformed = bool(validate_output(attacked_out, case.primitive))
        attacked_decision = _decision_of(attacked_out)
    except Exception:
        attacked_malformed = True
        attacked_decision = "<error>"

    malformed = benign_malformed or attacked_malformed
    benign_correct = benign_decision == case.benign.expected_decision
    # Conservative rule: a malformed attacked output counts as flipped.
    # A benign-malformed case has no baseline to attack — it is ineligible
    # for ASR (see metrics._asr_eligible) but still counts toward
    # malformed_rate.
    flipped = attacked_malformed or (
        not benign_malformed and attacked_decision != benign_decision
    )
    target = case.attacked.target_decision
    targeted = target is not None and attacked_decision == target

    return PerCaseResult(
        case_id=case.case_id,
        family=case.family,
        primitive=case.primitive,
        benign_correct=benign_correct,
        attacked_flipped=flipped,
        attacked_targeted=targeted,
        malformed=malformed,
        confidence=_confidence_of(benign_out) if not benign_malformed else None,
        benign_malformed=benign_malformed,
        has_target=target is not None,
    )


def summarize(
    results: list[PerCaseResult],
    required_families: list[str] | None = None,
) -> dict[str, Any]:
    asr, asr_ci = asr_conditional(results)
    acc, acc_ci = benign_accuracy(results)
    tsr, n_tsr = targeted_attack_success(results)
    elig = check_eligibility(results, required_families)
    eligible_counts = n_eligible_by_family(results, required_families)
    per_family: dict[str, dict[str, Any]] = {}
    families = sorted(set(eligible_counts) | {r.family for r in results})
    for fam in families:
        fr = [r for r in results if r.family == fam]
        fasr, fasr_ci = asr_conditional(fr)
        ftsr, fn_tsr = targeted_attack_success(fr)
        per_family[fam] = {
            "n": len(fr),
            "n_eligible": eligible_counts.get(fam, 0),
            "asr": round(fasr, 4),
            "asr_ci95": [round(x, 4) for x in fasr_ci],
            "targeted": round(ftsr, 4) if ftsr is not None else None,
            "n_targeted": fn_tsr,
        }
    return {
        "n_cases": len(results),
        "asr_conditional": round(asr, 4),
        "asr_ci95": [round(x, 4) for x in asr_ci],
        "targeted_attack_success": round(tsr, 4) if tsr is not None else None,
        "n_targeted": n_tsr,
        "benign_accuracy": round(acc, 4),
        "benign_accuracy_ci95": [round(x, 4) for x in acc_ci],
        "malformed_rate": round(malformed_rate(results), 4),
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
) -> None:
    if partial_path is None:
        return
    partial = RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        config={"n_cases": len(cases), "partial": True,
                "required_families": required_families},
        results=results_to_dicts(results),
    )
    partial.metrics = summarize(results, required_families)
    partial_path.write_text(partial.seal().to_json())


def validate_partial(
    partial: RunArtifact,
    adapter: Any,
    cases: list[Case],
    suite: str,
    dataset_version: str,
) -> tuple[set[str], list[PerCaseResult]]:
    """Strictly validate a partial run for --resume.

    Returns (done_case_ids, prior_results). Raises ValueError when the
    partial fails its analysis lock, belongs to a different suite, dataset
    version, or adapter name+version, references unknown case ids, or
    contains duplicate case ids. A partial that fails validation is never
    silently merged into a new run.
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
    for r in partial.results:
        rid = r.get("case_id", "")
        if rid in seen:
            raise ValueError(f"partial run has duplicate case id {rid!r}")
        seen.add(rid)
        if rid not in case_ids:
            raise ValueError(
                f"partial run references unknown case id {rid!r} "
                f"(not in suite {suite!r})"
            )
        results.append(PerCaseResult(**r))
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
    try:
        for case in cases:
            if case.case_id in done:
                continue
            results.append(run_case(adapter, case))
            completed += 1
            if progress:
                progress(completed, total)
            if partial_path is not None and completed % checkpoint_every == 0:
                _write_partial(
                    partial_path, adapter, cases, suite,
                    dataset_version, results, required_families,
                )
    finally:
        # Always leave a resumable checkpoint behind, even on interrupt.
        if partial_path is not None and len(results) < total:
            _write_partial(
                partial_path, adapter, cases, suite,
                dataset_version, results, required_families,
            )
    artifact = RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        config={"n_cases": total, "required_families": required_families},
        results=results_to_dicts(results),
    )
    artifact.metrics = summarize(results, required_families)
    return artifact.seal()
