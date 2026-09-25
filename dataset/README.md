# dataset/

- `trial-demo/` — 12-case offline demo fixture so the quickstart works with
  zero downloads. Clearly labeled scaffolding; do not build features
  against its exact contents.
- `trial/` — the branded 100-case Peira Trial (10 per family, v1-quality
  pilot, manifest `1.0.1`). Gated and review-sealed; runs stay off the
  leaderboard. See `trial/README.md`.
- `v1/` — the real v1 dataset lands here: 2,000 public cases + 500 private
  holdout (10 attack families × 200), with `DATASHEET.md`, `schema.json`,
  and the canary string. See `v1/README.md`.
- `safety-policy/` — the separate guardrail-native safety suite (starter
  set of 25 cases; not part of v1). See `safety-policy/README.md` and
  D-34.
