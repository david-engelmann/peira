---
version: alpha
name: Peira benchmark board
description: Design tokens and law for the peira benchmark board, an Operate surface where charts carry the page and every figure is evidence.
colors:
  ground: "#05070a"
  panel: "#0c1015"
  raised: "#141a21"
  lift: "#1a222c"
  hairline: "#232c35"
  edge: "rgba(255, 255, 255, 0.08)"
  edge-soft: "rgba(255, 255, 255, 0.05)"
  ink-1: "#eef2f6"
  ink-2: "#aebcc7"
  ink-3: "#71808f"
  accent: "#2fbf71"
  accent-bright: "#4ade80"
  amber: "#e8a33d"
  red: "#ff6a3d"
  chart-grid: "#232c35"
  chart-axis: "#232c35"
  chart-tick: "#71808f"
  chart-glyph-dark: "#0b0e12"
  chart-glyph-light: "#f4f7fa"
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
    fontSize: "44px"
    fontWeight: 650
    lineHeight: 1.16
    letterSpacing: "-0.022em"
  heading:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "30px"
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
  row-list:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink-1}"
    padding: "{spacing.space-4}"
  detail-card:
    backgroundColor: "{colors.lift}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-4}"
  chip:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.ctl}"
    padding: "{spacing.space-1}"
  chart-gridline:
    backgroundColor: "{colors.chart-grid}"
    height: "1px"
  chart-axis-label:
    textColor: "{colors.chart-tick}"
    typography: "{typography.micro}"
  scatter-disc-anthropic:
    backgroundColor: "{colors.chart-series-anthropic}"
    rounded: "{rounded.pill}"
  vendor-chip-anthropic:
    backgroundColor: "{colors.chart-series-anthropic}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  scatter-disc-openai:
    backgroundColor: "{colors.chart-series-openai}"
    rounded: "{rounded.pill}"
  vendor-chip-openai:
    backgroundColor: "{colors.chart-series-openai}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  scatter-disc-google:
    backgroundColor: "{colors.chart-series-google}"
    rounded: "{rounded.pill}"
  vendor-chip-google:
    backgroundColor: "{colors.chart-series-google}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  scatter-disc-meta:
    backgroundColor: "{colors.chart-series-meta}"
    rounded: "{rounded.pill}"
  vendor-chip-meta:
    backgroundColor: "{colors.chart-series-meta}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  scatter-disc-mistral:
    backgroundColor: "{colors.chart-series-mistral}"
    rounded: "{rounded.pill}"
  vendor-chip-mistral:
    backgroundColor: "{colors.chart-series-mistral}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  scatter-disc-deepseek:
    backgroundColor: "{colors.chart-series-deepseek}"
    rounded: "{rounded.pill}"
  vendor-chip-deepseek:
    backgroundColor: "{colors.chart-series-deepseek}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  scatter-disc-fallback:
    backgroundColor: "{colors.chart-series-fallback}"
    rounded: "{rounded.pill}"
  vendor-chip-fallback:
    backgroundColor: "{colors.chart-series-fallback}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  chart-axis-line:
    backgroundColor: "{colors.chart-axis}"
    height: "1px"
  flagged-chip:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  primary-control:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  finding-link:
    textColor: "{colors.accent-bright}"
    typography: "{typography.body}"
  caption-note:
    textColor: "{colors.ink-3}"
    typography: "{typography.caption}"
  error-note:
    textColor: "{colors.red}"
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
---

# Peira benchmark board

## Overview

This file is the board's design system in one place. Tokens live in the front matter above. The law lives in the sections below. A lane building board UI reads this file and `PRODUCT.md` beside it, builds only from these tokens, and runs the gates in the house kit's `gates/GATES.md`.

The board is an Operate surface in Impeccable's mode terms. It is read and worked, not admired. Findings open the page and the explorer follows as their evidence. Model addresses are deep links into one explorer. Guard results are one population inside the explorer, reached by its filter. Method states each rule once and per result facts live on the results.

