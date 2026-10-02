# Validation Systems Audit — peira agentic-dev readiness

**Auditor:** validation-audit subagent (read-only) · **Date:** 2026-10-02
**Repo:** `~/workspace/peira-agentic-audit` (branch `agentic-dev-audit`, main `fc289590`)
**Scope:** dataset gates, artifact seal/verify, Rust/Python parity tests,
`scripts/artifact_smoke.py`, `peira doctor`.

## Headline

No P1s. The validation architecture is genuinely strong: gates are
agent-actionable, the seal's cross-backend determinism is pinned by a
golden hash, parity tests use the right exactness split, and CI runs the
suite in both backends. The real damage is concentrated in two places:

1. **`scripts/artifact_smoke.py` is broken under the maturin backend** —
   its stale-build checks are setuptools-era and now false-fail on a fresh
   clone (P2) while the checks that remain are vacuous (P2).
2. **The gates crash on the bad data they're meant to report** — a
   non-string `prompt` (which G1 allows) kills `run_gates` with an
   unhandled `TypeError` instead of producing a finding (P2).

`peira doctor` misses the exact environment failure classes agents
actually hit (stale `.so`, `PEIRA_NO_RUST` confusion) — P2s. The seal is
tamper-evidence, not authenticity; the codebase knows this but
overstates it in two places — P2.

---

## P1 — bad data / bad seals slipping through

*None found.* Every P1-shaped candidate I chased resolved into a
documented design decision with a backstop (details under P2-3/P2-4).
Specifically: forged seals pass `verify()`, but the holdout pipeline
re-executes rather than trusting artifacts
(`docs/Holdout-Ranking-Design.md:23`), and public submissions require a
signed attestation (`docs/Admission-Rules.md`, "Submission bundle" §5).
The seal's *documented* purpose — tamper-evidence — holds and is
test-pinned.

---

## P2 — meaningful gaps

### P2-1 · `artifact_smoke.py` false-fails on a fresh clone under maturin

**File:** `scripts/artifact_smoke.py`, driver check at line 253,
`main()` at lines 524–529.

The stale-build logic is setuptools-era and was never adapted when the
maturin backend landed (commit `76f00d6f` only fixed staging). Trace:

1. `main()`: `tree_sos = find_native_extensions(pkg_dir)` → empty on a
   fresh clone (the prebuilt `_core*.so` is gitignored — confirmed: this
   worktree has no `.so` right now). So `so_hash = "none"` (line 524).
2. Under maturin, `pip wheel` **always compiles `peira._core` from
   `crates/peira-python`** (`pyproject.toml` `[tool.maturin]`,
   `module-name = "peira._core"`) and embeds it in the wheel — the tree's
   prebuilt `.so` is irrelevant to wheel contents (it's only for
   `maturin develop`).
3. The in-venv driver then runs, with `expected_so_hash == "none"`:
   `check("no-stray-native-ext", not sos, "wheel embeds a _core binary
   the tree did not build")` (line 253). `sos` is non-empty (the wheel
   legitimately embeds the freshly built extension) → **FAIL** →
   `SMOKE-RESULT FAIL` → exit 2.

So on any worktree where `maturin develop` hasn't been run — the normal
post-clone state — the smoke fails on a correctly built wheel. The
script even logs the wrong mental model: `"native ext: none in tree ->
pure-Python artifact expected"` — under maturin the wheel is never
pure-Python. AGENTS.md lists this smoke as "must stay green"; a gate
that reds on good builds trains agents to distrust or skip it.

### P2-2 · The smoke's stale-`.so` checks are vacuous under maturin

Same file, same root cause. What the smoke *claims* vs. what is true:

- The driver **skips** the installed-binary hash check when `"maturin"
  in backend` (comment: "a hash comparison here would be vacuous"),
  claiming "staleness is covered by the worktree mtime check (prebuilt
  .so older than newest Rust source fails the smoke before the wheel is
  built)".
