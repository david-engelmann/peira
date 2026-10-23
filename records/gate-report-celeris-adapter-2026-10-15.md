# Gate report: Celeris celeris-1-decision lane, 2026-10-15

Lane: build the celeris adapter on the Jev/System One pattern,
checkpoint-merge it, wire the live driver, canary, full v2 run under
a $2 cap, seal, back up. Stop before publishing (owner publishes).

Context note: Celeris-1-decision (announced 2026-10-08) claims the
top of jev-bench (80.0% accuracy, Brier 0.272) over
pplx-decider-v1.1-27b, Mercury Decide, Jev 1.13.0 and gpt-6-luna.
Those numbers are VENDOR-RUN on the vendor's own harness. Peira's
measurement is the independent check, and any public copy must keep
that distinction. The model was not in the 2026-10-14 landscape doc;
it is a new chart entrant.

## Step 0: live probe (2026-10-15, before building)

Helper: ~/workspace/custom-connectors/custom.celeris/bin/systemone_probe.py
(surrogate credential via dynamic_credentials, bearer_header
placement confirmed on the registered entry, allowed host
inference.celeris.ai; the key value never printed or logged).

- Combined call (one choice, one score, one noul question over a
  trivial state, the exact Jev question text): HTTP 200.
  - Response is NOT enveloped. Top level: answers, model, usage.
  - answers.decision: {choice "approve", confidence 0.94,
    probabilities {approve 0.96, deny 0.02, other 0.02},
    type "choice"}. The API confidence is close to but not equal to
    probabilities[choice]; the adapter reads the confidence field
    with the strictly validated probabilities fallback, as the
    hardened sibling does.
  - answers.score: {score 3.82 on the 0-based rubric scale,
    confidence 0.86, legend "0".."4", probabilities keyed "0".."4",
    type "score"}.
  - answers.abstain: {noul 0.03, type "noul"}. The abstain
    probability lives ONLY under the noul key; there is no abstain
    key.
  - model echoes the sent id exactly: "celeris-1-decision".
  - usage: {input_tokens 300, output_tokens 0}, genuine integers.
  - No x_celeris extension object anywhere in the response. Vendor
    material describes per-answer reasons in one; the adapter reads
    only the standard answer fields, so extension content can never
    enter a metric (pinned by a test whose fake response carries
    misleading reason text at top level and inside the answer).
  - Latency 30.7 s on this first-ever call (cold start).
- Warm and per-primitive probe (second script, same credential):
  combined call again 2.20 s; choice-only 1.44 s (169 input tokens);
  score plus paired decision 1.00 s (247 input tokens); abstain-only
  1.18 s (144 input tokens). Each per-primitive call returned only
  the requested answers. Four concurrent choice calls all returned
  200 (wall 3.45 s). output_tokens was 0 on every call.
- Error shapes (third script): HTTP 422 FastAPI body
  {"detail": [{"loc": [...], "msg": ..., "type": "value_error"}]}
  for an unknown model ("this endpoint serves celeris-1-decision"),
  an unknown question type ("must be choice, noul or score"), a
  missing model field, an empty questions object, and a missing
  state. 422 is terminal in the house status mapping.
- Pricing: vendor-stated $0.04 per 1M input tokens, output free.
  Per-case probe usage totals about 560 input tokens across the
  three adapter calls, so the full-trial projection is well under
  $1 even with real case states several times longer than the probe
  state. The driver's $2 cap stands with wide margin; the canary
  projection is the number of record (step 6).

## Step 1: the pricing landmine, determined before building

In-flight partials (~/workspace/peira-trial/partials/, verified this
lane, 2026-10-15): laya.full (350 results), granite-guardian.full
(350), shieldstral.full (350), all stamped pricing_version
2026-10-15.1. The local-queue supervisor (running, pid 21693) and
the Laya driver (pid 21701) resume them through
~/workspace/peira-worktrees/peira-main/.venv-local, whose peira.pth
points at ~/workspace/peira-trial-code/python; that checkout sits at
13cb9ebd with pricing table 2026-10-15.1. Stamp equality verified
programmatically for all three partials against that checkout's
table: match.

Mechanism (runner.py validate_partial, line 2637): a resuming
process compares the partial's stamp to load_pricing_table() from
the peira package IT imports. Consequences:

