# Art. 55-shaped evaluation report. Design.

**Status** Design document, 2026-10-01
**Covers** EB-32 (design only)
**Data contract** [docs/schemas/art55-report.schema.json](schemas/art55-report.schema.json)

This document designs the report generator EB-32 specifies. The
generator itself is not built here. That is deliberate, not deferred
by accident. The report's core sections are sourced from run-artifact
v3 blocks (`threat_model`, `attack_provenance`, `adjudication_policy`,
`exposure_attestation`) that have not landed in `peira.artifacts`. The
blocks currently ride sealed inside the artifact's `config.v3` carrier
(see `site/SITE_DATA_SCHEMA.md`), which is a staging area, not a
schema. Building the generator against the carrier would bake in a
shape we intend to move. The generator gets built when artifact v3
lands, with this design and the schema above as its spec.

## What the report is

A per-run evaluation document a deployer can file. It answers the
question a regulator, a customer security review, or an internal risk
register asks after an adversarial evaluation. What was tested, under
what threat model, what was found, what was not tested, and where the
evidence lives. It is shaped on two standards.

**EU AI Act Article 55(1)(a).** Providers of general-purpose AI models
with systemic risk must evaluate their models with standardised
protocols and tools reflecting the state of the art, including
conducting and documenting adversarial testing aimed at identifying
and mitigating systemic risks. The report is that documentation. The
protocol, the threat model, the coverage, and the results in one
sealed document.

**NIST AI RMF MEASURE.** The report maps onto the MEASURE function.
The methods and metrics used (MEASURE 1), the evaluation as conducted
(MEASURE 2), and the residual risks and follow-up the results imply
(MEASURE 4). It does not claim to satisfy the whole framework. It
covers the measurement evidence a MEASURE process consumes.

## Report sections

Each section lists its source. Sections marked AVAILABLE NOW can be
filled from a sealed v2 artifact today. Sections marked V3-GATED need
the artifact v3 blocks and stay empty until v3 lands.

**1. Report identity.** AVAILABLE NOW. Report id, report contract
version, generation timestamp, generator name and version. The id
derives from the run artifact id so a report is always traceable to
exactly one measurement.

**2. Run reference.** AVAILABLE NOW. Adapter name and pin, artifact
URI, analysis lock, artifact version, run date. This is the "which
measurement" block. The seal check in section 11 confirms it.

**3. Protocol.** AVAILABLE NOW. peira version, suite, dataset version,
dataset manifest SHA-256, methodology reference. Enough for a third
party to reproduce the run.

**4. Threat-model statement.** V3-GATED. The attacker the run assumed.
Its capabilities, its knowledge, its query budget, and what is
explicitly out of scope. Sourced from the artifact v3 `threat_model`
block, recorded at run time rather than reconstructed after the fact.

**5. Coverage matrix.** AVAILABLE NOW. Families exercised with case and
eligible counts, totals, and the foreseeable-misuse coverage slice
(see [Foreseeable-Misuse-Coverage](Foreseeable-Misuse-Coverage.md)).
That slice says which misuse classes the run covered and which it did
not. Per-family attack provenance (mechanism description, literature
reference) is V3-GATED, sourced from the artifact v3
`attack_provenance` block.

**6. Results.** AVAILABLE NOW. Headline attack success rate and benign
accuracy, each with 95% confidence intervals and n. Per-family and
per-severity slices. The targeted-ASR trio (benign utility,
utility-under-attack, targeted ASR) where target decisions are known,
with the judge validation status carried alongside. Flip counts by
EB-30 documentation-pack tier. A drift summary when a prior run in the
same monitoring series exists (see
[Drift-Monitoring-Spec](Drift-Monitoring-Spec.md)).

**7. Corrective measures.** AVAILABLE NOW, filled by the deployer.
What was done or is planned in response, keyed to the EB-30 tiers.
Peira fills the findings. The deployer fills the response. The
generator never invents corrective measures.

**8. Residual risks.** AVAILABLE NOW, partly human-filled. What the run
did not test, which mitigations are assumed but unmeasured, and the
planned follow-up for each. This section is where "a clean run means
the tested families did not flip the model" gets written down.

**9. Adjudication policy.** V3-GATED. How ambiguous outcomes were
decided. The abstention rule, the malformed-output rule,
tie-breaking, and the human-review trigger. Sourced from the artifact
v3 `adjudication_policy` block.

**10. Exposure attestation.** V3-GATED. Whether the evaluated
configuration matches the deployed one, who attested it, and when.
Sourced from the artifact v3 `exposure_attestation` block. Without
this, a report can silently describe a lab configuration.

**11. Provenance chain.** AVAILABLE NOW. The full tuple. Dataset
manifest SHA-256, code version, environment fingerprint, seal
verification result, artifact URI. The report is verifiable because
the artifact is verifiable (see
[Artifact-Versions](Artifact-Versions.md)).

## How the generator will work

When artifact v3 lands, the generator is a small command that takes a
sealed artifact path and emits the report JSON plus a rendered
Markdown twin. It reads v2 fields from the artifact and v3 fields
from the v3 blocks. It refuses to emit a report when required v3
blocks are absent, rather than emitting a report with silent gaps. It
verifies the analysis lock before generating anything. The Markdown
rendering is a straight projection of the JSON. One source of truth,
two shapes.

## What unblocks the build

Artifact v3 landing in `peira.artifacts` with the four blocks as
top-level schema fields. The fields are `threat_model`,
`attack_provenance`, `adjudication_policy`, and `exposure_attestation`.
Until then, the design and the schema above are the complete EB-32
deliverable, and the documentation pack template in
[Adversarial-Testing-Documentation-Pack](Adversarial-Testing-Documentation-Pack.md)
is the human-filled stand-in.

## Non-goals

The report does not decide reportability under Article 73. Counsel
does that. It does not certify a model as safe. It documents one
evaluation. It does not replace post-market monitoring. It feeds it.
And it never blends public and holdout numbers. A report covers one
artifact, and holdout artifacts are pseudonymized per the blind
holdout decision, so the report carries no suite or arm labels for
holdout runs.
