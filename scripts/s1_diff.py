#!/usr/bin/env python3
"""Compare two S-1 grading sets (protocol sections 5.4, 6.1, 6.3).

    scripts/s1_diff.py --a s1/grades_g1.json --b s1/grades_g2.json \\
        --cases dataset/v1/cases --out s1/disagreements.json

Each input is a JSON array of section-5.4 grading objects (or an
object with a "gradings" array). For every case present in both
sets, the script:

1. Validates each grading against the verdict schema (fail loudly).
2. Derives the severity-dimension defect verdict MECHANICALLY by
   comparing each grader's blind severity_tier against the case's
   current tier from the case files, then derives overall,
   defect_class and correction_path (protocol section 5.4; the
   blinded grader cannot set these without breaking the blinding).
3. Flags a case for adjudication when any of the five dimension
   verdicts differ (protocol section 6.1). Derived summary fields
   differ exactly when dimension verdicts differ, so they are
   consequences, not separate triggers.

Reports (pre-adjudication):

- raw agreement and Cohen's kappa on severity tiers (the 6.3 gate:
  raw >= 80% AND kappa >= 0.6);
- raw agreement on derived overall DEFECT/KEEP (diagnostic, P3-7);
- the marginal tier distribution per grader (the 6.3.1 diagnostic);
- two-tier disagreements (|tier distance| >= 2) and the >5% flag
  (protocol section 6.2).

Kappa uses the rubric's fixed four-tier category set. When kappa is
undefined (no pairs, or expected agreement 1.0 from single-tier
marginals: the kappa paradox), it is reported as null with a note,
and the gate's kappa component is reported as unevaluable so the
operator falls through to the section-6.3.1 diagnostic/waiver path
instead of treating it as a pass or fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_common as C  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

DIMENSIONS = ("severity", "gold", "factual", "attack_integrity", "format")


def load_gradings(path: Path) -> dict[str, dict]:
    """Load a grading set into {case_id: grading}, validating strictly."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: {path} is not valid JSON: {e}")
    if isinstance(doc, dict) and "gradings" in doc:
        doc = doc["gradings"]
    if not isinstance(doc, list):
        raise SystemExit(f"error: {path} must be a JSON array of gradings")
    gradings: dict[str, dict] = {}
    errors: list[str] = []
    for i, g in enumerate(doc):
        if not isinstance(g, dict) or "case_id" not in g:
            errors.append(f"[{i}]: not a grading object with case_id")
            continue
        cid = g["case_id"]
        if cid in gradings:
            errors.append(f"duplicate grading for {cid}")
            continue
        for e in C.validate_grading(g):
            errors.append(f"{cid}: {e}")
        gradings[cid] = g
    if errors:
        raise SystemExit("error: invalid gradings in "
                         f"{path}:\n  " + "\n  ".join(errors))
    return gradings


def _canon_issue(entry) -> str:
    """Canonical form of one issue entry for disagreement comparison."""
    if isinstance(entry, str):
        entry = {"detail": entry}
    if not isinstance(entry, dict):
        raise ValueError(f"issue entry must be a string or object: {entry!r}")
    return json.dumps(entry, sort_keys=True)


def _canon_issues(entries: list) -> list[str]:
    """Multiset-canonical form of an issue list (order-insensitive)."""
    return sorted(_canon_issue(e) for e in entries)


def differing_dimensions(ga: dict, gb: dict) -> list[str]:
    """Dimensions whose per-dimension verdicts differ (protocol 6.1)."""
    dims: list[str] = []
    if ga.get("severity_tier") != gb.get("severity_tier"):
        dims.append("severity")
    if ga.get("gold_verdict") != gb.get("gold_verdict"):
        dims.append("gold")
    if _canon_issues(ga.get("factual_issues") or []) != _canon_issues(
        gb.get("factual_issues") or []
    ):
        dims.append("factual")
    if ga.get("attack_integrity") != gb.get("attack_integrity"):
        dims.append("attack_integrity")
    if _canon_issues(ga.get("format_issues") or []) != _canon_issues(
        gb.get("format_issues") or []
    ):
        dims.append("format")
    return dims


def tier_distance(a: str, b: str) -> int:
    return abs(C.TIERS.index(a) - C.TIERS.index(b))