- Merging this lane's PR changes origin/main only. It does not
  touch peira-trial-code, any running process, or any partial. The
  in-flight partials remain resumable by exactly the code that
  resumes them today. The merge is safe for them, with the same
  reasoning the GLiNER (2026-10-15.2) and in-flight Perplexity
  (2026-10-15.3) bumps already rely on.
- The hazard is operational, and it is this lane's own run that
  creates it if done carelessly: fast-forwarding peira-trial-code
  to a main whose table differs from 2026-10-15.1 while .1-stamped
  partials remain unsealed would orphan them on the supervisor's
  next relaunch (a whole-VM reboot today would trigger exactly that
  relaunch). That already happened once today in the other
  direction (the Clef .1 table orphaned the .2-era Laya partial,
  archived untouched).
- Therefore: peira-trial-code is NOT advanced by this lane. The
  Celeris canary and full run launch from a copy of the driver whose
  only edit is the WORKTREE constant, pointed at a checkout of
  merged main (see step 6). The supervisor's file and checkout stay
  byte-identical throughout.

This lane stamps pricing 2026-10-15.3 (next after current main's
2026-10-15.2). The Perplexity branch carries .3 in its own tree; the
two lanes restamp on rebase in merge order, the established GLiNER
precedent (it restamped .2 over Clef's .1 the same way). At merge
time this lane re-checks main's table version and takes the next
number if main has moved.

## Step 2: adapter build (2026-10-15)

- Worktree ~/workspace/peira-celeris, branch feat/celeris-adapter,
  based on origin/main 5b0f85d1 (Strands merge). Local commit
  1696f9ab, tree c122b410.
- Files (8): python/peira/adapters/celeris.py (new),
  tests/test_celeris_adapter.py (new, 74 tests), pyproject.toml
  (entry point celeris), python/peira/data/pricing.json
  (celeris-1-decision at $0.04/$0, table version 2026-10-15.3, the
  _comment changelog segment appended, JSON edited programmatically
  with a byte-identical round-trip check first),
  tests/test_phase0_primitives.py (both literal pins moved to .3),
  docs/Adapters.md, docs/Troubleshooting.md, CHANGELOG.md.
- Structure mirrors the hardened pplx-decider adapter with the
  observed Celeris differences: no envelope, the body carries the
  pinned id, the endpoint itself is per-model (a wrong request model
  is refused by the endpoint with 422), error detail read from the
  FastAPI detail list's msg fields, and a model-echo check that
  refuses a response naming weights other than the pin.
- Strictness carried over from the sibling's two red-team passes, by
  construction rather than by repair: confidence is the API field or
  the chosen option's probability, both genuine numbers in [0, 1],
  with no midpoint default and no coercion; the score fallback
  accepts only a genuine distribution (non-empty, level keys 0..4,
  genuine values in [0, 1], total within 0.01 of 1); usage is
  required and its counters must be non-negative ints; the abstain
  probability is range-checked, never clamped, and disagreeing
  dual keys are terminal. One deliberate strengthening over the
  sibling: a score field outside the 0-based rubric range is
  terminal here (the sibling clamps it via _clamp01); clamping a
  position of 99 into a maximal score fabricates an extreme, and the
  sibling's reviewers never ruled on that input for the score field
  itself.
- Question text verified byte-identical to Jev's builders for all
  three primitives (AST comparison of _choice_question,
  _score_question, _noul_question: identical; JSON-bytes equality is
  pinned by the request-shape tests).
- Focused tests: 74 passed. Neighbour suites (Clef, Jev,
  conformance, discovery, pricing, phase0): 281 passed in total with
  15 subtests. check_public_surface.py exit 0;
  check_no_emdashes.py exit 0. Codepoint scan of the adapter:
  exactly two U+2014, both inside the inherited measurement strings,
  as in the siblings. Codepoint scan of the added docs prose: zero
  U+2014.
- Connector doc completed from its template at
  ~/workspace/custom-connectors/custom.celeris/CONNECTOR.md, with
  the verified helper at bin/systemone_probe.py (the probe above
  ran through it).

## Step 3: merge checkpoint

Three reviews ran on local head 1696f9ab (tree c122b410), 2026-10-15.

- Red team (fresh eyes, hostile fake transports run in the venv):
  attempted-and-held on NaN/Infinity/bool/string rejection on every
  numeric path, fallback-map key abuse, echo variants, key leakage,
  status classification across the full range, error-body shapes,
  headers=None, invalid UTF-8, question byte-identity (runtime
  compare), pricing coherence, and x_celeris influence (a poisoned
  extension is ignored). Findings:
  1. HIGH (test integrity): test_non_dict_probabilities_is_terminal
     asserted only ProviderError, so it could not distinguish the
     probabilities type check from the confidence path's raise.
     PARTIALLY VALID. The claimed mechanism is refuted on the real
     code: the owner's repro shows the type check's own message
     ("celeris returned probabilities that are not an object")
     firing first. The under-pinning is real, though: with the
     check deleted, the confidence path still raised. Fixed: the
     fake now carries a valid confidence and the test asserts the
     message, so the type check is the only branch that can raise;
     verified to fail with the check removed and restored.
  2. MEDIUM: a missing score with a non-dict probabilities value was
     claimed to escape as AttributeError. REFUTED. The owner's
     repro matrix on the shipped head (list, string, int, None,
     list/dict/None/NaN/inf values, int and float keys) produces the
     clean ProviderError "celeris score answer has no numeric
     score" in every case; no AttributeError exists on this path. A
     pinning test was added anyway so the behavior is regression
     proof.
  3. MEDIUM: the coerced-usage-counter test exercised only
     input_tokens, leaving output_tokens (True incl.) untested.
     VALID. Fixed: the test now loops both counters.
  4. LOW: Retry-After "inf" parses to inf. DISMISSED: the runner
     caps the value at consumption (runner.py line 1522,
     delay = min(retry_after, MAX_RETRY_AFTER_S)); the parse is
     family-identical. Safe end to end (the sibling lane's
     disposition, re-verified here).
  5. NIT: non-string model echoes format cleanly. Held, no action.
- Spec fidelity axis: one hard finding plus three clarifications.
  1. HARD: the CHANGELOG section was claimed to sit after the
     Strands and GLiNER sections, not at the top of [Unreleased].
     REFUTED. At the reviewed head the section is the first under
     [Unreleased] (grep: line 10, Strands at 26, GLiNER at 38), and
     the independent Standards reviewer verified the same placement
     first-hand. The reviewer's reading does not match the tree.
  2. The Troubleshooting prose for the usable-confidence and
     score-out-of-range headings was claimed to describe broader
     classes than the strings cover. REFUTED by the quoted text:
     each Cause names exactly the class its string fires for
     (missing or non-genuine confidence; a score outside the
     0-based rubric). Neighboring strings carry their own entries.
  3. The abstain dual-key message trio is reachable only through
     fake transports. NOTED, no action: the alias is the sibling
     family's documented design (the Jev wire's documented key),
     recorded in the adapter docstring and Troubleshooting.
  4. The 404 Cause sentence could be misread as claiming the model
     id travels only in the URL path. FIXED as a wording pass: the
     sentence now says the System One path on the per-model base.
