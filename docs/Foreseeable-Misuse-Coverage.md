# Foreseeable-misuse coverage matrix

**Status** Product spec, 2026-10-01
**Covers** EB-33

Peira tests decision models. These are systems that read a situation
and return approve, deny, a score, or an abstention. This document
enumerates the intended use of such models and the reasonably
foreseeable misuses of them. It then shows which peira attack families
cover each misuse and where the coverage has gaps. The exercise
follows the NIST AI Risk Management Framework's MAP function, which
asks teams to identify and document foreseeable misuses beyond the
intended purpose (see the Generative AI Profile's suggested actions on
MAP). The matrix turns "we have 25 families" into "we cover this much
of the misuse space," and it says out loud what we do not cover.

Misuses are described at the class level. Each names what the attacker
wants, not how to do it. This is a coverage document, not an attack
manual.

## Intended use

Decision models as peira evaluates them take structured or
semi-structured input (a claim, an application, a piece of content, a
retrieved document) and return a decision. Approve or deny, a numeric
score, or an abstention that routes to a human. Deployments include
content moderation, fraud and abuse screening, hiring and lending
pipelines, medical and safety triage, and LLM-as-a-judge evaluation
harnesses. The model is trusted to apply a policy or rubric to the
input as given.

## The misuse classes and their coverage

Each misuse names the attacker's goal. "Covered by" lists the peira
families that exercise that goal. Family descriptions follow
[Taxonomy](Taxonomy.md).

**M1. Getting a blocked thing approved.** The attacker wants the model
to approve what the policy would deny. A harmful request, a
fraudulent claim, a forbidden action. Covered by
instruction_override, indirect_injection, policy_paraphrase,
encoding_evasion, crosslingual_shift, criteria_smuggling. This is the
broadest coverage in the matrix. Six families attack the approve path
from different angles.

**M2. Getting a legitimate thing denied.** The attacker wants a valid
request blocked. A competitor's listing removed, a legitimate user
locked out, a review pipeline flooded with false alarms. Covered by
negation_games, abstain_forcing, option_order, criteria_order. The
deny path gets less attention than the approve path across the
industry. Peira covers it deliberately because the harm is real.

**M3. Laundering a decision through fabricated authority.** The
attacker plants fake authorization signals so the model believes the
decision was already made. Forged approvals, fake audit trails,
many-shot fake precedent. Covered by authority_fabrication,
state_poisoning, precedent_stacking.

**M4. Gaming a score.** The attacker moves a numeric score across a
threshold. By anchoring it, by inflating confidence around it, or by
winning on polish instead of substance. Covered by score_anchoring,
confidence_spoofing, verbosity_inflation.

**M5. Drowning the decision pipeline.** The attacker degrades decision
quality at scale rather than flipping one case. Noisy state, forced
abstentions that pile work onto human reviewers. Covered by
distractor_flooding, abstain_forcing.

**M6. Steering with evidence order.** The attacker reorders
byte-identical evidence to exploit primacy and recency effects.
Covered by evidence_positioning.

**M7. Poisoning the retrieval corpus.** The attacker plants false
facts in the documents the model retrieves, so the decision is steered
by lies the model trusts. Covered by retrieval_poisoning.

**M8. Exploiting date and threshold logic.** The attacker uses
misleading date phrasing or numeric framing to get a clean, confident,
wrong answer where code should have done the math. Covered by
temporal_numeric_traps.

**M9. Social-engineering the judge.** The attacker manipulates the
decision-maker instead of the case. Flattery, identity validation,
agreeableness pressure, consistency traps, or pleading the case's
merits directly. Covered by judge_sycophancy, self_advocacy.

**M10. Smuggling contradictory rules.** The attacker injects mutually
contradictory policy clauses crafted to resolve in the attacker's
favor. Covered by contradiction_injection.

**M11. Burying the payload.** The attacker hides hostile content
behind multi-hop indirection so surface inspection misses it. Covered
by indirection.

**M12. Exploiting literal reading.** The attacker uses face-value
scoping and negation tricks the model reads literally. Covered by
literal_reading.

The conversational suite adds two more. **M13** is escalating across
turns (multi_turn_escalation). **M14** is splitting the decision so no
single turn looks attackable (decision_splitting).

## The uncovered set

Honest gaps, stated plainly.

- **Action execution.** Peira tests the decision, not what happens
  after it. A model that correctly denies but whose tooling executes
  anyway is outside the matrix.
- **Multimodal inputs.** All current families are text. Image, audio,
  and document-layout attacks on the decision are uncovered.
- **Reviewer psychology over time.** abstain_forcing covers
  denial-of-decision as a mechanism, but long-horizon reviewer fatigue
  and trust calibration are not modeled.
- **Supply-chain and weight tampering.** The matrix assumes the model
  under test is the model deployed. Backdoored weights and poisoned
  fine-tunes are a different evaluation.
- **Multi-agent collusion.** Attacks coordinated across several model
  instances or tool calls are uncovered. Every family is single-shot.
- **Infrastructure-scale denial of decision.** Beyond the abstain
  primitive, cost-exhaustion and latency attacks on the serving layer
  are not decision attacks and are not covered.

Each gap is a candidate for a future family or a documented out of
scope. The matrix is versioned with the taxonomy. When a family lands
that covers a gap, the gap moves to the covered list with the family
name attached.

## How to use this matrix

A run's documentation pack (see
[Adversarial-Testing-Documentation-Pack](Adversarial-Testing-Documentation-Pack.md))
cites this matrix and lists which misuse classes the run exercised.
The Art. 55 report carries the same slice in machine-readable form.
A deployer reading either one can see at a glance that, say, M7 was
tested and action execution was not, and decide whether that matches
their threat model.
