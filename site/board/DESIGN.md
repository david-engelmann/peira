---
version: alpha
name: Peira benchmark board
description: Design tokens and law for the peira benchmark board, an Operate surface where charts carry the page and every figure is evidence.
colors:
  ground: "#05070a"
  panel: "#0c1015"
  panel-2: "#141a21"
  lift: "#1a222c"
  hairline: "#232c35"
  edge: "rgba(255, 255, 255, 0.08)"
  edge-soft: "rgba(255, 255, 255, 0.05)"
  ink-1: "#eef2f6"
  ink-2: "#aebcc7"
  ink-3: "#71808f"
  accent: "#2fbf71"
  amber: "#e8a33d"
  chart-grid: "#232c35"
  chart-axis: "#232c35"
  chart-tick: "#71808f"
  chart-glyph-dark: "#0b0e12"
  chart-glyph-light: "#f4f7fa"
  chart-field: "#39434e"
  chart-subject: "#ffffff"
  seg-genuine: "#31404f"
  chart-series-anthropic: "#d97757"
  chart-series-openai: "#d7e0e8"
  chart-series-google: "#8ab8ff"
  chart-series-meta: "#4a7dff"
  chart-series-mistral: "#ff8a3d"
  chart-series-deepseek: "#6e7bff"
  chart-series-fallback: "#8b98a5"
typography:
  display:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "5.25rem"
    fontWeight: 800
    lineHeight: 0.98
    letterSpacing: "-0.055em"
  scene-head:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "4.25rem"
    fontWeight: 800
    lineHeight: 0.98
    letterSpacing: "-0.055em"
  heading:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-0.018em"
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 400
    lineHeight: 1.45
  caption:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "12px"
  micro:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "11.5px"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "0.14em"
  data-figures:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontFeature: "\"tnum\" 1"
rounded:
  ctl: "6px"
  panel: "10px"
  pill: "999px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "24px"
  space-6: "32px"
  space-7: "48px"
  space-8: "64px"
  space-9: "96px"
components:
  well:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-5}"
  panel-row:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-4}"
  detail-card:
    backgroundColor: "{colors.lift}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-4}"
  chip:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.ctl}"
    padding: "{spacing.space-2}"
  chart-gridline:
    backgroundColor: "{colors.chart-grid}"
    height: "1px"
  chart-axis-label:
    textColor: "{colors.chart-tick}"
    typography: "{typography.micro}"
  scatter-disc-field:
    backgroundColor: "{colors.chart-field}"
    rounded: "{rounded.pill}"
  scatter-disc-subject:
    backgroundColor: "{colors.chart-subject}"
    rounded: "{rounded.pill}"
  vendor-chip-anthropic:
    backgroundColor: "{colors.chart-series-anthropic}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-openai:
    backgroundColor: "{colors.chart-series-openai}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-google:
    backgroundColor: "{colors.chart-series-google}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-meta:
    backgroundColor: "{colors.chart-series-meta}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-mistral:
    backgroundColor: "{colors.chart-series-mistral}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-deepseek:
    backgroundColor: "{colors.chart-series-deepseek}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-fallback:
    backgroundColor: "{colors.chart-series-fallback}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  chart-axis-line:
    backgroundColor: "{colors.chart-axis}"
    height: "1px"
  primary-control:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  finding-link:
    textColor: "{colors.ink-1}"
    typography: "{typography.body}"
  caption-note:
    textColor: "{colors.ink-3}"
    typography: "{typography.caption}"
  well-divider:
    backgroundColor: "{colors.edge-soft}"
    height: "1px"
  hairline-rule:
    backgroundColor: "{colors.hairline}"
    height: "1px"
  edge-strip:
    backgroundColor: "{colors.edge}"
    height: "1px"
  page:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink-1}"
  scene-lede:
    textColor: "{colors.ink-2}"
    typography: "{typography.body}"
  flagged-divider:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.amber}"
    rounded: "{rounded.panel}"
  split-bar-genuine:
    backgroundColor: "{colors.seg-genuine}"
    rounded: "{rounded.pill}"
---

# Peira benchmark board

## Overview