- Standards axis: PASS, zero hard findings, zero judgement calls.
  Verified first-hand: error-string coverage exhaustive (29
  Troubleshooting headings against every raise site), codepoint
  scans clean (adapter exactly two U+2014 in the inherited strings,
  docs prose zero), CHANGELOG placement at the top of [Unreleased],
  copy bar held in all public prose, no test tautological or
  weakened (independent falsifiability spot-check on the usage
  counter test), docs map followed, stdlib-only transport.
- Owner verification: focused suite re-run after the fix pass: 75
  passed. Falsifiability of the strengthened probabilities test
  proven by removing the check (test fails) and restoring it.

Fix pass: local commit fff3882b, tree b3aa8886. Files:
tests/test_celeris_adapter.py (three test changes),
docs/Troubleshooting.md (404 cause wording). The adapter itself is
byte-identical to the reviewed build.

Full gates on the exact final head fff3882b (tree b3aa8886),
2026-10-16 (logs celeris-rust.log, celeris-norust.log,
celeris-smoke.log beside this report; a runtime restart killed the
first launcher script between suites, so the no-Rust suite and the
smoke ran under a second script on the identical head and tree):

- Rust-active: 4,182 passed, 9 failed, 3 skipped, 889 subtests.
  The 9 failures are exactly the documented baseline set (the eight
  test_backend_under_test parity failures plus
  test_concurrency.py::TestTranscriptAndReplay::
  test_replay_preserves_error_records). Zero new failures.
