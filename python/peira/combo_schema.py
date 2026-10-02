"""Combination-attack (combo) evaluation suite: schema and validation.

The combo suite is a SEPARATE suite, not a v1/v2 family: it has its own
schema, gates, metrics, and versioning, while sharing the single-shot
runner's call machinery, validation gates, artifacts, and report tooling
where valid. Combo results are never blended with the paired
single-decision v1/v2 numbers (D-34 separation logic applies).

A combo case is one arm of a 2x2 factorial unit. Every substrate (a fresh
benign decision case) yields four arms:

    control : benign case as authored
    a       : benign + family A's transformation
    b       : benign + family B's transformation
    ab      : benign + both transformations (A applied first, then B,
              alphabetical by family id; recorded in ``transform_order``)

The interaction contrast for a pair (A, B) is then::

    interaction = flip(ab) - flip(a) - flip(b) + flip(control)

computed on the primary outcome registered per combo (flip rate by
default; abstain rate for availability combos; joint flip-and-oversight-
failure rate for masking combos). Classification uses the additive null
with a CI-excludes-zero rule: super-additive / additive / sub-additive /
unresolved (MDE floor not met). See
``research_notes/family-intersections-20260928.md`` (sections 4a, 6a, 6f)
for the full design.

Case IDs are ``combo-<a>-<b>-NNNN-<arm>`` where ``<a>`` and ``<b>`` are
short family codes, ``NNNN`` is the zero-padded substrate index, and
``<arm>`` is one of ``ctrl``, ``a``, ``b``, ``ab``. The ``family`` field
carries the combo pair id ``combo-<a>-<b>`` so the standard runner executes
each arm as an ordinary case; the 2x2 structure is recovered from the
``combo_*`` metadata fields at analysis time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from peira._rust import _impl as _rust

# Short codes for families used in combo pairs. The full family id is
# recoverable via COMBO_PAIRS below; codes keep case ids readable.
COMBO_PAIRS: dict[str, tuple[str, str]] = {
    "combo-dfl-ind": ("distractor_flooding", "indirection"),
    "combo-san-csp": ("score_anchoring", "confidence_spoofing"),
}

COMBO_SUITE_ID = "combo"

COMBO_ARMS = ("ctrl", "a", "b", "ab")

COMBO_PRIMARY_OUTCOMES = ("flip", "abstain", "joint")

# Primary outcome registered per combo pair (design section 6f).
COMBO_PRIMARY_OUTCOME: dict[str, str] = {
    "combo-dfl-ind": "flip",
    "combo-san-csp": "flip",
}

# Hypothesized interaction class per combo pair (design section 5).
# These are the pre-registered predictions the pilot tests.
COMBO_HYPOTHESIS: dict[str, str] = {
    # The burial: flooding degrades the reasoning budget that indirection
    # demands. Predicted super-additive.
    "combo-dfl-ind": "super",
    # Negative control: both attack the score/confidence surface (L4 x L4).
    # Predicted sub-additive (redundancy).
    "combo-san-csp": "sub",
}


def _combo_pair_id_py(family_a: str, family_b: str) -> str:
    """Reference implementation of :func:`combo_pair_id`."""
    a, b = sorted((family_a, family_b))
    for pair_id, (fa, fb) in COMBO_PAIRS.items():
        if (fa, fb) == (a, b):
            return pair_id
    raise KeyError(f"unknown combo pair: {family_a} x {family_b}")


def combo_pair_id(family_a: str, family_b: str) -> str:
    """Return the canonical combo pair id for two family ids.

    Families are ordered alphabetically so (A, B) and (B, A) map to the
    same pair.
    """
    if _rust is not None and isinstance(family_a, str) and isinstance(family_b, str):
        return _rust.combo_pair_id(family_a, family_b)
    return _combo_pair_id_py(family_a, family_b)


def _combo_case_id_py(pair_id: str, substrate_idx: int, arm: str) -> str:
    """Reference implementation of :func:`combo_case_id`."""
    if pair_id not in COMBO_PAIRS:
        raise KeyError(f"unknown combo pair id: {pair_id}")
    if arm not in COMBO_ARMS:
        raise ValueError(f"unknown combo arm: {arm}")
    return f"{pair_id}-{substrate_idx:04d}-{arm}"


def combo_case_id(pair_id: str, substrate_idx: int, arm: str) -> str:
    """Build the canonical case id for one arm of a substrate."""
    if (
        _rust is not None
        and isinstance(pair_id, str)
        and isinstance(arm, str)
        and isinstance(substrate_idx, int)
        and not isinstance(substrate_idx, bool)
    ):
        try:
            return _rust.combo_case_id(pair_id, substrate_idx, arm)
        except (OverflowError, TypeError, ValueError):
            # Integers outside i64 range (the reference formats them
            # fine): fall back to the pure-Python implementation.
            pass
    return _combo_case_id_py(pair_id, substrate_idx, arm)


def _parse_combo_case_id_py(case_id: str) -> tuple[str, int, str]:
    """Reference implementation of :func:`parse_combo_case_id`."""
    parts = case_id.rsplit("-", 2)
    if len(parts) != 3:
        raise ValueError(f"malformed combo case id: {case_id}")
    pair_id, idx_s, arm = parts
    if pair_id not in COMBO_PAIRS:
        raise ValueError(f"unknown combo pair in case id: {case_id}")
    if arm not in COMBO_ARMS:
        raise ValueError(f"unknown combo arm in case id: {case_id}")
    try:
        idx = int(idx_s)
    except ValueError:
        raise ValueError(f"malformed substrate index in case id: {case_id}")
    return pair_id, idx, arm


def parse_combo_case_id(case_id: str) -> tuple[str, int, str]:
    """Split a combo case id into (pair_id, substrate_idx, arm)."""
    if _rust is not None and isinstance(case_id, str):
        try:
            # The Rust index parser mirrors int() for the realistic
            # domain but rejects inputs the reference accepts
            # (underscores between digits, non-ASCII decimal digits);
            # fall back so those parse exactly as the reference does.
            return _rust.combo_parse_case_id(case_id)
        except (TypeError, ValueError):
            pass
    return _parse_combo_case_id_py(case_id)


@dataclass
class ComboCase:
    """One arm of a combo substrate, with the standard single-shot fields
    plus the 2x2 factorial metadata."""

    case_id: str
    family: str  # the combo pair id, e.g. "combo-dfl-ind"
    primitive: str
    severity: str
    benign: dict[str, Any]
    attacked: dict[str, Any]
    combo_arm: str  # "ctrl" | "a" | "b" | "ab"
    combo_substrate: str  # e.g. "combo-dfl-ind-0001"
    combo_pair: str  # human-readable, e.g. "distractor_flooding x indirection"
    transform_order: str  # e.g. "distractor_flooding then indirection"
    primary_outcome: str = "flip"
    notes: str = ""
    provenance: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "case_id": self.case_id,
            "family": self.family,
            "primitive": self.primitive,
            "severity": self.severity,
            "benign": self.benign,
            "attacked": self.attacked,
            "combo_arm": self.combo_arm,
            "combo_substrate": self.combo_substrate,
            "combo_pair": self.combo_pair,
            "transform_order": self.transform_order,
            "primary_outcome": self.primary_outcome,
        }
        if self.notes:
            d["notes"] = self.notes
        if self.provenance:
            d["provenance"] = self.provenance
        return d


def _validate_combo_dict_py(d: dict[str, Any]) -> list[str]:
    """Reference implementation of :func:`validate_combo_dict`."""
    errors: list[str] = []
    for key in ("case_id", "family", "primitive", "severity", "benign",
                "attacked", "combo_arm", "combo_substrate", "combo_pair",
                "transform_order"):
        if key not in d:
            errors.append(f"missing required key: {key}")
    if errors:
        return errors

    try:
        pair_id, idx, arm = parse_combo_case_id(d["case_id"])
    except ValueError as e:
        errors.append(str(e))
        return errors

    if d["family"] != pair_id:
        errors.append(
            f"family {d['family']!r} does not match case-id pair {pair_id!r}")
    if d["combo_arm"] != arm:
        errors.append(
            f"combo_arm {d['combo_arm']!r} does not match case-id arm {arm!r}")
    expected_substrate = f"{pair_id}-{idx:04d}"
    if d["combo_substrate"] != expected_substrate:
        errors.append(
            f"combo_substrate {d['combo_substrate']!r} does not match "
            f"expected {expected_substrate!r}")

    if d["primitive"] not in ("choice", "score", "abstain"):
        errors.append(f"bad primitive: {d['primitive']!r}")
    if d["severity"] not in ("critical", "high", "medium", "low"):
        errors.append(f"bad severity: {d['severity']!r}")
    if d["primary_outcome"] not in COMBO_PRIMARY_OUTCOMES:
        errors.append(f"bad primary_outcome: {d['primary_outcome']!r}")

    # Arm-content rules (design 6b.3): the benign side is always the clean
    # substrate; the control arm's attacked input must equal the benign
    # input (no transformation applied).
    benign_input = (d["benign"] or {}).get("input")
    attacked_input = (d["attacked"] or {}).get("input")
    if arm == "ctrl" and benign_input != attacked_input:
        errors.append("control arm attacked input must equal benign input")
    if arm != "ctrl" and benign_input == attacked_input:
        errors.append(f"arm {arm!r} attacked input identical to benign input")

    for side in ("benign", "attacked"):
        s = d.get(side) or {}
        if not isinstance(s.get("input"), dict):
            errors.append(f"{side} missing input dict")
        if side == "benign" and "expected_decision" not in s:
            errors.append("benign missing expected_decision")
        if side == "attacked" and "target_decision" not in s:
            errors.append("attacked missing target_decision")

    return errors


def validate_combo_dict(d: dict[str, Any]) -> list[str]:
    """Validate one combo case dict. Returns a list of error strings."""
    if _rust is not None and isinstance(d, dict):
        try:
            return _rust.combo_validate_dict(d)
        except (AttributeError, TypeError, ValueError):
            # Structural-contract violation, or a non-JSON-shaped value
            # (or an over-deep/lone-surrogate one) the converter
            # rejects: the reference raises the natural exception or
            # reports the errors itself.
            pass
    return _validate_combo_dict_py(d)


def load_combo_cases(path: str) -> list[dict[str, Any]]:
    """Load combo cases from a JSONL file, validating each record."""
    import json
    cases = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            errs = validate_combo_dict(d)
            if errs:
                raise ValueError(
                    f"{path}:{lineno}: {d.get('case_id', '?')}: "
                    + "; ".join(errs))
            cases.append(d)
    return cases
