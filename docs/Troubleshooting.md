# Troubleshooting

An error catalog: exact error → cause → fix. New user-facing errors get an
entry here in the same PR that introduces them.

**`error: unknown adapter: 'x'`**
Cause: the adapter name didn't resolve. Fix: use `mock`, or pass a dotted
path — `package.module` (with a top-level `adapter`),
`package.module:ClassName`, or `package.module.ClassName` (see
`examples/minimal_adapter.py`). Run from the directory your adapter module
lives under.

**`error: unknown suite 'x'`**
Cause: typo in `--suite`. Fix: `trial-demo` (demo fixture, offline) or
`trial` (the real 100-case Trial suite, planned — ships with dataset v1).

**`error: suite directory ... not found`**
Cause: you ran `peira` from outside the repo checkout. Fix: run from the
repo root, or `pip install -e .` from a checkout.

**`...: bad primitive: 'xyz'` / `bad severity` / `missing required key`**
Cause: a case file fails schema validation. Fix: run
`peira validate --dataset <dir>` — it prints file, line, and rule.

**`confidence 1.4 outside 0..1` (or similar contract errors)**
Cause: your adapter returned a value outside its primitive contract.
Fix: normalize outputs in your adapter (Choice confidence and Score must
be 0..1). Malformed outputs count against your ASR, so fix this before
benchmarking seriously.

**Hugging Face auth / rate-limit errors** (planned `peira[hf]` adapters)
Cause: `peira[hf]` adapters download models from HF Hub. Fix: `huggingface-cli
login`, or set `HF_TOKEN`. Model weights are cached after the first download.

**Out-of-memory on local models**
Cause: the model doesn't fit in RAM/VRAM. Fix: use a quantized variant or a
smaller adapter; see `docs/Hardware.md` for per-tier requirements.

