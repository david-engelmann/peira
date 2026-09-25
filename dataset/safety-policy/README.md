# dataset/safety-policy/

The **peira safety suite** — a separate guardrail-native benchmark suite, not
part of the v1 decision-model dataset. See D-34 (`docs/Decisions.md`) for why
it is separate: the metrics are not comparable with v1's (ASR reads as the
*attacker's* success rate here), the adapter contract is guardrail-native
(`allow` / `block` verdicts, no D-23 veto mapping), and the two directions
(evade vs. over-refuse) must be reported separately, never blended.

**Status:** starter set — 25 cases (`cases/safety_policy.jsonl`,
`v1-spy-001`…`v1-spy-025`), growing on its own timeline with its own holdout.
Not sealed; not leaderboard-eligible until it reaches suite maturity.

**Contents:**

- `cases/safety_policy.jsonl` — the 25 starter cases. Every case carries
  explicit unmarked `options` in both arms (B2 backfill): `["allow",
  "block"]` for choice cases, `["abstain", "allow", "block"]` for abstain
  cases. Schema: `case_id, family, primitive, severity, benign, attacked,
  notes, harm_category`.
- `SPEC.md` — the suite specification: decision space, label vocabulary,
  the two attack directions, coarse-equivalence scoring rule, and open
  questions.
- `manifest.json` — the build manifest: SHA-256 per file plus
  per-primitive / per-severity / per-direction counts. Built with
  `peira dataset build-manifest --dir dataset/safety-policy --version <v>`;
  verified with `peira dataset verify-manifest --dir
  dataset/safety-policy`. See `docs/Dataset.md`.

**Shared machinery:** the suite runs on the same runner, JSONL protocol,
primitives, gates, artifact format, and report tooling as v1. A separate
suite is a second manifest + suite entry + leaderboard view, not a second
benchmark. One product, two tabs, zero blended numbers.

**Not in v1:** these cases are excluded from the v1 manifest, the v1
leaderboard, and v1 holdout accounting. `peira run --suite v1` (when v1
lands as a runnable suite) will not see them.
