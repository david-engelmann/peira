"""Automated dataset validation gates (stdlib only).

Gates are the authoring-time contract: they run over every ``*.jsonl``
case file in a dataset directory and report per-gate findings. Findings
are either errors (fail the suite — fix before building a manifest) or
warnings (reported; the suite still passes and a human reviews them in
the review queue).

The gates never judge case quality or difficulty — only structural
integrity a machine can check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from peira.dataset import iter_case_lines
from peira.schema import CANONICAL_FAMILIES, validate_case_dict


@dataclass
class GateResult:
    gate_id: str
    name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _canon_input(variant: dict[str, Any]) -> str:
    return json.dumps(variant.get("input", {}), sort_keys=True)


def gate_schema(checked) -> GateResult:
    """G1: every case parses and satisfies the frozen schema.

    `checked` is (path, lineno, case_or_None, error_or_None) with the
    error pre-computed by the caller (see `run_gates`): validation runs
    once per case, and G1 only reports. `path` may be None in unit
    tests.
    """
    r = GateResult("G1", "schema")
    for path, lineno, _case, error in checked:
        if error:
            where = f"{path.name}:{lineno}" if path is not None else f"case:{lineno}"
            r.errors.append(f"{where}: {error}")
    return r


def gate_paired_variants(valid_cases) -> GateResult:
    """G2: benign and attacked variants are non-empty and actually differ.

    An attacked variant identical to its benign control is a broken case:
    there is no attack to measure.
    """
    r = GateResult("G2", "paired-variants")
    for path, lineno, case in valid_cases:
        benign_in = case["benign"].get("input")
        attacked_in = case["attacked"].get("input")
        if not isinstance(benign_in, dict) or not benign_in:
            r.errors.append(f"{path.name}:{lineno}: benign input is empty")
        if not isinstance(attacked_in, dict) or not attacked_in:
            r.errors.append(f"{path.name}:{lineno}: attacked input is empty")
        elif _canon_input(case["benign"]) == _canon_input(case["attacked"]):
            r.errors.append(f"{path.name}:{lineno}: attacked input is "
                            f"identical to benign input (no attack)")
    return r


def gate_dedup(valid_cases) -> GateResult:
    """G3: case ids are unique; no two cases share a content pair."""
    r = GateResult("G3", "dedup")
    seen_ids: dict[str, str] = {}
    seen_pairs: dict[str, str] = {}
    for path, lineno, case in valid_cases:
        loc = f"{path.name}:{lineno}"
        cid = case["case_id"]
        if cid in seen_ids:
            r.errors.append(f"{loc}: duplicate case_id {cid!r} "
                            f"(first seen at {seen_ids[cid]})")
        else:
            seen_ids[cid] = loc
        pair = (_canon_input(case["benign"]), _canon_input(case["attacked"]))
        key = "\x00".join(pair)
        if key in seen_pairs:
            r.errors.append(f"{loc}: duplicate content pair "
                            f"(first seen at {seen_pairs[key]})")
        else:
            seen_pairs[key] = loc
    return r


def gate_families(valid_cases) -> GateResult:
    """G4: every case uses a canonical attack-family id."""
    r = GateResult("G4", "families")
    for path, lineno, case in valid_cases:
        if case["family"] not in CANONICAL_FAMILIES:
            r.errors.append(f"{path.name}:{lineno}: unknown family "
                            f"{case['family']!r} (see docs/Taxonomy.md)")
    return r


def gate_target_coherence(valid_cases) -> GateResult:
    """G5: a named target decision must differ from the benign expectation.

    A targeted attack aiming at the decision the benign input already
    produces is incoherent — there is nothing to steer toward.
    """
    r = GateResult("G5", "target-coherence")
    for path, lineno, case in valid_cases:
        target = case["attacked"].get("target_decision")
        expected = case["benign"].get("expected_decision")
        if target is not None and target == expected:
            r.errors.append(f"{path.name}:{lineno}: target_decision "
                            f"{target!r} equals the benign expected decision")
    return r


_PII_PATTERNS = [
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone number", re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]


def gate_pii_scan(valid_cases) -> GateResult:
    """G6: flag identifier-like strings in case inputs.

    Warnings, not errors: attack payloads sometimes contain synthetic
    identifiers by design (a phishing case *about* a suspicious email).
    Every warning goes to the human review queue.
    """
    r = GateResult("G6", "pii-scan")
    for path, lineno, case in valid_cases:
        for variant in ("benign", "attacked"):
            text = json.dumps(case[variant].get("input", {}), sort_keys=True)
            for label, pattern in _PII_PATTERNS:
                if pattern.search(text):
                    r.warnings.append(f"{path.name}:{lineno}: possible "
                                      f"{label} in {variant} input")
                    break
    return r


def gate_score_reference(valid_cases) -> GateResult:
    """G7: score-primitive cases carry the author's reference score.

    Score diagnostics (A3 S6) measure adapter-vs-author agreement
    against benign.expected_score; a score case without one cannot
    contribute. Errors, not warnings: on release-track datasets a
    missing reference is a broken case, not a judgment call.
    """
    r = GateResult("G7", "score-reference")
    for path, lineno, case in valid_cases:
        if case["primitive"] == "score":
            if case["benign"].get("expected_score") is None:
                r.errors.append(f"{path.name}:{lineno}: score case missing "
                                f"benign expected_score (author reference)")
    return r


def run_gates(dataset_dir: Path) -> list[GateResult]:
    """Run all gates over a dataset directory, in order."""
    # One pass: every line is parsed and validated exactly once. Each
    # entry is (path, lineno, case_or_None, error_or_None) — G1 reports
    # the collected errors, G2–G6 consume the valid subset, so no case
    # is ever validated twice.
    checked: list[tuple[Path, int, Any, str | None]] = []
    for path, lineno, case, json_error in iter_case_lines(dataset_dir):
        if json_error is not None:
            checked.append((path, lineno, None, json_error))
            continue
        errors = validate_case_dict(case)
        checked.append((path, lineno, case,
                        "; ".join(errors) if errors else None))
    results = [gate_schema(checked)]
    valid = [(p, n, c) for p, n, c, e in checked if e is None]
    results.append(gate_paired_variants(valid))
    results.append(gate_dedup(valid))
    results.append(gate_families(valid))
    results.append(gate_target_coherence(valid))
    results.append(gate_pii_scan(valid))
    results.append(gate_score_reference(valid))
    return results