Token values were extracted on 2026-11-06 from the board's own stylesheet at `site/board/app/globals.css` and the vendor table at `site/board/lib/vendor-data.json` in the redesign tree at `~/workspace/peira-board-redesign/`. The extracted tokens, colors, type, shadows, and geometry, are the board's real values. The law sections of this file are different in kind. They set targets the shipped board has not yet converged to, and four divergences stand open between this file and the shipped CSS, stated plainly. First, the shipped CSS has no motion token layer, and its transitions are hardcoded 160ms ease and 0.15s ease values where this file requires tokenized durations and curves. Second, the shipped CSS still carries the global reduced motion block forcing all transitions to 0.01ms, the kill switch the motion doctrine's M19 forbids, where this file requires a designed branch. Third, shipped wells and cards still use gradient washes this file forbids. Fourth, off ladder radii sit on major components, the scatter wrap at 18px, the expanded card at 16px, and the detail card at 12px, not only on minor ones. The coherence re-score after the redesign is also owed. Convergence is build work under this file, tracked in the kit's RESEARCH.md.

This file carries no colors.primary token, deliberately. The accent token carries the primary role, and the design linter's missing-primary warning on this file is expected and waived on the record in the kit's gates file. Agents must not auto-generate a primary token here.

## Colors

The surface ladder is assigned, never improvised. Ground is the page. Panel is a well's floor. Raised separates elements inside a well. Lift is reserved for the one floating element, the scatter detail card, and the sticky nav. No section invents a gradient or tint of its own.

Ink comes in three steps. Ink 1 is body and data text. Ink 2 is secondary text and chip text. Ink 3 is furniture, ticks, and captions. Structural elements such as gridlines, tracks, and panel grounds are grayscale. Color is data or identity, never decoration.

Accent marks the primary reading path. Amber means flagged and nothing else, everywhere, including in motion. No animation may flash, pulse, or sweep amber or accent across data. State changes use ink and surface steps, not accent color, unless the element is itself the primary control.

Maker identity rides every figure. One hue per vendor family, used by the ranking, the scatter, the heatmap, the calibration panels, the detail cards, and the compare bars alike, resolved from the one vendor table. The chart series tokens above carry the lead families and the fallback. The full family list lives in `lib/vendor-data.json` and this file names the pattern, one token per family, keyed by family name. A figure whose points are all one color with identity hidden in a corner tile diverges from this file.

Chart furniture has named tokens so the linter can hold it. Gridlines and axis lines draw in chart-grid and chart-axis at reduced opacity where the stylesheet does so. Tick labels read in chart-tick. Discs and chips filled with a family color take their glyph ink from chart-glyph-dark or chart-glyph-light, whichever the family table assigns. Where neither glyph ink reaches the contrast floor on a family color, the chip ground and only the chip ground adjusts by the smallest five percent step that clears the floor, and the family keeps the ink with the larger margin. The adjusted ground is recorded in the vendor table as the family's chipColor, and the series color itself never changes. Discs and every other filled surface keep the family color as it stands. Two families carry an adjusted chip ground today, zhipu darkened one step to #1168ea with the light ink kept, and upstage lightened one step to #8664fb with the dark ink taken.

## Typography

Two families do all the work. Archivo carries data, prose, and display. JetBrains Mono carries labels, eyebrows, and stamps only. Mono never carries a data line.

Inside any chart there are exactly three text sizes, the axis and label size, the caption size, and the chart's title or finding size. No type in a section is larger than its finding or title. Data text is one uniform body size throughout a chart, and table headers are the smallest text in the table, kept readable by being short.

Floors are absolute. No rendered text under 10px at desktop widths or at 390. Low contrast small text fails at any size it cannot be read at a glance. Contrast meets 4.5 to 1, including placeholder text. Display letter spacing never goes below -0.04em and display size never exceeds the display token. Display renders at 44px and steps to 33px at phone widths, headings at 30px stepping to 25px, each step a media rule rather than a fluid scale.