This file is the board's design system in one place. Tokens live in the front matter above. The law lives in the sections below. A lane building board UI reads this file and `PRODUCT.md` beside it, builds only from these tokens, and runs the gates in the house kit's `gates/GATES.md`.

The board is an Operate surface in Impeccable's mode terms. It is read and worked, not admired. Results open the page, the explorer follows as the full record, the findings stand after it as evidence, and Method closes it. Model addresses are deep links into the one explorer. Guard results are one population inside the explorer, reached by its filter. Method states each rule once and per result facts live on the results.

Token values were re-derived on 2026-11-08 from the shipped board on main, the stylesheet at `site/board/app/globals.css` and the vendor table at `site/board/lib/vendor-data.json`, in the coherence re-score of the shipped board. The extracted tokens, colors, type, shadows, and geometry, are the board's real values. The four divergences an earlier version of this file stated against the shipped CSS, the missing motion token layer, the reduced motion kill switch, the gradient washes, and the off ladder radii, are cured in the shipped board and leave the record here. The three divergences the re-score then stated against the shipped code are cured in the shipped code as well, and leave the record here in their turn. The masthead frost transition ran at a hardcoded 300ms over the motion cap in Data & Motion, item F7 on the coherence re-score list, and now spends the entrance token at the cap. The detail card did not meet its keyboard contract, item F2, and now meets it, as Components states. Five vendor families stood under the contrast floor on the tint chip, item F5, and the chip's mark is now derived to the floor, as Colors states. Two divergences stand open, both in the chart's sync list, and in each the law in this file is the side that stands. The sync list omits the cost the scatter plots, stated in Data & Motion, and a flagged result stands in it with no label, stated in PRODUCT.md.

This file carries no colors.primary token, deliberately. The accent token carries the primary role. The design linter at its pinned version raises a missing-primary warning on this file, and the warning is expected and waived on the record in the kit's gates file. Agents must not auto-generate a primary token here.

## Colors

The surface ladder is assigned, never improvised. Ground is the page. Panel is a well's floor. Panel 2 separates elements inside a well, and the stylesheet spends it on tracks, inputs, rail rows, hover grounds, and delta rows. Lift is reserved for the floating elements, the scatter detail chip, the comparison tray, and the phone foot strip. No section invents a gradient or tint of its own.

The sticky nav is not a ladder element. It is the frosted bar, the board's one sanctioned frost, in the pattern source's material. At rest it is transparent over the first screen. On scroll it takes the ground color at 82 percent opacity, with a backdrop blur of 24px and saturate at 1.8, over a hairline bottom edge in the soft line step. The glassmorphism ban in the Don't list does not reach it. No other surface takes the frost.

Ink comes in three steps. Ink 1 is body and data text. Ink 2 is secondary text and chip text. Ink 3 is furniture, ticks, and captions. Structural elements such as gridlines, tracks, and panel grounds are grayscale. Color is data or identity, never decoration. The stylesheet folds the hairline, chart grid, and chart axis tokens into one line variable, and the edge-soft token into its soft line variable. The values agree, and this file's vocabulary is the record.

Accent marks the primary reading path. Amber means flagged and nothing else, everywhere, including in motion. No animation may flash, pulse, or sweep amber or accent across data. State changes use ink and surface steps, not accent color, unless the element is itself the primary control.

Maker identity rides every figure, in the form each surface carries. On the scatter, the field is one grey, the chart-field value, dimmed around the selected result, and the selected result is the one white disc in chart-subject white. Every disc carries its maker's mark. A logo glyph is drawn in ink 2 on a field disc and in the dark glyph ink on the subject. A monogram letter is drawn in chart-glyph-light on a field disc and in the dark glyph ink on the subject. A flagged disc takes an amber stroke. On rows, cards, and bars the maker rides as the vendor chip, and the family hue lives in the one vendor table. Families render as a bar list and calibration as a figure column, and identity reaches both through the row's chip and name. The chart series tokens above carry the lead families and the fallback. The full family list lives in `lib/vendor-data.json` and this file names the pattern, one hue per family, keyed by family name. A figure that hides its makers' identity entirely diverges from this file. The scatter's grey field is the sanctioned composition, not a divergence.

