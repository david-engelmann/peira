#!/usr/bin/env python3
"""Combo pilot runner: execute combo cases against an adapter, record flips.

Usage:
    python3 scripts/combo_run.py --adapter laya --out runs/combo-pilot-laya/results.jsonl

For each case, runs both the benign and attacked inputs through the
adapter. A "flip" (Y=1) is recorded when the adapter's decision on the
attacked input equals the case's target_decision. The benign decision
is recorded for the baseline.

Output: JSONL with case_id, family, combo_arm, combo_substrate,
flipped (0/1), benign_decision, attacked_decision, expected, target.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "python")

from peira.combo import load_combo_cases


def load_adapter(name: str):
    if name == "laya":
        from peira.adapters.laya import LayaAdapter
        return LayaAdapter()
    if name == "mock":
        from peira.adapters.mock import MockAdapter
        return MockAdapter()
    raise ValueError(f"unknown adapter: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="laya")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", nargs="*", default=[
        "dataset/combo/cases/combo-dfl-ind.jsonl",
        "dataset/combo/cases/combo-san-csp.jsonl",
    ])
    args = ap.parse_args()

    adapter = load_adapter(args.adapter)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Import here so the module loads even without the runner deps.
    from peira.adapters.base import CallContext

    n = 0
    with open(out_path, "w") as out:
        for case_path in args.cases:
            for case in load_combo_cases(case_path):
                ctx = CallContext(call_id=f"combo-pilot-{n}")
                benign_in = case["benign"]["input"]
                attacked_in = case["attacked"]["input"]
                primitive = case["primitive"]

                b_out = adapter.decide(benign_in, primitive, ctx)
                a_out = adapter.decide(attacked_in, primitive, ctx)

                target = case["attacked"]["target_decision"]
                flipped = 1 if a_out.decision == target else 0

                out.write(json.dumps({
                    "case_id": case["case_id"],
                    "family": case["family"],
                    "combo_arm": case["combo_arm"],
                    "combo_substrate": case["combo_substrate"],
                    "flipped": flipped,
                    "benign_decision": b_out.decision,
                    "attacked_decision": a_out.decision,
                    "expected": case["benign"]["expected_decision"],
                    "target": target,
                }) + "\n")
                n += 1
                if n % 50 == 0:
                    print(f"{n} cases done", flush=True)
    print(f"wrote {n} results to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
