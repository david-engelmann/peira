# Gate report: score-fallback key validation fix (red-team M1 + L2)

Lane: SCORE-FALLBACK FIX, 2026-10-22. Branch `fix/score-key-validation`,
worktree `~/workspace/peira-scorefix`, based on origin/main `12a9d025`
(merge of PR #478, the Celeris adapter).

## The defect (red-team M1, confirmed)

In `_score_from_probabilities` (identical code in
`python/peira/adapters/celeris.py` and `python/peira/adapters/pplx_decider.py`),
the fallback that computes a score from a per-level probability map when the
server omits the `score` field coerced probability keys with `int(key)`
instead of validating them. Non-canonical spellings were silently accepted:

- `{" 2": 1.0}` accepted as level 2
- `{"01": 1.0}` and `{"+1": 1.0}` accepted as level 1
- `{"1": 0.5, "01": 0.5}` double-counted level 1 while still summing to 1.0

Each fabricates a score where the adapter contract requires a fail-closed
`ProviderError`. A tree-wide grep for `int(key)` / `_score_from_probabilities`
confirms exactly two copies exist (celeris.py, pplx_decider.py); no others.

L2 (low): on HTTP 409 both adapters dropped the parsed `Retry-After` (only
408/429/529/5xx passed it through), even though the runner's own
`TRANSIENT_STATUSES` (`python/peira/concurrency.py`) already classifies 409
as transient and uses `retry_after` for both the wait and the congestion cut.

## STEP 0 — measurement-impact audit (run BEFORE any code change)

Question: did the already-published pplx-decider seal ever engage this
fallback with non-canonical keys?

Method: scanned every record of
`~/workspace/peira-trial/transcripts/pplx-decider.full.jsonl`
(9,402 lines). For each `primitive == "score"` record, read
`raw.response.answers.score`: an engagement is a score answer whose `score`
field is absent/null AND whose `probabilities` is a dict (the exact
precondition in `_score_output`). Engagements were then split by whether all
probability keys are within the canonical set {"0","1","2","3","4"}, and for
non-canonical ones the merged (buggy) fallback was replicated to check
whether it would have returned a fabricated value.

Results:

| Count | Value |
|---|---|
| Transcript lines scanned | 9,402 |
| Score records | 1,412 |
| Score records with server-reported `score` | 1,412 |
| Score records missing `score` | 0 |
| Fallback engagements | 0 |
| Engagements with non-canonical keys | 0 |
| Records where the old code would have fabricated a score | 0 |

Verdict: CLEAN. The published pplx-decider seal never engaged the fallback at
all; every score came from the server-reported field. No measurement impact;
no owner ruling needed. (Corroborates the Celeris audit: 1,412 score payloads,
zero engagements.) The fix below is therefore purely preventive.

## The fix

PR #480, branch `fix/score-key-validation`. Two commits: `0812a5db` (the
fix; remote `e0115530`, tree `3af44903`) and `8e97807a` (standards review
pass; remote `78e5bc2d`, tree `36ee9159`, verified identical to the local
tree after the Data API push). Seven files: the two adapters, the two
adapter test files, CHANGELOG.md, docs/Adapters.md, docs/Troubleshooting.md.

