# Dataset pipeline

How peira datasets are built, versioned, and verified. The pipeline exists
so one maintainer can author thousands of cases without losing track of
what's in a release: every dataset version is a locked, hashed,
machine-checkable artifact.

## Layout

```
dataset/
  trial-demo/        # 12-case offline demo fixture (scaffolding, not v1)
  trial/             # 20-case Trial starter suite (scaffolding, not v1)
                     # exercises the harness end to end via --suite trial
  v1/
    README.md
    cases.jsonl      # the 2,000 public cases (lands via the pipeline)
    trial.jsonl      # the 100-case Peira Trial suite, sampled from v1
    CANARY.txt       # the canary string (also embedded in every case file)
    DATASHEET.md     # full datasheet
    schema.json      # the frozen case JSON schema
    manifest.json    # the build manifest (this doc)
```

`trial-demo` and `trial` are both scaffolding: small case sets that let
the harness run offline before v1 lands. `trial-demo` predates the gates
and is exempt from them; `trial` passes all six gates and carries a
manifest, so it exercises the full mechanism (load → gate → manifest →
run → report).

## Case schema: closed for required fields, open for extension

The frozen schema requires `case_id`, `family`, `primitive`, `severity`,
`benign`, and `attacked` — and nothing else. Validators ignore unknown
top-level fields, and `Case.from_dict` preserves them on `Case.extras`,
so new per-case configuration rides through the whole pipeline (load →
run → artifact) without touching the schema, the loader, the gates, or
the artifact format. Only the consumer of a new field needs to know
about it. The trial starter suite uses this for its `canary` field.

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

A Rust port of the schema check ships as `peira-cli` (`crates/peira-cli`)
for fast dataset validation in CI:

```
peira-cli validate --dir dataset/v1          # G1 schema check, in Rust
peira-cli verify-manifest --dir dataset/v1   # manifest integrity, in Rust
```

Both commands are read-only and exit 1 on failure. The Rust core
(`crates/peira-core`) also ports the metrics, run artifacts, and the
canonical JSON behind analysis locks — byte-identical to the Python
reference, so either side verifies the other's artifacts.

## Generator templates

New cases start from a family template — never a blank file:

```
peira dataset new --family state_poisoning --id sp-042 --severity high
```

This prints a schema-valid case skeleton with `{{PLACEHOLDERS}}` for the
author to fill in. Each of the ten templates encodes its family's attack
pattern (documented in `python/peira/templates.py`): the state_poisoning
skeleton has the poisoned tool-output slot, option_order has the reordered
options, score_anchoring has the anchor context field, and so on. G1 and
G4 pass on a fresh skeleton; the author supplies only content.

With `--out cases.jsonl` the case is appended as JSONL instead of
printed. `--primitive` overrides the family's natural primitive
(score_anchoring defaults to `score`, negation_games to `noul`, the rest
to `choice`).

The templates remove blank-page friction. They don't judge difficulty or
quality — that's the review queue's job.

## Review queue

Automation checks structure; humans judge quality. The review queue
tracks human review state per case in `<dataset-dir>/review.json` and
enforces the project rule: **100% of critical-severity cases are
human-reviewed before release** (severity is graded with
`docs/SeverityRubric.md`).

A case needs review when it is critical-severity and not approved, or
when it carries gate warnings (G6 pii-scan) and is not approved.

```
peira dataset review --dir dataset/v1          # list pending + coverage
peira dataset review --dir dataset/v1 --check  # exit 1 if anything pending
peira dataset review approve --dir dataset/v1 --id sp-001 --reviewer dg --notes "..."
peira dataset review reject --dir dataset/v1 --id sp-002 --reviewer dg --notes "rework: ..."
```

`rejected` means sent back for rework — it does not count as reviewed.
The release gate is `peira dataset build-manifest --require-reviews`,
which refuses to write a manifest while any reviews are pending:

```
peira dataset build-manifest --dir dataset/v1 --version 1.0.0 --require-reviews
```

The authoring loop, end to end:

```
peira dataset new --family state_poisoning --id sp-042 --out dataset/v1/cases.jsonl
# ... fill in the {{PLACEHOLDERS}} ...
peira dataset gates --dir dataset/v1
peira dataset review --dir dataset/v1 --check
peira dataset build-manifest --dir dataset/v1 --version 1.0.0 --require-reviews
```

`review.json` is committed alongside the cases — review decisions are
part of the dataset's provenance.
