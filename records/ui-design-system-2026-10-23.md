# Peira UI design system and information architecture, rounds 5 to 7

Produced 2026-10-23 by the design system lane of the UI perfection
program (charter: ui-perfection-program-2026-10-23.md). Stack-agnostic.
Everything here is specified as components, tokens, and chart specs so
the build rounds can implement it in whichever framework round 4 picks.

Sources read first-hand for this document: the live render
(~/workspace/peira-dashpub/dist/index.html, publish26), the payload it
renders (~/workspace/peira-trial/payload-publish26.json), the owner's
screenshots (~/workspace/peira-trial/logs/ui-shots-owner-2026-10-23/),
the old design charter (files/dashboard-design-refinement-program.md),
and the Round 21 record (peira-dashdesign/design-harness/shots/
round21/RECORD.md). The old program's art direction is treated as
history. What survives below is only what can be argued from the
reader's task.

## 0. Facts the design must fit

These come from the payload, counted directly. No design below may
contradict them, and no printed number may change.

- 36 result rows. 32 ranked, 4 flagged with no rank. The flagged four
  share one reason, a malformed response rate above the 5 percent
  admission limit.
- Two populations share the board. 31 rows ran the full suite of
  4,701 cases. 5 rows are guardrail slices that ran a 373 case abstain
  subset. The slices hold ranks 1 to 5 today, and their attack success
  rates (0.0 to 9.1 percent) are not measured on the same base as the
  full suite rows (10.7 to 28.5 percent ranked). Any layout that lets a
  reader compare a slice rate against a full suite rate without seeing
  the population difference has failed, however pretty it looks.
- Ties are the norm, not the exception. Overlapping 95 percent
  intervals group the 32 ranked rows into bands of 3, 10, 2, 4, 3, 5,
  and 3, with single rows at ranks 4 and 32. Ten of the top fourteen
  rows sit in one band.
- Names are hostile. Display names run to 46 characters and two carry a
  full revision hash inside the name itself (the Qwen3.5-4B SemIf row
  ends in a 40 character hash). One model appears twice under two wires
  (gpt-6-luna on the Decisions API and on chat completions) with
  different numbers. Several rows share an organisation prefix that
  carries no ranking information.
- Cost is missing in three different ways. 26 rows carry a recorded
  cost above zero. 3 rows record exactly 0.0 because they were served
  locally. 7 rows carry no cost at all, including 2 ranked full suite
  rows (Decider 0.8B and Strands Decider 2B). Some recorded costs are
  lower bounds where a call went unpriced.
- Robustness tax exists only for the 27 ranked full suite rows. It is
  absent on slices and flagged rows, and it is computed against the
  best full suite benign accuracy and the best full suite attacked
  ECE. The current page's notes name slice rows as the benchmark
  setters, which contradicts the tax values themselves. The build
  rounds must take benchmark names from the same computation that
  produces the tax, and the data audit lane owns the correction. The
  design rule is stated in section 4.5 and needs no number from this
  document.
- Every row carries a detail block with 11 attack families (full
  suite) or 7 (slices), 3 severity bands, and a calibration block with
  15 reliability bins per arm. Slices never carry the canary leakage,
  history leakage, judge sycophancy, or threshold edge hunting
  families. Those cells are unmeasured, not zero.

### The name policy (binding on every component)

Most current defects trace back to names, so the policy is fixed here
once and referenced by every chart spec.

1. Primary label. The short name, derived from the payload display
   name by dropping the organisation prefix and moving any revision
   hash out of the label. Examples: ibm-granite/granite-guardian-
   hap-125m becomes granite-guardian-hap-125m. Qwen/Qwen3.5-4B@851bf…
   becomes Qwen3.5-4B, and the hash moves to the model card and the
   run register, where it belongs.
2. Duplicate short names are disambiguated by a wire line in plain
   words under the name, never by a bracketed counter. gpt-6-luna (1)
   and gpt-6-luna (2) become gpt-6-luna with the wire lines Decisions
   API and Chat completions.
3. The full display name appears exactly twice per model, on its
   detail card and in the run register. It never appears in a chart,
   a tile, a picker, or a table.
4. Labels never truncate. If a short name cannot fit its column at a
   given width, the row moves to a two-line layout. Clipping a name
   mid-word or mid-hash is a build failure at any width, including
   320 px.
5. Hashes never appear in chart labels, at any width, under any
   density pressure. Density problems are solved with layout, not by
   borrowing the hash's space or by cutting it in half.

## 1. Content inventory

Every fact and dataset the page must present, the payload field it
comes from, and the reader question it answers. Placement refers to
the architecture in section 2.

### 1.1 The headline counts

- Content: 36 results, 33 distinct models, 29 ranked models, 4
  flagged results, dataset 2.6.0, suite v2.
- Source: payload counts plus the distinct model counting rule.
- Reader question: how much evidence is behind this page, and how
  much of it earned a rank?
- Placement: masthead findings strip (section 2, position 2).

### 1.2 The headline finding

- Content: on the full suite, attack success runs from 10.7 to
  28.5 percent across ranked rows, and the nine leading full suite
  results overlap into a single tie band. Retrieval poisoning is the
  strongest attack family on the board, reaching 84 percent against
  the worst full suite rows.
- Source: ranked full suite rows and the family matrix.
- Reader question: what is the one thing I should take away before I
  look at any chart?
- Placement: masthead, set as prose, not as tiles.

### 1.3 Per-row headline metrics

- Content per row: rank or flagged status, attack success rate with
  its 95 percent interval, benign accuracy, malformed rate, attacked
  ECE, robustness tax where it exists, recorded cost or its absence
  state, eligible case count, and case base (4,701 or 373).
- Source: row fields asr_conditional, asr_ci95, benign_accuracy,
  malformed_rate, ece_attacked, robustness_tax, total_cost_usd,
  n_eligible, n_cases.
- Reader question: where does this model stand, and how sure are we?
- Placement: ranking (all rows), detail card (one row, full set),
  compare (two rows).

