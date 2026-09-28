# Troubleshooting

An error catalog: exact error → cause → fix. New user-facing errors get an
entry here in the same PR that introduces them.

**`error: unknown adapter: 'x' (available: 'mock' or a dotted path like 'examples.minimal_adapter')`**
Cause: the adapter name didn't resolve. Fix: use `mock`, or pass a dotted
path (`package.module` with a top-level `adapter`,
`package.module:ClassName`, or `package.module.ClassName`; see
`examples/minimal_adapter.py`). Run from the directory your adapter module
lives under.

**Loading an adapter runs its code: only use paths you trust**
Cause: `peira run --adapter some.module` imports that module to get the
adapter, and importing a module executes it. The working directory is
prepended to `sys.path` first, so a local file can shadow an installed
package of the same name. Fix: only load adapter paths you trust, and
run from a directory whose files you control. The bundled `mock`
adapter is safe.

**`error: unknown suite 'x' (available: smoke, safety-policy, trial, trial-demo, v1)`**
Cause: typo in `--suite`. Fix: `trial-demo` (demo fixture, offline) or
`trial` (the branded 100-case Peira Trial, sealed `1.0.5`).

**`error: suite directory ... not found`**
Cause: you ran `peira` from outside the repo checkout. Fix: run from the
repo root, or `pip install -e .` from a checkout.

**`...: bad primitive: 'xyz'` / `bad severity` / `missing required key`**
Cause: a case file fails schema validation. Fix: run
`peira validate --dataset <dir>`: it prints file, line, and rule. Type
errors look like `bad case_id: expected string`,
`bad benign input: expected object`, or
`bad attacked target_decision: expected string or null`: the value has
the wrong JSON type for that field.

**`confidence 1.4 outside 0..1` (or similar contract errors)**
Cause: your adapter returned a value outside its primitive contract.
Fix: normalize outputs in your adapter (Choice confidence and Score must
be 0..1). Malformed outputs count against your ASR, so fix this before
benchmarking seriously.

**Hugging Face auth / rate-limit errors** (`peira[hf]` adapters)
Cause: `peira[hf]` adapters download models from HF Hub. Gated models
(Llama Prompt Guard 2) additionally require a license click-through.
Fix: `huggingface-cli login`, or set `HF_TOKEN`; for gated models,
accept the license on the model's HF page first. Model weights are
cached after the first download. Revisions are pinned. A download
failure never silently falls back to another revision.

**`lakera adapter needs a Lakera API key`**
Cause: `LAKERA_API_KEY` is not set and no `api_key=` was passed. Fix:
`export LAKERA_API_KEY=<key>` (free Community tier: 10k requests/month
at platform.lakera.ai), or pass `api_key=` to the adapter constructor.

**`lakera API error 401 ...`**
Cause: the API key is invalid or the account lacks Guard API access.
Fix: check that `LAKERA_API_KEY` is valid and the account has Guard API
access enabled. This is terminal: the runner will not retry it.

**`lakera API error 422 ...`**
Cause: the request was rejected as malformed. Fix: this is an adapter
bug, not a retryable failure. Report it. The runner will not retry it.

**`lakera API error 429 ...` / `lakera API error 5xx ...`**
Cause: rate limit or server-side failure. Fix: transient. The runner
retries with backoff (honoring `Retry-After` up to the cap) and adapts
concurrency. If it persists, lower `--max-concurrency`.

**`lakera transport error: ...`**
Cause: the HTTPS request never completed (DNS, connection refused,
timeout). Fix: transient. The runner retries. Check network access to
`api.lakera.ai` if it persists.

**`lakera returned non-JSON response ...`**
Cause: the API answered with something that is not JSON (proxy error
page, WAF block). Fix: check for a proxy or firewall between you and
`api.lakera.ai`; the response body is in the run transcript.

**`lakera response missing boolean 'flagged' ...`**
Cause: the API answered with JSON that lacks the documented `flagged`
boolean (wire shape drift). Fix: the adapter's wire shape is from
Lakera's published API docs and hasn't been exercised against the live
API. Report the response keys from the error so the adapter can be
updated.

**Out-of-memory on local models**
Cause: the model doesn't fit in RAM/VRAM. Fix: use a quantized variant or a
smaller adapter; see `docs/Hardware.md` for per-tier requirements.

