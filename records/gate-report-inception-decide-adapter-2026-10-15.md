# Gate report: Inception Mercury Decide lane, 2026-10-15

Lane: build the Mercury Decide adapter on the closest verified sibling
pattern, checkpoint-merge it, wire the live driver, canary, full v2 run
under a cap set from the canary projection, seal, back up.
Stop before publishing (owner publishes).

Relaunch note: the first Inception lane died in a daemon restart about
nine minutes in and left no worktree, branch, or notes. This lane starts
clean; nothing was lost because nothing existed yet.

Base: origin/main at 5b0f85d1 (Strands merge, PR #471) at lane start.
Pricing version on main at lane start: 2026-10-15.2 (Clef took .1,
GLiNER took .2; the Perplexity lane holds .3 on its open PR #473;
this lane takes the next free version at merge time and restamps on
rebase if a sibling lands first, per the Perplexity precedent).

## Step 0: live docs read and probe

Lane 2 also died in a daemon restart (~23:54 EDT) after writing this
skeleton. The owner then ran the probe personally on 2026-10-16
~03:58 UTC; findings below are owner-verified and durable. Lane 3
starts from the adapter step.

Credential: connector custom.inceptionlabs via the surrogate helper
(add_surrogate_to_request, allowed_hosts api.inceptionlabs.ai). The
stored key works; no auth investigation is needed.

- GET https://api.inceptionlabs.ai/v1/models returned 200 (chat
  models mercury-2, mercury-2.5, and more). The decide model's
  pricing entry sat below the probe output's truncation point; lane 3
  re-reads the full list to establish the cost basis (new accounts
  carry free-token grants; record which basis applies).
- COST BASIS (lane 3, 2026-10-16): the full models list re-read with
  the stored key. mercury-decide's entry: description "Typed-decision
  preview. Decisions endpoint only.", supported_endpoints
  ["decisions"] only, context_length 65,536, pricing prompt
  "0.00000002" per token and completion "0" — that is $0.02 per 1M
  input tokens with output free, the same rate as pplx-decider.
  Cache read and write prices are "0". The metered rate is the basis
  for the pricing-table entry and the cap math (full-trial projection
  at the sibling's token counts is roughly $0.20, far under the $2
  cap); any free-token grant on the account would only lower the
  invoiced amount, not the measured rate.
- Decisions endpoint, from the vendor's OpenAPI
  (api.inceptionlabs.ai/openapi.json) and the docs page
  api-reference/decisions/create-a-decision: POST
  https://api.inceptionlabs.ai/v1/decisions, Bearer auth, body
  {model, state, questions} with System One question shapes (noul
  with instructions; choice with a criteria map; score with
  instructions, a criteria list, optional required). No streaming.
- LIVE CALL VERIFIED by the owner: one question of each type with
  model "mercury-decide" returned 200 in 1,385 ms. The response
  stamped model "mercury-decide" and carried all three answer shapes
  in System One form (noul value; choice with probabilities and
  confidence; score with legend, probabilities, and confidence),
  probabilities coherent, plus usage {input_tokens: 217,
  output_tokens: 3}.
- Vendor-documented error shapes: 401 invalid_api_key, 402
  account_error (billing inactive or quota), 404 model_not_found,
  413 request_too_large (20 MiB gateway body limit), 422 validation
  or upstream_error, 429 rate_limit_exceeded, 500 server_error,
  502/503/504 upstream errors and timeouts.

Adapter direction (owner-set): pin "mercury-decide" with the
Von/Strands response-stamp check; sibling pattern is the Perplexity
decisions adapter carrying the System One question payloads
byte-identical to the Jev family's; the pricing version discipline
in this report's header applies (take the next free version at merge
time, restamp on rebase if a sibling lands first).

## Step 1: adapter build (lane 4, 2026-10-16)

- Worktree ~/workspace/peira-inception, branch
  feat/inception-decide-adapter, based on origin/main 5b0f85d1.
- Files: python/peira/adapters/mercury_decide.py (new),
  tests/test_mercury_decide_adapter.py (new),
  pyproject.toml (entry point mercury-decide), pricing.json
  (mercury-decide at $0.02/$0, table version 2026-10-15.4),
  docs/Adapters.md, docs/Troubleshooting.md, CHANGELOG.md, plus
  the two phase0 pricing-version pins moved to 2026-10-15.4.
