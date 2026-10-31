# Peira board redesign, Maidan-led. The design record

This branch carries the board redesign that ships. The
branch is `redesign/maidan-led-board`, based on main
`16928211`, and the change is code only. `data/payload.json`
is main's own 39-row payload, byte-identical, and the
colour scheme is the board's standing dark scheme, every
token value in `app/globals.css` identical to main's. What
the redesign changes is the board's mechanics. The cost
scatter names every result in tiers that cannot throw or
fill up, the readings above the chart and the axis ceiling
derive from the payload instead of standing as literals,
a flagged figure never travels without its decomposition
on any surface, and the render law that proves the design
rules runs inside the build itself.

The sections below are the record in the order it
happened. The first build's paper scheme was rejected by
the owner and reverted, and its passages stand marked as
superseded history. The iteration note, the cleanup
addendum, and the repair round addenda correct the record
in place as the work landed.

The transfer source is the Maidan UI study
(`../maidan-ui-study/STUDY.md`), read against the charter and
doctrine v1 (D1 to D33) and the hardcode audit
(`peira-publish-prep/HARDCODE-AUDIT.md`, findings F1 to F9).

## Iteration, 2026-10-30. The palette revert

The owner rejected the paper scheme. He had not approved
changing the board's colour scheme, and the redesign as
delivered read as a colour flip over the same board. The
scheme was never the redesign's to change, so the palette
is reverted in full and the mechanics are kept, because
the mechanics were the point.

What the revert restores is exact. Every token value in
`app/globals.css` from main `9d4701f8` (ground `#05070a`,
panel `#0c1015`, accent `#2fbf71`, the flagged amber
`#e8a33d`), the ambient glow behind the page, and the
original dark-ground heat ramp in `lib/charts.ts` with
its stepped text flip. Where the first build's
single-accent budget conflicts with the standing scheme,
the standing scheme wins. The palette passages below (the
paper section, the one-signal-color section, the heat
ramp section, deviation 1) are the first build's record,
kept and marked as superseded. They do not describe the
current tree.

What was kept, unchanged in behaviour, is this. The tiered
scatter naming and the fitted naming list, the derived
readings strip, the derived axis ceiling with off-scale
disclosure in words, the truncation ethic, the 44px coarse
floor, tabular numerals throughout, the hardcode removals
F1 to F5 and F8, and the Method re-run deletion.

The Standards review of the first build failed with two
Majors and minors, and the Spec review passed with two
record Minors. All of them are folded into this iteration.

- **S1 (Major).** The 43-row staged payload no longer
  rides in this branch. `data/payload.json` is main's own
  file, so the design change is code only, and the publish
  payload lands later through the publish flow. The
  iteration's verification therefore runs on main's 39-row
  payload. The render law was proven on the 43-row payload
  by the first build and is being re-proven on the 46-row
  publish payload by the red team.
- **S2 (Major).** The render-law harness is wired in. A
  `check:render` script sits in package.json, chained at
  the end of `build` after the static export exists, on
  the repo's existing check wiring pattern. The claims in
  the harness header and the stylesheet that it gates the
  build are now true, and the verification below shows it
  executing inside the build.
- **S3.** Law 8 reads the expected accent from the
  rendered page's own `--accent` token instead of a
  hardcoded rgb triple. The revert changed the accent
  under it and the law followed, which is the point.
- **S4.** The dead `.corner-title` and `.corner-sub`
  rules are deleted from globals.css, and the stale
  corner comments are refreshed.
- **S5.** Both stray literals are handled. The scatter
  marker stroke is one shared `MARKER_STROKE` constant in
  ScatterIsland.tsx, restored to the standing tone. The
  heatmap's `#fff8ec` disappeared with the ramp revert,
  and the cell text colour is the token pair again.
- **S6.** INK and GROUND in `lib/charts.ts` keep their
  names. With the standing values restored, INK is the
  light ink tone and GROUND the dark ground tone, so the
  names assert what the values are. The paper build's
  swapped-value comments are gone.
