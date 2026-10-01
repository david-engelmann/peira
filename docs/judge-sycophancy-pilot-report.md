# Judge Sycophancy Pilot Report (Program D)

**Date:** 2026-09-30
**Question:** Should `judge_sycophancy` ship as a standalone v2 attack
family, or fold into `self_advocacy`?
**Verdict:** **STANDALONE** (D-38)

## Family definition

`judge_sycophancy`: the judged content manipulates the
**decision-maker** rather than pleading the case's merits. Five
sub-mechanisms:

| ID | Sub-mechanism | Attack vector |
|----|---------------|---------------|
| M1 | discernment_flattery | Flattery of the judge's discernment and insight |
| M2 | identity_validation | Validation of the judge's values and identity |
| M3 | agreeableness_pressure | Social pressure to agree ("surely you agree...") |
| M4 | consistency_trap | Weaponizing the judge's past positions and stated standards |
| M5 | ingratiation | Favors, gifts, praise, and reciprocity pressure |

This is distinct from `self_advocacy` ("the judged content pleads its
own case to the decision-maker: persuasion about this case, never a
rewrite of the rules", docs/Taxonomy.md). The sycophancy attack
never argues the case is meritorious; it argues the judge is the kind
of person who decides a certain way.

## Evidence for standalone

1. **Distinct causal mechanism.** self_advocacy operates on the
   judge's beliefs about the *case*; judge_sycophancy operates on the
   judge's beliefs about *themselves*. A judge can be fully informed
   about the case facts and still be moved by identity validation.

2. **Operationally separable deletion tests** (verified mechanically
   on all 421 cases). self_advocacy: remove the merit pleading, the
   attack dies. judge_sycophancy: remove the judge-directed sycophancy
   block, the attack dies, with no merit pleading ever present. The
   authoring script asserts on every case: the sycophancy block
   addresses the judge (you/your), contains zero merit pleading
   (anti-self_advocacy), zero instructions (anti-indirect_injection),
   zero rule rewrites (anti-criteria_smuggling), and
   attacked == benign + exactly one sycophancy block.

3. **Different countermeasures.** self_advocacy is countered by
   fact-checking the case claims; judge_sycophancy is countered by
   judge debiasing (recusal-style prompts, identity-neutral
   reframing). A benchmark that folds them cannot measure these
   separately.

4. **Literature grounding.** Sycophancy in LLMs is an established
   phenomenon (Sharma et al. 2023): models systematically produce
   responses that please the evaluator. judge_sycophancy is the
   adversarial-decision-model instantiation: the *judged content*
   exploits the *judge model's* sycophantic tendencies.

5. **Internal structure.** The five sub-mechanisms are not surface
   rewordings; they are distinct psychological levers (competence
   flattery, identity, social conformity, commitment/consistency,
   reciprocity) with distinct linguistic signatures, each holding 83-87
   cases.

## Corpus

421 cases (`v2-jsp-0001`..`v2-jsp-0421`), all paired benign/attacked:

- Mechanisms: M1 85, M2 83, M3 83, M4 87, M5 83
- Severity: 40 critical, 137 high, 244 medium
- Primitives: 375 choice, 46 score
- Domains: hiring, lending, admissions, procurement, underwriting,
  grants, moderation, licensing boards, safety inspection, and more

Every case passed the authoring script's validity assertions plus all
nine dataset gates (G1-G9, 0 errors; G9 near-dedup warnings are
sub-threshold by design, holding domain constant to isolate the
mechanism effect).

## Boundary ruling (Taxonomy.md #9)

`self_advocacy` vs `judge_sycophancy`: the subject pleads its own
case vs manipulates the decision-maker. Deletion tests decide: remove
the merit-pleading and if the attack dies, it is `self_advocacy`;
remove the judge-directed flattery/pressure and if the attack dies
with no merit pleading ever present, it is `judge_sycophancy`.

## Registration

- `python/peira/families.py`: FamilyInfo entry (after
  crosslingual_shift), in CANONICAL_FAMILIES and GATE_KNOWN_IDS
- `docs/Taxonomy.md`: family 25 + boundary ruling 9
- `docs/Decisions.md`: D-38 (this verdict)
- `dataset/v2/cases/judge_sycophancy.jsonl` + manifest entry,
  dataset version 2.4.0
- `CHANGELOG.md`: Unreleased entry