- Structure mirrors the final Perplexity adapter (including its
  second-red-team strictness: strict confidence resolution with no
  midpoint default, required usage with strictly typed counters,
  the genuine-distribution score fallback, the abstain range check
  and the dual-key ambiguity refusal), with the Inception deltas:
  single pin mercury-decide, endpoint
  https://api.inceptionlabs.ai/v1/decisions, INCEPTION_API_KEY, and
  the vendor error catalogue (401 invalid_api_key, 402
  account_error worded as billing inactive or quota exhausted, 404
  model_not_found, 413 request_too_large at the 20 MiB gateway
  limit, 422, 429, 500/502/503/504 transient).
- Pricing version: 2026-10-15.4 taken directly at build. Sequence
  is Clef .1, GLiNER .2, Perplexity .3 (PR #473, open at build
  time), Inception .4. When PR #473 lands first this lane rebases
  and keeps .4 with both entries present. Nothing in this change
  touches in-flight partials: Laya's running drivers validate
  against their own checkout's table (2026-10-15.1), and no merged
  table ever reaches a running driver.
- Question text verified byte-identical to the Perplexity
  sibling's builders for all three primitives (dict equality and
  JSON-bytes equality both true, programmatic compare), and the
  sibling builders were themselves verified byte-identical to
  Jev's. Codepoint scan of the new adapter: exactly two U+2014,
  both inside the inherited measurement strings.
- Environment note: the worktree venv install needs PATH with the
  venv and cargo bin directories plus RUSTUP_HOME/CARGO_HOME set,
  or maturin falls back to its puccinialin bootstrap and fails
  (the Perplexity lane's diagnosis; reproduced and applied here).

## Step 2: merge checkpoint

Reviews run on local head b779d409 (base 5b0f85d1), 2026-10-16:

- Standards axis: one HARD finding, fixed in full. The module
  docstring carried four semicolons in prose (the
  calibrated-answers sentence, the probe sentence, the "(3;
  output is billed free)" parenthesis, and the placeholder
  sentence), and the same fault sat in the SUPPORTED_MODEL_IDS
  and _SCORE_LEVELS variable docstrings: six prose semicolons in
  all, inherited verbatim from the sibling and invisible to the
  checker scripts, which do not scan adapter modules. All six
  rephrased with full stops; the measurement strings and the
  quoted error strings (which keep semicolons by the
  Troubleshooting convention) are untouched. The axis otherwise
  passed the lane: em dashes confined to the two exempt
  instrument strings, every error string present in
  Troubleshooting, trailer present, no test weakened or deleted.
  Its two judgement calls were adopted rather than dismissed:
  a test now pins the question builders byte-identical to the
  Jev module itself (dict and JSON-bytes equality, levels
  included), so the identical-decision-spaces claim fails loudly
  if either side's instrument text drifts, and the construction
  test asserts the literal endpoint URL instead of the constant
  it is assigned from. (Provenance note: an earlier draft of
  this section recorded a clean PASS from a review handoff whose
  coordinator children did not match this lane's agents. The
  lane's own Standards report, delivered in full after the
  checkpoint summary was written, is the one dispositioned here;
  its broader scope is why the fix pass has two parts.)
