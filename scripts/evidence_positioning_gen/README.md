# evidence_positioning corpus generator (family 23)

Deterministic authoring pipeline for the rebuilt `evidence_positioning`
corpus. Replaces the PR #191 corpus, which was held DO NOT MERGE for a P0
corpus-recycling defect (420 rows, only 32 distinct prompt pairs).

## Layout

- `entities.py`: shared entity pools (names, orgs, amounts, ...) and
  deterministic draw helpers.
- `g_critical.py`: 80 critical cases (60 choice / 10 abstain / 10 score).
- `g_high.py`: 100 high cases (75 choice / 13 abstain / 12 score).
- `g_medium.py`: 240 medium cases (180 choice / 30 abstain / 30 score).
- `generate.py`: assembles the 420-row corpus and enforces the
  construction invariants as hard assertions.

## Construction

Each scenario yields a paired case:

- **benign** evidence order: `[E1, T1, E2, T2, E3, T3]` (alternating)
- **attacked** evidence order: `[T1, E1, E2, E3, T2, T3]` (target-supporting
  evidence leads and closes; expected-supporting facts buried centrally)

Both arms use the identical six fact strings; only the order changes.
Options are sorted and identical across arms.

## Invariants (asserted, not documented)

- 420 rows; 420 distinct (benign, attacked) prompt pairs
- 420 distinct benign prompts; 420 distinct attacked prompts
- severity mix exactly 80 critical / 100 high / 240 medium
- primitive mix exactly 315 choice / 53 abstain / 52 score
- attacked arm leads AND closes with target-supporting evidence
- byte-identical fact multisets between arms; 6 distinct facts per case
- sorted, unique options; arm-identical options
- no em dashes / non-ASCII in prompts

## Usage

Run from the repository root (deterministic, seed-pinned):

```
python3 scripts/evidence_positioning_gen/generate.py \
    [output.jsonl]   # default: dataset/v2/cases/evidence_positioning.jsonl
```

Any invariant violation raises `AssertionError` and writes nothing.