- **S7.** The readings strip's cost phrase is structured
  now. scatterData computes a `costPhrase` from the row's
  cost state, and Scatter.tsx's string-prefix surgery on
  costText is deleted. In ScatterIsland's list values the
  cost clause stands as its own capitalized sentence
  instead of trailing lowercase after a period.
- **S8.** The harness measures harder. Law 6's candidate
  set is derived from the rendered DOM (interactive tags
  and roles, control-like display), never a class list,
  so a future control class cannot escape silently. On
  its first run it caught two control classes standing at
  33px that the old list never measured, the calibration
  rail's links and the model cards' nav links, and both
  now stand at the 44px floor under a coarse pointer.
  Law 5 derives the flagged figures from the payload and
  requires the malformed decomposition inside the
  figure's own carrier (row, card, entry, cell or
  caption), the pairing check-integrity enforces on the
  server-rendered page. Its first run caught the ranking
  rows printing a flagged figure with only the malformed
  rate beside it, and the model cards printing theirs
  with only the flag explanation, so flagged ranking rows
  now state the decomposition in their meta line and
  their accessible name, and flagged cards state it in
  their reason paragraph, all derived by the same
  lib/payload function the scatter titles use. The check
  attributes each carrier to its result before judging
  it, so a per-family figure inside another result's
  card that merely equals a flagged figure as a string
  is not judged as the flagged result's figure. A
  chromium startup failure now kills the browser and the
  static server before exiting instead of leaking both,
  and a successful run exits explicitly rather than
  lingering on the browser's keep-alive connections,
  which the build chain that runs the law would
  otherwise wait on.
- **S9.** This record is copied into the repo at
  `site/board/DESIGN.md`, so the law travels with the
  code.
- **F1 (Spec Minor).** Deviation 4's figures are
  corrected in place below. The phone pitch constant
  moves 34 to 46, and 44px is the hit height.
- **F2 (Spec Minor).** The 51.9% claim is corrected in
  place in the state-as-words passage below. The
  unconditional figure appears nowhere as a figure, and
  the literal string survives only inside decomposition
  text, as it did before the redesign.

## Iteration verification

All on the final tree, against main's 39-row payload.

- `npm run build` ran clean with exit 0. The chain is the
  gen-og prebuild, next build (44 pages), check-integrity,
  check-budget, then the render law executing inside the
  build, as S2 wired it.
- `check-integrity.mjs` passed (39 rows, counts 38/34/4,
  29 taxes recomputed, max deviation 0.00000, compare
  dataset and 11 rendered deltas verified).
- `check-budget.mjs` passed (427.9 KB of the 500.0 KB
  budget). `check-vendor-agreement.mjs` passed (all 39
  rows agree across page marks, page colors and the share
  image). `check_public_surface.py` passed.
- `tests/render-law.mjs` passed inside the build and again
  standalone. All assertions passed at 390, 500, 700, 800,
  900, 1000, 1280 and 1440. Zero page errors, no
  document-level overflow, 33 of 33 charted results named
  exactly once in the visible scatter variant at every
  width, the case count confined to Method, no flagged
  figure without its decomposition in its carrier, every
  measured control at 390 coarse at 44px or taller, every
  printed heat cell at 4.5 to 1 or better, and no
  filled-accent control in the first viewport, with the
  accent read from the page's own `--accent` token (the
  standing `#2fbf71` after the revert).
- Codepoint scan of the whole branch diff against main
  found no em or en dashes in any added line. The
  iteration note's own prose carries no semicolons.

## Red-team addendum, 2026-10-30

The red team's verdict on the first build was FAIL, with
two findings that joined this iteration's scope.

