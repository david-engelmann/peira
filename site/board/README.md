# The board front end

This app is the front end of the peira results board at
peiratrial.dev. It is a Next.js static export in React, with
charts on visx and hand-rolled SVG, styled by the Instrument
panel design system (direction A) from the 2026-11 board
redesign program. It renders one payload and nothing else. The
page is a single panel of sections in nav order, the scatter,
the ranking rail with its inspector, the flagged band, the
malformed rail, the families, calibration, compare, the models
index, and Method. Every number on the page is formatted
from that payload at build time, never recomputed by the front
end and never edited by hand.

## Building

Run `npm install` once, then `npm run build`. The build needs
Node 22 or newer and a Chromium for the share image and the
DOM audit. Both scripts look in the Playwright browser cache
and honor `PUPPETEER_EXECUTABLE_PATH` or `CHROME_PATH` when
set. The build regenerates the share image, produces the
static export in `out/`, and runs the integrity check, the
budget check, and the render law against the payload. The
gate chain also runs the vendor agreement check, `node
scripts/check-vendor-agreement.mjs`, against the same payload.
`node scripts/audit-dom.mjs
out <screenshots-dir>` drives the built page in Chromium at
six widths and in a touch session at 390 by 844, and checks
layout, geometry, names, and interactions against the payload.

## Where the data comes from

The only data file is `data/payload.json`. The pipeline
generates it from sealed run artifacts, and a publish replaces
it wholesale. Generating, verifying, deploying, and evidencing
a publish is a runbook task with its own gates.
