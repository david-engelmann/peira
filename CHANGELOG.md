# Changelog

All notable changes to this project will be documented here. The format is
based on Keep a Changelog, and the project adheres to Semantic Versioning
(the package and the dataset are versioned independently - see
`docs/Compatibility.md`).

## [Unreleased]

### Provider-error records no longer count as completed work

- A call record carrying a provider/transport `error_code`
  (`rate_limit`, `api_error`, `timeout`) and an empty
  `completion_hash` shares the blank-record shape of a malformed
  model output, but the model produced no completion. The runner
  now discriminates on that pair of fields, over every record a
  result carries (conversational turn records included).
  `validate_partial` validates such results but does not return
  them as done, so `--resume` re-attempts exactly those cases,
  and a run whose stored results contain one seals with
  `termination: "partial"` instead of `"complete"` (refreshing
  its on-disk partial so the resumable record is current). On
  resume, transcript entries for re-attempted cases are replaced
  by the fresh calls, and replay derives its termination from
  the rebuilt records the same way. Genuine malformed output
  (`parse_failure`, `refused_to_format`,
  `token_limit_exceeded`) is unchanged. It still counts as
  completed work and scores under the frozen adjudication
  policy. Regression coverage in
  `tests/test_runner_provider_errors.py`.

### Board claims derived from the payload, not written into the source

- The share image generators (`gen-og.mjs`,
  `gen-social-preview.mjs`) compute their headline and corner
  claims from the payload on every build and fail the build
  when the payload does not support them. The priciest ranked
  run is asserted to be the most flipped ranked run before
  the headline prints. The bottom corner states the payload's
  actual toughness extreme. The social preview card draws the
  cheapest and priciest costed runs of the ranked full suite
  population, picked by cost rather than by name. Both
  generators also stamp dataset and suite versions only when
  every payload row agrees on them.
- The shared attack success axis ceiling is derived from the
  ranked population (the smallest tenth at or above the worst
  ranked rate, floored at the standing 0 to 30 percent scale)
  in `lib/chart.ts` and in both generators, where it was a
  literal in three places. The generator ports follow the
  board rule exactly, so the share images draw the axis the
  board draws.
- Leaderboard rows carry a `rerun` record built from the
  standing artifact's own metadata (its `parent_run_id`
  chain, which chains re-runs and resumes alike, and its
  creation day), null when the run chains to nothing or its
  creation day is not recorded. The record ships as emitted
  provenance that no board surface consumes yet, and its
  removal is scheduled as a follow-up. The standing Method paragraph
  that named two runs and a date as source literals is gone,
  and the footer's "What changed" note, which no payload
  data could derive, is removed.

### Share image label placement degrades instead of failing the build

- The `gen-og.mjs` label placer aborted the whole build when
  a small payload change crowded a label off every seat (a
  point moving on the cost axis, a cost domain rescale).
  Placement now degrades in tiers derived from the same disc
  geometry, a widened candidate list, then the widened list
  at a smaller size, then a words tier that lifts the
  unseated label off the plot and names its point in a strip
  under the chart with the attack success and cost the
  payload carries for it. A payload that breaks a claim
  still fails the build. A crowded layout no longer does.

### Restart-surviving seal checkpointing (opt-in)

- `peira.metrics.summarize` accepts `checkpoint_dir` and
  `peira.runner.run_suite` accepts `seal_checkpoint_dir`: the
  seal bootstrap checkpoints its replicate loops into a JSON
  sidecar, so a process death mid-seal (VM restart, OOM kill)
  resumes instead of restarting the computation. The runner
  also freezes the finished artifact as a pre-seal snapshot in
  the same directory, so a resumed seal summarizes
  byte-identical results and never re-runs a case.
- Checkpointing is arithmetic-neutral: chunk boundaries only
  insert save/restore of the exact PRNG state between
  replicates of the original loops, and the checkpointed
  summary is bit-identical to the monolithic one
  (`tests/test_seal_checkpointing.py`). The sidecar is bound
  by a fingerprint to one input set and code version; a
  mismatch recomputes. `PEIRA_SEAL_MONOLITHIC=1` forces the
  monolithic path. Default behaviour is unchanged: no
  directory, no files, no checkpointing.

### Board scatter and heatmap: flagged figures carry their decomposition

- On the cost scatter, a flagged point's attack success
  figure now travels with its malformed decomposition
  wherever it prints. The point title and the accessible
  name state the genuine flip rate and the malformed share
  of the counted flips beside the figure, the detail card
  carries the two as rows of their own under a flagged
  standing row, and the entry rows in the overflow stack
  and the phone list state the standing and the cost with
  no figure. Where the sealed family records do not derive
  a decomposition, the title, the name and the card state
  the standing and no figure at all.
- On the attack family heatmap, every flagged cell title
  now states its family's genuine flip rate and the
  malformed share of its counted flips beside the family's
  figure, the flagged group header points at the notes
  under the grid, and the notes state each flagged
  result's whole-row decomposition. A flagged family
  whose records do not derive a decomposition prints no
  figure. Its cell stands suppressed on the not measured
  mark, and its title states that the figure is not
  stated and why.
- The decompositions derive from the sealed per-family
  records in the payload data layer, under the same rules
  the model pages' derivation already states. The
  integrity check gains a thirteenth check pinning the
  scatter titles, names and entries, and the heatmap
  titles, suppressed cells and notes, against the
  payload.

### Board malformed, compare, and model cards: design perfection cycle 6

- The malformed section's axis now follows the data. While the
  worst printed rate fits the historical 0 to 15 percent scale
  the axis is that scale; past it, the axis extends to the
  smallest 10 percent step at or above the worst rate, so a
  bar's fill always matches the axis it is read on. Every row
  carries its maker's vendor mark beside its name.
- Compare marks a flagged result everywhere it names it: a
  flagged suffix in both pickers, the flagged pill in its
  side's table header, its malformed rate in amber, its
  family-bar letter in amber, and a caption stating it is not
  ranked. At phone widths the table head restacks so no model
  name wraps mid-token, and the table fits its section in
  every pairing.
- Model cards state the base of the attack success figure,
  counted on eligible cases only, where a wrong answer, an
  abstention, or malformed output counts as attack success.
  The card provenance no longer prints the manifest hash in
  any form, and a family a run did not measure prints an
  empty track and a dash instead of a speck.
- Each maker's mark is defined once per page and referenced
  by every chip, which brings the board's initial transfer
  back under its 500 KB budget at 436.3 KB.

### Board Method and chrome: design perfection cycle 7

- A flagged result's own page now leads its head description
  with its flagged standing. Where most of its counted flips
  were malformed output rather than changed decisions, the
  head states the decomposition and the genuine flip rate
  beside the headline figure, and the same sentence stands
  on the page itself. Where no such majority can be derived
  from the sealed family records, the head carries no attack
  success figure at all.
- The footer no longer prints the dateline a third time in a
  colophon line. The date stands in the masthead stamp and
  the footer citation only.
- The Method section corrects what it claims. The intervals
  sentence is scoped to the headline rates in the ranking
  and on the model cards, the admission section states how
  slice runs are judged, the tax sentence names every input
  a recompute needs, and the re-run paragraph names the two
  results as the board prints them. Each Method subsection
  now carries its own anchor.
- The section bar behaves on touch. Activating a link by
  pointer no longer leaves the bar holding focus, a landing
  after a tap is guarded so the bar does not hide over the
  section just jumped to, and at phone widths an overflow
  cue stands at the strip's right edge and clears when the
  strip reaches its end. The nav links take the board's
  15.5 px prose step.
- The board's dataset and suite stamps now come from an
  agreement check over every row. A payload whose rows
  disagree fails the build, naming the disagreement, instead
  of stamping one row's versions as the board's. The
  integrity check pins the Method anchors, the flagged and
  slice head descriptions, and the two chrome rules in the
  built CSS.

### Board share image: honest alt text, the rail keeps its meaning, the amber ring decoded

- The og image's alt text described the ranking and claimed
  95 percent intervals the image does not contain. It now
  describes the image that exists: the cost scatter, every
  full-suite model named, the headline finding.
- The label placement pass treated the rail column as open
  space and seated a plotted point's label there, where it
  read as a sixth no-cost rail entry. The rail column is now
  reserved furniture; the label sits beside its own disc.
- The credit line now decodes the amber ring inside the
  image ("Amber ring: a flagged result"), since the image
  travels without the board's prose, and the sub line
  states the population it shows (the full-suite results)
  and the cost axis's log scale.
- Two results whose discs fell inside a single disc's span
  rendered as one disc (the board's two best results, 4.7px
  apart). Merged discs are now separated along y under the
  board's shift cap before labels seat, so the image shows
  every result it names.
- The gridlines no longer run behind the rail column. The
  rail is a list, as on the board; its discs are spaced for
  legibility at a pitch that leaves visible air between
  their outlines, and a gridline behind them claimed an
  axis position the spacing had moved them off.

### Board scatter: the wide chart fits its band, the card moves as one object

- Between the phone breakpoint and the page cap the wide
  scatter now re-solves its geometry at true CSS pixels
  instead of scaling down, so every label and figure stays
  at or above the 10 px floor at tablet widths; the DOM
  audit gates 900 px for all sections, which also refit
  the band heatmap's columns to their headers.
- The detail card's visible shell (background, border,
  shadow, padding) now sits on its motion layer, so on a
  point switch the whole card glides to the new point and
  on dismissal the shell fades with its contents instead
  of standing empty until unmount.

### Board on phones: the scatter rebuilt for touch, the bar steps aside

- The cost scatter's detail card is now one state machine
  for every pointer. A tap or click pins a point's card
  open; the pinned card carries a close control, tapping
  the point again or tapping anywhere else in the chart
  dismisses it, and Escape dismisses it too. Hover and
  keyboard focus still preview. Tap targets are touch-sized
  (a 46 px hit circle at phone scale) over the same drawn
  discs, and a tap resolves to the nearest point, so the
  packed low-cost cluster opens the point the finger
  actually landed on.
- The phone scatter changes shape instead of shrinking:
  drawn at true CSS pixels for a 390 px phone, its plot
  takes the well's full width at more than double the old
  height, carries no rail column (the rail points stand in
  the list under the plot, each beside its own disc), and
  sets every label at the wide chart's size. Names that
  cannot sit beside their point sit in that list, as
  before. Several labels that rested on discs and names
  that rendered under the 10 px floor are fixed by the
  shape, not by smaller type.
- At phone widths the section bar translates out of view
  while the reader scrolls down and returns on scroll up,
  so its band never sits on the top of a chart the reader
  has scrolled to; the scrollspy also keeps the active
  link inside the bar's scrolling strip.
- Fixed the scatter's active point throwing its disc to
  the chart's origin, scaled, whenever it was hovered,
  focused or pinned: the CSS grow replaced the mark's
  transform attribute outright. The translate and the
  grow now nest, and the disc grows around its own centre
  where it was plotted, at every width.
- The rail caption under the scatter now says where the
  rail stands on a phone (it joins the list under the
  plot, in attack success order), not only where it stands
  on the wide chart.
- The DOM audit gains disc-clearance and corner
  containment checks on the scatter, entry-form rail
  coverage, and a phone interaction block at 390x844 that
  taps through the card contract and the nav landing, each
  proven against the build before this change, where they
  fail.
### Main CI repair: pricing pins, replay error_code, test env leak

- The pinned pricing table's header carried duplicate `basis`, `date`,
  and `pricing_version` keys left by the 2026-10-23 API version
  refresh: the refresh's changelog sentence had been written into the
  first `pricing_version` value instead of `_comment`, where it now
  lives. The parsed table is unchanged (version 2026-10-23.1, date
  2026-10-23, all 80 model entries identical); the Phase 0 pricing
  pins assert the current version.
- Replay under the Rust backend dropped each error entry's recorded
  `error_code` (for example "api_error", "timeout") from the rebuilt
  record, so a replayed artifact differed from the Python reference
  and from the sealed original. The replay dispatcher now recovers
  `error_code` from the transcript entry with the other v3 sidecars,
  and the blank-record dispatcher overlays the "timeout" stamp the
  reference sets on timed-out records (the item-timeout path relies
  on it). Regression tests pin both behaviors against the reference.
- `tests/test_run_safety.py` set `PEIRA_NO_RUST=1` in the worker
  process at import time, which leaked into every later test in the
  same xdist worker and failed the Rust-parity backend assertions
  non-deterministically by scheduling order. The suite no longer
  mutates the process environment; the run-safety tests run under
  whichever backend the suite runs, so both CI legs cover them.

### Board families heatmap and calibration: design perfection cycle 5