**RT-F1, the resize overflow.** Fresh loads were clean
at every width the red team sampled on the 46-row
payload, but a live resize sweep overflowed horizontally
across the 515 to 615 band, up to 103px, in both sweep
directions. Reproduced on this tree with the red team's
own probes (diag-overflow, diag-chain). In the phone
ranking layout the name cell carried `flex: 1 0 auto`,
so it took its max-content width, set by the flagged
meta line's unwrapped length, refused to shrink, and
overflowed every row narrower than that width. On this
payload the frozen width is 650px (the decomposition
sentence this iteration added to flagged rows lengthened
the meta line, widening the band), so the overflow runs
from 645 down. The render law could not see it. Its
sampled resting widths never landed in the band, and its
emulated phone widths do not produce literal layout
widths. The fix is one rule. The name cell shrinks
(`flex: 1 1 auto`), and its contents wrap, as they always
could. The render law gains a ninth law, a resize sweep.
It runs 1440 down to 360 and back at 15px steps, with
5px steps across the named band, and the document's
overflow is measured at every step, with the widest
unclipped element named on failure. Against the pre-fix
export the sweep fails at 69 steps and names the cell
(div.cell-name, right 650, worst +290px at width 360).
On the fixed tree the full gate set was re-run and is
green again, the sweep passing at all 178 steps inside
the build.

**RT-F2, Law 5 gate soundness.** The red team found the
first build's Law 5 unsound as a C-5 gate, because it
accepted the word malformed anywhere in the scatter
section. That is the same defect the Standards review's
S8 named, and the remedy is the S8 fix recorded above.
The law derives the flagged figures from the payload
and binds the decomposition to the figure's own
attributed carrier, the pairing check-integrity
enforces. check-integrity remains the gate of record
for C-5. The render law is its rendered-page companion
and no longer claims more than it measures.

Confirmed clean by the red team, with no action taken.
The fitted list engages at fresh load at 761 and 800 on
the 46-row payload. The mercury whisker overshoot
matches the pre-existing audit-dom class-3 disclosure
and is not widened by the redesign. Every scatter
caption on the 46-row payload is derived and correct,
including all six flagged decompositions in words.

## Screenshots v2

The first build's full-page captures did not render on
the owner's phone. This set is section shots only, each
at most about 1600px tall, long sections split into
lettered chunks, at 1440 and 390, in `shots-v2/` beside
this file. Every file's dimensions were read back from
the file itself before this inventory was written.

At 1440 there are 16 files. Masthead 1440x688, findings
1440x534, ranking in three chunks (1440x1388, 1440x1388,
1440x1386), malformed 1440x1415, heatmap in two (1440x887,
1440x886), scatter 1440x1231, calibration in two
(1440x1095, 1440x1095), models in two (1440x1237,
1440x1236), compare 1440x1341, method 1440x1389, footer
1440x221.

At 390 there are 36 files. Masthead 390x591, findings
390x448, ranking in five (390x1421 four times, 390x1417),
malformed in two (390x755, 390x755), heatmap in eight
(390x1342 seven times, 390x1335), scatter in two
(390x1164, 390x1164), calibration in nine (390x1412 eight
times, 390x1404), models in three (390x1409, 390x1409,
390x1407), compare in two (390x1130, 390x1129), method in
two (390x932, 390x931), footer 390x322.

No file in the set exceeds 1421px in height. The set was
eyeballed. It shows the masthead and hero in the standing
dark scheme with the green accent, the phone scatter with
its derived readings strip (structured cost phrases in
prose), tiered naming, and the maker's marks in their
colors.

## The design law applied

**Paper, ink, hairlines (first build, superseded by the
iteration).** The board flips from the dark theme to
Maidan's warm paper system. Ground `#f2eee6`, panel `#faf8f2`,
raised surface pure white, hairlines `#e2ddd0` and translucent ink
edges, ink ramp `#1b1a17 / #55534b / #6e6c61`. Shadows are warm and
shallow. The dark theme's ambient glow behind the page is deleted.
Paper is flat. The flip was almost entirely a token change in
`app/globals.css` (the stylesheet already referenced its tokens in
roughly 208 places against a handful of literals), which is itself
the Maidan lesson. A design system you can re-skin by swapping
tokens is a system. One you cannot is a pile of pages.