**`peira report` warns "analysis lock mismatch"**
Cause: the run artifact was edited after sealing (the report still
renders, but the numbers aren't trustworthy). Fix: don't edit artifacts;
re-run. If you need different config, that's a new run with a new lock.

**`... field 'score': score 2.5 outside 0..1` (artifact load)**
Cause: a call record in the artifact (or partial run) carries a score
outside the 0..1 score space: a hand-edited or corrupt artifact.
The strict loader rejects it so neither backend can disagree about
what an artifact may contain. Fix: don't edit artifacts; re-run.
Scores are real numbers in 0..1, `null` for non-score-primitive calls.

**`error: dataset manifest verification failed:`**
Cause: `peira run` verifies the suite manifest before scoring, and a
case file changed after the manifest was built (hash mismatch, or
counts like `n_cases` drifted). Each mismatch is listed after the
colon. Nothing is scored. The run fails closed so a tampered dataset
can never seal a clean-looking artifact. Fix: don't edit released case
files. Cut a new dataset version instead. For a draft, rebuild the
manifest with `peira dataset build-manifest --dir <suite-dir>` and
re-run.

**`error: partial run was recorded against a different dataset snapshot ...`**
Cause: `peira run --resume` found a partial run whose sealed manifest
digest doesn't match the current suite manifest. The dataset changed
between the interrupted run and the resume. Merging old partial results
with a new dataset would corrupt the run. Fix: delete the
`<adapter>-<suite>.partial.json` file and re-run without `--resume`.

**`error: partial run was recorded with seed N, not M; re-run with the same --seed or drop --resume`**
Cause: `peira run --resume` found a partial run recorded with a different
`--seed` than the one requested. Seeds are part of every call record and
of the analysis lock, so mixing seeds would make the artifact lie about
its own provenance. Fix: resume with the same `--seed` the partial was
written with, or delete the `<adapter>-<suite>.partial.json` file and
re-run from scratch.

**`error: peira pricing table ...`**
Cause: `peira run` recomputes adapter costs from the pinned pricing
table (`peira/data/pricing.json` in the package, source and pin date
sealed into every artifact). The exact message names the problem:
`peira pricing table is missing or unreadable: ...` (a broken install;
the file ships as package data), `peira pricing table is corrupt: ...`
(not valid JSON), or `peira pricing table has the wrong shape: ...`
(the top level must be an object with a `models` object). Fix: reinstall
peira; if it was hand-edited, restore it. Unknown models price at 0.0
by design, so there is no reason to add entries by hand.

**`error: partial run has malformed result entry at index N ...`**
Cause: `peira run --resume` found a partial run whose `results` entry at
position N isn't a well-formed result object (a scalar, or an object with
the wrong fields). The file was hand-edited or corrupted. The resume
refuses to guess what the entry meant. Fix: delete the
`<adapter>-<suite>.partial.json` file and re-run without `--resume`.

**`error: no cases found in ...`**
Cause: the suite directory has no `.jsonl` files. Fix: check the path;
`dataset/trial-demo/cases.jsonl` ships with the repo.

**`error: unknown famil(ies): x (known families: ...)`**
Cause: `peira run --families` got a family id that isn't in the
registry. Fix: pick from the list in the error. The twenty canonical
ids are in `docs/Taxonomy.md`. If the id is `safety_policy`, use
`--suite safety-policy` instead: it is a suite, not an attack family.

**`error: --families matched no cases in ...`**
Cause: the ids are valid, but the suite has no cases for them (e.g. a
Tier 2 family before its cases are authored). Fix: drop `--families` or
check which families the suite covers.

**`peira run` exits with code 3**
Cause: none. The run completed. Exit 3 means ranking-ineligible (one of
the Methodology eligibility floors failed; the notes are printed with the
results). Fix: none needed for a demo; for a real submission, clear the
named gate. Exit codes: 0 clean, 1 user error, 2 infrastructure error,
3 completed but unranked.

**`error: dataset directory ... not found`**
Cause: `peira dataset build-manifest` / `verify-manifest` got a `--dir`
that doesn't exist. Fix: check the path. Dataset directories live under
`dataset/` (e.g. `dataset/v1`).

**`error: invalid cases, manifest not written`**
Cause: `build-manifest` validates every case before writing. One or more
lines failed schema validation (file, line, and rule are printed). Fix:
fix the cases, then rebuild. A manifest is never written for invalid data.

**`error: version ... is not semver ...; manifest not written`**
Cause: `build-manifest --version` must be a semantic version
(`1.0.0`, `0.1.0-trial`), per the versioning rules in `docs/Dataset.md`.
Fix: pass a semver version; prerelease suffixes like `-trial` are allowed.

**`error: N critical case(s) missing severity notes; manifest not written`**
Cause: the severity rubric asks the author to say why a case earned its
tier in the case notes, and the release seal enforces it for
critical-severity cases. Fix: add a severity justification to each listed
case's `notes` field (see `docs/Severity-Rubric.md`), then rebuild.

**`error: content changed since version ... was sealed; bump the version, manifest not written`**
Cause: a manifest already exists for that version but the dataset files
changed since. Versioning rule 1 says any case added, changed, or
removed is a new version. Rebuilding byte-identical content under the
same version is fine; changed content is not. Fix: rebuild with the
bumped `--version`.

**`error: no manifest.json in ...; run 'peira dataset build-manifest' first`**
Cause: `verify-manifest` needs a manifest to check against. Fix: build one
with `peira dataset build-manifest --dir <dir> --version <v>`.

