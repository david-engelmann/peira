# Peira v1 Datasheet

This datasheet follows the Datasheets for Datasets format. It describes
the public peira v1 benchmark suite. It carries the peira documentation
canary so readers can distinguish this prose from the benchmark cases.

```text
peira-doc-canary:1fbca5dc1f714a058fbc873b3be3e8d1
```

## Motivation

Peira measures how well decision models hold up under attack. The
benchmark presents paired cases. Each pair has a benign control and an
attacked variant. The model must make the right decision on both. The
gap between control and attacked performance is the robustness signal.

The dataset was created by the peira project to give the field a
shared, versioned, adversarial benchmark for decision models. There was
no public benchmark that paired benign and attacked decisions across a
broad set of attack families with statistical rigor.

## Composition

The public v1 suite holds 2,000 cases across 10 attack families, 200
cases per family. The families cover prompt-level attacks such as
policy paraphrase, negation games, distractor flooding, and confidence
spoofing, among others. The full taxonomy lives in `docs/Taxonomy.md`.

Each case is a JSON object with a benign variant and an attacked
variant. Each variant has an input prompt, a list of decision options,
and an expected or target decision. Cases also carry severity, notes,
and machine-readable flags.

A separate private holdout of 500 cases exists for blind re-evaluation.
It is never published. Its IDs, contents, and scoring data never appear
in this repository.

## Collection and preprocessing

Cases were authored by the peira team, both by hand and with
model-assisted drafting followed by human review. Every case passes
nine automated validation gates before it is sealed into a manifest.
Critical cases receive human review with recorded justifications.

The suite is versioned. Manifests record SHA-256 checksums for every
case file. The changelog in `docs/Dataset-Changelog.md` records every
correction.

## Uses

Use peira v1 to benchmark decision models, guardrails, and classifiers
under adversarial conditions. The paired design isolates attack effect
from base capability. Report results with the 95 percent confidence
intervals the tooling computes.

Do not train on peira cases. Every case carries `evaluation_only` and
`do_not_train` flags set to true, and the suite's case canary string
(`CANARY.txt`) marks training data for exclusion. Training on the
benchmark invalidates its results.

## Distribution

The public suite ships in this repository under `dataset/v1/cases/`.
It is released under CC-BY-4.0. The code is MIT licensed. See
`LICENSE` for details.

## Maintenance

The peira project maintains the dataset. Corrections land as versioned
releases with changelog entries. The holdout is rotated on a published
schedule described in `docs/Holdout-OpSec.md`.

## Contact

File issues in the peira repository issue tracker.