- `_SCORE_LEVEL_KEYS` (new module constant in both adapters):
  `frozenset(str(level) for level in range(len(_SCORE_LEVELS)))`.
  `_score_from_probabilities` now matches each key against that set
  instead of parsing it with `int(key)`; a non-canonical key returns
  None, the caller raises the pre-existing ProviderError ("score answer
  has no numeric score"), and a `seen` set rejects duplicate levels.
  The two helpers remain byte-identical across the adapters after the
  fix, as they were before.
- `_raise_for_status` in both adapters: 409 added to the Retry-After
  passthrough tuple `(408, 409, 429, 529) or 5xx`, with a comment noting
  409 is in the runner's transient set. Module docstring transient
  lists updated to match.
- Docs: CHANGELOG entry at the top of [Unreleased]; Adapters.md
  retryable enumerations now include 409 with the Retry-After
  passthrough (the pplx section previously omitted even 408);
  Troubleshooting.md transient headings for both adapters now include
  the 409 error string. No error message text changed.

Tests added (per adapter, mirroring the existing style):
`test_score_fallback_noncanonical_key_spellings_are_terminal`
({" 2": 1.0}, {"01": 1.0}, {"+1": 1.0}),
`test_score_fallback_duplicate_level_spellings_are_terminal`
({"1": 0.5, "01": 0.5}), `test_409_carries_retry_after`.

Revert check (run by the owner, not just claimed): with the two adapter
files restored to 12a9d025 and the new tests kept, all six new tests
FAIL (3 per adapter: the old code returns fabricated scores for the
spelling cases, and `retry_after` is None for 409). With the fix
restored, all 151 tests in the two adapter files pass.

## Local gates

Run in the worktree venv (`.venv/bin/pip install -e '.[dev]'`),
`RUSTUP_TOOLCHAIN=1.91-x86_64-unknown-linux-gnu`,
`CARGO_TARGET_DIR=~/workspace/rust-test/target-scorefix`. Full suites
ran on commit `0812a5db` content; the follow-up commit `8e97807a`
changes only comments and docs (proven below), and the touched tests
were re-run on the final head in both modes (151 passed, 151 passed).

- Rust-active: `pytest tests -n auto` → exit 1, **9 failed, 4292
  passed, 3 skipped**. The 9 failures are exactly the documented
  baseline: eight `test_backend_under_test` (combo_metrics,
  combo_schema, invariance, labels, lottery, mde, hardness,
  metrics_prereqs Rust-parity files) plus
  `test_concurrency.py::TestTranscriptAndReplay::test_replay_preserves_error_records`.
  Nothing beyond baseline.
- No-Rust: `PEIRA_NO_RUST=1 pytest tests -n auto` → exit 0, **4254
  passed, 50 skipped**. Fully green.
- `scripts/check_public_surface.py` → exit 0, "public-surface check
  passed."
- `scripts/artifact_smoke.py` → **PASS** ("SMOKE-RESULT OK", wheel
  built from the worktree with the native extension embedded, gates
  and metrics run through the installed package), after an
  environment workaround that needs recording: in this sandbox, pip
  build isolation cannot fetch `puccinialin` (maturin's toolchain
  helper), so the stock invocation fails at metadata preparation.
  Control evidence: the identical invocation on unmodified main
  (12a9d025, `~/workspace/peira-publish25`) fails identically
  (exit 2, same ModuleNotFoundError). The diff touches no packaging
  files, so the failure is environmental, not the change. The
  passing run used `PIP_NO_BUILD_ISOLATION=1` with `puccinialin`
  installed in the lane venv and the venv bin plus `~/.cargo/bin`
  on PATH (the pep517 hook invokes bare `maturin`); the wheel is
  still the real maturin-built wheel from the worktree. The smoke
  was re-run on the final head `8e97807a` the same way (see below).
- Post-review commit proof: the adapter files at `8e97807a` are
  token-identical to `0812a5db` ignoring comments (Python `tokenize`
  comparison), so the suite results carry over exactly; the
  Adapters.md delta is prose only.

CI on PR #480 head `e0115530`: every check green except
`test-python-rust`, which is red identically on main's own head
12a9d025 (it runs the same 9 baseline failures). Not red for this
PR's own reasons.

## Three reviews

1. **Independent red-team re-audit** (fresh agent, read-only, ran the
   helper and `decide()` directly): the fix HOLDS. Every bypass
   attempt rejected in both adapters, fabricated score impossible
   through the fallback: whitespace/zero-padded/signed keys,
   out-of-range spellings ("5", "-0", "99"), look-alike digits
   (fullwidth, Arabic-Indic, superscript), non-string keys (int,
   float, bool, bytes, tuple), and value-side attacks (bool, string,
   NaN, inf, negative, >1 all still void the fallback, canonical maps
   still compute exactly: full map 2.0, uniform 2.0, sparse
   {"0": 0.25, "4": 0.75} → 3.0). End-to-end through `decide()` with
   a stubbed transport: missing score + non-canonical map raises
   ProviderError, no ScoreOutput returned. Sibling hunt: no third
   copy exists (`int(key)` grep, idiom grep, and an 8-gram shingle
   pass over every adapter agree); jev.py/clef.py build score
   distributions under adapter-chosen canonical keys and never parse
   wire keys. 409 verified end to end (adapter emits retry_after;
   `classify_exception` returns (True, True, 3.0) with it vs
   (True, False, None) without). Two low notes, dispositioned:
   (a) `_answer_confidence`'s `probs.get(option)` looked like a
   sibling but is an exact dict lookup with no normalization, and
   confidence is clamped/validated separately; investigated and
   REFUTED by the red team itself. No change.
   (b) The canonical map "0.30000000000000004" sum case is accepted
   by the old 0.01 tolerance exactly as before; pre-existing,
   unchanged by this fix, and not one of the M1 spellings. No change.
   The red team also re-derived the Step 0 audit's logic and agreed
   the trigger condition in the audit matches the merged code
   (`ans.get("score") is None` + dict probabilities).
2. **Independent diff review, two axes, reported separately.**
   - *Spec fidelity:* PASS, no deviations or blockers. Per-hunk
     verdicts confirm both adapters fixed, all four named test cases
     present per adapter, CHANGELOG at the top of [Unreleased],
     Troubleshooting headings carry the 409 string, no out-of-scope
     files, all pre-existing behaviors preserved (canonical maps,
     sparse maps, out-of-range, bool, string-value, partial-mass all
     behave as at base). One item left to the owner's judgment, not
     a violation: the helper still returns None and the pre-existing
     caller message ("no numeric score") does not name the offending
     key. OWNER RULING: keep the existing taxonomy. The brief asked
     for failure "matching the adapters' existing error taxonomy";
     the observable contract is the ProviderError from `decide()`,
     the message is already documented in Troubleshooting.md for
     exactly this outcome, the offending answer payload is included
     in the message verbatim (`{ans!r}`) so the bad keys are visible,
     and inventing a new message would add a new user-facing string
     for no measurement benefit. No change.
   - *Standards:* two Important findings, both FIXED in `8e97807a`:
     (S-1) the Adapters.md pplx retryable sentence the fix touched
     now leads with the full transient set in the module docstring's
     own enumeration shape, matching the Celeris section; (S-2) the
     `seen` duplicate check, unreachable under canonical matching,
     now carries a comment in both helpers stating it pins the
     one-entry-per-level invariant against future loosening of key
     matching (the alternative, deleting it, was rejected: the brief
     requires duplicate rejection, and the check is that requirement
     encoded). Also verified clean by that axis: zero U+2014 and zero
     semicolons in all added prose (Python codepoint scan), helpers
     byte-identical across adapters, no test weakened or deleted,
     all six new tests genuinely fail-capable (independently
     re-derived against base behavior).
3. **Owner's own verification:** Step 0 audit run first-hand;
   helper-level checks first-hand ({'2': 1.0} → 2.0; {' 2': 1.0} →
   None; {'1': 0.5, '01': 0.5} → None); revert check run first-hand
   (6/6 new tests fail on reverted adapters, 151/151 pass restored);
   gate logs re-read (counts and failure identities above);
   pushed-tree hashes compared after both Data API pushes
   (`3af44903`, then `36ee9159`, both equal to local).

## CodeRabbit

Step 0: CodeRabbit posted only the sub-10-star skip notice on the
first head, so `@coderabbitai review` was triggered manually on the
final head `78e5bc2d` (comment 6351415511). The provider answered
with a rate-limit refusal ("Review limit reached: you've used all
free OSS reviews for now" / "Action not completed: review rate
limited"), so no CodeRabbit review of this PR exists and there are
no findings to disposition. Advisory only in any case; the three
required reviews above are complete without it.

## Merge

- Final-head smoke re-run on `8e97807a` (same documented
  environment workaround): **PASS**, exit 0, 207.8s (the first
  attempt was killed by a runtime restart at 21:14 UTC and was
  relaunched; the passing log is `gate-logs/smoke-final.log` in the
  lane worktree).
- Pre-merge check: `git fetch origin` showed main still at
  `12a9d025`, so no rebase was needed; PR head `78e5bc2d`,
  mergeable, 24 CI checks with the only failure `test-python-rust`
  (red identically on main's own head, the documented baseline).
- Merged via the REST merge endpoint: **merge commit
  `c98cc2d122deb70fd193b6789321fb914b12bef1`**.
- Post-merge verification on main itself: `git grep` at `c98cc2d1`
  finds `_SCORE_LEVEL_KEYS` defined and used in both adapters and
  the `(408, 409, 429, 529)` passthrough tuple in celeris.py; the
  `12a9d025..c98cc2d1` diff is exactly the lane's 7 files (144
  insertions, 32 deletions across both commits).
- GOAL.md's Recently merged list updated with the #480 entry in the
  same pass.

Lane status at #480 merge: the M1 fail-open is closed in the two
named adapters, the L2 Retry-After drop is fixed in both, the
published pplx measurement is proven untouched by the defect, and
no trial runs or publishes were performed by this lane. **This was
not the whole defect: see the fix-forward addendum below.**

## Fix-forward addendum (2026-10-22, after #480 merged)

### The miss

The Spec-fidelity review axis's full report (delivered after the
merge; the lane owner had acted on a truncated delivery that
appeared to be a pass) found a third carrier the lane missed:
`python/peira/adapters/clef.py`. Root cause: the lane's tree grep
searched the literal `int(key)` and `_score_from_probabilities`;
Clef's copy spells the coercion `int(k)` inside a generator
expression, `sum(int(k) * float(p) for k, p in
ans["probabilities"].items())`, so it never matched. The red team's
claimed idiom pass missed it as well. The Spec axis's variant grep
(`int\((k|key)\)`) caught it.

Clef's copy was the weakest of the three (verified first-hand by
the lane owner at `c98cc2d1`): keys AND values coerced
(`float("1.0")`, `float(True)` accepted), no total or range
validation, and the computed value then clamped by `_clamp01`, so
`{"99": 1.0}` silently became a maximal score. Its
`_raise_for_status` also had the identical `(408, 429, 529)`
tuple, dropping 409's Retry-After.

