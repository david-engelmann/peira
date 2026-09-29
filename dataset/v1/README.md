# dataset v1

The v1 benchmark dataset: 2,000 public cases (10 attack families x 200),
each a paired benign/attacked case isolating one attack's effect on a
decision. The 500-case private holdout is **never** committed here: it
lives encrypted, maintainer-only; only aggregate metrics are published.

## Contents

- `cases.jsonl`: the 2,000 public cases.
- `cases/`: per-family case files (one JSONL per attack family), plus
  `CHANGELOG.json` (pre-seal changelog entries) and `manifest.json`
  (the build manifest: SHA-256 per file plus per-family / per-severity
  counts).

Classifier guardrails are measured by the **separate safety-policy
suite** (`dataset/safety-policy/`), not by v1 - see D-34.

## License

The v1 dataset is licensed under **CC-BY-4.0**. See
[LICENSE-CC-BY-4.0](../../LICENSE-CC-BY-4.0) at the repo root. The
permanent canary (see
[Contamination-Policy](../../docs/Contamination-Policy.md)) marks the
files against training ingestion and is embedded in the v1 case files at
seal time.
