# peira v2 dataset

The v2 case corpus. No cap on families or cases: v2 grows as new
attack families are designed and validated.

## Layout

```
dataset/v2/
  README.md            this file
  cases/
    manifest.json              SHA-256 per file, per-family MDE table
    <family>.jsonl             one file per family, one case per line
```

## Case ID scheme

Post-v1 families use `v2-<fam>-XXXX`:

- `v2-verb-0001` … verbosity_inflation (family 21)
- `v2-retp-0001` … retrieval_poisoning (family 22)
- `v2-evpos-0001` … evidence_positioning (family 23)
- `v2-xling-0001` … crosslingual_shift (family 24)
- `v2-edge-0001` … threshold_edge_hunting (family 25)
- future families: `v2-<3-letter family code>-XXXX`, zero-padded,
  dense numbering per family file.

## Manifest

`cases/manifest.json` carries the standard file inventory
(`sha256`, `n_cases`, `n_by_family`, `n_by_primitive`,
`n_by_severity`) plus a top-level `mdes` field: the per-family
design minimum-detectable-effect table in percentage points at the
published discordance rates.

```json
"mdes": {
  "verbosity_inflation": {
    "pd_10": 4.4, "pd_20": 6.3, "pd_30": 7.7, "pd_40": 8.9,
    "unit": "percentage_points", "n": 400,
    "note": "Design minimum detectable effects at n=400 per discordance rate pd."
  }
}
```

## Families

| # | Family | Cases | Status |
|---|--------|-------|--------|
| 21 | verbosity_inflation | 470 | shipped |
| 22 | retrieval_poisoning | 470 | shipped |
| 23 | evidence_positioning | 420 | shipped |
| 24 | crosslingual_shift | 420 | shipped |
| 25 | threshold_edge_hunting | 420 | shipped |

New families land as `<family>.jsonl` plus a manifest rebuild and a
CHANGELOG entry. The 400/family design target is a floor, not a
ceiling: families ship with as many cases as statistical power
requires.
