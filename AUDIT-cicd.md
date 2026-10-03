# CI/CD Audit — peira (david-engelmann/peira)

**Auditor:** CI/CD subagent (read-only) · **Date:** 2026-10-02 · **Tree:** `agentic-dev-audit` @ `fc289590` (main)
**Scope:** `.github/workflows/ci.yml`, `scripts/check_*.py`, maturin workflow docs, CI runtime, local-vs-CI divergence.
Nothing was modified; every finding below was verified by reading code or running the script locally.

## Job inventory (note: 19 jobs, not 17)

`ci.yml` defines 19 jobs (lines 19–442): `check_runner` (19), `lockfile` (59),
`public-surface` (73), `docs` (84), `coderabbit-config` (109), `site` (124),
`dco` (146), `dataset-version` (178), `dataset-tags` (198),
`disposition-drift` (233), `lint-rust` (255), `test-python` (268),
`test-hf-tokenizers` (287), `test-rust` (326), `test-python-rust` (335),
`test-integration` (366), `quickstart` (397), `readme-table` (422),
`dataset-checks` (442).

## Check-script × CI cross-reference

| Script | In CI? | Verdict |
|---|---|---|
| `check_public_surface.py` | ✅ `public-surface` (73) | has defect — see P2-2 |
| `check_doc_links.py`, `check_no_emdashes.py`, `check_no_weighted_mcnemar.py`, `check_families.py`, `check_notes_tier_words.py`, `check_trial_version_pins.py` | ✅ `docs` (84) | clean |
| `gen_cli_reference.py --check` | ✅ `docs` (84) | clean (self-bootstraps `sys.path`, no install needed) |
| `check_coderabbit_config.py` | ✅ `coderabbit-config` (109) | clean |
| `check_dataset_version_bump.py` | ✅ `dataset-version` (178) | clean |
| `check_dataset_tags.py` | ✅ `dataset-tags` (198) | clean |
| `generate_audit_dispositions.py` (drift) | ✅ `disposition-drift` (233) | clean |
| `check_readme_table.py` | ✅ `readme-table` (422) | error-quality nits — see P3-3 |
| `gen_readme_table.py` | ✅ `quickstart` (397) + `readme-table` (422) | clean |
| `check_canary_separation.py` | ❌ **not in CI** | documented as manual-only (CANARY.md:37–40) — see P3-1 |
| `verify_no_emdashes.py` | ❌ not in CI | one-time PR-2 reproduction script, says so in its docstring — fine as local-only |
| `artifact_smoke.py` | ❌ **not in CI** | AGENTS.md:13 says "must stay green" — see P2-3 |
| `peira contamination-check` (cli.py:5884) | ❌ **not in CI** | permanent-canary CLI exists, never invoked — see P2-4 |
| `regen_fixture_manifest.py --check` | ➖ via `tests/test_fixture_manifest.py` in the pytest suite | covered indirectly |
| `audit_holdout_separation.py`, `audit_v2_drafts.py`, `drift_detect.py`, `combo_*.py`, `calibrate_g9_threshold.py`, `seal_manifest.py`, `record_dataset_release.py` | ❌ not in CI | research/release tooling; legitimately local-only |

---

## P1 — CI wastes huge time

### P1-1. Zero dependency caching: ~9 full Rust workspace compiles per CI run
**Evidence:** `.github/workflows/ci.yml` — the only `cache:` in the file is `cache: npm` (line 136, `site` job).
A repo-wide grep for `rust-cache|Swatinem|sccache|CARGO_TARGET_DIR|cache: pip` across
`.github/workflows/*.yml` returns nothing.

Every one of these installs the Rust toolchain and compiles the workspace from scratch,
with no cargo target cache and no pip cache:
- `lint-rust` (255): `cargo clippy --workspace --all-targets`
- `test-rust` (326): `cargo test --workspace`
- `test-python` (268): `pip install -e .[dev]` (maturin debug build at install time)
- `test-python-rust` (335): `pip install --no-build-isolation -e .[dev]` **plus** `maturin develop --release` (second compile)
- `test-integration` (366): full venv + `maturin develop --release` again (third release-profile compile)
- `dataset-checks` (442): `cargo run -q -p peira-cli` (compiles the CLI binary)
- `quickstart` (397): `pip install -e .` on **3 OSes** (3 more maturin builds)
- `readme-table` (422): `pip install -e .` again

