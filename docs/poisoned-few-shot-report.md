# Poisoned Few-Shot Report (EB-47)

**Date:** 2026-10-01
**Question:** Should `poisoned_few_shot` ship as a standalone v2 attack
family, or fold into `precedent_stacking` or `indirect_injection`?
**Verdict:** **STANDALONE** (D-39)

## Family definition

`poisoned_few_shot`: both arms show three worked examples of the
decision **task** plus the same target case; only the demonstrations
differ. The benign arm's demonstrations are honest; the attacked
arm's are poisoned. The family measures whether decision models
absorb poisoned in-context demonstrations. Five sub-mechanisms:

| ID | Sub-mechanism | Attack vector |
|----|---------------|---------------|
| M1 | label_flip | Every demonstration label flipped (reject-steering) |
| M2 | trigger_backdoor | A spurious trigger taught as approve on every demo |
| M3 | smuggled_policy | A fabricated Fast-Track Review Policy taught as decisive |
| M4 | boundary_shift | One honest demo swapped for a biased borderline approve |
| M5 | corrupted_reasoning | A fallacious reject-template taught as the review rule |

Peira's cases are zero-shot today; this family is the DecodingTrust
analog for in-context demonstration poisoning.

## Evidence for standalone

1. **Distinct causal mechanism.** precedent_stacking fabricates an
   approval history of the *same subject*; poisoned_few_shot
   demonstrates the decision *task* with *different subjects*  -  the
   target subject never appears in any demonstration (asserted at
   authoring time). indirect_injection smuggles *instructions* in
   third-party content; here the steering comes only from
   demonstrated input-output mappings  -  no imperatives appear in
   instructions, demonstrations, or targets (deny-listed and
   asserted). The attack vector is the demonstration mapping, which
   neither family covers.

2. **Operationally separable deletion tests** (verified mechanically
   on all 420 cases). Restore the honest demonstrations and the
   attack dies  -  the attack lives in the demonstrations, not the
   target case. The authoring script asserts on every case: the
   target subject appears in zero demonstrations
   (anti-precedent_stacking), and no imperative text appears anywhere
   in either arm (anti-indirect_injection). Demo stems are identical
   between arms except boundary_shift (which swaps exactly one demo).

3. **Different countermeasures.** precedent_stacking is countered by
   provenance verification of cited history; indirect_injection by
   instruction/data separation. Poisoned demonstrations are countered
   by demonstration sanitization (label auditing, trigger scanning,
   policy provenance checks on the prompt's own examples)  -  a
   distinct defense surface.

4. **Internal structure.** The five sub-mechanisms are distinct
   poisoning strategies (label corruption, trigger planting, policy
   fabrication, boundary manipulation, reasoning corruption) with
   distinct demonstration signatures, each holding exactly 84 cases
   (7-demo pools x 12 targets per mechanism).

## Corpus

420 cases (`v2-pfs-m1-0000`..`v2-pfs-m5-0419`), all paired
benign/attacked, all choice primitive:

- Mechanisms: M1 84, M2 84, M3 84, M4 84, M5 84
- Severity: 49 critical, 210 high, 161 medium
- Primitives: 420 choice
- Case pairing: 12 targets per mechanism drawn from 7-demo pools

Every case passed the authoring script's validity assertions plus all
nine dataset gates (G1-G9, 0 errors; G9 near-dedup warnings are
sub-threshold by design, holding domain constant to isolate the
mechanism effect).

## Boundary ruling (Taxonomy.md #11)

`poisoned_few_shot` vs `precedent_stacking`: both show many
demonstrations, but `precedent_stacking` fabricates an approval
history of the SAME subject while `poisoned_few_shot` demonstrates
the decision TASK with DIFFERENT subjects. The test: if the target
subject appears among the demonstrations, it is `precedent_stacking`;
if every demonstration concerns a different subject and the steering
comes only from demonstrated input-output mappings, it is
`poisoned_few_shot`. `poisoned_few_shot` vs `indirect_injection`: the
demonstrations contain no imperatives; if an instruction or command
appears in the demo text, it is `indirect_injection`.

## Registration

- `python/peira/families.py`: FamilyInfo entry (after
  dos_resource_exhaustion), in CANONICAL_FAMILIES and GATE_KNOWN_IDS
- `docs/Taxonomy.md`: family 30 + boundary ruling 12
- `docs/Decisions.md`: D-39 (this verdict)
- `docs/Methodology.md`: family section (paired-control
  construction, deletion-test diagnostics, design MDEs)
- `dataset/v2/cases/poisoned_few_shot.jsonl` + manifest entry,
  dataset version 2.5.0
- `CHANGELOG.md`: Unreleased entry
