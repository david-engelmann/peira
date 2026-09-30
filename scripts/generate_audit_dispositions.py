#!/usr/bin/env python3
"""Generate the A11a audit-disposition matrix: docs/audit-dispositions.md + .json.

Single canonical data source. The Markdown table and the JSON companion are
both rendered from FINDINGS below; edit the data, re-run, commit both.
"""

import json
import subprocess
import sys

# Disposition vocabulary (metareview closure standard + task wording):
#   fixed         - remediated on main; evidence cites a merged commit reachable from main
#   stale         - the finding no longer applies; evidence explains why (with proof)
#   rejected      - will not fix; evidence gives the reasoning
#   deferred      - valid but not yet addressed; evidence names the owning lane/PR
#   accepted-risk - valid but consciously accepted; evidence gives rationale + owner
#   unverified    - evidence could not be verified; never assert a fix without proof

FINDINGS = [
    # ---------------------------------------------------------------- docs ---
    dict(id="D-P0-1", track="docs", severity="P0",
         title="Abstention semantics wrong in five places. D-19/D-23 contradict the rule",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="Concepts.md, Taxonomy.md, Glossary.md, README.md, Methodology.md now state attack-induced abstention IS a flip. Decisions.md D-23 carries the amendment note (line 673).",
         verifier="grep abstention semantics across the five files on main@2d234e6"),
    dict(id="D-P0-2", track="docs", severity="P0",
         title="False '95% CIs on every number' tagline",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="Cross-cutting sweep. README.md line 187 now reads 'Wilson 95% confidence intervals on reported rates'. No '95% confidence intervals on every number' string remains in README.md, docs/CLI.md, pyproject.toml, python/peira/cli.py, crates/peira-core/Cargo.toml, scripts/generate_social_preview.py.",
         verifier="repo-wide grep for the false claim on main@2d234e6"),
    dict(id="D-P0-3", track="docs", severity="P0",
         title="Artifact-Versions claims peira validate verifies artifacts and mandates peira migrate-artifact",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Artifact-Versions.md now states peira validate is dataset-only and does not recompute metrics. No migrate-artifact is mandated. Artifact verification is documented as peira runs verify.",
         verifier="grep 'dataset-only' in docs/Artifact-Versions.md on main@2d234e6. grep migrate-artifact returns zero hits"),
    dict(id="D-P1-1", track="docs", severity="P1",
         title="Dataset.md cites phantom files and stale version 1.0.4",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Dataset.md describes the real layout (dataset/v1/cases, peira-cli validate/verify-manifest) and no longer pins phantom files or a stale version.",
         verifier="read docs/Dataset.md on main@2d234e6"),
    dict(id="D-P1-2", track="docs", severity="P1",
         title="Dataset-Changelog stale on v1 seal status, checklist, and version rules",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Dataset-Changelog.md now states v1 holds 6 pre-seal entries at version 1.0.3. The B2 backfill and safety-policy checklist items are marked done with D-34 references. The retire rule matches the 1.1.0 entries.",
         verifier="grep '6 pre-seal entries' in docs/Dataset-Changelog.md on main@2d234e6"),
    dict(id="D-P1-3", track="docs", severity="P1",
         title="FAQ/Hardware promise 'planned' adapters. Hardware.md claims phantom 27B tier",
         disposition="fixed", fix_pr="#190", evidence_commit="62abcf0",
         evidence="docs/FAQ.md and docs/Hardware.md rewritten. Only 'planned leaderboard will keep one row' (a design statement) mentions 'planned'. No 27B tier claim.",
         verifier="grep planned/27B in docs/FAQ.md docs/Hardware.md on main@2d234e6"),
    dict(id="D-P1-4", track="docs", severity="P1",
         title="README adapter table incomplete (missing Qwen3Guard, Granite, ShieldGemma, WildGuard)",
         disposition="fixed", fix_pr="#190", evidence_commit="62abcf0",
         evidence="README.md adapter table now lists Qwen3Guard-Gen 4B, Granite Guardian 4.1 8B, ShieldGemma 2B, WildGuard, Lakera Guard with shipped/not-measured status.",
         verifier="grep adapter names in README.md on main@2d234e6"),
    dict(id="D-P1-5", track="docs", severity="P1",
         title="FAQ claims '~5,000' denominator without support",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="No '5,000' string in docs/FAQ.md.",
         verifier="grep 5,000 in docs/FAQ.md on main@2d234e6"),
    dict(id="D-P1-6", track="docs", severity="P1",
         title="Troubleshooting error strings do not match the CLI",
         disposition="fixed", fix_pr="#190", evidence_commit="62abcf0",
         evidence="docs/Troubleshooting.md now quotes the four exact error strings. The cargo backticks, the -- prefix and (got N) on the concurrency flags, and the available lists on unknown adapter and suite all match the CLI code.",
         verifier="diff the four quoted strings against cli.py and build_core_ext.py on main@2d234e6"),
    dict(id="D-P1-7", track="docs", severity="P1",
         title="D-6 mislabels exit code 2 as usage (actually infrastructure error)",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Decisions.md D-6 carries an amendment note correcting the exit 2 label from usage to infrastructure error (EXIT_INFRA_ERROR). The historical record is preserved with the correction.",
         verifier="grep 'Amendment' near D-6 in docs/Decisions.md on main@2d234e6"),
    dict(id="D-P1-8", track="docs", severity="P1",
         title="Methodology.md stale NaN line contradicts S9 nonfinite rejection",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Methodology.md line 328-330 now states insufficiency is explicit at the type level (delta=None, ci=None, sufficient=False), never a NaN. Nonfinite hardening section documents the ValueError/panic policy.",
         verifier="grep NaN in docs/Methodology.md on main@2d234e6"),
    dict(id="D-P1-9", track="docs", severity="P1",
         title="Glossary 'abstain' too narrow (omits deliberate abstention)",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Glossary.md abstain entry now distinguishes deliberate model abstention (abstained=True, refusal_reason=None) from provider refusal, and states attack-induced abstention counts as a flip.",
         verifier="read Glossary abstain entry on main@2d234e6"),
    dict(id="D-P1-10", track="docs", severity="P1",
         title="Concepts.md describes the analysis lock only as 'the hash'",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="docs/Concepts.md now has a full '## 3. Analysis lock' section.",
         verifier="grep analysis lock in docs/Concepts.md on main@2d234e6"),
    dict(id="D-P1-11", track="docs", severity="P1",
         title="README falsely claims accuracy benchmarks cannot catch wrong approvals",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="README.md now specifies that accuracy benchmarks do not catch attack-driven flips (the conflation of always-wrong with flipped-under-attack). The false absolute claim is gone.",
         verifier="grep 'attack-driven flips' in README.md on main@2d234e6"),
    dict(id="D-P2-1", track="docs", severity="P2",
         title="SEO terms missing from README and Overview",
         disposition="fixed", fix_pr="#190", evidence_commit="62abcf0",
         evidence="README.md and docs/Overview.md now use 'decision robustness', 'adversarial robustness', 'decision model', 'AI safety stress-test', and 'LLM-as-judge'. Searchable terms present.",
         verifier="grep SEO terms in README.md docs/Overview.md on main@2d234e6"),
    dict(id="D-P2-3", track="docs", severity="P2",
         title="Terminology drift and unverified model IDs in Adapters.md",
         disposition="fixed", fix_pr="#120", evidence_commit="360e7d3",
         evidence="docs/Adapters.md uses exact model IDs and pinned revisions (e.g. google/shieldgemma-2b at d1dffc9c8c9237a90aab09c61383791e718ef9e8). Delegated to the API-pin repair lane. Landed via the pinned-models methodology layer.",
         verifier="grep model IDs/revisions in docs/Adapters.md on main@2d234e6"),
    dict(id="D-P3-1", track="docs", severity="P3",
         title="D-P3-1, Adapters.md orphan fragment (error not a silent mismeasurement)",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="The sentence is now complete. It reads 'This is a docs + pricing entry only' followed by 'do not run it on the current adapter shapes.'",
         verifier="read docs/Adapters.md around line 195 on main@2d234e6"),
    dict(id="D-P3-2", track="docs", severity="P3",
         title="Overview.md '15-line snippet' line count",
         disposition="rejected", fix_pr=None, evidence_commit=None,
         evidence="Rejected. The source verified the snippet is 15 lines including blanks and 14 code lines, which is accurate enough for a 15-line claim. No defect exists. Flagged in triage and downgraded on recount.",
         verifier="source docs.md P3-2 explicitly states accurate enough"),
    dict(id="D-P3-3", track="docs", severity="P3",
         title="Troubleshooting.md line 84 resume advice omits the filename suffix",
         disposition="fixed", fix_pr="#190", evidence_commit="62abcf0",
         evidence="docs/Troubleshooting.md now names the file. It says 'delete the <adapter>-<suite>.partial.json file and re-run without --resume'.",
         verifier="read Troubleshooting resume section on main@2d234e6"),
    dict(id="D-P3-4", track="docs", severity="P3",
         title="SemIf URL case inconsistency (SemIf vs semif)",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="Consistently github.com/theoleecj/semif (lowercase) in docs/Adapters.md line 479 and docs/Decisions.md line 1104.",
         verifier="grep semif URL case in docs on main@2d234e6"),
    # ---------------------------------------------------------------- tests --
    dict(id="T-P0-1", track="tests", severity="P0",
         title="Dishonest ShieldGemma test (fake logits asserted as real measurements)",
         disposition="stale", fix_pr="#116", evidence_commit="1b94847",
         evidence="PR #116 replaced the dishonest ShieldGemma test with honest mechanism tests. The P0 as stated no longer applies. The smaller fake-tokenizer hardening remainder was carried and fixed by PR #143 (harden _FakeTokenizer.get_vocab against impossible multi-token vocab ids).",
         verifier="git show 1b94847 (retro-docs-batch-r2). Test_hf_adapters.py on main@2d234e6"),
    dict(id="T-P1-1", track="tests", severity="P1",
         title="No exact exit-3 test (only message assertions)",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="tests/test_cli_exit_codes.py asserts exit 3 exactly for ineligible runs (unit test. cmd_run maps ranking_eligible=False to exit 3. End-to-end families-subset).",
         verifier="grep exit 3 in tests/test_cli_exit_codes.py on main@2d234e6"),
    dict(id="T-P1-2", track="tests", severity="P1",
         title="No real-tokenizer contract test (HF prompt format is load-bearing)",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="tests/test_hf_adapters.py pins the generation contract (exactly one greedy token) and spaced-first lookup order against the real SentencePiece behavior.",
         verifier="grep generation contract in tests/test_hf_adapters.py on main@2d234e6"),
    dict(id="T-P1-3", track="tests", severity="P1",
         title="D-11 has no validation (no-Rust runs skip parity with no recorded comparison)",
         disposition="fixed", fix_pr="#125", evidence_commit="6f0a633",
         evidence="tests/test_rust_execution_parity.py now compares public dispatched functions against _xxx_py reference implementations, passing with or without the Rust core. The docstring documents both-backend coverage. Delegated to the retro-107 repair lane.",
         verifier="read test_rust_execution_parity.py docstring on main@2d234e6"),
    dict(id="T-P2-1", track="tests", severity="P2",
         title="Tautological test (the one honest test asserts nothing)",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="The lone-surrogate case now pins the exact digest of the reference implementation instead of comparing a value to itself.",
         verifier="read test_rust_execution_parity.py cache_key validation on main@2d234e6"),
    dict(id="T-P2-2", track="tests", severity="P2",
         title="_FlippingClassifier tests the adapter, not the mechanism",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="The _FlippingClassifier fake now branches on an attack marker in the input text. The test asserts benign == other and attacked == abstain, verifying the actual flip.",
         verifier="read _FlippingClassifier in test_adapter_runner_integration.py on main@2d234e6"),
    dict(id="T-P2-3", track="tests", severity="P2",
         title="No conflicting-logit precedence tests (Qwen3Guard/Shieldstral spaced-first is load-bearing)",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="tests/test_hf_adapters.py has spaced-first precedence tests for Qwen3Guard and Shieldstral.",
         verifier="grep spaced-first in tests/test_hf_adapters.py on main@2d234e6"),
    dict(id="T-P3-1", track="tests", severity="P3",
         title="Bare asserts in test_doctor (unittest convention violation)",
         disposition="deferred", fix_pr=None, evidence_commit=None,
         evidence="Not addressed. tests/test_doctor.py still uses bare assert in TestCase methods (zero self.assert calls) on main@2d234e6. Owning lane is test-hygiene (PR-3 follow-up). Trivial style nit. No correctness impact.",
         verifier="grep assert in tests/test_doctor.py on main@2d234e6"),
    dict(id="T-P3-2", track="tests", severity="P3",
         title="No-Rust parity is vacuous (skips, nothing asserted about the Python fallback)",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="test_rust_execution_parity.py docstring documents that the suite validates the Python fallback with or without the Rust core.",
         verifier="read test_rust_execution_parity.py docstring on main@2d234e6"),
    dict(id="T-P3-3", track="tests", severity="P3",
         title="Anthropic forced-tool_choice contradicts the API docs (forward-compat)",
         disposition="deferred", fix_pr=None, evidence_commit=None,
         evidence="Not yet rewritten. python/peira/adapters/llm.py still uses forced tool_choice. The docstring records native output_config.format structured outputs as the decided migration direction. Waiting on the output_config.format migration.",
         verifier="grep tool_choice in python/peira/adapters/llm.py on main@2d234e6"),
    # ------------------------------------------------------------------- ci --
    dict(id="C-P1-1", track="ci", severity="P1",
         title="No clippy/fmt in CI",
         disposition="fixed", fix_pr="#119", evidence_commit="959b079",
         evidence=".github/workflows/ci.yml runs cargo clippy --workspace --all-targets -- -D warnings and cargo fmt --all -- --check (lines 151-153).",
         verifier="grep clippy/fmt in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P1-2", track="ci", severity="P1",
         title="Adapter-score PR-comment promise cannot be true (no such workflow)",
         disposition="fixed", fix_pr="#139", evidence_commit="4317b26",
         evidence="Decision was to delete the promise. No adapter-score comment promise remains in .github/workflows/ci.yml or adapters/README.md.",
         verifier="grep adapter-score promise in ci.yml/adapters/README.md on main@2d234e6"),
    dict(id="C-P1-3", track="ci", severity="P1",
         title="DCO unenforced (Contributing demands sign-off, nothing checks it)",
         disposition="fixed", fix_pr="#139", evidence_commit="4317b26",
         evidence=".github/workflows/ci.yml has a DCO job requiring Signed-off-by on every PR commit (line 102).",
         verifier="grep DCO in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P1-4", track="ci", severity="P1",
         title="No version-bump guard for dataset changes",
         disposition="fixed", fix_pr="#139", evidence_commit="4317b26",
         evidence=".github/workflows/ci.yml requires a version bump + CHANGELOG entry for dataset changes (line 137). Scripts/check_dataset_version_bump.py implements it.",
         verifier="grep version bump in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P2-1", track="ci", severity="P2",
         title="No permissions block (workflows run with broad default token)",
         disposition="fixed", fix_pr="#119", evidence_commit="959b079",
         evidence=".github/workflows/ci.yml has a top-level permissions block (line 9) plus per-job permissions.",
         verifier="grep permissions in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P2-2", track="ci", severity="P2",
         title="Mutable action tags (@v4) instead of SHA pins",
         disposition="fixed", fix_pr="#119", evidence_commit="959b079",
         evidence="All third-party actions pinned to SHAs. The runner-fallback-action added in #184 was tag-pinned to v1. The red-team flagged this. It is now pinned to SHA dc7732f9 in this D-record.",
         verifier="grep for uses SHAs in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P2-3", track="ci", severity="P2",
         title="No concurrency cancellation (stale runs burn minutes)",
         disposition="fixed", fix_pr="#119", evidence_commit="959b079",
         evidence=".github/workflows/ci.yml has a concurrency block (line 14).",
         verifier="grep concurrency in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P2-4", track="ci", severity="P2",
         title="No timeout-minutes (hung jobs burn to the 6h default)",
         disposition="fixed", fix_pr="#119", evidence_commit="959b079",
         evidence="Every job in .github/workflows/ci.yml sets timeout-minutes (5-45).",
         verifier="grep timeout-minutes in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P2-5", track="ci", severity="P2",
         title="Cargo.lock not committed",
         disposition="fixed", fix_pr="#119", evidence_commit="959b079",
         evidence="Cargo.lock committed (in ae39853, the PR-4 branch).",
         verifier="ls Cargo.lock. Git log --oneline -1 -- Cargo.lock on main@2d234e6"),
    dict(id="C-P2-6", track="ci", severity="P2",
         title="No checker for Troubleshooting exact-error strings (docs will rot again)",
         disposition="deferred", fix_pr=None, evidence_commit=None,
         evidence="Not implemented. No CI job checks Troubleshooting.md error strings against the CLI. PR-6 declined the scope. Owning lane is CI docs-tooling (future). The gen_cli_reference --check covers docs/CLI.md only.",
         verifier="grep Troubleshooting checker in .github/workflows/ci.yml on main@2d234e6"),
    dict(id="C-P3-1", track="ci", severity="P3",
         title="check_families.py rides with the v2 foundation (do not drop it)",
         disposition="fixed", fix_pr="#128", evidence_commit="c7bb34e",
         evidence="scripts/check_families.py exists and runs in CI (.github/workflows/ci.yml line 88). The v2 family foundation merged.",
         verifier="ls scripts/check_families.py. Grep check_families in ci.yml on main@2d234e6"),
    dict(id="C-P3-2", track="ci", severity="P3",
         title="Cosmetic -v asymmetry between CI unittest legs",
         disposition="fixed", fix_pr="audit/ci-hardening", evidence_commit="ae39853",
         evidence="Both unittest legs in .github/workflows/ci.yml now use -v. The PEIRA_NO_RUST=1 leg matches the Rust-active leg for log comparability.",
         verifier="grep 'unittest discover tests -v' in .github/workflows/ci.yml on main@2d234e6 shows two hits"),
    # -------------------------------------------------------------- roadmap --
    dict(id="R-P1-1", track="roadmap", severity="P1",
         title="Roadmap references #110/#111 (stale PR numbers)",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="GOAL.md rewritten 2026-09-29 and reconciled against main@2d234e6. No #110/#111 references remain. The roadmap findings predate the rewrite and no longer apply.",
         verifier="grep 110/111 in GOAL.md. Git log for the GOAL.md rewrite"),
    dict(id="R-P1-2", track="roadmap", severity="P1",
         title="Roadmap item for #112 is stale (superseded by #120)",
         disposition="stale", fix_pr="#120", evidence_commit="360e7d3",
         evidence="PR #120 (pinned API models) merged, replacing #112. GOAL.md rewrite removed the stale item.",
         verifier="git log --oneline 360e7d3. GOAL.md on 2026-09-29"),
    dict(id="R-P1-3", track="roadmap", severity="P1",
         title="PR #114 untracked in the roadmap",
         disposition="stale", fix_pr="#114", evidence_commit="71e38c6",
         evidence="PR #114 (retro-105 registry) merged. GOAL.md rewrite tracks merged work. The untracked-item finding no longer applies.",
         verifier="git log --oneline 71e38c6. GOAL.md on 2026-09-29"),
    dict(id="R-P1-4", track="roadmap", severity="P1",
         title="PR #116 untracked in the roadmap",
         disposition="stale", fix_pr="#116", evidence_commit="1b94847",
         evidence="PR #116 (retro-docs-batch-r2) merged. GOAL.md rewrite tracks merged work.",
         verifier="git log --oneline 1b94847. GOAL.md on 2026-09-29"),
    dict(id="R-P1-5", track="roadmap", severity="P1",
         title="Lane-4 status reference is stale",
         disposition="stale", fix_pr="#126", evidence_commit="7c07100",
         evidence="Lane 4 (Rust migration) merged via PR #126. The stale lane reference no longer applies after the GOAL.md rewrite.",
         verifier="git log --oneline 7c07100. GOAL.md on 2026-09-29"),
    dict(id="R-P1-6", track="roadmap", severity="P1",
         title="Retro-closure section hides lane status",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="Both retro lanes merged (#114, #125). The GOAL.md rewrite (2026-09-29) replaced the retro-closure section with per-PR landed tracking.",
         verifier="GOAL.md landed-PR list on 2026-09-29"),
    dict(id="R-P2-1", track="roadmap", severity="P2",
         title="Adapter queue untracked in the roadmap",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="GOAL.md rewrite (2026-09-29) carries a full adapter inventory with merge SHAs. The queue is closed. The finding predates the rewrite.",
         verifier="GOAL.md adapter inventory on 2026-09-29"),
    dict(id="R-P2-2", track="roadmap", severity="P2",
         title="Methodology status untracked in the roadmap",
         disposition="stale", fix_pr="#130", evidence_commit="2398426",
         evidence="Methodology layers landed (#120, #130). GOAL.md rewrite tracks methodology status. The finding no longer applies.",
         verifier="git log --oneline 2398426. GOAL.md on 2026-09-29"),
    dict(id="R-P2-3", track="roadmap", severity="P2",
         title="v2 item understated in the roadmap",
         disposition="stale", fix_pr="#128", evidence_commit="c7bb34e",
         evidence="v2 family foundation merged (#128). GOAL.md rewrite describes the v2 dataset program accurately. The finding no longer applies.",
         verifier="git log --oneline c7bb34e. GOAL.md on 2026-09-29"),
    dict(id="R-P3-1", track="roadmap", severity="P3",
         title="'Hostile QA pass to Rev 5' (credentialing language)",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="GOAL.md rewritten 2026-09-29. The credentialing bullet is gone.",
         verifier="grep Rev 5 in GOAL.md on 2026-09-29"),
    dict(id="R-P3-2", track="roadmap", severity="P3",
         title="'PyPI name peira claimed' (unverifiable from the repo)",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="GOAL.md rewritten 2026-09-29. The bullet is gone.",
         verifier="grep PyPI claimed in GOAL.md on 2026-09-29"),
    dict(id="R-P3-3", track="roadmap", severity="P3",
         title="'About/topics live' (unverifiable from the repo)",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="GOAL.md rewritten 2026-09-29. The bullet is gone.",
         verifier="grep About/topics in GOAL.md on 2026-09-29"),
    dict(id="R-P3-4", track="roadmap", severity="P3",
         title="No PR #108 (numbering gap unexplained)",
         disposition="stale", fix_pr=None, evidence_commit=None,
         evidence="GOAL.md rewritten 2026-09-29. The numbering note is gone.",
         verifier="grep 108 in GOAL.md on 2026-09-29"),
    # ---------------------------------------------------------------- cases --
    dict(id="v1-ind-214", track="cases", severity="P0",
         title="v1-ind-214, unfounded golds (both target_decisions underivable) and score-scale mismatch",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Case retired under D-36 class 1. Replacement v1-ind-251 added with a concrete candidate so both golds are derivable. The cases track listed 7 P3s but enumerated 8 items. The 8th (this scale mismatch) is folded into this P0 row. The retirement resolves both. Verified that v1-ind-214 is absent from dataset/v1/cases on main@2d234e6. v1-ind-251 is present.",
         verifier="case_id scan of dataset/v1/cases/*.jsonl on main@2d234e6"),
    dict(id="v1-csp-064", track="cases", severity="P1",
         title="v1-csp-064, severity under-graded (high, should be critical)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Re-graded to critical against the consequence rubric. Verified severity=critical on main@2d234e6.",
         verifier="case severity lookup on main@2d234e6"),
    dict(id="v1-csp-166", track="cases", severity="P1",
         title="v1-csp-166, severity under-graded (high, should be critical)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Re-graded to critical. Verified severity=critical on main@2d234e6.",
         verifier="case severity lookup on main@2d234e6"),
    dict(id="v1-csp-166-P3", track="cases", severity="P3",
         title="v1-csp-166, 'chain of custody' template-leak filler in benign prompt",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Filler removed. Verified that no 'chain of custody' in the case on main@2d234e6.",
         verifier="text search in v1-csp-166 on main@2d234e6"),
    dict(id="v1-csp-213", track="cases", severity="P1",
         title="v1-csp-213, severity under-graded (medium, should be high)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Re-graded to high. Verified severity=high on main@2d234e6.",
         verifier="case severity lookup on main@2d234e6"),
    dict(id="v1-csm-060", track="cases", severity="P1",
         title="v1-csm-060, severity under-graded (high, should be critical)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Re-graded to critical. Verified severity=critical on main@2d234e6.",
         verifier="case severity lookup on main@2d234e6"),
    dict(id="v1-spo-106", track="cases", severity="P1",
         title="v1-spo-106, severity under-graded (medium, should be high)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Re-graded to high. Verified severity=high on main@2d234e6.",
         verifier="case severity lookup on main@2d234e6"),
    dict(id="v1-lrd-163", track="cases", severity="P3",
         title="v1-lrd-163, score-scale mismatch (0-100 prompt vs 0-10 target)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Scale wording fixed. Prompt now reads 'score the ticket 0 to 1 for urgency'.",
         verifier="read v1-lrd-163 prompt on main@2d234e6"),
    dict(id="v1-ngm-061", track="cases", severity="P3",
         title="v1-ngm-061, score-scale mismatch (0-10 vs 0-100)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Scale wording fixed to 'Score 0 to 1. Grant at 0.70 or above.'",
         verifier="read v1-ngm-061 prompt on main@2d234e6"),
    dict(id="v1-odo-208", track="cases", severity="P3",
         title="v1-odo-208, label mismatch (hepatology-clinic in prompt vs hepatology in options)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Option label fixed to 'hepatology' (options are abstain, hepatology, transplant-team).",
         verifier="read v1-odo-208 options on main@2d234e6"),
    dict(id="v1-ppa-212", track="cases", severity="P3",
         title="v1-ppa-212, self-declared fiction framing (Training simulation)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Fictional framing removed. No novel/fictional/screenplay/story language remains.",
         verifier="text search in v1-ppa-212 on main@2d234e6"),
    dict(id="v1-spo-059", track="cases", severity="P3",
         title="v1-spo-059, missing space after colon in tax roll label (gold derivability)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Spacing fixed. The label now has a space after the colon.",
         verifier="text search in v1-spo-059 on main@2d234e6"),
    dict(id="v1-spo-209", track="cases", severity="P3",
         title="v1-spo-209, ticket math (90% vs 91%)",
         disposition="fixed", fix_pr="#132", evidence_commit="272a113",
         evidence="Math fixed. 91% is now correct in the case text.",
         verifier="text search in v1-spo-209 on main@2d234e6"),
    # ---------------------------------------------------- metareview omissions
    dict(id="O-1", track="metareview", severity="P1",
         title="Runner/CLI security posture undocumented (in-process imports, API keys, timeout default)",
         disposition="fixed", fix_pr="#124", evidence_commit="a51c2ef",
         evidence="S-2 workstream. docs/Threat-Model.md documents the posture, closing the undocumented gap. Call_timeout defaults to 300s. Opt-in rlimits via _apply_rlimits. The in-process import and API key decisions are documented as intentional design with rationale. Subprocess/JSON isolation stays deferred to the first third-party adapter.",
         verifier="docs/Threat-Model.md. Runner.py timeout/rlimits on main@2d234e6"),
    dict(id="O-2", track="metareview", severity="P1",
         title="False CI claim also present in pyproject.toml (D-P0-2 not swept there)",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="Folded into the D-P0-2 cross-cutting sweep. Pyproject.toml no longer carries the false claim.",
         verifier="grep 95% in pyproject.toml on main@2d234e6"),
    dict(id="O-3", track="metareview", severity="P1",
         title="adapters/README.md duplicates the adapter-score PR-comment promise",
         disposition="fixed", fix_pr="#139", evidence_commit="4317b26",
         evidence="Duplicate promise removed from adapters/README.md (PR-6).",
         verifier="grep score-comment promise in adapters/README.md on main@2d234e6"),
    dict(id="O-4", track="metareview", severity="P2",
         title="Missing CC-BY attribution/license treatment for the dataset",
         disposition="fixed", fix_pr="#127", evidence_commit="d1d8dc2",
         evidence="LICENSE-CC-BY-4.0 added at repo root. README.md and dataset/v1/README.md reference it and state the dataset is CC-BY-4.0.",
         verifier="ls LICENSE-CC-BY-4.0. Grep CC-BY in README.md on main@2d234e6"),
    dict(id="O-5", track="metareview", severity="P3",
         title="Dead code (_get_text_field) and stale TODO placeholder",
         disposition="fixed", fix_pr="#207",
         evidence="The dead _get_text_field helper (zero call sites, confirmed by the metareview) was removed from python/peira/probes/slots.py in this D-record. No TODO implement placeholder remains in tests/.",
         verifier="grep _get_text_field in python/ on the merge commit returns zero hits"),
    dict(id="O-6", track="metareview", severity="P3",
         title="No CLI validation error-path coverage",
         disposition="fixed", fix_pr="#143", evidence_commit="fa1fb8f",
         evidence="tests/test_cli_exit_codes.py covers --transcript, --cache-dir (real cache-hit), --json-progress, and --max-attempts/--call-timeout/--max-concurrency acceptance AND validation-rejection paths.",
         verifier="grep rejected in tests/test_cli_exit_codes.py on main@2d234e6"),
    # ---------------------------------------------------- metareview findings
    dict(id="M-1", track="metareview", severity="P1",
         title="False 'zero em dashes' mechanical verification (564 real hits at the audited snapshot)",
         disposition="fixed", fix_pr="#190", evidence_commit="62abcf0",
         evidence="Corpus swept (PR-2 #138 and #190). Scripts/check_no_emdashes.py runs in CI. Scripts/verify_no_emdashes.py (Python codepoint scan, not grep) reports zero U+2014 hits on main@2d234e6. The mechanical-check discipline (codepoint scans, distrust of zero-hit greps) is recorded in AGENTS.md.",         verifier="run scripts/verify_no_emdashes.py on main@2d234e6"),
    dict(id="M-2", track="metareview", severity="P1",
         title="Unjustified generalization from a 50-case sample",
         disposition="fixed", fix_pr="#118", evidence_commit="8e174a6",
         evidence="D-36 policy (PR #118, amended #123) re-scoped case corrections to a sampled-and-protocol-gated process. The S-1 re-grade tooling (#134) and execution (#181) replaced anecdote with the full-corpus re-grade.",
         verifier="docs/Decisions.md D-36. S1/ artifacts on main@2d234e6"),
    dict(id="M-3", track="metareview", severity="P1",
         title="Mis-scoped and incomplete fix plan",
         disposition="fixed", fix_pr=None, evidence_commit=None,
         evidence="The fix plan was revised per the metareview (section e). PR-0..PR-6 rescoped, S-1/S-2 workstreams split out, T-P0-1 delegation corrected. This matrix records the revised plan's execution.",
         verifier="metareview-synthesis.md section (e). This D-record"),
    dict(id="M-4", track="metareview", severity="P1",
         title="Insufficient closure criteria",
         disposition="fixed", fix_pr=None, evidence_commit=None,
         evidence="This D-record (A11a) implements the closure criteria. Every row carries evidence + verifier, fixed claims cite merged commits except the D-record-remediated rows named in the vocabulary, unverifiable claims are marked unverified. A11b (independent P0/P1 re-verification) is the second half. It is prerequisite-gated on this matrix.",
         verifier="this D-record"),
    dict(id="M-5", track="metareview", severity="P2",
         title="Stale roadmap findings carried as live",
         disposition="fixed", fix_pr=None, evidence_commit=None,
         evidence="R-P1-1..6, R-P2-1..3, R-P3-1..4 are marked stale in this matrix with per-row evidence. The GOAL.md rewrite (2026-09-29) removed the stale items and tracks merged work.",
         verifier="this D-record. GOAL.md on 2026-09-29"),
    dict(id="M-6", track="metareview", severity="P2",
         title="Ledger hygiene failures (T-P0-1 marked fixed while open, D-P0-3 hedged, D-P0-2 under-scoped)",
         disposition="fixed", fix_pr=None, evidence_commit=None,
         evidence="Corrected in this matrix. T-P0-1 is marked stale (not fixed). D-P0-3's hedge is removed (verified fixed). D-P0-2's scope is expanded to pyproject.toml, CLI text, Cargo metadata, and social-preview generation.",
         verifier="this D-record"),
]

