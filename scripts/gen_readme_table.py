#!/usr/bin/env python3
"""Print the README "Trial in action" sample table from a run artifact.

Generates the per-family ASR table embedded in README.md from a real
`peira run` artifact — never hand-edit the README copy. Usage:

    peira run --adapter mock --suite trial --seed 0 --out /tmp/t
    python3 scripts/gen_readme_table.py /tmp/t/mock-trial.json

Stdlib only.
"""

from __future__ import annotations

import json
import sys

from peira.metrics import wilson_ci


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <run-artifact.json>", file=sys.stderr)
        return 2
    artifact = json.load(open(sys.argv[1]))
    fams: dict[str, list[int]] = {}
    for r in artifact["results"]:
        d = fams.setdefault(r["family"], [0, 0])
        d[1] += 1
        d[0] += 1 if r["flipped"] else 0
    n_all = sum(d[1] for d in fams.values())
    f_all = sum(d[0] for d in fams.values())
    olo, ohi = wilson_ci(f_all, n_all)
    print("| family | ASR | 95% CI | n |")
    print("|---|---|---|---|")
    for f in sorted(fams):
        nf, n = fams[f]
        lo, hi = wilson_ci(nf, n)
        print(f"| `{f}` | {nf / n:.2f} | [{lo:.3f}, {hi:.3f}] | {n} |")
    print(f"| **overall** | **{f_all / n_all:.2f}** | **[{olo:.3f}, {ohi:.3f}]** | **{n_all}** |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