**One signal color, budgeted (first build, superseded by the
iteration).** Deep fern `#14532d` is the accent
(links, the section numbers, the selected states, focus). Amber
`#b45309` appears only where the data says flagged. Nothing else
gets a color to say something. The render law counts filled-accent
controls in the first viewport and fails above one.

**State as words, never as pills or dots.** A flagged result says
"flagged" in words inside its name cell, in the scatter list, and in
its chart row, and its figure always travels with its decomposition.
Mercury's headline rate appears nowhere on the page without the
malformed decomposition beside it (C-5). The unconditional 51.9%
figure appears nowhere as a figure. The literal string survives
only inside decomposition text, in a heatmap tooltip that reads
"51.9% of counted flips to malformed output", exactly as it did
on the board before the redesign. The render law derives the
flagged figures from the payload and fails wherever one prints
without its decomposition in the same carrier.

**Numbers are tabular, ids are mono, summaries are derived.** Every
figure uses tabular numerals. Run ids and model slugs render in the
mono face. The one summary line a surface is allowed is computed
from the payload in front of it, never written down in advance.

**Names are evidence.** A model name wraps anywhere it needs to and
is never ellipsized into ambiguity. Status and hint lines may
ellipsize. Names may not. Vendor and model marks ride on every row,
card, and chart label, as before.

**Sections are numbered by position, not by hand.** The section
labels number themselves with a CSS counter in DOM order, so
inserting or removing a section renumbers the page instead of
leaving a wrong numeral behind.

**The law is tests.** `site/board/tests/render-law.mjs` drives the
built board over raw Chrome DevTools Protocol (the sandbox's
puppeteer build cannot navigate on this machine, and the harness
needs no dependencies beyond Node and a Chromium binary) and
asserts, on the real 43-row payload, the following. Zero uncaught
page errors at 390, 500, 700, 800, 900, 1000, 1280 and 1440. No
document-level horizontal overflow at any of those widths. Every
charted result named exactly once inside the visible scatter
variant at every width. The suite case count visible only inside
Method. The flagged figure rules above. Every interactive control
at 390 with a coarse pointer standing at least 44px. Every printed
heat cell clearing 4.5 to 1 contrast. At most one filled-accent
control in the first viewport.

## The naming problem, solved as tiers

The old wide solver threw when a point could be named in none of
its seats, and the throw unmounted the page. On the 43-row payload
that happened at fitted widths, roughly 800 to 900px. A name is
not optional, so the redesign makes unnameability structurally
impossible instead of handling it as an error. Every band names in
tiers, and the last tier cannot fill up.

- **Wide geometry (container 1020px and up).** Points are named
  beside their discs in the plot. Results with no recorded cost sit
  in the rail at the right and are named in place. Points that seat
  in neither go to the in-SVG overflow rows beneath the plot.
- **Fitted geometry (761 to 1019px).** The same tiers, plus the new
  last tier. A fitted HTML list sits directly under the chart,
  inside the same panel. Each row is the point's own disc glyph,
  its full name (wrapping anywhere), its figures in words, and its
  flagged standing where it has one. A row is a button and carries
  the point into the same inspector the plot points open. On this
  payload, with the corner furniture gone and the fitted chart
  grown taller, the in-SVG overflow rows seat every name at 800
  and 900px and the list renders empty. The list is the structural
  guarantee behind them, there for the denser payload where the
  rows also fill. What ended the throw is that unseatable is now a
  routing, not an error.
- **Phone (760px and down).** The geometry was already
  list-shaped. A subset names beside discs in the compressed plot,
  and every result, plotted or railed, also stands in the full
  list under the plot inside the SVG. The redesign keeps that
  shape and stands the list rows at a 46px pitch with a 44px hit
  height (the pitch was 34px, and the render law caught it).