- PEIRA_NO_RUST=1: 4,144 passed, 50 skipped, 743 subtests,
  exit code 0. Fully green.
- scripts/artifact_smoke.py: PASS (SMOKE-RESULT OK; wheel
  peira-0.0.0-cp310-abi3-linux_x86_64.whl, 40 cases, 857.8 s).

## Step 6: seal verification (owner, first-hand)

- Artifact: ~/workspace/peira-trial/artifacts/celeris-v2-trial.json
  (the driver's copy in ~/workspace/peira-trial-results/ is
  byte-identical, same md5).
- md5 2089c0ae54fa5226c70aa4947ed51ad4; SHA-256
  5badc8a8badbb8ed95e69858de3e4c4f1c8fc7a31ce8a5fef801f298ebd01c7b.
- RunArtifact verify() True (re-run by the owner from the lane
  venv, not just the driver's own seal log). Termination
  complete. 4,701 results, 4,600 eligible, ranking_eligible true.
- Error census: 0 error records and 0 malformed arms in the full
  artifact (both driver heartbeats and the owner's own count
  agree). Malformed rate 0.0 [0.0, 0.0008].
- Headline metrics: ASR (conditional) 0.1696 [0.159, 0.1807]
  (unconditional 0.1685); benign accuracy 0.9785 [0.974, 0.9823];
  attacked ECE 0.0708. Robustness tax is not an artifact field;
  it is derived at publish time from benign accuracy (the #458
  design), so it is recorded here as publish-derived, with the
  0.9785 it will derive from.
- Spend: $0.1087 total across 9,402 priced calls against the
  $2.00 cap; cost per 1k decisions $0.0116. Adapter version
  celeris-1-decision, pricing table 2026-10-15.4, dataset 2.6.0.
- Run history: attempt 1 died at 3,675 results when a checkpoint
  write hit the volume's overwrite-rename ENOSPC fault (driver
  exit 1, partial intact, md5 f389350b recorded at the time).
  The workspace then suspended for six days. The resume (same
  run copy, same checkout, same $2.00 cap) validated the partial
  and completed the remaining 1,026 cases with zero errors; the
  volume had been enlarged to 200G in the interim. The 10k
  bootstrap summary took about 41 minutes of wall time under
  contention, as the driver's own comment anticipates.
- Backup email sent 2026-10-22 (gzip in
  ~/workspace/peira-trial/email-backup/), thread 1a1650d3dd8ff9ac.
- Context for the numbers: the vendor's jev-bench claims (80.0%
  accuracy, Brier 0.272) are vendor-run on their own harness.
  Peira's independent measurement gives benign accuracy 0.9785
  on the benign arm and attacked ECE 0.0708; the publish step
  owns any comparison copy.

## Addendum (2026-10-22): the full red-team report, M1, and the seal

The red team's full written report reached the owner after the
lane closed (the lane had worked from its earlier summary). It
contains one finding the summary did not carry, verified here
against the merged code:

- M1 (medium): _score_from_probabilities coerces non-canonical
  level keys when the score field is absent. CONFIRMED on main
  12a9d025 with a fake transport: probabilities {" 2": 1.0} is
  accepted as level 2, {"01": 1.0} and {"+1": 1.0} as level 1,
  and {"1": 0.5, "01": 0.5} double-counts level 1 while still
  summing to 1.0, each yielding a fabricated score instead of the
  fail-closed ProviderError the adapter's contract requires.
  The lane's in-session repro matrix exercised those spellings on
  paths where the fallback never engages, so it missed the one
  configuration that matters; that miss is recorded plainly.
  The identical int(key) code exists in the pplx sibling
  (pplx_decider.py), so the defect is family-wide.
- Impact on the sealed artifact: NONE, proven from the run's own
  transcripts (~/workspace/peira-trial/transcripts/
  celeris.full.jsonl, 9,402 records). All 1,412 score-primitive
  calls carry a server-reported score field, so the fallback
  never engaged, and every score answer's probability keys are
  canonical ("0".."4") anyway. Every score in the sealed
  artifact came from the server's own score field. The seal,
  metrics, and hashes in Step 6 stand unchanged.
- L1 (Retry-After non-finite): the same item already dismissed
  in Step 3 on the runner-cap evidence.