`Swatinem/rust-cache` (or `sccache`) plus `actions/setup-python` pip caching would collapse
nearly all of this. On the self-hosted `runner-grid` (David's laptop) this is his own CPU
burning on every push; on GitHub-hosted fallback it's billed minutes. This is the single
biggest CI cost in the repo.

### P1-2. `test-python` duplicates `test-python-rust`'s `PEIRA_NO_RUST=1` leg — a full suite run for nothing
**Evidence:** `ci.yml` `test-python` (268) runs
`PEIRA_NO_RUST=1 python -m pytest tests -n auto --ignore=tests/integration`;
`test-python-rust` (335) runs the same command as its second leg
(`PEIRA_NO_RUST=1 .venv/bin/python -m pytest tests -n auto --ignore=tests/integration`).

The `test-python` job comment claims it "covers the fallback backend on a fresh checkout"
while `test-python-rust` covers "the compiled backend" — but under `PEIRA_NO_RUST=1`
the built extension is never imported, so both legs execute byte-identical pure-Python code.
The only material difference is incidental: `test-python` uses build-isolated
`pip install -e .[dev]` (the documented local command) while `test-python-rust` uses
`--no-build-isolation`. If the intent is to smoke-test the documented install command,
keep `test-python` as an install-only job and drop its full pytest run — or drop the job
and keep one `NO_RUST` suite leg. As written, every PR/push pays for one redundant
editable install (maturin debug compile) plus one redundant full xdist suite run.

---

## P2 — meaningful gaps

### P2-1. `docs/Contributing.md` lists the wrong required checks
**Evidence:** `docs/Contributing.md:42–46`:
"The required checks are check_runner, coderabbit-config, public-surface, docs, dco,
dataset-version, lint-rust, test-python, test-hf-tokenizers, test-rust, test-python-rust,
test-integration, quickstart, readme-table, and dataset-checks."

That's 16 names. It **omits** `lockfile` (59), `dataset-tags` (198), `disposition-drift`
(233), and `site` (124) — all of which run on PRs — and **includes** `check_runner`,
which is a runner-selection helper job, not a check. If GitHub branch protection matches
either list, agents reading Contributing.md get a false picture of the merge gate
(e.g. believing `dataset-tags` or the lockfile check is advisory when it may be required,
or vice versa). The required-check list should be generated or mechanically verified
against the workflow, not hand-maintained prose.

### P2-2. `check_public_surface.py`: the allowlist escape hatch is broken for 18 of 19 patterns
**Evidence:** `scripts/check_public_surface.py` docstring: "Approved factual uses go in
`.public-surface-allowlist` (one regex per line)". Code at line 73:
```python
if raw == r"\baudits\b" and any(a.search(line) for a in allowed):
    continue
```
The allowlist is consulted **only** for the plural-audit pattern. The other 18 banned
patterns (the superlative pattern, the two speed-ship phrases, `\bdominat\w*`, …) ignore the allowlist
entirely. The script scans a huge blast radius — all of `dataset/` (including
`*.jsonl` case files), `tests/`, `site/`, docs — where a superlative can
appear in legitimate case content. Today the check passes (verified locally), but the
first false positive will be unfixable through the documented mechanism; the maintainer
would have to edit the script's `BANNED` list. Either apply the allowlist to every
pattern or document that only the plural-audit pattern is allowlistable.

### P2-3. `scripts/artifact_smoke.py` is required green locally but runs in no CI job
**Evidence:** `AGENTS.md:13` lists `.venv/bin/python scripts/artifact_smoke.py` as must-stay-green.
The script "builds the real wheel from the worktree, installs it into a scratch venv,
runs gates + metrics through the INSTALLED package". No job in `ci.yml` (or
`release-wheels.yml`, which only builds wheels on tags without installing or testing them)
exercises the real-wheel install path. The maturin migration just changed exactly this
packaging path, and the one check that validates the shipped artifact end-to-end has no
CI backstop — a local-only gate that CI cannot catch drifting. Wire it into CI
(e.g. a job after the build, or fold into `quickstart`'s install step using a wheel
instead of an editable install).

### P2-4. `peira contamination-check` exists but is never run in CI
**Evidence:** `python/peira/cli.py:5884` defines the `contamination-check` subcommand
("check public case files for the permanent canary", exits 1 when any file is missing
the canary). The `dataset-checks` job (442) — whose own comment calls it "the authoring
pipeline's release seal" — runs `peira dataset gates`, `peira dataset verify-manifest`,
and `cargo run -q -p peira-cli -- validate`, but never the canary scan. The permanent
canary is the training-contamination trust mechanism; a public case file missing the
canary string would pass CI today. One line in `dataset-checks` closes it.

---

## P3 — polish

