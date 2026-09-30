# Submission Disclosure and Operator Transparency

peira ranks decision models by how well they hold up under attack. For
those rankings to mean anything, the conditions behind each score have
to be public. This document states what peira measures, what it does
not, what submitters must disclose, and what the operator owes the
public in return. (R-14)

## What peira measures

peira measures attack success rate on paired decision cases. Each case
pairs a benign decision scenario with an attacked variant, and the
score is whether the attack flips the model's decision. Results are
reported per attack family with Wilson 95% confidence intervals, and
rankings come from the blind holdout, never from the public set alone.
Every number on the leaderboard carries its provenance. The methods
are public, the harness is public, and any vendor can reproduce any
number.

## What peira does not measure

- peira does not disclose vulnerabilities in any vendor's system. A
  leaderboard score is a measurement on public benchmark cases, not a
  security advisory. Results ship on the project's own schedule with
  no pre-briefs and no embargoes.
- peira is not a safety certification. A low attack success rate on
  these families does not mean a model is safe to deploy, and a high
  rate does not mean it is unsafe in every setting. The benchmark
  covers the attacks it covers, nothing more.
- peira does not claim real-world robustness. Cases are constructed
  scenarios with gold labels, not production traffic. The gap between
  the two is real and this document does not pretend otherwise.
- peira does not rank model quality overall. It ranks decision
  robustness under the specific attacks in the suite.

## Training-exclusion disclosure

Every submission carries a training-exclusion disclosure field. The
submitter states whether peira case material, public or holdout, was
present in the model's training data, to the best of their knowledge.
The field has three values. Clean, contaminated, or unknown. Unknown
is an acceptable answer. A wrong answer discovered later is not.

Disclosed contamination stays flagged on the public record next to
every score from that submission. The flag is not a punishment and it
does not remove the score. The blind holdout governs the ranked
number, and the holdout is designed to stay honest even when the
public set is contaminated. That is the BigFinanceBench posture.
Disclose, stay flagged, and let the holdout do its job.

Undisclosed contamination discovered after the fact is an integrity
incident. It is disclosed publicly, the affected scores are marked,
and the incident stays attached to the submitter's disclosure history.
The membership-inference stance below explains what counts as
discovery.

## Operator responsibilities

Anyone running peira officially, whether the maintainer or a third
party reproducing a ranked run, owes the following.

- Run the published harness unmodified for official runs. Custom
  harnesses are fine for exploration and must be labeled as such.
- Record the effective sampling configuration actually sent on the
  wire for every call, per R-04. A score without its sampling config
  is not a reproducible score.
- Respect the blind-holdout query budget. Twelve blind re-executions
  per adapter line per calendar year, counted publicly in
  `docs/Holdout-Query-Log.md`. See `docs/Holdout-Query-Budget.md`.
- Never probe the holdout for its contents. Debugging uses the public
  set. Holdout bytes never appear in logs, artifacts, error messages,
  or anything sent to a third party. See `docs/Holdout-OpSec.md`.
- Disclose any calibration or tuning done on the public set alongside
  the scores. Calibration artifacts are computed on the public set
  with the reasoning disclosed, per the adopted R-11 position, and
  that disclosure travels with the numbers.

## The blind-holdout protocol

Ranked runs execute against the holdout blind. Case IDs are
pseudonymized and no suite or arm labels are visible to the adapter,
so an adapter cannot detect that it is being measured on holdout
cases versus public ones. The holdout mirrors the public set's
severity mix per family, which keeps public-versus-holdout divergence
interpretable. The holdout's secrecy is the backstop. Cutoff-sliced
scoring is a control against accidental contamination, not a
replacement for that secrecy.

## Membership inference

Membership-inference signals are tripwires, not verdicts. A weak
statistical signal that a model may have seen peira cases triggers
investigation, never automatic punishment. No score is ever removed or
flagged on the strength of a membership-inference test alone. See
`docs/Holdout-Ranking-Design.md`. The contamination flag described
above is set by disclosure or by confirmed evidence, not by a
statistical test clearing some threshold.

## Annual operator-transparency note

Once per calendar year, the operator publishes a transparency note
covering the preceding year. It is a plain account of operations, not
a marketing document. It covers the following at minimum.

- Every official run executed, by adapter line, with dates.
- Holdout query-budget usage per adapter line against the published
  budget.
- Every holdout rotation, scheduled or burn-triggered, with the
  reason stated.
- Every training-exclusion disclosure flag set or changed, and every
  integrity incident with its resolution.
- Changes to the methodology, the dataset, or the policies in this
  document, with pointers to the decision records.
- The state of the refresh changelog and the pre-registered analysis
  plan for the monthly reports.

The note is published whether or not the year was quiet. A quiet year
gets a short note that says so. The first note covers the period from
the first ranked release through the end of that calendar year.
