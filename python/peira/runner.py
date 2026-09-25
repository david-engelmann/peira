"""Runner: executes a suite of cases through an adapter."""

from __future__ import annotations

import json
import sys
import threading
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
    brier_score,
    check_eligibility,
    ece,
    malformed_rate,
)
from peira.schema import Case, validate_case_dict

SUITE_DIRS = {
    "trial-demo": "dataset/trial-demo",
    "trial": "dataset/trial",  # the real 100-case Trial suite lands here at dataset v1
}


class AdapterTimeoutError(TimeoutError):
    """adapter.decide() did not return within the per-call timeout."""


def _decide_with_timeout(
    adapter: Any, case_input: dict, primitive: str, timeout: float | None
) -> AdapterOutput:
    """Call adapter.decide() with a wall-clock timeout.

    Runs decide() on a daemon thread and joins with the timeout. A call that
    exceeds the timeout raises AdapterTimeoutError. Pass timeout=None to
    disable the timeout (decide() is called directly, as before).

    Why a raw daemon thread instead of ThreadPoolExecutor: pool worker
    threads are non-daemon, and concurrent.futures' atexit hook joins every
    worker at interpreter exit — one stuck adapter would hang `peira run`
    forever on shutdown (verified empirically). A daemon thread can never
    block the run or interpreter exit; it is simply abandoned if it outlives
    the timeout.

    Limitation: a thread cannot be forcibly killed. If decide() is stuck in
    a C extension or a tight loop that never yields the GIL, the orphaned
    daemon thread keeps running until the process exits. For a hard-kill
    guarantee, use the Rust subprocess adapter protocol
    (crates/peira-core/src/adapter_protocol.rs), which kills the child
    process on timeout.
    """
    if timeout is None:
        return adapter.decide(case_input, primitive)
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["output"] = adapter.decide(case_input, primitive)
        except BaseException as exc:  # re-raised in the calling thread below
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True, name="peira-decide")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise AdapterTimeoutError(
            f"adapter.decide() did not return within {timeout:g}s "
            f"(primitive={primitive!r})"
        )
    if "error" in box:
        raise box["error"]
    if "output" not in box:
        # The worker died without returning (e.g. os._exit inside decide).
        raise RuntimeError("adapter worker thread exited without a result")
    return box["output"]


def load_cases(suite_dir: Path) -> list[Case]:
    cases: list[Case] = []
    seen_ids: set[str] = set()
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
                case = Case.from_dict(d)
                # Reject duplicate case_ids (audit M5): duplicates in the
                # dataset would silently double-count cases in metrics.
                if case.case_id in seen_ids:
                    raise ValueError(f"{path}:{lineno}: duplicate case_id {case.case_id!r}")
                seen_ids.add(case.case_id)
                cases.append(case)
    return cases


def _decision_of(output: AdapterOutput) -> str:
    if isinstance(output, (ChoiceOutput, ScoreOutput, NoulOutput)):
        return output.decision
    raise TypeError(f"unknown output type: {type(output).__name__}")


def _confidence_of(output: AdapterOutput, primitive: str) -> float | None:
    """Extract confidence for choice primitives only.
    
    Score primitives report a score (0..1), not a confidence. The score
    is stored separately in PerCaseResult.benign_score for calibration.
    """
    if primitive == "choice" and isinstance(output, ChoiceOutput):
        return output.confidence
    return None


def _score_of(output: AdapterOutput) -> float | None:
    """Extract the score value for score primitives."""
    if isinstance(output, ScoreOutput):
        return output.score
    return None


