# Peira v2 freeze archive — 2026-10-23

Everything behind the frozen peira board at https://peiratrial.dev as of
23 October 2026, in one place that is not an agent's sandbox.

## Contents

- seals/ — the 39 sealed trial artifacts (RunArtifact JSON). These are the
  source of truth for every number on the board. Each carries its own hash
  lock and verifies with peira's RunArtifact.verify(). MANIFEST.md lists
  every file with its md5 and headline figures.
- payloads/ — payload-freeze.json is the exact data file the live board was
  built from (39 entries), generated from seals/ by peira's own generator.
  payload-publish26.json is the previous publish, kept for drift checks.
- records/ — the paper trail: the UI perfection charter, the forensic
  census, the data integrity audit, the design system, the stack research,
  and the gate reports for the scored adapters, plus the program GOAL.md.
- tooling/ — deploy_pages.py, the Cloudflare Pages deploy script used for
  every publish.

## How the board was published from this

Seals were staged into a publish folder, the payload generated with
peira's dashboard leaderboard command from the peira repo at ba51d05b,
verified field-by-field against the previous payload (zero drift on the
36 shared rows), then the Next.js board in the repo (site/board) was built
with that payload as its only data file and deployed as a static export.
The board's build fails if any rendered number differs from the payload.

The board's source code lives in the peira GitHub repo, branch
feat/board-frontend. The repo's homepage is https://peiratrial.dev.