The vendor chip is a tint, not a solid. Its ground is a 16 percent color-mix of the family color over the panel, its border is a 42 percent color-mix of the same color, and its mark or monogram letter is drawn in the mark color derived from the family color against the floor stated below. It renders at 22px, 30px, and 44px in its mini, row, and card forms. The vendor-chip tokens in the front matter record the solid pair, the family ground with its paired glyph ink, and for the seven lead families the tokens pair every family with the dark glyph ink. The vendor table is the operative assignment where the two differ, and it assigns the light glyph ink to anthropic, meta, and deepseek. Surfaces filled with a solid family color, as the share image's big discs are, take their glyph ink from chart-glyph-dark or chart-glyph-light, whichever the family table assigns.

The contrast floor in Typography binds the chip's mark on its tint, without a split by kind, and the shipped code now meets it by derivation rather than by exception. The mark is the family color lightened toward white by the smallest five percent step that clears 4.5 to 1 against the tint ground, computed in the code from the family color alone, so a re-sampled family color takes its new mark with it and no per family exception is recorded anywhere. Five families stood under the floor in the family color itself, protectai at 2.34 to 1, zhipu at 3.60, upstage at 3.77, meta at 4.30, and deepseek at 4.47. The derivation moves exactly those five. Protectai lightens six steps to 4.57, zhipu three steps to 4.56, upstage three steps to 4.78, meta one step to 4.64, and deepseek one step to 4.81. Every other family and the fallback clear the floor unlightened, the lowest of them minimax at 4.73. No ground adjusts here, and the chipColor cure an earlier version of this file recorded, with its two adjusted values, stays deleted from the record, because the shipped vendor table carries no such field and needs none. The cure is item F5 on the coherence re-score list, landed. On the scatter itself the marks are comfortable, the monogram letter at 9.36 to 1 on the field disc and the logo glyph at 5.18 to 1.

The split bar's genuine segment takes the seg-genuine slate, a token spent only there and in the anatomy row's abstain slot. Two tokens the converged file carried, accent-bright and red, name values no shipped surface consumes, checked across the stylesheet, the components, and the data tables. They leave the front matter in this rewrite, and the removal stands on the record here. The brand mark is an asset, not a component. Its ground #0A0C0F is an asset constant carried in the mark's own files, outside the token ladder, and its bars stand in ink 1 on a field at the panel radius, the values item F3 on the coherence re-score list set and the shipped mark now carries.

## Typography

Two families do all the work. Archivo carries data, prose, and display. JetBrains Mono carries labels, eyebrows, and stamps, and the figures that stand inside list contexts, the rail rows, the sync rows, the family values, and the cost rows. Figures inside result rows and readings speak Archivo in tabular figures. Mono never carries a prose line.

Inside any chart there are exactly three text sizes, the axis and label size, the caption size, and the chart's title or finding size. No type in a section is larger than its finding or title. Data text is one uniform body size throughout a chart, and table headers are the smallest text in the table, kept readable by being short.

Floors are absolute. No rendered text under 10px at desktop widths or at 390. Low contrast small text fails at any size it cannot be read at a glance. Contrast meets 4.5 to 1, including placeholder text, and the tint chip's mark is derived to the same floor, as Colors states. Display type is fluid, and its clamps are the law. The display token's dimension in the front matter carries the clamp's ceiling, 5.25rem, because the file's format holds one dimension per token and cannot hold the clamp itself. The full clamp, from 3rem through 7.5vw to 5.25rem, 48px to 84px, is the token's value in force, at weight 800, with tracking at -0.055em and line height at 0.98. The scene head token carries its ceiling the same way, 4.25rem, and its clamp runs from 2.5rem through 5.2vw to 4.25rem, 40px to 68px, at the same weight, tracking, and line height. The plain heading is a fixed step, 30px at weight 700, stepping to 25px at phone widths by media rule. No display size exceeds its clamp's top step.

The working scale under the clamps runs 11.5, 12, 12.5, 13.5, 14.5, 16, 17, 20, 30, and 36px, with weights from 500 to 800. The 750 weight carries the money shot numerals, the stack figures at their own clamp from 44px to 64px, the in-bar figure from 24px to 30px, and the reading figures. A new size or weight joins the scale through a change to this file, not through a value pasted into a component.