**`error: ... does not match manifest.json` (sha256 mismatch / missing on disk)**
Cause: a dataset file changed after the manifest was built. Fix: if the
change is intentional, that's a new dataset version. Rebuild the manifest
with the bumped version. If not, restore the file (manifests are committed
to git for exactly this reason).

**`...: unsafe file name in manifest (path separators, '..', and absolute paths are not allowed)`**
Cause: the manifest lists a file whose name would escape the dataset
directory (`../`, a subdirectory, or an absolute path). Verification
reports the name instead of opening it. A manifest is not trusted to
choose filesystem paths. Fix: rebuild the manifest from files that live
directly in the dataset directory; case files are `<id>.jsonl` and never
need separators.

**`peira dataset gates` reports failures (exit 1)**
Cause: one or more gates found errors. File, line, and rule are printed
per gate. Fix: address each error (duplicate case ids/content, unknown
family id, attacked input identical to benign, incoherent target,
missing score reference), then
re-run. Warnings (e.g. G6 pii-scan) don't fail the suite but go to the
human review queue.

**`peira dataset status` exits 1**
Cause: none. Exit 1 here is a status signal, not a failure. It means
the dataset is not release-ready: gates report errors, reviews are
pending, or the manifest is absent or stale. The detail is printed above
the `status: not release-ready` line. Fix: address what is listed. Fix
gate errors, complete pending reviews (`peira dataset review --dir
<dir>`), build or refresh the manifest (`peira dataset build-manifest
--dir <dir> --version <v>`), then re-run.

**`peira dataset new: error: argument --family: invalid choice: 'x'`**
Cause: the family id isn't one of the eleven ids `dataset new` can
scaffold (the ten v1 families plus the safety-policy suite). A valid
v2 family id like `instruction_override` is canonical but has no case
template yet. Fix: pick from the list in the error; the full list
with descriptions is in `docs/Taxonomy.md` (see
`python/peira/families.py` for the registry).

**`error: cannot write to ...` from `peira dataset new --out`**
Cause: the output file's directory doesn't exist or isn't writable. Fix:
create the directory first, or drop `--out` to print to stdout.

**`error: unknown case id 'x' in ...`**
Cause: `peira dataset review approve/reject` got a case id that isn't in
the dataset directory. Fix: check the id. `peira dataset review --dir
<dir>` lists pending case ids.

**`error: unreadable review state: ...`**
Cause: `review.json` is corrupt. Fix: restore it from git (review
decisions are committed). If it was never created, there's nothing to
restore. An absent `review.json` simply means nothing reviewed yet.

**`error: unreadable case data: <file>:<line>: ...`**
Cause: a review, status, or build-manifest command hit a case-file line
that isn't valid JSON or fails schema validation. Review decisions are
never computed over a partially-read dataset, so the command stops
instead of silently skipping the line. Fix: run
`peira validate --dataset <dir>`: it prints file, line, and rule for
every bad line. Fix the lines, then re-run.

**`error: N reviews pending; manifest not written`**
Cause: `build-manifest --require-reviews` found unreviewed cases. Fix:
review them (`peira dataset review --dir <dir>`), or drop
`--require-reviews` for a draft manifest (never release one).

**`error: --dir is required`**
Cause: `peira dataset review` without `--dir`. Fix: pass
`--dir <dataset-dir>`.

**`peira-cli validate`: `validated N cases, M invalid`**
Cause: the Rust validator (`crates/peira-cli`, used in CI) found cases
that fail schema validation. Each offending line is printed as
`file:line: <rule>` above the summary. Fix: same as the Python
`peira dataset gates` failures: fix the case file. Error rules are
identical across both implementations.

**`peira-cli`: `error: dataset directory ... not found`**
Cause: `peira-cli validate` / `verify-manifest` got a `--dir` that
doesn't exist, or that exists but isn't a directory. The Rust CLI
rejects a file passed as `--dir` outright; the Python CLI would instead
validate zero cases and exit 0. Fix: check the path. Point `--dir` at
the suite directory (e.g. `dataset/trial`), not at a file inside it.

**`peira-cli`: `error: no manifest.json in ...; run 'peira dataset build-manifest' first`**
Cause: `peira-cli verify-manifest` needs a manifest to check against.
Fix: build one with the Python CLI first. The Rust side verifies
manifests, it doesn't author them.

**`peira-cli`: `error: unreadable manifest: ...`**
Cause: `manifest.json` is missing, corrupt, or not the expected shape.
Fix: restore it from git, or rebuild with
`peira dataset build-manifest`.

**`peira-cli`: `error: ... does not match manifest.json:`**
Cause: a case file changed after the manifest was built (hash mismatch,
or counts like `n_cases` drifted). Each mismatch is listed as
`  - <file>: <what changed>`. Fix: don't edit released case files. 
cut a new dataset version instead. For a draft, rebuild the manifest.