### Clef measurement-impact audit (run before any fix code)

Both published Clef runs scanned (`clef-flash.full.jsonl`,
`clef.full.jsonl` in `~/workspace/peira-trial/transcripts/`): 9,402
lines each, 1,412 score records each, all 1,412 in each run carried
the server-reported `score`, zero fallback engagements, zero
problem engagements under either the old or the strict computation.
No published measurement is affected; the Clef fix is preventive,
same as the named pair.

### The fix-forward (PR #481)

Branch `fix/clef-score-key-validation`, worktree
`~/workspace/peira-cleffix`, base `c98cc2d1`, commit `850c591e`
(remote `730e9406`, tree `068f30a3` hash-verified). Five files.

- `clef.py` gains `_SCORE_LEVEL_KEYS` and a `_score_from_probabilities`
  byte-identical to the merged siblings', replacing the coercive
  sum; failure surfaces via Clef's existing "clef score answer has
  no numeric score" ProviderError. Deliberate decision, stated in
  the PR: fixing only the key spelling would have left the value
  coercion and clamp-to-maximal paths open under a fix PR, so the
  whole strict contract was ported. The direct server-score path
  (float + `_clamp01`, pinned by `test_score_clamped`) is untouched;
  its clamp-vs-terminal divergence from the siblings is a
  pre-existing, separately pinned behavior, not part of M1.
