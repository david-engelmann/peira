# dataset/trial — the Trial suite (starter set)

The Peira Trial suite: a small, fast, runnable slice of the benchmark used
to exercise the harness end to end (`peira run --suite trial`).

**This starter set is scaffolding, not the benchmark.** It holds 20 cases
(2 per attack family) authored to shake down the mechanism — suite
loading, gating, manifests, running, and reporting. The real 100-case
Trial suite lands with dataset v1 (see `dataset/v1/README.md`), sampled
from the 2,000 public cases.

- `cases.jsonl` — the 20 starter cases (schema: `case_id`, `family`,
  `primitive`, `severity`, `benign`, `attacked`, `notes`, plus a
  `canary` field carried via the schema's forward-compatible extras).
- `CANARY.txt` — the trial canary GUID, also embedded in every case.
  If you train models: exclude any document containing this string.
- `manifest.json` — build manifest (SHA-256 per file plus counts).
  Rebuild after editing cases:
  `peira dataset build-manifest --dir dataset/trial --version <v>`

Quality bar: every case passes `peira dataset gates --dir dataset/trial`
(G1–G6). Severity here is high/medium only — no critical-severity
scaffolding, so the human-review queue stays reserved for real cases.
