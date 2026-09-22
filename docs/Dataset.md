# Dataset pipeline

How peira datasets are built, versioned, and verified. The pipeline exists
so one maintainer can author thousands of cases without losing track of
what's in a release: every dataset version is a locked, hashed,
machine-checkable artifact.

## Layout

```
dataset/
  trial-demo/        # 12-case offline demo fixture (scaffolding, not v1)
  v1/
    README.md
    cases.jsonl      # the 2,000 public cases (lands via the pipeline)
    trial.jsonl      # the 100-case Peira Trial suite, sampled from v1
    CANARY.txt       # the canary string (also embedded in every case file)
    DATASHEET.md     # full datasheet
    schema.json      # the frozen case JSON schema
    manifest.json    # the build manifest (this doc)
```

The 500-case private holdout is **never** committed to this repo. It lives
encrypted and maintainer-only; only aggregate metrics are published. Its
counts are recorded in the maintainer's private manifest, not here.

## The manifest

`manifest.json` is the dataset's build receipt. It records, per file:

- `sha256` — content hash of the exact bytes shipped
- `kind` — `cases` (a validated JSONL case file) or `artifact` (e.g. the canary)
- for case files: `n_cases`, `n_by_family`, `n_by_severity`, `n_by_primitive`

Build it after authoring:

```
peira dataset build-manifest --dir dataset/v1 --version 1.0.0
```

The build validates every case first — a manifest is never written for
invalid data. Verify a checkout against its manifest any time:

```
peira dataset verify-manifest --dir dataset/v1
```

Any mismatch (edited file, missing file, count drift) fails with details.
Manifests are committed to git; CI treats a mismatch as a build failure.

## Versioning

`dataset_version` follows semver:

- **major** — cases removed or semantics changed (revised expected decisions,
  re-cut splits)
- **minor** — cases added
- **patch** — metadata-only fixes (notes, formatting)

Rules:

1. Any case added, changed, or removed → new version, new manifest.
2. Manifests are immutable — never edit one in place; rebuild it.
3. Run artifacts record the dataset version they scored against, so old
   results stay comparable after a release.

## Canary

`CANARY.txt` holds a unique GUID string (also embedded in every case file).
If you train models: exclude any document containing the canary string —
the license *requests* non-training use, and the canary is the
machine-readable enforcement. Overlap checks against the canary back it up.

## Validation gates

Before a manifest is built, cases pass the automated gates:

```
peira dataset gates --dir dataset/v1
```

| Gate | Checks | On failure |
|------|--------|------------|
| G1 schema | every line parses as JSON and satisfies the frozen case schema | error |
| G2 paired-variants | benign and attacked inputs are non-empty and actually differ (an attack identical to its control measures nothing) | error |
| G3 dedup | `case_id` unique; no two cases share a benign/attacked content pair | error |
| G4 families | family id is one of the ten canonical ids (`docs/Taxonomy.md`) | error |
| G5 target-coherence | a named `target_decision` differs from the benign expected decision | error |
| G6 pii-scan | identifier-like strings (email, phone, SSN patterns) in inputs | warning |

Errors fail the suite (exit 1) — fix them before building a manifest.
Warnings don't fail; every warning goes to the human review queue. G2–G6
only run on cases G1 accepted, so one broken case doesn't spray
downstream noise.

The gates check structural integrity only — never case quality or
difficulty. Judging whether a case is a *good* test of its family stays
human work, in the review queue.

Note: `dataset/trial-demo/` predates the gates and is exempt — it's
quickstart scaffolding with deliberately repetitive content, not a real
dataset. Gates apply to `dataset/v1` authoring.

## Pipeline stages

The manifest is stage one, gates stage two. Landing next, in order:

1. **Generator templates** — one per attack family, so new cases start from
   a correct skeleton instead of a blank file.
2. **Review queue** — tracks human review state per case; 100% of
   critical-severity cases get human review before release.