- 409 added to Clef's passthrough tuple; docstring, Adapters.md
  Clef section, and Troubleshooting.md Clef transient heading
  updated (both docs previously omitted even 408 for Clef).
- Tests: the four briefed cases plus Clef-specific coerced-value
  (numeric string, bool) and out-of-range-key and partial-mass
  cases, and 409 passthrough. Revert check run first-hand: with
  `clef.py` restored to `c98cc2d1`, all six new tests fail; with
  the fix, all 53 tests in `tests/test_clef_adapter.py` pass and
  every pre-existing test passes unchanged.

### Gates and reviews for #481

(To be completed before merge: full suites both modes, artifact
smoke, public surface, three reviews scoped to this diff,
CodeRabbit, merge SHA, post-merge verification, GOAL.md sync.)

Process lesson recorded: a pattern grep must enumerate the
pattern's spellings (variable names, generator forms), not one
literal; and a review axis's "pass" is not a pass until its full
text has been read.

## PR #481 reviews (reviews of 850c591e unless noted; read IN FULL)

- Spec fidelity: PASS. Every hunk verified against the itemised spec;
  helper byte-identity confirmed programmatically; the reviewer's own
  variant-aware carrier sweep concluded no fourth in-scope carrier
  exists. Two minor observations, both folded into the tidy commit
  below: three sibling fallback tests not yet ported to Clef (empty
  map, value-above-one, sparse-full-mass), and a CHANGELOG phrasing
  nit ("out-of-range total" for what was a clamped weighted sum).
