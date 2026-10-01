# V1 exhaustive audit (perfection-gate item 7)

Row-by-row semantic screening of all 2,000 v1 public cases
(`dataset/v1/cases/*.jsonl`, 10 families x 200). The nine dataset gates
cover structure. The audit harness (`scripts/v1_exhaustive_audit.py`)
screens meaning. It checks attack fidelity via data-driven idiom
lexicons, structural family checks, family assignment, label sanity,
deep PII and secrets screening, and notes hygiene.

## Method

The harness screens every case programmatically. Every flagged finding
got a human read of the full case (both arms, notes, decisions).
Unflagged cases were screened, not human-read. Semantic correctness
(true label derivability, true attack fidelity) remains the stratified
manual read's job, as the harness docstring states.

## Findings and dispositions

The v4 harness flagged 86 findings. All were triaged 2026-10-01:

- **confidence_spoofing fidelity, 67.** Lexicon gap, not a dataset
  defect. Every flagged delta was read. All are genuine
  confidence-spoofing attacks (false authority endorsements such as
  "would not hesitate", "no doubt", "open-and-shut", "did not waver",
  "rubber-stamped", "green light", "threw their weight behind", "ended
  the debate"). The lift-mined lexicon missed these idioms.
- **criteria_smuggling fidelity, 3.** Lexicon gap. v1-csm-134 ("that IS
  the substance of documentation"), v1-csm-143 ("Quality is ultimately
  parent satisfaction"), v1-csm-169 ("normalized ... against the 10-year
  baseline") are textbook criteria-redefinition attacks.
- **negation_games fidelity, 14.** Design-consistent, not defects. 10 are
  Shape A, the meaning-preserving negation stack. Their targets are the
  documented mishandling outcomes (v1-ngm-013, 040, 064, 066, 074, 135,
  165, 170, 245, 247). 4 are Shape B, the meaning-inverting rewrite.
  Their targets are the correct applications of the hostile wording
  (v1-ngm-042, 121, 123, 178). The v4 "negation profile must change"
  heuristic was too narrow. Shape A preserves meaning by design, as
  docs/Taxonomy.md describes ("double negatives and Abstain-specific
  inversions"), and Shape B inversions need no negation vocabulary.
- **PII (email), 2.** Genuine hygiene defect, fixed directly: v1-csm-134
  used `audit@revenue.gov` (real-TLD, government-looking address) in
  both arms. Changed to `audit@revenue.example` (one-line diff). The
  dataset moved to version 1.4.1 with the new sha256 recorded in
  `dataset/v1/cases/manifest.json`, `dataset/v1/cases/croissant.json`,
  and a `fix` entry in `dataset/v1/cases/CHANGELOG.json`, plus a root
  `CHANGELOG.md` entry (the manifest-verify gate caught the stale
  hash).
  The configured screening checks found no other non-fictional emails,
  phones, SSNs, keys, or card numbers in the corpus. The remaining G6
  pii-scan warnings are fictional `.example` addresses by design.

## Harness v5

- confidence_spoofing and criteria_smuggling lexicons extended with the
  triaged idioms (documented gap-fills, including multi-word phrases
  such as "done deal", "no doubt", "green light").
- negation_games is shape-aware. Every case must declare Shape A or
  Shape B in notes (all 200 do). Shape A requires negation-stack
  vocabulary in the attacked arm's body text, with option-label tokens
  excluded so a "deny"/"no"-style option cannot satisfy the check
  vacuously. Shape B requires the arms to differ.
- The email check parses the domain after the final `@` and matches
  reserved domains exactly, so lookalike domains such as
  `revenueexample.com` are not wrongly exempted.
- The option_order check compares punctuation-normalized prompts, so a
  punctuation-only delta between the arms is flagged as not a reorder.
- Re-run: **0 findings across 2,000 cases** (exit 0).
- `tests/test_v1_exhaustive_audit.py`: 10 regression tests on synthetic
  fixtures (idiom flag/clear, Shape A stack flag/clear, missing shape
  annotation, id-family-mismatch, punctuation-only reorder delta,
  genuine reorder clear, non-reserved email domain flag, reserved
  domain exemptions). Each fails for a real reason.

## Reviews

Three reviews per the checkpoint rule, 2026-10-01. Code was reviewed at
`b0535a7c`. Later commits add only this audit record and remove lane
scratch, with no code changes. The two axes were run sequentially by the
same reviewer rather than in parallel, following the same briefs with
the reports kept separate:

1. **Red-team re-audit.** Re-verified every claim independently.
   Corpus count is 2,000 on disk. Harness stderr confirms 2,000
   scanned. The dataset diff is exactly one line (email). All 200 ngm
   cases carry Shape A/B annotations. Negative controls prove the
   checks are not vacuous. A bogus csp delta flags. A stackless Shape A
   flags. Genuine cases clear. Found and fixed: the dead `_neg_profile`
   left by the v5 rewrite (removed), the option-label vacuity in the
   Shape A check (fixed, negative control now passes), and em dashes in
   the triage record (replaced).
2. **Standards axis.** PASS with the red-team fixes applied. The harness
   is stdlib-only, per the repo AGENTS.md guidance to keep core files
   small and dependency-free. Names are clear, with no duplicated logic
   and no speculative generality. Sign-offs are on all commits and
   worktree/branch discipline is clean. On the copy bar, the en dash
   inside the score-scale regex is functional (it matches case text),
   not copy. New tests are non-tautological (each asserts flag/clear
   behavior on synthetic fixtures).
3. **Spec axis.** PASS with one noted interpretation. GOAL.md item 7
   asks for a row-by-row audit of all 2,000 public cases with defects
   fixed directly (no "known limitations"). Delivered: programmatic
   row-by-row screening of all 2,000 plus human reads of all 86
   findings, with the one genuine defect fixed in this change. No scope
   creep. The change is the harness, the test, the one-line dataset fix,
   and this record. No silent deletions. Interpretation note: unflagged
   cases were screened, not human-read. Full semantic verification
   remains the stratified manual read's job, disclosed here and in the
   harness docstring rather than claimed.

## Verification

- `python3 scripts/v1_exhaustive_audit.py`: 0 findings across 2,000
  cases, exit 0.
- `python -m pytest tests/test_v1_exhaustive_audit.py`: 10 passed.
- `peira dataset gates --dir dataset/v1/cases`: 9/9 passed, 0 errors
  (468 warnings. G9 near-dedup is informational. G6 warnings are all
  fictional `.example` addresses).
