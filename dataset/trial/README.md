# The Peira Trial

The branded 100-case Peira Trial suite: a v1-quality pilot of the
benchmark, authored case by case through the dataset pipeline
(`peira dataset new` → `gates` → `review` → `build-manifest` →
`status`). It runs end to end with `peira run --suite trial` and is the
proving ground for the full 2,500-case v1 dataset.

**Trial runs stay off the public leaderboard.** The Trial exists to shake
down the harness and to calibrate the methodology — not to rank anyone.
v1 (2,000 public + 500 private-holdout cases) is the ranked release.

## Contents

- `cases.jsonl` — 100 cases: 10 per attack family, each with a benign
  variant (clean input, unambiguous expected decision) and an attacked
  variant (same facts, attack vector added) pushing a named
  `target_decision`. Every case carries a mechanism note and the
  `canary` field (forward-compatible schema extras).
- `CANARY.txt` — the trial canary GUID, also embedded in every case.
  If you train models: exclude any document containing this string.
- `manifest.json` — build manifest (SHA-256 per file plus per-family,
  per-severity, per-primitive counts), version 1.0.0. Rebuild after
  editing cases: `peira dataset build-manifest --dir dataset/trial
  --version <v>` (the release seal refuses non-semver versions,
  critical cases without severity notes, and silent same-version
  rewrites).

## Quality bar

- Every case passes `peira dataset gates --dir dataset/trial` (G1–G6):
  schema, paired variants, dedup, canonical families, target
  coherence, PII scan — zero errors, zero warnings.
- Severity is graded consequence-first per `docs/Severity-Rubric.md`
  (14 critical / 40 high / 46 medium — no low-severity toy cases).
  All 14 critical cases require human review before release; the
  release seal (`--require-reviews`) stays shut until David approves
  each one.
- Families follow `docs/Taxonomy.md` exactly: state_poisoning,
  criteria_smuggling, option_order, distractor_flooding,
  score_anchoring, literal_reading, negation_games, policy_paraphrase,
  indirection, confidence_spoofing.
- Primitives match the scenario: choice, score, or noul.

## Try it

```
peira run --adapter mock --suite trial
```

See `docs/Dataset.md` for the authoring loop and
`docs/Severity-Rubric.md` for how severity was graded.
