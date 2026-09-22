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

## Pipeline stages

The manifest is stage one. Landing next, in order:

1. **Automated validation gates** — beyond schema: paired-variant checks,
   dedup, severity calibration, PII scan, split-integrity checks.
2. **Generator templates** — one per attack family, so new cases start from
   a correct skeleton instead of a blank file.
3. **Review queue** — tracks human review state per case; 100% of
   critical-severity cases get human review before release.
