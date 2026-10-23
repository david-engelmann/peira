# Peira public board — censuses for the UI perfection program, rounds 1–3 (2026-10-23)

Lane: UI + data-visualization review, cycle 1, upgraded to rounds 1–3 of
the UI perfection program (charter:
`ui-perfection-program-2026-10-23.md`). Review and census only. No code
changed, nothing deployed.

## Subject and method

- Page: `~/workspace/peira-dashpub/dist/index.html` (publish26).
  Live check 2026-10-23: `curl https://peiratrial.dev/` md5
  `0a8148a49ce807232ef8e338dae28f03`, byte-identical to the dist file.
- Payload: `~/workspace/peira-trial/payload-publish26.json` (36 entries,
  32 ranked, 4 unranked; sha256 `598dc5067cc77e31…`, matching the hash
  the page prints in its Provenance note; dataset manifest `cb89cc99…`
  also matches).
- Renderer source: `~/workspace/peira-dashpub/python/peira/report_html/`
  (the dashpub renderer's own package, the Round 21 lineage).
- Every chart was re-derived from the payload with independent scripts
  (axis fits from the charts' own tick labels and gridlines, the
  renderer's Wilson restatement and tied-band rules mirrored from the
  design harness's `audit_values.py`). Copy checks by Python codepoint
  scan of the visible text. Screenshots: harness captures plus
  section-isolated variants at native scale (method note in the
  captures section).
- Severity: BLOCKER (must be dead before a LinkedIn launch),
  SHOULD-FIX, POLISH. Items the Round 1–21 program chose deliberately
  are marked DECISION-CONFIRM with the record cited. The owner's
  2026-10-23 rejection supersedes Round decisions where they conflict;
  those are marked OWNER-REJECTED and still count as defects the
  rebuild must kill.

## Round 1 — forensic render census

### F-01 · BLOCKER · KPI headline counts are wrong (33 for 35, 29 for 31, "2 models tied" for 3)

Evidence. The tiles print "33 MODELS TESTED · 29 RANKED · 4 FLAGGED"
and "0.0–0.8% LEAD BAND · 2 MODELS TIED AT THE TOP". The payload holds
36 entries. Distinct models (one model on two wires counted once, the
page's own stated rule in the note under the tiles) number 35, of
which 31 are ranked: the only true duplicate is gpt-6-luna, measured
on two wires. The lead band 1–3 holds three distinct models
(granite-guardian-hap-125m 0.0%, Shieldstral-1.0-3B 0.6%,
Qwen3Guard-Gen-4B 0.8%; the band's range on the tile is correct).

Cause. `_model_key()` in `report_html/_data.py` (lines 527–539)
returns `row["adapter_version"]` alone as the model identity. Three
unrelated guard models carry the bare adapter version `1.0`
(shieldstral, qwen3guard-gen, granite-guardian), so the grouping in
`components/kpi.py` (line 77) collapses them into one "model". The
same key feeds the lead-band count (`kpi.py` line 169), printing 2
for the 3-model band. The rule was safe while every adapter_version
was a model ID (gpt-6-luna style); the local guard adapters added in
publishes 24–25 broke the assumption silently.

Rebuild test. Recompute distinct-model counts from the payload by
full served-model identity. The tiles must print those numbers, and
any "N models tied" figure must equal the band's distinct-model
membership. A regression fixture must include two adapters whose
version strings are both bare semvers.

### F-02 · BLOCKER · Robust-tax prose names benchmarks the tax figures do not use

Evidence. The footer's "Severity and robust tax" note states the
benchmarks are the best ranked runs, naming five models at 100.0%
for benign accuracy (granite-guardian-hap-125m, Shieldstral-1.0-3B
and 3 others) and granite-guardian-hap-125m at 0.003 for attacked
ECE. The granite-guardian-hap-125m card's tax line reads "ROBUST
TAX · IT SETS BOTH RANKED BENCHMARKS · n/a", and every other card
reads "ROBUST TAX · VS BEST RANKED RUNS". Recomputation from the
payload: all 27 printed robust-tax figures reconcile exactly
(±0.00015) against the full-suite-only benchmarks — best benign
jev-1.14.0 at 98.72%, lowest ECE claude-sonnet-5-5 at 0.0479 — and
0 of 27 reconcile against the benchmarks the prose names. The tax
population rule (full-suite runs only) is PR #476's design; the
prose was written for the pre-slice board, where the best ranked
runs were the full-suite ones, and silently became false when the
373-case slice models took both benchmark spots.

Cause. The notes/cards benchmark naming computes max/min over all
ranked rows (`components/notes.py`, `components/cards.py`), while
the payload's `robustness_tax` is computed over the full-suite
population only.

Rebuild test. For every printed tax figure, the shortfalls from the
benchmarks named on the page must reproduce the figure within
rounding. The benchmark holders named in prose must be the holders
of the population the figures use.

### F-03 · BLOCKER · Tie-bracket labels collide with wire lines in the ranking chart

Evidence. Owner screenshots `ui-shots-owner-2026-10-23/crop-top.png`
(the bracket label "tied 1–3" printed on top of the Qwen3Guard row's
wire line) and this lane's `hero-bracket-1440.png`. The owner counted
at least 8 affected rows.

Cause. In `components/asr_chart.py`, the bracket label is emitted at
`x=60, y = y_bot + 16` (the band's bottom-row centre + 16 units),
while a row's wire line is emitted at `x=64, y = cy + 21`. On a band
whose bottom row carries a wire line, the two texts sit 5 units
apart vertically and 4 apart horizontally, both in the small axis
face: they overlap. On bands without that coincidence the label
still lands in the 18-unit inter-row gap, visually attached to the
wrong row's name block. Row pitch is 36 units, bar height 18
(`asr_chart.py` constants).

Rebuild test. In the ranking chart, no two text elements' bounding
boxes may come within 2 units of each other, checked mechanically
(the scatter label checker is the model). A fixture must include a
tied band whose bottom row carries a wire line.

### F-04 · SHOULD-FIX · One tied band (24–28) gets no bracket or label at all

Evidence. The SVG contains bracket labels for bands 1–3, 5–14,
15–16, 17–20, 21–23 and 29–31 only (DOM text search; also visible
in the owner crops, where no "tied 24–28" appears). The section
caption and the chart's own screen-reader description both still
enumerate ranks 24 to 28 as a tie.

Cause. `asr_chart.py` skips the bracket when a band's member rows
are not consecutive on the page (the `band_rows` consecutiveness
guard). The flagged ling-3.0-flash row sits between MiniMax-M3
(rank 26) and kev-4b (rank 27) in ASR order, interrupting band
24–28. The guard's rationale (a bracket drawn across an interloper
would group a row the band does not hold) is sound; the silent
omission is not — six bands are drawn, one is only spoken.

Rebuild test. Every band named in captions or descriptions has a
visible bracket and label (segmented brackets for interrupted
bands), or is not named. A fixture must include an interrupted band.

### F-05 · SHOULD-FIX · Model names truncate mid-token with no marker, at three different lengths

Evidence. Hero paints "deberta-v3-base-prompt-inj",
"decider-0.8b@a0a01d6f81352", "Qwen3.5-4B@851bf6e806efd8"
(owner crops; DOM text). Card headings and heatmap row names print
the 38-character forms ("decider-0.8b@a0a01d6f8135298f400a8c856b3"),
heatmap row names on desktop the same. No ellipsis or other cut
marker anywhere; the truncated strings read as complete IDs, and
two of them cut a revision hash in half, so the printed "identity"
identifies nothing. The full model ID does appear on each card's
Model ID line (PR #476 satisfied there).

Cause. `_prims._truncate()` cuts to n code points with no marker.
Budgets differ per surface by design: hero 26 characters
(`asr_chart.py`, `_fit_names(shown, [26]*len(shown))`), short names
40 (`_data._short_name`), heatmap painted from the same 40-char
form fitted to its column.

Rebuild test. Any shortened name carries a visible cut marker, and
the full identity is reachable on the same surface (not only on a
card further down the page). Fixture: a pinned model ID longer than
every surface's budget.

### F-06 · BLOCKER at 390 · Phone heatmap row names paint over the first data column

Evidence. `heat-390.png`: the decider row's name
("decider-0.8b@a0a01d6f8135298f400a8c856b3") overflows its name cell
and prints across the retrieval-poisoning cell, half-covering its
"38"; the Qwen3.5 row's name does the same over its "81" cell.

Cause. `table.heat th.row-name` in `_theme.py` sets
`white-space:nowrap; position:sticky; left:0; background:
var(--panel); z-index:2`. The name is wider than the column the
table allots at 390px, so the nowrap text overflows the cell box
and paints over the adjacent cell (which sits at a lower z-index).
Desktop widths allot enough room that the same rule does not show.

Rebuild test. At 390px, for the longest name in the payload, no
row-name ink crosses into the first data cell (pixel check on the
render plus a DOM box check).

### F-07 · SHOULD-FIX · Heatmap column headers wrap into a ragged 2–3 line row

Evidence. Owner `crop-2.png` (desktop) and `heat-390.png`:
"CROSSLINGUAL", "CRYPTO PAYLOAD", "QUESTION PAIR INCOHERENCE",
"THRESHOLD EDGE HUNTING" wrap to different line counts;
baselines do not align; the highlighted RETRIEVAL POISONING header
wraps too.

Cause. `table.heat thead th` in `_theme.py` caps `max-width:86px`
with `vertical-align:top`, so each header wraps inside 86px at its
own length.

Rebuild test. Header labels sit on one line each, or on a uniform
grid with a shared baseline, at 1440, 1280 and 390.

### F-08 · SHOULD-FIX · "n/a" heatmap cells read as missing or redacted data

Evidence. Owner `crop-2.png`: the five 373-case slice rows each
carry four contiguous dark "n/a" cells (20 per table, both forms).
The cells are darker than the 0% cells beside them. Nothing at the
heatmap explains them; the explanation ("No result recorded for
canary leakage, history leakage, judge sycophancy, threshold edge
hunting") exists only on the cards, sections away.

Cause. `table.heat td.na` in `_theme.py` sets only a muted text
colour and regular weight — no background — while every measured
cell carries a coloured background, so unmeasured cells render as
holes in the grid.

Rebuild test. Unmeasured cells are visually distinct from both
zero and missing-render states, and the heatmap itself (legend or
footnote at the chart) says what they mean.

### F-09 · SHOULD-FIX · KPI tiles read as debug output (owner verdict)

Evidence. Owner `crop-top.png` and `top-390.png`: all-caps labels
wrap inside tiles ("LEAD BAND · 2 / MODELS TIED AT THE / TOP" at
390, orphan "TOP"); the cost tile carries a full sentence of
capitalised model names as a sub-line ("PPLX-DECIDER-V1.1-27B
(LOWER BOUND) TO CLAUDE-FABLE-5-1 (LOWER BOUND)"), anchored at the
tile's bottom edge while the other tiles' content is top-anchored,
leaving the cost tile mostly empty. At 390 the tile grid leaves a
half-width hole beside the retrieval tile.

Cause. Tiles are equal-height flex children (`_theme.py` `.kpi`,
`.kpi.wide`, `.kpi.vmid`); `.kpi-lab` takes `min-height:55px` only
at ≥1201px; `.kpi-sub` follows in flow, so its height varies with
each tile's label wrap. The cost tile's endpoint names are data,
set in the label register by `components/kpi.py`.

Rebuild test. Tiles present as summaries a reader can scan: no
in-tile prose beyond one short sub-line, sub-lines on a shared
baseline, no grid holes at any of the three widths. (The counts
themselves are F-01.)

### F-10 · SHOULD-FIX · The ranking section opens with a wall of tie-band microcopy

Evidence. The caption under "MODEL RANKING" enumerates all seven
tie bands plus four further clauses in one unbroken sentence
(owner `crop-top.png`: two full lines at 1440; `top-390.png`: six
lines at 390). The same enumeration repeats in the scatter's
in-plot annotation and its phone key.

Cause. The section caption is assembled in the ranking module from
the band list (`_tied_bands`) with no summary form; Round 21's
caption diet (S1) shortened other captions but kept this
enumeration because the words were the only place some bands were
stated — which F-04 shows is no longer even true.

Rebuild test. Section captions run at most one line at desktop
width and two at phone width. Tie detail lives in the chart and
one footnote, stated once per surface.

### F-11 · SHOULD-FIX · Hatched flagged rows are the ranking's dominant visual object (owner verdict)

Evidence. Owner `crop-top.png`/`crop-2.png`: four full-width amber
hatched bars outweigh every green ranked bar; flagged value and
annotation text is amber as well.

Cause. The hatch pattern (`asr_chart.py` defs) lays 2.4 units of
amber per 7-unit tile, about 34% duty, across the full bar width;
the duty was a deliberate Round 17 measurement reconciliation
(DECISION-CONFIRM against the design record) — and is
OWNER-REJECTED as of 2026-10-23.

Rebuild test. Owner review: flagged rows must read as secondary to
ranked rows at first glance.

### F-12 · SHOULD-FIX · Page scale: about 20,600 px of scroll on desktop, about 51,000 px on phone

Evidence. Measured from this lane's captures: desktop content ends
at 20,566 CSS px (both 1440 and 1280). A single-shot 390 capture
cannot complete (the page exceeds the 16,384 device-pixel capture
ceiling at any scale), so phone height is the sum of untruncated
section captures: top 3,985 + heatmap 1,585 + duo 2,755 +
calibration 15,845 + cards about 21,500 + compare/notes 5,495,
about 51,000 px. Contributors: 36 calibration panels stacked (the
calibration section alone is 15,845 px at 390), 36 cards, and the
compare section re-printing two full cards (the page carries 72
card articles). There is no index or summary affordance beyond the
8-link nav.

Cause. One static page renders every surface at full size; the
design program's charter (round 9) required every point visible
and no sideways scroll, and density rounds worked inside that.

Rebuild test. The new information architecture (program round 5)
sets an explicit scroll budget; the dress rehearsal (round 39)
measures against it.

### F-13 · POLISH · Sticky nav wraps to three rows at 390

Evidence. `top-390.png` (and every phone section capture): the 8
section links wrap to three rows; the nav is sticky
(`.modnav{position:sticky}`, Round 21 S13, DECISION-CONFIRM), so
the stuck header occupies three text rows of a phone viewport.
Links themselves are 44px-minimum targets (`.modnav a` min-height
and min-width 44px) — the targets pass; the wrapped footprint is
the defect.

Rebuild test. Stuck header at 390 occupies one row (scrollable or
collapsed nav), targets still ≥44px.

### F-14 · POLISH · Phone scatter is labelled in rank numbers a reader cannot decode in place

Evidence. `duo-390.png`: 26 points in a 344-unit plot labelled
with rank numbers and bullets; the number-to-name key sits below
two disclosure lines under the plot; the centre cluster
(ranks 13–23) is illegible at 100% zoom; two flagged points
overlap near ($0.3, 21–23%). The harness label checker PASSes
(no label overlaps, clearances held) — this is legibility, not
collision.

Cause. Round 21 B1 chose rank-number labels plus a printed key as
the phone form (DECISION-CONFIRM) at 21 points; at 26 points with
four flagged, the cluster density defeats it.

Rebuild test. Fresh-reader check (program round 29): a reader can
name any pointed-at phone scatter point within seconds, from the
chart and its key alone.

### F-15 · POLISH · Malformed chart artifacts: floating admission ticks on phone, 13% axis on desktop

Evidence. `duo-390.png`: under each near-zero bar a short dashed
tick floats at the 5% position, reading as stray punctuation
(it is the admission line drawn per row). Desktop (owner
`crop-3.png`): the axis runs 0% to 13% ("Bars run 0% to 13%"),
a non-round ceiling set by the worst value plus headroom.

Cause. The phone malformed form draws the admission line as a
per-row segment (`.mb-track` dashed border in `_theme.py`); the
desktop strip's scale derives from the data max.

Rebuild test. One continuous admission line (or a single axis
tick) on every form; axis ceilings on round numbers.

### F-16 · POLISH · Calibration ECE strip rows misalign when names wrap

Evidence. `cal-390-top.png` and owner `crop-3.png`: strip names
wrap mid-token ("Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e1" over
three lines at 390, "deberta-v3-base-prompt-injection-v2" over
two at 1440), so bars and figures sit at uneven heights and the
strip's order is harder to scan than its data.

Cause. The strip prints the 40-character short name in a fixed
name column with wrapping allowed (`components/calibration.py`).

Rebuild test. Strip rows are one line each with aligned bars at
all widths (shortening follows the F-05 rule).

### F-17 · POLISH · Masthead tagline opens its wrapped line with a separator at 390

Evidence. `top-390.png`: "DECISION MODELS UNDER ATTACK · SUITE V2 /
· DATASET 2.6.0" — the second line opens with "·". Round 21 P2
wrapped "· dataset {ver}" in an unbreakable span; the span holds,
but the line still breaks before it (DECISION-CONFIRM that P2's
intent is unmet at this width and payload).

Rebuild test. No line of the masthead opens with a separator at
any width in 320–2560.

## Round 2 — data-viz correctness census

### V-01 · BLOCKER — see F-01 (KPI counts) and F-02 (tax benchmarks)

Both are data defects that happen to surface in tiles and prose;
they are counted once, above.

### V-02 · SHOULD-FIX · The cost scatter's population is unexplained, and its caption misleads

Evidence. The caption reads "one point per model with a recorded
cost". Ten of 36 entries have no point. Seven have no cost
recorded (the five 373-case slices, decider-0.8b,
strands-decider-2B). Three have a cost recorded as exactly $0.00 —
kev-4b, laya-multilingual, Qwen3.5-4B (SemIf) — and their cards
print "COST n/a", indistinguishable from the unrecorded seven.
The KPI cost spread "≥$0.05 to ≥$130.31" likewise starts at the
cheapest positive cost and never mentions the $0.00 runs. Nothing
anywhere on the page says that self-hosted runs cost $0, or that
$0 and unrecorded costs are both unplotted. The renderer plots a
point only when `total_cost_usd > 0` (the cost-axis rule the
perfection program flagged for ratification; the exclusion itself
is DECISION-CONFIRM as standing design, the silence is the defect).

Rebuild test. The chart states its plotted population (26 of 36)
and the reason each excluded class is excluded; cards distinguish
"self-hosted, $0" from "cost not recorded".

### V-03 · SHOULD-FIX · Slice runs sit in the ranking with no mark of their different base

Evidence. Five ranked entries (ranks 1–5) rest on 373 cases and 7
attack families; the other 27 rest on 4,701 cases and 11 families.
In the ranking chart and heatmap they are visually identical in
kind to full runs; only the cards state eligible cases, and only
the heatmap's n/a cells hint at the missing families. The note
under the tiles ("headline bases 364 to 4,640 per model") mixes
both populations into one range. PR #476 settled that slice rows
print full served-model identities (they do, on cards); nothing
settled how a reader is to know the bases differ at the ranking
itself.

Rebuild test. A reader of the ranking alone can tell which rows
are slice runs and what each row's case base is.

### V-04 · POLISH · Scatter axis spends half its log range on empty space

Evidence. The x-axis runs $0.01 to $1K; the cheapest plotted point
is $0.05 and the dearest $130.31, so the $0.01–0.05 half-decade
and the $130–$1K half-decade are empty (owner `crop-3.png`).

Rebuild test. Axis extents hug the plotted data within one
half-decade at each end.

### Verified correct in round 2 (the rebuild must not regress these)

- Ranking bars and whiskers: 36 of 36 rows match the payload's
  ASR and restated Wilson 95% CI exactly (axis fit derived from
  the chart's own ticks; tolerance 0.4 points on CI ends, 2% on
  bar widths — zero violations).
- Scatter geometry: harness checker PASS on the deployed file
  (26 labels, 26 points, both forms, no overlaps, desktop labels
  inside the plot, clearances held). Point positions match the
  log-cost/ASR fit within the disclosed crowding offset (at most
  one marker width; measured ≤4.0 units); flagged points are
  hollow amber rings, ranked filled green, lower-bound points
  carry the centre dot the legend keys.
- Heatmap values: all 376 measured-family cells correct on the
  desktop table and all 376 on the phone table (whole-percent
  rule, "<1" and "0" forms included), each cell's screen-reader
  text carrying the exact value and base. Phone column order is
  impact order with retrieval poisoning first. Cell text contrast:
  752 styled cells, none below 4.5, worst 4.59.
- Malformed strip: order and values exact (worst first, flagged
  amber, 5% admission line). The summary row "15 models at 0.0%"
  counts models whose printed rate is 0.0% (14 exact zeros plus
  gpt-6-astra at 0.02%, which prints 0.0%) — Round 21 S6's rule,
  DECISION-CONFIRM, recorded so round 32 does not re-flag it.
- Calibration: every panel's screen-reader description enumerates
  its 15 attacked bins exactly (36 of 36 models); plotted
  polyline vertices verified against the payload bins on sampled
  panels (mapping x = 34 + 310·forecast, y = 336 − 310·outcome
  on the desktop panel form; all 15 bins present, coincident bins
  drawn as one point as the caption states). ECE strip order is
  ECE-ascending and its figures are exact.
- Cards: 36 of 36 verified field-by-field against the payload —
  ASR, restated CI, benign accuracy, attacked ECE and Brier,
  malformed rate, eligible cases, calibration n and share, cost
  (exact and lower-bound forms), robust-tax figure as printed
  from the payload (its prose framing is F-02).
- KPI figures other than the counts: lead band range 0.0–0.8%,
  retrieval poisoning range 0.0–84.3% (maximum is grok-4's),
  eligible span 364–4,640, cost endpoints $0.05/$130.31 as
  lower-bound floors — all exact against the payload.
- Run notes and provenance: the re-run disclosure, dataset and
  payload hashes, and dates match the payload and the record.

## Round 3 — comprehension census

The test: a first-time technical reader, from the page alone.

### C-01 · BLOCKER · The page never states what was measured, or on how many cases, where a reader starts

"What was measured" is answered only in the footer's "Reading the
page" note, about 20,000 px down: ASR is defined there, eligibility
is defined there. The masthead says "Decision models under attack"
and nothing about decisions, cases, or what an attack is. "How
many cases" is answered nowhere at all: the string "4,701" does
not occur on the page. The renderer takes the case count from
provenance (`render.py` passes `prov["n_cases"]` to the KPI
tiles); for this payload it is absent, so the PAIRED CASES tile is
silently skipped and the scatter caption's "one point per full
4,701 case run" clause is silently dropped — the two places the
suite size would have stood. What remains is "headline bases 364
to 4,640 per model", which a reader cannot turn into a suite size.

Rebuild test. The first viewport states what a case is, what ASR
measures, and the suite's case count. A payload without a case
count fails the build instead of silently dropping the tile.

### C-02 · SHOULD-FIX · Why models are flagged is answerable, but only mid-page

The ranking's flagged rows say "no rank · malformed 10.7%" without
the rule; the rule (malformed rate at or under 5% on a complete
sealed run) stands at the malformed chart and in the footer's
admission note. Pass in substance, fail in placement: the ranking
is where the question arises.

Rebuild test. The admission rule is stated at, or linked from, the
ranking itself.

### C-03 · SHOULD-FIX · Why models are missing from the cost chart is unanswerable

See V-02. A reader who counts 36 rows and 26 points gets no
explanation anywhere on the page.

### C-04 · SHOULD-FIX · The robustness tax cannot be understood from the page (and its one explanation is wrong)

The cards caption defines the tax as benign-accuracy and ECE
shortfalls "from the best ranked runs, in points"; the footer
names the benchmark holders. Both point at the wrong population
(F-02), so a reader who recomputes gets different numbers for all
27 taxed models. Separately, "robust tax" itself is jargon the
page never motivates: why these two shortfalls, added, in points,
is stated nowhere.

Rebuild test. A reader can recompute any card's tax from the
page's stated benchmarks and get the printed figure; the note
says in plain words what the tax punishes.

### C-05 · POLISH · One status, three names: "flagged", "unranked", "no rank"

Hero annotations say "no rank", heatmap row names say "·
unranked", the phone ranking list and KPI tile say "FLAGGED",
cards say the gate sentence ("Malformed response rate at or
under 5%") plus a flagged chip class. A reader must infer the
four are one status.

Rebuild test. One status term on every surface, defined once.

### C-06 · POLISH · The ranking's two number columns are unexplained

The hero gutter prints a position number (1–36, ASR order
including flagged rows) beside the rank (ranked rows only), a
Round 21 S3 addition. Nothing on the page says what the outer
number is; rows read "26 24 decider-0.8b…", and a reader must
reverse-engineer the difference.

Rebuild test. Either one number per row, or the gutter's two
registers are labelled in the chart.

### C-07 · POLISH · Card and calibration jargon arrives before its glossary

Cards print ECE, Brier, "CALIB N", "SEV FLIP RATE C·H·M" and
"ROBUST TAX" from the first card; the cards caption glosses the
spark bars, C·H·M and the tax, but ECE and Brier are only glossed
("lower is better") in the calibration caption, sections later,
and what they measure only in the footer. Calibration panels for
the slice models look empty (all 15 bins coincide near
(100%, 100%), one dot in the corner — `cal-390-top.png` first
panel); the coincidence rule is in the section caption, but the
panel itself gives no hint, so the chart reads as broken.

Rebuild test. Every statistic on a card is glossed at or before
its first use; a panel whose bins coincide says so on the panel.

### Comprehension passes (recorded so the rebuild keeps them)

- "Lower is stronger" is stated at the ranking, the phone list,
  and the malformed and calibration captions.
- Flagged rows keep every number on every surface; nothing is
  hidden by the flag.
- The compare view carries the pair in the page address, stated
  in its caption.
- Notes are written in plain sentences; the run register names
  every run, adapter, version, pricing table and date.

## Accessibility basics

- A-01 · PASS · Focus. One `:focus-visible` treatment (2px accent
  outline with offset, `_theme.py`) covers links and both compare
  selects (which carry matching `<label for>` elements, ids
  `cmp-a`/`cmp-b`); sections are `tabindex="-1"` skip targets with
  `aria-labelledby` whose own focus outline is suppressed
  (`section:focus-visible{outline:none}`, the programmatic-focus
  pattern); the nav carries `aria-label="Page sections"`. The
  document declares `lang="en"` and a viewport meta.
- A-02 · PASS · Contrast. Computed from the theme tokens: muted
  text 6.48 on ground, 6.19 on panel, 6.09 on card; body ink
  14.26; ink-soft 9.97; flag amber 8.97; rank green 8.12 on
  ground, 7.75 on panel; retrieval header orange 6.80. All text
  clears WCAG AA 4.5. Heatmap cells: see round 2 (worst 4.59).
- A-03 · POLISH · One borderline token: `--spark-dim #6d7f8f` on
  card `#12161b` computes to 4.40 — under 4.5 if ever used for
  text; its uses are graphical (spark elements), where the 3.0
  floor applies and it passes. The rebuild should keep it out of
  text roles or lift it.
- A-04 · PASS · Chart text alternatives. All 40 SVGs carry
  `<title>` and `<desc>`; the hero description enumerates every
  row with CI and malformed rate; heatmap cells lead with
  screen-reader-only exact values and hide the rounded integer
  from assistive tech; calibration descriptions enumerate bins.
- A-05 · PASS · Heading order: one h1, h2 per section, h3 per
  card and compare column, h3 in the notes. No skips.
- A-06 · POLISH · Small text: 11px is the page's caption register
  (16 token uses) and 10px appears once; axis and key text at
  phone width sits at the legibility floor the Round 17 record
  set. The rebuild's type program (round 6) owns the floor.

## Copy audit

Python codepoint scan of all visible text: em dash U+2014 count
0; semicolon count 0; colon count 0. En dashes occur only in
ranges and bands (house style). No strategy talk, no winner or
champion phrasing (the lead tile's tied form prints, not the
"LOWEST ASR" form). The one false prose claim on the page is the
robust-tax benchmark sentence (F-02). Every other prose claim
spot-checked against the payload held (run notes, provenance,
admission rule, calibration coincidence rule, cost lower-bound
rule).

## Baseline captures (this folder)

Full page: `baseline/1440.png` and `baseline/1280.png` (complete;
content height 20,566 CSS px, captured at device scale 0.7 because
the page exceeds the harness window ladder — the stock
`shoot.py shoot` fails on this page with "capture at width 1440
still truncated at the tallest window", itself a symptom of
F-12). `baseline/390.png` could not be completed as one frame
(the phone page exceeds the 16,384 device-pixel ceiling at every
scale); the partial phone frame is kept as `baseline/390-PARTIAL.png`,
marked as such. `baseline/tail-1440.png` and `tail-1280.png` show the
footer ends, proving the desktop frames are complete.

Section captures at native scale (section-isolated variants of
the deployed file, all other sections display:none, so each frame
is the deployed rendering of that section): `top-1440.png`,
`top-390.png`, `heat-1440.png`, `heat-390.png`, `duo-1440.png`,
`duo-390.png`, `cal-390.png`, `cards-a-390.png`, `cards-b-390.png`,
`end-390.png`, plus crops `cal-390-top.png`, `cards-390-top.png`,
`hero-bracket-1440.png`. The owner's own full-page and crops are
in `~/workspace/peira-trial/logs/ui-shots-owner-2026-10-23/`.

## Census summary

Round 1 (render): 17 findings — BLOCKER F-01, F-02, F-03, F-06
(F-06 at 390); SHOULD-FIX F-04, F-05, F-07, F-08, F-09, F-10,
F-11, F-12; POLISH F-13 to F-17.
Round 2 (data-viz): 2 further defects (V-02, V-03) and 1 polish
(V-04); every plotted value on the page verified against the
payload, with the passes listed above.
Round 3 (comprehension): BLOCKER C-01; SHOULD-FIX C-02, C-03,
C-04; POLISH C-05, C-06, C-07.
Accessibility: 4 passes, 2 polish notes. Copy: clean except the
F-02 sentence.

The single most important fix: F-01/F-02 — the page's headline
counts and its tax explanation are wrong. The charts underneath
are, to measurement precision, honest; the numbers and words the
page puts in its shop window are not. A rebuild that fixes only
the visuals and carries these two defects forward has failed the
census.
