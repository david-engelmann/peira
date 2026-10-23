# Gate report: Cerno adapter (apertixai/cerno-4b)

Lane: CERNO EXECUTION (second dispatch; the first lane died in a
daemon restart during recon with nothing stranded — verified: no
worktree, branch, or gate report existed at dispatch).
Opened: 2026-10-22 ~22:50 EDT. Deadline frame: post drafting starts
~09:28 EDT 2026-10-23; the freeze pass publishes whatever is sealed
by then. Full-run projection must be reported to the owner if it
cannot finish by ~08:00 EDT.

## Mission

Build CernoAdapter for apertixai/cerno-4b, merge at the full bar,
wire the live driver, canary, full v2 trial to a verified seal +
backup email. STOP before publishing; the owner publishes.

## Verified recon (2026-10-22, first hour)

- Family: apertixai/cerno-{27b,9b,4b}, Apache-2.0, Jev-style System
  One (state + typed questions in, calibrated probability per
  option out, one forward pass, no generation). Qwen3.5-text bases.
  Full record: final addendum of
  files/jev-competitor-landscape-2026-10-14.md.
- cerno-4b HEAD revision (HF API `sha`, read 2026-10-22):
  **ed4b5c59b542ee96c227ee874776c973980c640b** (lastModified
  2026-10-19, the v1.1). This is the adapter pin.
- cerno-4b decider_config.json (from the Hub, raw):
  `{"temperature": 1.534, "temperature_fit": "held-out non-Index
  eval sets ... fitted 2026-10-18 for this checkpoint"}` — a single
  scalar temperature; NO per-type map, NO version field, NO
  isolated_levels / schema_first / neutralize_none overrides (so
  the package defaults apply: neutralize_none=True,
  isolated_levels=False, schema_first=False).
- Checkpoint format: compressed-tensors FP8 W8A8 as shipped
  (config.json quantization_config: float-quantized, weights 8-bit,
  dynamic token-wise activation quantization, lm_head ignored →
  bf16). Architecture Qwen3_5ForCausalLM (qwen3_5_text), 32 layers,
  hidden 2560. Serving the FP8 weights as shipped is the
  checkpoint's native format (gpt-oss MXFP4 precedent), not a
  dtype shift. GGUF repos are off-limits.
- Vendor inference: github.com/apertixsk/cerno-inference (cloned to
  ~/workspace/cerno-inference-ref). The Decision Index runs were
  produced by evals/decision_index/engine_vllm.py (vLLM, FP8,
  GPU). Protocol per that engine + README: one row per question
  (state-first layout, decider.prompt.build), one generated token,
  top-k logprobs over the option label tokens, renormalised,
  shipped temperature applied as p^(1/T) — mathematically
  softmax(logits/T) restricted to the label tokens.
- The vendored inference subset (third_party/decider, vendored
  from decider commit 1c15a48f199adc0eb1952b17441516b5358d79a0)
  implements the same protocol over HF transformers:
  Decider.system_one → render_state/render_question/plan_rows
  (isolated=False for this config) → prompt.build rows →
  slot logits over letter tokens → softmax(logits/T) → assemble/
  format_answer (probabilities rounded to 4 dp, choice confidence
  = raw top probability, score = probability-weighted level index
  on the 0..levels-1 scale, noul = P(yes)). Cerno's one local
  change (JOINT_FIRST_PIECE tokenisation) is vendor-measured to
  produce identical tokens to separate encoding; using the
  vendored copy itself makes the question moot.
- Answer-shape consequence: Cerno's choice `confidence` is the RAW
  probability of the chosen option (format_answer), which is
  exactly Jev's semantics — unlike Strands' rescaled confidence,
  no correction patch is needed on the LocalSystemOneAdapter
  inheritance. (To be re-verified against jev.py's parser and the
  shipped examples before the build lands.)

## Design (decided 2026-10-22)

- peira adapter: `CernoAdapter(LocalSystemOneAdapter)` in
  python/peira/adapters/cerno.py, mirroring strands_decider.py:
  entry point `cerno`, PINNED_MODEL apertixai/cerno-4b only,
  response stamp check (server must report model `cerno-4b` on
  every response; anything else or nothing is terminal).