**``error: the `cargo` binary was not found on PATH.``**
Cause: you ran `scripts/build_core_ext.py` without the Rust toolchain.
Fix: install it (https://rustup.rs), or skip the build entirely. The
extension is an optional accelerator; peira runs on the pure-Python
reference implementation without it.

**`error: cargo build failed (exit N).`**
Cause: the PyO3 extension failed to compile. Fix: check you have a
Python 3.10+ interpreter with development headers (`Python.h`). On
Debian/Ubuntu that's `python3-dev`. Then re-run
`python scripts/build_core_ext.py`.

**`error: no cdylib found in target/...`**
Cause: cargo finished but produced no shared library (wrong target dir
or an interrupted build). Fix: `cargo clean -p peira-python` and rebuild
with `python scripts/build_core_ext.py`.

**`error: built extension failed to import:`**
Cause: the compiled `peira._core` doesn't load in your Python (usually a
version mismatch. The extension is built for the interpreter that ran
the script). Fix: rebuild with the Python you actually use, and make
sure no stale `_core*.so` / `_core*.pyd` from another interpreter sits in
`python/peira/`.

**`warning: unreadable manifest at ... (…); recording dataset_version='0.1.0-demo'.`**
Cause: `peira run` found a `manifest.json` in the suite directory but
couldn't parse it, so the run artifact records the fallback dataset
version instead of the real one. Fix: rebuild it with
`peira dataset build-manifest --dir <suite-dir> --version <v>` and re-run.
(The analysis lock still seals whatever version was recorded; this
warning is about accuracy of the label, not integrity of the run.)

