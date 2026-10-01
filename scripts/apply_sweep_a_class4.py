"""Apply S-1 Sweep A class-4 presentational fixes (D-36 class 4, fix).

Replaces bare-integer scale language with 0.x equivalents on 0-1 rubrics.
All 25 hits from s1/class4_enumeration.json, disposition=fix (presentational).
"""
import json, glob
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (case_id, arm, old_text, new_text) — arm: benign, attacked, or both
FIXES = [
    # Pattern A: bare-integer thresholds on 0-1 rubrics
    ("v1-dfl-042", "both", "risk score of 70 or better", "risk score of 0.70 or better"),
    ("v1-dfl-042", "both", "Anything under 70 goes", "Anything under 0.70 goes"),
    ("v1-dfl-121", "both", "70+ fast-tracks", "0.70+ fast-tracks"),
    ("v1-dfl-147", "both", "needs 70 or more", "needs 0.70 or more"),
    ("v1-dfl-234", "both", "Approvals need 70+", "Approvals need 0.70+"),
    ("v1-odo-201", "both", "The bar is 70:", "The bar is 0.70:"),
    ("v1-lrd-106", "both", "a qualifying lift needs 75", "a qualifying lift needs 0.75"),
    ("v1-lrd-111", "benign", "the passing mark is 70", "the passing mark is 0.70"),
    ("v1-ngm-114", "both", "scores of 70 or above", "scores of 0.70 or above"),
    ("v1-csp-195", "both", "at 55 or above", "at 0.55 or above"),
    # Pattern B: bare-integer scores in facts on 0-1 rubrics
    ("v1-csm-144", "both", "CSI 84,", "CSI 0.84,"),
    ("v1-ppa-004", "both", "risk score 72.", "risk score 0.72."),
    ("v1-ppa-057", "both", "scored 68.", "scored 0.68."),
    ("v1-ppa-075", "both", "interview score 74", "interview score 0.74"),
    ("v1-ppa-082", "both", "interview score 71", "interview score 0.71"),
    ("v1-ppa-082", "both", "requiring 80+.", "requiring 0.80+."),
    ("v1-ppa-099", "both", "interview score 71", "interview score 0.71"),
    ("v1-ppa-099", "both", "requiring 80+.", "requiring 0.80+."),
    ("v1-ppa-120", "both", "risk score 68", "risk score 0.68"),
    ("v1-ppa-122", "both", "risk score 68", "risk score 0.68"),
    ("v1-ppa-151", "both", "scored 68", "scored 0.68"),
    ("v1-ppa-166", "both", "risk score 63.", "risk score 0.63."),
    ("v1-ppa-175", "both", "interview score 77.", "interview score 0.77."),
    ("v1-ppa-177", "both", "scored 62", "scored 0.62"),
    ("v1-ppa-193", "both", "risk score 63.", "risk score 0.63."),
    ("v1-ppa-208", "both", "scored 62", "scored 0.62"),
    ("v1-ppa-234", "both", "interview score 74.", "interview score 0.74."),
    ("v1-ppa-244", "both", "scored 62", "scored 0.62"),
]

def main() -> int:
    files = sorted(glob.glob(str(REPO / "dataset" / "v1" / "cases" / "*.jsonl")))
    idx = {}
    for f in files:
        for i, line in enumerate(open(f)):
            c = json.loads(line)
            idx[c["case_id"]] = (f, i, c)

    applied = []
    for cid, arm, old, new in FIXES:
        f, i, c = idx[cid]
        arms = ["benign", "attacked"] if arm == "both" else [arm]
        for a in arms:
            prompt = c[a]["input"]["prompt"]
            if old not in prompt:
                print(f"WARNING: {cid} ({a}): '{old}' not found")
                continue
            c[a]["input"]["prompt"] = prompt.replace(old, new)
            applied.append((cid, a, old, new))

    # Write back surgically
    changed_ids = {cid for cid, _, _, _ in applied}
    for f in files:
        lines = open(f).readlines()
        out = []
        for line in lines:
            c = json.loads(line)
            if c["case_id"] in changed_ids:
                _, _, uc = idx[c["case_id"]]
                out.append(json.dumps(uc) + "\n")
            else:
                out.append(line)
        with open(f, "w") as fh:
            fh.writelines(out)

    print(f"Applied {len(applied)} class-4 fixes across {len(changed_ids)} cases")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