- Serving: a local server on 127.0.0.1 exposing POST
  /v1/systemone, wrapping the VENDORED decider code (imported, not
  copied) + transformers on CPU. Rationale: the run env
  (.venv-local: torch 2.14.1, transformers 4.57.6) has no
  decider-ai / compressed-tensors / vllm; a separate server
  process keeps the shared driver env untouched while the Laya
  queue runs from it, and the server restarts independently of
  the driver (this box restarts often; driver partials resume).
  The server stamps each response with the checkpoint basename it
  actually loaded and serves exactly the pinned snapshot
  (snapshot_download at the pinned revision).
- The server script + its env live OUTSIDE the peira PR
  (~/workspace/peira-cerno-serve/), like the Strands/Von serve
  sidecars; the adapter's SETUP_HINT documents how to start it.

## Open recon items

- [ ] FP8 compressed-tensors load on CPU under transformers
      4.57.6: does it run, what RSS, what speed? (fidelity test)
- [ ] Fidelity: vendored Decider on CPU vs the published 4B
      example answers (examples/answers.json) — argmax agreement
      and probability deltas.
- [ ] jev.py parser semantics re-check (confidence / score /
      noul / usage fields the base expects).
- [ ] Pricing table: current version on main (was .4; Mercury
      may have landed .5) → take next free; add cerno-4b $0.0.
- [ ] Driver roster row shape for local models (post-merge step).

## Status log