### 1.4 Tie bands

- Content: the band membership of every ranked row, derived from
  interval overlap.
- Reader question: is rank 7 actually better than rank 13, or are
  they indistinguishable on this evidence?
- Placement: drawn on the ranking as brackets (section 4.1). Stated
  once in prose under the ranking heading. Nowhere else.

### 1.5 The attack family matrix

- Content: for each model and each of the 11 families, the family
  attack success rate with interval, eligible base (400 to 470 on the
  full suite, 41 to 60 on slices), flips, and flip direction. Plus
  confidence histograms per family and arm, which the current page
  does not display.
- Source: detail.families.
- Reader question: where is each model weak, and is the weakness
  shared or specific?
- Placement: heatmap (rates), detail card spark bars (one model),
  compare (two models). Histograms stay undisplayed in this design.
  They are the weakest reader value per pixel in the payload, and the
  calibration section already covers confidence behaviour. Recorded
  here so the omission is a decision, not an oversight.

### 1.6 Severity flips

- Content: flip rate with interval at critical, high, and medium
  severity, with the base at each level (about 1,030, 1,550, and
  2,030 eligible on the full suite).
- Source: detail.severities.
- Reader question: when attacks land, do they land on the cases that
  matter most?
- Placement: detail card only. It is per-model depth, not a board
  level story, and no current section argues otherwise.

### 1.7 Calibration

- Content per row: attacked and benign ECE and Brier with intervals,
  the Murphy decomposition, 15 equal-count reliability bins per arm
  (mean forecast, mean outcome, bin base), confidence coverage (the
  share of eligible cases that reported a confidence), and the
  sufficiency flag.
- Source: detail.calibration.
- Reader question: when a model states a confidence, should I
  believe the number?
- Placement: calibration section (attacked arm, the standing Round 17
  decision, defended in section 4.4), detail card (both arms in
  numbers).

### 1.8 Cost and latency

- Content: recorded cost per run or its absence state, and attacked
  latency at p50 and p95.
- Source: total_cost_usd, latency_ms_p50_attacked,
  latency_ms_p95_attacked.
- Reader question: what does this level of robustness cost to run,
  and how slow is it under attack?
- Placement: scatter (cost), detail card (cost and latency). Latency
  never enters the ranking. It is a card level fact and putting it in
  the ranking row was noise.

### 1.9 Admission and flags

- Content: the 5 percent malformed admission rule, each flagged
  row's malformed rate and its reason string, and the statement that
  flagged models keep every number and carry no rank.
- Source: unranked reason fields, malformed_rate.
- Reader question: why do four models have no rank, and what would
  they need to earn one?
- Placement: malformed section directly after the ranking, flagged
  strip inside the ranking, method notes.

### 1.10 Provenance and the run register

- Content per run: full model ID, wire, adapter and version, run ID,
  pricing version and date, run date, contract version, dataset
  version, seed, and manifest hash.
- Source: provenance block on every row.
- Reader question: can I cite or reproduce this exact run?
- Placement: detail card (short form) and run register (full form,
  as a table).

### 1.11 Method and caveats

- Content: the definition of attack success and eligibility, the
  interval method, the derived figure rounding note, the robustness
  tax definition, the admission rule, the two re-run notes (Gemini
  and Kimi segments re-run under fixed adapters on 12 October 2026),
  the lower bound cost caveat, and the statement that figures are the
  current best measurement, not settled fact.
- Source: the current notes, carried over with the copy edits in
  section 2.4.
- Reader question: what exactly was measured, and what should I not
  conclude?
- Placement: final section, after compare. Method is the last thing
  on the page because the readers who need it will scroll for it, and
  the readers who do not should meet the results first.


## 2. Information architecture

The page answers four reader questions in order. What is the verdict.
Why should I believe it. Where does each model stand in depth. How
was it measured. Every section exists to serve one of those, and the
order follows the order a skeptical reader asks them.

### 2.1 Section order

1. **Masthead.** The Peira name, the one line claim (decision models
   under attack), the dataset and suite stamp, the official results
   line, and the headline finding from inventory 1.2 set as a short
   prose paragraph. The masthead's job is orientation in five
   seconds. It carries no chart and no tile.
2. **Findings strip.** Three findings replace the KPI tiles
   (section 2.3). Counts, the full suite range, and the cost spread,
   each as a number in display type with one plain caption line.
3. **Ranking.** The board itself, in two population groups with the
   flagged strip between them (section 4.1). This is the page's
   reason to exist and it starts within the first screen and a half
   at 1440 px.
4. **Malformed and admission.** The chart that explains the flags,
   placed immediately after the ranking because the ranking raises
   the question (why do four rows carry no rank) and this section
   answers it while the question is live.
5. **Attack family heatmap.** The shared weakness map. After the
   reader knows the standings and the flags, the next question is
   where the attacks land.
6. **Cost against attack success.** The value question. Placed after
   the heatmap because cost only means something once robustness and
   its failure modes are understood.
7. **Calibration.** The trust question, deliberately late. It is the
   most technical section and the one a casual reader may skip
   without losing the story.
8. **Model detail.** The card index, collapsed by default
   (section 2.2). Depth on demand, in rank order, one tap from every
   chart on the page.
9. **Compare.** Two models head to head. After the cards, because a
   reader compares models they have already met.
10. **Method and notes.** Definitions, admission, tax, run notes,
    provenance summary, and the run register as the final element.

Navigation is a sticky bar under the masthead with eight short
labels. Ranking, Families, Cost, Malformed, Calibration, Models,
Compare, Method. The bar highlights the section in view. On phones
it becomes a horizontally scrolling chip row in the same sticky
position. Eight labels is the ceiling. A ninth section needs an
owner decision, not a longer bar.

### 2.2 Per-model detail lives behind expansion

Decision. The 36 full cards leave the page flow. In their place, the
Model detail section is an index of 36 collapsed rows, each showing
rank or status, short name, attack success with interval, benign
accuracy, malformed rate, and cost state. Expanding a row opens the
full card in place (spec in section 4.5). Multiple rows may be open
at once. Every chart label, ranking row, and compare picker links to
the model's index row and opens it.

