"""S-1 class-4 label fixes (D-36, presentational).

v1-odo-106: prompt labels "paid-repair" -> "paid" (both arms) to match
  the schema options ['abstain', 'paid', 'warranty-queue'].
v1-odo-003: prompt labels "transplant-team" -> "transplant" (both arms)
  to match the schema options ['abstain', 'hepatology-clinic', 'transplant'].

Follows the v1-odo-208 precedent (1.1.0): prompt labels change to match
options; descriptions and correct answers unchanged.
"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "dataset" / "v1" / "cases"

FIXES = {
    # case_id: (old_label_fragment, new_label_fragment)
    "v1-odo-106": (") paid-repair — ", ") paid — "),
    "v1-odo-003": (". transplant-team — ", ". transplant — "),
}


def main() -> int:
    path = CASES / "option_order.jsonl"
    lines = open(path).readlines()
    out = []
    n = 0
    for line in lines:
        c = json.loads(line)
        cid = c["case_id"]
        if cid in FIXES:
            old, new = FIXES[cid]
            for arm in ("benign", "attacked"):
                prompt = c[arm]["input"]["prompt"]
                assert old in prompt, f"{cid}/{arm}: label not found"
                c[arm]["input"]["prompt"] = prompt.replace(old, new)
            n += 1
            out.append(json.dumps(c) + "\n")
        else:
            out.append(line)
    assert n == len(FIXES), f"fixed {n}, expected {len(FIXES)}"
    with open(path, "w") as fh:
        fh.writelines(out)
    print(f"fixed labels in {sorted(FIXES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