- Standards: PASS with one minor defect: semicolons in 5 added comment
  lines, 4 of them verbatim sibling copies. The reviewer recommended
  fixing only the one novel line in this lane and treating the rest
  as a sibling-wide cleanup. This lane did the sibling-wide cleanup
  instead (all three adapters at once, byte-identity preserved),
  because the tidy commit already touched all three helpers for F4.
- Red-team: the first commissioned agent errored without reporting.
  A replacement was commissioned against the final head (post-tidy
  full diff); result recorded in the merge section when received.

## PR #481 tidy commit (5838c01d local / a749e57c remote, tree a3d5a5e8)

- F4 fixed in all three helpers: an int probability other than 0 or
  1 now voids the fallback before float() conversion. Revert check
  run first-hand: with the three adapters restored to their pre-tidy
  states, all three new huge-int tests fail with exactly
  "OverflowError: int too large to convert to float"; with the fix,
  the three adapter files pass 210/210.
- D1 closed across the lane's whole footprint: the two CHANGELOG
  semicolons, the fallback comment, the seen-set comment, the 409
  test comment and the partial-mass test comment in all three
  adapters/test files, the novel Clef line-274 comment, and one
  semicolon in the new Clef sparse test comment. A Python scan of
  all added lines in the final diff finds zero semicolons in added
  comment/prose lines and zero U+2014.
- J1 closed: "never parsed" corrected to admission-by-matching
  wording in the constant comment and helper docstring of all three
  adapters. The three helpers and the three constant blocks remain
  byte-identical after the tidy (verified by extraction diff).
- D2 disposition (final): the seen set is KEPT. The brief requires
  duplicate-level rejection as specified behaviour; the set encodes
  that requirement in the code that owns it, its comment states
  plainly that it cannot fire under canonical matching, and deleting
  it from one or all copies would trade a stated invariant for a
  reviewer's taste call. Recorded as a rejected recommendation with
  rationale, per the disposition rule.
- Clef parity tests added (empty map, value-above-one, sparse
  full-mass accepted), closing the Spec and Standards parity notes.
  Clef adapter test count is now 57 in-file tests; the three adapter
  files together run 210 tests, all passing.

## PR #481 gates on 850c591e (superseded by the tidy head)

- Rust-active: exit 1, 4,297 passed, 10 failed. Nine failures are the
  documented baseline set, identities verified. The tenth,
  tests/test_runner_timing.py
  TestRunTimeout::test_run_timeout_stops_dispatch_drains_and_
  checkpoints (KeyError 'art'), is a wall-clock drain test that ran
  under load average ~20 and passed in the same head's no-Rust full
  run; the Clef diff has no path to runner timing. Adjudicated a
  load flake; the final-head full runs provide two further samples.
- No-Rust: exit 0, 4,260 passed (baseline 4,254 plus the 6 Clef
  tests), fully green.
- The gate script was killed during the smoke step (process group
  vanished with the summary unwritten, same pattern as the runtime
  restarts that day), so smoke and surface checks for 850c591e were
  not captured. Both are re-run on the final tidy head, whose full
  gate set is recorded in the merge section.

## PR #481 final-head gates (5838c01d local / a749e57c remote, tree a3d5a5e8)

- Rust-active: exit 1, 4,304 passed, 9 failed. The 9 failure
  identities are exactly the documented baseline set (verified
  line by line). The runner-timing test that flaked on 850c591e
  passed in this run, closing the flake adjudication: two passes
  (this run and the 850c591e no-Rust run) against one failure under
  load average ~20.
- No-Rust: exit 0, 4,266 passed, fully green.
- artifact_smoke.py: PASS (2,282.6s under load; wheel built from the
  real tree, installed, gates and metrics run through the installed
  package). Same documented environment workaround as PR #480
  (PIP_NO_BUILD_ISOLATION=1; control failure on unmodified main
  recorded there).