Reasoning. The current page prints all 36 cards in full and reaches
about 16,000 px. Almost none of that depth is read on a first visit,
and its uniform weight is what makes the page read as a console dump
rather than an argument. The reader tasks split cleanly. Scanning
tasks (who is strong, who is flagged, where are the weaknesses) are
served by the charts. Depth tasks (one model's severities, its
provenance, its calibration numbers) are always about a named model
the reader already has in mind. Expansion serves the second task at
the moment it arises and removes its cost from the first. The page
target with all cards collapsed is a scroll height at or under
10,500 px at 1440 px width, measured in the build rounds.

The risk is a reader who wants to skim all cards. The index row
carries the five numbers those readers actually compare, and the
section header carries an expand all control. That covers the skim
without taxing everyone else.

### 2.3 What is cut or demoted, and what replaces it

- **Cut, the KPI tiles.** The four tiles print debug output (a lead
  band range, a family range, a cost spread whose footnote names two
  models in capitals inside the tile). Replacement, the findings
  strip. Each finding is a number a reader would repeat to a
  colleague, with a caption that says what it means. Sample copy,
  checked against the payload:

  - 36 results from 35 models. Caption: four results are flagged and
    carry no rank. The board counts distinct models, and its ranks
    count results. (Corrected 2026-10-23 in the round 9 lane. The
    first draft of this sample read 33 models, the old renderer's
    version-only count. The audited rule counts the distinct
    models the board displays: the three guard models that share
    version 1.0 are three models, and gpt-6-luna, measured on two
    wires, is one. 35 tested, 31 ranked, 4 flagged.)
  - 10.7% to 28.5%. Caption: attack success across the ranked full
    suite, strongest to weakest. The five guardrail slices sit apart
    in their own group on the board.
  - $0.05 to $130.31. Caption: recorded cost per full run, cheapest
    to most expensive. Models served locally record no API cost.

- **Cut, the tie-band enumeration.** The current ranking states its
  seven bands three times, in the subtitle, in a second paragraph,
  and in per-row microcopy, and the tiles add a fourth, contradictory
  version. Replacement, one sentence under the ranking heading plus
  brackets drawn on the chart (section 4.1). Sample sentence: ranks
  follow point estimates, and rows joined by a bracket have
  overlapping 95 percent intervals and should be read as tied. That
  sentence is the only place tie prose appears on the page.
- **Cut, per-row tie microcopy and the wire line on ranking rows.**
  Both move. Tie membership is drawn, not written. The wire line
  survives only on the two rows that need it for disambiguation
  (name policy, rule 2) and on cards and the register.
- **Cut, the duplicated position and rank numbers.** The current row
  prints its position and its rank side by side, two numbers that
  disagree whenever a flagged row intervenes. One number per row.
  Ranked rows print their rank. Flagged rows print a flagged tag.
- **Cut, the calibration ECE index as a separate block.** The
  current calibration section opens with 36 mini bars that repeat
  what the panels say. Replacement, the index becomes the panel
  navigation rail (section 4.4). Same data, one job.
- **Demoted, the run register.** From a prose wall at the foot to a
  compact table with one row per run and the provenance fields as
  columns. It is reference material and should look like it.
- **Demoted, latency.** Off the ranking entirely, onto the card
  only (inventory 1.8).
- **Demoted, per-row malformed in the ranking.** The ranking meta
  line prints the malformed rate only when it is at or above
  1 percent, or when the row is flagged. Below that it is a card
  fact. Twenty quiet rows stop repeating a number that does not
  change any decision.
- **Kept against the current of the redesign, the 30 percent axis
  ceiling on the ranking and scatter.** Round 21 recorded it as a
  standing decision for comparability across publishes. It is
  defensible from first principles. A fixed scale lets a returning
  reader compare this board against the next one without relearning
  the axis, and the highest value on the board is 28.5 percent, so
  the ceiling costs almost no resolution. It stays.

### 2.4 Copy rules for the new build

All visible prose obeys the copy bar. No em dashes, no semicolons,
no colons in prose, no strategy talk, no debug output phrasing. Two
further rules come out of the current page's failures.

- A fact is stated once, in the section that owns it, and linked or
  anchored from elsewhere. The tie rule lives in the ranking. The
  admission rule lives in malformed. The tax definition lives in
  method. Sections may point, they may not repeat.
- Every caption answers the question a reader has at that exact
  point in the scroll, in one line where possible and two at most.
  A caption that needs a third line is a sign the chart is carrying
  a message it cannot draw, and the fix belongs in the chart.


## 3. Visual system

### 3.1 The direction, named

**Ledger.** The page should feel like an audited results ledger that
happens to be software. Editorial in its rhythm, instrumental in its
numerals, quiet everywhere the data is not speaking. The current page
reaches for a mission console, glowing green bars on near-black, and
the console register is exactly why dense data reads as noise on it.
A ledger earns trust by alignment and restraint. Nothing on the page
decorates. Every visual weight difference means something.

Four references, and what we take from each:

- **Artificial Analysis** (artificialanalysis.ai). The closest
  relative, a model benchmark presented for decision makers. We take
  its information discipline. One headline chart per question, cost
  plotted against quality without apology, models grouped by maker
  where grouping helps, and every chart titled by the question it
  answers rather than the data it contains.
- **Linear** (linear.app). The dark surface discipline. Hairlines
  instead of boxes, two text weights doing all the work, an accent
  that appears rarely enough to mean something, and density that
  stays calm because alignment is ruthless. We take its surface and
  spacing grammar, not its marketing layout.
- **Observable** (observablehq.com). Chart craft for readers. Direct
  labeling instead of legends wherever a label fits, small multiples
  with shared scales, and annotations written in plain words at the
  point of confusion. We take its labeling and small multiple rules.
