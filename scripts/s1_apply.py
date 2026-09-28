#!/usr/bin/env python3
"""Map confirmed S-1 defects to corrections (protocol sections 8.2, 10).

    scripts/s1_apply.py --verdicts s1/adjudicated.json --dry-run

Input is the adjudicated verdict set: a JSON array whose entries are
either {"case_id": ..., "verdict": {...section-5.4 schema...}} or the
schema object itself carrying case_id. Each verdict is re-derived
mechanically against the case's current tier (s1_common.derive_verdict);
entries whose derived overall is not DEFECT are skipped (they are
confirmed KEEPs).

For each confirmed defect the script builds a correction spec:

- retire+add (classes 1, 6, and 3/4 with answer impact): retire the old
  ID, mint the replacement ID (<prefix>-<NNN>, e.g. v1-csp-128; NNN = max
  live and retired index for the prefix + 1; retired numbers are never
  reused), and queue the replacement case for human authoring.
- annotate (class 2): write the annotation record
  (s1/annotations/<case_id>.json); case bytes unchanged.
- fix (class 5, and 3/4 tagged answer-preserving): queue the in-place
  edit for human authoring with the issue detail.

What the script writes (non-dry-run): s1/corrections.json (the full
machine-readable plan, including the human work queue), annotation
sidecars under s1/annotations/, and grouped CHANGELOG entries
(appended to dataset/v1/cases/CHANGELOG.json, one per entry type,
each carrying dataset_version, origin "s1_apply" and a batch id).
It does NOT edit case JSONL files: fixes, replacement cases and
retire removals are authored by the sweep operator in the sweep PR
(the script cannot safely author corrected case text from a defect
description), and s1_verify.py validates the finished state.

--dry-run prints the whole plan and writes nothing.

Version bump (protocol 8.2): minor if any retire+add shipped, else
patch. The new version is bumped from the CHANGELOG's current
dataset_version.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_common as C  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_verdicts(path: Path) -> list[tuple[str, dict]]:
    """Normalize adjudicated.json into [(case_id, verdict)] pairs."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: {path} is not valid JSON: {e}")
    if not isinstance(doc, list):
        raise SystemExit(f"error: {path} must be a JSON array")
    pairs: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for i, entry in enumerate(doc):
        if not isinstance(entry, dict):
            raise SystemExit(f"error: {path}[{i}] is not an object")
        if "verdict" in entry:
            cid = entry.get("case_id")
            verdict = entry["verdict"]
        else:
            cid = entry.get("case_id")
            verdict = entry
        if not cid or not isinstance(verdict, dict):
            raise SystemExit(f"error: {path}[{i}]: need case_id and verdict")
        if cid in seen:
            raise SystemExit(f"error: {path}[{i}]: duplicate verdict for {cid}")
        seen.add(cid)
        errs = C.validate_grading(verdict)
        if errs:
            raise SystemExit(f"error: {path}[{i}] ({cid}): "
                             + "; ".join(errs))
        pairs.append((cid, verdict))
    return pairs


def retired_ids_from_changelog(doc: dict) -> set[str]:
    retired: set[str] = set()
    for entry in doc.get("entries", []):
        if entry.get("type") == "retire":
            retired.update(entry.get("case_ids", []))
    return retired


def minted_ids_from_changelog(doc: dict) -> set[str]:
    """Replacement IDs already minted by earlier retire entries."""
    minted: set[str] = set()
    for entry in doc.get("entries", []):
        if entry.get("type") == "retire":
            minted.update(entry.get("replacements", {}).values())
    return minted


def family_prefixes(index: dict[str, dict]) -> dict[str, str]:
    """Map family name -> ID prefix ('v1-csp'), from live cases."""
    prefixes: dict[str, str] = {}
    for cid, case in index.items():
        fam = case.get("family")
        if fam and fam not in prefixes:
            prefixes[fam] = cid.rsplit("-", 1)[0]
    return prefixes


