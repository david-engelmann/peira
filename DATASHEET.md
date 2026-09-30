# Peira Datasets Datasheet

This datasheet follows the Datasheets for Datasets format
(Gebru et al.). It describes the public peira benchmark suites,
namely peira-v1, peira-v2, peira-trial, and peira-safety-policy. It carries
the peira documentation canary so readers can distinguish this prose
from the benchmark cases.

```text
peira-doc-canary:1fbca5dc1f714a058fbc873b3be3e8d1
```

## Motivation

**For what purpose were the datasets created**

Peira measures how well decision models hold up under attack. The
benchmarks present paired cases. Each pair has a benign control and
an attacked variant. The model must make the right decision on both.
The gap between control and attacked performance is the robustness
signal. The datasets exist to give the field a shared, versioned,
adversarial benchmark for decision models with statistical rigor on
every headline number.

**Who created the datasets and on whose behalf**

The datasets were created by the peira project, an independent
open-source effort led by David Engelmann, on behalf of the peira
project itself. No outside organization commissioned them.

**Who funded the creation of the datasets**

The peira project funded the work from its own resources. No grant,
sponsor, or vendor paid for dataset creation, and no funder reviewed
or approved the cases.

## Composition

**What do the instances represent**

Each instance is a paired adversarial decision case. One instance
holds a benign decision scenario (a prompt, an explicit decision
vocabulary, and the gold decision) and an attacked variant of the
same scenario (a perturbed prompt and the decision the attacker
tries to induce, or a null target when the attack only tries to
change the decision). The model under test sees both variants.

**How many instances are there in total**

peira-v1 holds 2,000 public cases across 10 attack families, 200
cases per family. A separate private holdout of 500 v1 cases exists
for blind re-evaluation and is never published. peira-v2 is the
living successor suite. Its first family file,
verbosity_inflation, holds 470 cases, and further families ship as
they are authored and reviewed. peira-trial is a 100-case branded
fixture for quick adapter smoke tests, not a benchmark. The
peira-safety-policy suite holds 25 guardrail-native policy cases.
Exact counts per suite are pinned in each suite's sealed manifest,
which is the authority when this prose and the bytes disagree.

**Is the dataset a sample or the complete set**

Each suite is a curated collection, not a sample from a larger
corpus. The v1 families were authored to fixed per-family quotas.
The v2 families grow toward statistical power rather than a fixed
number. The holdout is a separate random partition that never
mixes with the public set.

**What data does each instance consist of**

The case schema is documented in `docs/Dataset.md` and in machine-
readable form in every suite's `croissant.json`. Each case carries
a stable `case_id`, a `family` id from the taxonomy, a `primitive`
(choice, score, or abstain), a consequence-based `severity`
(critical, high, medium, or low), the benign and attacked variants
described above, free-text `notes`, optional R-10 `provenance`
fields recording where the case came from, and two boolean flags,
`evaluation_only` and `do_not_train`, both true by default.

**Is there a label or target for each instance**

Yes. The benign variant carries `expected_decision`, the gold label
used for scoring base capability. The attacked variant carries
`target_decision`, the decision the attacker tries to induce, or
null when the attack's goal is only to flip the decision away from
gold. For score primitives the variants carry `expected_score` in
the unit interval instead.

**Is any information missing from individual instances**

The `provenance` object is optional. Cases that predate provenance
capture omit it. The `notes` field is free text and may be empty on
low-severity cases. Critical-severity cases are required to carry
notes justifying the tier, enforced at manifest-build time.

**Are relationships between instances made explicit**

The `was_derived_from` provenance field names the source case when
a case was adapted from an earlier one, for example a v2 case
reworked from a v1 case. Family membership and the benign/attacked
pairing are explicit fields on every case.

**Are there recommended data splits**

The public suites ship as single pools. The v1 public 2,000 and the
private 500-case holdout are disjoint by construction, and the
holdout is the scoring authority for published claims. There are no
train/dev/test splits because the datasets are evaluation-only.

**Are there errors, noise, or redundancies**

Every case passes nine automated validation gates before sealing,
and the project runs periodic regrade audits with pre-registered
defect bars. Corrections ship as versioned releases with changelog
entries rather than silent edits. Known limitations of a release
are recorded in its changelog entry.

**Is the dataset self-contained**

Yes. Each suite ships its case files, its sealed `manifest.json`
with SHA-256 digests, its `croissant.json` metadata record, and
its `CANARY.txt`. No external resource is needed to use the data.

**Does the dataset contain confidential or sensitive data**

No. All cases are synthetic adversarial scenarios authored for the
benchmark. They contain no real user data, no credentials, no
nonpublic system details, and no information that could identify a
person.

**Does the dataset relate to people**

No. Cases are fictional decision scenarios. Some scenarios mention
fictional roles (an editor, a loan officer) as part of the prompt
fiction, but no case describes a real person and no human subjects
were involved in data collection.

## Collection process

**How was the data acquired**