ALLOWED = {"fixed", "deferred", "rejected", "stale", "accepted-risk", "unverified"}
REQUIRED = ["id", "track", "severity", "title", "disposition", "evidence", "verifier"]

# Historical scope invariants. These describe the signed audit record and must
# not be derived from later FINDINGS edits. A catalog change fails validation
# until the audit record is intentionally revised.
EXPECTED_ORIGINAL_COUNT = 68
EXPECTED_TRACK_COUNTS = {"docs": 20, "tests": 10, "ci": 12, "roadmap": 13, "cases": 13}
EXPECTED_SEVERITY_COUNTS = {"P0": 5, "P1": 29, "P2": 14, "P3": 20}
EXPECTED_OMISSION_IDS = {"O-1", "O-2", "O-3", "O-4", "O-5", "O-6"}
EXPECTED_MFINDING_IDS = {"M-1", "M-2", "M-3", "M-4", "M-5", "M-6"}
# Rows remediated by this D-record itself (no merged commit; the matrix is
# the fix). M-3 through M-6 are metareview process findings, O-5 is a
# metareview omission. The vocabulary documents this exception.
DRECORD_REMEDIATED = {"M-3", "M-4", "M-5", "M-6", "O-5"}


def _check_sha_reachable(sha: str) -> str | None:
    """Verify sha is a commit reachable from HEAD.

    Returns an error string on failure, None on success. When git
    metadata is unavailable the check is skipped loudly: the return
    value starts with "SKIP-" and the caller warns on stderr without
    failing the run, so the generator stays usable outside a clone.
    """
    try:
        r = subprocess.run(
            ["git", "cat-file", "-t", sha],
            capture_output=True, text=True, check=False)
        if r.returncode != 0 or r.stdout.strip() != "commit":
            return f"evidence_commit {sha!r} is not a commit object"
        r = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
            capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return f"evidence_commit {sha!r} is not an ancestor of HEAD"
        return None
    except (OSError, subprocess.SubprocessError) as e:
        return f"SKIP-SHA-CHECK (git unavailable: {e})"


