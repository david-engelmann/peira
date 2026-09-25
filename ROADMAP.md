# Peira Roadmap

**Last updated:** 2026-09-24  
**Status:** Pre-launch. No users. Building toward v1.0.

## Why Now

The decision-model category launched September 15, 2026 (TypeSafe AI's Jev, $40M seed). 
No adversarial benchmark exists for decision models. HELM (the previous standard) 
entered maintenance mode June 2026. Vals raised $40M (Sept 2026) for "ungameable 
benchmarks" — validating the anti-gaming thesis. The window is open now.

## v1.0 — The Launch

**Goal:** The definitive adversarial benchmark for decision models.

### Dataset (2,500 cases)
- [x] 10 attack families × 250 cases designed
- [x] 2,000 public + 500 private holdout split
- [ ] Independent audit of all 2,500 cases (in progress)
- [ ] Canonical source frozen, deterministic regeneration
- [ ] Public/private splits sealed with manifests

### Core (Python)
- [x] Schema validation (bool/NaN/inf rejected)
- [x] Runner with resume, dry-run, JSON progress
- [x] Metrics: Wilson CI, ASR, ECE, Brier, McNemar, bootstrap
- [x] Analysis locks (SHA-256, byte-exact)
- [x] `peira verify` CLI command
- [x] HTML report generation (XSS-safe)
- [ ] Custom adapter loading (dotted path) — CLI currently only supports `mock`
- [ ] Adapter timeout enforcement
- [ ] Version compatibility checks

### Core (Rust)
- [x] Metrics ported (Wilson, McNemar, Brier, ECE) — bit-exact parity
- [x] Schema validation ported
- [x] Artifact hashing ported — byte-exact parity
- [ ] PyO3 bindings (Python calls Rust)
- [ ] Runner logic ported
- [ ] Native Adapter trait

### Docs
- [x] False claims purged (drill-down fiction, `peira verify` fiction)
- [x] Severity-Rubric fragment fixed
- [ ] Adapter tutorial (highest-leverage missing doc)
- [ ] API reference
- [ ] Architecture overview
- [ ] README import paths updated
- [ ] CHANGELOG current

## v1.1 — The Jev Play

**Goal:** Publish the first adversarial evaluation of a production decision model.

- [ ] Jev adapter (Choice/Score/Noul → peira primitives)
- [ ] Run full 2,500-case suite against Jev
- [ ] Publish results with analysis locks
- [ ] "State of Decision Robustness" report

**Why:** Jev launched 9 days ago. Zero adversarial research exists. 
TypeSafe admits: "jev-1.13 does not treat state as hostile by default."
First-mover advantage on the defining evaluation.

## v2.0 — The Standard

**Goal:** Peira becomes the default way to evaluate decision robustness.

- [ ] Leaderboard with verified submissions
- [ ] Additional adapters (Shieldstral, ProtectAI, Prompt Guard 2)
- [ ] Monthly "State of Decision Robustness" reports
- [ ] Living dataset (new families as attacks evolve)
- [ ] peiratrial.dev hosted (docs, leaderboard, explorers)

## Non-Goals

- **Not a red-team tool.** We measure; we don't help attack.
- **Not a certification.** Scores measure robustness on this benchmark, not safety.
- **Not backward compatible.** No users yet. Break anything to reach the best end state.

## Decision Log

See `docs/Decisions.md` for architecture decision records.
