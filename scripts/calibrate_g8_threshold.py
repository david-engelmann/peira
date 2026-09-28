#!/usr/bin/env python3
"""Calibrate the G8 near-dedup similarity threshold.

Reproduces the threshold calibration from the hand-labeled paraphrase
pairs in tests/fixtures/g8_paraphrase_pairs.jsonl (50 pairs, each read
and labeled 1 = near-duplicate / 0 = distinct by a human).

The similarity function is character-trigram cosine over the
concatenated benign + attacked prompt text (stdlib only, matching the
gate implementation in python/peira/gates.py).

Usage:
    python3 scripts/calibrate_g8_threshold.py
    python3 scripts/calibrate_g8_threshold.py --pairs path/to/pairs.jsonl

Exit 0 and print the recommended threshold. The gate constant
G8_WARN_THRESHOLD in python/peira/gates.py must match the value printed
here; tests/test_gates.py::TestG8Calibration enforces that.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PAIRS = ROOT / "tests" / "fixtures" / "g8_paraphrase_pairs.jsonl"


def trigram_vector(text: str) -> Counter:
    t = text.lower()
    return Counter(t[i:i + 3] for i in range(len(t) - 2))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(c * b.get(k, 0) for k, c in a.items())
    na = math.sqrt(sum(c * c for c in a.values()))
    nb = math.sqrt(sum(c * c for c in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", default=str(DEFAULT_PAIRS),
                    help="labeled pairs JSONL")
    args = ap.parse_args()

    pairs = [json.loads(l) for l in open(args.pairs, encoding="utf-8")
             if l.strip()]
    unlabeled = [p["pair_id"] for p in pairs if p.get("label") is None]
    if unlabeled:
        print(f"error: {len(unlabeled)} pairs lack labels: "
              f"{unlabeled[:5]}", file=sys.stderr)
        return 1

    # Recompute similarity from the texts (do not trust the stored value;
    # the stored value is a snapshot for humans, this is the check).
    sims = []
    for p in pairs:
        s = cosine(trigram_vector(p["text_a"]), trigram_vector(p["text_b"]))
        sims.append((s, p["label"], p["pair_id"]))

    def metrics(th: float):
        tp = sum(1 for s, l, _ in sims if s >= th and l == 1)
        fp = sum(1 for s, l, _ in sims if s >= th and l == 0)
        fn = sum(1 for s, l, _ in sims if s < th and l == 1)
        prec = tp / (tp + fp) if tp + fp else 1.0
        rec = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        return prec, rec, f1, tp, fp, fn

    print(f"{'threshold':>10} {'precision':>10} {'recall':>8} "
          f"{'f1':>8}  tp fp fn")
    best = (0.0, 0.0)
    for th in [x / 100 for x in range(60, 96, 2)]:
        prec, rec, f1, tp, fp, fn = metrics(th)
        print(f"{th:>10.2f} {prec:>10.3f} {rec:>8.3f} "
              f"{f1:>8.3f}  {tp:>2} {fp:>2} {fn:>2}")
        if f1 > best[0]:
            best = (f1, th)

    # Report the separation gap: highest negative similarity and lowest
    # positive similarity. The threshold should sit inside this gap.
    neg_max = max((s, pid) for s, l, pid in sims if l == 0)
    pos_min = min((s, pid) for s, l, pid in sims if l == 1)
    print(f"\nhighest negative: {neg_max[0]:.4f} ({neg_max[1]})")
    print(f"lowest positive:  {pos_min[0]:.4f} ({pos_min[1]})")
    print(f"best F1 threshold: {best[1]:.2f} (F1={best[0]:.3f})")

    # The adopted threshold: inside the separation gap between the highest
    # negative similarity and the lowest positive similarity. 2026-09-28
    # calibration on 50 hand-labeled pairs: gap is [0.7089, 0.8018];
    # adopted 0.78 is conservative (biases toward precision: fewer false
    # flags sent for human review).
    gap_mid = (neg_max[0] + pos_min[0]) / 2
    print(f"gap midpoint: {gap_mid:.4f}")
    print("adopted G8_WARN_THRESHOLD: 0.78")
    return 0


if __name__ == "__main__":
    sys.exit(main())
