#!/usr/bin/env python3
"""Apply v2-draft-audit mechanical fixes (perfection gate item 8).

All fixes are pure copy edits to prompt/notes text verified by hand;
no labels, options, or case structure are touched.

Fix 1: article errors in role lines ("You are a insurance/admissions/...")
       -> "You are an ...". Excludes "a university" / "a utilization"
       (correct as-is).
Fix 2: doubled "Score score X higher" question line in 30 evidence_positioning
       score cases -> "Score X higher".
Fix 3: 44 verbosity_inflation abstain cases whose notes claim "the choice
       primitive" while the primitive field is 'abstain' -> correct the notes.

Usage: python3 scripts/apply_v2_audit_fixes.py [--check]
--check prints what would change without writing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "dataset" / "v2" / "cases"

ARTICLE_RE = re.compile(
    r"\bYou are a (admissions|insurance|emergency|immigration|academic|"
    r"environmental|aviation|election|air)\b"
)
SCORESCORE_RE = re.compile(r"\bScore score ")
CHOICE_PRIMITIVE_NOTE = (
    "Uses the choice primitive with abstain as the benign-expected option."
)
ABSTAIN_PRIMITIVE_NOTE = (
    "Uses the abstain primitive; abstain is the benign-expected option."
)


def fix_file(path: Path, check: bool) -> dict:
    counts = {"article": 0, "scorescore": 0, "notes": 0}
    rows = []
    changed = False
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        row_changed = False
        for arm in ("benign", "attacked"):
            p = row[arm]["input"]["prompt"]
            p2, n = ARTICLE_RE.subn(r"You are an \1", p)
            if n:
                counts["article"] += n
                row[arm]["input"]["prompt"] = p2
                row_changed = True
            p = row[arm]["input"]["prompt"]
            p2, n = SCORESCORE_RE.subn("Score ", p)
            if n:
                counts["scorescore"] += n
                row[arm]["input"]["prompt"] = p2
                row_changed = True
        if CHOICE_PRIMITIVE_NOTE in row["notes"]:
            row["notes"] = row["notes"].replace(
                CHOICE_PRIMITIVE_NOTE, ABSTAIN_PRIMITIVE_NOTE
            )
            counts["notes"] += 1
            row_changed = True
        changed = changed or row_changed
        rows.append(json.dumps(row, ensure_ascii=False))
    if changed and not check:
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return counts


def main() -> int:
    check = "--check" in sys.argv
    total = {"article": 0, "scorescore": 0, "notes": 0}
    files_changed = []
    for path in sorted(CASES_DIR.glob("*.jsonl")):
        counts = fix_file(path, check)
        if any(counts.values()):
            files_changed.append((path.name, counts))
            for k in total:
                total[k] += counts[k]
    print(("would change" if check else "changed"), len(files_changed), "files")
    for name, counts in files_changed:
        print(f"  {name}: {counts}")
    print("totals:", total)
    # assertions: the audited defect counts, verified when fixes are applied.
    # Skipped in --check mode (re-runs on the fixed tree report 0 changes)
    # and when nothing changed.
    if not check and files_changed:
        assert total["article"] == 198, total
        assert total["scorescore"] == 60, total
        assert total["notes"] == 44, total
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
