# The board front end

This app is the front end of the peira results board at
peiratrial.dev. It is a Next.js static export in React, with
charts on visx and hand-rolled SVG. It renders one payload
and nothing else.

The page opens with five findings, the claims the payload
supports, each with one dominant visual and one action that
reads the claim in the explorer under it. The explorer is
the board's one evidence surface. Every result stands there
as a row that expands in place into its reading, with rank,
chart, and families views of the same rows, a population
filter for the ranked results, the guard slices, and the
flagged band, and a pin that holds two readings side by side
for comparison. Method follows, stating each rule of the
measurement once, in general terms. Per-result facts live on
the readings, never in Method. The nine sections of the
previous design, which presented the same figures three
ways, are gone.

Every number on the page derives from the payload at build
time. Nothing is recomputed by hand and nothing is edited
into the markup. A model address, /models/<slug>/, hands
off to that result's reading in the explorer.

## Building

Run `npm install` once, then `npm run build`. The build
needs Node 22 or newer and a Chromium for the share images
and the DOM audit. The generator and audit scripts look in
the Playwright browser cache and honor
`PUPPETEER_EXECUTABLE_PATH` or `CHROME_PATH` when set.

The build regenerates the share images, produces the static
export in `out/`, and runs the gate chain against the built
page, in this order. The integrity check recomputes every
figure the page prints from the payload and fails on any
disagreement. The budget check holds the initial transfer
at or under 500 KB, fonts at or under 120 KB. The prose
census measures the page against the design's word budgets.
The render law loads the page at four widths and asserts
the standing render rules. The vendor agreement check,
`node scripts/check-vendor-agreement.mjs`, stands alongside
the chain and proves the page
marks, the page colors, and the share images all resolve
vendor identity through the one vendor table. The DOM
audit, `node scripts/audit-dom.mjs`, drives the built page
in Chromium at six widths and in a touch session at 390 by
844, and exercises the explorer's interactions, expansion,
pinning, sorting, filtering, chart hover and brush, deep
links, and the phone sheet.

`npm test` runs the generator tests, the integrity check
tests, and the board data tests, which recompute the
findings and the explorer's figures from the payload
independently of the code that derives them for the page.

## Where the data comes from

The only data file is `data/payload.json`. The pipeline
generates it from sealed run artifacts, and a publish
replaces it wholesale. The copy committed here is the
currently published payload, kept so the board builds from
a clean checkout exactly as it stands on the site.
Generating, verifying, deploying, and evidencing a publish
is a runbook task with its own gates.
