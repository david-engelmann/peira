# Troubleshooting

An error catalog: exact error → cause → fix. New user-facing errors get an
entry here in the same PR that introduces them.

**`error: unknown adapter: 'x'`**
Cause: the adapter name didn't resolve. Fix: use `mock`, or pass a dotted
path — `package.module` (with a top-level `adapter`),
`package.module:ClassName`, or `package.module.ClassName` (see
`examples/minimal_adapter.py`). Run from the directory your adapter module
lives under.

**Loading an adapter runs its code — only use paths you trust**
Cause: `peira run --adapter some.module` imports that module to get the
adapter, and importing a module executes it. The working directory is
prepended to `sys.path` first, so a local file can shadow an installed
package of the same name. Fix: only load adapter paths you trust, and
run from a directory whose files you control. The bundled `mock`
adapter is safe.

**`error: unknown suite 'x'`**
Cause: typo in `--suite`. Fix: `trial-demo` (demo fixture, offline) or
`trial` (the branded 100-case Peira Trial, sealed `1.0.0`).

**`error: suite directory ... not found`**
Cause: you ran `peira` from outside the repo checkout. Fix: run from the
repo root, or `pip install -e .` from a checkout.

**`...: bad primitive: 'xyz'` / `bad severity` / `missing required key`**
Cause: a case file fails schema validation. Fix: run
`peira validate --dataset <dir>` — it prints file, line, and rule. Type
errors look like `bad case_id: expected string`,
`bad benign input: expected object`, or
`bad attacked target_decision: expected string or null` — the value has
the wrong JSON type for that field.

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

**`error: partial run has malformed result entry at index N ...`**
Cause: `peira run --resume` found a partial run whose `results` entry at
position N isn't a well-formed result object (a scalar, or an object with
the wrong fields) — the file was hand-edited or corrupted. The resume
refuses to guess what the entry meant. Fix: delete the
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

**`error: version ... is not semver ... — manifest not written`**
Cause: `build-manifest --version` must be a semantic version
(`1.0.0`, `0.1.0-trial`), per the versioning rules in `docs/Dataset.md`.
Fix: pass a semver version; prerelease suffixes like `-trial` are allowed.

**`error: N critical case(s) missing severity notes — manifest not written`**
Cause: the severity rubric asks the author to say why a case earned its
tier in the case notes, and the release seal enforces it for
critical-severity cases. Fix: add a severity justification to each listed
case's `notes` field (see `docs/Severity-Rubric.md`), then rebuild.

**`error: content changed since version ... was sealed — bump the version, manifest not written`**
Cause: a manifest already exists for that version but the dataset files
changed since — versioning rule 1 says any case added, changed, or
removed is a new version. Rebuilding byte-identical content under the
same version is fine; changed content is not. Fix: rebuild with the
bumped `--version`.

**`error: no manifest.json in ... — run 'peira dataset build-manifest' first`**
Cause: `verify-manifest` needs a manifest to check against. Fix: build one
with `peira dataset build-manifest --dir <dir> --version <v>`.

**`error: ... does not match manifest.json` (sha256 mismatch / missing on disk)**
Cause: a dataset file changed after the manifest was built. Fix: if the
change is intentional, that's a new dataset version — rebuild the manifest
with the bumped version. If not, restore the file (manifests are committed
to git for exactly this reason).

**`...: unsafe file name in manifest (path separators, '..', and absolute paths are not allowed)`**
Cause: the manifest lists a file whose name would escape the dataset
directory (`../`, a subdirectory, or an absolute path). Verification
reports the name instead of opening it — a manifest is not trusted to
choose filesystem paths. Fix: rebuild the manifest from files that live
directly in the dataset directory; case files are `<id>.jsonl` and never
need separators.

**`peira dataset gates` reports failures (exit 1)**
Cause: one or more gates found errors — file, line, and rule are printed
per gate. Fix: address each error (duplicate case ids/content, unknown
family id, attacked input identical to benign, incoherent target), then
re-run. Warnings (e.g. G6 pii-scan) don't fail the suite but go to the
human review queue.

**`peira dataset status` exits 1**
Cause: none — exit 1 here is a status signal, not a failure. It means
the dataset is not release-ready: gates report errors, reviews are
pending, or the manifest is absent or stale. The detail is printed above
the `status: not release-ready` line. Fix: address what is listed — fix
gate errors, complete pending reviews (`peira dataset review --dir
<dir>`), build or refresh the manifest (`peira dataset build-manifest
--dir <dir> --version <v>`) — then re-run.

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

**`error: unreadable case data: <file>:<line>: ...`**
Cause: a review, status, or build-manifest command hit a case-file line
that isn't valid JSON or fails schema validation. Review decisions are
never computed over a partially-read dataset, so the command stops
instead of silently skipping the line. Fix: run
`peira validate --dataset <dir>` — it prints file, line, and rule for
every bad line. Fix the lines, then re-run.

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
doesn't exist — or that exists but isn't a directory. The Rust CLI
rejects a file passed as `--dir` outright; the Python CLI would instead
validate zero cases and exit 0. Fix: check the path — point `--dir` at
the suite directory (e.g. `dataset/trial`), not at a file inside it.

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

**`<path>:<line>: invalid JSON (...)`**
Cause: `peira validate` hit a case-file line that isn't JSON. Fix: fix
the line — the message quotes the parser's complaint (e.g. `Expecting
value: line 1 column 1`). Every line of a `*.jsonl` case file must be
one complete JSON object.

**`error: <run> is not a valid run artifact (...)`**
Cause: `peira report` couldn't parse the artifact file — corrupt JSON,
or JSON with the wrong shape. Fix: re-run to regenerate the artifact;
don't hand-edit artifact files (the analysis lock exists precisely so
edits are detectable).

The parenthetical names the exact problem: `artifact is missing required
field: 'dataset_version'` (the lock is meaningless without the
identifiers it binds — `peira_version` and `dataset_version` are
required), `unknown artifact field: '...'` (the frozen format rejects
fields it doesn't know rather than silently ignoring them),
`artifact field 'config' must be dict, got str` (wrong JSON type), or
`artifact results entry 3 is missing required field: 'family'` (a
malformed result object — same strictness as the Rust core's typed
results vector). A minimal artifact with just the two required fields
loads fine — every other field has a documented default (see ADR D-12).

**`error: cannot write report to <out> (...)`**
Cause: `peira report --out` points somewhere unwritable — a missing
parent directory, or a permissions problem. Fix: create the directory
first, or pick a writable path.

**`...: nesting depth <n> exceeds the 256-level cap`**
Cause: a case-file line nests `[`/`{` deeper than 256 levels
(`peira-cli validate` / the Rust core). Case files stay shallow by
construction — unbounded nesting is a stack-overflow vector. Fix:
flatten the input; no real case nests anywhere near that deep (see
`docs/Dataset.md`).