def max_indices(index: dict[str, dict], retired: set[str],
                minted: set[str]) -> dict[str, list[int]]:
    """Map ID prefix -> all known numeric indices.

    Union of live, retired, and previously minted replacement indices, so
    a new replacement never collides with any of them. Retired numbers
    are never reused (protocol P3-8).
    """
    out: dict[str, list[int]] = defaultdict(list)
    for cid in list(index) + sorted(retired) + sorted(minted):
        try:
            _letters, num = C.parse_case_id(cid)
        except ValueError:
            continue
        out[cid.rsplit("-", 1)[0]].append(num)
    return out


def build_correction(
    case_id: str,
    verdict: dict,
    derived: dict,
    case: dict,
    minter: dict[str, list[int]],
    prefixes: dict[str, str],
) -> dict:
    """Build the correction spec for one confirmed defect."""
    family = case.get("family")
    spec: dict = {
        "case_id": case_id,
        "family": family,
        "defect_class": derived["defect_class"],
        "all_defect_classes": derived["all_defect_classes"],
        "correction_path": derived["correction_path"],
        "dimensions": {
            name: {"defect": d["defect"],
                   "defect_class": d.get("defect_class")}
            for name, d in derived["dimensions"].items()
        },
    }
    path = derived["correction_path"]
    if path == "retire+add":
        prefix = prefixes[family]
        new_id = C.mint_replacement_id(prefix, minter[prefix])
        minter[prefix].append(int(new_id.rsplit("-", 1)[1]))
        spec["action"] = "retire+add"
        spec["retire_id"] = case_id
        spec["new_id"] = new_id
        spec["human_work"] = (
            f"Author replacement case {new_id} (family {family}) and append "
            f"it to {family}.jsonl; remove retired case {case_id} from "
            f"{family}.jsonl. Defect class {derived['defect_class']}: "
            f"{_defect_summary(verdict, derived)}"
        )
    elif path == "annotate":
        sev = derived["dimensions"]["severity"]
        spec["action"] = "annotate"
        spec["annotation"] = {
            "case_id": case_id,
            "annotation_type": "severity_regrade",
            "severity_tier": verdict["severity_tier"],
            "previous_tier": sev["current_tier"],
            "direction": sev["direction"],
            "severity_bullet": verdict.get("severity_bullet"),
            "severity_notes": verdict.get("severity_notes"),
            "source": "S-1 re-grade (adjudicated)",
        }
        spec["human_work"] = (
            f"No case edit: annotation record written by s1_apply.py. "
            f"Case bytes unchanged (severity {sev['current_tier']} -> "
            f"{verdict['severity_tier']} recorded as annotation)."
        )
    else:  # fix
        issues = []
        for e in verdict.get("factual_issues", []):
            issues.append(("factual", e if isinstance(e, str) else e.get("detail"))
                          )
        for e in verdict.get("format_issues", []):
            issues.append(("format", e if isinstance(e, str) else e.get("detail")))
        spec["action"] = "fix"
        spec["issues"] = [{"dimension": d, "detail": t} for d, t in issues]
        spec["human_work"] = (
            f"Edit case {case_id} in place in {family}.jsonl "
            f"(answer unaffected): "
            + "; ".join(t for _d, t in issues)
        )
    return spec


def _defect_summary(verdict: dict, derived: dict) -> str:
    parts = []
    for name, d in derived["dimensions"].items():
        if d["defect"]:
            cls = d.get("defect_class")
            if cls is None:
                # Format dimension stores a list of classes.
                classes = d.get("defect_classes", [])
                cls = ",".join(str(c) for c in classes) or "?"
            parts.append(f"{name}=class {cls}")
    return ", ".join(parts) or "defect"