Numbers render in tabular figures in their final form in the first frame they are visible. Names never break mid token. If a name does not fit, the layout changes, by a wider slot, a shorter sanctioned name form, or list form.

Data lines speak one dialect wherever the figures appear as a set. Spaced, sentence case labels, interval in brackets. Rates print at one decimal with their interval. Costs print by the kind law in Data & Motion, never in one flat format. No figure carries digits no reader can act on.

## Layout

The page column is 1180px at most, with 24px side padding. Section spacing comes from the 4px based scale in the front matter, tokens space-1 through space-9. The one section gap is 48px on both sides of the scene hairline and stays. Every internal gap snaps to the scale. Where a section has a rail beside a grid, rail and grid share one top baseline. Two composition values stand outside the scale as named exceptions in the pattern source's grammar. The hero's top padding is 48px, and the scene anchor offset is 84px.

Nothing extends past the section edge at any audited width. Zero elements beyond either edge, measured in the DOM and confirmed on the render. If a chart's mandatory label set cannot clear at a width, the chart changes shape, by faceting, splitting the population, or demoting to a ranked list. Type, label, and point sizes never shrink to fit a population.

Three collapse breakpoints carry the responsive law, stated here and worked in Responsive Behavior. At 1080px the rank grid sheds its benign and calibration columns. Columns leave rather than shrink, and the surviving columns keep the widths their labels and figures measured. At 980px the chart and its sync list stack, the sync list capped at 300px tall, and the compare columns stack. At 760px the ladder reflows to cards and the reading becomes a bottom sheet.

## Elevation & Depth

Elevation is the surface ladder plus its three shadows, and nothing else. Wells sit flat on panel. Raised elements inside a well take the first shadow step at most. The floating elements, the detail chip, the comparison tray, and the phone foot strip, sit on lift and take the deeper steps. The masthead takes no shadow and no ladder step, and its frost is a material, stated in Colors. A section may not invent its own shadow, tint, or gradient wash.

The shadow values, extracted with the tokens above.

- First step, 0 1px 2px rgba(0, 0, 0, 0.35), 0 4px 14px rgba(0, 0, 0, 0.22).
- Second step, 0 2px 6px rgba(0, 0, 0, 0.4), 0 14px 34px rgba(0, 0, 0, 0.3).
- Third step, 0 8px 18px rgba(0, 0, 0, 0.5), 0 28px 64px rgba(0, 0, 0, 0.42).

## Shapes

The radius ladder has three values and a circle. Control radius 6px for controls, chips, and small elements. Panel radius 10px for panels, cards, wells, and figures. Pill radius 999px for pills, and for the tracks and whiskers that read as pills, the plain split bar track, the family tracks, and the interval whiskers. Discs and dots are circles at 50 percent, which are circles, not corners. Every other radius value is deleted wherever it survives in the stylesheet. A grep for border-radius values outside this set fails review.

## Components

One sanctioned container holds data. The panel is a bordered card at panel radius on panel ground, and it carries figures and lists alike, the findings, the leader cards, the share card, the result rows, the family rows, the chart wrap, the sync panel, and the below-reading panel, with the population dividers taking the same idea at control radius. A reader scrolling the page meets exactly one container idea. The row list of hairline ruled rows directly on ground, the converged design's list container, is retired law. The shipped result rows are panels standing 8px apart, and each row opens its reading as a ruled region on the soft hairline, the page's only hairline ruled treatment.

The page below the hero is numbered scenes. Each scene opens with a mono eyebrow whose number is spent in the accent, one display claim, and one short lede, and a hairline at the section gap separates the scenes. The scenes stand in page order as 01 Results, 02 Explorer, 03 Findings, and 04 Method. A scene's claim heading is a derived result, stated from the payload the scene presents. A heading that states a figure the payload does not carry fails the evidence law in Data & Motion.

The share card stack is the Results scene's object. Each entry is a label, a name with its vendor chip, one large tabular numeral at the stack clamp, and a caption. The flagged lead's entry carries the figured split bar, its track at panel radius and 48px tall, the malformed share set large inside the malformed segment as the in-bar figure in the dark glyph ink, and both segment shares labeled under the bar with their bases stated in words.