- Red team (fresh eyes, hostile fake transports; every repro
  re-run as a pinning test after the fix pass): no hardening
  dropped versus the Perplexity sibling; the catalogue, echo,
  usage, confidence and solo abstain paths all held. Findings:
  1. MEDIUM, VALID: a direct score outside [0, 4] was clamped
     into a fabricated extreme (99 read as 1.0). Fixed: terminal
     outside a 0.01 float-dust band, with the new error string
     documented in Troubleshooting in the same commit. This
     deliberately diverges from the sibling, which still clamps
     (its test_score_clamped enshrines it); the same fabrication
     class was a HIGH fix in the sibling's own second red-team
     round for the fallback path.
  2. MEDIUM, VALID: the score fallback's loose int(key) accepted
     non-canonical keys ({"0": 0.5, "00": 0.5} faked a total of 1
     from one level; " 1", "+1", int and float keys coerced).
     Fixed: only canonical decimal spellings name a level.
  3. MEDIUM, VALID: the abstain dual-key check compared with ==
     before type-checking, so {"abstain": 1, "noul": True} was
     accepted (1 == True) with the bool never checked. Fixed:
     every carried value is type-checked before any comparison.
  4. MEDIUM, VALID: vendor error detail was copied verbatim into
     ProviderError text, so a gateway echo of the Authorization
     header would carry the API key into logs and artifacts.
     Fixed: the detail is scrubbed of the key at the raise site.
  5. MEDIUM, PARTIALLY VALID: Retry-After "inf" passed through.
     The non-finite case is fixed (dropped to None). Finite
     values pass through uncapped at the adapter because the
     runner caps the delay at min(retry_after, MAX_RETRY_AFTER_S)
     at consumption (runner.py line 1522, verified); the
     HTTP-date form falls back to the runner's backoff, as on
     the sibling.
  6. LOW, VALID: _latency_ms from an injected transport was
     unvalidated (a string escaped decide() as a bare ValueError).
     Fixed: junk reads as 0.0 (unknown); latency is run metadata,
     not a measurement input, and the real transport always sets
     a finite non-negative float.
  7. LOW, DISMISSED: malformed case inputs (None prompt coerced
     by str()). The handling is sibling-identical and measured
     runs only see schema-validated cases: the runner validates
     every case with validate_case_dict before dispatch (the
     Perplexity lane's disposition, re-verified here).
  8. LOW, DISMISSED: a 200 body carrying a top-level error key
     beside valid answers/model/usage is accepted. Every field
     the measurement uses is validated and echo-checked; unknown
     keys are ignored by design (pinned by
     test_unknown_keys_ignored), and an error-only 200 fails
     closed on the missing answers.
  9. LOW, PARTIALLY VALID: docs precision. Adapters.md omitted
     408 from the retryables; fixed. The docstring now cites the
     models list for the 65,536 context limit; the 413 limit's
     source is the vendor OpenAPI catalogue recorded in Step 0 of
     this report (Troubleshooting cause lines carry no citations
     anywhere in the file). The pricing date/version point is
     dismissed: the table's date is the 2026-10-15 pin date the
     whole .1-.4 revision series shares (the Perplexity tree at
     .3 keeps the same date), and the .4 jump is the documented
     sequence, with .3's segment joining on the rebase.
  Fix pass: local commit a9a5da52 (adapter, tests, Adapters.md,
  Troubleshooting.md). Focused suite 77 passed; both surface
  checkers exit 0.
  SIBLING FLAGS (out of scope, for the owner): findings 1-6 all
  exist in the merged Perplexity adapter in the same form, and
  findings 1-3 and 6 in Clef's lineage as well (the Perplexity
  gate report already flags Clef's confidence default and usage
  tolerance). No sealed measurement is affected: the probes and
  canaries showed none of these wire shapes. A family hardening
  pass should adopt the same fixes.
- Spec fidelity axis: PASS, no missing, partial, wrong, or
  unrequested behaviour found. The axis verified the diff is
  exactly the eight lane files on the stated base, the pin and
  stamp check, the byte-identical builders, the error catalogue
  split, the pricing rate and the .4 version discipline, the
  docs coverage, and the inherited fail-closed strictness, item
  by item against the brief. (Reviewed head b779d409; the two
  fix commits that followed came from the red team's findings
  and the Standards finding, add one documented error string,
  and change no spec surface.)

## Push + PR

- Build commit b779d409 and red-team fix commit a9a5da52 pushed
  via the Data API as commit c709a33d on branch
  feat/inception-decide-adapter, parented on 5b0f85d1, with the
  complete eight-file list and the Signed-off-by trailer in the
  message. Pushed tree 40136b05 verified identical to the local
  tree. Both new files are regular 100644 blobs (no executables
  in this lane).
- Rebase onto current main 06f19579 (PR #473's merge, explicit
  SHA) completed as local head 4dcdc2b6. Conflicts landed exactly
  where predicted (pricing comment and source, the two phase0
  pins, pyproject entry point, the Adapters and Troubleshooting
  junctions, CHANGELOG auto-merged). Resolution was verified by
  construction, not by eye: both docs were rebuilt as main's
  content plus this lane's block with multiset (Counter) proofs
  that nothing was dropped or duplicated after a first
  line-union resolution was caught silently dropping sibling
  lines, and pricing.json carries both lanes' comment segments,
  both source clauses, both model entries and version
  2026-10-15.4. Survival check: the adapter and its tests are
  byte-identical across the rebase; focused and neighbour suites
  on the rebased tree pass 235 (mercury-decide 77, pplx-decider,
  phase0, pricing).