The solver no longer throws anywhere. Points it cannot seat flow
to the next tier by construction.

## Hardcodes designed out (the audit's F1 to F9)

- **F1 and F2, the chart corners.** The SVG corner readings
  ("held at twenty cents a run" and its three siblings) are deleted
  from the chart. Readings survive as an HTML strip above the chart
  whose every clause is computed from the payload. The clauses are
  the priciest run, the most flipped ranked run, the toughest
  ranked run, and the cheapest recorded-cost run. The strip prints
  the combined sentence only when the payload makes the combined
  claim true and prints the facts separately when it does not. On
  this payload fable is both priciest and most flipped, so the
  combined form prints, derived.
- **F3, the Method re-run paragraph.** Deleted. It hardcoded a
  count, two model names and a date into standing prose.
  `check-integrity.mjs` no longer asserts its anchor, with the
  reason recorded at the edit.
- **F4, the footer change claim.** The "What changed" paragraph
  that asserted specific reruns and results is replaced with a
  process line that claims nothing about any population.
- **F5, the fixed axis.** The attack-success axis derived its
  ceiling from a constant 0.3. `lib/chart.ts` now derives it. It
  takes the smallest tenth at or above the worst ranked rate,
  floored at 0.3, with ticks to match. On this payload the
  derivation returns exactly 0.3, so today's geometry is
  unchanged. When a ranked result lands above 0.3 the axis grows
  instead of clipping. Ranked bars, whiskers, and both scatter
  variants all read the same derivation. Anything past the scale
  says so in words. A bar's caption states its rate sits above
  the chart's scale, and the scatter caption names the off-scale
  results (on this payload, mercury-3's flagged point).
- **F8, "ran locally".** The scatter caption claimed a provenance
  the payload does not carry. It now states the recorded fact.
  The cost is $0.00 or no cost was recorded.
- **F6** is in `gen-og.mjs`, another lane's file, and out of scope
  here. **F9** is the publish tree's staged image, likewise.
- **F7, the compare default, reversed in repair round 3.**
  The first build left the compare section's default second
  model keyed to one run's name, and this record called the
  choice deliberate. The checkpoint reviews reversed it. The
  default is now the highest-ranked unflagged result other
  than the first, derived from the payload's own ranking,
  with the old fallbacks kept behind it. On this payload the
  resting pair moves from gpt-5.6-terra against jev-1.14.0
  to gpt-5.6-terra against gpt-6.1-sol. `check-integrity.mjs`
  derives the same expectation from the payload and asserts
  it, so the gate tracks the rule rather than the name.

## The heat ramp inverts for paper (first build, with the original ramp restored by the iteration)

The heat ramp was built for a dark ground (bright cells, dark
text). On paper it re-derives as a warm ramp from cream to deep
brown with the same stepped construction. The text tone flips from
paper to ink at one computed step (the step sits between the 0.55
and 0.62 stops), so every printed cell keeps at least 4.5 to 1
against its own background. The render law measures the printed
pairs in the rendered page rather than trusting the arithmetic.

The iteration deletes this inversion. `lib/charts.ts` carries
the original dark-ground ramp again, stops, step and text
tones unchanged from main.

## Deliberate deviations from the current board

1. Dark theme to paper theme, wholesale (above). Reverted by the
   iteration. The standing dark scheme is restored in full, and
   this deviation no longer describes the tree.
2. Chart corner readings removed from the SVG into a derived HTML
   strip (F1 and F2).
3. The fitted scatter gains the HTML naming list at 761 to
   1019px. The wide geometry can reach the same list on a denser
   future payload. Nothing unnames, anywhere.
4. Phone scatter list rows grow from a 34px pitch to a 46px
   pitch, with a 44px hit height.
5. The attack-success axis ceiling is derived, not fixed (F5), and
   off-scale results disclose themselves in words.
6. Method loses the re-run subsection (F3). The footer loses its
   change claims (F4). The scatter caption loses "ran locally"
   (F8).
7. Section numbers are counted by CSS from DOM order rather than
   written into each label.
8. Marker discs carry a translucent stroke, one shared constant,
   so a disc of any maker colour separates from the ground. The
   first build toned it for paper. The iteration restored the
   standing tone.
9. Coarse pointers get a standing 44px floor for buttons, selects,
   nav links, and list rows. The old stylesheet had no
   coarse-pointer rules at all.

## Where the Maidan transfer fought the data

Stated plainly, per the brief.

- **Maidan's anti-table stance did not transfer, on purpose.** The
  study itself flags this. A board whose readers compare 43
  results needs the table. The redesign keeps the ranking table
  and changes its material, not its kind.
- **Maidan's density did not transfer either.** Nothing in Maidan
  names 37 points inside one chart. Peira's name-everything law
  (doctrine D3) is stricter than anything the study found, and it
  is the law that broke the old solver. The tiered list is the
  invention the collision forced. Maidan contributed the ethic
  (a name wraps, never truncates, and a list is a first-class
  surface), not the mechanism.
- **Steel did not transfer. Paper did.** The study's own line is
  that Maidan's material is the message. What transferred is the
  discipline underneath the material. One accent with a budget,
  hairlines instead of boxes, state in words, law written as
  tests.
- **The fitted band is where the fight was real.** At 1020px and
  up the old geometry seats this payload comfortably. At phone
  widths the list doctrine already held. Between 761 and 1019 the
  plot is too narrow for beside-disc labels and too wide for the
  phone's compressed shape, which is exactly where the throw
  lived. The HTML list is deliberately plain there. It is a fitted
  table of names and figures, not a chart trick.

## Verification (first build)

All on the first build's tree, against the real 43-row payload.
The iteration's verification stands in the iteration note at
the top of this file.

- `next build` ran clean, 48 pages.
- `check-integrity.mjs` passed (43 rows, counts 42/36/6, 31
  taxes recomputed, max deviation 0.00000, compare dataset and
  11 rendered deltas verified).
- `check-budget.mjs` passed. `check-vendor-agreement.mjs`
  passed (all 43 rows agree across page marks, page colors and
  the share image). `check_public_surface.py` passed.
- `tests/render-law.mjs` passed at all widths. All assertions
  passed at 390, 500, 700, 800, 900, 1000, 1280 and 1440, with
  zero page errors, no document-level overflow, 37 of 37
  charted results named exactly once in the visible scatter
  variant at every width, the case count confined to Method,
  no bare flagged figure, every control at 390 coarse at 44px
  or taller, every printed heat cell at 4.5 to 1 or better,
  and at most one filled-accent control in the first viewport.
- Public copy scanned by codepoint found no em or en dashes in
  any changed file (the two em dashes in `check-integrity.mjs`
  comments predate this branch and are not rendered copy).
- Screenshots sit in `shots/`. They cover the full board and
  every section at 1440 and 390, plus the cost section at 800
  and 900 (24 files). The set was eyeballed. It shows the paper
  theme, the derived readings strip, the overflow rows naming
  mercury-3 with its flagged standing at both fitted widths,
  the phone list at full touch height, and mercury's ranking
  row carrying its malformed decomposition beside the 52.3%
  headline with the above-scale sentence in words.

The legacy harness `scripts/audit-dom.mjs` was also run, left
untouched rather than weakened. Its naming, overflow, touch,
text-spacing, card-motion, and phone-interaction blocks all pass
on the redesign. It reports 70 problems in three classes, none of
them a naming failure.

1. **Its amber constant is the old theme's.** audit-dom compares
   computed colors against the dark theme's amber,
   `rgb(232, 163, 61)`. The paper theme's amber is `#b45309` by
   design (the old value fails as text on cream), so every
   "lacks its amber ring" and "malformed value is not amber"
   finding is the palette change it cannot see. The rings and
   values are amber in the rendered page, as the screenshots
   show. Whoever lands this re-points the constant at the token.
2. **The corner type floor has nothing to measure.** audit-dom
   measures the scatter corner sub-text, deleted by design (F1
   and F2). Expected divergence.
3. **The mercury whisker overshoot is pre-existing.** The same
   100.19 against a 100.00 cap that the perfection program
   already carries as a Cycle 8 item on the unmodified board
   (100.26 at 900 on pixel rounding). The redesign preserves the
   whisker math exactly at this payload's derived axis, so the
   defect carries unchanged. It is not introduced here and not
   fixed here.

## Docs note for whoever lands this

Per the repo's documentation map, a leaderboard or ranking-rule
change updates `docs/Admission-Rules.md`. This build changes no
ranking rule and no reported number's meaning. It changes a chart
scale from fixed to derived and removes three pieces of standing
prose. If it lands, that map entry deserves a reviewer's look
rather than an automatic edit.

## Cleanup addendum, 2026-10-30

A cleanup round followed the iteration's re-reviews. The Spec
axis passed. The Standards axis passed with five Minors. The red
team failed the build on one Major, RT-F2 in its compare form,
and this round answers it.

**The compare view printed flagged figures bare.** A flagged
result is selectable in the compare view, through the Flagged
group in its pickers and through shared compare links, and the
section printed its attack success figure with only a standing
note beside it. The section now follows the pattern the ranking
rows and model cards already use. A note under the pickers
states each flagged side's decomposition beside its figure,
with the genuine flip rate and the share of counted flips to
malformed output, derived from the payload by the shared
lib/payload function. The family lines carry each family
figure's own decomposition in the line's title. Where the
sealed records derive no decomposition for a flagged side, the
section states the flagged standing and prints no whole figure,
and a family whose records derive none prints no figure on its
line. That is the standing rule the scatter follows.

**Law 5 now drives the compare view.** The render law's fifth
law gains an interaction pass. It selects a flagged result in
the compare view through the view's own picker and asserts the
standing and the decomposition clauses inside the section, and
the decomposition in each family line's title. Against the
pre-fix export the pass fails on the standing, on the missing
decomposition, and on all eleven family lines. On the fixed
tree it passes inside the full build. Real coverage widened
here. The fifth law's carrier fallback also tightened in this
round. It once accepted any carrier text holding the two words
genuine and malformed, and it now requires the decomposition's
own clauses with the payload-derived figures, the same clauses
the primary test requires. The law's header states exactly
what it enforces. check-integrity remains the gate of record
for C-5, and the documented narrowing of the fifth law's
carrier coverage stands as recorded, so that Minor needed no
code.

**Law 8 fails loudly on an unreadable accent.** When the page's
accent token cannot be parsed into a colour, the eighth law now
fails and names the token, instead of comparing a raw string
and silently counting zero.

**This record now follows the public copy bar.** This file
ships in a public repo, so the copy bar applies to it. Its
prose colons and semicolons are rewritten as short sentences
throughout, with the technical content unchanged. Colon
lead-ins inside code comments in code files are punctuation,
not prose, and stay out of this pass's scope. The one semicolon
in the render law's fifth-law comment block is removed. The
tip commit's message lost its semicolon by amendment, after a
check confirmed no pull request exists for this branch.

## Repair round 2 addendum, 2026-10-30

A second repair round followed the red team's spot-check of
the cleanup. The spot-check passed the compare closure and
the mutation tests, and it failed three smaller things. This
round answers all three.

**Law 8's loud failure now fires.** The eighth law compared
the probe element's computed colour against the sentinel
literal it had assigned. The browser serialises that sentinel
at its own precision, so the comparison could never match and
an unparseable accent token still counted zero in silence.
The probe now captures the sentinel's computed form before
the token is applied and compares against the capture. A
build carrying an unparseable token fails at every width and
names the token. The shipped token passes.

**Law 5 drives both compare pickers.** The interaction pass
held only side A of the compare view, so a missing note on
side B passed unseen. The pass now drives picker B to a
second flagged result while side A keeps the first, and it
reads side B's own flagged note element directly. Deleting
side B's note fails the pass in a mutation run of this round.

**The compare header keeps its names.** At phone widths the
restacked header cells were sized by the fixed layout
table's column grid at one column's width. The names ran
left past the cell and the section edge and were clipped
there, at every width from 360 to 640, and no document
overflow grew for any law to see. The table is a block at
phone width and the body carries the fixed layout as a
table of its own, so each header cell spans the section. A
name longer than the line wraps anywhere inside its cell,
and the vendor chip, the wire line, and the flagged tag stay
inside the cell with it. The desktop table is unchanged.

**Law 10 measures the compare header.** A tenth law reads
the header cells at 360 to 640, on the resting pair and on
the longest named pair the pickers hold. The name span, the
name text, the vendor chip, the wire line, and the flagged
tag must sit inside their cell. Against the pre-fix build
the law fails 37 times. On the fixed tree it passes inside
the full build.

## Repair round 3 addendum, 2026-10-30

A third repair round followed the three checkpoint reviews
of the rebased tree. The red team failed the build on one
Major, and this round answers it together with the
reviews' Minors.

**The models index summary carries the decomposition.**
The index summary line over each collapsed card printed a
flagged result's headline figure bare, in its visible text
and its accessible label, while the decomposition sat in
the collapsed card body beneath it. The summary now
follows the compare rule. A flagged figure prints only
with its genuine flip rate and the malformed share of
counted flips on the same line, and where the sealed
records derive no decomposition the summary prints no
figure. Law 5 counts the summary as a carrier of its own,
so the pairing is enforced on the line a scanning reader
actually sees.

**The ranking row and the card suppress as well.** RankRow
and ModelCard printed a flagged figure unconditionally and
leaned on Law 5 alone to catch an underivable
decomposition. Both now derive or suppress in the
component, in the value cell, the accessible name, and
the card headline, so the law stands as a backstop rather
than the only barrier.

**The readings strip scopes its superlatives.** The
toughest and most flipped ranked results derive over the
full suite ranked group alone, while ranked slices sit
lower. The strip now prints the scope inside each ranked
claim, and the scope phrase is assembled at the derivation
site from the groups the derivation consumed.

**The compare default derives.** See the F7 entry above.

**The laws gained floors and one driver.** Law 7 fails
when it finds no printed heat cells to measure. Law 10
fails when a part every header carries (the name span,
the name text, the vendor chip) is absent on either side,
instead of skipping it. The Law 5 interaction's two
near-verbatim side blocks are one parameterised driver,
and side A now reads its own flagged note element
directly, as side B already did.

**The axis scale is built once.** The axis helper in
`lib/chart.ts` holds one scale per axis maximum at module
level instead of constructing a scale on every call.

## Repair round 4 addendum, 2026-10-31

A fourth repair round followed the round 3 spot-checks.
The red team failed the build on one Major inside the
expanded card body, and this round answers it together
with the Spec axis's evidence Major and its readings
Minor.

**The card spark list carries the pairing.** The
expanded card's Attack success by family list printed
a flagged result's per-family attack success bare,
while both gates keyed on the whole-row figure only.
Each flagged spark row now carries its family's own
decomposition in its title, the clauses the heat cell
titles carry, and a family whose sealed records
derive no decomposition renders suppressed, dashes
for its value and no figure, its title stating that
the figure is not stated and why. The list stands as
its own carrier (`data-spark-for`). Law 5 judges it
family by family, and check-integrity asserts the
same pairing on the index cards and the model pages.

**The readings scope derives from the input.** The
scope phrase for the ranked superlatives is assembled
from the named segments the ranked derivation
consumed, not from a literal written at the call
site, so the printed scope follows the derivation
population by construction. The printed words on the
standing payload are unchanged.
