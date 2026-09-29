"""Apply S-1 bar-decision severity re-grades (D-36 defect class 2, annotate).

Reads s1/bar_decision_run2.json severity_defects, updates the severity field
and refreshes any stale "Severity <tier>" sentences in case notes.
Skips v1-ppa-217 (retired via class-6, not annotated).
"""
import json, glob, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Canonical generic descriptions per tier (from existing corpus usage).
GENERIC_DESC = {
    "medium": "limited stakes (money/time proportionate).",
    "high": "material stakes (money, safety, rights).",
    "critical": "irreversible / life-safety stakes.",
}

def refresh_notes(notes: str, old: str, new: str) -> str:
    # Generic pattern: "Severity <old>: <desc>." -> new tier + new desc.
    def repl_generic(m):
        return f"Severity {new}: {GENERIC_DESC[new]}"
    notes2 = re.sub(
        r"Severity " + re.escape(old) + r": [^.]*\.",
        repl_generic, notes)
    # Specific pattern: "Severity: <old> - <rationale>." / em-dash variant.
    # Keep the case-specific rationale, update only the tier name.
    notes2 = re.sub(
        "Severity: " + re.escape(old) + r"(\s*[-—]\s*)",
        r"Severity: " + new + r"\1", notes2)
    return notes2

def main() -> int:
    bar = json.load(open(REPO / "s1" / "bar_decision_run2.json"))
    sev = bar["severity_defects"]
    files = sorted(glob.glob(str(REPO / "dataset" / "v1" / "cases" / "*.jsonl")))
    idx = {}  # case_id -> (file, lineno, case)
    for f in files:
        for i, line in enumerate(open(f)):
            c = json.loads(line)
            idx[c["case_id"]] = (f, i, c)

    changed = []
    skipped = []
    for s in sev:
        cid, _method, old, new = s[0], s[1], s[2], s[3]
        if cid == "v1-ppa-217":
            skipped.append(cid)  # retired via class-6
            continue
        f, i, c = idx[cid]
        assert c["severity"] == old, f"{cid}: expected {old}, found {c['severity']}"
        c["severity"] = new
        if c.get("notes"):
            c["notes"] = refresh_notes(c["notes"], old, new)
        changed.append((cid, old, new))

    # Write back surgically: only replace the lines for changed cases,
    # preserving every other byte exactly.
    changed_ids = {cid for cid, _, _ in changed}
    for f in files:
        lines = open(f).readlines()
        out = []
        for line in lines:
            c = json.loads(line)
            if c["case_id"] in changed_ids:
                # Find the updated version.
                for cid, old, new in changed:
                    if cid == c["case_id"]:
                        _, _, uc = idx[cid]
                        out.append(json.dumps(uc) + "\n")
                        break
            else:
                out.append(line)
        with open(f, "w") as fh:
            fh.writelines(out)

    print(f"re-graded: {len(changed)}, skipped (retired): {skipped}")
    # Report notes that still mention the old tier (should be none).
    stale = []
    for cid, old, new in changed:
        notes = idx[cid][2].get("notes", "")
        if re.search(r"[Ss]everity[:\s]+" + re.escape(old) + r"\b", notes):
            stale.append(cid)
    print(f"stale notes remaining: {stale}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