- **Stripe Press** (press.stripe.com). Numbers set like they matter.
  Display numerals with real presence, tabular figures in tables,
  prose and figures in a deliberate rhythm on the page. We take its
  treatment of the numeral as a first class typographic citizen.
- **The Pudding** (pudding.cool). Guided reading of dense data. One
  idea per view, the takeaway stated before the evidence, nothing
  charted that the text has not prepared the reader for. We take its
  sequencing instinct, applied to section order and captions.

### 3.2 Typography

Two faces, both already self-hosted in the current lineage, kept
because each survives a first principles test.

- **Archivo** for display, prose, labels, and all data numerals. A
  grotesque with enough character to not read as a default, a wide
  weight range, and true tabular figures. The current page's failure
  is not the face. It is that everything is set at nearly the same
  size and weight, so nothing leads.
- **JetBrains Mono** for identifiers only. Model IDs, run IDs,
  hashes, and the dataset stamp. The current page sets its data
  numerals in mono, and mono numerals are the single largest
  contributor to the debug console feel. Data numerals move to
  Archivo with tabular figures engaged everywhere a number appears,
  so digits align on the decimal and columns read as columns.

Type scale (px, with role):

| Token | Size | Weight | Role |
| --- | --- | --- | --- |
| display | 40 | 600 | findings strip numerals |
| h1 | 32 | 650 | page title only |
| h2 | 20 | 650 | section titles, letterspaced caps |
| lead | 17 | 400 | masthead finding paragraph |
| body | 14.5 | 400 | prose and captions |
| data | 13.5 | 500 | table and chart numerals |
| label | 12 | 600 | caps labels, tags, axis titles |
| micro | 11.5 | 400 | footnotes, register, provenance |

Rules:

- Letterspacing applies to caps labels only, at 0.09em. Body text is
  never letterspaced. Numerals are never letterspaced.
- Line height is 1.45 for prose, 1.25 for data rows, 1.1 for display
  numerals. A section uses at most three sizes. A chart uses at most
  two.
- Weights are 400, 500, 600, and 650. Nothing bolder ships. Emphasis
  comes from size, spacing, and position before it comes from
  weight.

Number formatting, binding on every component:

- Attack success and benign accuracy print at one decimal as
  percents (10.7%). A true zero prints 0.0%, never 0%, so a reader
  can tell a measured zero from a missing value at a glance.
- Intervals in tight contexts print compact, 10.7% [9.8, 11.6]. In
  prose and on cards they print in full, 95% CI 9.8% to 11.6%.
- Values between zero and 0.05 percent print as <0.1% in prose and
  as <1 in whole percent heatmap cells. A nonzero value always
  renders visibly. A missing value renders as the not measured state
  (section 3.4), never as zero and never as a blank.
- ECE and Brier print at three decimals (0.071). Cost prints with
  the dollar sign at two decimals, and lower bound costs carry the
  ≥ prefix. Ranges print with the word to in prose and with an en
  dash in compact labels. Negatives, if any ever appear,
  use a true minus sign.
- Counts print with thousands separators (4,701). Eligible bases
  print wherever a rate could be misread without them, per the
  placement rules in section 4.

### 3.3 Color

The dark theme is retained, and here is the argument rather than the
habit. The page is a dense instrument that readers screenshot into
posts and decks, where a dark ground carries the accent and heat
colors with more range than a light one. Its audience reads it
alongside dark tooling. And the failure of the current page is not
darkness, it is undisciplined color. Three hues currently compete as
decoration (green bars, amber hatching, red text) until none of them
means anything. The fix is a budget, not a new theme.

Tokens:

| Token | Value | Use |
| --- | --- | --- |
| ground | #0A0C0F | page ground |
| panel | #10141A | chart frames, expanded cards |
| raised | #171D24 | hover and open states only |
| hairline | #232C35 | every divider, axis, and frame |
| ink-1 | #E9EEF3 | primary text and data marks |
| ink-2 | #AEBCC7 | secondary text, whiskers, axis labels |
| ink-3 | #71808F | captions, bases, de-emphasised rows |
| accent | #2FBF71 | the strength end of scales, links, focus |
| amber | #E8A33D | flagged semantics only |
| red | #FF6A3D | worst family and over threshold marks only |

Semantic constraints, treated as hard rules:

- **Amber means flagged and nothing else.** No amber text, fill, or
  rule may appear for any other purpose anywhere on the page. The
  current build spends amber on headings, names, and bars until the
  flag stops registering. One meaning, total consistency.
- **Red means the extreme and nothing else.** The worst family on a
  card, a bar past the admission line, the hottest heat cells. If red
  appears more than a few times per screen, the screen is wrong.
- **Green is the strength accent, not the default fill.** Data bars
  and points render in ink-1 at restrained weight. Green appears at
  the strong end of scales, on the leading group marker, and on
  interactive elements. The current wall of saturated green bars is
  the loudest thing on the page and it says nothing, because every
  bar has it.
- **Population is never encoded by hue.** Slices and full suite rows
  differ by grouping, tags, and whisker style (section 4.1), never by
  a color a colorblind reader cannot separate from the flag amber.
- **Hatching is banned.** It is the strongest texture available and
  the current build spends it on four rows until they dominate a 36
  row chart. Flagged rows get an amber tag, an amber left rule, and
  amber value text. That is enough, because amber appears nowhere
  else.
- Heat encoding uses its own ramp (section 4.3) and borrows no hue
  from the semantic set. Green never appears in the heatmap.

Contrast floors: ink-1 on ground exceeds 12 to 1, ink-2 exceeds 7 to
1, ink-3 exceeds 4.5 to 1 and is therefore barred from carrying any
number a reader needs. Amber on ground exceeds 7 to 1. Cell text in
the heatmap flips between ground and ink-1 at the ramp midpoint.

### 3.4 Spacing, surfaces, and the calm rules

- Base unit 4 px. Spacing scale 4, 8, 12, 16, 24, 32, 48, 64, 96.
  Content column max width 1180 px, centred, with 24 px gutters.
