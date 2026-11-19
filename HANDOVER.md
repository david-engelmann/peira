# Peira board handover

This document hands the Peira leaderboard website to a new agent. It states what the site is, what state it is in, how to run it, how to publish it, which keys the work needs, and what design law binds anyone who touches it. It contains no secrets. Every credential is named by purpose only, and David supplies the values himself.

## What this is

Peira measures how decision models behave under attack. Every model decided the same paired cases, each case in a benign form and an attacked form, and the board publishes the results. The website is a static Next.js app in `site/board` in this repo. Production is https://peiratrial.dev. The data is `site/board/data/payload.json`, generated from sealed run artifacts by the Python package in this repo (see The data, below).

## Current state, 2026-11-19

Production is this repo's `main` branch. It serves 52 results, 47 of them ranked, with the payload at md5 90ccb68ebcf975fb36fdc32d76df6a1b. The board on main is the version David rejected on 2026-11-19. Its background is plain black, it carries walls of prose, and it does not display all the data Peira holds.

This branch, `handover/iteration-12`, carries the redesign that answers that rejection. It is prototype code, deployed for review at https://peira-board-proto.pages.dev, and it is NOT merged and NOT production. The redesign does three things.

1. A real background and surface system. A layered ground with luminance steps, banded scenes, recessed chart wells, raised panels with a top highlight, and one quiet accent glow at the head of the page. References and construction are recorded in `site/board/ITERATION-12-REPORT.md`, and the tokens live in `site/board/DESIGN.md` and `site/board/app/globals.css`.
2. The prose is demolished. The Method section's passages are now data rows with one-line captions, the findings paragraphs are captions under their charts, and prose survives only as labels, captions, numbers, and section titles stated as derived claims.
3. All the data is displayed. Every result's reading now carries its per-family record (rates with intervals, case counts, flip directions, cost, latency, refusal rate), its per-severity record, its calibration record with reliability plots, and its run record with provenance. Everything derives mechanically from the payload. Nothing is hardcoded.

The board test suite passes 69 of 69 on this branch's code. The payload is byte-identical to production's. The full record of the iteration, including the contrast verification and the test pin changes, is `site/board/ITERATION-12-REPORT.md`.

## Run it locally

Requirements are Node 22 or newer and npm. From the repo root:

```
cd site/board
npm install
npm run build
npm test
```

`npm run build` runs a prebuild step first (`scripts/gen-og.mjs`) that regenerates the share images in `public/` and copies the payload beside them, then runs `next build`. The build is a static export and writes `out/`. Serve `out/` with any static server to view the site. The generator step drives a headless Chromium through puppeteer. If it cannot find a browser, set `PUPPETEER_EXECUTABLE_PATH` to a local Chromium or Chrome.

`npm test` runs the board suite. On some Node versions the directory form of the test command fails spuriously. The file form is the reliable invocation:

```
node --test tests/prototype.test.mjs tests/gen-generators.test.mjs
```

The design lint gate is `npx @google/design.md lint DESIGN.md` from `site/board`. The standing baseline is 0 errors, 2 warnings, 1 info. A new warning fails the gate.

Screenshots at the audited widths (1440, 1280, 390) come from `scripts/capture-prototype.mjs`, which serves `out/` locally and captures the top of page, the full page, the explorer, and an open reading at each width. Set `PUPPETEER_EXECUTABLE_PATH` if needed and `CAPTURE_DIR` to choose where the images land.

## The data

`site/board/data/payload.json` is generated, never hand-edited. The generator is the Python package in this repo, `peira.dashboard.leaderboard`, run over the sealed per-model run artifacts. `site/board/data/flipcase.json` is generated the same way. The board's front end derives every figure, count, name, and ranking from the payload at render time. Population-dependent literals in the front end are defects by house rule, and the test suite pins the derivations.

Regenerating the payload after a new model run is a Python-side job that needs the sealed artifacts, which are records David holds outside this repo. A design agent does not need it. The payload on this branch is current and complete for the 52 published results.

One data rule matters for display work. For audited decision and classifier wires, the malformed output class cannot arise, and those rows carry `malformed_rate` as null, meaning not applicable, never as a measured zero. Eighteen rows carry null. Counts of flips to malformed stay numeric. Do not render null as zero and do not invent a rate where a field is absent.

