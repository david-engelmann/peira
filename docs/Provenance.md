# Provenance

Every peira number traces back to its source. This page describes the
four provenance records the project keeps and how they link together.

## 1. Croissant records

Each dataset directory ships a `croissant.json` next to its
`manifest.json`. It is a Croissant 1.0 metadata record (MLCommons),
the dataset-description standard that dataset search engines and
catalogs understand.

The record is generated from the sealed manifest at manifest-build
time, so it always describes the exact bytes it ships with. Those
are

- the dataset name, description, version, license (CC-BY-4.0), and
  creator
- one distribution entry per case file with its SHA-256 digest and
  case count
- a `recordSet` documenting every field of the paired-case schema

Because the digests in `croissant.json` are copied from the sealed
manifest, any drift between the two means one of them was edited by
hand. The provenance tests fail the build if they ever disagree.

Regenerate a record explicitly with

```
PYTHONPATH=python python3 -c "
from pathlib import Path
from peira.dataset import read_manifest
from peira.provenance import write_croissant
d = Path('dataset/v1/cases')
write_croissant(d, read_manifest(d))
"
```

but normally you never need to. `peira dataset build-manifest`
writes the record automatically.

### Case field documentation

The `recordSet` in every `croissant.json` documents these fields.
The table is generated from the same constant the builder uses
(`peira.provenance.CASE_FIELDS`), so the record and this page cannot
drift.

| Field | Type | Meaning |
|---|---|---|
| case_id | Text | Stable case identifier, e.g. v1-spo-001. |
| family | Text | Attack family id from the peira taxonomy. |
| primitive | Text | Decision primitive, either choice, score, or abstain. |
| severity | Text | Consequence-based severity, either critical, high, medium, or low. |
| benign.input.prompt | Text | The unattacked decision prompt. |
| benign.input.options | Text | The explicit decision vocabulary. |
| benign.expected_decision | Text | Gold decision on the benign variant. |
| attacked.input.prompt | Text | The attacked decision prompt. |
| attacked.target_decision | Text | Decision the attacker tries to induce, or null when the attack only tries to change the decision. |
| provenance | Object | Optional PROV-style object with generated_by, generated_at, was_derived_from, and was_attributed_to. |
| evaluation_only | Boolean | True. Benchmark data, never train on it. |
| do_not_train | Boolean | True. Exclude from training corpora. |

## 2. Per-case provenance

Each case may carry a `provenance` object with four optional
PROV-style fields.

| Field | Meaning |
|---|---|
| generated_by | The activity that generated the case, e.g. v2-authoring-batch-3 |
| generated_at | ISO-8601 UTC timestamp of generation |
| was_derived_from | Source case_id when this case was adapted from an earlier case |
| was_attributed_to | The agent responsible for the case, e.g. peira-team |

All four are strings when present. Unknown sub-fields are allowed
and preserved on round-trip, so the vocabulary can grow without a
schema change. Both validation backends (Python reference and Rust
core) enforce the shape with byte-identical error messages, and the
Rust struct mirrors the Python field exactly.

Cases that predate provenance capture simply omit the object. The
fields document authorship workflow facts only. They are never
invented after the fact.

## 3. The immutable tag registry

`data/dataset-releases.json` binds immutable git tags to manifest
digests. Each entry records

- `tag`, e.g. dataset-v1-1.0.0
- `dataset` and `dataset_version`
- `manifest_path` inside the repo
- `manifest_sha256` and `croissant_sha256` of the files AT THE TAG
- `commit` the tag points at

Tags are never moved and entries are never edited. A correction
ships as a new tag plus a new entry. CI verifies every entry on
every PR through `scripts/check_dataset_tags.py`. The tag must
resolve, must still point at the recorded commit, and the manifest
and croissant bytes at the tag must hash to the recorded digests.

### Cutting a dataset release

1. Seal the manifest on main and confirm CI is green.
2. Cut the annotated tag.
   `git tag -a dataset-v1-1.0.0 -m "peira-v1 1.0.0"`
3. Record it.
   `python3 scripts/record_dataset_release.py --tag dataset-v1-1.0.0 --dataset peira-v1 --manifest-path dataset/v1/cases/manifest.json`
   The script reads the manifest AT THE TAG, checks the dataset
   label, and appends the digests to the registry. It refuses
   duplicate tags.
4. Commit the registry update and push the tag plus the commit.
   `git push origin main dataset-v1-1.0.0`

Tag names follow `dataset-<suite>-<semver>`, e.g.
dataset-v1-1.0.0 or dataset-trial-0.1.0.

## 4. Leaderboard provenance

Every ranked leaderboard row carries a `provenance` object binding
the row to the complete measurement tuple.

- `adapter_name`, `adapter_version`, `adapter_revision`, `adapter_spec`
- `suite`, `dataset_version`, `manifest_sha256`
- `seed`, `pricing_version`, `pricing_date`
- `env_sha256`, `contract_version`

A row is therefore self-describing. Given the tuple you can locate
the exact dataset bytes (via the tag registry), the exact adapter
revision, the pricing rules in force, and the environment
fingerprint, and re-run the measurement. The provenance object is
attached to every ranked row with all twelve keys. Two of them,
`manifest_sha256` and `adapter_version`, are required non-empty by
the ranking gate itself. The rest default to the empty string (or,
for `seed`, 0) when the run artifact did not record them, so treat
empty values as not recorded rather than as verified facts.

## 5. Distilled artifacts

A distilled artifact is anything derived from run records for
humans to read. A summary, a chart, a press-kit number, a slide.
It is one step removed from the measurement, and it must say so.

Every distilled artifact carries three provenance fields. They are
listed below.

- `generated_by`. The tool and version that produced it, in the
  form `distill/<tool>@<version>`. A hand-made chart says
  `distill/manual@1`, with the author named beside it.
- `derived_from_runs`. The count of source runs the artifact was
  derived from, as a string. `"14"`, not `14`. Provenance fields
  are string-typed throughout peira, and distilled fields follow
  the same rule so validators never have to guess.
- `review_status`. Always the string `review before use` until a
  human has reviewed the artifact and recorded the review. An
  unreviewed chart does not get published, quoted, or screenshotted
  into a slide. The review records who looked and what they
  checked, in the same record as the artifact.

A distilled artifact never silently inherits the trust of its
sources. The run records are sealed and the analysis lock holds.
The chart drawn from them is a new claim, and it carries its own
provenance or it carries nothing.