- Sections separate by 96 px of space and one hairline. Inside a
  section, groups separate by 32 px. A panel border appears only
  around something with a coordinate system (scatter, heatmap,
  calibration panels). Text never sits in a bordered box.
- Radius is 6 px on panels and 3 px on tags, or zero. No pill
  shapes except tags. No shadows except the sticky bar's single
  bottom hairline darkening on scroll.
- Row heights: ranking rows 40 px, index rows 44 px, register rows
  32 px. Density is welcome in tables and banned in prose. Prose
  measures at most 68 characters per line anywhere on the page.

The not measured state, one treatment everywhere: the cell or field
renders in ground tone with a single centred middot, and the reason
is stated once per group in the group caption (not run on slices,
no cost recorded, no tax on slices). A reader who sees the middot
twice has learned it. It never prints as n/a, which reads as a data
failure, and never as a blank, which reads as a bug.

Calm rules, the checklist reviewers apply to every screenshot:

1. One idea per section, stated in its title or its first line.
2. Alignment before decoration. If a column of numbers does not
   align on the decimal, the layout is wrong before anything else
   is judged.
3. At most three text sizes and two weights visible in any single
   chart.
4. Whitespace separates before hairlines do, and hairlines before
   boxes do. Reach for the weakest separator that works.
5. The loudest element on each screen is the data the section
   exists to show. If a caption, a tag, or a flagged row is louder,
   the screen fails.
6. Repetition is noise. A number already printed in a section is
   not printed again in that section in a different costume.
7. Every color on screen can be named and justified from the token
   table. An unlisted color is a defect.


## 4. Chart specs

Common rules, stated once. Every chart is titled by its reader
question in the section heading system of section 2. Every chart
prints its axis ceiling and its base sizes where a reader could
misread without them. Hover and focus always produce the same
information. Anything reachable by mouse is reachable by keyboard,
with a visible focus ring in accent. Reduced motion is respected.
No chart animates on load.

### 4.1 Ranking

**Question.** Which models are hardest to attack, and how sure are
we.

**Layout.** A single chart in three stacked groups, sharing one
axis (attack success, 0 to 30 percent, ticks at 0, 10, 20, 30).

1. Full suite ranked group, 27 rows in payload rank order.
2. Flagged strip, the 4 flagged rows in attack success order.
3. Abstain slice group, the 5 slice rows in payload rank order,
   under a group header that carries its base in words. Sample
   header copy: guardrail slices, measured on the 373 case abstain
   subset. Their rates sit apart from the full suite and the two
   groups are never interleaved.

Group order reasoning. The full suite is the board's main event and
leads. The flagged strip follows it directly because the reader's
next question is who is missing and why. The slices close the
chart, clearly a different instrument, their low rates unable to
masquerade as the top of the main board. Payload rank numbers print
unchanged inside both ranked groups (slices keep ranks 1 to 5), so
no printed number changes. The group headers carry the population
warning that the numbers cannot.

**Encoding.** Per row: rank or flagged tag, short name, bar,
whisker, value. The bar runs from zero to the point estimate in
panel tone with an ink-1 end edge, deliberately quiet. The whisker
is the visual lead: a 2 px ink-1 line spanning the 95 percent
interval with end caps, centred on the bar. The value prints right
of the whisker in data type. Slice rows draw the same bar with a
hollow whisker (open caps) so the population difference survives
even a greyscale screenshot. Flagged rows draw the bar and whisker
in amber outline with no fill, the value in amber, and the reason
in the meta line (malformed 10.7%, over the 5% admission limit).

**Ties, drawn not written.** A bracket in the left margin joins
each band of two or more ranked rows: a hairline vertical rule
spanning the band with short ticks at its ends, labelled once with
the word tied in label type, placed beside the bracket's midpoint.
Brackets appear in both ranked groups (the slice band of ranks 1
to 3 gets one). Single rows get no bracket. The word tied appears
on the page once in the ranking sentence (section 2.3) and once
per bracket, nowhere else. No row prints a band range, and no
caption enumerates bands.

**Labels.** Short names per the name policy. The two gpt-6-luna
rows carry their wire lines. Meta line under a name appears only
for flagged rows (the reason) and for rows whose malformed rate is
at or above 1 percent (malformed 4.2%). All other rows are one
line. Nothing truncates, per policy rule 4.

**Interactions.** Hover or focus on a row raises it to the raised
surface tone and shows a tooltip with the full figures: attack
success in full interval form, benign accuracy, malformed rate,
eligible base, and cost state. Clicking a row, or pressing Enter
on it, opens that model's detail card below and scrolls to it.
There is no re-sorting. Rank order is the editorial claim of this
chart, and a sort control would quietly unmake it. A reader who
wants another order wants the data, and the register serves that.

**Edge states.** A model with a zero attack success prints a
whisker and a 0.0% value with no bar, which is visibly distinct
from a missing row. A future payload with no flagged rows collapses
the flagged strip entirely, header included. A future payload with
no slices collapses the slice group the same way. Bands of one get
no bracket by construction.

**Acceptance test.** On the 1440 px screenshot: count the word tied
in the section, brackets plus one sentence, and confirm no other
tie text exists. Confirm the slice group header is visible without
scrolling past the full suite group being possible to mistake, by
checking the slice rows cannot be reached without crossing the
flagged strip and a group header. Measure that no name is clipped
by comparing every rendered label's scroll width against its
client width in the DOM. Confirm exactly one number per row in the
rank column. Confirm amber appears only inside the flagged strip.

### 4.2 Scatter, cost against attack success

**Question.** What does a given level of robustness cost per run.

**Encoding.** X is recorded cost per run on a log axis from $0.01
to $1,000, with decade ticks labelled $0.01, $0.10, $1, $10, $100,
$1K. Y is attack success, 0 to 30 percent, shared ceiling with the
ranking. 31 of the 36 rows belong in this chart. 26 carry a cost
above zero and plot on the axes. 5 carry no usable cost and plot
on the rail described below. The 5 remaining rows are slices,
excluded at the end of this spec. Ranked models are
filled ink-1 discs. Flagged models are amber rings. A lower bound
cost draws a short leftward tick from the point, pointing back
toward the true cost, with the meaning stated once in the caption.
Sample caption: cost is the recorded total per run. Points with a
leftward tick are lower bounds, where a call went unpriced.