The detail card is the board's one popover. It is one object with changing contents, not a new card per point. It carries a visible close control, tap outside dismisses, and Escape dismisses. Keyboard focus produces the identical card with the identical contract, and the shipped card meets it. Every disc is a focusable button, focus raises the same card the pointer raises, Enter and Space pin it as a click does, one dismissal path serves the close control, tap outside, and Escape alike, the Dismiss control stands in the hover state and the pinned state alike, and a keyboard dismissal returns focus to the disc that raised the card. Its figures are also reachable by keyboard through the sync list and the rail buttons, which open the same reading below the chart. The contract is item F2 on the coherence re-score list, landed.

Results that stand off the scatter's cost axis sit below the chart in the rail, under headed groups by cost kind. Measured through a harness, No API cost, and No recorded cost, each with its own explanatory note, and a group renders only when it holds a result. The current payload holds no harness result, so that group does not render. The rail's law is the cost kind law in Data & Motion.

Every figure caption is one or two declarative sentences stating what the figure shows and the one caveat that matters, placed directly under its figure, in the caption style. Methodological essays live in Method, not under figures.

Labels follow the label law. Clearance is absolute, no label's rendered box intersects any disc, label, axis, gridline, or furniture at any audited width, and a label that cannot clear is not placed. Labels are chosen by a selection rule stated before rendering, the extremes of both axes, every flagged result, and the best result per maker always label. No leader lines anywhere. A model is named at most once per surface per width. Labels carry names, not numbers. The one exception is the subject's sub label on the scatter, which carries the subject's rate and cost text as the chart's one figured label.

Chart form follows the reader's question. Lookup gets the list twin. Pattern gets a chart. Two item comparison gets paired bars on a shared scale. Per model detail gets small multiples sharing one scale and one key. Every chart head states the question and the population before any axis is read. Every scale carries its key inside the figure, because charts travel without prose. Absence is a visible, named state, a deliberate mark in the cell's position, never a faint speck or an empty slot.

## Do's and Don'ts

### Do

- Build only from the tokens in this file, and send any new value through a change to this file first.
- Give every chart its list twin with the same figures.
- State each fact once per view, in its one place.
- Verify rendered at 1440, 1280, and 390 before calling a change done.

### Don't

- Invent a number, a count, or a figure the payload does not carry.
- Repeat a headline figure in the same row's small print.
- Use glassmorphism as a default material anywhere outside the masthead's one sanctioned frost, a hero metric template as decoration, identical card grids, or eyebrow scaffolding.
- Add a second accent, a bespoke gradient, or a per section tint.
- Put internal language on the public face, no lane names, worktree paths, decision codes, draft markers, or approval states.

## Responsive Behavior

Three widths govern. Desktop at 1440, laptop at 1280, phone at 390. Phone is a re-flow, never a squeeze. Any component that cannot fit 390 without clipping either edge gets a phone specific layout.

Sticky chrome may not hide content. The masthead sticks in flow rather than fixing, so at rest it hides nothing. While the page scrolls, the scenes pass under its frost, and scene anchors clear it by the 84px scroll margin, so a jumped-to scene head never lands beneath it. A nav that cannot show all its links at 390 shows the ones that fit plus one overflow affordance, and a link cut mid word is a defect. At phone widths the reading opens as a bottom sheet over the foot strip, and coarse pointers raise every target to 44px.

At phone widths the hero's top padding is 24px. At phone widths the Results scene's gap is 24px on both sides of its hairline. At phone widths the leader cards' vertical padding is 16px, and their horizontal padding stays at 24px.

The motion contract is identical at phone width. Distance does not shrink and duration does not grow. Board changes are verified by an interactive touch session at 390x844, card opens on tap, switches, dismisses by tap outside and by its close control, and Escape dismisses it under keyboard, plus rendered inspection at all three widths. Static renders and desktop mouse passes do not verify the phone experience.

## Data & Motion

The evidence law, in force on every board surface.

- Charts carry the page. Prose is cut to labels and captions.
- Figures never animate.
- Motion only on interface state changes, re-sorts, filters, selection, and mode switches. Payload data changes never animate. No ambient motion.
- Every number on the surface traces to a data field in the sealed payload. If it cannot be traced, it does not ship.
- Every chart ships with its list twin. The list twin is the board's data table alternative, a list carrying the chart's results in the same order with their stated figures, as the sync list stands beside the scatter. The sync list states attack success and omits the cost the scatter plots on its axis, and that omission stands as a recorded divergence. The board carries no table element, by design.