### P3-1. `check_canary_separation.py` full scan is manual-only and the release seal never invokes it
Compliant with the stated rule (CANARY.md:37–40 documents it as "covered by unit tests
in CI; run it manually against the repo root"), so not a violation — but note the
compounding gap: the unit tests only test the script's *logic* against fixtures, never
the repo's actual canary state, and `scripts/release/preflight.py` / `validate.py`
contain zero canary references (verified by grep). The tier-separation security property
has no automated enforcement point anywhere in the pipeline or the release path.
Consider invoking it from the release tooling (`scripts/release/`) at seal time.

### P3-2. `test-hf-tokenizers` pins stale action versions
**Evidence:** `ci.yml` `test-hf-tokenizers` (287) uses `actions/checkout@11d5960a` (v4)
and `actions/setup-python@a26af69b` (v5) while every other job uses v7.0.1 / v7.0.0 SHAs.
Harmless today, but the inconsistency will confuse the next person bumping actions.

### P3-3. `check_readme_table.py` fails with raw tracebacks instead of actionable errors
**Evidence:** `scripts/check_readme_table.py`:
- missing README path → unhandled `FileNotFoundError` traceback (verified: ran with a
  nonexistent path, got a traceback, not the script's `usage:`/`error:` format);
- README without the `"generated, never hand-edited"` anchor → bare `StopIteration`
  from `next(...)` in `committed_table` (no default), not the clean
  `"error: no table found after ... anchor"` message the table-missing branch produces;
- `generated_table` shells out to the *relative* path `scripts/gen_readme_table.py`,
  so running the check from any directory other than the repo root fails confusingly.
  (Contrast `check_trial_version_pins.py`, whose error messages name the exact file,
  the expected pattern, and how to fix the script — the quality bar to copy.)

### P3-4. `EXIT_GATE_NOTE` and `EXIT_REPRO_MISMATCH` both equal 3 — latent trap for the `|| [ $? -eq 3 ]` pattern
**Evidence:** `python/peira/cli.py:55` (`EXIT_GATE_NOTE = 3`, "ran fine, but the run is
not ranking-eligible") and `cli.py:4606` (`EXIT_REPRO_MISMATCH = 3`).
Verified safe **today**: `quickstart` (397) and `readme-table` (422) only run
`peira run`, whose code paths return `EXIT_GATE_NOTE` and never `EXIT_REPRO_MISMATCH`
(the latter is returned only by `cmd_reproduce`, lines 4809/4857/4865), and the
`|| [ $? -eq 3 ]` idiom correctly fails on any other exit code — it is *not* masking
failures. But the shared value means a future `peira reproduce ... || [ $? -eq 3 ]`
would silently swallow a reproduction *mismatch* as "ranking-ineligible". Give the two
constants distinct values.

### P3-5. Unpinned installers in lightweight jobs
`lockfile` (59) runs `pip install uv` and `coderabbit-config` (109) runs
`pip install pyyaml` with no version pins — a breaking upstream release turns into a
mystery CI failure. Pin them.

### P3-6. Minor duplications / nits
- `quickstart` (397) and `readme-table` (422) both run
  `peira run --adapter mock --suite trial --seed 0` (two ~100-case runs + two editable
  installs). Different purposes (verbatim-README test vs table-drift check), so keep both
  jobs, but the run itself could be shared via an artifact.
- `quickstart` is the only job that does not `need: check_runner` — correct for the
  macOS/Windows matrix (the grid is Linux), but undocumented; a comment would stop the
  next reader "fixing" it.
- `test-hf-tokenizers` runs `pip install -e .[hf]` then `pip install -e .[dev]` —
  two editable installs back-to-back; one `-e .[hf,dev]` would do.

---

## Explicitly checked and found fine (do not "fix")

- **`|| [ $? -eq 3 ]` does not mask failures.** Fails on any exit code other than 0 or 3;
  exit 3 from `peira run` can only mean ranking-ineligible (see P3-4 for the caveat).
- **`docs` job needs no `pip install`.** `gen_cli_reference.py` (line 24),
  `check_no_weighted_mcnemar.py`, and `check_families.py` all self-bootstrap with
  `sys.path.insert(0, <root>/python)` — deliberate, and distinct from the
  `PYTHONPATH` testing pitfall AGENTS.md warns about (these scripts generate docs,
  they don't exercise `_core`).
- **`test-hf-tokenizers` network-in-CI / skip-locally is deliberate and documented**
  in the job comment (lines 287–296), including the zero-skip summary grep — a good
  anti-dishonesty pattern worth copying elsewhere.
- **`site` job's comment is accurate.** It claims mock-artifact ingestion, which happens
  via the `prebuild: npm run ingest-mock` hook (`site/package.json:13`), not a missing step.
- **`dco`, `dataset-version`, `dataset-tags`, `disposition-drift`** all set
  `fetch-depth: 0` where they need history; `dataset-tags` handles the empty
  `BASE_SHA` on push events correctly.
- **Maturin workflow docs are current.** `docs/Contributing.md:60–98` documents
  `maturin develop` + venv, the gitignored `_core` artifact, and the
  `PYTHONPATH` silent-fallback trap. `AGENTS.md` (symlinked as `CLAUDE.md`) matches.
  Stale `build_core_ext.py` references exist only in historical records where they belong:
  `CHANGELOG.md:62,1371`, `docs/Decisions.md:14,1739`, `docs/audit-dispositions.md:47`
  (frozen evidence text). No live doc references the retired script.
- **Check-script error quality is otherwise high.** `check_trial_version_pins.py`
  names the file, the regex, and the fix; `check_families.py` prints a clear one-line
  pass ("families: registry and docs/Taxonomy.md agree (29 families)"); the `docs` job
  scripts fail fast with file:line context.

## Suggested fix order

1. P1-1 (caching) — biggest win, mechanical.
2. P1-2 (drop one `NO_RUST` suite leg) — pair with the caching change since both touch the test jobs.
3. P2-4 (one-line `contamination-check` in `dataset-checks`) and P2-3 (`artifact_smoke.py` in CI) — cheap, close real coverage holes on the packaging/canary trust path.
4. P2-2 (allowlist scope) and P2-1 (required-checks list) — doc/code consistency.
5. P3 items as drive-bys.