- But the wheel never embeds the tree's `.so` under maturin — maturin
  compiles fresh from the staged `crates/` copy. The mtime check on the
  tree `.so` therefore protects nothing about the artifact; and
  `inspect_wheel`'s stale-by-omission check (`if tree_sos and not
  so_members`) can never fire either, because a maturin wheel always
  contains a `_core`.
- Net: the only real staleness protection is "the wheel was built fresh
  in this run" — true, but unstated as the mechanism, and the script's
  comments claim coverage that doesn't exist. If a lane ever goes back
  to trusting these checks ("the smoke verified the binary is fresh"),
  that trust is misplaced. The checks should be rewritten for the
  maturin reality: assert the wheel's embedded `_core` was produced by
  *this* build (e.g. build-id/mtime inside the fresh stage dir), and
  drop the tree-`.so` comparisons.

### P2-3 · `run_gates` crashes instead of reporting a non-string `prompt`

**Files:** `python/peira/gates.py:392` (`gate_near_dedup`),
`python/peira/gates.py:416` (`_g9_case_text`),
`python/peira/schema.py:297` (`_validate_case_dict_py`).

G1/the schema never type-checks `prompt` — only that `input` is a dict
carrying `options`. But G9 does raw string concatenation:

```python
b = case.get("benign", {}).get("input", {}).get("prompt", "")
a = case.get("attacked", {}).get("input", {}).get("prompt", "")
return (b + "\n" + a).strip()
```

A case with `"prompt": ["not", "a", "string"]` passes G1, then kills the
entire gate run:

```
CRASH: TypeError can only concatenate list (not "str") to list
```

(empirically confirmed against the source tree, `PEIRA_NO_RUST=1`).
A validator must never crash on the bad data it exists to report — an
agent gets a traceback instead of `cases.jsonl:1: bad prompt type`, and
a lane that catches exceptions broadly could misread this as "no
findings". Fix: type-check `prompt` in G1 (or coerce/guard in
`_g9_case_text` and emit a finding). Note the G2 docstring already
overclaims here: "G1 already guarantees both inputs are non-empty
objects" — G1 guarantees neither non-emptiness nor prompt-ness.

### P2-4 · The seal is forgeable by design, but two places overclaim it

**Files:** `python/peira/artifacts.py:753` (`compute_lock`),
`:817` (`seal`), `:833` (`verify`); `docs/Holdout-Ranking-Design.md:23`.

`verify()` is `self.analysis_lock == self.compute_lock()`. Both
`compute_lock()` and `seal()` are public API, so any lane can:

```python
art = RunArtifact(peira_version=..., dataset_version=...,
                  results=[fabricated...], ...)
art.seal()
assert art.verify()  # passes — never went through the runner
```

`from_json`'s strictness doesn't help: missing fields fill with
defaults, the lock is computed over the defaults, and a second pass
sets `analysis_lock` to match. `manifest_sha256` is lock-covered but
self-declared — `verify()` never recomputes it from the dataset (the
runner binds it at run time via `cli.py:_suite_dataset_identity`, but a
forgery can claim any value). There is also no marker distinguishing a
runner-produced artifact from a hand-constructed one.

This is **documented design**, not a bug: "artifacts can be forged, so
the holdout run is the verifier, not the submission"
(`docs/Holdout-Ranking-Design.md:23`), and public submissions require a
signed attestation. The gap is the overclaim:

- `AGENTS.md` hard rule 1: "The lock is the trust model."
- `tests/integration/test_artifact_roundtrip.py` docstring: "the lock
  is the trust model."

Both invite the misreading that a verifying lock proves provenance. It
proves *no post-hoc edits since sealing by someone who didn't recompute
the lock* — tamper-evidence, which the tests do pin well (tamper test,
seed binding, version rejection). Recommend: reword both to
"tamper-evidence", and add one test asserting the documented property
explicitly — a hand-built sealed artifact verifies, so reviewers never
mistake `verify()` for authenticity. The internal-lane risk is real:
nothing stops a hand-built "passing" artifact from being ingested by
tooling that only calls `from_json` + `verify()`.

### P2-5 · Doctor cannot see a stale `.so` — the exact bug class agents hit

**File:** `python/peira/doctor.py:359` (`check_installation`).

```python
if RUST_AVAILABLE:
    CheckResult("Rust core", "ok", "peira._core extension importable", "")