Numbers render in tabular figures in their final form in the first frame they are visible. Names never break mid token. If a name does not fit, the layout changes, by a wider slot, a shorter sanctioned name form, or list form.

Data lines speak one dialect wherever the figures appear as a set. Spaced, sentence case labels, interval in brackets. Costs print at two decimals, rates at one decimal with their interval, and no figure carries digits no reader can act on.

## Layout

The page column is 1180px at most, with 24px side padding. Section spacing comes from the 4px based scale in the front matter, tokens space-1 through space-9. The one section gap is 64px and stays. Every internal gap snaps to the scale. Where a section has a rail beside a grid, rail and grid share one top baseline.

Nothing extends past the section edge at any audited width. Zero elements beyond either edge, measured in the DOM and confirmed on the render. If a chart's mandatory label set cannot clear at a width, the chart changes shape, by faceting, splitting the population, or demoting to a ranked list. Type, label, and point sizes never shrink to fit a population.

## Elevation & Depth

Elevation is the surface ladder plus its three shadows, and nothing else. Wells sit flat on panel. Raised elements inside a well take the first shadow step at most. The detail card and the sticky nav, the only lift elements, take the deeper steps. A section may not invent its own shadow, tint, or gradient wash. The ambient page wash behind everything is page furniture owned by the stylesheet, not a per section effect.

The shadow values, extracted with the tokens above:

- First step, 0 1px 2px rgba(0, 0, 0, 0.35), 0 4px 14px rgba(0, 0, 0, 0.22).
- Second step, 0 2px 6px rgba(0, 0, 0, 0.4), 0 14px 34px rgba(0, 0, 0, 0.3).
- Third step, 0 8px 18px rgba(0, 0, 0, 0.5), 0 28px 64px rgba(0, 0, 0, 0.42).

## Shapes

The radius ladder has three values and a circle. Control radius 6px for controls, chips, and small elements. Panel radius 10px for panels, cards, wells, and figures. Pill radius 999px for pills only. Discs and dots are circles at 50 percent, which are circles, not corners. Every other radius value is deleted wherever it survives in the stylesheet. A grep for border-radius values outside this set fails review.

## Components

Two sanctioned containers hold data, and a section picks one. The well is a panel at panel radius on the surface ladder with a hairline border, used by figures. The row list is hairline ruled rows directly on ground, used by lists. After any build pass, a reader scrolling the page meets exactly two container ideas.

The detail card is the board's one popover. It is one object with changing contents, not a new card per point. It carries a visible close control, tap outside dismisses, and Escape dismisses. Keyboard focus produces the identical card with the identical contract.

Every figure caption is one or two declarative sentences stating what the figure shows and the one caveat that matters, placed directly under its figure, in the caption style. Methodological essays live in Method, not under figures.

Labels follow the label law. Clearance is absolute, no label's rendered box intersects any disc, label, axis, gridline, or furniture at any audited width, and a label that cannot clear is not placed. Labels are chosen by a selection rule stated before rendering, the extremes of both axes, every flagged result, and the best result per maker always label. No leader lines anywhere. A model is named at most once per surface per width. Labels carry names, not numbers.

Chart form follows the reader's question. Lookup gets a table. Pattern gets a chart. Two item comparison gets paired bars on a shared scale. Per model detail gets small multiples sharing one scale and one key. Every chart head states the question and the population before any axis is read. Every scale carries its key inside the figure, because charts travel without prose. Absence is a visible, named state, a deliberate mark in the cell's position, never a faint speck or an empty slot.

## Do's and Don'ts

Do:

- Build only from the tokens in this file, and send any new value through a change to this file first.
- Give every chart a data table alternative with the same figures.
- State each fact once per view, in its one place.
- Verify rendered at 1440, 1280, and 390 before calling a change done.

Don't:

- Invent a number, a count, or a figure the payload does not carry.
- Repeat a headline figure in the same row's small print.
- Use glassmorphism as a default material, a hero metric template as decoration, identical card grids, or eyebrow scaffolding.
- Add a second accent, a bespoke gradient, or a per section tint.
- Put internal language on the public face, no lane names, worktree paths, decision codes, draft markers, or approval states.