- The first remote branch could not be moved to the rebased tree
  (non-fast-forward), so per the house remedy the identical tree
  went up as fresh branch feat/inception-decide-adapter-r2,
  commit 1db02c6c, parented on 06f19579, tree 61d7a92d verified
  identical to the local rebased tree.
- PR #474 opened on the r2 branch with the capability table,
  live-state evidence, cost basis and the review-readiness block.
  CodeRabbit triggered with an @coderabbitai review comment.
- The lane's own Standards report then arrived in full with a
  broader scope than the summary that reached this lane first
  (two more docstring semicolons, two adopted judgement calls).
  The completed fix pass (local commit cdc5e815, tree 67205e31,
  focused suite 78 passed) changed the exact head, so the lane
  restacked: fresh branch feat/inception-decide-adapter-r3
  (remote commit dd72992c, tree verified identical to the local
  final tree), PR #477 opened with the same body plus a restack
  note, PR #474 closed with a pointer comment in the same pass,
  CodeRabbit triggered on #477, and the full gates relaunched on
  the final tree. The first gate run (on the r2 tree) was
  stopped as superseded.
- The full Standards report (delivered after the first fix
  commit) extended the semicolon finding to two variable
  docstrings and raised two judgement calls (a cross-adapter
  byte-identity test against the Jev module; a literal endpoint
  assertion). Both were adopted in a further fix commit, but the
  lane's insertion script left the new test class triplicated in
  the committed tree (the working tree and the 78-test focused
  run each carried one copy; the commit captured three). The
  owner side caught and repaired this: the stack was rebuilt
  deduplicated (local head cdc5e815), restacked as branch
  feat/inception-decide-adapter-r3 (commit dd72992c, tree
  67205e31, verified identical to this lane's intended final
  tree and to the local head's tree), and opened as PR #477,
  with CodeRabbit already engaged there. PR #474 was closed by
  this lane with a pointer comment to #477, restoring the
  one-live-PR rule. The merge, the exact-head gates on #477 and
  the GOAL.md sync are on the owner side's track; this lane ran
  the full Rust-active suite on the pre-Standards-completion tree
  (61d7a92d) to 9 failed / 4254 passed, exactly the documented
  baseline of 9 pre-existing failures with zero new, and the
  focused suite on the final content passes 78.
- Incident note (for the owner): while stopping its own
  superseded gate run, this lane sent SIGTERM to three processes
  matched too broadly (PIDs 241645, 241646, 235052, 235059 at
  about 06:35 UTC). One was this lane's no-Rust suite; the others
  carried command lines referencing a celeris-rust gate script
  and a write under ~/workspace/goals/, so a sibling lane's gate
  run may have been interrupted and should be re-checked.
- Driver wiring: the mercury-decide roster row is in the live
  driver (~/workspace/peira-ling-driver/trial_driver.py) after
  the pplx-decider row, on the generic adapter_spec path with
  credential custom.inceptionlabs. No MODEL_CONFIG entry (no
  documented rate limit, sibling precedent).
- The custom.inceptionlabs connector doc was filled in from the
  scaffold template with the verified facts only (bearer
  placement, the models-list pricing, the decisions wire, the
  error catalogue).

## CodeRabbit

(pending)

## Merge

(pending)

## Driver wiring, canaries, runs, seals

(pending)

## Merge lane (owner-dispatched, 2026-10-22; David's order: "Do the mercury trial now")

- Verified PR #477 branch head dd72992c / tree 67205e31 matches this
  report before touching anything. origin/main at lane start:
  12a9d025 (Celeris adapter merged as PR #478).
- Pricing audit: main's table is version 2026-10-15.4 with 65 models
  including celeris-1-decision and both pplx-decider rows but NO
  mercury-decide row. This branch's .4 carries mercury-decide but no
  celeris row. Per the merge rule the rebased table therefore holds
  both rows (66 models) and the version bumps to 2026-10-15.5.
- Rebase onto the explicit SHA 12a9d025 in worktree
  ~/workspace/peira-mercury. Conflicts in exactly three files,
  resolved and proven, not eyeballed:
  * pricing.json: _comment = main's full comment (Celeris segment
    closing at .4) + the Mercury segment reclosed at .5; source =
    shared prefix + Celeris clause + Mercury clause; version
    2026-10-15.5; parsed result verified: all 65 main model rows
    identical, mercury-decide row identical to the branch's, 66 rows.
  * docs/Troubleshooting.md: both lanes had appended their entry
    blocks after the same base line; resolution is main's file with
    the 133-line Mercury block inserted after the Celeris block,
    proven a pure insertion (multiset equality + diff opcodes).
  * CHANGELOG.md: same shape (Celeris block, then the 27-line
    Mercury block with its version sentence moved to 2026-10-15.5),
    multiset-verified against main + block after repair of a dropped
    separator blank line the first construction missed. Caught
    honestly: the first rebase --continue committed the still-
    conflicted CHANGELOG (the resolver script had failed on a bad
    anchor before writing it); the file was then resolved properly
    and the commit amended; the final tree carries no markers.
  * The two phase0 pricing pins (tests/test_phase0_primitives.py)
    moved 2026-10-15.4 -> 2026-10-15.5 to match the bumped table.
- Survival check: python/peira/adapters/mercury_decide.py and
  tests/test_mercury_decide_adapter.py are byte-identical between
  the pre-rebase tree (dd72992c) and the rebased head. Diff vs main
  is the seven lane files (pricing.json +12/-3 lines of text).
- Rebased local head after amendments: bd3e1bcf (single commit on
  12a9d025, Signed-off-by trailer present).
- Gate incident (2026-10-22 ~19:17 UTC): a box-wide process kill
  (platform restart; /tmp wiped, every detached process on the VM
  died, including other lanes' charges, which are the owner's to
  recover) killed the first full-gate run at ~31% of the Rust-active
  suite with no exit code recorded. Gates relaunched on the quiet
  box from a script kept under ~/workspace/peira-trial/logs/ (the
  /tmp copy died with the restart). Focused suites on the rebased
  head had already passed: 217 passed (mercury-decide, phase0 at the
  .5 pins, pplx neighbours), zero failures.
- Exact-final-head gates on the rebased tree d2ba9a42 (head
  bd3e1bcf local): Rust-active 9 failed / 4,364 passed, the FAILED
  list being exactly the documented baseline (8 Rust-parity
  test_backend_under_test + the concurrency replay test), zero
  new; no-Rust exit 0 with 4,326 passed, fully green;
  scripts/artifact_smoke.py PASS (SMOKE_EXIT:0, wheel built from
  the staged tree, both modes exercised through the installed
  package). Log set: ~/workspace/peira-trial/logs/mercury-gate-*.log.
- Push: the rebased tree went onto the EXISTING r3 branch in place
  via the Git Data API (the PR David named stays the one live PR;
  no branch was deleted or recreated). All eight file blobs match
  the local blob SHAs; the API-built tree d2ba9a42 is byte-identical
  to the gated local tree; new head commit 1634ed87, parented on
  12a9d025, message carrying the Signed-off-by trailer. PR #477
  then read head 1634ed87 against base main 12a9d025, mergeable
  True.

## CodeRabbit

The 2026-10-16 trigger on the old head was rate-limited by
CodeRabbit (free OSS review limit) and produced no findings (its
summary comment is the limit notice). Re-triggered 2026-10-22 on
the final head 1634ed87 with an @coderabbitai review comment on
PR #477 (comment 6351348515); disposition of any findings follows
below.
- CodeRabbit review of head 1634ed87 (triggered 2026-10-22,
  review comment posted the same day): four inline findings, all
  Minor. Dispositions:
  - FIXED, Troubleshooting.md missing-API-key entry: the body left
    its inline code span unclosed, carried a placeholder that did
    not match the error message's own placeholder, and had no
    closing punctuation (verbatim from the branch; the three
    reviews checked the heading, not the body prose). Body now
    closes the span, matches the message, and ends the sentence.
  - FIXED, mercury_decide.py transport: http.client.HTTPException
    (IncompleteRead on a mid-response drop, BadStatusLine) is
    neither a URLError nor an OSError, so it escaped the 408
    classification the module docstring promises. The except tuple
    now catches it; regression test
    test_http_client_exception_maps_to_408 covers both raise
    points and fails when the adapter change is reverted
    (verified).
  - FIXED, pricing.json _comment: the merge-lane splice truncated
    the Mercury segment's date to "6:" (the lane's own defect;
    its earlier comment check was circular, built from the same
    construction it meant to verify). Restored to "2026-10-16:".
  - DISMISSED, pricing.json date field: the finding asks for the
    table date to move to 2026-10-16 with the Mercury source
    citation. Both predecessor tables (main's .4 and the branch's
    .4) keep date 2026-10-15 alongside 2026-10-16 verification
    citations, so the merged table preserves both lanes'
    convention; the version bump to .5 and its two pins already
    moved together.
  The three fixes ride in the same commit as the restack (the
  branch still carries exactly one commit on 12a9d025); the full
  gate set re-runs on the new exact head before the merge.