- The families heatmap now fits its section at desktop widths. The
  grid's 1160 px minimum width ran 28 px past the section and cut
  the last family's header mid-word with no scroll cue on screen;
  the floor is gone, and the cryptographic family's short header
  reads "Crypto" (its full name stays in every cell's title). On
  phones the matrix restacks into a list: each result's cells wrap
  under its name as chips labeled with their family, so all eleven
  families stay present and named with nothing off canvas and no
  sideways scrolling.
- A family a result never faced now prints the mark "--" at full
  ink strength on its ground tone cell instead of a faint middot,
  and the legend and the slice group caption name the mark in
  quotes. The heatmap lede names its three groups with their
  counts, so a phone reader knows the flagged results and the
  slices stand further down the list. Between the phone restack
  and the desktop fit (761 to 953 px) the grid scrolls with its
  sticky name column and shows the scroll cue in that band only.
- Calibration panels no longer carry the bins-coincide note on the
  two panels it applied to; the section lede states the fact once,
  naming the two results and the payload rule behind it, so every
  panel carries the same apparatus. Axis tick numerals render at
  10 px or more at every audited width (17 viewBox units on
  desktop, 9 in the capped one-column phone panel) in a lighter
  ink, and the last panel of the second-to-last desktop row no
  longer shows x ticks that belong to the last row alone.
- On phones the calibration index returns to one result per row
  with its bar (the wrapped-paragraph packing is gone) and the
  reliability panels run one across carrying both axes, so names
  no longer break mid-word, the ECE and Brier figures stay on one
  line, and every panel keeps its whole key.
- `scripts/audit-dom.mjs` gains the checks that pin these repairs
  (H-01 heatmap containment, H-02 lede group counts, C-01 tick
  size, C-02 rail lines, C-04 name breaks, C-05 rail containment,
  C-06 tick boxes, C-08 axis edge panels, and C-07 restated for
  the lede), each verified failing on the pre-fix build.

### GitHub face: social preview, one description, README first screen

- Added `.github/social-preview.png` (1280 by 640), the repo's social
  preview image, generated from the live board payload by
  `site/board/scripts/gen-social-preview.mjs`. The image draws the
  two ends of the board's cost story at large size on the board's
  own scales, jev-1.14.0 at $0.20 per run and claude-fable-5-1 at
  $130.31 per run, each with its maker's mark and its figures. It
  replaces a first design that drew the full cost scatter, whose
  names collapsed into illegible texture at feed sizes; the owner
  picked the two-extremes design on 2026-10-26. Applying the image
  to the repo is a Settings step (Social preview).
- One canonical project description now stands in the repo description,
  the README's first line, `pyproject.toml`, and `docs/Overview.md`.
- The README's first screen carries the board visual and the headline
  finding with its definition; board counts are stated once, the
  adapter inventory points at `docs/Adapters.md` instead of repeating
  its status table, and repeated board links in the first screen are
  removed.

### Internal work documents removed from the public docs tree

- Removed 11 internal work documents from `docs/`: a lane work queue,
  a draft cut-criteria memo, the audit disposition records, checkpoint
  evidence adjudications, a data-capture gap matrix, two dated internal
  reviews, the announcement package, and the board publishing runbook.
  The audit-dispositions generator script and its CI drift check are
  removed with them. The public docs tree now carries reader-facing
  documentation only; the removed files are preserved in the project
  records.

### Board hero and ranking: design perfection cycle 2

- The board's hero finding now runs the full content width
  instead of a narrow capped column, and the counts line and
  links share one meta row under a hairline. No wording
  changed.
- Ranking rows re-flow at phone widths into a single column
  inside the section box: the name takes its own full-width
  line when it cannot sit beside its vendor mark, the value
  sits on its own line with its interval, and nothing is
  clipped at either edge. Tie brackets keep their word at
  phone widths, turned vertical in the rail; the interval
  strip gains a track; the guardrail slices' axis title now
  states the abstain subset. The DOM audit gains a containment
  check (F-08) pinning this at the audited widths
  (1440, 1280 and 390).
- Each ranking row's sub-line no longer repeats the headline
  rate; it carries the interval and the malformed rate only.

### Cursor harness adapter measures grok-4.7-high-fast through Cursor's agent

- `CursorHarnessAdapter` (`cursor-harness`) measures a model
  through Cursor's agent CLI (headless print mode, `--mode ask`),
  with the account's Cursor User API key passed to the subprocess
  only through its environment. It is a harness measurement, not a
  bare-wire one, and is labeled as such everywhere. The pinned
  model id is Cursor's variant label `grok-4.7-high-fast`, never
  xAI's `grok-4.7`. Sampling is declared provider-incapable
  because the harness exposes no temperature or seed. Per-call
  token usage is recorded from the CLI envelope. Verified live
  2026-10-24 on CLI 2026.10.22-27dcf5f. A probe call returned its
  JSON envelope with usage in 7.3 s. Pricing is $0.0 by the
  self-hosted convention. The run draws on Cursor plan included
  usage.

### Mercury chat models gain a direct Inception wire, effort pinned

- `MercuryAdapter` (`mercury-structured`) measures Inception's
  Mercury chat models through Inception's own OpenAI-compatible API
  at `https://api.inceptionlabs.ai/v1` with the existing
  `INCEPTION_API_KEY`, reusing the structured-output request shape.
  Default pin `mercury-3` (api_pins `mercury-structured`), priced
  $0.10/$0.35 per 1M in `pricing.json` under the direct id
  `mercury-3`. Mercury 3 was first measured through the OpenRouter
  gateway; the direct wire was verified 2026-10-24 (live
  `/v1/models` listing plus a strict `json_schema` probe returning
  schema-valid JSON with the model id echoed). Gateway and direct
  runs are different wires and are never mixed in one artifact.
- `MercuryAdapter` sends `reasoning_effort` explicitly on every
  call (default `"medium"`, constructor-validated against
  low/medium/high). The wire defaults to low when the parameter
  is omitted and Inception's own benchmarks run at medium, so the
  pin is part of the instrument: it is recorded in the transcript
  request shape and in `decode_params`, and the effort is carried
  in the cache namespace so runs at different efforts never share
  entries. Verified live 2026-10-24 (medium 39 reasoning tokens,
  high 54, same prompt, both HTTP 200). The first direct full run
  was stopped at 1,500 cases when the omission was caught; its
  partial was discarded and the run restarted pinned.

### Score validation and transient follow-ups across the decision adapters

- The OpenRouter Decisions adapter's score fallback now
  validates its per-level probability map to the same contract
  as the Jev fallback it mirrors, reading each level by its
  canonical key instead of weighting values by their position
  in the map, so mass under a key naming no level can no longer
  fabricate a score and a huge-integer probability voids the
  fallback instead of escaping as an OverflowError.
- The OpenAI Decisions adapter now validates a score answer's
  per-level probabilities as a genuine distribution, the contract
  the System One and Mercury adapters already hold their
  probability maps to. Level indices are in range and named at
  most once, probabilities are genuine numbers in [0, 1], and
  the total is within 0.01 of 1. A partial, duplicated or inflated map is
  terminal instead of computing a weighted position that is not
  a measurement. Choice-answer probabilities carry the same
  per-value validation, since they feed the confidence fallback.
- Huge-integer wire values can no longer escape as an
  unclassified OverflowError on any adapter's direct paths.
  Every adapter's score, abstain and confidence conversions now
  bound or compare an int before converting it, and the clamp
  helper each adapter shares compares an int exactly before
  converting it, so a several-hundred-digit score, probability
  or confidence fails closed on the adapters whose paths raise,
  or clamps to the extreme in its own direction on the adapters
  whose paths clamp, instead of raising OverflowError. The
  Mercury adapter's transport latency reader treats the same
  class of junk as unknown latency rather than letting it
  escape.
- Jev passes a 408 or 409 response's Retry-After to the runner,
  and Mercury passes a 409's, like every other transient. Both
  statuses were already in the runner's transient set, so the
  server's stated wait was being dropped.
- Mercury's error-detail reader now treats a connection dropped
  mid-body (IncompleteRead) as no detail instead of letting the
  exception escape.

- The clamp helper every decision adapter shares now holds one
  strict contract across the family. A bool, a string or a
  non-finite value fails closed instead of being coerced or
  clamped into a fabricated measurement, and an int is compared
  exactly before conversion. The Jev, OpenAI Decisions and
  OpenRouter Decisions helpers previously clamped NaN to a
  maximal confidence, and the Decider, Laya and SemIf helpers
  shared the same hole plus the huge-integer escape. GLiNER
  Decide and Strands Decider carried the huge-integer escape on
  their own confidence paths, and a Strands probability outside
  [0, 1] previously passed through unclamped. All of these now
  fail closed or clamp by the same rules as the rest of the
  family.
- Cerno's probability predicates no longer convert their
  argument through math.isfinite before range-checking it. A
  several-hundred-digit integer probability or confidence
  raised OverflowError inside the predicate instead of failing
  closed as server drift. Ints are now compared exactly, as in
  every other adapter in the family.
- The local System One transport shared by Kev, Strands,
  Decider, Cerno, Von and OpenJev now passes a 408 or 409
  response's Retry-After to the runner, matching the Jev
  adapter. A non-finite Retry-After value now reads as no stated
  wait in every decision adapter instead of an infinite delay.

### Fleet pins and adapter landings for the full-run windows

- Cerno gains its two sibling pins: `Cerno9BAdapter` measures
  `apertixai/cerno-9b` at Hub revision
  80010f97eaa989b41c908ecba7d7b7fadaa99239 and `Cerno27BAdapter`
  measures `apertixai/cerno-27b` at Hub revision
  c2f7efe54fe4d3dfd7136bb2e9daf2c0c0633e3d, both resolved live
  from the Hub on 2026-10-23. The stamp check is parametrized
  over the pin; the 4B adapter's behavior and error text are
  unchanged. Pricing: both checkpoints added at $0.0
  (self-hosted convention), pricing version 2026-10-15.7.
- Five guardrail adapters land from the October sweep's
  pod-only code, at the same pins the sweep recorded:
  `Qwen3Guard8BAdapter` (`Qwen/Qwen3Guard-Gen-8B`, the 4B
  adapter's sibling subclass; the multi-token Controversial
  repair remains a separate change and will be inherited when
  it lands), `ShieldGemma9BAdapter` (`google/shieldgemma-9b`,
  the 2B adapter's sibling subclass, gated),
  `NemotronSafetyGuardAdapter`
  (`nvidia/llama-3.1-nemotron-safety-guard-8b-v3`, prompted
  with NVIDIA's published taxonomy template, verified
  byte-identical against the pinned checkpoint's
  `inference_script.py`), `LlamaGuard4Adapter`
  (`meta-llama/Llama-Guard-4-12B`, text path, gated), and
  `GptOssSafeguardAdapter` (`openai/gpt-oss-safeguard-20b`,
  bring-your-own-policy generative scoring over the harmony
  final channel). Nemotron and Llama Guard 4 are landed
  live-unverified against their weights; the gpt-oss adapter
  is probe-only at landing.
### Fixed score probability keys ignored by position in the Jev adapter

- The score fallback in the `jev` adapter, which derives a rubric
  position from per-level probabilities when the server omits the
  `score` field, weighted values by their position in the map and
  never read the keys, so mass under a key naming no level was
  scored as level-0 mass and mass under an out-of-range key in
  fifth position fabricated the maximum score; a
  several-hundred-digit integer probability escaped as an
  OverflowError. Keys must now be exactly the canonical level
  spellings `"0"` to `"4"` and the map must be a genuine
  distribution totalling 1 within rounding; anything else voids
  the fallback and the answer fails closed with the existing
  ProviderError, the same contract the `celeris`, `pplx-decider`
  and `clef` adapters already enforce. The `kev` and `strands`
  adapters inherit the fallback through the local System One
  adapter. A transcript audit of the published Jev runs found
  zero fallback engagements, so no published measurement is
  affected.

### The results board front end

- `site/board/` now holds the Next.js front end that has served
  peiratrial.dev since publish 27 (2026-10-23), landed with its
  gate scripts (the payload integrity check, the transfer budget
  check, and the DOM audit) and the share image generator. The
  app renders the pipeline payload in
  `site/board/data/payload.json` and formats its numbers
  without recomputing them. Publishing the board is a runbook
  task, written down in
  `docs/Board-Publishing.md`.

### Added Llama Guard 3 adapters

- New `llama-guard-3-1b` and `llama-guard-3-8b` adapters for Meta's
  Llama Guard 3 safety classifiers, pinned to
  `meta-llama/Llama-Guard-3-1B` at Hub revision
  acf7aafa60f0410f8f42b1fa35e077d705892029 and
  `meta-llama/Llama-Guard-3-8B` at Hub revision
  7327bd9f6efbbe6101dc6cc4736302b3cbb6e425. Both run prompt
  classification through the model's own chat template (the
  MLCommons taxonomy ships inside it) and score P(unsafe)
  renormalized over the first-token safe/unsafe label logprobs,
  the model card's classifier-score construction. Abstain
  primitive only, like the rest of the HF guardrail family. Both
  checkpoints are gated under the Llama 3.1 Community License.

### HF guardrail adapter repairs landed from the sweep pod

- Shieldstral now loads through `AutoModelForImageTextToText`: the
  pinned checkpoint ships a `Mistral3Config`, which
  `AutoModelForCausalLM` refuses on current transformers. The adapter
  also resolves its yes/no verdict tokens bare-first (`"yes"`/`"no"`,
  falling back to the spaced spellings): measured on the checkpoint,
  the bare tokens carry the verdict mass after the adapter's prompt
  while the spaced variants are effectively never emitted, so the
  old spaced-first order renormalized numerical noise.
- Qwen3Guard label resolution now falls back to a label's first
  token when the label is not a single token in the Qwen3 tokenizer
  (`Controversial`), instead of raising before it can score; Safe
  and Unsafe keep the exact single-token path, and a label the
  tokenizer cannot encode at all still fails closed. All three
  repairs were proven on the October 2026 sweep pod and produced the
  sealed Shieldstral and Qwen3Guard-Gen-4B slices; they now land on
  main with tests.

### API version refresh and the Perplexity default pin flip

- Added pinned support and pricing for the current API model versions: grok-4.7, deepseek-v4-pro, glm-5.3, MiniMax-M3.1-Flash, gemini-4-argon, pplx-decider-v1.2, pplx-decider-flash-v1.2, inception/mercury-3 (via the new openrouter-decisions adapter), inclusionai/ling-3.1-flash, microsoft/microsoft-decision-1, and gpt-5.6-sol. Each was proven with a 10-case canary before landing. Pricing table version 2026-10-23.1.
- The Perplexity adapter default pin flipped from pplx-decider-v1.1-27b to pplx-decider-v1.2. Perplexity silently re-pointed the v1.1 and v1 ids to v1.2 weights server-side, so the old default would have recorded v1.2 measurements under a v1.1 name. The older ids remain accepted pins for reproducibility of pre-re-pointing runs.

### Board facts refreshed to the freeze publish

- The README and the announcement package now state the freeze board with 39 entries covering 38 distinct models, 34 ranked models and 4 flagged models. The refresh adds Mercury Decide and Clef omni as published full-suite results, marks Llama Prompt Guard 2 as measured on the guardrail slice, records that the robustness tax frontier is unchanged, and adds adapter table rows for Mercury Decide and Cerno.

### Added Cerno adapter

- New `cerno` adapter for Apertix's Cerno System One decision
  models, pinned to `apertixai/cerno-4b` at Hub revision
  ed4b5c59b542ee96c227ee874776c973980c640b and served locally by
  a sidecar that wraps the vendored Apertix Decider (the vendor
  ships no server). The adapter reuses the local System One wire
  plumbing, checks the server's `cerno-4b` model stamp and Hub
  revision stamp on every call, and validates answers
  fail-closed: a probability that is missing, non-numeric,
  non-finite, or outside [0, 1], or a distribution that does
  not sum to 1 within rounding, is a terminal provider error,
  never a clamped or defaulted number. The `confidence` field
  is optional on the wire, matching the vendor's published
  answer format, because it duplicates the chosen option's
  probability; the adapter normalizes it from the probability
  map before parsing, so a recorded confidence is always a
  number the model produced. Pricing: `apertixai/cerno-4b`
  added at $0.0 (self-hosted convention), pricing version
  2026-10-15.6.

### Announcement package finalized around the published v2 board

- The announcement package records the verified v2 board as published at the time, with 36 entries covering 35 distinct models, states the ranked and flagged split, and defines the robustness tax against the full-suite frontier set by Jev 1.14.0 and Claude Sonnet 5-5. It replaces the October draft scaffolding and its placeholders with final repository and LinkedIn copy, and it states the refresh rule for the freeze publish landing on 23 October 2026.

### README finalized around the live leaderboard

- The README leads with the live board at peiratrial.dev (a badge,
  a link in the top link row, and a Live results section). The
  Leaderboard section describes the published v2 board and links
  the admission rules instead of describing official runs as in
  progress. The adapter table reports measured status against the
  published board and adds rows for the decision-model adapters
  measured since the table was last updated (Celeris, Clef, Decider,
  Strands Decider, pplx-decider). The Reports section names the
  live board as the standing report.
- The Adapters intro drops the stale adapter count, the Install
  section states the PyPI status as a plain fact instead of a
  pending release, and the Datasets section drops its
  forward-looking holdout sentence.

### Fixed score probability keys accepted by spelling in the Clef adapter

- Fix-forward for the entry below: the `clef` adapter carried the
  same score fallback pattern in a different spelling and was
  missed by that change. Its fallback summed `int(key) * float(p)`
  over the probability map, so non-canonical keys (`" 2"`, `"01"`,
  `"+1"`) were silently accepted as levels, duplicate spellings
  double-counted a level, string and boolean values were coerced
  into probabilities, and a weighted sum outside the rubric (a
  level-99 key computes 99) was clamped into an extreme score
  instead of failing. The fallback now applies
  the same strict contract as the Celeris and pplx-decider
  adapters: keys exactly `"0"` to `"4"`, genuine numbers in
  [0, 1], a total within rounding distance of 1, anything else
  fails closed with the existing ProviderError. The adapter also
  now passes a 409 response's `Retry-After` through to the runner,
  like the other transient statuses. A transcript audit of both
  published Clef runs found zero fallback engagements (all 1,412
  score answers in each run carried the server-reported score),
  so no published measurement is affected.

### Fixed score probability keys accepted by spelling in the Celeris and pplx-decider adapters

- The score fallback in the `celeris` and `pplx-decider` adapters,
  which derives a rubric position from per-level probabilities when
  the server omits the `score` field, parsed probability keys with
  `int()` instead of validating them. Spellings such as `" 2"`,
  `"01"` and `"+1"` were silently accepted as levels, and `"1"`
  alongside `"01"` double-counted one level while still summing to
  1, fabricating a score. Keys must now be exactly the canonical
  level spellings `"0"` to `"4"`. Anything else voids the fallback
  and the answer fails closed with the existing ProviderError. A
  transcript audit of the published pplx-decider run found zero
  fallback engagements (all 1,412 score answers carried the
  server-reported score), so no published measurement is affected.
- Both adapters now pass a 409 response's `Retry-After` through to
  the runner, like the other transient statuses. 409 was already in
  the runner's transient set. The parsed wait was previously
  dropped.

### Added Celeris adapter

- New `celeris` adapter for Celeris-1-decision, a diffusion decision
  model served on the System One wire at inference.celeris.ai. The
  adapter sends the Jev adapter's question text unchanged and pins
  the single served model id. A response whose model echo differs
  from the pin is refused, so a measurement never seals under the
  wrong model's name.
- Pricing gains a `celeris-1-decision` entry at $0.04 per 1M input
  tokens with output free. The rate is the vendor-stated price. The
  pricing table moves to version 2026-10-15.4.
- Live state at landing. The wire shape was verified against the
  live API on 2026-10-15 before the adapter was written. A probe
  carrying the adapter's exact question text returned HTTP 200 on a
  combined call and on each per-primitive call shape.

### Added Inception Mercury Decide adapter (Decisions API)

- New `MercuryDecideAdapter` (entry point `mercury-decide`) for
  Inception's Mercury Decide decision model on the hosted Decisions
  API, the model the account's models list serves on the decisions
  endpoint only. The adapter sends the Jev adapter's question text
  unchanged and reads the unenveloped response body (`answers`,
  `model`, `usage`), so the two wires are measured on identical
  decision spaces.
- One pinned model is supported. It is named by its full served id,
  with per-instance version and cache namespace following the pin.
  It is `mercury-decide`, the typed-decision preview model. The
  account's chat models and every other id are rejected at
  construction. The adapter also refuses a response whose echoed
  `model` differs from the pin, so a measurement can never seal
  under the wrong model's name.
- Pricing gains an entry for the model at $0.02 per 1M input tokens
  with output free, verified against the models list served by
  Inception's API on 2026-10-16. The pricing table moves to version
  2026-10-15.5.
- Live state at landing. The wire shape was verified against the
  live API on 2026-10-16, before the adapter was written, with a
  probe call carrying one question of each type. The probe returned
  HTTP 200 for `mercury-decide` with all three primitives answered.
  The abstain probability arrived under the `noul` key only. The
  adapter's first measured exercise is the standard driver canary.

### Added Strands Decider adapter

- New `strands-decider` adapter for Strands Decider 2B (AWS
  Strands Labs, Apache 2.0), served by `strands-decider serve`
  over the TypeSafe-compatible `/v1/systemone` wire. The adapter
  reuses the self-hosted wire plumbing shared with Kev, pins the
  `StrandsAgents/strands-decider-2B-hobson-v21` checkpoint, and
  corrects the one wire difference that matters (the server's
  rescaled choice confidence is replaced by the raw probability
  for the chosen option wherever the answer carries a probability
  distribution). Adapters.md records the CPU practicality measured
  in the adapter's canary.
### Added GLiNER2.5-Decide adapter

- New `gliner-decide` adapter for Fastino's GLiNER2.5-Decide
  (Apache 2.0), a 340M DeBERTa-v3 schema classifier that runs
  locally on CPU through the `gliner2` package. Peira's three
  primitives map onto caller-supplied label sets (choice options
  as a described label set, score levels as labels, abstain as a
  two-label yes/no set), documented in the adapter and in
  Adapters.md, with the winning label's model probability as the
  confidence. The checkpoint is pinned to
  `fastino/GLiNER2.5-Decide` at a fixed Hub revision.
- Pricing gains a `fastino/GLiNER2.5-Decide` entry at $0.0 per 1M
  tokens (self-hosted; local inference cost explicitly
  unaccounted). The pricing table moves to version 2026-10-15.2.
- Live state at landing. The live CPU canary passed on 2026-10-15
  through the real adapter (exit 0, peak resident set 2,770 MB;
  choice, score and abstain outputs all validating) after the
  first attempts on the shared trial VM were OOM-killed under
  contention, a host capacity state rather than an adapter
  defect.

### Added Perplexity pplx-decider adapter (Decisions API)

- New `PplxDeciderAdapter` (entry point `pplx-decider`) for
  Perplexity's pplx-decider decision model on the hosted Decisions
  API, the endpoint Perplexity positions directly against TypeSafe's
  Jev. The adapter sends the Jev adapter's question text unchanged
  and reads the unenveloped response body (`answers`, `model`,
  `usage`), so the two wires are measured on identical decision
  spaces.
- Two pinned models are supported. Each is named by its full served
  id, with per-instance version and cache namespace following the
  pin. The two are `pplx-decider-v1.1-27b` (the current version, the
  default) and `pplx-decider-v1-27b` (the launch version).
  Unversioned names and every other id are rejected at construction.
  The adapter also refuses a response whose echoed `model` differs
  from the pin, so a measurement can never seal under the wrong
  model's name.
- Pricing gains entries for both models at $0.02 per 1M input tokens
  with output free, verified against Perplexity's official Decisions
  API documentation on 2026-10-15. The live docs rate of $0.02
  supersedes the $0.04 figure carried in pre-launch secondary
  reporting. The pricing table moves to version 2026-10-15.3.
- Live state at landing. The wire shape was verified against the
  live API on 2026-10-15, before the adapter was written, with a
  probe call carrying the adapter's exact question text. The probe
  returned HTTP 200 for `pplx-decider-v1.1-27b` with all three
  primitives answered. The abstain probability arrived under the
  `noul` key only. The adapter's first measured exercise is the
  standard driver canary.

### Fixed slice-row presentation on the dashboard leaderboard

- The robustness tax frontier is now the full-suite cohort. The
  tax column previously computed its frontier over every ranked
  row, so a slice row (a run over a defined sub-population, for
  example the 373-case abstain slice the Hugging Face guardrail
  adapters speak) moved the best-observed anchors and rebased
  every full-suite tax on the board. The frontier now comes from
  the ranked rows that ran the most cases within the
  board's suite and dataset version, chosen by measurement
  population and never by model name. Slice rows print their own
  numbers and, on the full-suite board, carry no tax.
- Leaderboard rows now carry the served model's full display
  name. The guardrail adapters seal an adapter release tag as
  their version ("2.0", "125m"), which printed as the row's
  name. The display name is now the model the adapter serves,
  resolved from the adapter's declared model pin and printed
  only when the run artifact's pinned revision matches that
  declaration. ProtectAI rows now name
  protectai/deberta-v3-base-prompt-injection-v2 and Granite HAP
  rows name ibm-granite/granite-guardian-hap-125m.
- A canary (probe) run staged as an entry's only run no longer
  prints as an unranked result. Probe exclusion previously
  applied only when a probe shadowed a full run of the same
  entry. A run sealed under a canary suite marker is now omitted
  entirely, while a run that measured the benchmark still prints
  with its standing, however small or quality-failing it is.

### Added Cloudflare Clef adapter (Workers AI decision models)

- New `ClefAdapter` (entry point `clef`) for Cloudflare's Clef
  decision-model family on Workers AI, the drop-in System One
  compatible API Cloudflare launched on 2026-10-01 and benchmarked
  head-to-head against TypeSafe's Jev. The adapter sends the Jev
  adapter's question text unchanged and unwraps the Workers AI
  envelope (`result.answers`), so the two wires are measured on
  identical decision spaces.
- Three pinned models are supported. Each is named by its full
  Workers AI id, with per-instance version and cache namespace
  following the pin. The three are `@cf/cloudflare/clef-flash`
  (9B, the default), `@cf/cloudflare/clef` (27B) and
  `@cf/cloudflare/clef-omni` (30B-A3B). Short names and every other
  id are rejected at construction.
- Pricing gains entries for all three models at $0.038, $0.240 and
  $0.150 per 1M input tokens with output free, verified against
  Cloudflare's official Workers AI pricing page on 2026-10-15. The
  clef-flash rate is the 2026-10-09 price cut from $0.090. The
  pricing table moves to version 2026-10-15.1.
- Live state at landing. An access probe on 2026-10-15 with the
  account's existing Cloudflare token received HTTP 401 from the run
  endpoint (error code 10000) and HTTP 403 from the model search
  endpoint, while the same token verified active and listed zones.
  The token carries no Workers AI scope. The adapter is canary-ready
  and stays out of measured runs until a Workers AI scoped token is
  provisioned and the first canary passes.
### Added Von adapter

- New `von` adapter for Von (wfzyx, Apache 2.0), an open
  non-autoregressive System One decision model served by
  `von serve` over the TypeSafe-compatible `/v1/systemone` wire.
  The adapter reuses the self-hosted wire plumbing shared with Kev
  and pins the `von-1.3.0` snapshot id (the checkpoint `von serve`
  serves; Von 1.3, an engine release whose weights are unchanged
  from 1.2), with optional Bearer auth for servers started with
  `VON_API_KEY` set. The adapter checks the model stamp on every
  server response and refuses a response whose stamp names a
  different checkpoint than the pin, or that carries no stamp.
  The docs record the
  two serve settings a measurement depends on (the raw noul
  decision rule and refuse-on-overflow) because the adapter cannot
  see either of them.
### Added Decider adapter

- New `decider` adapter for Mapika's Decider 0.8B (Apache 2.0),
  the small arm of the Decider family of System One-style models,
  run in-process through the `decider-ai` package. The adapter
  sends Jev's question builders unchanged, reports the raw
  probability for the chosen option as the confidence (the
  answer's own confidence field is the rescaled TypeSafe figure),
  normalizes the score from its 0..levels-1 index scale, and
  never overrides the checkpoint's fitted per-type temperatures.
  The checkpoint is pinned to `Mapika/decider-0.8b` at a fixed Hub
  revision.

### Added Jev 1.14 snapshot support (jev-1.14.0)

- `JevAdapter` now accepts two pinned snapshots, `jev-1.13.0` and
  `jev-1.14.0`, with `jev-1.13.0` unchanged as the default. Floating
  tags such as `jev-latest` and `jev-preview` and every other model
  id are still rejected at construction, so a measurement always
  names the exact model that produced it.
- `version` and `cache_namespace` now follow the instance's pinned
  snapshot. A 1.14.0 run seals adapter version `jev-1.14.0` and
  caches under `jev:jev-1.14.0`, never colliding with a 1.13.0 run.
- Pricing gains a `jev-1.14.0` entry at $0.042 per 1M input tokens
  with output free, verified against the TypeSafe models page on
  2026-10-14. The pricing table moves to version 2026-10-14.2.
- An owner probe verified the 1.14.0 wire live on 2026-10-14 and
  received HTTP 200 with the response model field naming
  `jev-1.14.0`.

### Fixed Decisions adapter error strings carrying em dashes

- Two error messages from the OpenAI Decisions adapter used an
  em dash before their guidance clause, and Troubleshooting.md
  quotes error strings verbatim, so the public docs carried the
  dashes and failed the docs check. The 401 and 422 messages now
  join their guidance clause with a semicolon, the construction
  the Troubleshooting.md headings already print for the matching
  Jev messages, and the Decisions headings match the emitted
  strings word for word. The two API error strings and the
  adapter's other error messages, docstrings and comments no
  longer carry em dashes. The two question strings the adapter
  sends keep their exact original wording, dashes included,
  because they are the measurement text shared with the Jev
  wire. One is the score rubric label and the other is the
  abstain question, and changing either would change what the
  wire is asked.
### Fixed MODELS TESTED tile counting entries as models

- The leaderboard KPI tile printed the entry count under its
  MODELS TESTED label, and its ranked and flagged split counted
  entries too. An entry is one model measured over one wire, so
  a model measured over two wires counted twice and a 20 entry
  board of 19 models read as 20 models tested. The tile now
  counts distinct model IDs (adapter_version), classifying each
  model once. A model counts as ranked when any of its entries
  holds a rank, and flagged only when none does, so the split
  sums to the headline count. Card ranks stay per measurement
  over the ranked entries.
- The retrieval poisoning tile's carry note counted entries
  the same way, printing a carrier count over an entry count
  under a MODELS word. It now counts the distinct models that
  carry the family, over the field's distinct-model count.
- The lead band tile stated the size of the tied lead group
  as a count of entries under a MODELS word, so a band
  holding one model on two wires overstated the number of
  models tied at the top. The tile now counts the distinct
  models in the band. A tie of two entries still names both
  entries instead of counting, unchanged when the two
  entries are one model on two wires.

### Fixed leaderboard robustness tax collapsing models that share an adapter

- The dashboard tax column keyed its inputs by adapter name, so
  models sharing one adapter (every Anthropic model uses
  anthropic-structured and every OpenAI model uses
  openai-structured) collapsed into a single reading. The
  collapsed models printed the surviving model's tax, and their
  own readings dropped out of the frontier, which moved the tax
  printed for unrelated models. The column now keys by model
  identity, the pair of the run's adapter name and
  adapter_version, since neither field alone names a model.
  Each ranked model is taxed from its own benign accuracy and
  attacked ECE. The
  `peira tax` command keyed its inputs the same way and gets
  the same fix, so two runs from models sharing one adapter
  both stand in its analysis instead of the later one silently
  replacing the earlier.

### Added OpenAI Decisions adapter (openai-decisions, gpt-6-luna)

- New adapter `peira.adapters.openai_decisions:OpenAIDecisionsAdapter`
  (entry point `openai-decisions`) for OpenAI's Decisions API, a
  decision-model endpoint in the Jev family. The case prompt rides as
  the request `input` with named typed questions, and the wire's
  typed answers map onto all three primitives. Choice answers carry
  a per-option probability distribution plus a separate confidence
  field. Score arms batch a rubric score question and the paired
  decision question in one request, with the score normalized from
  the five-level rubric. The abstain primitive maps onto a predicate
  question whose probability is P(abstain). Any question can return
  a documented refusal answer, which maps to an abstained output.
- The question text (instructions, five-level rubric, label
  construction) is the Jev adapter's unchanged, so the two
  Jev-pattern wires see identical decision spaces.
- Model pinned to `gpt-6-luna`, the only model the endpoint
  supports. No pricing change. The wire reports zero output tokens
  and the existing `gpt-6-luna` table entry ($0.10 per 1M input)
  computes the cost exactly. Choice and score wire shapes were
  verified live on 2026-10-14 by the design lane's probe. The
  predicate and refusal shapes are documented in the API reference
  and are first exercised by the post-merge canary.

### Fixed Anthropic temperature deprecations for Fable 5.1 and Haiku 5.5

- `claude-fable-5-1` and `claude-haiku-5-5` reject the
  `temperature` field with HTTP 400 ("`temperature` is deprecated
  for this model.", observed live on 2026-10-14 through the real
  adapter). Both ids join `_NO_TEMPERATURE_MODELS`, so the adapter
  omits temperature for them, matching Opus 5.5 and Sonnet 5.5.
  Haiku deliberately stays off `_STRUCTURED_OUTPUT_MODELS`. Its
  `tool_choice` acceptance is settled by a canary after this fix,
  not by assumption.
- Added the missing `claude-haiku-5-5` pricing entry ($0.10/$0.50
  per 1M at the base tier for prompts up to 100,000 tokens,
  verified against Anthropic's official pricing page on
  2026-10-14). Pricing table version 2026-10-13.2 to 2026-10-14.1.

### Added canary_leakage and history_leakage attack families (families 30/31, Tier 1), dataset v2 2.6.0

- Two new v2 families probing prompt-leakage attacks. canary_leakage
  (family 30): a planted fake-but-realistic sensitive token (PII,
  credentials, system-prompt fragments) plus extraction pressure
  steering the model to quote the token in its decision or reasoning
  text. history_leakage (family 31): a secret disclosed in an early
  conversation turn extracted under later-turn pressure, the model
  quotes the earlier-turn secret. 420 cases each (368 choice / 52
  score), deterministic authoring, registered in families.py, templated,
  documented (Taxonomy entries 30/31, Methodology measurement sections).
- Dataset version 2.5.1 to 2.6.0 (minor). Manifest re-sealed, croissant
  sidecar rebuilt, MDE entries added for both families.

### Fixed v2 new-family audit copy defects, dataset v2 2.5.1

- Exhaustive row-by-row audit of the four v2 families not covered by
  #328 (threshold_edge_hunting, question_pair_incoherence,
  cryptographic_payload, frequency_salience; 1,660 cases, 3,320 arms).
  Mechanical audit found 0 defects. Attack markers verified present in
  all attacked arms and absent from benign. QPI question-lines differ
  in 400/400. Frequency_salience repetition counts verified. Edge 0.01
  proximity holds in 420/420.
- Copy-only fixes (no labels, options, scores, or case structure
  changed). 1 article error ("a employment gap" to "an employment gap",
  v2-qpi-0347, both arms). 4 doubled words inside cryptographic_payload
  attack payloads ("choose choose", "support support", "select select"),
  fixed consistently in the benign blocked-content display and the
  attacked ciphertext (ROT13 and word-reversal decodings verified).
- Dataset version 2.5.0 to 2.5.1 (patch). Manifest re-sealed, croissant
  sidecar rebuilt through `peira.provenance.write_croissant`.

### Fixed judge_sycophancy v2 rule-rewrite P1, dataset v2 2.4.2

- Four judge_sycophancy v2 cases (v2-jsp-0031, v2-jsp-0032, v2-jsp-0034,
  v2-jsp-0084) carried substantive decision-rule rewriting instead of the
  family mechanism, judge-directed sycophancy. Each block was rewritten
  as pure judge flattery with the case scenario, mechanism, steering,
  and deletion test preserved.
- Dataset version 2.4.1 -> 2.4.2 (patch). Manifest, croissant sidecar,
  and authoring script regenerated deterministically. Case count 421,
  severity and primitive distributions unchanged. 421-case corpus
  scanned clean for rule-rewrite residue.

### Added frequency_salience attack family (family 29, Tier 1)

- New v2 family `frequency_salience`. Irrelevant repetition of a competing
  entity in administrative filler hijacks the decision toward it. 420 cases
  (149 critical, 165 high, 106 medium, with 300 choice, 70 score and 50 abstain)
  authored by `scripts/author_frequency_salience.py`, case IDs `v2-freq-0001`
  and up. The attacked variant keeps the benign facts byte-identical and adds
  an administrative-notes block (calendar entries, directory listings, access
  logs) repeating the competing entity 1, 3, or 7 times. Filler length is held
  approximately constant across doses so only the mention count varies. The family ships a
  dose-response design (100 scenarios x 3 mention-count doses for the choice
  cases, plus 70 score and 50 abstain cases cycling the doses) measuring the
  salience curve toward the repeated entity. Registered in
  `python/peira/families.py`, documented in `docs/Taxonomy.md` (entry 29,
  boundary ruling vs verbosity_inflation, evidence_positioning, and
  distractor_flooding) and `docs/Methodology.md` (measurement section with the
  deletion test). Ships in dataset version 2.5.0.

### Changed - maturin replaces setuptools + hand-rolled Rust build script (D-43)

- The PEP 517 build backend is now `maturin` (`build-backend = "maturin"`,
  `[tool.maturin]` with `bindings = "pyo3"`, `module-name = "peira._core"`,
  `features = ["pyo3/abi3-py310"]`). `scripts/build_core_ext.py` is deleted;
  `pip install -e '.[dev]'` builds the extension (release profile in CI via
  `MATURIN_PEP517_ARGS=--release`), and `maturin develop` gives incremental
  debug rebuilds after Rust changes. Wheels are abi3 (one per platform);
  installing from an sdist or git URL now requires a Rust toolchain.
- CI installs the Rust toolchain in every job that pip-installs the package
  (the maturin backend builds the extension at install time). `test-python`
  now runs the suite with `PEIRA_NO_RUST=1`, keeping its pure-Python
  fallback coverage; `test-python-rust` covers the compiled backend.
- New `release-wheels.yml` workflow builds abi3 wheels (linux x86_64,
  macOS arm64, Windows x86_64) plus an sdist on `v*` tags and publishes to
  PyPI via trusted publishing (OIDC).

### Added R-04 effective sampling config and stability probe

- Every transcript entry now records `sampling_config`: the effective
  `temperature`, `seed`, and `max_tokens` actually sent on the wire
  plus a `sampling_source` flag from the closed vocabulary
  `adapter-declared` / `provider-incapable` / `unknown`. It rides the
  entry, the rebuilt `CallRecord`, and the sealed artifact, so replay
  preserves the original config.
- New `peira.sampling` module with the fail-closed gate: an adapter
  that declares `_supports_temperature` / `_supports_seed` but leaves
  the parameter unset raises `SamplingConfigError` before any case
  runs, instead of silently running on provider defaults.
  `_StructuredLLMBase` declares `_supports_temperature = True`.
- The response-cache key now folds the effective sampling config into
  the cache namespace (lm-eval-harness #3881 class): a run at
  temperature 0.7 never reuses entries recorded at temperature 0.0.
  Adapters with no sampling knobs produce an empty fragment, so their
  existing cache entries keep working (one-time post-upgrade cache
  miss for LLM adapters).
- New `peira.stability_probe` module and `peira stability-probe`
  command: ~100 cases x 3 trials over a fixed deterministic slice,
  per-case flip rates, attacked-arm pass^k (P(all k succeed)) with
  Wilson 95% CI as the headline, stability score next to accuracy,
  standalone report plus `borderline_cases.json` sidecar (flags,
  never quarantine). Determinism explicitly not claimed, even at
  temperature 0.

### Changed - uv replaces pip-compile for Python dependency locking (D-40)

- `uv.lock` at the repo root is now the single committed Python
  lockfile, generated by `uv lock` (D-40). The three pip-compile files
  (`requirements/base.lock`, `requirements/dev.lock`,
  `requirements/all.lock`) are deleted.
- `pip install peira` is unchanged. Package metadata stays PEP 621
  with the setuptools backend, and CI still installs with
  `pip install -e .[dev]`. uv manages the lockfile only.
- The Dockerfile projects `uv.lock` to a hash-pinned requirements
  file at build time (`uv export`, hashes included by default) and
  installs it with pip `--require-hashes`. The full-extras set,
  including torch, is hash-pinned for the first time. The
  `EXTRAS_LOCK` build arg is now `EXTRAS` (`dev` or `all`).
- CI runs `uv lock --check` so a stale lockfile fails the PR. See
  docs/Reproducibility.md for the new workflow.

### Fixed v2 draft copy defects from the exhaustive v2-draft audit, dataset v2 2.4.1

- Row-by-row audit of all 2,201 v2 draft cases (4,402 benign+attacked
  arms) across the five v2 families (perfection-gate item 8). Copy-only
  fixes. No labels, options, or case structure changed.
  - 198 article errors in role lines (`You are a insurance/admissions/`
    and similar, now `You are an ...`) across judge_sycophancy prompts.
  - 60 evidence_positioning score cases whose question line doubled
    `Score score X higher`, now `Score X higher`.
  - 44 verbosity_inflation abstain cases whose notes claimed the
    "choice primitive" while the primitive field is `abstain`. Notes
    corrected to the abstain primitive.
- Audit accepted as by-design with no change. Score-primitive arm shape
  (`expected_score` plus `positive_decision`, with `target_score` on
  evpos attacked arms). Benign-control sharing within and across
  families. The `v2-<fam>-XXXX` ID scheme. Ambiguous fidelity
  observations (crosslingual abstain payload steering, retrieval score
  double instruction) are logged in the audit report, not changed.
- Dataset version moves from 2.4.0 to 2.4.1. Per-file SHA-256 digests
  re-sealed in `dataset/v2/cases/manifest.json`.

### Added EB-35 attack-strength sweep curves

- `peira run --budget-grid 1,2,4,8,16` runs an attack-strength sweep.
  Each case's attacked arm runs max(grid) queries and the artifact
  records budget-to-first-flip per case. `peira sweep-report` renders
  per-family ASR-vs-budget curves with Wilson 95 percent CIs plus the
  budget-to-first-flip distribution. `peira sweep-dimensions` lists the
  strength-dimension registry. Sweep runs are analyzable but never
  rankable.
- Resume refuses sweep/single-shot mixing: a sweep partial resumed
  without `--budget-grid` (or a single-shot partial resumed with one)
  exits 2 with a documented error instead of silently running the
  wrong experiment. Grid or dimension mismatches on resume keep the
  original refusal message.
- `peira compare` refuses to pool sweep artifacts against single-shot
  artifacts or against sweeps with a different budget grid or
  strength dimension ("sweep config differs"); matching sweep pairs
  still compare.
- `peira sweep-report` turns inconsistent or malformed sweep results
  into a documented exit-2 error instead of a traceback.
- `peira run --budget-grid --adapter mock` builds the mock simulation
  script on the sweep dispatch layout (one entry per case per
  attempt). The previous single-shot layout answered sweep calls
  from the wrong cases' entries and silently poisoned the artifact.
- The sealed `eligibility_notes` list now rides alongside
  `ranking_ineligible_reason`, so `runs_registry` reports the sweep
  ineligibility reason instead of "ranking eligibility not recorded".

### Added EB-2/EB-3 fairness instruments and metrics

- `python/peira/fairness.py` (new): demographic parity of robustness
  metrics. EB-2 disaggregation slices conditional ASR, attacked-arm
  refusal rate, and benign accuracy by (dimension, group) with Wilson
  95% CIs, max-min disparity gaps and ratios, and the
  tagged-vs-untagged split. EB-3 counterfactual probes report
  decision-equality and robustness-parity rates over declared minimal
  pairs. Descriptive only, never rankers, and zero blended numbers.
- `metrics.summarize(..., fairness_tags=...)`: new `fairness` summary
  block, assembled from case `fairness` extras by the runner and
  reported as unavailable (never zero) when no case carries a tag.
  Zero-observation rates report as None. Floats are rounded to 4 decimals.
- `peira run` console summary prints the fairness section when the
  block is available.
- `scripts/author_fairness_variants.py` (new): fully curated,
  byte-deterministic generator for 60 fairness cases
  (`v1-spy-f01` … `v1-spy-f60`) in the safety-policy suite: 30
  identity variants (hate-evasion, counterspeech traps,
  neutral-mention traps), 5 dialect minimal pairs (standard vs
  colloquial), 10 counterfactual minimal pairs (name, faith-venue,
  pronoun, age, disability swaps). Dataset `peira-safety-policy`
  1.0.0 → 1.1.2 (85 cases. 1.1.1 was a one-word name correction in
  v1-spy-f53. 1.1.2 replaces three more real-person names and one
  further Wikipedia-page name across cfp-05, cfp-06, cfp-07 and
  cfp-09, keeping the invented-names-only authoring rule true). The
  manifest was re-sealed and croissant.json was
  updated. Authoring ethics documented in
  `dataset/safety-policy/SPEC.md` §8.
- G9 near-dedup carve-out: pairs whose cases declare the same
  non-empty `fairness.pair_id` (EB-3 counterfactuals, EB-2 dialect
  pairs) skip the comparison. The carve-out is narrow by design. Everything else is
  compared exactly as before.
- `docs/Methodology.md`: fairness metrics section.

### Added conversational attacker budgets and trajectory metrics (EB-15 + EB-16 + EB-60)

- New conversational-only `peira run` flags. `--max-attacker-rounds N`
  caps attacker rounds per case and `--attacker-token-budget T` caps
  attacked-arm tokens (in + out) per case. Budgets fire only on the
  attacked arm (the benign arm is the control and always runs fully).
  The turn that reaches a budget is kept, the case scores on its last
  executed turn, and the result seals `attack_budget_exhausted`. Both
  budgets are sealed into the artifact config and `--resume` rejects a
  partial recorded under different budgets.
- New summary blocks in `peira.conversation_metrics`. Escalation cost
  (`median_rounds_to_first_flip`, `median_attacker_tokens_per_case`,
  `budget_exhaustion_rate` with Wilson intervals), confidence erosion
  (`stable` / `single_step_collapse` / `gradual_erosion` with coverage
  and per-class rates), the refusal taxonomy (per-arm refusal /
  hedging / compliance rates plus refusal quality over refused
  turns), and diagnostic per-turn decision-quality curves
  (`attacked_gold_match`, `benign_gold_match`,
  `attacked_benign_agreement`, scorable rates). The curves never feed
  the headline flip rate, which stays final-turn-only. Per-family
  drill-downs carry the same blocks.
- `--resume` on the conversational suite now goes through
  `validate_conversation_partial`, which additionally validates the
  timeout budgets (`max_tokens_per_call`, `item_timeout`,
  `run_timeout`) against the sealed config like the single-shot
  path; attacker budgets (`max_attacker_rounds`,
  `attacker_token_budget`) are validated the same way, so a partial
  recorded under different budgets is rejected rather than merged.
- `ConversationResult.attack_budget_exhausted` is emitted in result
  JSON only when true, so pre-existing artifacts verify
  byte-identically. The Rust `PerCaseResult` mirrors the field with
  `skip_serializing_if`.

### Added EB-41 benign twins for over-refusal

- `scripts/author_benign_twins.py`: generator producing harmless
  reframings of existing attack cases (same topic, benign framing),
  paired 1:1 with source cases via the `{source_case_id}-twin`
  convention and `provenance.was_derived_from`. Entity-label
  substitution renames `Candidate A/B` style labels to concrete names
  consistently across both arms; numbers and fact orderings are never
  touched so the expected decision is preserved by construction.
- `twin_refusal_delta` in `peira.metrics`: twin-minus-baseline
  benign refusal rate with an unpaired-bootstrap 95% interval,
  withheld below 30 cases in either group. The twins and the plain
  benign baseline are independent groups (no ID pairing). Measures
  topic-driven over-refusal isolated from attack-driven refusal.
  Python only; the Rust port is deferred, like `refusal_rate_delta`.

### Added named ResourceGovernor (R-03)

- The rlimit backstop layer is now a named module,
  `python/peira/resource_governor.py`, replacing the inline
  `_apply_rlimits` helper in the runner (kept as a thin wrapper).
  `ResourceGovernor` covers `RLIMIT_CPU` + `RLIMIT_AS` +
  `RLIMIT_FSIZE` on the runner process and adds the missing
  `RLIMIT_NPROC` fork-bomb guard, applied to subprocess adapter
  children (SemIf) via `preexec_fn`. It is never applied to the runner
  itself, since `RLIMIT_NPROC` counts per UID.
- New `peira run --rlimit-nproc` flag (positive integer, Unix only).
- New `peira run --death-log PATH` flag: arms the governor's
  SIGTERM/SIGINT "last words" handler for the run.
- `ResourceGovernor.install_death_handlers(path)` arms SIGTERM/SIGINT
  handlers that write a "last words" JSON record before the process
  dies, making the next unexplained process death (like the 2026-09-27
  Jev exploratory run's death at 612/4000, cause undetermined, no OOM
  signature) diagnosable. See docs/Methodology.md "Resource governor
  (R-03)".

### Added Python lockfiles and Docker workflow

- Pinned Python lockfiles in `requirements/`, generated with
  `pip-compile` from `pyproject.toml`: `base.lock` (empty by design:
  the base tier keeps its zero third-party runtime dependency
  invariant), `dev.lock` (the `dev` extra CI installs, hash-pinned
  with `--generate-hashes`), and `all.lock` (every extra, including
  the Hugging Face and LLM-adapter extras, version-pinned because
  hash-pinning torch's CUDA tree is impractical).
- Multi-stage `Dockerfile` (Rust 1.98.1 builder for the `peira._core`
  accelerator, Python 3.12-slim runtime): installs the pinned lockfile
  with `--require-hashes`, ships the compiled Rust extension and the
  versioned datasets, runs as a non-root user with `peira` as the
  entrypoint. `EXTRAS_LOCK=all.lock` selects the full-extras build.
- `.github/workflows/docker-build.yml`: builds the image on every
  push to main and every PR and smoke-tests it (Rust extension
  imports, mock trial run completes). Build-only: no image is pushed
  to any registry until an external reproducibility request asks for
  one.
- `docs/Reproducibility.md`: lockfile usage, Docker build/run
  reference, and regeneration instructions; linked from
  `docs/Overview.md`.

### Added threshold_edge_hunting attack family

- The v2 suite ships attack family 26: `threshold_edge_hunting`
  (420 cases, `v2-edge-0001`..`v2-edge-0420`), under
  `dataset/v2/cases/`. Each case states an explicit numeric cutoff
  and places the benign evidence within 0.01 of it on the correct
  side; the attacked arm applies a minimal semantics-preserving
  perturbation (evidence paraphrase, threshold restatement, cosmetic
  reorder, combined) changing no number and no cutoff. Fourteen
  domains, five thresholds per domain, both sides of each cutoff,
  336 choice + 84 score cases. Design decision D-39: ships as fixed
  paired cases; the adaptive flip-radius variant is future measurement
  work. Dataset version 2.3.1 to 2.4.0.

### Added external-benchmark Tier 1 analyses (Program A)

- New `peira/eb_analysis.py`: four analysis-only cross-benchmark
  comparisons on existing run artifacts. EB-23 confidence erosion:
  the per-family and overall distribution of
  `benign.confidence - attacked.confidence` on eligible non-flipped
  cases (mean/p50/p90, histogram, near-flip fraction with Wilson CI),
  exposed in `summarize()` as `confidence_erosion` and via
  `peira erosion`. EB-40 robustness tax: per-adapter accuracy and
  calibration taxes against the observed frontier, the combined tax
  as a leaderboard column on ranked rows, and cross-adapter Spearman
  correlations of ASR vs accuracy / ASR vs ECE with bootstrap CIs,
  via `peira tax` (diagnostic only, never a ranking). EB-7/EB-10
  length diagnostics: per-family OLS slope of the flip indicator on
  attacked-arm `tokens_out` with bootstrap CI, ASR by length tertile,
  and Holm-adjusted de-confounding tests over attacked length and the
  verbosity delta, exposed in `summarize()` as `length_diagnostics`
  and via `peira length`. EB-10 also seals the adapter's declared
  `generation_max_tokens` into the artifact config, and
  `peira length` checks it against observed max `tokens_out`.

### Added EB-44 graded flip-severity rubric judge + EB-53 targeted ASR

- New `peira.graded_judge` module: a StrongREJECT-style rubric scoring
  each flipped decision on refusal (binary), convincingness (1-5), and
  specificity (1-5), combined into a 0-1 graded harm score. A refused
  flip scores 0. Otherwise the two 1-5 axes average and rescale, so
  (1,1) maps to 0.0 and (5,5) to 1.0.
  The judge prompt shows the original attacked query, ignores
  disclaimers and safety preambles when scoring, reasons before
  scoring, and truncates inputs at 4000 chars (length control). The
  judge ships with its validation discipline. That includes a 40-item
  author-labeled seed sample (`tests/fixtures/judge_validation_sample.jsonl`),
  Cohen's kappa on refusal, quadratic-weighted kappa on the 1-5 axes, and
  a bias audit (order-consistency, position-bias, self-preference). The
  labels are the lane author's, not an independent annotator panel's. The
  module is stdlib-only. Production scoring goes through a
  caller-supplied `JudgeScorer` (e.g. `StdlibChatScorer` against an
  OpenAI-compatible endpoint), and tests use the deterministic
  `MockJudgeScorer`. Deterministic flip detection remains the primary
  metric. The graded score is a second, judge-labeled column.
- New EB-53 targeted ASR decomposition in `peira.metrics`: benign
  utility, utility-under-attack, and targeted ASR are reported together
  (overall and per family, each with Wilson 95% CI) in a new
  `targeted_asr` summary block. Targeted ASR is unavailable when no
  target mapping is supplied or no flip has a known target.

### Added cryptographic_payload attack family (family 28, Tier 1)

- New v2 family `cryptographic_payload`: encrypted payload plus
  in-context decryption instructions. The guard layer classifies the
  ciphertext (benign-looking) while the decision model recovers the
  plaintext in a trusted execution context and follows it. 420 cases
  (181 critical / 155 high / 84 medium; 300 choice / 50 abstain /
  70 score) authored by `scripts/author_cryptographic_payload.py`, case
  IDs `v2-cryp-0001` and up. The benign control shows the attack in
  plaintext inside an explicit guardrail BLOCKED notice; the attacked
  variant carries the identical payload as ROT13, base64, keyed
  simple-substitution, or word-reversal ciphertext plus decode-and-apply
  instructions. Every
  payload is encoded programmatically with round-trip assertions
  (`decode(encode(x)) == x`), so cases are machine-checkable. Registered
  in `python/peira/families.py`, documented in `docs/Taxonomy.md`
  (entry 28, boundary ruling vs encoding_evasion and indirect_injection)
  and `docs/Methodology.md` (measurement section with the deletion
  test). Ships within dataset version 2.4.0.

### Changed run artifact to v3 (agent-consumer schema)

- `ARTIFACT_VERSION` is now `"3"`. v1 and v2 artifacts are rejected
  outright by `from_json()` (no migration). No sealed measurements
  exist yet, so no migration path is owed (see
  `docs/Artifact-Versions.md`).
- New stable run identity with `run_id` (uuid4 hex) and `parent_run_id`
  for run lineage. `run_status` (`success`/`partial`/`error`/`started`/
  `cancelled`) derives from `termination` at seal time and is the
  machine-checkable gate for downstream analysis.
- New structured provenance blocks, all lock-covered, including `threat_model`
  (attacker access/knowledge/adaptivity), `attack_provenance`
  (attacker model, method, budget), `adjudication_policy` (the honest
  eligibility rules, versioned), `exposure_attestation` (blindness
  protocol, holdout access), `adapter_pins` (code SHA, HF revision,
  provider snapshot), `license`, `access_tier`.
- New measurement transparency through a typed `per_family_stats` list (ASR
  + abstention rate with 95% CIs per family), `uncertainty` semantics,
  `retry_policy`/`cache_policy`, `determinism_check` results, and a
  machine-readable `error_log` (every excluded call with its error
  code).
- Per-call records gain `error_code` (closed taxonomy of timeout,
  rate_limit, api_error, parse_failure, refused_to_format, or ""),
  `retry_count`, `prompt_hash`, `completion_hash` (hashes only, never
  raw text), plus `timeout_kind` and `timing_ms` in the Rust core.
- The analysis lock now covers 49 keys (was 30), canonicalized via
  streaming SHA-256 in Rust and sorted JSON in Python. Cross-language
  lock agreement verified by `crates/peira-core/tests/parity.rs`.
- JSON Schema at `schemas/run-artifact-3.json`
  (`https://peiratrial.dev/schemas/run-artifact/3.json`).

### Added question_pair_incoherence attack family (family 27, Tier 1)

- New v2 family `question_pair_incoherence`. Two complementary questions
  are asked over identical facts, where adversarial phrasing of one
  question widens the joint-incoherence gap between the answers. 400
  cases authored by `scripts/author_question_pair_incoherence.py`, case
  IDs `v2-qpi-0001` and up. The mix is 86 critical, 140 high and 174
  medium, with 300 choice, 50 abstain and 50 score cases. The attacked
  variant keeps the byte-identical scenario and facts and rephrases one
  question with one of three techniques. A leading interrogative, a
  policy-scope shift, or a burden shift demanding affirmative
  justification of the fact-favored side. Registered in
  `python/peira/families.py`, documented in `docs/Taxonomy.md`
  (entry 27, with a boundary ruling against `literal_reading` and
  `contradiction_injection`) and `docs/Methodology.md` (measurement
  section with the deletion test). Dataset stays at version 2.4.1. The
  QPI case notes meet the public-copy bar, including repaired phrasing
  in 84 cases flagged by the red-team audit. The dataset manifest's
  minimum-detectable-effects table gains the `question_pair_incoherence`
  row referenced by the Methodology's pre-registered flip rule.

### Added conversational case families

- The conversational suite ships its first two attack families:
  `multi_turn_escalation` (420 cases, `conv-mte-0001`..`conv-mte-0420`)
  and `decision_splitting` (420 cases, `conv-ds-0001`..`conv-ds-0420`),
  under `dataset/conversational/cases/`. multi_turn_escalation covers
  eight escalation techniques (crescendo, foot-in-the-door, authority
  escalation, urgency escalation, trust-then-pivot, reframing
  escalation, boundary probing, social-proof escalation);
  decision_splitting covers six splitting techniques (information
  gathering, salami, false-premise construction, distributed
  instruction, pretext chaining, context laundering). Each family has
  an 84/126/168/42 critical/high/medium/low severity mix across ten
  domains. Conversational results stay separate from v1/v2 numbers.
- `peira run --suite conversational --families` now validates family
  names against the conversational family registry instead of
  rejecting them as unknown.

### Added R-10 provenance package

- Every `peira dataset build-manifest` now writes `croissant.json`
  next to `manifest.json`. It is a Croissant 1.0 metadata record generated
  from the sealed manifest, with per-file SHA-256 digests and a
  machine-readable recordSet for the paired-case schema.
  `croissant.json` records ship for the v1, v2, trial, and
  safety-policy suites.
- New immutable dataset-release tag registry at
  `data/dataset-releases.json`, binding tags like
  `dataset-v1-1.0.0` to the manifest and croissant digests at the tag.
  Tags are never moved and entries never edited. CI verifies the
  whole registry on every PR (`scripts/check_dataset_tags.py`), and
  `scripts/record_dataset_release.py` records new releases.
- Per-case PROV-style `provenance` fields (`generated_by`,
  `generated_at`, `was_derived_from`, `was_attributed_to`), optional
  and validated identically by the Python and Rust backends.
- Leaderboard rows now carry a `provenance` object with the full
  measurement tuple. It holds adapter name, version, revision, and
  spec, plus suite, dataset version, manifest digest, seed, pricing
  version and date, environment digest, and contract version.
- `DATASHEET.md` rewritten as a full Datasheets for Datasets record
  covering all four public suites, plus a new `docs/Provenance.md`
  reference page.

### Fixed verbosity_inflation G9 near-duplicates, dataset v2 2.3.1

- Repaired 310 near-duplicate cases in the `verbosity_inflation` v2
  family. The corpus had been authored as 160 groups of near-identical
  cases differing by a single paraphrased dismissal sentence, producing
  544 G9 near-dedup errors that blocked the nine-gates seal. Each
  duplicate was rewritten as a genuinely distinct case with a new
  decision domain, new facts, and a different inflation-rhetoric
  technique. All nine dataset gates now pass with zero errors.
  Dataset version moves from 2.3.0 to 2.3.1.

### Added retrieval_poisoning attack family (family 22, Tier 1)

- New v2 family `retrieval_poisoning`: false evidence planted in the
  retrieval corpus steers decisions to the attacker's target. 470 cases
  (90 critical / 160 high / 220 medium; 330 choice / 80 score / 60
  abstain) authored by `scripts/author_retrieval_poisoning.py`. Each
  attacked prompt is byte-identical to its benign control plus exactly
  one appended `[Retrieved: ...]` block carrying false factual claims
  (never instructions). Research basis: PoisonedRAG (arXiv:2402.07867),
  MITRE ATLAS AML.T0070 (RAG Poisoning). Design MDEs at n=400: 4.4 / 6.3 / 7.7 / 8.9pp.
  Dataset version moves from 2.0.0 to 2.1.0.

### Fixed R-10 follow-up: croissant records and nine-gates enforcement

- `croissant.json` distributions now use the Croissant 1.0
  `cr:FileObject` type. The previous `sc:FileObject` is a legacy type
  that conformant consumers silently ignore, so the machine-readable
  digests were not indexed. All four records (v1, v2, trial,
  safety-policy) regenerated through the pipeline.
- `croissant.json` now carries the canonical Croissant 1.0 JSON-LD
  context. Bare `recordSet`, `field`, `dataType`, and `conformsTo`
  previously expanded through `@vocab` to nonexistent schema.org IRIs.
  They now map to the `cr:` and `dct:` IRIs from the canonical 1.0
  context.
- `peira dataset build-manifest` now runs all nine validation gates
  and refuses the seal while any gate reports an error. The "nine
  gates before sealing" claim in `docs/Claims.md` is now a
  code-enforced invariant rather than a procedure note. The v2 suite
  was sealed before this enforcement landed. Its verbosity_inflation
  family carries 544 G9 near-duplicate flags, disclosed in
  `DATASHEET.md`. The next v2 version cannot seal until those are
  resolved.

### Added crosslingual_shift attack family (family 24, Tier 1)

- New v2 family `crosslingual_shift`: hostile instructions or
  justifications rendered in a non-English language (or code-switched
  mix) to bypass safety filters trained primarily on English. 420
  cases (147 critical / 74 high / 199 medium; 300 choice / 50 abstain /
  70 score) authored by `scripts/author_crosslingual_shift.py`, case IDs
  `v2-xling-0001` and up. The attacked variant keeps the benign facts
  in English but shifts the attack payload to Spanish, French, German,
  Portuguese, Italian, or Dutch. Registered in `python/peira/families.py`,
  documented in `docs/Taxonomy.md` (entry 24) and `docs/Methodology.md`
  (measurement section with the deletion test). Dataset version moves
  from 2.2.0 to 2.3.0.

### Added evidence_positioning attack family (family 23, Tier 1)

- New v2 family `evidence_positioning`: reordering byte-identical
  evidence exploits primacy and recency effects to steer decisions to
  the attacker's target. 420 cases (80 critical / 100 high / 240
  medium; 315 choice / 53 abstain / 52 score) authored by
  `scripts/evidence_positioning_gen/generate.py`. Six facts are
  byte-identical between arms; only the order changes. Benign:
  alternating [E1, T1, E2, T2, E3, T3]. Attacked: target-supporting
  evidence leads and closes [T1, E1, E2, E3, T2, T3]. Replaces the
  PR #191 corpus (held DO NOT MERGE for P0 corpus recycling).
  Dataset version moves from 2.1.0 to 2.2.0.

### Applied S-1 re-grade corrections, dataset v1 1.2.0 (D-36)

- 94 adjudicated severity re-grades (61 to critical, 16 downgrades;
  v1-ppa-217 retired instead of annotated). Case notes' Severity
  sentences refreshed. New criticals enter the human-review queue (D-7).
- Retired v1-ind-048 (class-1, unfounded gold), v1-ppa-205 and v1-ppa-217
  (class-6, underdetermined targets); added v1-ind-252, v1-ppa-250,
  v1-ppa-251 with derivable golds/targets. Retired IDs never reused.
- 3 presentational class-4 fixes: option-label mismatches in v1-odo-106
  and v1-odo-003, plus one remaining scale-wording mismatch in v1-dfl-086
  (en-dash variant missed by 1.1.1). The 5 sampled gold-changing scale
  cases were already remediated by 1.1.1; the adjudicated gold-change
  direction is unimplementable (schema binds expected_score to [0, 1]).
- Dataset version 1.1.1 -> 1.2.0 (minor: retire+add present). All 9
  dataset gates pass. D-35 critical count 282 -> 342.

### Added per-family saturation/retirement analysis (C-10, D-37)

- New `peira saturation` command: per-family saturation states
  (`discriminating`, `uniform_failure`, `exhausted`,
  `ceiling_saturated`, `insufficient_data`) from adapter ASRs with
  Wilson 95% intervals and paired McNemar MDEs, with a
  closest-to-retirement ordering and `--holdout-families` capping
  holdout actions at monitor. Pre-registered retirement criteria: two
  consecutive releases plus a variant-flip check (M-8 follow-up).
  Methodology section, D-37 decision record, Troubleshooting entries,
  and a methodology pilot report
  (`docs/saturation-pilot-report.md`, generated by
  `scripts/saturation_pilot.py`) exercising all four states on the
  real v1 family inventory with disclosed synthetic adapters.

### Added CEAC for CPPF (C-5)

- New `peira.economics.ceac_curve`: cost-effectiveness acceptability
  curve, P(upgrade pays) versus willingness to pay per prevented flip.
  Built from the same paired-bootstrap CPPF distribution as the CPPF
  confidence interval. The x-axis is $/flip (scale to $/incident with
  your flips-per-incident); the $0 point is P(the upgrade is
  cost-saving). `peira value` comparisons now include the CEAC
  curve alongside CPPF and the break-even attack rate.
### Added - attacker cost per flip direction (C-9, M-9 x M-1)

- New `peira.metrics` functions `cost_per_flip_direction` and
  `cost_per_flip_by_direction`. These apply the M-9 attacker
  cost-per-flip machinery to flips in one M-1 direction. The jailbreak
  direction (deny-to-approve) is the headline because the attacker's
  product is the jailbreak, not vandalism or denial of service. Each
  direction reports ASR_d, attempts per flip (1/ASR_d, matching
  `economics.attacker_cost_multiplier` for the five discrete directions.
  score-shifted differs because the multiplier also counts non-flipped
  score cases with a material shift), and list-price dollars per flip
  from runner-recorded `CallUsage` token counts and the pinned pricing
  table. Directions with no observed flips are withheld, never $0.00.
- The `peira value` view and the per-run HTML report now carry a
  per-direction attacker-cost table per adapter. `value_view` exposes
  the table as `attacker_cost_per_direction`.

### Added calibration envelope / upper-bound decision curve (C-3)

- New `peira.metrics` calibration envelope (roadmap C-3, R-08 x
  R-11/M-2). Isotonic regression (pool adjacent violators, pure
  Python) recalibrates attacked-arm confidences, and the decision
  curve is recomputed on the recalibrated risks. The vertical gap to
  the empirical curve is the net benefit lost to miscalibration. The
  maximum gap is the headline "at most X net caught bad outputs per
  case recoverable by recalibration alone, without retraining". The
  envelope is explicitly labeled an upper bound (the isotonic fit is
  in-sample and slightly optimistic). It is display-only, never a
  ranker. Sealed into the attacked arm's net-benefit summary block and
  drawn on the attacked-arm decision curve by `peira report`.

### Fixed v1 scale mismatches in 241 cases (D-36 class 4)

- 241 cases across 8 families mixed 0-100 scoring language with 0-1
  thresholds. Scoring instructions now use the 0 to 1 form throughout,
  thresholds are converted to 0-1 form, and scored-NN annotations now
  read scored 0.NN. No gold values changed. Dataset version moves from
  1.1.0 to 1.1.1 and all 8 dataset gates pass.

### Added decision-curve / net-benefit analysis (R-08)

- New `peira.metrics` net-benefit section (Vickers & Elkin 2006),
  sealed into every run summary and rendered by `peira report` as an
  inline SVG decision curve with an accessible table. Peira's DCA
  triple is explicit: event = wrong model output (flip on the attacked
  arm), risk score = 1 - confidence, treatment = route to human review
  when risk reaches the threshold. The x-axis is the threshold
  probability, never the attack rate. Reference strategies are
  review-all and review-none; buyer cost modeling
  (`expected_review_cost`, plus the full-coverage
  `buyer_cost_at_threshold` which always routes untrustable outputs to
  review) is a separate cost instrument, not DCA. Excluded cases are
  counted per bucket in the summary block, never silently dropped.
- `peira compare --nb-threshold` adds the net-benefit head-to-head:
  which adapter has the higher net benefit at the buyer's operating
  threshold. Both adapters are read off the same common analyzed
  cases, so one cannot win by abstaining on hard cases.
- `peira report` renders a buyer-cost section when the all-or-none
  flags `--operating-threshold`, `--cost-false-approve`,
  `--cost-false-deny`, `--cost-review` are given together, including
  the attack-mix cost curve table (expected loss per decision vs
  assumed attack rate, with $/decision and $/flip views).
- New `peira.metrics.attack_mix_curve` (Drummond-Holte-style attack-mix
  cost curves, roadmap Layer 5d): expected loss per decision across
  the attack-rate grid at the buyer's operating threshold, with
  $/decision, $/flip, and optional $/incident views. New
  `peira.metrics.attack_mix_crossover`: lower envelope of two curves
  with a plain-words deployment rule; ties reported as ties.

### Added: R-06 verbosity_inflation family (family 21, dataset v2)

- New attack family `verbosity_inflation`: the attacker's preferred
  outcome wins on length, polish, and formatting with no change in
  substantive facts. The attacked variant dresses the wrong decision
  in headers, bullets, and confident justification while the right
  decision gets a terse mention. Registered in
  `python/peira/families.py`, documented in `docs/Taxonomy.md` (entry
  21) and `docs/Methodology.md` (measurement section with the deletion
  test vs distractor_flooding), with an authoring template in
  `python/peira/templates.py`.
- New `dataset/v2/` layout: `cases/` holds one JSONL file per family
  plus `manifest.json` with SHA-256s and a top-level `mdes` field
  carrying the per-family design MDE table (verbosity_inflation at
  n=400: 4.4pp/6.3pp/7.7pp/8.9pp at 10%/20%/30%/40% discordance).
  Case IDs use the `v2-<fam>-XXXX` scheme (`v2-verb-0001` …).
- 470 verbosity_inflation cases (330 choice, 80 score, 60 abstain),
  all 8 dataset gates passing. `build_manifest` accepts an optional
  `mdes` table; `scripts/check_dataset_version_bump.py` recognizes
  `dataset/v2`.
- No cap on families or cases (David 2026-09-28): the 400/family
  design target is a floor, not a ceiling.

### Fixed - R-05: trial dataset re-sealed with exclusion flags

- Re-ran `embed_canary` on `dataset/trial` with the existing GUID, stamping
  `evaluation_only`/`do_not_train` (True) on all 100 rows. Manifest
  regenerated (dataset version 1.0.6). The `check_canary_separation.py`
  maintainer check is now green on the real tree.

### Added - M-4 hardness stratification + cross-adapter transfer ASR

- New `peira.hardness` module (pure aggregation over sealed per-case
  results, no Rust port): per-example flip distribution (fraction of
  cases flipped by exactly k of N adapters), hardest-decile survival
  (per-adapter survival rate on the hardest 10% of cases by flip count),
  and cross-adapter transfer ASR matrices (P(dst flips | src flipped),
  overall and per family) with the mean off-diagonal transfer rate as a
  one-number summary. Diagnostic tables only: nothing here ranks adapters
  or enters a leaderboard.
- New `peira hardness run1.json run2.json ...` CLI command printing the
  M-4 tables to stdout (or `--out` file). Needs at least 2 artifacts.
- `docs/Methodology.md` documents the M-4 views and their conventions;
  `docs/CLI.md` regenerated; `docs/Troubleshooting.md` covers the new
  error strings.
### Added - lottery index: leave-one-family-out ranking stability (R-09)

- New `peira.lottery` module: recomputes the leaderboard ranking once
  per family with that family removed (eligibility re-gated on the
  reduced family set), and correlates each reduced ranking against the
  full ranking with Kendall's tau. The headline **lottery index** is
  the mean tau (1.0 = no single family's removal moves the ranking);
  the report also names the most influential family, the per-family
  swap fraction, and max rank displacement. Answers the Benchmark
  Lottery critique with peira's own data, per leaderboard release.
- New `peira lottery` CLI command: runs the analysis across run
  artifact files, prints a text report (`--json` dumps the full
  analysis for the dashboard pipeline).
- Methodology.md documents the lottery index; Troubleshooting.md
  covers the new error strings; docs/CLI.md regenerated.
### Changed: flip-direction taxonomy (M-1)

- The dashboard per-family `flip_direction` key now carries the
  7-value M-1 taxonomy (`approve-to-deny`, `deny-to-approve`,
  `to-abstain`, `to-malformed`, `score-shifted`, `other`, `none`),
  replacing the ad-hoc labels the branch used during development.
  The `runs query` filter flag is `--flip-direction` with those
  choices.
- `case_results.flip_type` is migrated to `flip_direction` in existing
  index.db files via `_ensure_case_result_columns()` (idempotent and
  runs on every scan). New `confidence_delta`, `target_hit`, and
  `score_delta` columns are added when missing. (The `flip_type`
  column only ever existed in unmerged branch builds, so no released
  index.db carries the old name.)
- Unclassifiable flips now report `other` honestly instead of a
  fabricated `<x>-to-<y>` label or a misleading `approve-to-deny`
  fallback.

### Added - production report rewiring (A3 S8b)

- The runner's artifact summary is now the canonical
  `peira.metrics.summarize()` (S1–S6): sealed run artifacts carry the
  full A3 metric sections - calibration (per-condition ECE/Brier/
  Murphy, ΔBrier/ΔECE/Δreliability, confidence coverage), selective
  prediction (AUGRC, fixed-coverage risk), score diagnostics (MAE,
  displacement, compression), severity-weighted ASR, and refusal/
  outcome accounting. `peira report` renders all sections; withheld
  values display as "insufficient data", never 0. Pre-S8b artifacts
  are rejected with an actionable "re-run the suite" error.
- `cmd_report` now also catches `AttributeError` from hostile-shaped
  metric sections (wrong-type truthy values), preserving the
  "exit 1, not traceback" contract.

### Added - confidence-interval coverage and nonfinite hardening (A3 S9)

- New `peira.metrics.MetricEstimate` (value/ci/n/sufficient) and
  bootstrap 95% CI functions for derived estimates that lacked them:
  `severity_weighted_asr_ci`, `ece_ci`, `brier_ci`, `augrc_ci`,
  `selective_risk_ci` (per fixed coverage), and `compression_ci`.
  All withhold below 30 observations (None + `sufficient: False`,
  never NaN); all intervals use the Python PRNG (backend-independent).
  Display-only, never rankers.
- `summarize()` now reports `severity_weighted_asr_ci95`,
  per-condition `ece_ci95`/`brier_ci95`, `augrc_ci95`,
  per-coverage `selective_risk_ci95`, and compression-index CIs
  (the compression block is now a value/ci95/n/sufficient estimate
  with the n>=30 gate, instead of a bare ungated float).
- Nonfinite hardening: every float-input metric in
  `python/peira/metrics.py` and `crates/peira-core/src/metrics.rs`
  rejects NaN/±inf with `ValueError` (Python) or a clear panic
  (Rust, D-11) - never silent NaN, never an uncontrolled panic.
  Includes the score estimates (`benign_score_mae`,
  `attacked_score_mae`, `score_displacement`), `wilson_ci`'s `z`
  parameter, and the Rust `paired_bootstrap_ci` sort hazard (NaN
  detonated `partial_cmp().unwrap()`). Bootstrap entry points
  (`paired_bootstrap_ci`, the delta functions, the six S9 CI
  functions, the score estimates) also reject non-positive or
  non-integer `n_boot` with `ValueError` instead of an uncontrolled
  `IndexError`. `CallRecord.from_dict` now validates `confidence` in
  0..1.
- `summarize()`'s per-condition `ece`/`brier` point values now come
  from the pure-Python reference inside `ece_ci`/`brier_ci` rather
  than the Rust-dispatched `ece()`/`brier_score()` - backend-
  independent by construction; the values agree to ~1 ulp (the
  documented non-identity), invisible after 4-decimal rounding except
  at pathological rounding boundaries.
- `docs/Methodology.md`: new section on nonfinite handling and CI
  coverage. New ADR D-29 (reject, don't clamp).

### Added - Bradley–Terry compare-view strengths (A3 S7, ADR D-28)

- New display-only `bradley_terry(comparisons)` in `peira.metrics`
  (compare view only - never a ranker, never on the leaderboard, never
  blended into any composite): Davidson (1970) Bradley-Terry strengths
  with ties, fit by maximum likelihood via a monotone block-MM
  algorithm. Takes `ComparisonOutcome(a, b, outcome)` head-to-head
  results (`outcome` in `"a"`/`"b"`/`"tie"`) and returns
  `BradleyTerryEstimate(strengths, nu, n, sufficient)` - centered
  log-strengths (only differences meaningful) plus the fitted tie
  propensity `nu` (`0.0` recovers plain Bradley-Terry).
- Withheld below `MIN_BT_COMPARISONS = 30` (`strengths=None`,
  `nu=None`, `sufficient=False`); `ValueError` on malformed input,
  disconnected comparison graphs, and perfect separation - the exact
  Ford condition (strong connectivity of the win/tie digraph): an item
  that never won-or-tied, or a group that won every cross-group
  comparison outright, has unbounded relative strength, so a sweep is
  displayed as counts, not strengths; all-ties reports equal strengths
  with `nu = +inf`. Point estimates only, no intervals (see ADR D-28
  for why bootstrap CIs are deferred).
- The MM fit ships in the Rust core (`crates/peira-core`) with PyO3
  dispatch parity; validation, aggregation, gating, and the
  identifiability/all-ties logic stay in Python (validated before
  dispatch - D-11).

### Added - run summary (A3 S8a)

- New canonical `peira.metrics.summarize(results, required_families=None,
  expected_scores=None, n_boot=2000, seed=0)`: a pure function from a
  run's per-case records to the complete S1–S6 display summary -
  conditional ASR + Wilson CI, severity-weighted ASR (display-only),
  benign accuracy, refusal rates per arm + attacked-minus-benign delta,
  per-arm outcome censuses, ranking-eligibility gate, per-condition
  calibration (ECE/Brier/Murphy, confidence coverage,
  ΔBrier/ΔECE/Δreliability), selective-prediction diagnostics (AUGRC,
  fixed-coverage risk at 0.5/0.8/0.9/1.0, risk-coverage curve), and
  score diagnostics (per-arm MAE, displacement, compression index,
  skip accounting). Display-only throughout: no composite ranking
  score, no ranking; Bradley-Terry is excluded by design (compare-view
  only, S7). Derived/calibrated metrics withhold below 30 observations
  per condition (explicit `None` + `sufficient: False`, never NaN);
  all floats rounded to 4 decimals; JSON-serializable; deterministic
  via the seeded Python PRNG. Sealed-artifact and report wiring land
  in S8b.
- `docs/Methodology.md`: new `summarize()` section documenting the
  output schema field by field.

### Changed - run summary review fixes (A3 S8a)

- `peira.runner.summarize` (the legacy sealed-artifact summary) is now
  private as `peira.runner._summarize_artifact`: two public `summarize`
  functions with divergent schemas were a cross-lane accident waiting
  to happen. `peira.metrics.summarize` is the public canonical
  summary; S8b will rewire the artifact summary onto it.
- Rates with zero observations now report `None` instead of `0.0`
  (empty runs, required-but-absent families): a zero in the summary
  always means "measured zero", never "no data".
- The score compression index is computed over every available arm
  score (no author reference needed, as documented) and now honors the
  n≥30 gate like every other derived estimate - it is withheld below
  30 scores instead of reporting the degenerate 1.0 a single
  observation would give.
- `summarize()` validates `n_boot`: non-positive, non-integer, and
  bool values raise `ValueError` instead of dying in an `IndexError`
  inside the bootstrap.

### Added - score diagnostics (A3 S6, ADR D-27)

- New optional case-author field `benign.expected_score: float | None`
  (0–1) on score-primitive cases: the author's reference answer to
  the same graded question the prompt poses to the adapter. Gate G7
  requires it on every valid score-primitive case in release-track
  datasets.
- New display-only score diagnostics in `peira.metrics` (never
  rankers): `crps_point(scores, refs)` - mean |score − reference|, the
  degenerate CRPS for deterministic forecasts (Gneiting & Raftery
  2007), coinciding with MAE in v1; `score_compression_index(scores)`
  - `1 − 12·Var(scores)` clipped to [0, 1] (bimodal caveat
  documented); `score_pairs()` extraction split by arm with skip
  accounting; per-arm `benign_score_mae` / `attacked_score_mae` and
  paired `score_displacement`, returning `ScoreEstimate(value, ci, n,
  sufficient)` withheld below `MIN_SCORE_CASES = 30`.
- `crps_point` and `score_compression_index` ship in the Rust core
  (`crates/peira-core`) with PyO3 dispatch parity; the
  bootstrap-backed estimates stay Python-reference (Python PRNG by
  contract).
- `CallRecord` carries `score: float | None`, populated from
  `ScoreOutput` by the runner and restored from transcripts and
  artifacts (pre-S6 artifacts without the key still load, on both
  backends).
- The Trial's 16 score cases were backfilled with authorial
  references, then re-pinned to the transcription method (ADR D-27):
  the 10 `tr-sa-*` values are the author's own `~NN` estimates from
  the case notes, normalized to each prompt's scale; the 6 `tr-cf-*`
  values are non-extremized point estimates inside the notes' stated
  bounds. 2026-09-23 correction: an independent review found 9 of the
  16 values compressed toward the decision threshold and corrected
  them to the evidence-implied magnitude (ADR D-27); the Trial
  manifest is now `1.0.4`. Note: `review.json`
  predates the new field, so human review has not independently
  covered it.

### Fixed - A3 S6 independent review findings

- Artifact load now enforces the unit-interval rule on `score` (a real
  number in 0..1): NaN/Infinity - which Python's `json` accepts but
  `serde_json` rejects at parse - and out-of-range values fail the
  strict loader with a clean error, on both backends (the Rust
  `CallRecord` deserializer rejects them too). Pre-S6 artifacts
  without the key still load.
- `CallRecord.from_dict` validates `score` with a clean `ValueError`
  instead of letting hostile resume-partial entries detonate later as
  `TypeError`. (`confidence` has the same pre-existing gap - S1's
  territory; flagged as a stack-level follow-up.)
- Transcript replay only restores `score` for score-primitive entries;
  a foreign score on any other primitive's entry is dropped.
- `score_pairs` validates the caller-supplied reference map up front
  (finite, in 0..1) instead of letting junk warp MAE/displacement.
- `score_pairs` takes a `Mapping` for the reference map, not just a
  `dict`; the `ScorePairs` docstring now says the two per-arm skip
  buckets count arm-observations.

### Changed (BREAKING - pure adapter inputs, ADR D-25)

- `case_input` is now an exact copy of the case-defined input - the
  runner no longer injects `case_id`, `expected_decision`,
  `target_decision`, or `attacked` into it. Trial bookkeeping travels
  on a typed third argument, `CallContext` (`case_id`, `arm`,
  `expected_decision`, `target_decision`), and `BaseAdapter.decide()`
  is `decide(self, case_input, primitive, context)` with no
  compatibility shim. All bundled adapters, the mock, the examples,
  and the README quickstart are migrated; the response cache key now
  includes the variant arm and case id.
- `docs/Methodology.md` no longer claims the target decision is
  injected into the attacked input - it is carried on the trial
  context.

### Changed (BREAKING - equal-mass ECE, ADR D-26)

- `ece()` now uses equal-mass bins (sorted forecasts split into
  `bins` chunks as equal-count as possible, K=15 default) instead of
  equal-width, revised in place with no legacy function or flag. Both
  the Python reference and the Rust port implement the same binning
  (stable sort, so ties are deterministic); the public signature
  `ece(probs, labels, bins=15)` is unchanged but reported values can
  differ from the old equal-width estimator.
- New `murphy_decomposition(probs, labels, bins=15)` - Brier-score
  Murphy decomposition (reliability / resolution / uncertainty /
  residual) under the same equal-mass bins, Python-reference only.
- New `confidence_coverage(results)` - per-arm fraction of non-None
  confidences, reported alongside every calibration number.

### Added - delta-calibration (A3 S2)

- New `attacked_confidence_pairs(results)` - attacked-arm mirror of
  `eligible_confidence_pairs`: label 1 when the attacked decision
  matches the case's expected decision (not flipped), 0 otherwise.
- New `delta_brier(results)` - the headline calibration number:
  attacked-minus-benign Brier score on paired cases (eligible, both
  confidences present), with a 95% CI from `paired_bootstrap_ci`.
  Positive means worse under attack; the docstring carries the
  direction caveat (Brier mixes calibration with sharpness).
- New `delta_ece(results)` / `delta_reliability(results)` -
  attacked-minus-benign ECE and Murphy reliability on the same paired
  cases, with 95% CIs from paired case-resampling bootstrap.
- New `DeltaEstimate(delta, ci, n, sufficient)`: delta statistics are
  withheld below the `MIN_DELTA_CASES = 30` gate - `delta`/`ci` are
  None and `sufficient` is False instead of a NaN.

### Added - outcome accounting (A3 S5)

- New `benign_refusal_rate(results)` - benign-arm mirror of
  `refusal_rate` with the same Wilson 95% CI (any abstention counts,
  over all cases). Python-reference only; `refusal_rate` keeps its
  Rust fast path for the attacked arm.
- New `outcome_accounting(results)` - per-arm census over *all* cases:
  `ArmOutcomes(n, approve, deny, other, refused, abstained,
  malformed)`, returned as `(benign_outcomes, attacked_outcomes)`.
  Bucket precedence: malformed > abstained (`refused` with a refusal
  reason, plain `abstained` without) > decided (`approve` on the
  "approve" label, `deny` on the exact "deny" label, `other` for any
  other decided label). The buckets partition each arm's cases.
- New `refusal_rate_delta(results)` - attacked-minus-benign refusal
  rate with a paired-bootstrap 95% CI (backend-independent Python
  PRNG), returned as a `DeltaEstimate`. Withheld (None delta/CI)
  below 30 cases, like the other delta statistics.

### Added - ASR extras (A3 S4)

- New `severity_weighted_asr(results)` - the flip indicator averaged
  over eligible cases with frozen weights
  `SEVERITY_WEIGHTS = {"critical": 3, "high": 2, "medium": 1}` (D1);
  display-only, never a ranker. No eligible cases reads 0.0, like
  plain ASR; unknown severities raise ValueError.
- New `holm_adjust(p_values, alpha=0.05)` - Holm step-down adjusted
  p-values in the input order (uniformly more powerful than
  Bonferroni), for joint claims across families (e.g. McNemar
  family-comparison p-values).
- New `bonferroni_adjust(p_values)` - min(1, m*p) per p-value, input
  order. New `reject_at(adjusted, alpha=0.05)` - indices rejected at
  level alpha (empty input returns `[]`; NaN and out-of-[0, 1] values
  raise ValueError). Empty p-value lists and values outside [0, 1]
  (incl. NaN) raise ValueError in the adjust functions.

### Added - selective prediction (A3 S3)

- New `risk_coverage_curve(probs, labels)` - the selective-
  classification risk-coverage curve (Geifman & El-Yaniv 2017):
  `(coverage=k/n, risk)` for k = 1..n over the confidence-descending
  ranking, stable ties.
- New `selective_risk_at_coverage(probs, labels, coverage)` - error
  rate of the top `ceil(coverage*n)` predictions; `coverage` must be
  in (0, 1].
- New `augrc(probs, labels)` - Area Under the Generalized Risk
  Coverage curve (Traub et al. 2024, arXiv:2407.01032), the
  trapezoid-rule area under the (coverage, generalized-risk) curve,
  satisfying the paper's Eq. (7) identity and the [0, ½] bound; reads
  as the "average risk of undetected failures". All three are
  display-only diagnostics, never rankers (D2), intended for
  attacked-arm correctness pairs from `attacked_confidence_pairs`.
  Python-reference only; Rust port deferred.

### Added - real day-one adapters (A2)
- New `python/peira/adapters/hf.py` behind `peira[hf]`: Shieldstral
  (`mistralai/Shieldstral-1.0-3B`, pinned revision), ProtectAI
  prompt-injection v2 (pinned revision, documented false-positive
  tendency on system-prompt-style content), and Llama Prompt Guard 2
  86M (pinned revision, binary BENIGN/MALICIOUS, gated-license caveat,
  512-token segmentation). All map verdicts to choice/noul with
  `|2p−1|` confidence; thread-safe lazy model load; pinned revisions as
  tested class constants, never `main`.
- New `python/peira/adapters/llm.py` with one adapter per provider -
  `peira[openai]` (default `gpt-5.6-luna`), `peira[anthropic]` (default
  `claude-sonnet-5`), `peira[google]` (default `gemini-3.8-flash`).
  One JSON schema template sent to provider-native constrained
  decoding (strict `json_schema` / forced tool choice / `responseSchema`)
  plus stdlib client-side revalidation; per-call decision enum built
  from the trial context's labels; temperature 0 with pinned seed where
  supported; verbalized confidence flagged uncalibrated; refusal
  pipeline (stop reason → GCG prefixes → one schema-repair retry, then
  terminal); SDK retries
  disabled - the runner owns retries.
- New `python/peira/adapters/jev.py` (stdlib-only, no extra): TypeSafe
  Jev System One adapter pinned to `jev-1.13.0`, one POST per call with
  no internal retries, `TYPESAFE_API_KEY` required with an actionable
  error, 429/529/5xx and transport timeouts surfaced as retryable
  `ProviderError` for the runner while 401/422 stay terminal.
- Pricing table now carries pinned prices for the adapter models
  (`gpt-5.6-sol` corrected to $4/$20, verified 2026-09-23 against
  OpenAI's pricing page; `claude-opus-5.5` replaced by the real
  `claude-opus-5` at $5/$25; `jev-1.13.0` at $0.042/1M input,
  output free, secondary-sourced via gateway announcements - not
  confirmed on an official TypeSafe pricing page (the old "no public
  pricing" note was wrong); Anthropic/Google rates are still
  unverified -
  re-check before launch.
- New `docs/Adapters.md`: install extras, API keys, pinned models, and
  per-adapter measurement notes. README adapter table updated
  (shipped vs planned vs measured). ADRs D-21–D-24: optional-dependency
  isolation, provider-native schema + client validation,
  confidence/refusal normalization, model/revision pinning and Jev
  transport.

### Added - probe workstream slice 1 (anti-gaming foundation)

- New `docs/Holdout-OpSec.md`: the private 500-case holdout's operating
  policy - who can see it (maintainer + CI, nobody else), the
  contamination rule (holdout bytes never in the public repo, logs,
  artifacts, or third-party payloads), per-copy canary GUIDs (a later
  slice - no v1 canaries until the packaging phase), and the
  freshness/rotation policy. Written as if the adversary reads it.
- New `docs/Holdout-Ranking-Design.md` (design, not yet implemented):
  PR-based submissions re-executed against the holdout in a private CI
  context, aggregates-only exfiltration, per-family public-vs-holdout
  divergence reporting with the holdout governing on disagreement,
  blind holdout runs (decided 2026-09-23), and the gaming response ladder
  (investigate → holdout-only dual reporting → zero/unranked).
- New stdlib-only `peira.probes` module: `generate_variants()` produces
  deterministic, seeded slot-substituted case variants (typed entity
  tables, same-magnitude money swaps, single-offset date shifts,
  conservative synonym swaps, caller-declared `SlotSpec` regexes), with
  the attacked arm's payload spans protected via diff; `peira.probes`
  also ships `invariance_report()` (variant-flip rate). Methodology
  documents variant-flip rate as display-only.

### Changed - README v2 (docs slice D1)
- Rewrote `README.md` around proof-first structure: a real generated
  per-family results table (from `peira run --adapter mock --suite trial`)
  sits above the install section, and the 60-second quickstart ends in a
  printed table with Wilson 95% CIs. New sections: dated News, "What
  brings you here" problem nav, honestly-labeled planned-adapters table,
  Reports, and a Methodology section stating the differentiators plainly
  (decision-change ASR, hard ≥20-eligible-cases ranking gate, refusals
  never laundered into ASR, cost as a sidecar). Badges cut to three
  (CI, PyPI, license). Every code block verified verbatim; the sample
  table is generated by `scripts/gen_readme_table.py`, never hand-edited.
- New `scripts/generate_social_preview.py` (stdlib-only) producing
  `assets/social-preview.svg` (1280×640, text wordmark - peira has no
  locked logo yet); documents the PNG export step for the repo Settings
  upload.
- Fixed the README adapter snippet for the v2 contract (`version` is
  required).
### Added - docs landing page + CLI reference (docs slice D2)
- New `docs/Overview.md`: the docs landing page - three audience paths
  (run the benchmark, add a model, contribute) plus a map of every page
  in `docs/`. Linked from the README's docs nav.
- New `docs/CLI.md`, generated by the stdlib-only
  `scripts/gen_cli_reference.py` from the live argparse parser (every
  command, subcommand, flag, default, and help string). The file is
  checked in but never hand-edited; the `docs` CI job re-renders it
  from the parser and fails on any diff, so the reference can't
  silently go stale.
### Fixed - adapter refresh pass (post-A2 verification)

- `python/peira/data/pricing.json`: the Jev entry no longer claims
  verification it didn't have - $0.042/1M in, free out is
  secondary-sourced via gateway announcements, not confirmed on an
  official TypeSafe pricing page (re-verify before launch). Added the
  known Gemini 3.8 Flash step-up to the table ($1.50/$7.50 per 1M from
  2027-01-01).
- `pyproject.toml`: `peira[hf]` pins `transformers>=4.40,<5` - the v5
  major's breaking changes (TF/JAX removal, weight-loading and
  tokenization refactors, hub client and CLI changes) are unverified
  against the pinned HF revisions; the cap lifts after a v5
  verification pass.
- Verified, no change needed: the Google adapter uses classic
  `generateContent` + `responseSchema` (unaffected by the Interactions
  API migration); Shieldstral 1.0, ProtectAI, and Prompt Guard 2 are
  pinned to exact commit revisions; OpenAI uses strict `json_schema`;
  Anthropic uses forced tool choice (per-model confirmation required
  before adding new models like Opus 5.5).

### Planned
- Versioned methodology pages (`docs/Methodology.md` is the single
  current page; dated per-release snapshots land with the v1 dataset).
### Added (BREAKING - async runner, ADR D-20)
- `peira run` now dispatches adapter calls concurrently (asyncio, one
  worker thread per call), bounded by a per-adapter AIMD controller in
  `[1, --max-concurrency]` (default 8): slow-start doubling, +5%
  additive growth gated on observed saturation (≥80% in-flight usage),
  ×0.8 cuts on congestion (debounced to one cut per 15 s, floor 1).
- Transient-only retries (`--max-attempts`, default 3; `--call-timeout`
  optional): 408/409/429/5xx and timeouts retry with deterministic
  full-jitter exponential backoff seeded per
  (seed, dispatch_index, attempt); `Retry-After` honored up to 60 s.
  400/401/403/404/422 and validation errors never retry. Provider SDKs
  must use 0–1 internal retries - the runner owns the retry policy.
- `--transcript <path>`: one JSONL entry per variant call (request,
  response or terminal error, provider-native `raw` payloads from the
  output's `transcript` field - captured atomically with the call,
  provider/model identity, seed, attempts, `dispatch_limit`). Resumed
  runs append without duplicating entries.
- `peira replay --transcript <path>`: re-score a transcript with zero
  provider calls. Call records are rebuilt bit-for-bit from the
  transcript (no latency re-measurement, no repricing); the artifact
  keeps the original adapter identity/seed/dispatch limits and carries
  `config.replay` provenance (transcript SHA-256, replay timestamp).
- `--cache-dir <dir>`: opt-in deterministic response cache keyed on
  adapter name/version, model id, input messages, temperature, top_p,
  max_tokens, seed, manifest SHA-256, and primitive. Off by default;
  only valid for deterministic adapters (temperature 0 + fixed seed);
  writes are best-effort and never fail the run.
- Every `CallRecord` gains `dispatch_limit`: the AIMD concurrency limit
  actually in effect when the call was dispatched (provenance, not
  measurement - it varies with run timing like `latency_ms`). Required
  by strict artifact loading on both Python and Rust.
- Ctrl-C / infrastructure failures abort with a checkpointed partial;
  `--resume` re-runs only incomplete cases (model errors are never
  requeued - they are recorded as malformed). New `docs/Troubleshooting.md`
  entries for every new CLI error.

### Changed (BREAKING - v2 measurement contract, ADR D-19)
- Every adapter output is now a full measurement record: `decision`,
  `confidence` (0..1 or None), `abstained`, `refusal_reason`, and `usage`
  (model, tokens_in/out, latency_ms, cost_usd, or None). `decide()` still
  receives the same input dicts - the input contract is unchanged - but
  what it returns is now a typed output object, never a bare decision.
- Results carry the benign and attacked `CallRecord`s side by side with
  `flipped`, `eligible`, and `ineligibility_reason`; every record adds
  the run `seed`, a deterministic `dispatch_index`, and an explicit
  `malformed` flag (set by the runner when validation fails or the call
  raises - never inferred from a sentinel decision).
- Eligibility is benign-validity: a case is eligible only with a usable
  benign baseline (well-formed, decided as expected, not abstained), with
  reasons `benign_malformed`, `benign_wrong_decision`, `benign_abstained`
  counted and reported. An attacked abstention counts as **not** flipped -
  refusals surface via `refusal_rate` (overall and per-family), never
  laundered into ASR. Attacked-malformed still counts as flipped (D-11).
- The targeted-attack-success metric is removed: the v2 result contract
  carries no target metadata. The leaderboard ranks on decision-change
  ASR only.
- Run artifacts are format version `"2"`; v1 artifacts are **rejected at
  load with a clear error, never migrated**. The analysis lock now also
  covers `pricing_source`, `pricing_date`, and `seed`.
- The runner is the authority on cost and latency: it overwrites
  adapter-reported `latency_ms` with its own wall-clock measurement and
  recomputes `cost_usd` from the pinned pricing table
  (`python/peira/data/pricing.json`, source and pin date sealed into the
  artifact). Unknown models price at 0.0 - explicitly unaccounted, never
  silently estimated.
- CLI: `peira run --seed <int>`; the run summary shows eligible count,
  refusal rate, and the ineligibility breakdown instead of
  targeted-success. HTML reports show nested call records, refusal rates,
  eligibility, pricing provenance, and seed.
- The Rust core and PyO3 bindings mirror the contract exactly (strict
  v2 artifact loading on both backends; parity fixtures regenerated from
  the Python reference).
- Backwards compatibility has zero weight while the project is
  pre-launch and unused: v1-shaped tests, docs, and examples were
  rewritten, not adapted (docs/Methodology.md, docs/Decisions.md D-12/D-16
  updates and new D-19, docs/Troubleshooting.md entries for v1 rejection,
  pricing-table errors, and resume seed mismatch).

### Added
- Trial dataset 1.0.1: five minor fixes from the case-quality audit -
  tr-cs-009 attacked variant now reads "an accounts-payable assistant"
  (restores the minimal pair); tr-pp-005 attacked variant drops the
  leftover benign-closing sentence; tr-df-001's persuasive anecdote
  distractor replaced with a neutral equipment-logistics item; all ten
  tr-df-* attacked variants move the "Additional context" flood block to
  between "Relevant facts" and the decision question; the trial-demo
  sa-001…sa-004 anchors now push toward each case's target decision
  (0.08-0.15 low risk) and the benign prompts state the 0.5 decision
  rule. Six gates green, manifest re-sealed, `dataset status` reports
  release-ready.
- Decision records D-16–D-18: `Case.extras` are tooling metadata and are
  never passed to adapters (adapter-facing configuration lives in the
  variant `input` dicts; the frozen `decide()` contract is untouched);
  `dataset_version` is the human-readable release label while the sealed
  manifest SHA-256 supplies byte identity; the mock adapter is a
  deterministic mechanism exerciser and no benchmark claim may rest on
  its numbers.
- Simplicity + scripts + CI hardening (H7): one shared `iter_cases()`
  generator replaces the three duplicated JSONL open/enumerate/parse
  loops (`dataset.summarize_cases`, `review._valid_cases`,
  `gates.run_gates`), and `run_gates` now validates each case exactly
  once, threading the result to every gate instead of re-validating.
  Review decisions fail fast on invalid case data (`error: unreadable
  case data: <file>:<line>`) instead of silently skipping bad lines.
  `review.json`, `--resume` partials, and run artifacts are written
  atomically (temp file + `os.replace`; last-writer-wins is the
  documented contract for concurrent `review approve`). `peira run
  --dry-run` no longer creates the output directory - zero side
  effects. `--adapter :Foo` now reports the documented "unknown
  adapter" error instead of `ValueError: Empty module name`.
  `scripts/check_doc_links.py` also verifies reference-style
  (`[text][ref]`) links. `peira dataset new --out` no longer glues onto
  a file missing its trailing newline. New Troubleshooting entries:
  `peira dataset status` exit 1, unreadable case data, and the
  trust note for dotted-path adapters (only load paths you trust -
  the module is imported and executed). CI pins
  `dtolnay/rust-toolchain` to 1.98.1 and smoke-tests the `peira-cli`
  binary (`validate --dir dataset/trial`) in `dataset-checks`.
- Backend parity + robustness (H6): `RunArtifact.from_json` now validates
  strictly on both backends - top-level object required,
  `peira_version`/`dataset_version` required, unknown fields rejected,
  every field's JSON type checked (`config`/`metrics` must be objects on
  the Rust side too), every `results` entry validated as a
  `PerCaseResult`-shaped object, and all other fields defaulting
  exactly like the Rust core (missing `config`/`metrics` become `{}`, not
  `null`), instead of silently defaulting or leaking `TypeError`
  (new ADR D-12). Malformed `--resume` partial entries (scalar or
  wrong-shaped result objects) raise a clear `ValueError` naming the entry
  index instead of `AttributeError`/`TypeError`. The `ece` / `brier_score`
  / `paired_bootstrap_ci` input asserts are explicit `ValueError`s
  (non-empty, equal-length) that survive `python -O` and are validated
  before backend dispatch so both backends agree (D-11 extended;
  `docs/Methodology.md` updated). Manifest verification rejects file
  names containing `..`, separators, or absolute paths before touching
  the filesystem, and reads `manifest.json` exactly once - the digest
  sealed into the analysis lock is always the digest of the verified
  bytes (no verify-then-reread race). Schema error strings now use a
  fixed escaping rule implemented identically in both languages
  (`_safe_repr` / `py_repr`) instead of `repr()`, making them
  byte-identical for every input (new ADR D-13). The Rust analysis lock
  streams canonical bytes straight into SHA-256 (no more deep-clone of
  `config`/`results`), case files are read+hashed in one pass, and
  canonical output sorts object keys explicitly. The Rust CLI matches the
  Python CLI's `validate` summary text (`validated N cases, M invalid`),
  full-path `file:line` errors, exit codes, and `--dir=` form, and types
  manifest errors instead of string-matching them. New user-facing errors
  are catalogued in `docs/Troubleshooting.md`.
- Trust-boundary hardening (H5): `peira report` now formats every
  metric cell through a single `_num` formatter (floats render with four
  decimals, anything unexpected is escaped) and escapes the artifact
  version, analysis lock, and manifest digest - closing the
  stored-XSS-shaped hole H2 left in the metric cells (regression-tested
  with a hostile artifact). `peira validate` reports malformed JSON
  lines as exit-1 user errors with `file:line` instead of tracebacks;
  `peira report` exits 1 (not 2) on corrupt artifacts and unwritable
  `--out`. The schema validator now enforces the declared JSON types
  (`bad case_id: expected string`, `bad benign input: expected object`,
  …) on both backends with byte-identical messages. `validate_output`
  rejects non-string decisions and non-numeric confidences instead of
  mis-scoring or raising bare `TypeError`. Case files are read as UTF-8
  on every platform. The Rust core rejects case-file lines nesting
  deeper than 256 levels before parsing. The three
  `paired_bootstrap_ci` / `ece` / `mcnemar` edge divergences now fail
  loudly and identically on both backends (new ADR D-11). New
  user-facing errors are catalogued in `docs/Troubleshooting.md`.
- Trial-demo disposition (T3): `dataset/trial-demo` confirmed as the
  12-case offline quickstart fixture (gate-exempt, contents frozen for
  the quickstart). Stale "starter suite" / "lands at v1" wording swept
  from `AGENTS.md`, `docs/Troubleshooting.md`, `docs/Decisions.md`, and
  the dataset docstring; `dataset/README.md` now lists the branded
  Trial; D-8's "to revisit" note resolved - Trial runs stay off the
  leaderboard (below the hard 20-case ranking gate).
- Branded 100-case Peira Trial (T2): `dataset/trial` now holds 100
  v1-quality cases (10 per attack family; 14 critical / 40 high / 46
  medium) authored through the full pipeline - all six gates green,
  100% of critical cases human-reviewed, manifest sealed at 1.0.0
  (`peira dataset status` reports release-ready). The README quickstart
  gains a per-adapter-class cost/time table, and the two stale Trial
  claims are reworded (the Trial is here now; per-case drill-down in
  `peira report` is real).
- Authoring pipeline, third slice (T1c): `peira dataset status --dir
  <dir>` - one view of the generate → gate → review → manifest flow
  (per-gate results, review pending/coverage, manifest state). Exit 0
  means release-ready (no gate errors, no pending reviews, manifest
  verifies clean); anything else is exit 1. Documented in
  `docs/Dataset.md`, including the authoring loop.
- Public decision records: `docs/Decisions.md` now records the locked
  methodology decisions as ADRs (D-4 decision-change ASR with targeted
  success secondary; D-5 asymmetric malformed handling; D-6 hard
  per-family ranking gate with exit code 3 for unranked runs; D-7 100%
  human review of critical cases; D-8 trial suites stay off the
  leaderboard; D-9 benchmark before thresholds library; D-10 no vendor
  pre-briefs). Each names the alternatives considered and what would
  trigger a revisit.
- Docs link check: `scripts/check_doc_links.py` fails CI on dead
  internal links (new `docs` job), so the growing docs set can't rot
  silently.
- GitHub issue templates for bug reports and feature requests.
- Authoring pipeline, second slice (T1b): the release seal in
  `peira dataset build-manifest`. The build now refuses when
  `--version` isn't semver, when any critical-severity case lacks a
  severity justification in its notes (the rubric's "say why" rule), or
  when the dataset changed under an already-sealed version - bump the
  version instead (idempotent rebuilds are still fine). `peira dataset
  new` also prints the family's severity hint so authors grade against
  the rubric at authoring time. New errors documented in
  `docs/Troubleshooting.md`.
- Authoring pipeline, first slice (T1a): CI runs the dataset checks on
  every push - `peira dataset gates --dir dataset/trial` and
  `peira dataset verify-manifest --dir dataset/trial` on the committed
  Trial starter suite, plus conditional gates/manifest checks on
  `dataset/v1` once it has case files. This makes the documented claim
  true: manifests are committed to git and a mismatch is a build
  failure. `dataset/trial-demo/` stays exempt (gate-exempt scaffolding).
- Byte-proof dataset identity (H4): `peira run` verifies the suite
  manifest before scoring and seals the manifest's SHA-256 into the
  analysis lock, so an artifact proves the exact dataset bytes scored -
  not just the version label. A verification mismatch fails closed
  (nothing is scored), and `peira run --resume` refuses a partial run
  recorded against a different dataset snapshot. The Rust
  `RunArtifact`/`lock_payload` mirror the new sealed field, with
  regenerated parity fixtures.
- Rust `Case` now preserves unknown top-level keys in `extras`
  (`#[serde(flatten)]`), matching Python's `Case.extras`, with a
  Python-generated fixture pinning byte-identical canonical round-trips
  across both implementations.

### Fixed
- Report HTML: `peira report` now escapes author-controlled strings
  (case ids, family names, adapter name/version, suite and dataset
  labels) so a hostile case id lands inert in the HTML.
- Docs: consolidated the two overlapping severity rubrics
  (`docs/Severity-Rubric.md` + `docs/SeverityRubric.md`) into a single
  `docs/Severity-Rubric.md` - tiers, rules, template-author guidance,
  and the confidence-movement disambiguation in one place.
- Mock adapter flip behavior: on its seeded flip subset the mock now flips
  toward each case's own `target_decision` (injected into the attacked
  input by the runner) instead of hard-coding the approve/deny toggle,
  so targeted-attack-success is meaningful for arbitrary decision labels
  (A/B, advance/reject, flag/clear, …). The approve/deny toggle remains
  as the fallback for target-less synthetic inputs. Deterministic and
  bit-for-bit reproducible as before.

### Added
- Initial scaffold: Python SDK (`BaseAdapter`, case schema, runner,
  metrics, sealed run artifacts), `peira` CLI (`run`/`validate`/`report`),
  deterministic mock adapter, 12-case offline demo fixture.
- Rust workspace with `peira-core` skeleton (ports hot paths after the
  Phase 0 interface freeze).
- Docs: Methodology, Taxonomy, Threat-Model, Severity-Rubric, Concepts,
  FAQ, Troubleshooting, Glossary, Hardware, Compatibility, Contributing,
  Claims, Decisions.
- CI: Python + Rust tests, `public-surface` strategy-language check, README
  quickstart executed verbatim on Ubuntu/macOS/Windows.
- Optional Rust accelerator: `crates/peira-python` exposes the Rust core to
  Python as the `peira._core` PyO3 extension (built with
  `scripts/build_core_ext.py`). The scoring hot paths in `peira.metrics`
  and `peira.schema` dispatch to it when importable and fall back to the
  pure-Python reference otherwise, so `pip install peira` still needs no
  Rust toolchain. Backend parity is pinned by
  `tests/test_rust_backend.py`; the `test-python-rust` CI job builds the
  extension and runs the Python suite against both backends.
- Trial-suite mechanism: `dataset/trial/` starter suite (20 scaffolding
  cases, 2 per family, all six gates green, manifest `0.1.0-trial`) wired
  to `peira run --suite trial`. Case schema is now forward-compatible:
  validators ignore unknown top-level fields and `Case.from_dict`
  preserves them on `Case.extras`, so future per-case configuration needs
  no pipeline refactoring. `peira run` records the suite's manifest
  dataset version in the artifact (part of the analysis lock); `peira
  report` gains a per-case results table for drilling into flips.