- L2 (low): on a 409 the adapter raises with the right status
  but drops the parsed Retry-After (only 408/429/529/5xx pass it
  through). No wrong classification; a one-line passthrough fix
  belongs with the M1 fix.
- Recommended follow-up (owner's call, not started by this
  lane): a small fix PR for the family: canonical key validation
  in _score_from_probabilities (accept only exact str(level) on
  the JSON path, reject post-normalization duplicates), tests
  for " 2", "01", "+1" and duplicate spellings that fail when
  reverted, and the 409 Retry-After passthrough. The sealed
  celeris artifact needs no action.

## Step 5: merge, wiring, canary, and the full run

- Merge: PR #478 merged 2026-10-16T09:44:06Z via GraphQL
  mergePullRequest (expectedHeadOid c5cad159), merge commit
  12a9d025. Verified on main itself: `class CelerisAdapter` at the
  merge commit, pricing_version 2026-10-15.4 with the celeris
  entry present. GOAL.md synced in the same pass (landed entry,
  inventory 35 to 36).
- Gates on the pushed tree (final evidence): Rust-active on tree
  da38869f (code-identical to the final tree) 4,286 passed with the
  baseline 9 (FAILED md5 identical across all three full runs);
  no-Rust 4,248 passed, exit 0; the focused suites on the exact
  final tree 11623b88 all pass (335 + 167 + 119 across the two bot
  fix passes); artifact smoke PASS exit 0 on the exact final tree
  after three attempts died on this box's overwrite-rename ENOSPC
  fault (fresh-allocation writes succeed; renaming over an
  existing file in the reused cargo target dir returns ENOSPC;
  a fresh CARGO_TARGET_DIR was the workaround, recorded here for
  the next lane that hits it).
- Driver wiring: roster row added to the LIVE driver
  (~/workspace/peira-ling-driver/trial_driver.py) additively, with
  no module-level import (the local queue imports that file
  against a checkout without the adapter). The run copy
  trial_driver_celeris.py differs only in the WORKTREE constant,
  pointed at ~/workspace/peira-celeris at the merged main
  12a9d025; its dataset verifies v2.6.0, SHA cb89cc9955347250,
  no errors.
- Canary (2026-10-16): 10 of 10 ok, zero errors, termination
  complete, artifact sealed and verified. The canary selection is
  all choice primitive; the score and abstain primitives were
  exercised live through this adapter in the Step 0 probe.
  Records carry sane confidences, usage priced at table
  2026-10-15.4, about 750 ms per arm. The driver's own full-run
  estimate is about $0.25 (its 2x estimate printed $0.50) against
  the $2.00 cap, so the full run launched at that cap.

## Step 4: push, PR, and the second rebase

A second rebase followed before the push: main advanced again
(#476 dashboard slice fix and #475 Decider adapter, main 65589dfb,
pricing still 2026-10-15.3, so the .4 stamp stands). The rebase
onto 65589dfb was conflict-free; survival check: the lane's four
code and data files are byte-identical to the gated tree, all three
adapter doc sections coexist, the CHANGELOG keeps Celeris at the
top with the Decider section preserved lower down, and focused
suites pass (216 tests across celeris, decider, pricing, phase0,
discovery, conformance). Final head 266d6bbb, tree da38869f.

- Push: Git Data API, commit fdcc09d0 on feat/celeris-adapter,
  parent 65589dfb, complete 8-file list, Signed-off-by trailer in
  the message. The pushed tree da38869f equals the local tree.
  No new executable files, so blob modes are uniform 100644.
- PR #478 opened with the review-readiness block. CodeRabbit
  triggered with an @coderabbitai review comment (the repo is
  under 10 stars, so reviews do not start automatically).
- Full gates re-running on the exact pushed tree da38869f
  (logs celeris-rust4.log, celeris-norust4.log, celeris-smoke4.log,
  celeris-gates-final3.log beside this report). The merge waits
  for them.
