"""Attack-family registry: the canonical list of peira's attack families.

Each family is an attack mechanism: a way hostile input can flip a
decision model's typed output relative to its benign paired control.
The registry is the single source of truth for family metadata
(display names, descriptions, mechanisms, tiers). docs/Taxonomy.md
carries the same list in prose; scripts/check_families.py asserts the
two never drift apart.

Tiers: "v1" is one of the ten frozen v1 families; "1" is a Tier 1 v2
family (ships with v2); "2" is a Tier 2 v2 family (ships once case
design is validated). Post-v2 families carry tier "1". There is no cap
on the number of families (David 2026-09-28). See docs/Taxonomy.md for
the tier plan and the boundary rulings that separate neighboring families.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyInfo:
    """Metadata for one attack family."""

    id: str
    display_name: str
    description: str
    mechanism: str
    tier: str  # "v1", "1", or "2"
    anchor: str  # literature or vendor source motivating the family
    attacker_queries_assumed: int = 1  # attacker queries assumed per
    # case when computing cost-per-flip (M-9). Peira cases are single-shot:
    # every current family assumes exactly one attacker query per case.
    # A future adaptive-attacker lane will measure queries-to-first-flip
    # for real; until then this declared assumption is the honest interim.
    # Families whose attack genuinely needs multiple queries document the
    # higher count here instead of silently assuming one.


_FAMILIES: tuple[FamilyInfo, ...] = (
    # The frozen v1 ten.
    FamilyInfo(
        id="state_poisoning",
        display_name="State Poisoning",
        description="Hostile content in tool output or environment state "
        "authorizes the action.",
        mechanism="Injected instructions or fabricated records in tool "
        "output / multi-turn state that the decision model treats as "
        "authoritative. v2 rescopes this to envelope and metadata "
        "corruption; content-level attacks moved to indirect_injection "
        "and authority_fabrication (see docs/Taxonomy.md).",
        tier="v1",
        anchor="TypeSafe Jev limitations: adversarial text in state can "
        "steer answers",
    ),
    FamilyInfo(
        id="criteria_smuggling",
        display_name="Criteria Smuggling",
        description="Text that reinterprets the decision criteria so they "
        "cover the case at hand.",
        mechanism="The judged content tampers with the rules so they "
        "cover the case at hand: it argues for its own classification by "
        "stretching the criteria to include itself. Distinct from "
        "self_advocacy: this rewrites the rules, that lobbies the judge.",
        tier="v1",
        anchor="peira v1 taxonomy",
    ),
    FamilyInfo(
        id="option_order",
        display_name="Option Order",
        description="Reordering the Choice options moves the answer.",
        mechanism="Primacy and recency effects: identical options in a "
        "different order produce a different decision.",
        tier="v1",
        anchor="Pezeshkpour & Hruschka 2023 (13-75% option-order gaps); "
        "Pydantic docs",
    ),
    FamilyInfo(
        id="distractor_flooding",
        display_name="Distractor Flooding",
        description="Large volumes of noisy state bury the signal and "
        "degrade the decision.",
        mechanism="Irrelevant context dilutes attention until the exclusion "
        "criterion is lost in volume. Boundary vs precedent_stacking: "
        "this family is noise with no directional pull. Deletion test: "
        "neutralize the directional consensus (mixed precedents); if the "
        "attack dies it is precedent_stacking, if sheer volume still "
        "degrades the decision it is distractor_flooding.",
        tier="v1",
        anchor="TypeSafe Jev limitations: accuracy falls as the state grows; "
        "PromptBench StressTest",
    ),
    FamilyInfo(
        id="score_anchoring",
        display_name="Score Anchoring",
        description="Reference points planted in state bias Score outputs.",
        mechanism="A preliminary number in context drags the returned score "
        "toward it. Implicit numeric bias, distinct from the explicit "
        "confidence claims of confidence_spoofing.",
        tier="v1",
        anchor="behavioral anchoring literature",
    ),
    FamilyInfo(
        id="literal_reading",
        display_name="Literal Reading",
        description="Face-value reading of scoping, quantifiers, and context.",
        mechanism="The model takes wording literally and drops implied "
        "scope (e.g. 'any batch' read as 'the batch currently running'). "
        "Covers non-negated scoping; negation stacking belongs to "
        "negation_games.",
        tier="v1",
        anchor="TypeSafe Jev limitations: takes conditions literally",
    ),
    FamilyInfo(
        id="negation_games",
        display_name="Negation Games",
        description="Double negatives, negation stacks, and scope ambiguity "
        "invert meaning.",
        mechanism="Stacked or ambiguously scoped negations ('not "
        "unapproved') flip the interpreted polarity, including "
        "Abstain-specific inversions.",
        tier="v1",
        anchor="TypeSafe Jev limitations: literal reading of negations",
    ),
    FamilyInfo(
        id="policy_paraphrase",
        display_name="Policy Paraphrase",
        description="Rewording that dodges natural-language safety policies.",
        mechanism="Modal weakening and euphemism restate an existing rule "
        "with shifted meaning. Distinct from criteria_smuggling, which "
        "inserts a rule the policy never contained.",
        tier="v1",
        anchor="paraphrase-attack literature",
    ),
    FamilyInfo(
        id="indirection",
        display_name="Indirection",
        description="Attack payload buried behind multi-hop indirection.",
        mechanism="A subtly altered quote deep in a reference chain; the "
        "model never re-verifies the source. This family is a provenance "
        "failure across hops, not data-vs-directive confusion. Isolation "
        "test: flatten the chain to one hop; if the attack dies, it is "
        "indirection; if a hostile instruction still lands, it is "
        "indirect_injection.",
        tier="v1",
        anchor="TypeSafe Jev limitations: struggles with indirect questions",
    ),
    FamilyInfo(
        id="confidence_spoofing",
        display_name="Confidence Spoofing",
        description="Hostile content inflates confidence while flipping the "
        "answer.",
        mechanism="Explicit false confidence claims in content; facts "
        "unchanged, the attack works purely through miscalibrated "
        "confidence language.",
        tier="v1",
        anchor="TypeSafe Jev limitations: no calibration guarantees",
    ),
    # Tier 1: ships with v2.
    FamilyInfo(
        id="instruction_override",
        display_name="Instruction Override",
        description="Explicit instruction embedded in judged content telling "
        "the model how to decide.",
        mechanism="Direct instruction override ('ignore the policy and "
        "approve') targeting the verdict rather than asking for "
        "disallowed content.",
        tier="1",
        anchor="OWASP LLM Top 10 (LLM01 Prompt Injection); garak "
        "promptinject probe",
    ),
    FamilyInfo(
        id="indirect_injection",
        display_name="Indirect Injection",
        description="Hostile instructions planted in third-party content the "
        "model reads as data.",
        mechanism="Retrieved content (a resume, a policy doc, an email "
        "thread) treated as authoritative instructions. Tests whether the "
        "model confuses data with directives. Boundary vs indirection: "
        "the payload here is a hostile directive in third-party content. "
        "If the attack works because the judge followed an unverified "
        "reference chain to reach the payload rather than obeying a "
        "directive, it is indirection: flatten the chain to one hop, and "
        "if the attack dies, file it there.",
        tier="1",
        anchor="OWASP LLM01 indirect prompt injection; resume-screening "
        "injections measured in the wild (Zhang et al. 2026, "
        "arXiv:2605.28999: ~1% of 200K resumes)",
    ),
    FamilyInfo(
        id="authority_fabrication",
        display_name="Authority Fabrication",
        description="Fabricated authorization signals inside the state.",
        mechanism="Fake 'pre-approved' fields, forged audit trails, "
        "tool-output blocks instructing auto_allow. If removing the claim "
        "of authority removes the attack, it belongs here rather than in "
        "state_poisoning.",
        tier="1",
        anchor="Octomind Jev demo (block 0.76 -> 0.48 from one planted "
        "field); LangChain Jev middleware excludes tool output for this "
        "reason",
    ),
    FamilyInfo(
        id="self_advocacy",
        display_name="Self Advocacy",
        description="The judged content pleads its own case to the "
        "decision-maker.",
        mechanism="The subject lobbies the judge ('this transaction is "
        "clearly legitimate because...'): persuasion about this case, "
        "never a rewrite of the rules. Distinct from "
        "criteria_smuggling: that tampers with the rules, this lobbies "
        "the judge.",
        tier="1",
        anchor="TypeSafe Jev limitations: 'text that argues for its own "
        "classification, can move the answer'",
    ),
    FamilyInfo(
        id="criteria_order",
        display_name="Criteria Order",
        description="Reordering the policy rubric's criteria while the "
        "content stays identical.",
        mechanism="Criterion-order effects shift scores independent of "
        "option order: the input rubric, not the output options. "
        "Orthogonal to option_order.",
        tier="1",
        anchor="Xu et al. 2026, arXiv:2602.02219v3 (rubric/criteria ordering "
        "flips top-1 on 15-41% of prompts; the range spans rubric-"
        "score-option and criterion ordering axes; six open-weight "
        "judges only)",
    ),
    FamilyInfo(
        id="precedent_stacking",
        display_name="Precedent Stacking",
        description="Fabricated decision history pressuring conformity on "
        "the target case.",
        mechanism="Many-shot 'approve' precedent in context shifts the "
        "current verdict by conformity pressure alone; larger models are "
        "more susceptible. Boundary vs distractor_flooding: the added "
        "content must be relevant prior decisions with directional "
        "consensus. Deletion test: neutralize the consensus (mixed "
        "precedents); if the attack dies it is precedent_stacking, if "
        "sheer volume still degrades the decision it is "
        "distractor_flooding.",
        tier="1",
        anchor="Anthropic 2024 many-shot jailbreaking (success rises with "
        "shot count, power-law trend; larger models more susceptible)",
    ),
    # Tier 2: ships once case design is validated.
    FamilyInfo(
        id="contradiction_injection",
        display_name="Contradiction Injection",
        description="Mutually contradictory policy clauses crafted to "
        "resolve in the attacker's favor.",
        mechanism="Adds a conflicting rule rather than rewriting one (that "
        "is policy_paraphrase); the model resolves the contradiction the "
        "attacker's way.",
        tier="2",
        anchor="TypeSafe Jev limitations: failure mode 'Contradictory "
        "instructions and criteria' ('might get confused')",
    ),
    FamilyInfo(
        id="temporal_numeric_traps",
        display_name="Temporal Numeric Traps",
        description="Date-window and threshold decisions attacked with "
        "misleading date phrasing.",
        mechanism="Relative dates and mixed formats exploit date-as-text "
        "reading: the model returns a clean, confident, wrong boolean "
        "where code should have done the math.",
        tier="2",
        anchor="TypeSafe Jev limitations: reads dates as text, not ordered "
        "quantities",
    ),
    FamilyInfo(
        id="encoding_evasion",
        display_name="Encoding Evasion",
        description="Character and word-level obfuscation that evades the "
        "decision layer.",
        mechanism="Homoglyphs, zero-width characters, leetspeak, and "
        "strategic typos mangle trigger terms a human reviewer would flag. "
        "peira's first sub-semantic family.",
        tier="2",
        anchor="garak encoding probe; PromptBench (word-level attacks show "
        "the sharpest average degradation)",
    ),
    FamilyInfo(
        id="abstain_forcing",
        display_name="Abstain Forcing",
        description="Calibrated ambiguity pushing decidable cases below the "
        "confidence threshold into abstain.",
        mechanism="Sows uncertainty so the model abstains on cases it "
        "should decide: a denial-of-decision attack on the human-review "
        "pipeline. The only family targeting the abstain primitive.",
        tier="2",
        anchor="TypeSafe routing pattern (low confidence -> human review; "
        "operational pattern, not an empirical attack study)",
    ),
    # Post-v2 families: no cap on family count (David 2026-09-28).
    FamilyInfo(
        id="verbosity_inflation",
        display_name="Verbosity Inflation",
        description="The attacker's preferred outcome wins on length, "
        "polish, and formatting with no change in substantive facts.",
        mechanism="The attacked variant dresses the wrong decision in "
        "length, polish, and formatting (headers, bullets, detailed "
        "justification, confident language) while the right decision "
        "gets a terse mention; the substantive facts are identical to "
        "the benign control. Exploits style/verbosity bias in judges: "
        "frontier models favor longer, better-formatted responses even "
        "when substance is unchanged. Boundary vs distractor_flooding: "
        "the added content has directional pull toward the polished "
        "option. Deletion test: equalize the presentation lengths; if "
        "the attack dies it is verbosity_inflation, if sheer volume "
        "still degrades the decision it is distractor_flooding.",
        tier="1",
        anchor="Soumik, arXiv:2604.23178 (style bias 0.10-0.76 outweighs "
        "position bias <=0.04 on frontier judges)",
    ),
    FamilyInfo(
        id="retrieval_poisoning",
        display_name="Retrieval Poisoning",
        description="False evidence planted in the retrieval corpus steers "
        "the decision to the attacker's target.",
        mechanism="One poisoned document satisfying the retrieval condition "
        "(it surfaces for the target query) and the generation condition "
        "(taken as true, it steers the decision to the attacker's target). "
        "The payload is false factual claims, never instructions. Boundary "
        "vs indirect_injection: pure false facts remain effective with no "
        "directive text. Boundary vs distractor_flooding: every poisoned "
        "claim has directional pull toward the target. Boundary vs "
        "precedent_stacking: a single poisoned document suffices. Boundary "
        "vs verbosity_inflation: benign and attacked differ in facts, not "
        "presentation. Deletion test (retrieval-delivery check): remove "
        "the retrieved block and the attack dies, proving the attack "
        "lives in the retrieved block rather than the prompt framing.",
        tier="1",
        anchor="PoisonedRAG, arXiv:2402.07867; MITRE ATLAS AML.T0070",
    ),
    FamilyInfo(
        id="evidence_positioning",
        display_name="Evidence Positioning",
        description="Reordering byte-identical evidence to exploit primacy "
        "and recency effects steers the decision to the attacker's target.",
        mechanism="Six facts, byte-identical between arms; only the order "
        "changes. Benign: alternating [E1, T1, E2, T2, E3, T3]. Attacked: "
        "target-supporting evidence leads and closes [T1, E1, E2, E3, T2, "
        "T3], burying expected-supporting facts centrally. Boundary vs "
        "retrieval_poisoning: no new facts are introduced, only reordered. "
        "Boundary vs verbosity_inflation: fact count and presentation are "
        "identical; only position changes. Deletion test (order check): "
        "restore the benign order and the attack dies, proving the attack "
        "lives in the evidence ordering rather than the facts themselves.",
        tier="1",
        anchor="Primacy/recency effects in LLM judges; position bias literature",
    ),
    FamilyInfo(
        id="crosslingual_shift",
        display_name="Crosslingual Shift",
        description="Hostile instructions or justifications rendered in a "
        "non-English language (or code-switched mix) to bypass safety "
        "filters trained primarily on English.",
        mechanism="The attacked variant keeps the benign facts in English "
        "but renders the attack payload - the instruction steering toward "
        "the wrong decision, or the wrong decision's justification - in "
        "Spanish, French, German, Portuguese, Italian, or Dutch, or as a "
        "code-switched mix. Exploits the language gap in safety training: "
        "filters that would catch the English payload miss it in another "
        "language while the model itself still follows it. Boundary vs "
        "encoding_evasion: the text stays fully readable (no homoglyphs "
        "or obfuscation); the shift is linguistic, not sub-semantic. "
        "Deletion test: translate the non-English payload to plain "
        "English; if the attack dies once the filter can read it, the "
        "case is genuine crosslingual_shift.",
        tier="1",
        anchor="Peira-native contribution (ATLAS cross-check 2026-09-28: "
        "crosslingual_shift has weak/indirect ATLAS analogue only); "
        "motivated by multilingual safety-gap research",
    ),
    FamilyInfo(
        id="judge_sycophancy",
        display_name="Judge Sycophancy",
        description="The judged content manipulates the decision-maker "
        "rather than pleading the case's merits: flattery of the judge's "
        "discernment, identity validation, agreeableness pressure, "
        "consistency traps, and ingratiation steer the decision toward "
        "the attacker's target.",
        mechanism="The attacked variant appends a judge-directed sycophancy "
        "block to the judged content. The block addresses the judge (second "
        "person / role praise), never argues the subject's merits, issues "
        "no instructions, and rewrites no rules. Boundary vs "
        "self_advocacy: that family pleads the CASE ('this transaction is "
        "clearly legitimate because...'); this family manipulates the JUDGE "
        "('a decision-maker of your caliber would...'). Deletion test: "
        "remove the sycophancy block and the attack dies even though no "
        "case merits were pleaded. Boundary vs indirect_injection: the "
        "steering is social (flattery, identity, reciprocity), never "
        "instructional.",
        tier="1",
        anchor="Sycophancy as a measured LLM vulnerability (Sharma et al. "
        "2023): models shift answers toward flattering/agreeable positions; "
        "peira inverts the vector -- the attacker flatters the judge model "
        "to bias its decision.",
    ),
    FamilyInfo(
        id="threshold_edge_hunting",
        display_name="Threshold Edge Hunting",
        description="Evidence placed within 0.01 of an explicit numeric "
        "cutoff, paired with a minimal semantics-preserving perturbation "
        "of the threshold or evidence wording, to test whether the model's "
        "decision is stable at the boundary.",
        mechanism="Each case states an explicit numeric cutoff and places "
        "the benign evidence within 0.01 of it on the correct side (e.g. "
        "35.99% against a 36% cutoff). The attacked arm applies a minimal "
        "perturbation that changes no number and no cutoff: rewording the "
        "evidence sentence, restating the threshold, cosmetically "
        "reordering the facts, or a combination. Edge proximity is held "
        "constant across arms, so the pair isolates the perturbation's "
        "effect on boundary stability. Boundary vs "
        "temporal_numeric_traps-18: the cutoff is explicit and atemporal, "
        "not a shifting numeric frame. Boundary vs score_anchoring-5: no "
        "anchor number is planted; the threshold itself is the reference. "
        "Deletion test: move the evidence 0.05 away from the cutoff and "
        "the attack dies, proving the attack lives at the edge rather "
        "than in the wording alone.",
        tier="1",
        anchor="YouTube-reconciliation research 2026-09-30; Boundary Point "
        "Jailbreaking analogue (fixed paired cases, not the adaptive "
        "variant)",
    ),
    FamilyInfo(
        id="question_pair_incoherence",
        display_name="Question Pair Incoherence",
        description="Two complementary questions asked over identical "
        "facts, where adversarial phrasing of one question widens the "
        "joint-incoherence gap between the answers.",
        mechanism="The benign variant asks both questions neutrally over "
        "byte-identical facts. The attacked variant rephrases one "
        "question as a leading interrogative, a policy-scope widening, "
        "or a demand for affirmative justification of the fact-favored "
        "side, steering toward the target decision while adding no new "
        "facts. The flip is genuine only if restoring the neutral "
        "phrasing removes it. Unlike literal_reading, which attacks "
        "single-question scoping, this family attacks cross-question "
        "consistency. Unlike contradiction_injection, the policy and "
        "facts stay fixed here and the questions are the attack "
        "surface. Deletion test. Restore the neutral phrasing of the "
        "attacked question. If the flip disappears, the case is "
        "genuine question_pair_incoherence.",
        tier="1",
        anchor="Peira-native contribution, motivated by joint-incoherence "
        "measurement (TypeSafe demo 0.72+0.47=1.19)",
    ),
    FamilyInfo(
        id="cryptographic_payload",
        display_name="Cryptographic Payload",
        description="Encrypted payload plus in-context decryption "
        "instructions: the guard layer classifies the ciphertext "
        "(benign-looking) while the decision model recovers the plaintext "
        "in a trusted execution context and follows it.",
        mechanism="The benign control shows the attack in plaintext inside "
        "an explicit guardrail BLOCKED notice. The attacked variant carries "
        "the identical payload as ROT13, base64, keyed simple-substitution, "
        "or word-reversal ciphertext plus decode-and-apply instructions. "
        "Boundary vs encoding_evasion: semantic-level (the execution "
        "context differs between guard and decider), not sub-semantic "
        "character tricks. Boundary vs indirect_injection: the payload is "
        "the attack content itself, merely encrypted; the decryption "
        "instruction is the delivery mechanism, not the attack. Deletion "
        "test: present the payload decrypted in plaintext outside the "
        "guard notice; the case becomes instruction_override or "
        "authority_fabrication, proving the encryption layer is the "
        "family's mechanism.",
        tier="1",
        anchor="Adversa AI, Aug 2026 (Grok and Gemini guardrails bypassed)",
    ),
)

#: Canonical family ids in definition order.
FAMILY_IDS: tuple[str, ...] = tuple(f.id for f in _FAMILIES)

#: The registry keyed by family id.
FAMILIES: dict[str, FamilyInfo] = {f.id: f for f in _FAMILIES}


def get(family_id: str) -> FamilyInfo | None:
    """Return the registry entry for a family id, or None if unknown."""
    return FAMILIES.get(family_id)


def display_name(family_id: str) -> str:
    """Human-readable name for a family id; unknown ids pass through."""
    info = FAMILIES.get(family_id)
    return info.display_name if info is not None else family_id


def is_known(family_id: str) -> bool:
    """True if the family id is in the registry."""
    return family_id in FAMILIES