def analyze(
    gradings_a: dict[str, dict],
    gradings_b: dict[str, dict],
    index: dict[str, dict],
) -> dict:
    """Compare two grading sets; return the full analysis document."""
    common = sorted(set(gradings_a) & set(gradings_b))
    missing_a = sorted(set(gradings_b) - set(gradings_a))
    missing_b = sorted(set(gradings_a) - set(gradings_b))

    derived: dict[str, dict] = {}
    disagreements: list[dict] = []
    sev_pairs: list[tuple[str, str]] = []
    overall_pairs: list[tuple[str, str]] = []
    two_tier = 0

    for cid in common:
        if cid not in index:
            raise SystemExit(f"error: graded case {cid} not found in case files")
        current_tier = index[cid].get("severity")
        if current_tier not in C.TIERS:
            raise SystemExit(
                f"error: case {cid} has invalid current tier {current_tier!r}"
            )
        ga, gb = gradings_a[cid], gradings_b[cid]
        da = C.derive_verdict(ga, current_tier)
        db = C.derive_verdict(gb, current_tier)
        derived[cid] = {"grader_a": da, "grader_b": db}
        dims = differing_dimensions(ga, gb)
        if dims:
            disagreements.append(
                {
                    "case_id": cid,
                    "dimensions": dims,
                    "grader_a": ga,
                    "grader_b": gb,
                }
            )
        sev_pairs.append((ga["severity_tier"], gb["severity_tier"]))
        overall_pairs.append((da["overall"], db["overall"]))
        if tier_distance(ga["severity_tier"], gb["severity_tier"]) >= 2:
            two_tier += 1

    sev_raw = C.raw_agreement(sev_pairs)
    kappa, kappa_note = C.cohen_kappa(sev_pairs)
    overall_raw = C.raw_agreement(overall_pairs)
    marginals = {
        "grader_a": dict(Counter(a for a, _b in sev_pairs)),
        "grader_b": dict(Counter(b for _a, b in sev_pairs)),
    }
    # Every rubric tier appears, even unobserved (honest marginals).
    for side in ("grader_a", "grader_b"):
        for t in C.TIERS:
            marginals[side].setdefault(t, 0)

    n = len(common)
    two_tier_fraction = (two_tier / n) if n else 0.0
    gate_raw_ok = sev_raw is not None and sev_raw >= 0.80
    gate_kappa_ok = kappa is not None and kappa >= 0.60

    return {
        "n_compared": n,
        "n_only_in_a": len(missing_b),
        "n_only_in_b": len(missing_a),
        "missing_in_a": missing_a,
        "missing_in_b": missing_b,
        "derived": derived,
        "agreement": {
            "severity_raw": sev_raw,
            "severity_kappa": kappa,
            "kappa_categories": C.TIERS,
            "kappa_note": kappa_note,
            "overall_defect_keep_raw": overall_raw,
            "marginals": marginals,
            "two_tier_disagreements": two_tier,
            "two_tier_fraction": two_tier_fraction,
            "two_tier_flag": two_tier_fraction > 0.05,
            "gate": {
                "raw_threshold": 0.80,
                "kappa_threshold": 0.60,
                "raw_ok": gate_raw_ok,
                "kappa_ok": gate_kappa_ok,
                # kappa None (undefined) is unevaluable, not a pass:
                # the operator must run the 6.3.1 diagnostic.
                "kappa_evaluable": kappa is not None,
                "pass": gate_raw_ok and gate_kappa_ok,
            },
        },
        "disagreements": disagreements,
        "n_disagreements": len(disagreements),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--a", required=True, help="first grading set JSON")
    p.add_argument("--b", required=True, help="second grading set JSON")
    p.add_argument("--cases", default=str(REPO_ROOT / "dataset" / "v1" / "cases"),
                   help="dataset cases directory (current tiers)")
    p.add_argument("--out", required=True, help="output disagreements JSON")
    args = p.parse_args(argv)

    cases_dir = Path(args.cases)
    if not cases_dir.is_dir():
        raise SystemExit(f"error: cases directory not found: {cases_dir}")

    gradings_a = load_gradings(Path(args.a))
    gradings_b = load_gradings(Path(args.b))
    index = C.load_case_index(cases_dir)
    result = analyze(gradings_a, gradings_b, index)

    doc = {
        "tool": "scripts/s1_diff.py",
        "generated_utc": C.utc_now(),
        "inputs": {"a": str(args.a), "b": str(args.b),
                   "cases": str(cases_dir)},
        **result,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    ag = result["agreement"]
    gate = ag["gate"]
    raw = ag["severity_raw"]
    overall = ag["overall_defect_keep_raw"]
    print(f"compared {result['n_compared']} cases; "
          f"{result['n_disagreements']} disagreements -> {out}")
    print(f"severity raw agreement: {'n/a' if raw is None else f'{raw:.3f}'} "
          f"(gate: {'PASS' if gate['raw_ok'] else 'FAIL'})")
    if ag["severity_kappa"] is None:
        print(f"severity kappa: UNEVALUABLE ({ag['kappa_note']}) "
              "- run the 6.3.1 diagnostic")
    else:
        print(f"severity kappa: {ag['severity_kappa']:.3f} "
              f"(gate: {'PASS' if gate['kappa_ok'] else 'FAIL'})")
    print(f"overall DEFECT/KEEP raw agreement (diagnostic): "
          f"{'n/a' if overall is None else f'{overall:.3f}'})")
    print(f"two-tier disagreements: {ag['two_tier_disagreements']} "
          f"({ag['two_tier_fraction']:.1%})"
          f"{' - FLAG: rubric guidance needs work' if ag['two_tier_flag'] else ''}")
    print(f"agreement gate: {'PASS' if gate['pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
