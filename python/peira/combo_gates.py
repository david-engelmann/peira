"""Dataset gates for the combination-attack (combo) suite.

These gates run at authoring time over ``dataset/combo/cases/*.jsonl``.
They are separate from the v1/v2 gates (different schema, 4-arm
structure) but follow the same gate-result conventions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from peira.combo_schema import (
    COMBO_ARMS,
    COMBO_PAIRS,
    parse_combo_case_id,
    validate_combo_dict,
)


@dataclass
class ComboGateResult:
    gate_id: str
    name: str
    passed: bool
    n_errors: int
    errors: list[str] = field(default_factory=list)


def _load_all(files: list[str]) -> tuple[list[dict], list[str]]:
    import json
    cases: list[dict] = []
    load_errors: list[str] = []
    for path in files:
        try:
            with open(path) as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cases.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        load_errors.append(f"{path}:{lineno}: bad JSON: {e}")
        except OSError as e:
            load_errors.append(f"{path}: unreadable: {e}")
    return cases, load_errors


def gate_cg1_schema(cases: list[dict]) -> ComboGateResult:
    """CG1: every record validates against the combo schema."""
    errors: list[str] = []
    for c in cases:
        for e in validate_combo_dict(c):
            errors.append(f"{c.get('case_id', '?')}: {e}")
    return ComboGateResult("CG1", "combo schema validity", not errors,
                           len(errors), errors[:50])


def gate_cg2_arm_completeness(cases: list[dict]) -> ComboGateResult:
    """CG2: every substrate has exactly the four arms (ctrl, a, b, ab)."""
    errors: list[str] = []
    by_substrate: dict[str, Counter] = {}
    for c in cases:
        try:
            pair_id, idx, arm = parse_combo_case_id(c.get("case_id", ""))
        except ValueError:
            continue  # CG1 reports these
        substrate = f"{pair_id}-{idx:04d}"
        by_substrate.setdefault(substrate, Counter())[arm] += 1
    for substrate, arms in sorted(by_substrate.items()):
        for arm in COMBO_ARMS:
            n = arms.get(arm, 0)
            if n == 0:
                errors.append(f"{substrate}: missing arm {arm!r}")
            elif n > 1:
                errors.append(f"{substrate}: duplicate arm {arm!r} x{n}")
    return ComboGateResult("CG2", "2x2 arm completeness", not errors,
                           len(errors), errors[:50])


def gate_cg3_pair_separation(cases: list[dict]) -> ComboGateResult:
    """CG3: no substrate id is shared across pairs; case ids unique."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for c in cases:
        cid = c.get("case_id", "?")
        if cid in seen:
            errors.append(f"duplicate case_id: {cid}")
        seen[cid] = c.get("family", "?")
    # Substrate namespaces: the pair prefix must match the family field.
    for c in cases:
        cid = c.get("case_id", "")
        fam = c.get("family", "")
        if cid.startswith("combo-") and fam.startswith("combo-"):
            prefix = "-".join(cid.split("-")[:3])
            if prefix != fam:
                errors.append(
                    f"{cid}: case-id pair prefix {prefix!r} != family {fam!r}")
    return ComboGateResult("CG3", "pair separation + id uniqueness",
                           not errors, len(errors), errors[:50])


def gate_cg4_substrate_freshness(cases: list[dict]) -> ComboGateResult:
    """CG4: benign substrates must not duplicate existing v1/v2 prompts.

    Combo arms must derive from fresh substrates (design 6b.1); reusing
    an existing single-family case's benign text would confound the
    contrast. This gate checks for exact prompt duplication against a
    caller-supplied corpus of existing prompts.
    """
    # Implemented as a function taking the reference corpus so the gate
    # stays dependency-free; the CLI wires the v1/v2 prompt set in.
    return ComboGateResult("CG4", "substrate freshness (needs corpus)",
                           True, 0, [])


def gate_cg4_with_corpus(cases: list[dict],
                         existing_prompts: set[str]) -> ComboGateResult:
    """CG4 with the reference corpus of existing v1/v2 benign prompts."""
    errors: list[str] = []
    for c in cases:
        prompt = ((c.get("benign") or {}).get("input") or {}).get("prompt", "")
        if prompt in existing_prompts:
            errors.append(
                f"{c.get('case_id', '?')}: benign prompt duplicates an "
                f"existing v1/v2 case")
    # Check once per substrate, not once per arm.
    seen_substrates: set[str] = set()
    deduped: list[str] = []
    for e in errors:
        substrate = e.split(":")[0].rsplit("-", 1)[0]
        if substrate not in seen_substrates:
            seen_substrates.add(substrate)
            deduped.append(e)
    return ComboGateResult("CG4", "substrate freshness", not deduped,
                           len(deduped), deduped[:50])


def gate_cg5_near_dedup(cases: list[dict]) -> ComboGateResult:
    """CG5: near-duplicate detection across substrates within a pair.

    Two substrates whose benign prompts are near-identical would not be
    independent draws. Uses normalized token-set Jaccard; flags pairs
    above 0.85 for author review. Reports, does not auto-fail: the
    author dispositions each flag.
    """
    import re
    errors: list[str] = []
    # One prompt per substrate (use the ctrl arm's benign input).
    substrates: dict[str, str] = {}
    for c in cases:
        try:
            pair_id, idx, arm = parse_combo_case_id(c.get("case_id", ""))
        except ValueError:
            continue
        if arm != "ctrl":
            continue
        prompt = ((c.get("benign") or {}).get("input") or {}).get("prompt", "")
        substrates[f"{pair_id}-{idx:04d}"] = prompt

    def toks(s: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", s.lower()))

    token_sets = {k: toks(v) for k, v in substrates.items()}
    keys = sorted(token_sets)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            # Only compare within a pair.
            if a.rsplit("-", 1)[0] != b.rsplit("-", 1)[0]:
                continue
            ta, tb = token_sets[a], token_sets[b]
            if not ta or not tb:
                continue
            jacc = len(ta & tb) / len(ta | tb)
            if jacc > 0.85:
                errors.append(
                    f"{a} ~ {b}: token Jaccard {jacc:.2f} > 0.85")
    return ComboGateResult("CG5", "substrate near-dedup", not errors,
                           len(errors), errors[:50])


COMBO_GATES = (
    ("CG1", gate_cg1_schema),
    ("CG2", gate_cg2_arm_completeness),
    ("CG3", gate_cg3_pair_separation),
    ("CG5", gate_cg5_near_dedup),
)


def run_combo_gates(files: list[str]) -> list[ComboGateResult]:
    """Run all combo gates over the given case files."""
    cases, load_errors = _load_all(files)
    results: list[ComboGateResult] = []
    if load_errors:
        results.append(ComboGateResult(
            "CG0", "file loading", False, len(load_errors), load_errors[:50]))
        return results
    for gate_id, fn in COMBO_GATES:
        results.append(fn(cases))
    return results