Cost kinds. A result's cost prints in one of five states, and the states never share a figure or a wording. A recorded total prints as a dollar figure. A recorded total with unpriced calls prints as a lower bound, marked wherever it prints. A result measured through an agent harness prints its plan basis in words and never a figure, because the run is billed through the plan that carries the harness and its cost is real and not metered per run. A result served locally prints that it carries no API cost. A result with no cost recorded prints as unrecorded, in words. A recorded zero never renders as a dollar figure, and none of the unpriced states stands at zero on the cost axis. Method's Costs passage is this law stated for readers.

Basis wording. Every decomposition states both of its bases in words wherever it prints, on the board and on the share image alike. A genuine share is stated as a share of counted flips or as a rate over eligible cases, in the words of its own basis, and the two never stand in one sentence with only one basis named. A headline rate for a result whose flips are mostly malformed output never appears without its malformed share beside it.

The motion tokens behind the law. Durations are 120ms for micro feedback, 200ms for state changes, and 280ms for entrance, and no duration on the board exceeds 280ms. Exits run at 0.7 times the matching entrance. Easing is ease-out cubic-bezier(0.23, 1, 0.32, 1) for entrances and responses, ease-in-out cubic-bezier(0.77, 0, 0.175, 1) for on screen movement, and plain ease for opacity and color. Ease-in is banned. Travel is capped at 12px on one axis, and the distance tokens are named. Rise-micro is 4px for micro feedback, and rise-enter is 12px for entrances, the cap itself. The one exception to the travel cap is the row re-sort FLIP. It animates transform only, travels the row's full delta at the state duration on the ease-out curve, and disables itself under reduced motion. No other element inherits the exception. The masthead's frost transition is a color change at the entrance duration, 280ms, at the cap. Stagger applies within one figure, never exceeds 6 steps or 40ms per step, and a stagger group's total completion time never exceeds 480ms. Stagger never applies to expand all or collapse all. Animated properties are transform and opacity, plus color transitions on micro interactions. The one layout exception is the disclosure container's grid rows technique.

The never list. Axes, gridlines, scales, tick labels, and axis titles never animate. No number counts up, tweens, rolls, or flips, on load, on scroll, or on state change. Text that could be mid read never moves. In place scatter labels never transition between positions. The page skeleton's layout never animates. Nothing loops. Nothing triggered by the keyboard animates, keyboard initiated state changes are instant. When the underlying payload changes at a new publish, nothing animates to show the difference, deltas are communicated in the publish note prose.

Reduced motion is a designed branch, not a kill switch. Under prefers-reduced-motion, anchor jumps are instant, the disc opacity fade snaps, the masthead frost transition is removed, the re-sort FLIP disables itself in script, micro interaction transforms are removed, and color changes survive. Every element's resting state is identical in both branches. The board's detail card and disclosures do not animate in the full branch, so the branch carries no crossfade provisions for them.

The whole motion layer costs at most 2.5KB against the board's bundle budget. No animation library. The full doctrine, with per component contracts M1 through M20 and coherence tokens C1 through C8, lives in the house motion file and the peira design record it distills.

## Agent Prompt Guide

A lane briefed to build or review board UI works in this shape.

1. Role. You are building an Operate surface for a benchmark board, not a marketing page.
2. Context. Read this file and PRODUCT.md first. The claims discipline in PRODUCT.md outranks visual preference.
3. Tokens. Build only from the front matter tokens. Reference tokens by path, never by pasted value.
4. Population. State the population and the reader's question before choosing a chart form.
5. Labels. Apply the label law from the Components section, selection rule stated before rendering.
6. Claims. Every figure traces to the payload. Decompositions travel with their headlines.
7. Motion. Apply the Data & Motion section. When in doubt, no animation.
8. Verify. Render at 1440, 1280, and 390, run the touch session at 390x844, and check clearance and edges on the renders.
9. Gates. Run the lint, diff, and detector steps in the kit's gates file and report the results in the review readiness block.
