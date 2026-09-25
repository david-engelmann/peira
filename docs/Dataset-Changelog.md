# Dataset CHANGELOG Schema (v1)

**File:** `dataset/v1/cases/CHANGELOG.json`
**Format version:** 1
**Status:** Active

## Purpose

Machine-readable record of every change to the dataset after sealing.
Humans read the `description`; tools read the structured fields.

## Schema

```json
{
  "$schema": "https://peiratrial.dev/schemas/dataset-changelog-1.json",
  "format_version": "1",
  "dataset": "peira-v1",
  "dataset_version": "1.0.0",
  "entries": [
    {
      "date": "2026-09-25",
      "type": "seal",
      "dataset_version": "1.0.0",
      "description": "Human-readable description",
      "manifest_sha256": "abc123...",
      "case_count": 2025,
      "families": {"family_name": 200}
    }
  ]
}
```

## Entry Types

### `seal`

Marks a dataset version as sealed. The dataset is immutable from this point;
any further change requires a new version.

**Required fields:** `date`, `type`, `dataset_version`, `description`,
`manifest_sha256`, `case_count`, `families`.

**Example:** The initial v1.0.0 seal.

### `add`

New cases added (minor version bump).

**Required fields:** `date`, `type`, `description`, `case_ids` (list of new IDs),
`dataset_version` (the new version), `rationale`.

**Rules:**
- New case IDs must not collide with existing or retired IDs.
- The `manifest_sha256` of the new version must be recorded in a subsequent
  `seal` entry.

### `retire`

Bad cases removed (minor version bump). Cases are never deleted from history —
they're marked retired and excluded from scoring.

**Required fields:** `date`, `type`, `description`, `case_ids` (list of retired IDs),
`rationale` (why each case was retired), `dataset_version` (the new version),
`replacements` (map of old ID → new ID, if replaced).

**Rules:**
- Retired IDs are never reused.
- The rationale must be specific (e.g. "duplicate of v1-csm-023", not "bad case").

### `fix`

Typo or formatting fix that does NOT affect the correct answer (patch version bump).

**Required fields:** `date`, `type`, `description`, `case_ids`, `rationale`
(explaining why the answer is unaffected), `dataset_version` (the new version),
`diff_summary` (what changed, e.g. "fixed 'recieve' → 'receive' in prompt").

**Rules:**
- If there's ANY doubt whether the fix affects the answer, it's a `retire` + `add`,
  not a `fix`.
- The `manifest_sha256` will change (bytes changed) — this is expected for patch bumps.

## Version Bump Rules

| Change | Version bump | Example |
|--------|--------------|---------|
| Initial seal | 1.0.0 | First release |
| Typo fix (answer unaffected) | 1.0.1 (patch) | "recieve" → "receive" |
| New cases added | 1.1.0 (minor) | 50 new indirection cases |
| Cases retired | 1.1.0 (minor) | Duplicate removed |
| Schema change | 2.0.0 (major) | New primitive added |
| Case ID format change | 2.0.0 (major) | v1-xxx → v2-xxx |

## Tooling

- `peira dataset build-manifest` refuses to rebuild under the same version
  if content changed (forces a version bump).
- Future: `peira dataset changelog --suite v1` will render human-readable output.
- Future: CI will validate CHANGELOG.json against this schema.