- 22:50 EDT lane opened; recon above banked; worktree
  ~/workspace/peira-cerno on branch feat/cerno-adapter at
  origin/main 1bf0407b (Mercury #477 merge). Snapshot download of
  the pinned revision launched.
- ~23:14 EDT THIRD dispatch (second lane also died in a daemon
  restart; its recon above is complete and adopted). Download
  COMPLETED: snapshot verified at the pinned revision
  ed4b5c59b542ee96c227ee874776c973980c640b (model.safetensors
  4.84 GB FP8 blob; download exit 0 logged twice).
- Recon item 3 (jev.py parser) SETTLED by code read: the vendored
  format_answer shapes match JevAdapter exactly (choice carries
  confidence = raw top probability + probabilities map keyed by
  peira's labels; score carries the probability-weighted level
  index on 0..levels-1 plus a probabilities map keyed "0".."n-1";
  noul carries {"noul": P(yes)}, which _noul_output reads via its
  abstain->noul fallback). No confidence patch needed (confirms
  the second lane's reading). One gap the adapter must close:
  the vendored Decider stamps responses "decider-dev" (its
  decider_config.json carries no version field), so the SERVER
  stamps the checkpoint basename cerno-4b itself, per design.
- Pricing (item 4) SETTLED: main is at 2026-10-15.5 (Mercury);
  cerno-4b takes 2026-10-15.6 at $0.0 (self-hosted convention).
- Driver roster (item 5) SETTLED by code read: local-model row
  ("cerno-4b", "CernoAdapter", "apertixai/cerno-4b", None,
  "peira.adapters.cerno:CernoAdapter") + MODEL_CONFIG
  {"max_concurrency": 1}; build_adapter constructs local
  adapters with cls(), which the pin default satisfies. A
  call_timeout override is added only if canary latency demands
  it (CALL_TIMEOUT is 300 s).
- Server env: compressed-tensors is absent from .venv-local, so
  it (plus pydantic, loguru, psutil) is installed --target into
  ~/workspace/peira-cerno-serve/pylibs and put on the server
  process's PYTHONPATH only; the driver env stays untouched.
- MEMORY CONSTRAINT (new, measured): the box has 7,935 MB total,
  no swap. A bf16-dequantized 4B (~8.1 GB) cannot fit at all, so
  the run is only viable if compressed-tensors keeps the FP8
  weights resident (~4.84 GB) with per-layer dequantization.
  The fidelity test runs with a self-watchdog that aborts the
  process if its RSS passes 6,200 MB, so a blowup cannot take
  the box (or the Laya/Mercury tenants) down.
- Fidelity/load test launched (fidelity_test.py in the serve
  dir): loads Decider(snapshot, cpu, use_graphs=False), runs
  examples/requests.json through system_one at
  max_state_tokens=16384 (the vLLM Index engine's value), and
  diffs against the published cerno-4b answers.
- ~00:20 EDT LOAD BLOCKER found and routed around (server env
  only): .venv-local's transformers 4.57.6 has no qwen3_5 module
  at all, and the package index jumps from 4.57.6 to 5.x.
  transformers 5.20.2 (plus huggingface_hub 2.2.0 and
  tokenizers 0.23.3) is installed into the serve dir's pylibs
  and registers qwen3_5_text; the driver env is untouched. The
  vendor's requirements bound (>=4.57,<5) predates this.
- FP8 ON CPU (recon item 1, measured): transformers 5.20.2 +
  compressed-tensors loads the checkpoint FP8-RESIDENT (plain
  nn.Linear modules, weight float8_e4m3fn + per-module
  weight_scale; embeddings/lm_head bf16 tied). A raw forward
  fails (bf16 activations vs FP8 weights; torch._scaled_mm is
  CUDA-only). The server therefore wraps each FP8 linear's
  forward to dequantize (weight x scale) to bf16 transiently —
  248 linears wrapped, vendored code untouched — the standard
  dequantized execution for FP8 checkpoints on CPU. Load 39-50s;
  RSS stays mmap-backed (~0.6-1.1 GB observed under memory
  pressure; full residency ~4.9 GB as pages touch).
- ADAPTER DEFECT found by reading the vendor's published
  answers (owner-flagged pattern): the vendor's two formatters
  differ — the vendored format code emits `confidence`, but
  the published example answers and the submitted-run
  references (sample/reference-4b.jsonl) OMIT it on choice and
  score answers, because it duplicates the chosen option's
  probability. The adapter's first draft REQUIRED confidence,
  which would reject the vendor's own format while measuring
  nothing extra. Fixed before first commit: confidence is
  optional, validated as a finite probability when present
  (the parser records a present value unchecked otherwise).
  The probabilities map stays required (its absence makes the
  inherited parser fabricate 0.5). FLAG FOR THE OWNER: any
  other adapter that requires fields the vendor format makes
  optional has the same latent hard-stop; the seated Mercury
  run should be checked for the same over-strictness.
- FIDELITY (item 2, SETTLED): both vendor example requests
  reproduce on the CPU stack — 8/8 answers agree (choice
  argmax, score within 0.5 levels, noul within 0.05), worst
  probability delta 0.0251 (bf16 dequantized CPU execution vs
  the vendor's FP8 vLLM numbers; deltas above rounding, argmax
  intact). The serving stack measures the pinned checkpoint
  faithfully.
- LATENCY (item 1 speed half, SETTLED with numbers): dataset
  prompts run 225 chars (p10) / 476 (p50) / 1,215 (p90). On
  the contended box (load 13-18, 2 vCPU) a p10 choice call
  took 318s wall and a p10 score call 616s wall; pure CPU
  accounting is ~60+ CPU-seconds per p10 call, so the cost is
  compute, not contention alone (the transformers reference
  implementation of the gated delta rule is the bottleneck;
  the fused kernel is GPU-only). Full-run volume is 9,402
  calls; even a dedicated box projects to roughly 80-200
  hours. VERDICT: the full run cannot seal inside the freeze
  window on this VM, by two orders of magnitude. The adapter,
  server, and driver canary (the end-to-end proof) proceed;
  the run itself is the owner's call with these numbers
  (dedicated-host or GPU routes measure the same checkpoint
  through the same adapter contract).
- BUILD STATE ~01:35 EDT: adapter + tests + docs + pricing
  committed (8fe2ffe9, reworked onto the current
  LocalSystemOneAdapter contract in 4a42ba65 after the first
  draft targeted a stale base signature — the base resolves
  pins from class attributes and takes timeout_s; focused
  tests 35/35 pass), timeout raised to 1200s (6269a6c6).
  Entry point, pricing load, and driver-path construction
  verified first-hand. Full gates running; three checkpoint
  reviews (red team, Spec, Standards) running in parallel.
- GATES on 6269a6c6: no-Rust 4,368 passed EXIT=0; Rust-active
  4,406 passed, 9 failed = exactly the documented baseline
  (8x test_backend_under_test + concurrency replay);
  check_public_surface OK.
- REVIEWS (all three FAIL on the first pass, findings fixed in
  1065f34f after a rebase onto main 68f7c799, PRs #481/#482;
  survival check passed — lane files byte-identical across the
  rebase except the CHANGELOG merge and upstream Clef doc
  hunks): RED TEAM found 2 P1s, both reproduced live. (1) A
  score call under the vendor's published format recorded the
  parser's fabricated 0.5 confidence — jev's score mapping
  reads the decision answer's confidence with a 0.5 default
  and never consults its probabilities map; fixed with the
  Strands-pattern normalization (_with_probability_confidence
  in _choice_output/_score_output). (2) The parser prefers an
  'abstain' key over 'noul' and clamps it, and the validator
  never checked that key ({"noul":0.2,"abstain":1.7} sealed as
  abstain/1.0); both keys now validated. P2s: distributions
  never sum-checked (now |sum-1| <= 0.01 on choice and score
  maps); PINNED_REVISION was dead code (now a required
  response stamp, checked next to the model stamp; the
  sidecar emits it); six Troubleshooting strings missing (all
  added, plus the new strings' entries). SPEC axis: the
  missing score probabilities map was a second unapproved
  exception — the map is now required on score answers too;
  capability table is in the PR body; the trial exercise is
  the post-merge driver canary per the mission order (the
  Mercury precedent); the 1200s timeout is flagged in the PR
  body for owner ratification. STANDARDS axis: F1 docs (same
  fix), F2 dead constant (same fix), F3 helper factoring
  (done: one map validator + finite-number guard), F4 nits
  (SETUP_HINT lower-case fragment, constant docstrings,
  EXPECTED_MODEL_STAMP naming, timeout comment placement,
  blank line). P3-A (non-dict responses / malformed usage
  crash as bare exceptions in the inherited parser) is
  accepted as inherited Jev-family behavior, consistent with
  the sibling adapters; the real HTTP transport rejects
  non-object JSON before the wrappers. All red-team repros
  re-run first-hand against the fixed adapter: score
  confidence 0.6 not 0.5; abstain=1.7 terminal; sum-2.0 map
  terminal; missing revision terminal. Focused suite now 47
  tests, all passing; neighbors (strands/kev/jev/phase0) 198
  passing with them. Red-team re-audit of the fix diff and
  final-head gates (both modes + artifact smoke + public
  surface) running on 1065f34f.
- RE-AUDIT: PASS. Both P1s and all P2s verified closed with
  live repros; all 318 vendor answers (examples + submitted
  run references) pass the new validator, worst |sum-1|
  0.0005 against the 0.01 tolerance; the confidence patch
  provably does not mutate caller dicts or transcripts; no
  regressions (focused 47, inherited suites 99). Three P3
  follow-ups recorded, none blocking: (N1) the inherited
  base string "cerno returned a non-object JSON response" is
  described but not quoted verbatim in Troubleshooting (the
  Cerno-authored strings are all quoted); (N2) the score
  field is not cross-checked against its own level map
  (vendor data agrees within 0.0046, so an inconsistency
  would be detectable drift); (N3) choice-map keys are not
  validated against the offered labels (transport-level
  validation has no label context; the recorded confidence is
  still the genuine map entry). Follow-up lane material, in
  the perfection program's remit.
- FINAL-HEAD GATES on 1065f34f: no-Rust 4,392 passed, 50
  skipped, EXIT=0. Public surface EXIT=0. The chain's Rust
  leg died at session finish on a root-owned .pytest_cache
  (EPERM writing nodeids) and the smoke leg on a transient
  no-usable-tempdir fault; both re-running with
  -p no:cacheprovider and TMPDIR on workspace disk.
- MERGED: PR #484 squash-merged as ba51d05b (REST merge,
  no 404). Adapter verified importable from origin/main at
  the merge commit (model pin, endpoint, 1200 s timeout,
  cache namespace). GOAL.md synced: Recently merged entry at
  the head of the list; adapter inventory 37 to 38 with
  Cerno named. Driver wiring applied to the live driver
  (CERNO_TIMEOUT_S 1200.0, roster row cerno-4b, build_adapter
  branch, MODEL_CONFIG concurrency 1; cerno-4b NOT in
  ABSTAIN_ONLY_KEYS). The driver binds peira to
  peira-trial-code via a WORKTREE constant at its head, so
  the run uses a lane copy (trial_driver_cerno.py, one-line
  WORKTREE diff to the peira-cerno-run worktree at the merge
  commit) on the Mercury driver-copy precedent;
  peira-trial-code untouched.
- CANARY ATTEMPT 4 (06:58 EDT launch, after the third
  restart): sidecar re-verified healthy, canary relaunched
  per the owner's second restart notice. Case 1 completed
  clean again (heartbeat 1/10 ok=1, zero errors, 642 s;
  calls 259.00 s and 382.57 s). Case 2's first arm then
  slowed into another box-wide RAM crunch (available RAM
  ~0.8 GB, server main thread in D state on page faults,
  the same signature as attempt 2). Attempt 4 left running
  detached at this report; if it seals, the artifact lands
  at ~/workspace/peira-trial/artifacts/ as the v2-canary
  cerno-4b run and the transcript at
  ~/workspace/peira-trial/transcripts/cerno-4b.canary.jsonl
  already carries the completed cases' wire records. The
  stack is proven end to end through the real driver
  (roster, build_adapter, run_suite, adapter validation,
  sidecar, vendored Decider): every completed call measured
  cleanly with zero adapter rejections. What blocks the
  canary seal is box weather (three VM restarts today plus
  recurring RAM crunches from co-tenants), not the lane's
  code.
- CANARY ATTEMPT 3 (06:43 EDT launch): case 1 of 10
  completed clean (both arms ok, zero errors, 411 s for the
  case; server-side calls 223.75 s and 186.36 s, RSS peak
  1.18 GB) before the THIRD VM restart of the day
  (~10:51 UTC) killed driver and sidecar again. Transcript
  holds 6 lines for the completed case; no partial file is
  written in canary mode. ATTEMPT 4 relaunched 06:58 EDT
  after the sidecar was re-verified healthy (/health 200,
  pinned revision stamp). Observed pace for the owner:
  ~205 s per call and ~411 s per case on the shared box,
  so an uninterrupted canary is ~70 minutes and the full
  9,402-call run projects to ~500+ hours here (the
  dedicated-box projection from recon is 80-200 hours);
  the full run cannot seal inside the freeze on either
  number and remains the owner's call.
- CANARY RELAUNCHED 06:43 EDT (owner restart notice: the
  09:52 UTC restart was the day's second; the sidecar was
  found listening and answered /health 200 after a brief
  settling-window stretch of refused/empty replies, the
  documented post-restart hazard). The relaunched canary
  (trial_driver_cerno.py --canary --models cerno-4b
  --skip-inspection-gate, log at
  ~/workspace/peira-trial/logs/cerno-canary-2026-10-23.log)
  built the adapter and applied the 1-concurrency / 1200 s
  overrides cleanly; first call in flight at the relaunch.
  Available RAM at relaunch ~4.2 GB (the earlier crunch had
  eased); load still ~20.
- CANARY: first attempt (05:11 EDT) died with the VM restart
  mid-first-call, no partial written. Second attempt
  (05:58 EDT) stalled in the post-restart relaunch storm:
  the box showed load 18-19 and only ~0.9 GB available RAM;
  the server's main thread sat in D state on page faults
  (majflt ~9.5k) with the weight working set unable to stay
  resident while every tenant relaunched. Both processes
  killed by this lane at ~06:21 EDT to retry into calmer
  conditions; no case completed, no partial, no error
  records: nothing contaminated, the retry starts clean.
- GATES COMPLETE on the rebased head's byte-identical code:
  Rust-active re-run 9 failed (exactly the documented
  baseline: 8x test_backend_under_test + concurrency replay),
  4,430 passed, 3 skipped. CodeRabbit: no actionable
  comments. Artifact smoke needed two lane-venv repairs
  (maturin 1.15's puccinialin dependency missing from the
  venv; the maturin binary not on PATH for the build hook);
  with both fixed the smoke runs its full course (result
  appended below when it lands).
- SECOND REBASE (main moved again): #483 (announcement
  finalization, docs only) landed as 03084eb1 while the gates
  ran. Rebased onto it (head 9ccc651e); CHANGELOG conflict
  resolved with the Cerno entry on top and the announcement,
  README, and Clef entries intact below. Survival check:
  the diff vs the pre-rebase head is exactly #483's own two
  files; all eight lane files byte-identical; focused suite
  on the rebased head 116 passed. A box-wide transient EPERM
  window (~08:00 UTC, writes from git/python/shell helpers
  intermittently refused, then self-cleared) delayed the
  rebase by minutes; no data lost.
- PUSHED + PR OPEN: branch feat/cerno-adapter created via
  the Data API with --parent 03084eb1 and the complete
  8-file list; pushed tree 07dfad8a equals the local rebased
  tree; commit e7f8755e carries the Signed-off-by trailer.
  PR #484 https://github.com/david-engelmann/peira/pull/484
  with the capability table, known deviations, and the
  timeout ratification flag in the body. CodeRabbit review
  triggered manually (repo under 10 stars): completed with
  NO actionable comments (zero findings). CI on the PR head:
  public-surface, build, quickstart (all three OSes) green;
  toolchain-pins and lint-workflows red, but both fail
  identically on unrelated PR #479 and live entirely in
  .github/Dockerfile/ci.yml config this PR does not touch:
  pre-existing repo state, not this PR's reasons.