**The no-cost rail.** Models with no usable cost cannot sit on a
log axis, and the current chart solves this by silence: 5 ranked
full suite models simply do not appear. That is
the chart's worst defect, because the missing models are the
locally served ones a cost-conscious reader most wants to find.
The spec adds a rail: a labelled gutter strip at the left edge of
the plot, outside the axis, headed no recorded API cost. Those 5
models plot there as discs on a vertical line at their attack
success, in the same ranked and flagged encodings. The rail is
inside the panel, visually part of the chart, and its header makes
the encoding unmissable. Zero cost rows (Kev 4B, Laya multilingual,
SemIf) and null cost rows (Decider, Strands) share the rail, and
the tooltip and the detail card carry which of the two each one
is, since the payload distinguishes a recorded 0.0 from an absent
cost and the design preserves that distinction in words wherever
the model is named with its cost.

**Slices.** The 5 slice rows do not plot. They belong to the other
population and carry no costs. The caption states the exclusion in
the same line as the base note. Sample: the five guardrail slices
carry no recorded cost and are not plotted.

**Labels.** At desktop width every plotted point carries its short
name. Collision rules, in order: a label may not overlap another
label, a point, or the axis furniture. A label displaced more than
12 px from its point draws a hairline leader. Where a cluster
cannot satisfy those rules at desktop width (the cheap and strong
corner, where Jev 1.13, Jev 1.14, both gpt-6-luna wires, DeepSeek,
and Gemini sit within a few points of each other), the cluster
collapses into one callout: the points keep small index numbers,
and a keyed list beside the plot names them in attack success
order. The threshold is mechanical: if the label solver leaves any
pair overlapping, the densest cluster keys out. At phone width all
labels key out (section 5).

**Interactions.** Hover or focus on a point shows the tooltip:
short name, attack success with interval, cost with its bound
state, rank or flagged status. Points on the rail behave
identically. Clicking opens the detail card, as in the ranking.
No zoom, no pan, no axis controls. The chart's claim is a static
one and interaction should serve identification, not exploration
theatre.

**Edge states.** A point exactly on another point (same cost, same
rate) offsets by at most one marker width, and both labels stay.
A cost above $1,000 extends the axis by one decade rather than
clipping. An all-local future payload leaves the plot empty and
the rail full, and the caption rule still holds.

**Acceptance test.** Count plotted points plus railed points
against the payload: 26 costed rows plotted, 5 on the rail, 5
slices absent, total 36 accounted for, read off the screenshot and
the DOM. Confirm no two labels overlap by the harness label check.
Confirm every locally served model a reader can name from the
ranking is findable on this chart.

### 4.3 Heatmap, attack families

**Question.** Where is each model weak, and which weaknesses are
shared across the field.

**Encoding.** Rows are models in overall attack success order,
grouped exactly as the ranking groups them (full suite ranked,
flagged, slices) with the same group headers, so the two charts
teach one mental model. Columns are the 11 families in descending
order of mean attack success across the models that carry them,
the standing ordering rule. Each cell prints the family attack
success as a whole percent (0, 2, 14), with values above zero and
below 0.5 printing <1. Cell color follows the heat ramp below.
Hover or focus on a cell shows the exact rate at one decimal, its
interval, and its eligible base.

**The ramp.** The current green to red ramp fails twice. Green is
spent elsewhere with a different meaning, and a linear 0 to 100
ramp puts nearly every cell in the same dark green, because the
informative range of this data is 0 to 30 with a tail to 98. The
new ramp is single-hue heat: ground tone at zero, rising through
deep amber to bright ember at 100, interpolated in a perceptual
space with a power curve of 0.65 so differences between 0 and 30
are visible without exaggerating them. The legend prints its
ticks at 0, 10, 25, 50, and 100 and states the curve in words.
Sample legend note: shading rises faster than the value, so low
rates separate. Judge cells by their printed numbers. The printed
number in every cell is what makes the non-linear ramp honest:
color finds the pattern, the number carries the fact.

**Headers.** Column headers are short family names on one line,
never wrapped: Crosslingual, Crypto payload, Evidence, Frequency,
Question pair, Retrieval, Verbosity, Canary, History, Sycophancy,
Threshold. The full names live in the method notes as a family key
and in each header's tooltip. Row headers are short model names
with the flagged tag where it applies, and no inline status text.
The current build's wrapped three line headers and its inline
unranked suffixes are both banned by this spec.

**Not measured cells.** The four families slices never ran render
as the not measured state (section 3.4): ground tone, one middot,
and the slice group header carries the reason once. They must not
read as zeros. A column of middots under the slice group, aligned
and quiet, says exactly that.

**Interactions.** Hover highlights the row and column hairlines so
a cell can be traced to its model and family at 36 by 11 density.
Clicking a row header opens the detail card. No column sorting:
the family order is a claim about the field, and it stays.

**Edge states.** A family carried by a single model still gets a
column. A model whose family rate is a true zero prints 0 in
ground tone, distinguishable from the middot by the printed digit.
At the widest values (98) the cell text flips to ground tone per
the contrast rule in section 3.3.

**Acceptance test.** On the 1440 px screenshot: confirm every
header fits one line by DOM measurement. Confirm the four slice
columns show 5 middots each and no zeros. Pick the three hottest
cells by eye and confirm they are the three largest values in the
payload matrix. Confirm green appears nowhere in the grid.

### 4.4 Calibration

**Question.** When a model states a confidence, should the number
be believed.

**Layout.** A two-part section. Left, a navigation rail listing
all 36 models in attacked ECE order, each with its ECE value and a
slim bar. Right, a grid of small multiple panels in the same
order, 3 across at desktop. The rail is sticky within the section
and clicking a name scrolls its panel into view and flashes its
frame. This replaces the current design, where the ECE index and
the panels are two separate blocks printing the same ordering
twice.

