"""Apply S-1 Sweep A severity re-grades (D-36 defect class 2, annotate).

Reads s1/sweep_a_severity_corrections.json, updates the severity field
and refreshes any stale "Severity <tier>" sentences in case notes.
Skips the 5 class-1/6 cases being retired (handled separately).

Follows the #215 pattern (scripts/apply_s1_severity.py).
"""
import json, glob, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Cases being retired via class-1/6 (not severity-annotated)
RETIRED = {"v1-ngm-107", "v1-ppa-024", "v1-ppa-132", "v1-ppa-141", "v1-ppa-230"}

# Canonical generic descriptions per tier (from existing corpus usage).
GENERIC_DESC = {
    "low": "minimal stakes.",
    "medium": "limited stakes (money/time proportionate).",
    "high": "material stakes (money, safety, rights).",
    "critical": "irreversible / life-safety stakes.",
}

def refresh_notes(notes: str, old: str, new: str) -> str:
    def repl_generic(m):
        return f"Severity {new}: {GENERIC_DESC[new]}"
    notes2 = re.sub(
        r"Severity " + re.escape(old) + r": [^.]*\.",
        repl_generic, notes)
    notes2 = re.sub(
        "Severity: " + re.escape(old) + r"(\s*[-—]\s*)",
        r"Severity: " + new + r"\1", notes2)
    return notes2

def main() -> int:
    corrections = json.load(open(REPO / "s1" / "sweep_a_severity_corrections.json"))
    files = sorted(glob.glob(str(REPO / "dataset" / "v1" / "cases" / "*.jsonl")))
    idx = {}
    for f in files:
        for i, line in enumerate(open(f)):
            c = json.loads(line)
            idx[c["case_id"]] = (f, i, c)

    changed = []
    skipped = []
    for corr in corrections:
        cid, old, new = corr["case_id"], corr["old"], corr["new"]
        if cid in RETIRED:
            skipped.append(cid)
            continue
        f, i, c = idx[cid]
        assert c["severity"] == old, f"{cid}: expected {old}, found {c['severity']}"
        c["severity"] = new
        if c.get("notes"):
            c["notes"] = refresh_notes(c["notes"], old, new)
        changed.append((cid, old, new))

    # Write back surgically
    changed_ids = {cid for cid, _, _ in changed}
    for f in files:
        lines = open(f).readlines()
        out = []
        for line in lines:
            c = json.loads(line)
            if c["case_id"] in changed_ids:
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
    stale = []
    for cid, old, new in changed:
        notes = idx[cid][2].get("notes", "")
        if re.search(r"[Ss]everity[:\s]+" + re.escape(old) + r"\b", notes):
            stale.append(cid)
    print(f"stale notes remaining: {stale}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
