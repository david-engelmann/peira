# The board front end

This app is the front end of the peira results board at
peiratrial.dev. It is a Next.js static export in React, with
charts on visx and hand-rolled SVG. It renders one payload
and nothing else.

The overview shows attack success across all ranked full-suite results. The analysis compares attack families and measured run costs. Readers can follow each chart into the explorer, inspect individual results, and compare two runs. Guard subsets and flagged runs remain available through population filters. Method includes the scoring rules and an inspectable paired case.

Every number on the page derives from the payload at build
time. Nothing is recomputed by hand and nothing is edited
into the markup. A model address, /models/<slug>/, hands
off to that result's reading in the explorer.

## Building

Run `npm install` once, then `npm run build`. The build
needs Node 22 or newer and a Chromium for the share images.
The generator and audit scripts look in the Playwright
browser cache and honor `PUPPETEER_EXECUTABLE_PATH` or
`CHROME_PATH` when set.

For a prototype deployment, set `BOARD_PUBLIC_ORIGIN` to the public prototype origin before building so shared links load its preview image. The default origin is production.

The prebuild regenerates the share images from the payload
and copies the payload beside them, and the build then
produces the static export in `out/`. The vendor agreement
check, `node scripts/check-vendor-agreement.mjs`, stands
alongside the build and proves the page marks and the page
colors resolve vendor identity through the one vendor
table. The DOM audit, `node scripts/audit-dom.mjs`, drives
the built page in Chromium at several widths and in a touch
session at 390 by 844, and exercises the explorer's
interactions. Both stand alongside the build rather than
inside it.

`npm test` runs the board suite, which pins the board's
derivations and its standing rules against the payload and
the sources, the cost truth labels among them.

## Where the data comes from

The summary data is in `data/payload.json` and the recorded paired example is in `data/flipcase.json`. The pipeline
generates it from sealed run artifacts, and a publish
replaces it wholesale. The copy committed here is the
currently published payload, kept so the board builds from
a clean checkout exactly as it stands on the site.
Generating, verifying, deploying, and evidencing a publish
is a runbook task with its own gates.