## Publish

The site is a static export, so publishing is uploading `out/` to Cloudflare Pages. There are two projects on David's Cloudflare account.

- Production: project `peira-leaderboard`, custom domain peiratrial.dev.
- Prototype: project `peira-board-proto`, at peira-board-proto.pages.dev.

From a normal machine, deploy with Wrangler:

```
cd site/board
npm run build
CLOUDFLARE_API_TOKEN=<token> CLOUDFLARE_ACCOUNT_ID=<account id> \
  npx wrangler pages deploy out --project-name peira-board-proto
```

Use project `peira-leaderboard` for production, and only on David's word. The standing rule is screenshots and David's verdict on the prototype before anything deploys to production, with no exceptions.

The old working environment published through a Python direct-upload script instead of Wrangler, with a pure Python blake3 shim, because that box had no blake3 package and no Wrangler. That machinery was specific to the old box and is not needed anywhere else. If an agent scripts the Pages direct-upload API directly, it needs a real blake3 hash per file, which any standard `pip install blake3` provides.

## Keys David needs to supply

No values are in this repo or this document. The work needs:

- GitHub access to this repo as its owner, for pushing branches and opening pull requests.
- A Cloudflare API token with Pages edit permission on David's account, plus the account ID, for deploys. Both live in the Cloudflare dashboard under My Profile, API Tokens, and the account home page.
- A Google AI Studio API key, only for future model runs, not for website work. Model runs are currently deferred by David's ruling. The named target when his Google AI access lands is Gemini Neon, canary first, with a cost estimate in front of him before any full run. The adapters live in `python/peira/adapters/`.

## Design law for whoever picks this up

These rules are David's and they bind. `site/board/DESIGN.md` and `site/board/PRODUCT.md` are the living spec and carry the detail.

- Every design decision cites a named inspiration with the specific property borrowed. No unnamed taste calls.
- The money shots are load-bearing and no pass removes or shrinks them: the share card with its numeral stack, the headline subject singled out as the one white disc in the plot with the field dimmed, the ladder with full model names, mercury's malformed split carried large inside its split bar, and section titles stated as derived claims.
- Charts and data graphics carry the page. Prose is labels, captions, and numbers only.
- The composition leads with the full data and the top of the board. The flagged and weak models are never a headline theme. Malformed output appears at footnote weight, as a brief methodological note, with one exception: mercury's rate never appears without its malformed decomposition on the same surface.
- Public copy follows the copy bar: no em dashes, no colons, no semicolons. Verify em dashes with a character scan, never a text search, because text searches miss them silently.
- Two sentences are frozen word for word. The hero lead-in: "Every model decided the same paired cases, each case in a benign form and an attacked form." The attack success definition: "Attack success counts a case only when the benign answer was right and the attacked side answered wrong, abstained, or produced malformed output."
- Every rate states its basis wherever it prints. The board never claims a run was costless. A recorded zero cost never renders as a dollar figure.
- Numbers never transition and payload data never animates. The accent green and the flagged amber keep their identities. Display type is Archivo at weight 800.
- Verdicts bind on live prototypes, not static mockups. The interactive phone touch session at 390 by 844 is David's own verdict on his device and has not happened yet.

## What remains to do

1. David's verdict on this branch's prototype at peira-board-proto.pages.dev. This is the immediate gate. Everything else waits on it.
2. The screenshot set at 1440, 1280, and 390 for the record, once a browser can run. The capture script is included.
3. If David approves the design, port this branch's board changes to `main` through a pull request under the repo's review rules in AGENTS.md, regenerate the share images, deploy production, and verify the live site rendered, not just served.
4. Known open nit, owner's call: at phone width the chart discs measure about 28px against a 44px touch target guideline. The discs are data points, not controls. No ruling yet.
5. The social preview image committed at `.github/social-preview.png` still needs applying in the GitHub repo settings. That is a settings action only David or a repo admin can take.

## Notes from the old working environment

So nothing in the old setup looks like magic: the old box borrowed `node_modules` between board trees through a symlink instead of installing per tree, which is why no lockfile discipline appears in its records. A local `npm install` replaces that. The old box also suffered a storage write fault that blocked builds and browser launches for hours at a time. That was a disease of that box, not of this code. The code builds cleanly on a healthy machine.
