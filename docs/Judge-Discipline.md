# Judge Discipline for Internal LLM-Assisted Loops

peira's leaderboard scoring is deterministic: the adapter's *decision* is
graded directly against gold labels, with no model in the scoring path.
That is deliberate and load-bearing (see D-42: grade the outcome, not the
path). This document governs the one place LLM judgment *is* used inside
peira: internal process work such as adjudicating disputed cases, triaging
failure modes, and QA-ing case authorship. The discipline below keeps
those loops honest.

## The binary-judge protocol

Every internal LLM-assisted judgment must satisfy all five requirements:

1. **Binary verdict per failure mode.** The judge answers one question
   per failure mode ("does this case exhibit X: yes/no"), never a free
   score or a holistic grade. Multi-aspect assessments decompose into
   one binary verdict each. Continuous scores invite calibration drift
   that goes unaudited; binary verdicts make error rates countable.

2. **Written rationale (critique).** Every verdict ships with a short
   written rationale quoting the evidence it rests on. The rationale is
   the audit trail: a verdict whose rationale cannot be checked against
   the case is a verdict without a witness.

3. **Rubric with labeled examples in the prompt.** The prompt carries the
   decision rubric *and* at least two labeled examples per failure mode
   (one positive, one negative). The rubric is versioned alongside the
   prompt; a verdict is meaningless without the rubric version that
   produced it.

4. **Chain-of-thought enabled.** The judge reasons step-by-step before
   committing to the verdict. CoT is what moves assistant-judges from
   unusable to usable on non-trivial adjudication; a verdict without
   visible reasoning is not reviewable.

5. **Validated against a human-adjudicated slice.** Before first use and
   after every rubric change, the judge is validated against a
   human-adjudicated slice of the same task, reporting **TPR and TNR
   per failure mode** (or Cohen's kappa where the task is not binary).
   Never raw agreement: raw agreement is inflated by class imbalance and
   hides the "always pass" judge. A judge that cannot beat a trivial
   baseline on TPR/TNR is not deployed.

## Re-validation on rubric change

Criteria drift is the norm, not the exception. Any change to the rubric
or the labeled examples invalidates the previous validation: the judge
is re-run against the human slice (or a fresh slice when the change
redefines the failure modes) and the new TPR/TNR is recorded with the
rubric version. The rubric is a living document; the validation log is
its changelog.

## Anti-self-grading (protocol invariant)

No adapter, and no model from the same family as the adapter under test,
may serve as a judge or grader over that adapter's leaderboard entry.
This is a protocol invariant, not a suggestion (see D-41). It is
currently moot for scoring since scoring is deterministic, and it is
written down so the day any model-graded check is added, a future
contributor cannot violate it by accident. peira's blind-holdout design
(pseudonymous call IDs, zero gold in adapter-visible context) already
embodies the principle: the model must not grade its own bake-off entry.

## Scope

This discipline covers internal loops only: adjudication of disputed
cases, failure-mode triage, case-authoring QA. It does not touch
leaderboard scoring, which stays judge-free. If the safety-policy suite
(guardrail-native, currently gold-labeled) ever needs model-graded
scoring, this discipline pre-applies. Confirm the suite stays
gold-labeled before reaching for a judge.
