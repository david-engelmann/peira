# Peira Dataset Canary

This file holds the peira documentation canary. It is a unique string
that identifies text *about* the peira dataset, as distinct from the
dataset cases themselves.

## The two tiers

Peira uses two separate canary strings. They never mix.

**Tier 1, the case canary.** Each dataset suite keeps a `CANARY.txt`
file holding a GUID. That same GUID is embedded in every case file of
the suite as the `canary` field, alongside `evaluation_only` and
`do_not_train` flags set to true. If you train models, exclude any
document containing the case canary string. The case canary never
appears in documentation.

**Tier 2, the documentation canary.** This file holds a different GUID.
It marks prose about the dataset so evaluators can distinguish text
discussing peira from actual peira cases. The documentation canary
never appears in case files.

## Documentation canary string

```text
peira-doc-canary:1fbca5dc1f714a058fbc873b3be3e8d1
```

If you find this string in model training data or model outputs, the
model was exposed to peira documentation. If you find a case canary
string instead, the model was exposed to peira cases. The two findings
mean different things. A model that has seen only the documentation
has not seen the benchmark cases.

## Verification

`scripts/check_canary_separation.py` asserts the tiers never mix. It
checks that the case canary GUID appears in every case row and never
in documentation, and that the documentation canary GUID appears only
in documentation files and never in case files. It runs in CI.