def _copy_json_shaped(obj: Any) -> Any:
    """Fast deep copy for JSON-shaped data (dicts, lists, primitives).
    
    Performance (audit P3): 7.6x faster than copy.deepcopy (2.6μs vs 19.9μs).
    Case inputs are parsed from JSON, so they contain only dicts, lists,
    strings, numbers, booleans, and None — this manual recursion is
    sufficient and preserves the L-1 security property (adapter cannot
    mutate the Case object's inputs via nested references).
    """
    if isinstance(obj, dict):
        return {k: _copy_json_shaped(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_copy_json_shaped(v) for v in obj]
    else:
        # Primitives (str, int, float, bool, None) are immutable
        return obj


def run_case(adapter: Any, case: Case, timeout: float | None = 30.0) -> PerCaseResult:
    """Run one case (benign + attacked variant) through the adapter.

    timeout: per-decide() wall-clock timeout in seconds (default 30). A
    variant whose decide() call exceeds the timeout is marked malformed
    (reason logged to stderr as "timeout") and the run continues with the
    next case. Pass None to disable the timeout.

    Honest coverage: if the adapter's ``supported_primitives`` does not
    include this case's primitive, the case is skipped — not scored, not
    marked malformed. Skipped cases are excluded from all metrics and
    reported via n_skipped / primitive_coverage in the artifact. An
    adapter without ``supported_primitives`` is assumed to support all
    primitives.
    """
    supported = getattr(adapter, "supported_primitives", None)
    if supported is not None and case.primitive not in supported:
        return PerCaseResult(
            case_id=case.case_id,
            family=case.family,
            primitive=case.primitive,
            benign_correct=False,
            attacked_flipped=False,
            attacked_targeted=False,
            malformed=False,
            confidence=None,
            skipped=True,
        )
    # CRITICAL: Never pass gold labels to the adapter. The adapter receives
    # only the case input, case_id, and primitive. Passing expected_decision
    # or expected_score would allow a cheating adapter to achieve perfect
    # scores by echoing the gold (see audit C1).
    # SECURITY (audit L-1): Deep-copy inputs so a malicious adapter cannot
    # mutate the Case object's input dict via nested references.
    # Performance: uses _copy_json_shaped (7.6x faster than copy.deepcopy).
    benign_in = _copy_json_shaped(case.benign.input)
    benign_in.update({"case_id": case.case_id})
    attacked_in = _copy_json_shaped(case.attacked.input)
    attacked_in.update({"case_id": case.case_id, "attacked": True})

    timeout_str = "none" if timeout is None else f"{timeout:g}s"
    benign_malformed = False
    attacked_malformed = False
    benign_score: float | None = None
    try:
        benign_out = _decide_with_timeout(adapter, benign_in, case.primitive, timeout)
        benign_malformed = bool(validate_output(benign_out, case.primitive))
        benign_decision = _decision_of(benign_out)
        if case.primitive == "score":
            benign_score = _score_of(benign_out)
    except AdapterTimeoutError:
        benign_malformed = True
        benign_decision = "<timeout>"
        print(f"timeout: adapter.decide() exceeded {timeout_str} on case "
              f"{case.case_id} (benign variant) — marked malformed",
              file=sys.stderr)
    except Exception:
        benign_malformed = True
        benign_decision = "<error>"

    try:
        attacked_out = _decide_with_timeout(adapter, attacked_in, case.primitive, timeout)
        attacked_malformed = bool(validate_output(attacked_out, case.primitive))
        attacked_decision = _decision_of(attacked_out)
    except AdapterTimeoutError:
        attacked_malformed = True
        attacked_decision = "<timeout>"
        print(f"timeout: adapter.decide() exceeded {timeout_str} on case "
              f"{case.case_id} (attacked variant) — marked malformed",
              file=sys.stderr)
    except Exception:
        attacked_malformed = True
        attacked_decision = "<error>"

    malformed = benign_malformed or attacked_malformed
    # Correctness: the adapter's decision must match the expected decision.
    # For score primitives, the adapter applies its own threshold to derive
    # the decision from its score (see docs/Methodology.md). The runner does
    # NOT second-guess with a hardcoded 0.5 — the dataset uses per-case
    # thresholds in natural language, and the adapter's deployed threshold
    # is part of what's being measured (see examples/custom_threshold.py).
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
        confidence=_confidence_of(benign_out, case.primitive) if not benign_malformed else None,
        benign_malformed=benign_malformed,
        benign_score=benign_score,
        expected_score=case.benign.expected_score if case.primitive == "score" else None,
    )