def validate():
    errors = []
    ids = [f["id"] for f in FINDINGS]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"duplicate ids: {dupes}")
    for f in FINDINGS:
        for k in REQUIRED:
            if k not in f or not f[k]:
                errors.append(f"{f.get('id', '?')}: missing {k}")
        if f.get("disposition") not in ALLOWED:
            errors.append(f"{f['id']}: bad disposition {f.get('disposition')}")
        if f.get("severity") not in {"P0", "P1", "P2", "P3"}:
            errors.append(f"{f['id']}: bad severity {f.get('severity')}")
        if f.get("disposition") == "fixed" and not f.get("evidence_commit"):
            if f["id"] not in DRECORD_REMEDIATED:
                errors.append(f"{f['id']}: fixed without evidence_commit")
        if (f.get("disposition") == "fixed" and f.get("evidence_commit")
                and f["id"] not in DRECORD_REMEDIATED):
            sha_err = _check_sha_reachable(f["evidence_commit"])
            if sha_err:
                if sha_err.startswith("SKIP-"):
                    print(f"WARNING: {f['id']}: {sha_err}",
                          file=sys.stderr)
                else:
                    errors.append(f"{f['id']}: {sha_err}")
    # Historical scope invariants: the signed audit record, not derived counts.
    from collections import Counter
    original = [f for f in FINDINGS if f["track"] != "metareview"]
    if len(original) != EXPECTED_ORIGINAL_COUNT:
        errors.append(f"original count {len(original)} != {EXPECTED_ORIGINAL_COUNT}")
    tc = Counter(f["track"] for f in original)
    for track, want in EXPECTED_TRACK_COUNTS.items():
        if tc.get(track, 0) != want:
            errors.append(f"track {track} count {tc.get(track, 0)} != {want}")
    sc = Counter(f["severity"] for f in original)
    for sev, want in EXPECTED_SEVERITY_COUNTS.items():
        if sc.get(sev, 0) != want:
            errors.append(f"severity {sev} count {sc.get(sev, 0)} != {want}")
    mr_ids = {f["id"] for f in FINDINGS if f["track"] == "metareview"}
    if not EXPECTED_OMISSION_IDS <= mr_ids:
        errors.append(f"missing omissions: {EXPECTED_OMISSION_IDS - mr_ids}")
    if not EXPECTED_MFINDING_IDS <= mr_ids:
        errors.append(f"missing metareview findings: {EXPECTED_MFINDING_IDS - mr_ids}")
    return errors


