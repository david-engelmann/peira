# A11b: Independent P0/P1 Re-verification Report

**Date:** 2026-09-30
**Base:** origin/main @ `12744b8c` (PR #258)
**Scope:** All 41 P0/P1 findings from the A11a disposition matrix (`docs/audit-dispositions.json`), re-verified independently against current main without trusting A11a's claims.

## Method

Each item was checked mechanically against the current tree: string presence/absence in docs, test file contents, CI workflow contents, JSONL case data, and behavioral execution where applicable (CLI error strings, test suite runs). The silent-deletion incidents of 2026-09-30 (PR #238 clobbering metrics.py, PR #239 clobbering R-12 CLI flags) motivated checking every item against the CURRENT main head rather than the A11a evidence commits.

## Result: 41/41 verified clean. Zero fix-forwards required.

### P0 items (5/5)

| ID | Title | Verdict | How verified |
|----|-------|---------|--------------|
| D-P0-1 | Abstention semantics wrong in five places | VERIFIED | All five files (Concepts.md, Taxonomy.md, Glossary.md, README.md, Methodology.md) state attack-induced abstention counts as a flip. D-23 carries the amendment note in Decisions.md. |
| D-P0-2 | False '95% CIs on every number' tagline | VERIFIED | The false string appears in none of README.md, docs/CLI.md, pyproject.toml, python/peira/cli.py, crates/peira-core/Cargo.toml, scripts/generate_social_preview.py. README.md now reads 'Wilson 95% confidence intervals on reported rates'. |
| D-P0-3 | Artifact-Versions claims peira validate verifies artifacts | VERIFIED | docs/Artifact-Versions.md states peira validate is dataset-only, no migrate-artifact mandated, verification documented as peira runs verify. |
| T-P0-1 | Dishonest ShieldGemma test | VERIFIED (stale) | No ShieldGemma test file remains in tests/. The dishonest test is gone, not merely fixed. |
| v1-ind-214 | Unfounded golds, score-scale mismatch | VERIFIED | v1-ind-214 absent from dataset/v1/cases. Replacement v1-ind-251 present in indirection.jsonl. |

### P1 items (36/36)

| ID | Title | Verdict | How verified |
|----|-------|---------|--------------|
| D-P1-1 | Dataset.md phantom files, stale 1.0.4 | VERIFIED | No 1.0.4 pin. Real layout (dataset/v1/cases) described. |
| D-P1-2 | Dataset-Changelog stale | VERIFIED | v1 1.0.3 stated, D-34 references present. |
| D-P1-3 | FAQ/Hardware 'planned' adapters, phantom 27B | VERIFIED | Exactly one 'planned' occurrence (the design statement). No 27B tier. |
| D-P1-4 | README adapter table incomplete | VERIFIED | Qwen3Guard, Granite, ShieldGemma, WildGuard, Lakera all listed. |
| D-P1-5 | FAQ '~5,000' denominator | VERIFIED | No '5,000' string in docs/FAQ.md. |
| D-P1-6 | Troubleshooting error strings mismatch CLI | VERIFIED | All four documented error strings present in docs/Troubleshooting.md. Behavioral check: actual CLI output for unknown adapter matches the documented string exactly. |
| D-P1-7 | D-6 mislabels exit code 2 | VERIFIED | D-6 amendment note present, correcting to infrastructure error. |
| D-P1-8 | Methodology.md stale NaN line | VERIFIED | Type-level insufficiency stated (delta=None, ci=None, sufficient=False). |
| D-P1-9 | Glossary 'abstain' too narrow | VERIFIED | Deliberate abstention distinguished from provider refusal; attack-induced abstention counts as a flip. |
| D-P1-10 | Concepts.md analysis lock only 'the hash' | VERIFIED | Full '## 3. Analysis lock' section present. |
| D-P1-11 | README false accuracy-benchmark claim | VERIFIED | Conflation specified: accuracy benchmarks do not catch attack-driven flips. |
| T-P1-1 | No exact exit-3 test | VERIFIED | tests/test_cli_exit_codes.py asserts exit 3. Test run (exit-codes + hf-adapters + rust-parity): 139 passed, 3 skipped. |
| T-P1-2 | No real-tokenizer contract test | VERIFIED | tests/test_hf_adapters.py pins greedy single-token contract. Tests green. |
| T-P1-3 | D-11 no validation | VERIFIED | tests/test_rust_execution_parity.py compares against _py reference implementations. Tests green. |
| C-P1-1 | No clippy/fmt in CI | VERIFIED | .github/workflows/ci.yml runs cargo clippy and cargo fmt --check. |
| C-P1-2 | Adapter-score PR-comment promise | VERIFIED | No adapter-score promise in ci.yml. |
| C-P1-3 | DCO unenforced | VERIFIED | DCO job present in ci.yml, requires Signed-off-by on every non-merge commit. |
| C-P1-4 | No version-bump guard | VERIFIED | check_dataset_version_bump.py referenced in ci.yml. |
| R-P1-1 | Roadmap references #110/#111 | VERIFIED (stale) | No #110/#111 references in GOAL.md. |
| R-P1-2 | Roadmap item for #112 stale | VERIFIED (stale) | Stale item gone after GOAL.md rewrite. |
| R-P1-3 | PR #114 untracked | VERIFIED (stale) | Finding no longer applies. |
| R-P1-4 | PR #116 untracked | VERIFIED (stale) | Finding no longer applies. |
| R-P1-5 | Lane-4 status reference stale | VERIFIED (stale) | Finding no longer applies. |
| R-P1-6 | Retro-closure hides lane status | VERIFIED (stale) | Finding no longer applies. |
| v1-csp-064 | Severity under-graded (high to critical) | VERIFIED | severity=critical in confidence_spoofing.jsonl. |
| v1-csp-166 | Severity under-graded (high to critical) | VERIFIED | severity=critical in confidence_spoofing.jsonl. |
| v1-csp-213 | Severity under-graded (medium to high) | VERIFIED | severity=high in confidence_spoofing.jsonl. |
| v1-csm-060 | Severity under-graded (high to critical) | VERIFIED | severity=critical in criteria_smuggling.jsonl. |
| v1-spo-106 | Severity under-graded (medium to high) | VERIFIED | severity=high in state_poisoning.jsonl. |
| O-1 | Runner/CLI security posture undocumented | VERIFIED | docs/Threat-Model.md documents timeout (300s), rlimits, in-process import and API key decisions. |
| O-2 | False CI claim in pyproject.toml | VERIFIED | No false claim in pyproject.toml. |
| O-3 | adapters/README duplicates promise | VERIFIED | No adapter-score promise in adapter READMEs. |
| M-1 | False 'zero em dashes' verification | VERIFIED | scripts/check_no_emdashes.py runs in CI. |
| M-2 | Unjustified 50-case generalization | VERIFIED | D-36 policy present in Decisions.md. |
| M-3 | Mis-scoped fix plan | VERIFIED | Process item; revised plan executed per matrix. |
| M-4 | Insufficient closure criteria | VERIFIED | Process item; this report is the A11b half of the closure criteria. |

## Notes

- The six roadmap (R-P1-*) and one tests (T-P0-1) items are dispositioned 'stale' in A11a, meaning the finding no longer applies rather than a fix landing. Re-verification confirmed the stale status holds on current main.
- No silent-deletion regressions were found in any A11a-fixed area despite the 2026-09-30 clobber incidents affecting metrics.py and cli.py.
- P2/P3 items (39 rows) are out of scope for A11b per the lane definition.