- Main moved during the fix pass: PR #480 (score-key validation
  for the Celeris and Perplexity adapters) merged as c98cc2d1.
  Per the pre-merge origin check, the lane commit was rebased
  onto c98cc2d1. #480 touched CHANGELOG.md, docs/Adapters.md and
  docs/Troubleshooting.md but not pricing.json; the doc merges
  were verified as exact unions (every line of new main present;
  the only superseded lines are the ones #480 itself rewrote).
  Survival check: the adapter, its tests, pricing.json,
  pyproject.toml and the phase0 pins are byte-identical to the
  gated 992ef6b7 versions; the diff against c98cc2d1 is exactly
  the lane's eight files. Focused suites on the rebased head:
  299 passed (mercury, celeris, pplx, phase0). New head 08507190,
  tree 03926c78; the full gate set re-runs on this exact head.
- Process note: the superseded gate chain for the pre-#480 tree
  was stopped by pattern-matched SIGTERM from this lane; the
  match also caught exec wrapper processes whose command text
  mentioned the gate script (including this lane's own). No
  repository state was harmed; the lesson (kill by exact argv,
  never by substring over wrapper cmdlines) is recorded here.

## Merge

Merged 2026-10-23 via the GraphQL mergePullRequest mutation
(merge commit, matching main's convention; REST not attempted
after the standing 404 history): PR #477, head 7409d805 (tree
03926c78, byte-identical to the locally gated tree), parent
c98cc2d1. Merge commit 1bf0407bfb356e7839e3c71fdc979a35296f5094.
All four CodeRabbit threads answered before the merge. Final
gates on the exact head: Rust-active 9 failed / 4,371 passed
(the documented baseline list, identical), no-Rust exit 0 with
4,333 passed, artifact smoke PASS. Post-merge verification on
origin/main at 1bf0407b: MercuryDecideAdapter present in
python/peira/adapters/mercury_decide.py, the mercury-decide
entry point present in pyproject.toml, pricing table at
2026-10-15.5 with the mercury-decide row ($0.02/$0, official)
among 66 models. GOAL.md's Recently merged list and adapter
inventory updated in the same pass.

## Trial (Mercury execution lane, 2026-10-22)

- Run worktree: ~/workspace/peira-mercury-trial at the merge
  commit 1bf0407b (the brief's suggested name was already this
  lane's scratch dir; only the driver's tree pointer matters).
- Driver: the live trial_driver.py hard-pins its peira tree with
  sys.path.insert(0) at peira-trial-code, which must not be
  modified (its pricing table is held at 2026-10-15.1 for the
  Laya queue), so per the established lane convention (the
  Celeris lane's trial_driver_celeris.py differs from the live
  driver by exactly this one line) the run uses
  trial_driver_mercury.py, a copy differing only in WORKTREE ->
  peira-mercury-trial. Run python, cwd, env per the brief.
- Canary (10 cases, suite v2-canary): CLEAN. 10/10 answered,
  zero errors in both arms, sealed and verified by the driver;
  per-arm usage carries model mercury-decide, tokens_in
  268/324 on the first case, price_table_ref 2026-10-15.5;
  canary spend about $0.0001, projecting the full run at about
  $0.06, far under the $2 cap.
- Full run launched detached 2026-10-23 ~00:33 UTC with
  --budget-usd 2 --skip-inspection-gate; log at
  ~/workspace/peira-trial/logs/mercury-full-2026-10-22.log;
  ceiling $2.00 recorded by the driver (its own 2x estimate was
  $0.50). Progress is tracked by the partial's persisted result
  count in ~/workspace/peira-trial/partials/.
- Full run HALT 2026-10-23 00:48 UTC at 413 completed cases:
  the driver's spend-protection rail tripped on 10 consecutive
  benign-arm errors. Census of the partial's error arms: 11
  attacked and 9 benign, every one error_code rate_limit,
  starting at result index 401 (case v2-cnl-0402) after about
  15 minutes and 800 calls at the run's dispatch pace; sampled
  arms show retry_count 2, so the runner's transient retries
  fired before the errors were recorded. Spend at halt $0.0051
  of $2. The partial is intact and resumable at 412 persisted
  results; the response is the driver's own designed path
  (cool-down, then resume with the identical command; no
  partial edit, no condition change).
- Tranche 2 (resume 01:27 UTC after a 40-minute cool-down and a
  clean single-call probe): validated and resumed at 413, then
  HALTED 01:35 UTC by the rolling-error rail (benign-arm error
  rate 22.0% over the last 50 cases against a 20% threshold).
  Partial at 630 results, 25 error-arm cases, $0.0067 spent.
- Tranche 3 (resume 02:35 UTC after a 55-minute cool-down and
  another clean probe): resumed at 631, banked 20 more results,
  then the platform restart wave (three runtime restarts in the
  small hours) killed the detached driver mid-flight; no HALT
  line, partial intact at 650 results, 26 error-arm cases,
  about $0.007 spent of the $2 ceiling. No driver process is
  running now.
- Assessment at the stop: the vendor's decisions endpoint is a
  preview product with a quota far below the runner's dispatch
  pace (first wall after about 800 calls in 15 minutes; a
  half-refilled bucket errors at 6-22%). Every tranche records
  its rate-limit arms permanently (11 cases in tranche 1, 14 in
  tranche 2, 1 in the 20-case tranche 3 fragment). Grinding the
  remaining 4,051 cases out in tranches at this pattern would
  seal with a rate-limit census of roughly 4-6% of all cases,
  clustered by case order, which is a materially degraded
  measurement. The levers (a paced fresh run under different
  recorded dispatch conditions, a vendor quota raise, accepting
  the census, or parking the model) are owner decisions. The
  lane stops here with the partial valid and resumable; the
  merge (Part A) is complete and verified. Backup email is
  NOT sent: there is no seal to back up yet.
- Correction to the stop assessment above: the tranche 3
  driver SURVIVED the restart wave (the restarts killed agent
  exec wrappers only; the setsid driver and its workers are
  alive and advancing, 700 results at the check after the
  correction, 4 error cases in tranche 3's first 70). The
  "lane stops here" conclusion was written on a false premise
  (a process scan raced the driver's worker spawn) and is
  withdrawn: the run continues under monitoring, and the
  escalation options stay on the table only if the rails halt
  it again or the error census grows past a defensible share.
- Final lane state at handoff (2026-10-23 ~04:15 UTC): the
  owner's own resume script (mercury-owner-resume.sh, created
  02:36 UTC) took over the resume cycle after tranche 3 halted
  at 02:39 UTC; owner instances carried the partial from about
  660 to 2,625 results. At the handoff check no driver process
  is running. Partial: 2,625 of 4,701 results persisted, 60
  cases carrying a rate_limit error arm (94 error arms total),
  spent $0.0301 of the $2 ceiling, pricing stamped 2026-10-15.5.
  The partial remains valid and resumable with the identical
  command. This lane launches nothing further, to avoid
  double-driving the partial against the owner's cycle. When
  the run seals, the remaining steps are the driver's own
  verify (built into its seal path), the copy already made by
  the driver into ~/workspace/peira-trial-results/, the gzip
  into ~/workspace/peira-trial/email-backup/, the standing
  backup email, and the run record appended here.
- Wire-level cause of the error clusters (from the partial's
  own records, banked 2026-10-23 while the owner tends the
  run): concurrency, not content. The run's max_concurrency
  is 4 and dispatch began at limit 4; the first rate_limit arm
  lands at result 401 after roughly 800 calls in 15 minutes.
  The runner's adaptive controller steps the dispatch limit
  down through the 250-749 bands (4, then a 3/2/1 mix, with 54
  cases at limit 1 in the 500-749 band) and from result 750
  onward every banked case ran at limit 1, fully serialized,
  which is where the long clean stretches come from. Totals
  in the partial's retry_policy at 2,625 results:
  rate_limit_hits 91, total_retries 262, max_retries 2.
  Error cases by family (crosslingual_shift 26,
  canary_leakage 11, history_leakage 8, judge_sycophancy 8,
  frequency_salience 7) follow the suite's block ordering,
  i.e. the families that happened to be running while the
  bucket was hot; 56 of 60 error cases are the choice
  primitive. No content sensitivity is indicated: the vendor's
  preview decisions endpoint tolerates one call in flight at
  this adapter's latency but not four. Observability gap,
  recorded for the owner: the partial's error_log entries
  carry only arm, case_id and error_code, so the vendor's 429
  body and any Retry-After value are not preserved anywhere
  in the run record; the adapter does pass Retry-After
  through to the runner (red-team verified), but nothing
  seals what the vendor actually sent.
- Partial health check during the owner's resume cycle
  (2026-10-23 ~04:45 UTC): the partial at 2,712 results
  parses cleanly through the repo's own RunArtifact path,
  all 2,712 case_ids are unique (no checkpoint-race
  duplication), termination reads partial. The run's data
  is intact; the short-lived driver processes tonight are
  platform restart churn, not validation failures.
- Run provenance, three segments (owner-confirmed
  2026-10-23): segment one ran under the runner's adaptive
  concurrency, dispatch limit 4 collapsing to 1 under the
  429 pressure (the partial's own dispatch_limit bands are
  the record), and ended in the rails' halts at 413 and 630
  banked. Segment two was an owner relaunch at the default
  limit: it burst, tripped 10 consecutive benign-arm errors,
  and halted at 2,712 banked. Segment three is owner-tended
  with mercury-decide pinned to max_concurrency 1 in the
  driver copy's MODEL_CONFIG (the documented mechanism, with
  a dated comment citing this lane's diagnosis), relaunched
  04:52 UTC from 2,712 with 1,989 cases remaining and clean
  heartbeats (rate_limited 0). The seal record must carry
  this history: adaptive 4-to-1 in segment one, burst halt
  in segment two, pinned 1 in segment three.

## Seal (2026-10-23)

SEALED 2026-10-23 07:50 UTC at
~/workspace/peira-trial/artifacts/mercury-decide-v2-trial.json:
4,701 results, termination complete, verified through the
repo's own path (RunArtifact.verify() True, re-run by this
lane after the seal). md5 949a09c505b8bf12e6cb649fdd71d155,
SHA-256 a4949cb1fac301e327615e56ebf1b5a354bdb4cf6629303eb66377ce67debe93,
16,044,122 bytes. Headline metrics: ASR unconditional 0.1732
[0.1626, 0.1842]; ASR conditional 0.1649; ASR excluding
malformed 0.1618 [0.1514, 0.1728]; benign accuracy 0.9806
[0.9762, 0.9842]; malformed rate 0.0151 [0.0120, 0.0190];
attacked ECE 0.1278; n_eligible 4,554 of 4,701 (ineligible:
benign_malformed 57, benign_wrong_decision 90,
benign_abstained 0). Spend $0.0513 of the $2 cap (9,288
calls, all priced); pricing stamped 2026-10-15.5.
Error census disclosed in the artifact: 71 cases carry an
error arm (68 rate_limit, 3 api_error), every one from the
run's early hot segments; the pinned-concurrency running
was error-free, including the final segment's 1,876 cases
(benign_err 0, attacked_err 0, rate_limited 0 on every
heartbeat). Concurrency history for the seal record:
segment one under the runner's adaptive concurrency
(dispatch limit 4 collapsing to 1; halts at 413 and 630
banked), segment two an owner relaunch at the default
limit (burst; 10 consecutive benign errors; halt at 2,712
banked), segment three owner-tended with mercury-decide
pinned to max_concurrency 1 in the driver copy's
MODEL_CONFIG, completing the remaining 1,989 cases plus
restart-interrupted continuations under the same pin.
The driver's own copy in ~/workspace/peira-trial-results/
is md5-identical to the sealed artifact. Backup email
sent with the gz attached (1,985,752 bytes), thread
1a167bf97d568493. Publishing is the owner's; nothing was
staged into publish-runs.