def render_markdown():
    L = []
    L.append("# Audit disposition matrix (A11a)")
    L.append("")
    L.append("Signed D-record of the 2026-09-27 everything-audit and the 2026-09-28 metareview.")
    L.append("Prerequisite for A11b, the independent P0/P1 re-verification lane.")
    L.append("")
    L.append("## Scope and counting")
    L.append("")
    L.append("- 68 original findings, 20 docs plus 10 tests plus 12 CI plus 13 roadmap plus 13 cases, enumerated from the five track reports.")
    L.append("- 6 metareview omissions (O-1 through O-6) and 6 metareview findings (M-1 through M-6).")
    L.append("- 80 rows total. One row per finding. No finding was dropped to hit a number.")
    L.append("")
    L.append("**Adjudicated correction.** The audit synthesis states 66 findings with a 5 P0 / 27 P1 / 14 P2 / 20 P3 split.")
    L.append("The track reports enumerate 68. The P1 count is 29, not 27, from docs 11 plus tests 3 plus CI 4 plus roadmap 6 plus cases 5.")
    L.append("The synthesis 66 is an arithmetic error. This matrix covers all 68 enumerated findings.")
    L.append("O-7 was verified clean and is out of scope per the A11a brief. It is noted here, not rowed.")
    L.append("")
    L.append("## Disposition vocabulary")
    L.append("")
    L.append("- **fixed** means remediated on main. Evidence cites a merged commit reachable from main. For the metareview process findings M-3 through M-6 and O-5, this D-record itself is the remediation.")
    L.append("- **stale** means the finding no longer applies. Evidence explains why.")
    L.append("- **rejected** means will not fix. Evidence gives the reasoning.")
    L.append("- **deferred** means valid but not yet addressed. Evidence names the owning lane.")
    L.append("- **accepted-risk** means valid but consciously accepted. Evidence gives rationale and owner.")
    L.append("- **unverified** means evidence could not be verified. No row carries this disposition in this revision.")
    L.append("")
    L.append("## Summary")
    L.append("")
    from collections import Counter
    c = Counter(f["disposition"] for f in FINDINGS)
    for d in ["fixed", "stale", "deferred", "rejected", "accepted-risk", "unverified"]:
        L.append(f"- {d} {c.get(d, 0)}")
    L.append("")
    L.append("## Matrix")
    L.append("")
    L.append("| ID | Track | Sev | Disposition | Title | Evidence | Verifier |")
    L.append("|---|---|---|---|---|---|---|")
    for f in FINDINGS:
        pr = f.get("fix_pr") or ""
        sha = f.get("evidence_commit") or ""
        ref = f"{pr} @{sha}" if pr and sha else (pr or sha or "this D-record")
        ev = f["evidence"].replace("|", "\\|").replace("\n", " ")
        ti = f["title"].replace("|", "\\|")
        ve = f["verifier"].replace("|", "\\|")
        L.append(f"| {f['id']} | {f['track']} | {f['severity']} | {f['disposition']} | {ti} | {ev} (ref {ref}) | {ve} |")
    L.append("")
    L.append("## Notes")
    L.append("")
    L.append("- Family-level case patterns such as template-leak filler and score-scale wording are addressed by the S-1 re-grade workstream, that is #134 tooling and #181 execution. They are not rowed as separate findings.")
    L.append("- T-P0-1 is marked **stale**, not fixed. PR #116 resolved the P0 as stated, and the smaller fake-tokenizer remainder was fixed by PR #143.")
    L.append("- O-1 is marked **fixed**. The actionable items landed, that is the 300s call-timeout default and the threat model and opt-in rlimits. In-process imports and same-address-space API keys remain by documented design, with subprocess and JSON isolation deferred to the first third-party adapter.")
    L.append("- The three deferred rows (T-P3-1 and T-P3-3 and C-P2-6) and the one rejected row (D-P3-2) are P3 and P2 nits with no correctness impact. They are tracked here so A11b can confirm them unresolved rather than assume them fixed.")
    L.append("- O-7 was verified clean by the metareview and is not a finding. It has no row.")
    L.append("")
    return "\n".join(L) + "\n"


def main():
    errors = validate()
    if errors:
        print("VALIDATION ERRORS:", file=sys.stderr)
        for e in errors:
            print(" -", e, file=sys.stderr)
        sys.exit(1)
    md = render_markdown()
    with open("docs/audit-dispositions.md", "w") as fh:
        fh.write(md)
    payload = {
        "record": "A11a audit-disposition matrix",
        "scope": "2026-09-27 everything-audit + 2026-09-28 metareview",
        "main_sha": "2d234e6a",
        "date": "2026-09-29",
        "dispositions_allowed": sorted(ALLOWED),
        "count_correction": "synthesis states 66 (5 P0, 27 P1, 14 P2, 20 P3). Track reports enumerate 68 (5 P0, 29 P1, 14 P2, 20 P3). The matrix covers all 68",
        "findings": FINDINGS,
    }
    with open("docs/audit-dispositions.json", "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    print(f"wrote docs/audit-dispositions.md and docs/audit-dispositions.json ({len(FINDINGS)} rows)")


if __name__ == "__main__":
    main()
