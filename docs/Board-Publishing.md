# Board publishing

This runbook publishes the results board at peiratrial.dev. It is
the recipe the freeze publish (publish 27, 2026-10-23) followed end
to end, written down from that pass. The board is a static Next.js
app in `site/board/`. Its only data file is a payload the pipeline
generates from sealed run artifacts. Nobody edits a number on the
page by hand, and the front end formats the payload's numbers
without recomputing them.

## Stage the seals

Copy the sealed artifacts for this publish into the curated
publish folder at `~/workspace/peira-trial/publish-runs/`. The
folder holds exactly the set the board will show, and nothing
else goes in. A canary artifact never goes in. A partial never
goes in. A sealed artifact is never edited, because the seal is
the trust model. Check each staged file's md5 against the md5
recorded when the run sealed before anything downstream reads it.

## Generate the payload

Generate from merged main in a dedicated publish worktree, never
from a lane's working tree. Add the worktree from the main clone,
then run the dashboard leaderboard command with the trial
environment's Python and the worktree's package on the path,
from the driver folder.

```bash
git -C ~/workspace/peira-worktrees/peira-main worktree add ~/workspace/peira-publishN <merged-main-sha>
cd ~/workspace/peira-ling-driver
PYTHONPATH=~/workspace/peira-publishN/python ~/workspace/peira-worktrees/peira-main/.venv-trial/bin/python -m peira.cli dashboard leaderboard --runs-dir ~/workspace/peira-trial/publish-runs --out ~/workspace/peira-trial/payload-publishN.json
```

Generation takes minutes, and tens of minutes on a loaded box.
Run it detached with a log and wait for its exit line rather than
watching it.

## Verify the payload before anything renders

Compare the new payload against the previous published payload
before the app ever sees it. Rows are keyed by adapter name,
adapter version, and wire. Every row the two payloads share must
agree on all eight measured fields (asr_conditional, asr_ci95,
benign_accuracy, malformed_rate, ece_attacked, robustness_tax,
n_cases, n_eligible). Zero drift is the pass mark. Every new row
must match its sealed artifact figure for figure, and the
artifact itself must pass `RunArtifact.verify()`, constructed
with `RunArtifact.from_json` on the file's text. Any drift, any
missing row, or any added row nobody commissioned stops the
publish. The data gets fixed at the artifact or the generator,
never in the payload file.

## Put the payload in the app

Copy the verified payload over `site/board/data/payload.json`.
That file is the app's only data input. The build's prebuild step
stages it at `public/payload.json` for readers who want the raw
data and regenerates the share image from it.

## Run the gate chain

Every gate runs on the exact tree that will deploy, and every
gate must pass before the deploy step.

```bash
cd ~/workspace/peira-board/site/board
npm run build
node scripts/audit-dom.mjs out <screenshots-dir>
```

`npm run build` runs the prebuild, the static export into `out/`,
the integrity check, and the budget check. The integrity check
recomputes the headline counts under the board's display rule,
recomputes every robustness tax from the payload's frontier
(the maximum deviation must print 0.00000), rebuilds the tie
brackets, and proves the compare dataset and its rendered
deltas against the payload. The budget check caps the board
page's initial transfer at 500 KB. The DOM audit then drives
the built page in Chromium at 1440, 1280, and 390 and checks
layout, geometry, names, and interactions against the payload.
A gate failure on real data is a finding to report, not an
obstacle to route around. No gate gets edited to fit the data,
and no checker is weakened to reach a pass.

## Deploy

Deploy the static export with the Pages deploy script from the
dashpub environment, which holds its Cloudflare credential.

```bash
cd ~/workspace/peira-dashpub
./.venv/bin/python deploy_pages.py ~/workspace/peira-board/site/board/out
```

Record the deployment id and the deployment URL the script
prints. They belong in the publish record and in the goal file's
publish paragraph.

## Verify the live site

Fetch the live page and compare it with the build.

```bash
curl -s https://peiratrial.dev/ -o /tmp/live-index.html
md5sum /tmp/live-index.html ~/workspace/peira-board/site/board/out/index.html
```

The hashes must match. Confirm the new model identities and the
counts sentence appear in the live HTML, and fetch one new model
page to a 200. Then open the rendered live site in a browser and
inspect every element and interaction on it, at desktop width
and at phone width. Hash equality proves the right bytes were
served. It does not prove the page looks right, and it is not a
substitute for looking. Publish 27 was first reported verified
on hashes alone and the owner caught the substitution, so the
visual pass is a required step of this recipe, not a courtesy.

## File the evidence pack

Every publish also lands outside the agent workspace, in the
repo the owner controls. Commit the publish's sealed artifacts
(gzipped), the payload it produced, and its records to an
archive branch of this repository, with a manifest that lists
every seal's md5 and headline figures. The freeze publish used
`archive/v2-freeze-2026-10-23`. Prove the pack by reading one
seal back through the API or a fresh clone and checking its
md5. The agent workspace is not storage. It has vanished for
days at a time before, and nothing the owner needs may exist
only there. Per-seal gzip backups also go out as email
attachments when each run seals, so the set survives in the
owner's mail as well.

## Record the publish

Write the publish paragraph in the goal file the same pass,
with the payload's counts, the deployment id, the live md5, and
the seals' md5s. A publish that is not recorded did not finish.