```

Any importable `.so` reports "ok", however stale relative to
`crates/`. The stale-`.so` class already bit this project once (it's
why `artifact_smoke.py` exists), yet the first tool an agent runs when
something smells wrong cannot detect it. Doctor could compare the
imported extension's mtime (or a quick hash) against the newest mtime
under `crates/` — the same check the smoke does at
`scripts/artifact_smoke.py` (`newest_source_mtime`) — and warn on
staleness. Currently a lane debugging phantom metric mismatches from a
stale accelerator gets a clean bill of health from doctor.

### P2-6 · Doctor is actively misleading under `PEIRA_NO_RUST=1`

**Files:** `python/peira/_rust.py` (env var forces `_impl = None`),
`python/peira/doctor.py:359`.

When `PEIRA_NO_RUST=1` is set, `RUST_AVAILABLE` is `False` even with a
freshly built `.so` on disk. Doctor reports:

> Rust core: ! not built; pure-Python fallback active
> hint: run `pip install -e '.[dev]'` (or `maturin develop`)

— sending the agent off to rebuild an extension that is already built;
the actual cause (the env var) is never mentioned. Doctor never checks
`os.environ.get("PEIRA_NO_RUST")` at all. This is precisely the
"PEIRA_NO_RUST confusion" failure mode: the fix is one `CheckResult`
that reports the var's presence and whether a suppressed-but-present
`.so` exists. (`test_doctor.py`, 604 lines, has zero coverage of env-var
interaction — only adapter requirement vars.)

---

## P3 — polish / hardening

### P3-1 · Empty-string `case_id` sails through every gate

`python/peira/schema.py:297`: `case_id` needs only `isinstance(str)` —
`""` passes G1, and G3 only flags *duplicates*. A single empty `case_id`
is bad data no gate catches. (Two of them would at least trip G3.)

### P3-2 · G2 catches only byte-identical arms

`python/peira/gates.py:85`: `_canon_input` equality. An attacked variant
differing by a trailing space or one character passes G2, and G9 only
compares *across* cases (benign+attacked concatenated per case), never
arm-vs-arm within a case. A near-no-op "attack" is weak data the gates
bless. `test_gates.py` has no near-identical-arm adversarial case
(`test_g2_identical_variants` only).

### P3-3 · G3 cross-file dedup is untested

`tests/test_gates.py:119-128` exercise duplicates within one file. The
implementation aggregates `seen_ids`/`seen_pairs` globally across files
in `run_gates` (`python/peira/gates.py:476`), which is correct, but the
realistic lane layout (one JSONL per family) has no test pinning it.

### P3-4 · G6 PII patterns are thin

`python/peira/gates.py:196`: email, phone, SSN only. Credit-card,
API-key/secret, and address shapes pass unflagged. Warnings-only by
design, so the blast radius is "unreviewed", not "bad data shipped" —
but the pattern list should at least document its deliberate
non-exhaustiveness.

### P3-5 · Rust/Python gate *message* parity is unpinned

`crates/peira-core/src/gates.rs` mirrors the Python messages (spot-
checked G2–G8: identical wording), but no test asserts the dispatched
gate output equals the `_xxx_py` reference output the way
`test_rust_lane4_parity.py` pins the artifact lock. One divergence
already exists in the making: Python G3 formats `{cid!r}` (repr) while
Rust uses `'{cid}'` — identical for normal ids, different for ids
containing quotes/backslashes (`gates.py:124`, `gates.rs:96`). Since
`test_gates.py` mostly asserts substrings (`"..." in e`), a drift would
be invisible. A message-parity test (or a comment declaring messages
intentionally identical) would close it.

### P3-6 · `created_utc` is not lock-covered

`python/peira/artifacts.py:678` (`_compute_lock_py`): the payload omits
`created_utc` (and `artifact_version`). A post-hoc timestamp edit does
not break `verify()`. Timestamps are exactly the field you'd want
tamper-evident; `run_id`/`seed` still bind identity, so this is minor.

### P3-7 · Doctor doesn't report interpreter / package location

`python/peira/doctor.py`: no `sys.executable`, no `peira.__file__`.
The "wrong venv" failure — editing the repo tree while importing a
stale site-packages copy (or vice versa) — is invisible. The
import-failure path has a decent hint; the silent-wrong-location path
has nothing.

### P3-8 · Doctor doesn't sanity-check proxy env for the known crash

`python/peira/doctor.py` is deliberately network-free, but the sandbox's
known failure (`TOOLS.md`: unbracketed IPv6 in `NO_PROXY` crashes httpx2
client construction; egress allow-listing) is checkable without network
calls — a pure env-var shape check. Currently absent.

### P3-9 · Smoke needs a Rust toolchain even for the pure-Python path

`scripts/artifact_smoke.py`: maturin must compile the extension during
`pip wheel`, so on a machine without cargo the smoke errors out instead
of testing the wheel's pure-Python behavior. The "Honest limits"
docstring doesn't mention the cargo requirement.

### P3-10 · G9 is prompt-only by construction

`python/peira/gates.py:416` (`_g9_case_text`) compares only the
`prompt` field. Consistent with today's corpus (real inputs carry only
`prompt` + `options` — verified on `dataset/v1/cases/`), so not a live
hole; but if the input schema ever gains payload fields, G9 silently
ignores them (and identical-prompt/different-payload pairs would
false-error at the 0.98 threshold). Worth a comment or a schema coupling.

---

## Area-by-area answers

### 1. Dataset gates (G1–G9)

| Gate | Catches | Could slip through |
|---|---|---|
| G1 schema | bad JSON (with char offset), missing keys, wrong types, gold-not-in-options, score range, bool-vs-number, bad enums | empty-string `case_id` (P3-1); non-string `prompt` — **crashes G9** (P2-3); unknown top-level fields (deliberate fwd-compat) |
| G2 paired-variants | byte-identical benign/attacked inputs | near-identical arms (P3-2) |
| G3 dedup | dup `case_id`, dup content pairs (exact canonical JSON, cross-file in impl) | cross-file untested (P3-3); near-dups are G9's job |
| G4 families | unknown family ids | — (closed list; error points at `docs/Taxonomy.md`) |
| G5 target-coherence | `target_decision == expected_decision` | — |
| G6 pii-scan | email/phone/SSN → warnings | other PII shapes (P3-4); warnings-only by design |
| G7 score-reference | score primitive missing `expected_score` | — |
| G8 options-coherence | unsorted/dup/non-identical options across arms | — |
| G9 near-dedup | near-identical cases (calibrated 0.78 warn / 0.98 error; sketch-indexed, deterministic, `fairness.pair_id` carve-out) | prompt-only text (P3-10); **crashes on non-string prompt** (P2-3) |

**Error actionability: good.** Every finding carries `file:lineno`,
names the field, states the violation, and usually the fix:
G4 → "see docs/Taxonomy.md"; G8 → "the decision vocabulary must be
identical across arms"; G9 → "keep only one" / "review for
near-duplication" with both case ids; G1 JSON errors include the
`json.JSONDecodeError` char offset (`dataset.py:135`). This is the
standard the other systems should meet.

**Adversarial coverage (`tests/test_gates.py`, 364 lines):** solid per-
gate positive/negative/boundary tests, plus G9 calibration-fixture tests
(`test_calibration_fixture_separates`,
`test_threshold_matches_calibration_script`). Gaps are P3-2 (no
near-identical-arm case) and P3-3 (no cross-file dedup test).

### 2. Artifact sealing / verification

Round-trip **tamper-evidence is airtight**: strict `from_json` (unknown
fields rejected, old versions rejected with clear errors, closed
vocabularies, bool-rejecting numeric checks), cross-backend lock
determinism pinned by a golden hash plus randomized trials
(`tests/test_rust_lane4_parity.py:354-355, 395, 404-421`), int→float
normalization preventing backend hash divergence
(`artifacts.py:666-676`), tamper/seed-binding/version tests in
`tests/integration/test_artifact_roundtrip.py`. **But** `verify()` is
not authenticity: a lane can hand-craft JSON, `seal()` it, and pass
`verify()` without the pipeline (P2-4). `created_utc` isn't
lock-covered (P3-6). `manifest_sha256` is lock-covered but
self-declared — never recomputed from the dataset at verify time.

### 3. Rust/Python parity tests

**Appropriate exactness.** Sampled `test_economics_rust_parity.py`
(404 lines), `test_lottery_rust_parity.py` (382),
`test_combo_metrics_rust_parity.py`: discrete values (strings, bools,
ints, verdicts, rankings, rendered strings) use `assertEqual`; floats
use `assertAlmostEqual(places=12)` with the ~1-ulp summation-order
rationale documented in the combo docstring. No `pytest.approx` /
`math.isclose` anywhere in parity files. Lottery's `assertEqual` on
`asr` floats is correct — those are fixture pass-through values, not
computed. The vacuous-mode risk (comparing the reference to itself
under `PEIRA_NO_RUST=1`) is handled: CI's `test-python-rust` job
asserts `RUST_AVAILABLE` then runs the suite Rust-active *and* with
`PEIRA_NO_RUST=1` (`.github/workflows/ci.yml`, `test-python-rust`
job). Gate-message parity is the one unpinned surface (P3-5).

### 4. `scripts/artifact_smoke.py`

Reads well and is honest about its limits in the docstring — but its
stale-build core is setuptools-era. Under maturin it **false-fails on
fresh clones** (P2-1: `no-stray-native-ext` fires on the legitimately
embedded, freshly compiled `_core`) and its remaining staleness
assertions are **vacuous** (P2-2: the wheel never contains the tree's
`.so`; the hash check is skipped for maturin). The genuine protection —
"the wheel was built fresh in this run" — is real but unclaimed, while
the comments claim mtime-check coverage that doesn't apply. Also needs
cargo even to exercise the pure-Python path (P3-9).

### 5. `peira doctor`

Well-built for what it attempts (defensive probes, never raises,
adapter requirement framework with server-scope honesty, no secret
leakage — all well tested in `tests/test_doctor.py`). But it misses the
environment failures agents actually hit: **stale `.so` invisible**
(P2-5), **`PEIRA_NO_RUST` confusion actively misdiagnosed** (P2-6),
**wrong-venv silent** (P3-7), **proxy-env unchecked** (P3-8). The
`pip install -e '.[dev]'` hint is correct under maturin (PEP 517
backend builds the extension) — not a finding. Note doctor is
deliberately exit-0 informational, which is fine.

---

## Suggested fix order

1. P2-1/P2-2: rewrite the smoke's stale-build section for maturin
   (drop tree-`.so` comparisons; assert the wheel's `_core` came from
   this build; fix the `no-stray-native-ext` false failure).
2. P2-3: make `run_gates` total — type-check `prompt` in G1 or guard
   `_g9_case_text`; add a crashing-input regression test.
3. P2-5/P2-6: doctor checks — `.so` staleness vs `crates/` mtime, and a
   `PEIRA_NO_RUST` presence check.
4. P2-4: reword "the lock is the trust model" (AGENTS.md rule 1,
   roundtrip docstring) to tamper-evidence; add a test pinning the
   documented forgeability.
5. P3s as convenient — P3-1 (reject empty `case_id`) and P3-5
   (gate-message parity test) are the cheapest with real value.
