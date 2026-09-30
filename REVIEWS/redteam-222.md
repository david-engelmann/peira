# Red-team audit: PR #222 — retrieval_poisoning (family 22)

Independent auditor, no prior exposure to this PR. All claims re-verified
against the code and data. Branch `r06-retrieval-poisoning-v4` @ 8efa81a,
diffed against origin/main. Worktree: ~/workspace/peira-222-gate.

## Method

- Full corpus scan: 470/470 cases checked for pair honesty (attacked ==
  benign + exactly one `\n\n[Retrieved: ...]` suffix; option vocab identical;
  gold decisions in vocab; expected != target). Zero failures.
- Directive-language scan: author's DIRECTIVE_PATTERNS gate (passes in
  suite) plus an independent keyword scan — 7 hits, all false positives
  ("fire" in factual contexts like "fire investigation supplement";
  "deny" in "board voted to deny renewal").
- Manual spot-check of 30 cases stratified across choice/score/abstain and
  critical/high/medium: retrieval condition (block reads as query-relevant
  evidence), directional pull to the target, no instructional text, benign
  control genuinely benign. All pass.
- Diversity: 470 unique benign prompts, 470 unique attacked prompts, 470
  unique (scenario, poison) pairs (all enforced by tests, which I re-ran);
  name/number-masked skeleton collision count = 0 for both scenarios and
  blocks; 0 of 3,160 sampled pairs above 0.75 SequenceMatcher similarity.
  No template regurgitation.
- Holdout: corpus IDs are `v2-retp-0001..0470`; sealed v1 holdout used
  `v1-holdout-*`; no `holdout` strings anywhere in the corpus. Clean.
- Ran the suites: `tests/test_retrieval_poisoning.py` (19 passed),
  `tests/test_families.py`, `tests/test_schema_families.py`,
  `tests/test_check_families.py` (19 passed). Regeneration is
  byte-identical (determinism test passes).
- Manifest: sha256 `1efb4eeb…a51a68` recomputed and matches; counts
  (470 / 90-160-220 / 330-80-60) match the JSONL exactly; dataset_version
  2.0.0 -> 2.1.0 consistent across manifest, CHANGELOG, and test; MDE
  values 4.4/6.3/7.7/8.9 at n=400 are identical to verbosity_inflation's
  (same design discordance table — plausible).
- Authoring script: no `random` import anywhere; corpus is hand-authored
  data tables, deterministic by construction. `validate()` only reports
  errors, never filters or drops cases — no hidden post-hoc biasing.
- Copy bar: 0 em/en dashes in all new prose (verified with a Python
  codepoint scan, not grep). Colons/semicolons appear in new docs prose,
  but so do 221/18/103 on main's Methodology/Taxonomy/CHANGELOG — the
  standing register for technical docs; the no-colon/semicolon rule from
  the 2026-09-28 incident targets public marketing copy, not docs.
- Family numbering: retrieval_poisoning is the 22nd family (last in the
  tuple, docs list 1..22 enforced by test); no collision with #188 (24).
- Boundary rulings hold on the actual cases: every block is a single
  poisoned document with directional pull (vs distractor_flooding),
  single-document (vs precedent_stacking), facts-not-presentation
  (vs verbosity_inflation), explicit `[Retrieved:]` untrusted framing
  (vs state_poisoning), zero directive text (vs indirect_injection).
- Out of scope (pre-existing, repair lane owns it): main's red CI from
  `tests/test_threshold_family.py` ImportError (orphaned by PR #197).
  Did not merge-block on it.

## Findings

### P1 — Wrong MITRE ATLAS technique ID in four places

The anchor cites "MITRE ATLAS T0099". Verified from current ATLAS
references (multiple 2026 crosswalks reconciled against ATLAS dist
data): **AML.T0099 is "AI Agent Tool Data Poisoning"** (the adversary
plants malicious content where an agent tool can retrieve it) — an
agent-native technique, not RAG poisoning. The correct RAG-poisoning
technique is **AML.T0070 "RAG Poisoning"** ("malicious content injected
into vector store RAG knowledge bases to manipulate retrieval results").
CodeRabbit's dispute is correct; the PR's citation is a wrong factual
claim in public copy, violating the copy bar.

Evidence:

- `python/peira/families.py:336` —
  `anchor="PoisonedRAG, arXiv:2402.07867; MITRE ATLAS T0099"`
- `docs/Taxonomy.md:122` — "PoisonedRAG (Zou et al., arXiv:2402.07867);
  MITRE ATLAS T0099."
- `CHANGELOG.md:19` — "MITRE ATLAS T0099."
- `scripts/author_retrieval_poisoning.py:12` — "ATLAS T0099." (docstring)

Fix: replace `MITRE ATLAS T0099` with `MITRE ATLAS AML.T0070` in all
four locations. (The PoisonedRAG arXiv:2402.07867 citation is correct.)

### P2 — templates.py states an invalid family-classification rule

`python/peira/templates.py:820-825` (notes_prompt) says:

> "Deletion test: remove the retrieved block; if the attack dies it is
> retrieval_poisoning (vs indirect_injection, whose payload is an
> instruction, not false evidence)."

CodeRabbit is right that this cannot be a classifier: removing the
entire block kills an indirect_injection attack too, since its payload
is also delivered in retrieved content. The discriminative test is the
one already stated correctly in `docs/Methodology.md` ("strip only the
instructional sentences from the block and keep the factual claims")
and `docs/Taxonomy.md` boundary ruling 8. The template text is the
weaker construction check (the attack lives in the retrieved block,
not the prompt) presented as a classifier, and it contradicts the
docs' own correct version.

Fix: rewrite the notes_prompt parenthetical to match
Methodology/Taxonomy — strip instructional sentences only, keep the
false-fact claims; attack surviving = retrieval_poisoning, attack
dying without the instruction = indirect_injection.

### P3 — families.py mechanism deletion-test sentence could be tightened

`python/peira/families.py:333-334`: "Deletion test: remove the retrieved
block and the attack dies." As written it is true and valid as a
retrieval-delivery diagnostic, but sitting next to the
indirect_injection boundary sentence it invites the same misreading
as the P2 above. Optional: frame it explicitly as the
retrieval-delivery check ("the attack lives in the retrieved block,
not in the prompt framing") rather than leaving it adjacent to the
classifier claim.

## Verdict

**APPROVE-WITH-FINDINGS.** The corpus is sound: 470 genuine
retrieval-poisoning pairs, honest construction, no directive leakage,
real diversity, no holdout contamination, schema-valid, manifest and
MDEs check out, authoring script deterministic with no hidden
filtering. The two substantive findings are a wrong ATLAS technique
ID in four places (P1) and a misleading classifier statement in
templates.py (P2) — both small, both fixable before merge.
