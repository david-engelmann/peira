# The board front end

This app is the front end of the peira results board at
peiratrial.dev. It is a Next.js static export in React, with
charts on visx and hand-rolled SVG, styled by the Ledger design
system from the 2026-10-23 UI perfection program. It renders one
payload and nothing else. Every number on the page is formatted
from that payload at build time, never recomputed by the front
end and never edited by hand.

## Building

Run `npm install` once, then `npm run build`. The build needs
Node 22 or newer and a Chromium for the share image and the
DOM audit. Both scripts look in the Playwright browser cache
and honor `PUPPETEER_EXECUTABLE_PATH` or `CHROME_PATH` when
set. The build regenerates the share image, produces the
static export in `out/`, and runs the integrity check and the
budget check against the payload. `node scripts/audit-dom.mjs
out <screenshots-dir>` drives the built page in Chromium at
four widths and checks layout, geometry, names, and
interactions against the payload.

## Where the data comes from

The only data file is `data/payload.json`. The pipeline
generates it from sealed run artifacts, and a publish replaces
it wholesale. Generating, verifying, deploying, and evidencing
a publish is a runbook task with its own gates.