**`<path>:<line>: invalid JSON (...)`**
Cause: `peira validate` hit a case-file line that isn't JSON. Fix: fix
the line. The message quotes the parser's complaint (e.g. `Expecting
value: line 1 column 1`). Every line of a `*.jsonl` case file must be
one complete JSON object.

**`error: <run> is not a valid run artifact (...)`**
Cause: `peira report` couldn't parse the artifact file: corrupt JSON,
or JSON with the wrong shape. Fix: re-run to regenerate the artifact;
don't hand-edit artifact files (the analysis lock exists precisely so
edits are detectable).

The parenthetical names the exact problem: `artifact is missing required
field: 'dataset_version'` (the lock is meaningless without the
identifiers it binds. `peira_version` and `dataset_version` are
required), `unknown artifact field: '...'` (the v2 format rejects fields
it doesn't know rather than silently ignoring them),
`artifact field 'config' must be dict, got str` (wrong JSON type),
`artifact results entry 3 is missing required field: 'family'` (a
malformed result object), or
`artifact results entry 3 call record 'benign' is missing required field:
'malformed'` (a truncated call record; same strictness as the Rust
core's typed results vector). A minimal artifact with just the two
required fields loads fine. The remaining defaults are documented in
ADR D-12.

**`error: <run> uses the pre-S8b artifact schema (no A3 metric summary)`**
Cause: the artifact was sealed before the S8b rewiring, so its
`metrics` lack the A3 summary sections (`calibration`,
`selective_prediction`, `score_diagnostics`, …) the report renders.
The artifact itself is valid (it's just from an older schema), so
`peira report` refuses with this message instead of rendering a
half-empty page or calling the artifact corrupt. Fix: re-run the
suite to generate a current artifact.

**`error: unsupported artifact_version '1': ...`**
Cause: the artifact was produced before the v2 measurement contract.
Peira never migrates v1 artifacts. The numbers were computed under
weaker semantics (flat results, no call records, no refusal tracking),
and a migration shim would bless them as v2. Fix: re-run the adapter to
produce a v2 artifact (the suite cases are unchanged; only the harness
outputs moved).

**`error: cannot write report to <out> (...)`**
Cause: `peira report --out` points somewhere unwritable: a missing
parent directory, or a permissions problem. Fix: create the directory
first, or pick a writable path.

**`...: nesting depth <n> exceeds the 256-level cap`**
Cause: a case-file line nests `[`/`{` deeper than 256 levels
(`peira-cli validate` / the Rust core). Case files stay shallow by
construction. Unbounded nesting is a stack-overflow vector. Fix:
flatten the input; no real case nests anywhere near that deep (see
`docs/Dataset.md`).

**`error: --max-concurrency must be >= 1 (got N)` / `error: --max-attempts must be >= 1 (got N)` / `error: --call-timeout must be > 0 (got N)`**
Cause: `peira run` got a non-positive `--max-concurrency`,
`--max-attempts`, or `--call-timeout`. Fix: pass a positive value
(`--max-concurrency 8`, `--max-attempts 3`).

**`error: --rlimit-cpu-seconds must be > 0 (got N)` / `--rlimit-as-mb must be > 0` / `--rlimit-fsize-mb must be > 0`**
Cause: `peira run` got a non-positive `--rlimit-cpu-seconds`,
`--rlimit-as-mb`, or `--rlimit-fsize-mb`. Fractional values are allowed
and round up to the limit's granularity (CPU seconds round up to whole
seconds). Fix: pass a positive value (`--rlimit-cpu-seconds 3600`,
`--rlimit-as-mb 4096`).

**`error: cannot write transcript to <path>: <reason>`**
Cause: `peira run --transcript` points somewhere unwritable: a missing
parent directory or a permissions problem. The runner probes the path
before dispatching anything, so a bad path fails fast instead of
mid-run. Fix: create the directory first, or pick a writable path.

**`error: cannot use cache directory <dir>: <reason>` / `error: cache directory <dir> is not writable: <reason>`**
Cause: `peira run --cache-dir` points somewhere unusable or unwritable.
Like the transcript path, the cache directory is probed before the run
starts. Fix: create the directory first, or pick a writable path. A
cache write that fails *mid-run* is silently skipped. The cache is a
pure optimization, never load-bearing for the measurement.

**`error: transcript <path> has no entries`**
Cause: `peira replay` got an empty transcript file. Fix: replay the
transcript written by a real run (`peira run --transcript <path>`).

**`error: transcript <path> covers N adapters (...); a replay transcript must come from a single adapter run`**
Cause: the transcript mixes entries from different adapters (or
adapter versions), e.g. two runs appended to one file by hand. Replay
re-scores one measurement, so it refuses a mixed transcript. Fix: replay
each run's transcript separately.

**`error: transcript <path> has conflicting seeds [...]; a replay transcript must come from a single run`**
Cause: the transcript mixes entries recorded under different run seeds.
Fix: replay each run's transcript separately.

**`error: transcript <path> has duplicate entry for case 'x' variant 'y'`**
Cause: the transcript has two entries for one variant call. The file
was edited by hand or concatenated. Fix: replay the original transcript
file; resumed runs never duplicate entries (the runner skips dispatch
indices already on record).

**`error: transcript <path> is missing N case(s): ...; replay needs the full suite transcript`**
Cause: the transcript doesn't cover every case in `--suite`. It is a
partial run's transcript, or from a different suite. Fix: replay with
the matching `--suite`, or replay the completed run's transcript.

**`interrupted; partial run saved; re-run with --resume.`**
Cause: Ctrl-C during `peira run`. The runner checkpoints completed
cases (and closes the transcript cleanly) before exiting, so nothing
measured is lost. Fix: re-run the same command with `--resume`, or
drop the `--resume` and the stale `.partial.json` to start over.
In-flight provider calls can't be force-cancelled; they are abandoned
and their cases re-run on resume.

## A2 adapter errors

**`this adapter requires the 'hf' extra (torch and transformers): install it with: pip install 'peira[hf]'`**
Cause: you instantiated a Hugging Face adapter (`shieldstral`,
`protectai-prompt-injection`, `llama-prompt-guard-2`, `qwen3guard-gen`,
`granite-guardian`, `shieldgemma`, `wildguard`) without the optional
dependency. Fix: `pip install "peira[hf]"` (the base package
stays dependency-free by design). The LLM baselines fail closed the same way, naming their own
extra: `the peira[openai] extra is required for OpenAIAdapter; 
install it with: pip install "peira[openai]"`,
`the peira[anthropic] extra is required for AnthropicAdapter; 
install it with: pip install "peira[anthropic]"`, and
`the peira[google] extra is required for GoogleAdapter; 
install it with: pip install "peira[google]"`.

**`sentencepiece` / `protobuf` missing when loading `wildguard`**
Cause: WildGuard's tokenizer is Mistral-7B-v0.3's SentencePiece
tokenizer; transformers needs the `sentencepiece` and `protobuf`
packages to load it, and neither ships with `peira[hf]`. The import
fails at load time. Fix: `pip install sentencepiece protobuf`.

**`...: hf_revision must be a pinned commit hash, never 'main'/'latest'`**
Cause: internal sanity check. An adapter was constructed with a
floating revision. You can't hit this through the bundled adapters
(their revisions are pinned constants); it fires only for a subclass
that overrides the pin with something unpinned. Fix: pin the exact
commit hash.

**`Cannot download gated model '...' (HTTP ...). Accept the model license on its Hugging Face page ...`**
Cause: Llama Prompt Guard 2 is gated. You haven't accepted the Meta
Llama 4 Community License on the model's HF page, or `huggingface-cli
login` / `HF_TOKEN` isn't set. Fix: accept the license (one click on
the model repo), then authenticate locally. The download is a one-time
cost; weights are cached afterwards.

**`Transient Hugging Face Hub error (HTTP ...) while loading '...'; safe to retry.`**
Cause: the model download hit a transient Hub error (rate limit or
5xx). This is raised with retry metadata, so `peira run` retries it
under `--max-attempts` like any transient provider failure. Fix: wait
and re-run; no action needed beyond the retry.

**`no pinned model registered for adapter '...' (known: ...)`**
Cause: code asked `peira.api_pins.get_pinned_model()` for an adapter
name the pin registry doesn't know. This is a packaging bug, not a user
error: the registry must cover every API adapter. Fix: add the
adapter's verified model id to `peira.api_pins.PINNED_API_MODELS`
(and a matching pin entry in `python/peira/data/pricing.json`).

**`model '...' was retired by its vendor; use '...' instead`**
(also raised as `pinned model '...' for adapter '...' was retired by
its vendor; use '...' instead` from the pin registry itself)
Cause: you passed an explicitly deprecated model id to an LLM baseline
adapter (`DeprecatedPinError`), or the registry pin itself is stale.
Deprecated ids may 404 or resolve to different weights than when they
were pinned, so peira fails closed instead of running an
unreproducible measurement. Fix: use the named replacement id. If you
maintain the registry, move the old id into
`peira.api_pins.DEPRECATED_PINS` and pin the replacement.

**`<adapter> does not support primitive 'score'`** (HF adapters)
Cause: the HF guardrail adapters are classifiers. They support
`choice` and `abstain` only. A `score` case fails closed as malformed
rather than being force-fit. Fix: none for the adapter; the Trial's
score cases are measured by the LLM and Jev adapters.

**`tokenizer for '...' has no single-token id for yes (tried ...) ...`**
Cause: Shieldstral reads its verdict from the first-token logprobs of
` yes`/` no`. The loaded tokenizer has no single-token id for either
spelling, so the probability can't be read honestly. This is a
tokenizer/model mismatch, not a retryable failure. Fix: check the
pinned revision actually matches `mistralai/Shieldstral-1.0-3B`;
don't substitute tokenizers.

**`tokenizer for 'Qwen/Qwen3Guard-Gen-4B' has no single-token id for Safe (tried ...) ...`**
Cause: Qwen3Guard reads its verdict from the first-token logprobs of
` Safe`/` Unsafe`/` Controversial`. The loaded tokenizer has no
single-token id for one of the three label spellings (tried with and
without the leading space), so the probability can't be read honestly.
This is a tokenizer/model mismatch, not a retryable failure. Fix:
check the pinned revision actually matches
`Qwen/Qwen3Guard-Gen-4B`; don't substitute tokenizers.

**`chat template for 'Qwen/Qwen3Guard-Gen-4B' did not return text; cannot build the moderation prompt`**
Cause: Qwen3Guard is prompted through the model's own chat template
(`apply_chat_template`); the template returned something other than
text, so the moderation prompt can't be built. This is a
tokenizer/model mismatch, not a retryable failure. Fix: check the
pinned revision actually matches `Qwen/Qwen3Guard-Gen-4B`; don't
substitute tokenizers.

**`tokenizer for 'ibm-granite/granite-guardian-4.1-8b' has no single-token id for yes (tried ...) ...`**
Cause: Granite Guardian reads its verdict from the first-token
logprobs of `yes`/`no`. The loaded tokenizer has no single-token id
for either spelling (tried bare first, then with the leading space),
so the probability can't be read honestly. This is a tokenizer/model
mismatch, not a retryable failure. Fix: check the pinned revision
actually matches `ibm-granite/granite-guardian-4.1-8b`; don't
substitute tokenizers.

**`tokenizer for 'google/shieldgemma-2b' has no vocab entry for Yes/No labels: ...`**
Cause: ShieldGemma reads its verdict from the first-token logprobs of
the `Yes`/`No` vocab entries (mirroring the official scoring snippet).
The loaded tokenizer has no such vocab entries, so the probability
can't be read honestly. This is a tokenizer/model mismatch, not a
retryable failure. Fix: check the pinned revision actually matches
`google/shieldgemma-2b`; don't substitute tokenizers.

**`tokenizer for 'allenai/wildguard' has no single-token id for yes (tried ...) ...`**
Cause: WildGuard reads its verdict from the first-token logprobs after
the `"Harmful request: "` prefill. The loaded tokenizer has no
single-token id for the yes/no label spellings (tried bare, then with
the leading space), so the probability can't be read honestly. This is
a tokenizer/model mismatch, not a retryable failure. Fix: check the
pinned revision actually matches `allenai/wildguard`; don't substitute
tokenizers.

**`chat template for 'ibm-granite/granite-guardian-4.1-8b' did not return text; cannot build the moderation prompt`**
Cause: Granite Guardian is prompted through the model's own chat
template (`apply_chat_template`); the template returned something
other than text, so the moderation prompt can't be built. This is a
tokenizer/model mismatch, not a retryable failure. Fix: check the
pinned revision actually matches
`ibm-granite/granite-guardian-4.1-8b`; don't substitute tokenizers.

**`llama-prompt-guard-2 tokenizer has no CLS/SEP token ids`**
Cause: the loaded tokenizer reports no CLS/SEP token ids, so chunks
can't be wrapped for the classification head (which pools position
0). This is a tokenizer/model mismatch, not retryable. Fix: check
the pinned revision matches the Prompt Guard 2 repo; don't substitute
tokenizers.

**`OPENAI_API_KEY is not set; OpenAIAdapter needs it (and the peira[openai] extra)`**
Cause: no API key found in the environment (or the explicit `api_key=`
argument). Anthropic reads `ANTHROPIC_API_KEY`; Google reads
`GOOGLE_API_KEY` with fallback to `GEMINI_API_KEY`. Fix: export the
key; keys never appear in transcripts or artifacts.

**`<name> does not support primitive 'x'`** (LLM baselines)
Cause: the adapter was asked for a primitive outside `choice`, `score`,
`abstain`. You can't hit this through the bundled adapters on the Trial
(they cover all three). It fires only for a genuinely unknown
primitive string. Fix: check the primitive name.

**`<name>: model output failed schema validation twice: ...`**
Cause: the provider returned output that didn't validate against the
constrained-decoding schema on both the first attempt and the single
schema-repair retry. The message quotes both validation errors. Fix:
this is usually provider-side flakiness. Re-run (the runner retries
transient failures). If it persists for a model, report it: the schema
is per-call and the provider claims to honor it.

**`OpenAI request timed out: ...` / `Anthropic request timed out: ...`**
Cause: the provider SDK's own timeout fired (mapped to status 408 so
the runner treats it as transient and retries). Fix: re-run; sustained
timeouts mean the provider is degraded.

**`OpenAI connection failed: ...` / `Anthropic connection failed: ...`**
Cause: the SDK hit a connection error mid-call. Raised as a builtin
`ConnectionError` (not `ProviderError`) so the runner treats it as
transient and retries under `--max-attempts`. Fix: re-run; sustained
failures mean your network or the provider is down.

**`OpenAI returned no choices`**
Cause: the provider answered with an empty choices list: a malformed
provider response, not a retryable failure. Fix: re-run; if it
persists, the provider is misbehaving.

**`jev does not support primitive 'x'`**
Cause: Jev was asked for a primitive outside `choice`, `score`,
`abstain`. You can't hit this through the bundled adapters on the Trial
(they cover all three). Fix: check the primitive name.

**`jev adapter needs a TypeSafe API key: set the TYPESAFE_API_KEY environment variable (or pass api_key=...)`**
Cause: no Jev API key. Jev is gated on access. The message says where
to request it. Fix: `export TYPESAFE_API_KEY='your-key-here'`

**`jev adapter pins model 'jev-1.13.0'; got '...'`**
Cause: a floating or wrong model id was passed. Jev measurements must
name the exact model. `jev-latest` and friends are rejected. Fix:
don't pass `model=` at all (the default is the pin), or pass the exact
pinned id.

**`jev API error 401: ...; check that TYPESAFE_API_KEY is valid and the account has Jev access.`**
Cause: bad or unauthorized key. Terminal: the runner won't retry it.
Fix: check the key and your Jev access.

**`jev API error 422: ...; the request was rejected; this is an adapter bug, not a retryable failure.`**
Cause: Jev rejected the request shape. The adapter validates every
question client-side before sending, so this means API drift. Fix:
report it; don't retry.

**`jev transport error: ...` (status 408)**
Cause: the connection dropped, DNS failed, or the request timed out.
Raised as status 408 so `peira run` treats it as transient and retries
under `--max-attempts`. Fix: re-run; sustained 408s mean your network
or Jev's endpoint is degraded.

**`jev API error 429` / `jev API error 529` / `jev API error 5xx`**
Cause: rate limit, overload, or provider error. `retry_after` comes
from the `Retry-After` response header when the API sends one;
otherwise the runner backs off on its own schedule. Fix: none, but if
every attempt 429s, lower `--max-concurrency`.

**`jev built ... question ...` (e.g. `jev built a malformed question 'x': not an object`)**
Cause: a question failed the adapter's client-side shape check
(`type` + `instructions`, plus `criteria` for choice/score) before it
was sent. You can't hit this through the bundled builders. It means
an adapter bug. Fix: report it.

**`jev returned non-JSON response (HTTP ...)` / `jev returned a non-object JSON response`**
Cause: the transport returned something that isn't the documented JSON
object. Terminal (API drift or a broken transport). Fix: check for a
proxy mangling responses; otherwise report it.

**`jev response missing 'answers' object` / `jev response missing answer 'decision'`**
Cause: the response lacks the per-question answers the API promises
(`choice`, `score`, or `abstain` under each question name). Terminal. Fix:
same as above: likely API drift.

**`jev returned choice 'x' outside the offered labels [...]; adapter bug or API drift.`**
Cause: Jev returned a choice that wasn't among the labels sent. The
adapter refuses to map it to anything (guessing would corrupt the
measurement). Terminal. Fix: report it.

**`jev score answer has no numeric score: ...` / `jev abstain answer has no numeric abstain value: ...`**
Cause: the score/abstain answer is missing its numeric field. Terminal:
same drift handling as above.

**`jev returned non-numeric confidence: ...` / `jev returned non-numeric abstain: ...`**
Cause: a confidence/probability field wasn't a number. Clamped only
when numeric; non-numeric is terminal. Fix: report it.

**`error: <run> not found` (from `peira compare`)**
Cause: one of the two artifact paths doesn't exist. Fix: check the
paths. `peira compare` takes two positional artifact files.

**`error: hardness needs at least 2 run artifacts` (from `peira hardness`)**
Cause: fewer than two artifact paths were given. Hardness and transfer
are cross-adapter views; one run has nothing to stratify against. Fix:
pass two or more run artifact paths.

**`error: <run> not found` (from `peira hardness`)**
Cause: one of the artifact paths doesn't exist. Fix: check the paths.

**`error: <run> is not a valid run artifact (...)` (from `peira hardness`)**
Cause: the file isn't valid JSON or isn't a sealed run artifact. Fix:
point at `peira run` output files.

**`error: cannot write hardness report to <out> (...)`**
Cause: `peira hardness --out` points somewhere unwritable: a missing
parent directory, or a permissions problem. Fix: create the directory
first, or pick a writable path.

**`error: artifacts are not comparable: ...`**
Cause: the two artifacts weren't scored under the same trial. The
message names the mismatch: different `suite`, different
`dataset_version`, different `artifact_version` (measurement contract),
or different `manifest_sha256` (dataset bytes). Fix: compare runs of
the same suite and dataset version; re-run the adapter if the dataset
moved on. Comparing across dataset versions is refused deliberately:
the per-case outcomes wouldn't be paired observations of the same
trial.

**`error: artifacts share no cases: nothing to compare`**
Cause: the two artifacts have no `case_id` overlap (different case
sets, or one run was truncated). Fix: make sure both runs covered the
same suite; compare always uses the case-id intersection.

**`error: cannot write comparison to <out> (...)`**
Cause: `peira compare --out` points somewhere unwritable: a missing
parent directory, or a permissions problem. Fix: create the directory
first, or pick a writable path.

**`peira compare` says "withheld" for McNemar / Bradley-Terry / deltas**
Cause: not an error. The sample-size discipline. McNemar and
Bradley-Terry need paired *choice*-primitive cases (score/abstain
cases don't enter the right/wrong test); Bradley-Terry needs ≥ 30
comparisons; deltas need ≥ 30 paired cases. Below the gates the
estimate is withheld rather than fabricated. The head-to-head counts
and per-family win rates still render.

**`error: <path> not found` (from `peira lottery`)**
Cause: one of the artifact paths doesn't exist. Fix: check the
paths. `peira lottery` takes one or more positional artifact files.

**`error: <path> is not a valid run artifact (...)` (from `peira lottery`)**
Cause: the file isn't a sealed run artifact (bad JSON, or a JSON file
that isn't a run artifact). Fix: point at the `.json` files `peira run`
wrote to the runs directory.

**`error: <path>: cannot decode per-case results (...)` (from `peira lottery`)**
Cause: the artifact's per-case results don't decode (a hand-edited
artifact, or an artifact from an incompatible peira version). Fix:
re-run the adapter on the current peira; don't hand-edit artifacts.

**`error: no families found in the given runs` (from `peira lottery`)**
Cause: none of the artifacts contain any per-case results (empty
runs). Fix: pass artifacts from completed runs.

**`error: cannot write lottery JSON to <out> (...)` (from `peira lottery`)**
Cause: `peira lottery --json` points somewhere unwritable: a missing
parent directory, or a permissions problem. Fix: create the directory
first, or pick a writable path.

**`peira lottery` reports "Lottery index: undefined"**
Cause: not an error. No family yields two runs ranked in both the full
and the reduced ranking (too few eligible runs for a pairwise
comparison). Fix: add more ranking-eligible runs; a lottery analysis
needs at least two runs that stay eligible when any one family is
removed.

**`error: unknown families: <names> (not present in the given runs)` (from `peira lottery`)**
Cause: `--families` names a family that appears in none of the given
artifacts (often a typo). Fix: check the spelling against the family
names in the runs; omit `--families` to use the union across the runs.

**`error: rank_runs: families must not be empty` (from `peira lottery`)**
Cause: `--families` left only one family to analyze, so removing it
leaves nothing to rank on (leave-one-out needs at least two families).
Fix: pass at least two families, or omit `--families` to use the union
across the runs.

**`error: cannot write dashboard JSON to <out> (...)` (from `peira dashboard run`)**
Cause: `--out` points somewhere unwritable: a missing parent
directory, or a permissions problem. Fix: create the directory first,
or pick a writable path.

**`error: cannot write leaderboard JSON to <out> (...)` (from `peira dashboard leaderboard`)**
Cause: `--out` points somewhere unwritable: a missing parent
directory, or a permissions problem. Fix: create the directory first,
or pick a writable path.

**`error: cannot write comparison JSON to <out> (...)` (from `peira dashboard compare`)**
Cause: `--out` points somewhere unwritable: a missing parent
directory, or a permissions problem. Fix: create the directory first,
or pick a writable path.

**`No cases found.` (from `peira runs query`)**
Cause: not an error. No indexed case rows match the filters
(`--adapter`, `--family`, `--flip-direction`, confidence bounds, or
`--limit`). Fix: loosen the filters and check the spelling of
`--family` against the family names in the runs.
