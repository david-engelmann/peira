# Combo suite: family-combination attacks

**Status.** Pilot phase. Two pairs ship: `combo-dfl-ind`
(distractor_flooding x indirection) and `combo-san-csp`
(score_anchoring x confidence_spoofing), 100 substrates x 4 arms = 400
cases each (800 total).

## What this is

peira measures attack families in isolation. Real attackers combine
techniques. The combo suite measures **interaction effects** between
family pairs: when two attack mechanisms are applied to the same case,
is the combined effect super-additive (synergy), additive
(independent), or sub-additive (redundancy)?

This is a **separate suite**, not v1/v2 families: separate schema,
separate gates, separate versioning, separate leaderboard tab. Combo
numbers never blend into family ASRs. The design is
`research_notes/family-intersections-20260928.md`.

## The 2x2 factorial unit

Every substrate (a fresh benign decision case, authored for this suite)
yields four arms:

| Arm | Construction |
|---|---|
| `ctrl` | benign case as authored |
| `a` | benign + family A's transformation |
| `b` | benign + family B's transformation |
| `ab` | benign + both (A applied first, then B) |

The interaction contrast:

```
interaction = flip(ab) - flip(a) - flip(b) + flip(control)
```

computed per substrate and averaged (paired analysis). Classification
uses the additive null with a CI-excludes-zero rule; "unresolved" when
the MDE floor is not met. Primary outcome is registered per pair
(`flip` for both pilot pairs).

## Case IDs and files

- IDs: `combo-<a>-<b>-NNNN-<arm>` (e.g. `combo-dfl-ind-0042-ab`)
- Family field: the pair id (e.g. `combo-dfl-ind`)
- Files: `dataset/combo/cases/combo-dfl-ind.jsonl`,
  `dataset/combo/cases/combo-san-csp.jsonl`
- Manifest: `dataset/combo/cases/manifest.json` (combo schema v1.0.0)

## Pilot pairs

1. **combo-dfl-ind** (distractor_flooding x indirection). The burial:
   flooding degrades the reasoning budget; indirection forces multi-hop
   resolution that consumes budget. Pre-registered hypothesis:
   **super-additive**.
2. **combo-san-csp** (score_anchoring x confidence_spoofing). Negative
   control: both attack the score/confidence surface (L4 x L4).
   Pre-registered hypothesis: **sub-additive** (redundancy).

## Construction rules (design 6b)

1. Same substrate across arms. Never reuse existing single-family cases.
2. Transformation order fixed (A then B, alphabetical); recorded in
   `transform_order`.
3. Benign arm must stay benign; defective substrates excluded.
4. Separate namespace and versioning (`dataset/combo/`).

## Running the pilot

```bash
# Authoring gates
python3 -m peira.combo_gates dataset/combo/cases/*.jsonl

# Run all four arms through the standard runner (each arm is an
# ordinary case; the 2x2 structure is recovered at analysis time)
peira run --dataset dataset/combo/cases --adapter <name>

# Interaction analysis (paired contrast + CI + MDE)
python3 scripts/combo_analyze.py runs/<run-id>/results.jsonl
```