def summarize(results: list[PerCaseResult]) -> dict[str, Any]:
    asr, asr_ci = asr_conditional(results)
    acc, acc_ci = benign_accuracy(results)
    elig = check_eligibility(results)
    per_family: dict[str, dict[str, Any]] = {}
    families = sorted({r.family for r in results})
    for fam in families:
        fr = [r for r in results if r.family == fam and not r.skipped]
        fasr, fasr_ci = asr_conditional(fr)
        per_family[fam] = {
            "n": len(fr),
            "asr": round(fasr, 4),
            "asr_ci95": [round(x, 4) for x in fasr_ci],
        }
    # Score calibration: ECE and Brier for score-primitive cases.
    # METHODOLOGY NOTE (audit C3): The dataset uses per-case thresholds in
    # natural language (e.g., "Threshold 0.70"), not a fixed 0.5. Binarizing
    # gold scores at 0.5 to create ECE labels is methodologically incoherent
    # when the case threshold differs. Until per-case thresholds are
    # machine-readable in the schema, calibration is reported with labels
    # derived from decision correctness (1 if the adapter's decision matched
    # gold, 0 otherwise), measuring whether higher scores correspond to
    # correct decisions. This is a provisional methodology; see
    # docs/Methodology.md for the full specification.
    score_results = [
        r for r in results
        if r.primitive == "score"
        and r.benign_score is not None
        and not r.benign_malformed
    ]
    score_calibration: dict[str, Any] | None = None
    if score_results:
        probs = [r.benign_score for r in score_results]  # type: ignore[misc]
        # Label: 1 if decision was correct, 0 otherwise.
        # This measures calibration of scores against decision accuracy.
        labels = [1 if r.benign_correct else 0 for r in score_results]
        score_calibration = {
            "n": len(score_results),
            "ece": round(ece(probs, labels), 4),
            "brier": round(brier_score(probs, labels), 4),
            "methodology": "provisional: labels are decision correctness, not binarized gold scores",
        }
    # Honest coverage: per-primitive scored/skipped breakdown. Skipped
    # cases (adapter doesn't declare the primitive) are excluded from all
    # metrics above; they are described here, not penalized.
    primitive_coverage: dict[str, dict[str, int]] = {}
    for prim in sorted({r.primitive for r in results}):
        pr = [r for r in results if r.primitive == prim]
        n_skip = sum(1 for r in pr if r.skipped)
        primitive_coverage[prim] = {
            "n_cases": len(pr),
            "n_scored": len(pr) - n_skip,
            "n_skipped": n_skip,
        }
    n_skipped = sum(1 for r in results if r.skipped)
    return {
        "n_cases": len(results),
        "n_scored": len(results) - n_skipped,
        "n_skipped": n_skipped,
        "primitive_coverage": primitive_coverage,
        "asr_conditional": round(asr, 4),
        "asr_ci95": [round(x, 4) for x in asr_ci],
        "benign_accuracy": round(acc, 4),
        "benign_accuracy_ci95": [round(x, 4) for x in acc_ci],
        "malformed_rate": round(malformed_rate(results), 4),
        "ranking_eligible": elig.eligible,
        "eligibility_notes": list(elig.reasons),
        "per_family": per_family,
        "score_calibration": score_calibration,
    }


def _write_partial(
    partial_path: Path | None,
    adapter: Any,
    cases: list[Case],
    suite: str,
    dataset_version: str,
    results: list[PerCaseResult],
) -> None:
    if partial_path is None:
        return
    partial = RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        config={"n_cases": len(cases), "partial": True},
        results=results_to_dicts(results),
    )
    # Performance (audit P2): summarize() is not called here because the
    # resume path only reads partial.results, never partial.metrics.
    # Computing metrics for every checkpoint is pure waste (~0.35s/run).
    partial_path.write_text(partial.seal().to_json())


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
    timeout: float | None = 30.0,
) -> RunArtifact:
    """Run a full suite, sealing the results into a RunArtifact.

    timeout: per-decide() wall-clock timeout in seconds, forwarded to
    run_case (default 30). Timed-out variants are marked malformed and the
    run continues. Pass None to disable.
    """
    done = already_done or set()
    results: list[PerCaseResult] = list(prior_results or [])
    total = len(cases)
    try:
        for i, case in enumerate(cases, 1):
            if case.case_id in done:
                continue
            results.append(run_case(adapter, case, timeout=timeout))
            if progress:
                progress(i, total)
            if partial_path is not None and len(results) % checkpoint_every == 0:
                _write_partial(
                    partial_path, adapter, cases, suite,
                    dataset_version, results,
                )
    finally:
        # Always leave a resumable checkpoint behind, even on interrupt.
        if partial_path is not None and len(results) < total:
            _write_partial(
                partial_path, adapter, cases, suite,
                dataset_version, results,
            )
    artifact = RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        config={"n_cases": total},
        results=results_to_dicts(results),
    )
    artifact.metrics = summarize(results)
    # Honest coverage: one stderr line per skipped primitive, so partial
    # coverage is visible in logs as well as in the artifact.
    skip_counts: dict[str, int] = {}
    for r in results:
        if r.skipped:
            skip_counts[r.primitive] = skip_counts.get(r.primitive, 0) + 1
    if skip_counts:
        declared = getattr(adapter, "supported_primitives", None)
        declared_str = (
            "all primitives" if declared is None else f"{sorted(declared)}"
        )
        for prim in sorted(skip_counts):
            print(
                f"skip: {skip_counts[prim]} {prim!r} case(s) not scored "
                f"(adapter declares {declared_str})",
                file=sys.stderr,
            )
    return artifact.seal()