def group_changelog_entries(
    corrections: list[dict], new_version: str, date: str, batch: str
) -> list[dict]:
    """Group corrections into one CHANGELOG entry per entry type."""
    by_action: dict[str, list[dict]] = defaultdict(list)
    for c in corrections:
        by_action[c["action"]].append(c)

    entries: list[dict] = []
    if by_action["retire+add"]:
        rs = by_action["retire+add"]
        entries.append({
            "date": date,
            "type": "retire",
            "dataset_version": new_version,
            "description": f"S-1 re-grade: retire {len(rs)} defective cases",
            "case_ids": [c["retire_id"] for c in rs],
            "rationale": "Confirmed defects under D-36 (S-1 re-grade). "
                         "Per-case rationales in per_case.",
            "replacements": {c["retire_id"]: c["new_id"] for c in rs},
            "per_case": {
                c["retire_id"]: {
                    "defect_class": c["defect_class"],
                    "new_id": c["new_id"],
                    "summary": c["human_work"],
                } for c in rs
            },
            "origin": "s1_apply",
            "batch": batch,
        })
        entries.append({
            "date": date,
            "type": "add",
            "dataset_version": new_version,
            "description": f"S-1 re-grade: add {len(rs)} replacement cases",
            "case_ids": [c["new_id"] for c in rs],
            "rationale": "Replacements for retired cases (retire+add); "
                         "retired IDs never reused.",
            "origin": "s1_apply",
            "batch": batch,
        })
    if by_action["fix"]:
        fs = by_action["fix"]
        entries.append({
            "date": date,
            "type": "fix",
            "dataset_version": new_version,
            "description": f"S-1 re-grade: fix {len(fs)} cases (answer unaffected)",
            "case_ids": [c["case_id"] for c in fs],
            "rationale": "Typo/formatting or answer-preserving corrections; "
                         "per-case rationale in per_case.",
            "diff_summary": "; ".join(
                f"{c['case_id']}: "
                + ", ".join(i["detail"] for i in c["issues"]) for c in fs
            )[:2000],
            "per_case": {
                c["case_id"]: {
                    "defect_class": c["defect_class"],
                    "issues": c["issues"],
                } for c in fs
            },
            "origin": "s1_apply",
            "batch": batch,
        })
    if by_action["annotate"]:
        an = by_action["annotate"]
        entries.append({
            "date": date,
            "type": "annotate",
            "dataset_version": new_version,
            "description": f"S-1 re-grade: annotate {len(an)} severity re-grades",
            "case_ids": [c["case_id"] for c in an],
            "rationale": "Severity re-grades do not change prompts, options "
                         "or correct answers (D-35 precedent); recorded as "
                         "annotations. Per-case records in per_case.",
            "per_case": {c["case_id"]: c["annotation"] for c in an},
            "origin": "s1_apply",
            "batch": batch,
        })
    return entries


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verdicts", required=True,
                   help="s1/adjudicated.json (adjudicated verdict set)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan without writing anything")
    p.add_argument("--force", action="store_true",
                   help="allow appending when s1_apply entries already exist")
    p.add_argument("--cases", default=str(REPO_ROOT / "dataset" / "v1" / "cases"),
                   help="dataset cases directory")
    p.add_argument("--changelog",
                   default=str(REPO_ROOT / "dataset" / "v1" / "cases"
                               / "CHANGELOG.json"),
                   help="CHANGELOG.json to append to")
    p.add_argument("--plan-out", default=str(REPO_ROOT / "s1" / "corrections.json"),
                   help="output corrections plan JSON")
    args = p.parse_args(argv)

    cases_dir = Path(args.cases)
    changelog_path = Path(args.changelog)
    plan_path = Path(args.plan_out)
    if not cases_dir.is_dir():
        raise SystemExit(f"error: cases directory not found: {cases_dir}")
    if not changelog_path.is_file():
        raise SystemExit(f"error: CHANGELOG not found: {changelog_path}")

    pairs = load_verdicts(Path(args.verdicts))
    index = C.load_case_index(cases_dir)
    changelog = json.loads(changelog_path.read_text(encoding="utf-8"))
    cl_errs = C.validate_changelog_doc(changelog)
    if cl_errs:
        raise SystemExit("error: CHANGELOG invalid:\n  " + "\n  ".join(cl_errs))

    existing_batches = [e for e in changelog.get("entries", [])
                        if e.get("origin") == "s1_apply"]
    if existing_batches and not args.dry_run and not args.force:
        raise SystemExit(
            "error: CHANGELOG already contains s1_apply entries "
            f"({len(existing_batches)}). Re-running would duplicate them; "
            "pass --force if that is intended."
        )

    retired = retired_ids_from_changelog(changelog)
    prefixes = family_prefixes(index)
    minter = max_indices(index, retired, minted_ids_from_changelog(changelog))

    corrections: list[dict] = []
    dispositions: list[dict] = []
    skipped_keep = 0
    for case_id, verdict in pairs:
        if case_id not in index:
            raise SystemExit(f"error: verdict for unknown case {case_id}")
        if case_id in retired:
            raise SystemExit(f"error: verdict for retired case {case_id}")
        derived = C.derive_verdict(verdict, index[case_id]["severity"])
        drafted = derived["overall"] == "DEFECT"
        dispositions.append({
            "case_id": case_id,
            "current_tier": index[case_id]["severity"],
            "overall": derived["overall"],
            "defect_class": derived["defect_class"],
            "all_defect_classes": derived["all_defect_classes"],
            "correction_path": derived["correction_path"],
            "correction_drafted": drafted,
        })
        if not drafted:
            skipped_keep += 1
            continue
        corrections.append(build_correction(
            case_id, verdict, derived, index[case_id], minter, prefixes))

    entry_types = []
    for c in corrections:
        entry_types.extend(
            ["retire", "add"] if c["action"] == "retire+add" else [c["action"]]
        )
    bump = C.bump_for_entry_types(entry_types)
    pre_version = changelog.get("dataset_version", "0.0.0")
    new_version = C.bump_version(pre_version, bump) if bump else pre_version

    stamp = C.utc_now()
    batch = stamp
    date = stamp[:10]
    entries = group_changelog_entries(corrections, new_version, date, batch)

    plan = {
        "tool": "scripts/s1_apply.py",
        "generated_utc": stamp,
        "verdicts_file": str(args.verdicts),
        "n_verdicts": len(pairs),
        "n_confirmed_defects": len(corrections),
        "n_confirmed_keep": skipped_keep,
        "pre_version": pre_version,
        "version_bump": bump,
        "new_version": new_version,
        "corrections": corrections,
        "adjudicated_dispositions": dispositions,
        "changelog_entries": entries,
        "human_work_queue": [
            {"case_id": c.get("retire_id", c["case_id"]),
             "action": c["action"],
             "work": c["human_work"]}
            for c in corrections
        ],
    }

    # --- dry run: print everything, write nothing ---
    print(f"S-1 corrections plan ({len(corrections)} confirmed defects, "
          f"{skipped_keep} keeps skipped)")
    print(f"version: {pre_version} -> {new_version} ({bump})")
    for c in corrections:
        extra = ""
        if c["action"] == "retire+add":
            extra = f" retire {c['retire_id']} -> add {c['new_id']}"
        print(f"  [{c['action']}] {c['case_id']} "
              f"(class {c['defect_class']}){extra}")
    print(f"CHANGELOG entries to append: {len(entries)} "
          f"({', '.join(e['type'] for e in entries) or 'none'})")
    if args.dry_run:
        print("dry-run: wrote nothing")
        return 0

    # --- write the plan, annotations, and CHANGELOG entries ---
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")

    annotations_dir = plan_path.parent / "annotations"
    n_annotations = 0
    for c in corrections:
        if c["action"] == "annotate":
            annotations_dir.mkdir(parents=True, exist_ok=True)
            (annotations_dir / f"{c['case_id']}.json").write_text(
                json.dumps(c["annotation"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            n_annotations += 1

    changelog["entries"].extend(entries)
    if entries:
        changelog["dataset_version"] = new_version
        changelog_path.write_text(
            json.dumps(changelog, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"appended {len(entries)} CHANGELOG entries; "
              f"dataset_version -> {new_version}")
    else:
        print("no corrections: CHANGELOG left untouched")
    print(f"wrote plan: {plan_path} "
          f"({len(corrections)} corrections, {n_annotations} annotations)")
    print("case JSONL edits (fixes, replacement cases, retire removals) are "
          "human work: see human_work_queue in the plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
