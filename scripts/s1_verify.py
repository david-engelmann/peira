#!/usr/bin/env python3
"""Post-sweep verification for the S-1 re-grade (protocol sections 9, 10).

    scripts/s1_verify.py --manifest dataset/v1/cases/manifest.json

Runs after the sweep PR's case edits and manifest rebuild (protocol
Phase 5). Checks, each reported separately; exit 1 if any fail:

1. Manifest integrity: every file's sha256 and case summary matches
   (the manifest hash chain), via peira.dataset.verify_manifest.
2. Manifest dataset_version equals the corrections plan's new_version.
3. Schema validity (peira.schema.validate_case_dict) of every touched
   case: edited fix/annotate cases and every new replacement case.
4. ID uniqueness across the live corpus (no duplicates).
5. No retired-ID reuse: retired IDs appear in no live file; no new ID
   collides with a retired or live ID; every minted replacement ID
   exists in the live corpus.
6. No dropped defects (P3-5): every adjudicated DEFECT has a
   correction draft in s1/corrections.json AND a CHANGELOG entry
   covering it.
7. CHANGELOG well-formedness per docs/Dataset-Changelog.md
   (required fields per type, dataset_version on each entry).
8. Version-bump consistency: the bump recomputed from the s1_apply
   batch's entry types matches the plan's bump; new_version equals
   bump(pre_version); the CHANGELOG and manifest versions equal
   new_version.
9. Seal hash binding: if the CHANGELOG has seal entries, the latest
   seal's manifest_sha256 matches the recomputed manifest digest.
10. Annotation records: every annotate correction has its
    s1/annotations/<case_id>.json sidecar.

Optional paths default to the conventional s1/ locations; override
them when the sweep used different ones.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_common as C  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira import dataset as peira_dataset  # noqa: E402
from peira.schema import validate_case_dict  # noqa: E402


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


class Check:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []

    def fail(self, msg: str) -> None:
        self.errors.append(msg)

    def ok(self) -> bool:
        return not self.errors


def check_manifest(cases_dir: Path) -> Check:
    c = Check("manifest integrity (hash chain)")
    for e in peira_dataset.verify_manifest(cases_dir):
        c.fail(e)
    return c


def check_versions(manifest: dict, changelog: dict, plan: dict,
                   batch_entries: list[dict]) -> Check:
    c = Check("version-bump consistency")
    pre_version = plan.get("pre_version")
    new_version = plan.get("new_version")
    claimed_bump = plan.get("version_bump")
    if not pre_version or not new_version:
        c.fail("corrections plan missing pre_version/new_version")
        return c
    recomputed = C.bump_for_entry_types([e.get("type") for e in batch_entries])
    if recomputed != claimed_bump:
        c.fail(f"plan claims bump {claimed_bump!r} but batch entry types "
               f"imply {recomputed!r}")
    if claimed_bump is None:
        if new_version != pre_version:
            c.fail(f"no bump but version changed {pre_version} -> {new_version}")
    elif C.bump_version(pre_version, claimed_bump) != new_version:
        c.fail(f"bump({pre_version}, {claimed_bump}) != {new_version}")
    for e in batch_entries:
        if e.get("dataset_version") != new_version:
            c.fail(f"batch entry {e.get('type')} carries version "
                   f"{e.get('dataset_version')!r}, expected {new_version!r}")
    if changelog.get("dataset_version") != new_version:
        c.fail(f"CHANGELOG version {changelog.get('dataset_version')!r} != "
               f"{new_version!r}")
    if manifest.get("dataset_version") != new_version:
        c.fail(f"manifest version {manifest.get('dataset_version')!r} != "
               f"{new_version!r}")
    return c


def check_schema(index: dict[str, dict], touched: set[str]) -> Check:
    c = Check("schema validity of touched cases")
    for cid in sorted(touched):
        case = index.get(cid)
        if case is None:
            c.fail(f"touched case {cid} missing from live corpus")
            continue
        for e in validate_case_dict(case):
            c.fail(f"{cid}: {e}")
    return c


def check_retired(index: dict[str, dict], changelog: dict,
                  new_ids: set[str]) -> Check:
    c = Check("no retired-ID reuse")
    retired: set[str] = set()
    for entry in changelog.get("entries", []):
        if entry.get("type") == "retire":
            retired.update(entry.get("case_ids", []))
    live = set(index)
    for rid in sorted(retired):
        if rid in live:
            c.fail(f"retired ID {rid} still present in live corpus")
    for nid in sorted(new_ids):
        if nid in retired:
            c.fail(f"new ID {nid} collides with a retired ID")
        if nid not in live:
            c.fail(f"minted replacement ID {nid} missing from live corpus")
    return c


def check_no_dropped_defects(pairs: list[tuple[str, dict]] | None,
                             corrections: list[dict],
                             batch_entries: list[dict],
                             ledger: list[dict]) -> Check:
    c = Check("no adjudicated DEFECT dropped")
    if not ledger:
        c.fail("corrections plan has no adjudicated_dispositions ledger; "
               "regenerate it with the current s1_apply")
        return c
    if pairs is not None:
        ledger_ids = {d.get("case_id") for d in ledger}
        verdict_ids = {cid for cid, _ in pairs}
        if ledger_ids != verdict_ids:
            missing = sorted(verdict_ids - ledger_ids)
            extra = sorted(ledger_ids - verdict_ids)
            c.fail("disposition ledger does not cover the adjudicated input: "
                   f"missing={missing} extra={extra}")
    draft_by_case = {co.get("case_id"): co for co in corrections}
    covered: set[str] = set()
    for e in batch_entries:
        covered.update(e.get("case_ids", []))
        if e.get("type") == "retire":
            covered.update(e.get("replacements", {}).keys())
    for d in ledger:
        if d.get("overall") != "DEFECT":
            continue
        cid = d.get("case_id")
        if cid not in draft_by_case:
            c.fail(f"adjudicated DEFECT {cid} "
                   f"(class {d.get('defect_class')}) has no correction draft")
            continue
        if cid not in covered:
            c.fail(f"DEFECT {cid} has a correction draft but no "
                   f"CHANGELOG entry")
        co = draft_by_case[cid]
        if co.get("action") == "retire+add":
            nid = co.get("new_id")
            if nid not in covered:
                c.fail(f"DEFECT {cid}: replacement {nid} has no "
                       f"CHANGELOG add entry")
    return c


def check_changelog(changelog: dict) -> Check:
    c = Check("CHANGELOG well-formedness")
    for e in C.validate_changelog_doc(changelog):
        c.fail(e)
    return c


def check_seal_binding(changelog: dict, cases_dir: Path) -> Check:
    c = Check("seal hash binding")
    seals = [e for e in changelog.get("entries", []) if e.get("type") == "seal"]
    if not seals:
        return c  # v1 is unsealed; nothing to bind yet
    _manifest, digest, _errors = peira_dataset.verify_manifest_sealed(cases_dir)
    latest = seals[-1]
    if latest.get("manifest_sha256") != digest:
        c.fail("latest seal manifest_sha256 does not match recomputed "
               "manifest digest")
    return c


def check_annotations(corrections: list[dict], annotations_dir: Path) -> Check:
    c = Check("annotation records present")
    for co in corrections:
        if co.get("action") == "annotate":
            p = annotations_dir / f"{co['case_id']}.json"
            if not p.is_file():
                c.fail(f"annotate correction {co['case_id']}: missing {p}")
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                c.fail(f"{p}: bad JSON: {e}")
                continue
            if doc.get("case_id") != co["case_id"]:
                c.fail(f"{p}: case_id mismatch")
    return c


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", required=True, help="manifest.json path")
    p.add_argument("--corrections", default=None,
                   help="s1_apply corrections plan (optional: when absent, "
                        "only manifest/CHANGELOG/seal checks run)")
    p.add_argument("--verdicts", default=None,
                   help="adjudicated verdict set (optional: cross-checks the "
                        "plan's disposition ledger against the original input)")
    p.add_argument("--changelog",
                   default="dataset/v1/cases/CHANGELOG.json",
                   help="CHANGELOG.json path")
    p.add_argument("--annotations", default="s1/annotations",
                   help="annotation sidecar directory")
    args = p.parse_args(argv)

    manifest_path = _resolve(args.manifest)
    cases_dir = manifest_path.parent
    corrections_path = _resolve(args.corrections) if args.corrections else None
    verdicts_path = _resolve(args.verdicts) if args.verdicts else None
    changelog_path = _resolve(args.changelog)
    annotations_dir = _resolve(args.annotations)

    for label, path in (("manifest", manifest_path),
                        ("changelog", changelog_path)):
        if not path.is_file():
            print(f"FAIL: {label} not found: {path}")
            return 1

    pairs = None
    if verdicts_path is not None:
        if not verdicts_path.is_file():
            print(f"FAIL: verdicts not found: {verdicts_path}")
            return 1
        verdicts_doc = json.loads(verdicts_path.read_text(encoding="utf-8"))
        if not isinstance(verdicts_doc, list):
            print(f"FAIL: verdicts must be a JSON array: {verdicts_path}")
            return 1
        pairs = []
        for i, e in enumerate(verdicts_doc):
            if not isinstance(e, dict):
                print(f"FAIL: verdicts[{i}] is not an object: {verdicts_path}")
                return 1
            pairs.append((e.get("case_id"), e.get("verdict", e)))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changelog = json.loads(changelog_path.read_text(encoding="utf-8"))

    plan: dict = {}
    corrections: list[dict] = []
    ledger: list[dict] = []
    batch_entries: list[dict] = []
    if corrections_path is not None:
        if not corrections_path.is_file():
            print(f"FAIL: corrections not found: {corrections_path}")
            return 1
        plan = json.loads(corrections_path.read_text(encoding="utf-8"))
        corrections = plan.get("corrections", [])
        ledger = plan.get("adjudicated_dispositions", [])
        batch_id = plan.get("generated_utc")
        batch_entries = [e for e in changelog.get("entries", [])
                         if e.get("batch") == batch_id and
                         e.get("origin") == "s1_apply"]
    else:
        print("note: no corrections plan; running manifest/CHANGELOG/seal "
              "checks only")

    # load_case_index raises on duplicate IDs: check 4 (uniqueness).
    try:
        index = C.load_case_index(cases_dir)
    except ValueError as e:
        print(f"FAIL: corpus ID uniqueness: {e}")
        return 1

    corrections = plan.get("corrections", [])
    touched: set[str] = set()
    new_ids: set[str] = set()
    for co in corrections:
        if co.get("action") == "retire+add":
            new_ids.add(co["new_id"])
            touched.add(co["new_id"])
        else:
            touched.add(co["case_id"])

    checks = [
        check_manifest(cases_dir),
        check_changelog(changelog),
        check_seal_binding(changelog, cases_dir),
    ]
    if plan:
        checks.extend([
            check_versions(manifest, changelog, plan, batch_entries),
            check_schema(index, touched),
            check_retired(index, changelog, new_ids),
            check_no_dropped_defects(pairs, corrections, batch_entries,
                                     ledger),
            check_annotations(corrections, annotations_dir),
        ])
    else:
        c = Check("manifest/CHANGELOG version agreement")
        if manifest.get("dataset_version") != changelog.get("dataset_version"):
            c.fail(f"manifest version {manifest.get('dataset_version')!r} != "
                   f"CHANGELOG version {changelog.get('dataset_version')!r}")
        checks.append(c)

    failed = [c for c in checks if not c.ok()]
    for c in checks:
        status = "ok" if c.ok() else "FAIL"
        print(f"[{status}] {c.name}")
        for e in c.errors:
            print(f"    - {e}")
    if failed:
        print(f"s1_verify: {len(failed)} check(s) FAILED")
        return 1
    print(f"s1_verify: all {len(checks)} checks passed "
          f"({len(index)} live cases, {len(corrections)} corrections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