Cases were authored by the peira team, by hand and with
model-assisted drafting followed by human review. Attack prompts
were designed against the published taxonomy in `docs/Taxonomy.md`.
There was no scraping, no crowdsourcing, and no third-party data
source.

**What procedures were used**

Authoring followed the dataset pipeline in `docs/Dataset.md`. New
cases are drafted from generator templates, validated against the
case schema, scored by the nine validation gates, and reviewed
through the review queue. Critical-severity cases require a human
reviewer to record why the case earned the tier before the manifest
build accepts them.

**Who was involved and how were they compensated**

The peira project team authored and reviewed the cases as part of
the project's own work. No crowd workers or external annotators
were used.

**Over what timeframe was the data collected**

The v1 suite was authored during the project's 2026 benchmark
sprint. The v2 and safety-policy suites are living collections that
grow as families are authored and reviewed. Each suite's manifest
records the UTC build timestamp of its release.

**Was any ethical review conducted**

No formal ethics review was conducted. The datasets contain no
human subjects, no personal data, and no real-world records, so
there was no human-subjects component to review. The project's
contamination policy (`docs/Contamination-Policy.md`) governs how
the public and holdout partitions are handled.

**Consent, notification, and revocation**

Not applicable. No data was collected from individuals, so no
consent was sought and no revocation mechanism is needed.

## Preprocessing, cleaning, and labeling

**Was any preprocessing or labeling done**

Labeling is the authoring itself. Every benign variant carries its
gold decision and every attacked variant its target decision,
assigned by the author and checked by the validation gates. The
gates reject cases whose expected decision is not among the input
options, cases with malformed prompts, and cases that fail schema
validation. No text normalization or cleaning pipeline transforms
the prompts. What the author wrote is what ships.

**Was the raw data saved**

The authored JSONL is the raw data. There is no separate raw stage.

**Is the labeling software available**

Yes. The validation gates, the manifest builder, and the review
queue tooling are in this repository under `python/peira/`, MIT
licensed. The exact gate versions that sealed a release are pinned
by the peira package version recorded in the manifest.

## Uses

**Has the dataset been used for any tasks already**

The suites exist to benchmark decision models, guardrails, and
classifiers under adversarial conditions. The project's public
leaderboard reports adapter results measured with the peira runner.
The paired design isolates attack effect from base capability.

**What other tasks could the dataset be used for**

The cases suit red-team prompt engineering research, guardrail
regression testing, decision-calibration studies, and attack-family
ablation work. The per-family manifests make family-level analysis
straightforward.

**Is there anything about composition or collection that might
impact future uses**

The suites are adversarial by design. They overrepresent attack
pressure relative to ordinary traffic, so they measure worst-case
robustness, not typical-case accuracy. The v1 families are fixed
quotas of 200 cases each, which bounds the statistical power of
fine-grained family comparisons. Scores on the public set should
be read alongside blind holdout re-evaluations, since public cases
are assumed contaminated from day one.

**Are there tasks the dataset should not be used for**

Do not train on peira cases. Every case carries `evaluation_only`
and `do_not_train` set to true, and the suite's case canary marks
training corpora for exclusion. Training on the benchmark
invalidates its results. Do not use the suites to make safety
claims about a deployed system without also running the blind
holdout evaluation.

## Distribution

**Will the dataset be distributed to third parties**

Yes. The public suites are published for anyone to download and
use under their license.

**How and when is it distributed**

The suites ship in this repository under `dataset/`. Releases are
cut as immutable git tags named `dataset-<suite>-<semver>` and
registered in `data/dataset-releases.json` with the manifest and
croissant digests at the tag. The registry and its CI verification
are described in `docs/Provenance.md`.

**Under what license**

The datasets are released under CC-BY-4.0. The code in this
repository is MIT licensed. See `LICENSE` for details.

**Have third parties imposed restrictions**

No. The project holds the rights it licenses. No third-party data
is included.

**Do export controls apply**

The project is not aware of any export controls or regulatory
restrictions applying to these synthetic benchmark cases.

## Maintenance

**Who maintains the dataset**

The peira project maintains the datasets. Corrections land as
versioned releases with changelog entries. Manifests are immutable.
A correction is a new version, never an edit in place.

**How can the maintainer be contacted**

File issues in the peira repository issue tracker.

**Is there an erratum**

Corrections are recorded per release in the dataset changelog
(`docs/Dataset-Changelog.md` and the per-suite `CHANGELOG.json`
files). There is no separate erratum document.

**Will the dataset be updated**

Yes. The v2 and safety-policy suites are living collections. The
v1 suite is corrected as defects are found. Every change ships as
a new semver version with a new sealed manifest, a new croissant
record, and, for formal releases, a new immutable tag.

**Will older versions stay available**

Yes. Versioned manifests and immutable release tags keep every
released version reproducible. Run artifacts record the dataset
version and manifest digest they scored against, so old results
stay comparable after a release.

**Can others contribute**

Contributions follow the repository's normal pull-request process.
New cases must pass the schema validation, the nine gates, and
the review queue, including severity-note justification for
critical cases, before a manifest build will accept them.