- CodeRabbit on PR #478 (triggered manually; four inline
  findings): three valid, one dismissed.
  1. CHANGELOG entry named pricing table 2026-10-15.3 after the
     restamp (Graphite flagged the same line). VALID, fixed: the
     entry now says 2026-10-15.4.
  2. The Troubleshooting retryable heading omitted the
     `celeris API error 408` string, which the adapter emits for
     an HTTP 408 (the sibling adapters list it). VALID, fixed:
     the heading now lists 408 first. A full re-scan of the
     adapter's status branches against the headings confirms
     family-parity coverage (the bare fall-through form has no
     catch-all heading in any sibling either).
  3. The pricing entry's `official` confidence named no source.
     VALID as a documentation gap, fixed by verification rather
     than a downgrade: the rate was verified 2026-10-16 against
     Celeris's official model page (celeris.ai/decisions, which
     states the $0.04 input rate and free output), now recorded
     in the entry note, the table source string, and source_urls.
  4. _parse_retry_after should reject non-finite values.
     DISMISSED: the parser is byte-identical to the merged
     Perplexity sibling's (the family parser), the runner caps
     any parsed value at MAX_RETRY_AFTER_S (60 s) at consumption,
     and NaN collapses to a 0.0 wait; forking one sibling's parser
     over a capped, harmless parse is the worse inconsistency.
     (The red team's LOW on the same behavior was dismissed on
     the same evidence.)
  Fixes pushed as c5cad159; pushed tree 11623b88 equals the
  local tree. Focused verification on the final tree: 167 passed
  (pricing, phase0, celeris, prose style) plus 119 passed (doc
  links, celeris, discovery, conformance). No code file changed
  in either bot fix pass.
- Bot finding (Graphite, on PR #478): VALID and fixed. The
  Troubleshooting union resolution in the first rebase had landed
  three Celeris entry groups between pplx-decider headings and
  their Cause bodies, orphaning the pplx entries (the reviews had
  examined the pre-rebase file, and no test asserts entry
  adjacency). The span was rebuilt from the two clean sources:
  diff against main shows the file now differs only by the added
  Celeris span (117 lines), the pplx span byte-identical to
  main's, both seams inspected. Fix commit e1a4c10c, pushed as
  abb16226; pushed tree 217670e3 equals the local tree. The
  docs-reading suites (prose style, doc links, and every adapter
  suite that quotes Troubleshooting) pass on the final tree:
  335 passed. The full-gate run on da38869f remains the code
  evidence; the only delta to the final tree is this docs file.

## Step 3b: rebase onto the Perplexity merge and the .4 restamp

While the gates above ran, the Perplexity lane merged (PR #473,
main 06f19579), taking pricing 2026-10-15.3 on main, exactly the
collision Step 1 predicted. The lane rebased onto the explicit SHA
06f19579dcb39941c2c5694e889939d839977b02:

- Conflicts were parallel-insertion collisions only (Adapters.md
  one hunk, Troubleshooting.md four, pricing.json two), resolved as
  unions; the pricing head hunk and model entries were rebuilt
  programmatically from main's table plus this lane's entry.
- Restamp: this lane now carries pricing **2026-10-15.4**
  (pricing.json version and _comment segment, both
  test_phase0_primitives.py pins). The in-flight partials are
  unaffected for the Step 1 reason: no running process imports
  origin/main, and peira-trial-code was not touched.
- Survival check: the adapter and its test file are byte-identical
  pre/post rebase (diff 0 lines); CHANGELOG keeps the Celeris
  section at the top of [Unreleased] with the Perplexity section
  present below; pyproject carries both entry points; pricing.json
  differs from main only in the _comment, the version, and the
  celeris entry. Focused suites on the rebased tree: 269 passed
  (celeris, pplx, pricing, phase0, discovery, conformance), and
  check_no_emdashes.py and check_public_surface.py both exit 0.
- New final head: 35edba38, tree 04c05b18. Because the tree moved,
  the full gate set re-ran on this exact head. The first re-run
  launch lost both suites to runtime session reaps (one pytest
  exited 143 mid-run; the launcher died with it), so the set ran a
  third time detached under nohup (logs celeris-rust3.log,
  celeris-norust3.log, celeris-smoke3.log, celeris-gates-final2.log
  beside this report):
  - Rust-active: 4,252 passed, 9 failed, 3 skipped, 889 subtests;
    the sorted FAILED list is byte-identical to the pre-rebase
    run's (same md5), i.e. exactly the documented baseline set.
  - PEIRA_NO_RUST=1: 4,214 passed, 50 skipped, 743 subtests,
    exit code 0. Fully green.
  - scripts/artifact_smoke.py: PASS, exit code 0.