**Panel encoding.** Each panel plots the attacked arm's 15
equal-count reliability bins: mean forecast on x, mean outcome on
y, both 0 to 100 percent, with the perfect calibration diagonal as
a hairline. Points are ink-1 discs. The region below the diagonal
is overconfidence, stated once in the section caption, never per
panel. Panel header is one line: short name, then ECE and Brier
and the calibration base. Sample header: granite-guardian-hap-125m
· ECE 0.003 · Brier 0.000 · n 373. Axes print on edge panels only (bottom row x,
left column y) so 36 panels do not print 72 axis furniture sets.
Slice panels carry the slice tag. Panels are ordered by ECE
across both populations, because the
calibration question does not change with population the way the
attack success question does. The benign arm appears as numbers
on the detail card, not as a second set of panels. 72 panels
would double the section to serve a question the attacked arm
already answers.

**Edge states.** A row whose calibration block reports
insufficient data or no bins gets a framed panel in the not
measured state with its confidence coverage printed, so an absent
panel never reads as a lost model. A model whose bins collapse to
fewer distinct points (bins with equal forecast and outcome draw
as one point, per the current caption) prints its bin count in
the header tooltip.

**Interactions.** Rail click to scroll and flash, as above. Hover
on a point shows the bin's forecast, outcome, and base. No arm
toggle: the attacked arm is the subject of this benchmark, and a
toggle invites a comparison the page makes no claim about.

**Acceptance test.** Count panels against payload rows, 36,
including any not measured frames. Read one panel against its
payload bins by hand: first bin forecast and outcome within
rounding. Confirm the rail order and the panel order are the
same order, and that ECE values match between rail, panel header,
and the detail card for three sampled models.


### 4.5 Model detail cards

**Question.** Everything about one model, in one place, in a fixed
order I can learn once and reuse 36 times.

**Index row (collapsed).** Rank or flagged tag, short name with
wire line where the name policy requires it, attack success with
compact interval, benign accuracy, malformed rate, cost state
(amount, ≥ amount, locally served, or the not measured state), and
an expand control. Rows group as the ranking groups (full suite,
flagged, slices) under the same headers. The section header
carries expand all and collapse all controls.

**Expanded card.** A panel in place, with a fixed anatomy. Nothing
reorders between cards.

1. Header line: rank statement in words (rank 6 of 32 ranked, or
   flagged with its reason, or the slice statement), then the full
   display name in mono as the model ID, then the wire in plain
   words.
2. Headline figures: attack success in full interval form, benign
   accuracy, malformed rate, eligible cases with the case base.
3. Stat grid, two columns at desktop, fixed order: cost (with
   bound state), latency p50 and p95 under attack, attacked ECE,
   attacked Brier, benign ECE, benign Brier, calibration base with
   its coverage share, robustness tax where it exists.
4. Family spark bars: 11 horizontal bars in the heatmap's fixed
   family order on a shared 0 to 100 percent scale, each with its
   whole percent value. The worst family prints in red. Families
   the model does not carry draw as outline slots in the not
   measured state. These bars use ink-1, never the heat ramp, so a
   card never pretends to be a heatmap.
5. Severity line: flip rates at critical, high, and medium, each
   with its base. One row of three figures, not a chart.
6. Robust tax line, where the tax exists: the figure, and the two
   benchmark setters named from the tax computation itself, in the
   form tax is measured against the best full suite benign
   accuracy (jev-1.14.0, 98.7%) and the best full suite attacked
   ECE (claude-sonnet-5-5, 0.048). Where the tax does not exist
   (slices, flagged rows), the line prints the not measured state
   with its reason. Benchmark names are generated from the same
   rows the tax is computed against. A card may never name a
   benchmark its own tax was not computed against, which is the
   contradiction the current page ships (section 0).
7. Provenance block, in mono at micro size: adapter, version, run
   ID, pricing version, run date, manifest hash to 12 characters.
   The full hash lives in the register only.

**Interactions.** Expand and collapse in place with no page jump:
the scroll position anchors to the row header. Opening a card
from a chart elsewhere on the page scrolls to the index, opens
the card, and flashes its frame. Cards hold their state in the
page address (an opened model is a shareable link), matching the
compare behaviour the current page already promises.

**Edge states.** Flagged cards carry the amber header rule and
the reason line. Slice cards carry the slice tag and the abstain
base statement in the header figures, so a slice card can never
be screenshotted out of context and read as a full suite result.
A model with unpriced calls prints its cost with ≥ and the words
lower bound.

**Acceptance test.** Open three cards (one full suite, one
flagged, one slice) and confirm identical anatomy order. Confirm
the slice card states its 373 case base in its header figures.
Confirm every figure on the card matches the payload row for one
sampled model, field by field.

### 4.6 Compare

**Question.** Between these two specific models, which is stronger,
where, and at what cost.

