#!/usr/bin/env python3
"""Regenerate canary_leakage scenarios that used first-person voice.

77 scenarios came back in first person ("I am reviewing..."); the
corpus standard is third person. Case 365 is also redone for a number
drift ("exceeds by 300%" became "three times the limit"). Updates
/tmp/cnl_scenarios.jsonl in place, then re-runs verification.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gen_canary_scenarios import (  # noqa: E402
    BATCH,
    TASK,
    build_ingredients,
    call_api,
    item_prompt,
    parse_batch,
    verify,
)

SCRATCH = REPO_ROOT / ".agent-scratch" / "cnl_scenarios.jsonl"

EXTRA = (" Write in the third person only: never use 'I', 'my', 'we', "
         "or 'our'. Describe the case; do not narrate as the decision "
         "maker.")


def main() -> None:
    items = {it["case_idx"]: it for it in build_ingredients()}
    recs = {}
    for line in SCRATCH.read_text().splitlines():
        r = json.loads(line)
        recs[r["case_idx"]] = r

    redo = [cid for cid, r in recs.items()
            if re.search(r"\bI (compared|recommend|reviewed|am|have|believe|"
                         r"think|found|see)\b", r["scenario"])
            or " my " in r["scenario"].lower()]
    redo.append(365)
    redo = sorted(set(redo))
    print(f"regenerating {len(redo)} scenarios: {redo[:10]}...")

    # canary values for the no-leak check
    import author_canary_leakage as A
    used: dict[str, set[str]] = {k: set() for k in A.KINDS}
    canary_values: set[str] = set()
    for it in items.values():
        _label, value = A.mint_canary(it["kind"], it["seed"], used[it["kind"]])
        canary_values.add(value)

    for i in range(0, len(redo), BATCH):
        chunk = redo[i:i + BATCH]
        user_text = "\n".join(
            item_prompt(items[cid], n + 1) for n, cid in enumerate(chunk)
        ) + "\n" + TASK + EXTRA
        for attempt in range(3):
            try:
                arr = parse_batch(call_api(user_text), len(chunk))
                break
            except Exception as e:  # noqa: BLE001
                print(f"  retry {attempt + 1}: {e}")
                if attempt == 2:
                    raise
        for cid, o in zip(chunk, arr):
            recs[cid] = {"case_idx": cid,
                         "scenario": o["scenario"].strip(),
                         "file_note": o["file_note"].strip()}
        print(f"  redone {i + len(chunk)}/{len(redo)}")

    with open(SCRATCH, "w") as f:
        for cid in sorted(recs):
            f.write(json.dumps(recs[cid]) + "\n")

    ordered_items = [items[cid] for cid in sorted(recs)]
    ordered_recs = [recs[cid] for cid in sorted(recs)]
    problems = verify(ordered_items, ordered_recs, canary_values)
    if problems:
        print(f"{len(problems)} problems remain:")
        for p in problems[:20]:
            print("  -", p)
        sys.exit(1)
    print("verification clean")


if __name__ == "__main__":
    sys.exit(main() or 0)
