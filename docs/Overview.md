# peira docs

Everything in `docs/`, organized by what you are trying to do. Pick a path, or browse the full map below.

## Run the benchmark

1. [60-second quickstart](../README.md#60-second-quickstart): 100 cases, offline, prints its own receipts. Exit code 3 is expected, not an error.
2. [Methodology](Methodology.md): what ASR, eligibility, and the analysis lock mean. Read before quoting a number.
3. [CLI reference](CLI.md): every flag for `peira run` (concurrency, retries, transcripts, cache, replay).
4. [Troubleshooting](Troubleshooting.md): exact error, cause, fix.

## Add your model or guardrail

1. [Add your model](../README.md#add-your-model): the 15-line adapter snippet.
2. [Adapters](Adapters.md): the day-one adapters (install extras, API keys, pinned models, what each one measures).
3. [examples/minimal_adapter.py](../examples/minimal_adapter.py): the runnable version, about 25 lines.
4. [Taxonomy](Taxonomy.md): the three primitives and the 27 attack families documented in the taxonomy.
5. [Methodology](Methodology.md): the contracts your `decide()` output must satisfy, and what makes a case eligible.
6. [CLI reference](CLI.md): `--adapter` takes a dotted path. `--max-concurrency`, `--transcript`, and `--cache-dir` are the flags you will actually use.

## Contribute cases or work on peira itself

1. [Contributing](Contributing.md): the mechanical checklist. Read first; it defines "done".
2. [Dataset](Dataset.md): the authoring pipeline (templates, gates, review queue, manifests).
3. [Severity-Rubric](Severity-Rubric.md): consequence-based severity, assigned at authoring time, never derived from model behavior.
4. [Decisions](Decisions.md): the architecture decision records. Check here before proposing a design change; the argument already happened.
5. [Taxonomy](Taxonomy.md): family definitions for case authors.

## Full map

**Measure** (what the numbers mean):

- [Methodology](Methodology.md): how peira measures the adversarial robustness of decision models. The measurement contract: ASR, eligibility, analysis locks.
- [Methodology-Governance](Methodology-Governance.md). How verified rows, the saturation trigger, adaptive attacks, and the contamination assumption are handled after the methodology is frozen.
- [Taxonomy](Taxonomy.md): the three primitives (choice, score, abstain) and the 27 attack families.
- [Concepts](Concepts.md): the five ideas the benchmark rests on.
- [Severity-Rubric](Severity-Rubric.md): consequence-based severity tiers, for case authors.
- [Threat-Model](Threat-Model.md): what peira measures, and what it explicitly does not.
- [Claims](Claims.md): what peira claims, what it does not, and what is still unverified.
- [Submission-Disclosure](Submission-Disclosure.md): what peira measures and does not, the training-exclusion disclosure field, operator responsibilities, the blind-holdout protocol, and the annual transparency note.
- [Hardware](Hardware.md): hardware guidance per adapter tier.

**Build** (datasets and project mechanics):

- [Dataset](Dataset.md): the authoring pipeline (templates, gates, review queue, manifests, versioning).
- [Holdout-OpSec](Holdout-OpSec.md): the private holdout's operating rules (access, the contamination rule, freshness and rotation).
- [Holdout-Ranking-Design](Holdout-Ranking-Design.md): CI re-execution against the holdout, divergence reporting, gaming policy.
- [Refresh-Burn-Retirement-Policy](Refresh-Burn-Retirement-Policy.md): the refresh cadence and changelog, the two burn triggers, per-family saturation and retirement, and the pre-registered monthly analysis plan.
- [Compatibility](Compatibility.md): package vs dataset versioning (what works today, what is planned).
- [Decisions](Decisions.md): architecture decision records, D-1 onward.

**Use** (day to day):

- [CLI](CLI.md): every command and flag, generated from the parser. Never hand-edited, never stale.
- [Adapters](Adapters.md): the day-one adapters (extras, keys, pinned models, what each one measures).
- [Local-Run-Walkthrough](Local-Run-Walkthrough.md): from install to scored run, with real output.
- [Reproducibility](Reproducibility.md): pinned lockfiles and the Docker image for byte-exact environments.
- [What-Peira-Does](What-Peira-Does.md): a worked example with one real case.
- [Compare-Report-Guide](Compare-Report-Guide.md): how to read compare and report output.
- [Troubleshooting](Troubleshooting.md): exact error, cause, fix. Every user-facing CLI error lives here.
- [FAQ](FAQ.md): the questions everyone asks first.
- [Glossary](Glossary.md): terms, defined once.

**Deploy** (for teams shipping a decision model)

- [Adversarial-Testing-Documentation-Pack](Adversarial-Testing-Documentation-Pack.md). Flip classes mapped to incident-severity tiers shaped on the EU AI Act, the reporting clock each tier implies, and the corrective action per tier.
- [Drift-Monitoring-Spec](Drift-Monitoring-Spec.md). The scheduled re-run protocol and the statistical method for detecting attack-success drift over calendar time.
- [Foreseeable-Misuse-Coverage](Foreseeable-Misuse-Coverage.md). Intended use, the foreseeable misuses of decision models, which attack families cover each one, and the stated gaps.
- [Art55-Report-Design](Art55-Report-Design.md). Design and data contract for the per-run evaluation report. Design only. The generator waits on run-artifact v3.
- [Landing-Page-Readiness](Landing-Page-Readiness.md). What "ready" means for the public leaderboard page.
- [Announcement-Package](Announcement-Package.md). Prepared launch copy. Draft, not published.

**Project**:

- [Contributing](Contributing.md): the checklist for PRs.
- [Gate-Exit-Criteria](Gate-Exit-Criteria.md): the campaign gates from code freeze to the official runs. Entry and exit criteria, required evidence, and the decision rule per phase.
- [Overview](Overview.md): this page.
