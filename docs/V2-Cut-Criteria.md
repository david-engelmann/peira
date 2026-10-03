# V2 Dataset Cut Criteria

**Status:** DRAFT for David's approval. The v2 official run (A12) proceeds only after these criteria are met.

**David's decision (2026-10-02):** We're going to v2, full data, every finished adapter, full holdout. Money is not a constraint.

## What's in v2

| Component | Cases | Status |
|-----------|-------|--------|
| 11 v2 families (21-31) | 4,701 | Sealed at v2.6.0 |
| Conversational suite (2 families) | 840 | Landed |
| Combo suite (2 pairs) | 800 | Landed |
| **Total** | **6,341** | |

## Cut criteria

The v2 dataset is cut (frozen for the official run) when ALL of the following hold:

1. **All 11 v2 families pass the 9 dataset gates** with 0 errors.
2. **Conversational and combo suites pass their gates** with 0 errors.
3. **Exhaustive row-by-row audit complete** on all v2 cases (the 4,400 v2 drafts item in the dataset-perfection checklist).
4. **Manifest sealed** with SHA-256 per file at the cut version.
5. **Immutable git tag** created: `dataset-v2-<version>` (R-10 provenance).
6. **No open P0/P1 dataset defects.**

## Post-cut rules

- After the cut tag, v2 cases are immutable. Any fix requires a version bump (D-36) and re-seal.
- The official run (A12) references the cut tag, never a branch head.
- The holdout (A13) uses the same cut version.

## Cost estimate (2026-10-02)

| Component | Estimate |
|-----------|----------|
| Public run (5,501 cases x 2 arms x 11 paid adapters) | ~$831 |
| Holdout run (500 cases x 2 arms x 11 paid adapters) | ~$76 |
| **Total** | **~$906** |

14 additional adapters run free (9 HF guardrails local, 5 Jev-family local, Lakera verified).

Pricing table version: 2026-10-02.2 (all 11 paid adapters now have rates).
