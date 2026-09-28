#!/usr/bin/env python3
"""Shared semantics for the S-1 re-grade tooling suite.

Implements the mechanical rules from the S-1 re-grade protocol
(~/workspace/research_notes/s1-regrade-protocol-20260928.md):

- section 3: defect classes 1-6 and their correction paths, the
  conservative rule, and the conservatism ordering
  (retire+add > annotate > fix)
- section 5.4: mechanical derivation of the severity-dimension defect
  verdict and the summary fields (overall, defect_class,
  correction_path) from a grader's per-dimension verdicts
- section 6.3: raw agreement and Cohen's kappa on severity tiers
- section 8.2: replacement-ID minting (<prefix>-<NNN>, where the prefix
  is the family prefix as it appears in live IDs, e.g. ``v1-csp``) and
  version-bump computation

This module is imported by scripts/s1_sample.py, s1_sheet.py,
s1_diff.py, s1_apply.py and s1_verify.py. It is stdlib-only except
for the peira.schema import (severity tiers); scripts add the repo's
python/ directory to sys.path before importing it, following the
precedent of scripts/gen_readme_table.py.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.schema import SEVERITIES  # noqa: E402

# Canonical tier order, most severe first (matches the rubric and
# peira.schema.SEVERITIES). Used for upgrade/downgrade direction and
# for the two-tier disagreement distance in s1_diff.py.
TIERS = list(SEVERITIES)

DEFECT_CLASSES = (1, 2, 3, 4, 5, 6)

# Conservatism ordering of correction paths (protocol section 3):
# retire+add outranks annotate outranks fix.
PATH_RANK = {"retire+add": 3, "annotate": 2, "fix": 1}

CASE_ID_RE = re.compile(r"^v1-([a-z]+)-(\d{3})$")

# Verdict-schema keys a grader must supply (protocol section 5.4).
# The grader records per-dimension verdicts only; defect_class,
# correction_path and overall are derived mechanically.
REQUIRED_GRADING_KEYS = (
    "case_id",
    "grader_id",
    "severity_tier",
    "severity_bullet",
    "severity_notes",
    "gold_verdict",
    "gold_derivation",
    "factual_issues",
    "attack_integrity",
    "format_issues",
)

# CHANGELOG entry types and required fields per docs/Dataset-Changelog.md.
# Protocol section 8.2 additionally requires dataset_version on each entry.
CHANGELOG_REQUIRED = {
    "seal": ("date", "type", "dataset_version", "description",
             "manifest_sha256", "case_count", "families"),
    "add": ("date", "type", "description", "case_ids",
            "dataset_version", "rationale"),
    "retire": ("date", "type", "description", "case_ids", "rationale",
               "dataset_version", "replacements"),
    "fix": ("date", "type", "description", "case_ids", "rationale",
            "dataset_version", "diff_summary"),
    "annotate": ("date", "type", "description", "case_ids",
                 "dataset_version", "rationale"),
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with timezone."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def validate_grading(grading: dict) -> list[str]:
    """Check a grader verdict object against the section-5.4 schema.

    Returns a list of violation descriptions; empty means valid.
    """
    errors: list[str] = []
    if not isinstance(grading, dict):
        return ["grading is not a JSON object"]
    for key in REQUIRED_GRADING_KEYS:
        if key not in grading:
            errors.append(f"missing required key: {key}")
    tier = grading.get("severity_tier")
    if tier not in TIERS:
        errors.append(
            f"severity_tier {tier!r} not one of {TIERS} "
            f"(case {grading.get('case_id')})"
        )
    for key in ("factual_issues", "format_issues"):
        issues = grading.get(key)
        if issues is not None and not isinstance(issues, list):
            errors.append(f"{key} must be a list (case {grading.get('case_id')})")
        elif isinstance(issues, list):
            for i, entry in enumerate(issues):
                if not isinstance(entry, (str, dict)):
                    errors.append(
                        f"{key}[{i}] must be a string or object, "
                        f"got {entry!r} (case {grading.get('case_id')})"
                    )
                elif isinstance(entry, dict):
                    if "detail" not in entry:
                        errors.append(
                            f"{key}[{i}] dict entry must have a 'detail' key "
                            f"(case {grading.get('case_id')})"
                        )
                    if key == "format_issues":
                        cls = entry.get("class", 5)
                        if cls not in (4, 5):
                            errors.append(
                                f"{key}[{i}].class must be 4 or 5, "
                                f"got {cls!r} (case {grading.get('case_id')})"
                            )
    return errors


def _norm_issue(entry) -> dict:
    """Normalize one factual/format issue entry to a dict.

    Graders may record a bare string (the issue description) or an
    object with explicit flags. Bare strings take the conservative
    defaults (see below).
    """
    if isinstance(entry, str):
        return {"detail": entry}
    if isinstance(entry, dict):
        return dict(entry)
    raise ValueError(f"issue entry must be a string or object, got {entry!r}")


def _format_issue_class(entry: dict) -> int:
    """Map one format issue to defect class 4 or 5.

    The protocol's dimension 5 covers both class 4 (scale mismatches)
    and class 5 (typos/formatting). Graders tag class-4 issues
    explicitly with {"class": 4, ...}; untagged entries default to
    class 5, because class-4 scale defects are Sweep B's mechanical
    enumeration, so a human-flagged format issue without an explicit
    scale tag is most plausibly a typo/formatting defect.
    """
    cls = entry.get("class", 5)
    if cls not in (4, 5):
        raise ValueError(f"format issue class must be 4 or 5, got {cls!r}")
    return cls


def correction_for_class(cls: int, answer_impact: bool = True) -> tuple[str, str]:
    """Return (correction_path, version_bump) for a defect class.

    Classes 3 and 4 branch on answer impact (protocol section 3):
    ``answer_impact=True`` means the correction changes gold values
    (or there is doubt, per the conservative rule), which ships as
    retire+add/minor. Factual issues default to impact=True and
    class-4 format issues default to changes_gold=True, because the
    protocol's conservative rule sends every doubtful case to
    retire+add; the grader opts into fix only by explicitly tagging
    the issue as answer-preserving.
    """
    if cls == 1:
        return ("retire+add", "minor")
    if cls == 2:
        return ("annotate", "patch")
    if cls == 3:
        return ("retire+add", "minor") if answer_impact else ("fix", "patch")
    if cls == 4:
        return ("retire+add", "minor") if answer_impact else ("fix", "patch")
    if cls == 5:
        return ("fix", "patch")
    if cls == 6:
        return ("retire+add", "minor")
    raise ValueError(f"unknown defect class: {cls!r}")


def _tier_direction(grader_tier: str, current_tier: str) -> str:
    """Classify a severity move as upgrade/downgrade/same.

    Upgrade means the grader's blind tier is more severe than the
    current tier (protocol section 9.3 requires reporting the
    confirmed severity-mislabel rate broken out by direction).
    """
    if grader_tier == current_tier:
        return "same"
    return (
        "upgrade"
        if TIERS.index(grader_tier) < TIERS.index(current_tier)
        else "downgrade"
    )


def derive_verdict(grading: dict, current_tier: str) -> dict:
    """Derive the mechanical verdict fields (protocol section 5.4).

    Takes one grader's per-dimension verdicts plus the case's current
    severity tier (from the case file, which the grader never saw)
    and derives:

    - the severity-dimension defect verdict: a class-2 defect with
      path ``annotate`` iff the blind tier differs from the current
      tier;
    - ``overall``: DEFECT iff any dimension is defective;
    - ``defect_class``: the defective dimension's class, or, when
      several dimensions are defective, the class whose correction
      path is most conservative (retire+add > annotate > fix); ties
      on path break toward the lowest class number for
      determinism;
    - ``all_defect_classes``: every defective dimension's class, so
      bar counting (Rules 1b/2b) does not undercount cases defective
      in more than one dimension;
    - ``correction_path``: follows ``defect_class`` per section 3.

    Non-severity dimensions are graded against the current labels, so
    the grader's per-dimension verdicts for those stand as recorded;
    only the severity dimension and the three summary fields are
    derived.
    """
    if current_tier not in TIERS:
        raise ValueError(f"current_tier {current_tier!r} not one of {TIERS}")
    case_id = grading.get("case_id")

    dims: dict[str, dict] = {}

    # Severity (derived): blind tier vs current tier.
    g_tier = grading["severity_tier"]
    sev_defect = g_tier != current_tier
    dims["severity"] = {
        "defect": sev_defect,
        "defect_class": 2 if sev_defect else None,
        "grader_tier": g_tier,
        "current_tier": current_tier,
        "direction": _tier_direction(g_tier, current_tier),
    }

    # Gold labels (as recorded): anything but "ok" is a class-1 defect.
    gold_ok = grading.get("gold_verdict") == "ok"
    dims["gold"] = {"defect": not gold_ok, "defect_class": 1 if not gold_ok else None}

    # Factual accuracy (as recorded): each issue is class 3; the path
    # branches on answer impact, defaulting to True (conservative).
    factual = [_norm_issue(e) for e in (grading.get("factual_issues") or [])]
    fact_defect = bool(factual)
    fact_path = None
    if fact_defect:
        impact = any(e.get("changes_answer", True) for e in factual)
        fact_path = correction_for_class(3, impact)[0]
    dims["factual"] = {
        "defect": fact_defect,
        "defect_class": 3 if fact_defect else None,
        "correction_path": fact_path,
        "n_issues": len(factual),
    }

    # Attack integrity (as recorded): anything but "ok" is class 6.
    attack_ok = grading.get("attack_integrity") == "ok"
    dims["attack_integrity"] = {
        "defect": not attack_ok,
        "defect_class": 6 if not attack_ok else None,
    }

    # Format validity (as recorded): each issue maps to class 4 or 5.
    fmt = [_norm_issue(e) for e in (grading.get("format_issues") or [])]
    fmt_classes = sorted({_format_issue_class(e) for e in fmt})
    fmt_defect = bool(fmt)
    fmt_path = None
    if fmt_defect:
        paths = set()
        for e in fmt:
            c = _format_issue_class(e)
            if c == 4:
                paths.add(correction_for_class(4, e.get("changes_gold", True))[0])
            else:
                paths.add(correction_for_class(5)[0])
        fmt_path = max(paths, key=lambda p: PATH_RANK[p])
    dims["format"] = {
        "defect": fmt_defect,
        "defect_classes": fmt_classes,
        "correction_path": fmt_path,
        "n_issues": len(fmt),
    }

    # Summary fields.
    defective = [name for name, d in dims.items() if d["defect"]]
    overall = "DEFECT" if defective else "KEEP"

    # Every defective dimension's class (for Rules 1b/2b bar counting).
    all_classes: list[int] = []
    if dims["severity"]["defect"]:
        all_classes.append(2)
    if dims["gold"]["defect"]:
        all_classes.append(1)
    if dims["factual"]["defect"]:
        all_classes.append(3)
    if dims["attack_integrity"]["defect"]:
        all_classes.append(6)
    all_classes.extend(dims["format"]["defect_classes"])
    all_classes = sorted(set(all_classes))

    defect_class = None
    correction_path = None
    if all_classes:
        # Most conservative correction path wins; ties on path break
        # toward the lowest class number (deterministic).
        def _key(cls: int) -> tuple[int, int]:
            path, _bump = _path_for_class_in_verdict(cls, dims)
            return (PATH_RANK[path], -cls)

        defect_class = max(all_classes, key=_key)
        correction_path, _bump = _path_for_class_in_verdict(defect_class, dims)

    return {
        "case_id": case_id,
        "dimensions": dims,
        "overall": overall,
        "defect_class": defect_class,
        "all_defect_classes": all_classes,
        "correction_path": correction_path,
    }


def _path_for_class_in_verdict(cls: int, dims: dict) -> tuple[str, str]:
    """Resolve the (path, bump) for a class given derived dimensions.

    Classes 3 and 4 carry their answer-impact resolution in the
    dimension record; the rest follow the static section-3 mapping.
    """
    if cls == 3:
        path = dims["factual"]["correction_path"]
        return (path, "minor" if path == "retire+add" else "patch")
    if cls == 4:
        path = dims["format"]["correction_path"]
        return (path, "minor" if path == "retire+add" else "patch")
    return correction_for_class(cls)


def raw_agreement(pairs: list[tuple]) -> float | None:
    """Fraction of pairs whose two labels agree; None when empty."""
    if not pairs:
        return None
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def cohen_kappa(
    pairs: list[tuple[str, str]], categories: list[str] | None = None
) -> tuple[float | None, str | None]:
    """Unweighted Cohen's kappa over a fixed category set.

    Categories default to the rubric's four severity tiers, so tiers
    no grader assigned still count as categories (the standard
    treatment; it avoids inflating kappa when a tier never appears).

    Returns (kappa, note). kappa is None when it is undefined:
    with no pairs, or when expected agreement is 1.0 (all mass in a
    single tier for both graders, the kappa paradox). Callers
    implementing the section-6.3 gate must treat None as "kappa
    unevaluable" and fall through to the section-6.3.1 diagnostic,
    not as a pass or a fail.
    """
    cats = list(categories) if categories is not None else TIERS
    n = len(pairs)
    if n == 0:
        return (None, "no pairs to compare")
    po = sum(1 for a, b in pairs if a == b) / n
    n1 = Counter(a for a, b in pairs)
    n2 = Counter(b for a, b in pairs)
    pe = sum((n1[c] / n) * (n2[c] / n) for c in cats)
    if pe >= 1.0:
        return (None, "undefined: expected agreement is 1.0 (single-tier marginals)")
    return ((po - pe) / (1 - pe), None)


def bump_version(version: str, bump: str) -> str:
    """Apply a semver bump ('major', 'minor', 'patch')."""
    m = SEMVER_RE.match(version)
    if not m:
        raise ValueError(f"not a X.Y.Z version: {version!r}")
    major, minor, patch = (int(g) for g in m.groups())
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump: {bump!r}")


def bump_for_entry_types(types: list[str]) -> str | None:
    """Compute the version bump implied by a set of CHANGELOG entry types.

    Any retire/add ships a minor bump (gold values changed somewhere);
    otherwise any fix/annotate ships a patch bump (protocol 8.2).
    """
    t = set(types)
    if t & {"retire", "add"}:
        return "minor"
    if t & {"fix", "annotate"}:
        return "patch"
    return None


def mint_replacement_id(prefix: str, existing_numbers: list[int]) -> str:
    """Mint the next replacement ID: <prefix>-<NNN>, NNN zero-padded to 3.

    The prefix is the case's family prefix as it appears in live case IDs
    (e.g. ``v1-csp``); the result keeps that prefix verbatim and advances
    the numeric index. NNN is max(existing numeric indices for the prefix)
    + 1, per the protocol's P3-8 resolution. Retired numbers are never
    reused: the caller must pass the union of live and retired indices.
    """
    nxt = max(existing_numbers, default=0) + 1
    if nxt > 999:
        raise ValueError(f"index overflow for prefix {prefix}: {nxt} exceeds 999")
    return f"{prefix}-{nxt:03d}"


def parse_case_id(case_id: str) -> tuple[str, int]:
    """Split 'v1-csp-001' into ('csp', 1); raises ValueError if malformed."""
    m = CASE_ID_RE.match(case_id)
    if not m:
        raise ValueError(f"malformed case ID: {case_id!r}")
    return (m.group(1), int(m.group(2)))


def load_case_index(cases_dir: Path) -> dict[str, dict]:
    """Load every case into {case_id: case_dict} from a cases directory.

    Raises ValueError on duplicate IDs or malformed lines.
    """
    index: dict[str, dict] = {}
    for path in sorted(cases_dir.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path.name}:{lineno}: bad JSON: {e}")
                cid = case.get("case_id")
                if not cid:
                    raise ValueError(f"{path.name}:{lineno}: missing case_id")
                if cid in index:
                    raise ValueError(f"duplicate case_id {cid} ({path.name}:{lineno})")
                index[cid] = case
    return index


def validate_changelog_entry(entry: dict) -> list[str]:
    """Check one CHANGELOG entry against docs/Dataset-Changelog.md.

    Returns a list of violation descriptions; empty means well-formed.
    """
    errors: list[str] = []
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]
    etype = entry.get("type")
    if etype not in CHANGELOG_REQUIRED:
        errors.append(f"unknown entry type: {etype!r}")
        return errors
    for field in CHANGELOG_REQUIRED[etype]:
        if field not in entry:
            errors.append(f"{etype} entry missing required field: {field}")
    date = entry.get("date")
    if date is not None and not DATE_RE.match(str(date)):
        errors.append(f"date {date!r} is not YYYY-MM-DD")
    for list_field in ("case_ids",):
        if list_field in entry and not isinstance(entry[list_field], list):
            errors.append(f"{list_field} must be a list")
    if etype == "retire" and "replacements" in entry:
        if not isinstance(entry["replacements"], dict):
            errors.append("replacements must be a map of old ID to new ID")
    return errors


def validate_changelog_doc(doc: dict) -> list[str]:
    """Check the CHANGELOG document envelope and every entry."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["CHANGELOG is not a JSON object"]
    for field in ("$schema_id", "format_version", "dataset", "dataset_version",
                  "entries"):
        if field not in doc:
            errors.append(f"CHANGELOG missing top-level field: {field}")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        errors.append("CHANGELOG entries must be a list")
        return errors
    for i, entry in enumerate(entries):
        for e in validate_changelog_entry(entry):
            errors.append(f"entries[{i}]: {e}")
    return errors