**`peira report` warns "analysis lock mismatch"**
Cause: the run artifact was edited after sealing (the report still
renders, but the numbers aren't trustworthy). Fix: don't edit artifacts;
re-run. If you need different config, that's a new run with a new lock.

**`error: dataset manifest verification failed:`**
Cause: `peira run` verifies the suite manifest before scoring, and a
case file changed after the manifest was built (hash mismatch, or
counts like `n_cases` drifted). Each mismatch is listed after the
colon. Nothing is scored — the run fails closed so a tampered dataset
can never seal a clean-looking artifact. Fix: don't edit released case
files — cut a new dataset version instead. For a draft, rebuild the
manifest with `peira dataset build-manifest --dir <suite-dir>` and
re-run.

**`error: partial run was recorded against a different dataset snapshot ...`**
Cause: `peira run --resume` found a partial run whose sealed manifest
digest doesn't match the current suite manifest — the dataset changed
between the interrupted run and the resume. Merging old partial results
with a new dataset would corrupt the run. Fix: delete the
`<adapter>-<suite>.partial.json` file and re-run without `--resume`.

**`error: no cases found in ...`**
Cause: the suite directory has no `.jsonl` files. Fix: check the path;
`dataset/trial-demo/cases.jsonl` ships with the repo.

**`peira run` exits with code 3**
Cause: none — the run completed. Exit 3 means ranking-ineligible (one of
the Methodology eligibility floors failed; the notes are printed with the
results). Fix: none needed for a demo; for a real submission, clear the
named gate. Exit codes: 0 clean, 1 user error, 2 infrastructure error,
3 completed but unranked.

**`error: dataset directory ... not found`**
Cause: `peira dataset build-manifest` / `verify-manifest` got a `--dir`
that doesn't exist. Fix: check the path — dataset directories live under
`dataset/` (e.g. `dataset/v1`).

**`error: invalid cases, manifest not written`**
Cause: `build-manifest` validates every case before writing — one or more
lines failed schema validation (file, line, and rule are printed). Fix:
fix the cases, then rebuild. A manifest is never written for invalid data.

**`error: no manifest.json in ... — run 'peira dataset build-manifest' first`**
Cause: `verify-manifest` needs a manifest to check against. Fix: build one
with `peira dataset build-manifest --dir <dir> --version <v>`.

**`error: ... does not match manifest.json` (sha256 mismatch / missing on disk)**
Cause: a dataset file changed after the manifest was built. Fix: if the
change is intentional, that's a new dataset version — rebuild the manifest
with the bumped version. If not, restore the file (manifests are committed
to git for exactly this reason).

**`peira dataset gates` reports failures (exit 1)**
Cause: one or more gates found errors — file, line, and rule are printed
per gate. Fix: address each error (duplicate case ids/content, unknown
family id, attacked input identical to benign, incoherent target), then
re-run. Warnings (e.g. G6 pii-scan) don't fail the suite but go to the
human review queue.

**`peira dataset new: error: argument --family: invalid choice: 'x'`**
Cause: the family id isn't one of the ten canonical ids. Fix: pick from
the list in the error — `state_poisoning`, `criteria_smuggling`,
`option_order`, `distractor_flooding`, `score_anchoring`,
`literal_reading`, `negation_games`, `policy_paraphrase`, `indirection`,
`confidence_spoofing` (see `docs/Taxonomy.md`).

**`error: cannot write to ...` from `peira dataset new --out`**
Cause: the output file's directory doesn't exist or isn't writable. Fix:
create the directory first, or drop `--out` to print to stdout.

**`error: unknown case id 'x' in ...`**
Cause: `peira dataset review approve/reject` got a case id that isn't in
the dataset directory. Fix: check the id — `peira dataset review --dir
<dir>` lists pending case ids.

**`error: unreadable review state: ...`**
Cause: `review.json` is corrupt. Fix: restore it from git (review
decisions are committed). If it was never created, there's nothing to
restore — an absent `review.json` simply means nothing reviewed yet.

**`error: N reviews pending — manifest not written`**
Cause: `build-manifest --require-reviews` found unreviewed cases. Fix:
review them (`peira dataset review --dir <dir>`), or drop
`--require-reviews` for a draft manifest (never release one).

**`error: --dir is required`**
Cause: `peira dataset review` without `--dir`. Fix: pass
`--dir <dataset-dir>`.

**`peira-cli validate`: `validate: FAILED (N errors in M cases)`**
Cause: the Rust validator (`crates/peira-cli`, used in CI) found cases
that fail schema validation. Each offending line is printed as
`file:line: <rule>` above the summary. Fix: same as the Python
`peira dataset gates` failures — fix the case file. Error rules are
identical across both implementations.

**`peira-cli`: `error: dataset directory ... not found`**
Cause: `peira-cli validate` / `verify-manifest` got a `--dir` that
doesn't exist. Fix: check the path.

**`peira-cli`: `error: no manifest.json in ... — run 'peira dataset build-manifest' first`**
Cause: `peira-cli verify-manifest` needs a manifest to check against.
Fix: build one with the Python CLI first — the Rust side verifies
manifests, it doesn't author them.

**`peira-cli`: `error: unreadable manifest: ...`**
Cause: `manifest.json` is missing, corrupt, or not the expected shape.
Fix: restore it from git, or rebuild with
`peira dataset build-manifest`.

**`peira-cli`: `error: ... does not match manifest.json:`**
Cause: a case file changed after the manifest was built (hash mismatch,
or counts like `n_cases` drifted). Each mismatch is listed as
`  - <file>: <what changed>`. Fix: don't edit released case files —
cut a new dataset version instead. For a draft, rebuild the manifest.

**`error: the 'cargo' binary was not found on PATH.`**
Cause: you ran `scripts/build_core_ext.py` without the Rust toolchain.
Fix: install it (https://rustup.rs) — or skip the build entirely. The
extension is an optional accelerator; peira runs on the pure-Python
reference implementation without it.

**`error: cargo build failed (exit N).`**
Cause: the PyO3 extension failed to compile. Fix: check you have a
Python 3.10+ interpreter with development headers (`Python.h`) — on
Debian/Ubuntu that's `python3-dev`. Then re-run
`python scripts/build_core_ext.py`.

**`error: no cdylib found in target/...`**
Cause: cargo finished but produced no shared library (wrong target dir
or an interrupted build). Fix: `cargo clean -p peira-python` and rebuild
with `python scripts/build_core_ext.py`.

**`error: built extension failed to import:`**
Cause: the compiled `peira._core` doesn't load in your Python (usually a
version mismatch — the extension is built for the interpreter that ran
the script). Fix: rebuild with the Python you actually use, and make
sure no stale `_core*.so` / `_core*.pyd` from another interpreter sits in
`python/peira/`.

**`warning: unreadable manifest at ... (…); recording dataset_version='0.1.0-demo'.`**
Cause: `peira run` found a `manifest.json` in the suite directory but
couldn't parse it, so the run artifact records the fallback dataset
version instead of the real one. Fix: rebuild it with
`peira dataset build-manifest --dir <suite-dir> --version <v>` and re-run.
(The analysis lock still seals whatever version was recorded — this
warning is about accuracy of the label, not integrity of the run.)