## Responsive Behavior

Three widths govern. Desktop at 1440, laptop at 1280, phone at 390. Phone is a re-flow, never a squeeze. Any component that cannot fit 390 without clipping either edge gets a phone specific layout.

Sticky chrome may not hide content. Fixed and sticky elements are opaque, offset the content they overlay, and in every audit scroll position hide zero content. A nav that cannot show all its links at 390 shows the ones that fit plus one overflow affordance, and a link cut mid word is a defect.

The motion contract is identical at phone width. Distance does not shrink and duration does not grow. Board changes are verified by an interactive touch session at 390x844, card opens on tap, switches, and dismisses by tap outside and by its close control, plus rendered inspection at all three widths. Static renders and desktop mouse passes do not verify the phone experience.

## Data & Motion

The evidence law, in force on every board surface:

- Charts carry the page. Prose is cut to labels and captions.
- Figures never animate.
- Motion only on interface state changes, re-sorts, filters, selection, and mode switches. Payload data changes never animate. No ambient motion.
- Every number on the surface traces to a data field in the sealed payload. If it cannot be traced, it does not ship.
- Every chart ships with a data table alternative carrying the same figures.

The motion tokens behind the law. Durations are 120ms for micro feedback, 200ms for state changes, and 280ms for entrance, and no duration on the board exceeds 280ms. Exits run at 0.7 times the matching entrance. Easing is ease-out cubic-bezier(0.23, 1, 0.32, 1) for entrances and responses, ease-in-out cubic-bezier(0.77, 0, 0.175, 1) for on screen movement, and plain ease for opacity and color. Ease-in is banned. Travel is capped at 12px on one axis, and the distance tokens are named. Rise-micro is 4px for micro feedback, and rise-enter is 12px for entrances, the cap itself. Stagger applies within one figure, never exceeds 6 steps or 40ms per step, and a stagger group's total completion time never exceeds 480ms. Stagger never applies to expand all or collapse all. Animated properties are transform and opacity, plus color transitions on micro interactions. The one layout exception is the disclosure container's grid rows technique.

The never list. Axes, gridlines, scales, tick labels, and axis titles never animate. No number counts up, tweens, rolls, or flips, on load, on scroll, or on state change. Text that could be mid read never moves. In place scatter labels never transition between positions. The page skeleton's layout never animates. Nothing loops. Nothing triggered by the keyboard animates, keyboard initiated state changes are instant. When the underlying payload changes at a new publish, nothing animates to show the difference, deltas are communicated in the publish note prose.

Reduced motion is a designed branch, not a kill switch. Under prefers-reduced-motion, entrances lose travel and stagger, the detail card cross fades only, disclosures cross fade with instant height, anchor jumps are instant, and micro interaction transforms are removed while color changes survive. Every element's resting state is identical in both branches.

The whole motion layer costs at most 2.5KB against the board's bundle budget. No animation library. The full doctrine, with per component contracts M1 through M20 and coherence tokens C1 through C8, lives in the house motion file and the peira design record it distills.

## Agent Prompt Guide

A lane briefed to build or review board UI works in this shape:

1. Role. You are building an Operate surface for a benchmark board, not a marketing page.
2. Context. Read this file and PRODUCT.md first. The claims discipline in PRODUCT.md outranks visual preference.
3. Tokens. Build only from the front matter tokens. Reference tokens by path, never by pasted value.
4. Population. State the population and the reader's question before choosing a chart form.
5. Labels. Apply the label law from the Components section, selection rule stated before rendering.
6. Claims. Every figure traces to the payload. Decompositions travel with their headlines.
7. Motion. Apply the Data & Motion section. When in doubt, no animation.
8. Verify. Render at 1440, 1280, and 390, run the touch session at 390x844, and check clearance and edges on the renders.
9. Gates. Run the lint, diff, and detector steps in the kit's gates file and report the results in the review readiness block.
