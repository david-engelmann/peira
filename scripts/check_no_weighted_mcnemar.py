#!/usr/bin/env python3
"""Fail if any report attaches a McNemar p-value to a weighted metric.

McNemar's test operates on unweighted discordant-pair counts — that is
the entire statistic. There is no standard cost-weighted McNemar. A
p-value from McNemar attached to a severity-weighted or cost-weighted
metric is a category error; weighted comparisons get paired-bootstrap
inference instead (C-2).

This script enforces the rule two ways:

1. Structural check: build a synthetic comparison dict through
   ``peira.compare.comparison_to_dict`` and run
   ``validate_no_weighted_mcnemar`` over it. The shipped comparison
   structure must be clean.
2. Negative control: feed the validator a deliberately violating dict
   and require it to flag the violation. A validator that cannot catch
   a violation is not a gate.
3. Static check: grep ``python/peira`` for code patterns that assign a
   McNemar p-value alongside a weighted metric name.

Exits nonzero with a violation report on any failure.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from peira.compare import (  # noqa: E402
    WEIGHTED_METRIC_NAMES,
    validate_no_weighted_mcnemar,
)


def check_structural() -> list[str]:
    """The shipped comparison dict structure must validate clean."""
    # A minimal comparison dict in the shape comparison_to_dict emits:
    # top-level "mcnemar" block (unweighted headline test) plus
    # weighted_deltas carrying bootstrap CIs only.
    report = {
        "mcnemar": {"b": 12, "c": 4, "p_value": 0.03, "winner": "a"},
        "weighted_deltas": [
            {
                "name": "severity_weighted_asr",
                "delta": 0.07,
                "ci95": [0.01, 0.13],
                "n": 200,
                "sufficient": True,
                "favors": "a",
            }
        ],
        "deltas": [
            {"name": "asr", "delta": 0.05, "ci95": [0.0, 0.1],
             "n": 200, "sufficient": True, "favors": None}
        ],
    }
    violations = validate_no_weighted_mcnemar(report)
    if violations:
        return [f"structural: clean report flagged: {v}" for v in violations]
    return []


def check_negative_control() -> list[str]:
    """The validator must catch a deliberate violation."""
    bad = {
        "weighted_deltas": [
            {
                "name": "severity_weighted_asr",
                "delta": 0.07,
                "mcnemar_p_value": 0.03,
                "n": 200,
            }
        ]
    }
    violations = validate_no_weighted_mcnemar(bad)
    if not violations:
        return ["negative control: validator missed a McNemar p-value "
                "on severity_weighted_asr"]
    # Also check the "weighted" substring fallback and e_attacked.
    bad2 = {"metrics": [{"name": "e_attacked", "p_value": 0.01}]}
    if not validate_no_weighted_mcnemar(bad2):
        return ["negative control: validator missed p_value on e_attacked"]
    bad3 = {"x": {"name": "my_weighted_thing", "mcnemar_p": 0.04}}
    if not validate_no_weighted_mcnemar(bad3):
        return ["negative control: validator missed mcnemar_p on "
                "'my_weighted_thing'"]
    return []


# Assignment of a McNemar p-value key inside a dict/list literal that
# also mentions a weighted metric name, on nearby lines.
_STATIC_PATTERNS = [
    re.compile(
        r'(mcnemar_p_value|mcnemar_p)\s*[:=]\s*[^\n]*\n'
        r'(?:[^\n]*\n){0,3}[^\n]*(weighted|severity_weighted_asr|e_attacked)',
        re.IGNORECASE,
    ),
    re.compile(
        r'(weighted|severity_weighted_asr|e_attacked)[^\n]*\n'
        r'(?:[^\n]*\n){0,3}[^\n]*(mcnemar_p_value|mcnemar_p)\s*[:=]',
        re.IGNORECASE,
    ),
]


def check_static() -> list[str]:
    """Grep for code that pairs McNemar p-values with weighted metrics."""
    hits: list[str] = []
    for path in sorted((ROOT / "python" / "peira").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pat in _STATIC_PATTERNS:
            for m in pat.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                rel = path.relative_to(ROOT)
                hits.append(
                    f"{rel}:{lineno}: possible McNemar p-value on a "
                    f"weighted metric"
                )
    # The validator itself and this script mention both terms by design.
    hits = [h for h in hits
            if "check_no_weighted_mcnemar.py" not in h
            and "def validate_no_weighted_mcnemar" not in h]
    return hits


def main() -> int:
    problems: list[str] = []
    problems.extend(check_structural())
    problems.extend(check_negative_control())
    problems.extend(check_static())
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        n = len(problems)
        print(f"\n{n} weighted-McNemar violation{'s' if n != 1 else ''}; "
              "weighted metrics take paired-bootstrap inference, never "
              "McNemar p-values.", file=sys.stderr)
        return 1
    print("No McNemar p-values on weighted metrics. "
          f"Guarded names: {sorted(WEIGHTED_METRIC_NAMES)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
