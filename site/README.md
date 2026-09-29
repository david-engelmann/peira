# Peira leaderboard site (scaffold)

Astro static site for **peiratrial.dev**: the peira benchmark
leaderboard, model pages, and docs. This is a **scaffold**: every number
it renders today is synthetic mock data, and every mock surface says so.

## Develop

```bash
npm install
npm run ingest-mock   # artifacts -> src/data/results.json (mock)
npm run dev           # dev server
npm run build         # ingest mock data + static build -> dist/
```

## Data pipeline

Real results flow through one path:

```
official run artifacts (sealed RunArtifact JSON)
  -> site/scripts/ingest.py (verifies analysis locks, enforces schema)
  -> src/data/results.json (gitignored build artifact)
  -> astro build -> dist/
```

`ingest.py` fails loudly on a broken lock, a version mismatch, or a
mock/real mixup. The contract both sides honor is
`site/SITE_DATA_SCHEMA.md`.

Mock data for development:

```bash
npm run gen-mock      # rebuild site/assets/mock-artifacts/*.json
```

The mock artifacts are built with the real peira code path (real
dataclasses, real `summarize()`, real seals) so the pipeline cannot
tell them apart except by the `config.mock` marker. The public runs
carry 504 cases (24 per family across 21 families, 3% benign defect
rate) so the mock leaderboard exercises ranking-eligible rows; the
holdout runs carry 100 cases and stay ranking-ineligible, like a real
holdout slice would before official results exist.

## Going live (checklist, not yet done)

- [ ] A12/A13 official runs sealed; artifacts published with SHA-256s
- [ ] `ingest.py` run WITHOUT `--mock` against the sealed artifacts
- [ ] `mock_data: false` verified in the built `results.json`
- [ ] Seal verification wired into the build (recompute the analysis
      lock over the lock payload; fail closed on mismatch)
- [ ] D5/D6/D16 display decisions resolved with David

## Deploy (Cloudflare Pages, when live)

- Build command: `npm run build`
- Output directory: `dist`
- Custom domain: `peiratrial.dev` (apex)

## Views

Leaderboard, Families, Calibration, Frontier, Compare, Cases,
Methodology. The public/holdout toggle and all view state live in the
URL query string, so any view is linkable. CSV, PNG, and SVG export
from the same client-side data the charts render.