**Layout.** Two pickers at the top, then a metric table: one row
per metric, model A value, model B value, and a centre delta
column. Below the table, paired family bars: 11 rows, A's bar
above B's in each pair, on the shared 0 to 100 percent scale, in
the fixed family order. The pair is carried in the page address
(the current behaviour, kept, because a shared comparison link is
the section's most valuable property).

**Pickers.** Grouped lists in three groups matching the page's
groups (full suite ranked, flagged, slices), short names only,
with the wire line inside the option for the duplicated name. The
hash-carrying names never appear. Default pair on first load: the
strongest full suite row against jev-1.14.0, the reference model
of this benchmark's programme, so the section opens on the
comparison most readers came for rather than on two slices.

**Delta column.** Each delta is A minus B computed from the
unrounded payload values, printed at the same precision as its
metric, with the better side marked by an accent dot in its own
column. Lower is better for attack success, malformed, ECE,
Brier, and cost. Higher is better for benign accuracy. The method
notes already state that derived figures are computed from
unrounded values, so deltas follow a rule the page has published
since before this redesign. The owner decision on printing deltas
at all is listed in section 6.

**Population guard.** When the pair crosses populations (a slice
against a full suite row), a banner line appears above the table
stating that the two ran different case bases and their attack
success rates are not measured on the same base. The table still
prints, because the reader asked, but it never prints unguarded.

**Edge states.** The same model on both sides prints the table
with an em state: deltas collapse to a single line stating the
pair is the same model, and no winner dots render. A family one
side does not carry prints the not measured state on that side,
and its pair mate still prints.

**Interactions.** Changing either picker updates the table, the
bars, and the address without a reload. A swap control exchanges
A and B. Winner dots and deltas recompute client side from the
same payload the page already carries.

**Acceptance test.** Load the default pair and verify three
deltas by hand against the payload's unrounded values. Cross a
slice with a full suite row and confirm the banner appears.
Screenshot the pair and confirm no full display name or hash
appears anywhere in the section.

## 5. Mobile, 390 px and 320 px

Rules per section, stated so a reviewer can test them. The general
principles come first because they decide every argument below.

- Nothing truncates. The name policy holds at 320 px exactly as
  at 1440 px. When a row cannot fit on one line, it takes two.
- No sideways scrolling except inside the heatmap, which is
  signposted, and the nav chip row. Any other horizontal overflow
  at 320 px is a build failure.
- Tap targets are 44 px or taller. Hover-only information always
  has a tap equivalent: a tap on a data mark shows the same
  tooltip a hover would, and a second tap follows the link.
- Type does not shrink below micro size. Space is found by
  stacking, never by setting data smaller.

**Masthead and findings.** The claim line wraps under the name.
The findings strip stacks into three rows separated by hairlines,
numeral left, caption right, each row at least 64 px tall. The
nav becomes a sticky chip row with horizontal scroll and a fade
at the right edge.

**Ranking.** Each row takes two lines. Line one: rank or tag,
then the short name, then the value right aligned. Line two: the
bar with its whisker at full content width, with the compact
interval at its right end. Band brackets survive on the left
margin at both widths, narrowed to a 10 px gutter. The group
headers and the flagged strip keep their full copy. At 320 px
the longest short name (strands-decider-2B-hobson-v21) fits line
one beside its value, verified by DOM measurement, not by eye.

**Malformed.** One line per row becomes name above bar, as in
the ranking. The 5 percent admission line stays drawn and
labelled on the line itself. The folded summary line for the
zero group stays a line of text.

**Heatmap.** The grid scrolls sideways inside its panel. The
model name column is sticky at the left with a ground tone
background and a hairline at its right edge. Cells hold a 44 px
minimum width so whole percent values never crowd. A fade and a
one line hint above the panel state that the families continue
to the right, and the hint dismisses itself once the reader has
scrolled the grid. Column headers stay one line at both widths,
per section 4.3, because the grid's width is allowed to exceed
the screen while the page never does.

**Scatter.** Labels key out entirely. Points carry index numbers
and the keyed list prints below the plot in attack success
order, two columns at 390 px and one at 320 px. The no-cost rail
survives as a labelled band at the plot's left with its points
numbered into the same key. Plot height 300 px. The caption
keeps both of its statements, rail and slice exclusion.

**Calibration.** Panels stack one per row. The rail becomes a
wrapping chip list of short names with ECE values, tapping a
chip scrolls to its panel. Panel headers keep name, ECE, Brier,
and base on one wrapped line. Axes print on every panel at this
width, because with one panel per row the edge-only rule has no
grid to lean on.

**Model detail.** Index rows take the ranking's two-line form.
Expanded cards set their stat grid at two columns at 390 px and
one column at 320 px. Spark bars go full width with the family
short name and value on the line above each bar. The provenance
block wraps freely, mono text may break anywhere.

**Compare.** The pickers stack full width, A above B, with the
swap control between them. The metric table becomes three lines
per metric: the metric name, then A and delta, then B, with the
winner dot beside the winning value. Family pairs stack with the
family name above each pair. The population banner keeps its
full copy.

**Method and register.** Prose measures the full content width.
The register table becomes a definition list per run, field
label above value, because a six column table at 320 px serves
nobody. It remains a table at 390 px only if every value fits
without truncation, which the build rounds must prove by DOM
measurement or fall back to the list at both widths.

## 6. Decisions the build rounds need from the owner

1. **Grouped ranking with original rank numbers.** Section 4.1
   separates slices and flagged rows into their own groups while
   keeping payload rank numbers (slices keep 1 to 5). This is
   this document's strongest recommendation and it changes how
   the board reads more than any visual choice in it. The
   alternative, one interleaved list with stronger tags, keeps
   the current comprehension hazard in a cleaner costume.
2. **The scatter rail.** Section 4.2 puts the 5 costless models
   on a labelled rail inside the cost chart. It repairs a silent
   omission, and it changes the chart David has already reviewed
   once. It should be confirmed at the round 9 chart prototype
   gate at the latest.
3. **Compare deltas.** Section 4.6 prints A minus B figures
   computed from unrounded values. They are new printed numbers
   in the derived sense the method notes already sanction, but
   they are new, and the no new numbers rule deserves an explicit
   yes before they ship.
4. **The heat ramp curve.** Section 4.3 specifies a power 0.65
   ramp with printed cell values carrying exactness. If the owner
   prefers strict proportionality, the fallback is a linear ramp
   on the same hues, accepting that the 0 to 30 band will read
   flatter. One of the two must be picked before the heatmap
   build round, because the legend copy differs.
5. **Benchmark naming on cards.** Section 4.5 rule 6 requires
   tax benchmark names from the tax computation. The data audit
   lane owns confirming the two setter rows. The card build
   round blocks on that confirmation, not on this document.

Nothing else in this document needs a decision. Where the old
program had a rule worth keeping (the 30 percent ceiling, the
attacked calibration arm, worst first family ordering by mean,
direct labeling), this document keeps it and says why, so the
build rounds inherit the reasoning and not just the rule.