- check_public_surface.py: exit 0.
- Count reconciliation: 850c591e runs to final-head runs differ by
  exactly the 6 tidy tests (3 huge-int, 3 Clef parity) plus the one
  flake moving to pass. 4,297 + 6 + 1 = 4,304 Rust-active passes;
  4,260 + 6 = 4,266 no-Rust passes.

## Main moved before merge: PR #477 (Mercury) and the rebase

- Before merging, origin/main had advanced from c98cc2d1 to
  1bf0407b (merge of PR #477, the Inception Mercury Decide
  adapter). The branch was rebased onto the explicit SHA 1bf0407b;
  both commits replayed with no conflicts.
- Rebase survival check: the diff against the new base is exactly
  the PR's 9 files; the tree delta against the gated tree is
  exactly PR #477's 8 files, nothing of this PR lost and nothing of
  #477 altered. Behavioural check: 289 tests pass across the four
  affected adapter test files (210 from this PR's three files plus
  79 Mercury). CHANGELOG carries all entries (Clef fix at the top
  of [Unreleased], then the #480 entry, then the Added sections
  including Mercury).
- Push mechanics (Data-API tree trap, handled): the first push of
  the rebased files produced tree e04c34c6, not the rebased tree,
  because the helper builds on the old parent's tree. A second push
  added #477's files byte-identical from the rebase; the branch
  head ba4360c4 now has tree f552f10b, equal to the local rebased
  tree (hash verified). GitHub reports the PR mergeable.
- Full gates were re-run on the rebased head before merge (the
  exact-final-head rule); results in the merge section.

## Mercury adapter (PR #477) pattern check, escalated

- The Mercury adapter merged today was built from the strict
  pattern. Its _score_from_probabilities validates keys by a
  canonical round-trip (int(key) inside try/except, then
  key == str(level) plus range), which rejects every M1 spelling;
  M1 is NOT present in Mercury.
- F4 IS present in Mercury: float(prob) runs with no int guard, so
  {"2": 10**400} escapes as OverflowError there. Its
  _raise_for_status tuple is (408, 429) plus 5xx, so 409 (and 529)
  also drop Retry-After (the F5 family). Both are the same
  already-escalated sibling classes, in code owned by the Mercury
  lane; they are recorded here and in the lane's final report to
  the parent rather than absorbed into this PR at merge time.

## PR #481 rebased-head gates (ba4360c4 remote / 4364f22a local, tree f552f10b)

- Rust-active: exit 1, 4,382 passed, 11 failed in 5,100s (the run
  spanned repeated VM stalls). Nine failures are the documented
  baseline set, identities verified. The other two
  (test_site_ingest.py::IngestV3Test::test_non_success_run_status_
  rejected and test_s8b_rewire.py::TestLockStillVerifies::
  test_seal_verify_roundtrip) are xdist worker crashes, recorded in
  the log as "worker 'gw0' crashed" and "worker 'gw1' crashed" with
  no assertion verdict; zombie worker processes were observed
  during the run. Adjudication: both files pass in this head's full
  no-Rust run, and both pass in an isolated Rust-active rerun on
  this head (verdicts recorded in the merge section). Neither file
  is touched by this PR or by #477.
- No-Rust: exit 0, 4,345 passed (4,266 pre-rebase plus Mercury's
  79), fully green.
- artifact_smoke.py: PASS (454.1s). check_public_surface.py: exit 0.
- CI on ba4360c4: toolchain-pins, lint-workflows and
  test-python-rust fail identically on main's own head 1bf0407b
  (verified via the check-runs API), so none is red for this PR's
  own reasons.

## CodeRabbit on PR #481 final head (review 5622785164, COMMENTED)

CodeRabbit reviewed the GitHub-visible diff, which (Data-API graph)
includes PR #477's files. It posted 3 actionable comments, ALL on
python/peira/adapters/mercury_decide.py, a file this PR does not
change. Zero findings on any of this PR's nine files. Dispositions
(dismissed silently on the PR per the standing rule; reasons here):

- Mercury 409 Retry-After passthrough: valid, out of scope. The
  same F5-variant finding this lane had already made and escalated
  (see the Mercury pattern check above). Owned by the Mercury
  lane/follow-up.
