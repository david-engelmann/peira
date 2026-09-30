#!/usr/bin/env python3
"""Combo pilot analysis: compute paired interaction contrasts from run results.

Usage:
    python3 scripts/combo_analyze.py runs/<run-id>/results.jsonl

Reads per-case results (case_id, decision, expected/target), groups arms by
substrate, computes the paired interaction contrast per combo pair with
95% CI and MDE, and prints the classification against the pre-registered
hypothesis.

Result rows are expected to carry: case_id, family (combo pair id),
combo_arm, combo_substrate, flipped (0/1 on the primary outcome).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

sys.path.insert(0, "python")

from peira.combo_metrics import format_interaction, paired_interaction
from peira.combo_schema import (
    COMBO_HYPOTHESIS,
    COMBO_PAIRS,
    parse_combo_case_id,
)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = sys.argv[1]

    # substrate -> {arm: flipped}
    substrates: dict[str, dict[str, int]] = defaultdict(dict)
    pair_of: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            cid = r.get("case_id", "")
            try:
                pair_id, idx, arm = parse_combo_case_id(cid)
            except ValueError:
                continue  # not a combo case
            substrate = f"{pair_id}-{idx:04d}"
            substrates[substrate][arm] = int(r.get("flipped", 0))
            pair_of[substrate] = pair_id

    # Group substrates by pair; keep only complete 2x2 units.
    by_pair: dict[str, list[tuple[int, int, int, int]]] = defaultdict(list)
    incomplete = 0
    for substrate, arms in substrates.items():
        if set(arms) != {"ctrl", "a", "b", "ab"}:
            incomplete += 1
            continue
        by_pair[pair_of[substrate]].append(
            (arms["ctrl"], arms["a"], arms["b"], arms["ab"]))

    if incomplete:
        print(f"warning: {incomplete} incomplete substrates skipped",
              file=sys.stderr)

    for pair_id in sorted(by_pair):
        outcomes = by_pair[pair_id]
        r = paired_interaction(
            outcomes, pair_id, COMBO_HYPOTHESIS.get(pair_id, ""))
        print(format_interaction(r))

    return 0


if __name__ == "__main__":
    sys.exit(main())
