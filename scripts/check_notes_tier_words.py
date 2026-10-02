#!/usr/bin/env python3
"""Fail on any notes/severity tier-word mismatch or scale-wording mismatch.

Case notes carry severity as prose sentences ("Critical: drug-approval
integrity.", "High: national trade position."). Two defect classes have
shipped in this file:

1. Stale tier-words (F-2, R-2): a severity re-grade leaves the old
   tier-word behind, so the corpus contradicts itself on its face.
   #280's refresh_notes only matched "Severity <old>:" and
   "Severity: <old> -" patterns and missed indirection's bare "<Tier>:"
   sentence style, re-creating the class at scale (31 mismatches).
2. Scale-wording mismatch (F-1, class-4): a score-primitive case whose
   expected_score is on the 0-1 convention while the prompt still says
   "0 to 100" / "70-plus" (v1-dfl-116, v1-ngm-128).

This script enforces both invariants corpus-wide, with a negative
control: a synthetic violating case must be flagged, so a validator
that cannot catch a violation is not a gate.

Exits nonzero with a violation report on any failure.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "dataset" / "v1" / "cases"

TIERS = ("critical", "high", "medium", "low")

# Bare severity sentences: "High: drug-approval integrity." The tier-word
# must open the sentence (start of notes or after ". "/"! "/"? "/"; ").
BARE_TIER_RE = re.compile(r"(?:^|[.!?;] )((?:Critical|High|Medium|Low)):")
# The two patterns #280's refresh_notes matched; both must agree with
# the case severity too.
SEVERITY_WORD_RE = re.compile(r"\bSeverity\s+(critical|high|medium|low):",
                              re.IGNORECASE)
SEVERITY_DASH_RE = re.compile(r"\bSeverity:\s*(critical|high|medium|low)\s*-",
                              re.IGNORECASE)

# Scale-wording (class-4): a 0-1 expected_score with a "0 to 100" prompt,
# or a bare "70-plus" threshold (the fixed form is "0.70-plus").
SCALE_100_RE = re.compile(r"0 to 100")
BARE_70_PLUS_RE = re.compile(r"(?<!0\.)70-plus")


def _iter_cases():
    for path in sorted(CASES_DIR.glob("*.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                yield path.name, lineno, json.loads(line)


def _check_tier_words(case: dict) -> list[str]:
    """Tier-words in notes must agree with the case severity."""
    errors = []
    cid = case.get("case_id", "?")
    severity = str(case.get("severity", "")).lower()
    notes = str(case.get("notes", ""))
    if severity not in TIERS:
        return [f"{cid}: unknown severity {severity!r}"]
    want = severity.capitalize()
    for m in BARE_TIER_RE.finditer(notes):
        if m.group(1) != want:
            errors.append(f"{cid}: notes say {m.group(1)!r} "
                          f"but severity is {severity!r}")
    for m in SEVERITY_WORD_RE.finditer(notes):
        if m.group(1).lower() != severity:
            errors.append(f"{cid}: notes say 'Severity {m.group(1)}' "
                          f"but severity is {severity!r}")
    for m in SEVERITY_DASH_RE.finditer(notes):
        if m.group(1).lower() != severity:
            errors.append(f"{cid}: notes say 'Severity: {m.group(1)}' "
                          f"but severity is {severity!r}")
    return errors


def _check_scale_wording(case: dict) -> list[str]:
    """0-1 expected_score cases must not carry 0-100 scale wording."""
    errors = []
    cid = case.get("case_id", "?")
    benign = case.get("benign") or {}
    score = benign.get("expected_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return []
    if not 0 <= score <= 1:
        return []
    for arm in ("benign", "attacked"):
        variant = case.get(arm) or {}
        prompt = (variant.get("input") or {}).get("prompt", "")
        if not isinstance(prompt, str):
            continue
        if SCALE_100_RE.search(prompt):
            errors.append(f"{cid} [{arm}]: prompt says '0 to 100' "
                          f"but expected_score is {score} (0-1 scale)")
        if BARE_70_PLUS_RE.search(prompt):
            errors.append(f"{cid} [{arm}]: prompt has bare '70-plus' "
                          f"threshold but expected_score is {score} (0-1 scale)")
    return errors


def check_corpus() -> list[str]:
    errors: list[str] = []
    for _fname, _lineno, case in _iter_cases():
        errors.extend(_check_tier_words(case))
        errors.extend(_check_scale_wording(case))
    return errors


def check_negative_control() -> list[str]:
    """The validator must catch a deliberately violating synthetic case."""
    errors = []
    bad_tier = {
        "case_id": "synthetic-tier",
        "severity": "critical",
        "notes": "Benign is deny. High: some consequence. Difficulty: easy.",
    }
    if not _check_tier_words(bad_tier):
        errors.append("negative control: stale 'High:' tier-word not flagged")
    bad_scale = {
        "case_id": "synthetic-scale",
        "benign": {"expected_score": 0.52,
                   "input": {"prompt": "Score 0 to 100. Award at 70-plus."}},
        "attacked": {"input": {"prompt": "Score 0 to 100."}},
    }
    if not _check_scale_wording(bad_scale):
        errors.append("negative control: '0 to 100' scale wording not flagged")
    good = {
        "case_id": "synthetic-good",
        "severity": "high",
        "notes": "Benign is deny. High: some consequence. Difficulty: easy.",
        "benign": {"expected_score": 0.52,
                   "input": {"prompt": "Score 0 to 1. Award at 0.70-plus."}},
        "attacked": {"input": {"prompt": "Score 0 to 1."}},
    }
    if _check_tier_words(good) or _check_scale_wording(good):
        errors.append("negative control: clean synthetic case wrongly flagged")
    return errors


def main() -> int:
    errors = check_corpus()
    errors.extend(check_negative_control())
    if errors:
        print("tier-word/scale-wording check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("tier-word/scale-wording check passed: "
          "zero mismatches corpus-wide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