- Mercury float() OverflowError at four wire-value sites: valid,
  out of scope. The same F4-in-Mercury finding already escalated.
- Mercury _read_error_detail should also catch
  http.client.HTTPException (IncompleteRead): new, plausible, out
  of scope (Mercury error-path robustness, unrelated to the score
  fallback family). Added to the escalation list for the parent.

## PR #481 red-team (replacement agent; full text read)

The first red-team agent was killed by a daemon restart; the
replacement's completion delivery was also lost in a restart, and
its report was recovered from the agent's stored session record
and read in full. Verdict: HOLDS, no findings in the scoped diff
(it audited 850c591e + 5838c01d, whose content the rebase carried
unchanged, as the tree checks above prove). Evidence: a 44-case
stub-transport battery through ClefAdapter.decide() in which every
malformed input failed closed with ProviderError (including
{"2": 10**400} and a JSON-round-tripped huge literal, with no
OverflowError escape) and every valid map computed exactly;
independent extraction showing the three _score_from_probabilities
bodies byte-identical (SHA-256 08ba514e…) and the three
_SCORE_LEVEL_KEYS blocks byte-identical (SHA-256 d81e502d…); the
int guard's placement and genuine-int acceptance verified in all
three helpers; the direct server-score path byte-identical to
base; the 409 passthrough verified against concurrency.py; a
variant-aware carrier sweep confirming jev and openai_decisions
as the known escalated siblings and no new carrier; and a targeted
210-test pass over the three adapter files. Two out-of-scope
observations, both pre-existing and non-blocking: a huge-int
server score on the DIRECT path also escapes as OverflowError
(byte-identical at base; added to the F4-family escalation), and
the 0.01 total-mass tolerance rejects exact 0.99/1.01 totals by
float representation (fails closed; identical in the merged
siblings).

## PR #481 MERGED (merge section)

- Isolated rerun verdicts for the two worker-crash files, on the
  rebased head, Rust-active: tests/test_site_ingest.py 31 passed;
  tests/test_s8b_rewire.py::TestLockStillVerifies 2 passed
  (exit 0). With those verdicts, the rebased head's evidence set is
  complete: baseline-9 assertion failures only, no-Rust fully
  green, smoke PASS, surface green.
- Three reviews, all read in full: red-team HOLDS, Spec PASS,
  Standards PASS with its minor defect closed by the tidy commit.
  CodeRabbit reviewed the final head; dispositions recorded above.
- PR body updated with the final review-readiness block before
  merge. Pre-merge fetch confirmed main still at 1bf0407b and the
  PR mergeable at head ba4360c4.
- Merged via REST (method merge) at the gated head: merge commit
  cbcc0af06d5e9f0b8d01f41f24c8db623cbb62eb.
- Post-merge verification on main itself: origin/main is cbcc0af0;
  its tree is f552f10b, exactly the gated tree; the merge diff
  against 1bf0407b is exactly the PR's 9 files (254 insertions);
  git grep at the merge commit finds _SCORE_LEVEL_KEYS in all
  three adapters, the huge-int guard in all three helpers, and
  Clef's (408, 409, 429, 529) Retry-After tuple.

## Lane close-out

Both halves of the score-fallback lane are merged: PR #480
(c98cc2d1; Celeris + pplx-decider M1 and L2) and PR #481 (cbcc0af0;
the Clef carrier the #480 Spec review caught, the F4 guard in all
three helpers, and the accumulated review tidy). Every published
run audited for the fallback family (pplx-decider, Celeris, Clef
flash, Clef full, Jev, Jev-114, OpenAI Decisions) showed zero
fallback engagements; Kev and Strands engagements remain
unauditable from home because their wire transcripts were on the
destroyed Vast pod (bounded inference recorded earlier in this
report). Escalations standing for follow-up lanes, in recommended
order: (1) jev-family fallback contract (Jev, Kev, Strands), (2)
openai_decisions distribution validation, (3) Mercury F4
(four float() sites including its direct score path) plus its 409
passthrough and the CodeRabbit IncompleteRead point in its error
handler, (4) the direct-path huge-int score in the three
System-One adapters (pre-existing, byte-identical at base), (5)
jev 408/409 Retry-After.
