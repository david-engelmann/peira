# Two-axis review: `openrouter-support` branch (cheap-model pilot set)

Branch: `openrouter-support` @ `29ad9731e839ff7a3a80003f4b52fbe068a0a2f1`
Base: `origin/main` @ `a77f5d2c5ba6551ff4021fbbd37da47590ad3519`
Reviewed: 2026-10-03 (final two-axis review before merge)
Commits: `710076d5` (pilot set, pricing, tests, docs) + `29ad9731` (red-team repairs)

Spec (David, 2026-10-03): "Make OpenRouter a first-class run path with cheap models
for the pilot run. One cheap model per major lab, verified against OpenRouter's live
API, with pricing and docs."

Files: `python/peira/api_pins.py` (+101/-13), `python/peira/data/pricing.json` (+66/-2),
`tests/test_api_pins.py` (+52), `docs/Adapters.md` (+31).

## Method (independent verification)

- Read every changed line; confirmed the fixed point resolves and the diff is non-empty.
- Re-ran the old `openrouter` branch of `_passes_vendor_semantics` (extracted from
  `origin/main`) against all 10 new IDs: the old code REJECTs 7 of 10
  (`gpt-oss-20b`, `llama-3.1-8b-instruct`, `gemma-3-4b-it`, `glm-4.7-flash`,
  `kimi-k2.5`, `grok-4.3`, `claude-haiku-4.5`). The semantics loosening in `29ad9731`
  is therefore *required* for `validate_registry()` to accept the new set, not scope creep.
- Ran the suite: `PYTHONPATH=python python3 -m pytest tests/test_api_pins.py -q` ->
  37 passed, 78 subtests passed.
- Recomputed the cost table independently (11,002 calls x 1,500 in / 400 out tokens):
  per-model estimates match the code comments and docs to the cent; total $95.67 ~ $96.
- Codepoint scan of the 31 added docs lines: zero em/en dashes. Copy bar clean.
- Verified the cross-file invariants by inspection: all 10 pricing keys match the
  `OPENROUTER_CHEAP_MODELS` values; `validate_registry()` reaches the new dict via the
  existing `openrouter-structured` -> `openrouter` adapter mapping; `__all__` exports both
  new names.

## Spec (fidelity)

- "One cheap model per major lab": PASS. 10 entries, 10 distinct vendor prefixes
  (mistralai, deepseek, openai, qwen, meta-llama, google, z-ai, moonshotai, x-ai,
  anthropic); `test_ten_models_one_per_lab` pins this.
- "Verified against OpenRouter's live API": claimed consistently in the code comments,
  pricing `_note`s, and docs (2026-10-03, `/api/v1/models`, structured-output support
  advertised). Caveat: not independently re-verifiable from this review sandbox
  (openrouter.ai egress is not on the approved domain list for subagents); the claim is
  recorded, not confirmed. The code is honest about the residual gap: "Each model id
  still needs a live smoke test before any measured run."
- "With pricing": PASS. All 10 IDs in `pricing.json` under identical keys, live rates,
  date + pricing_version + source bumped together per the table's documented rule.
- "And docs": PASS. `docs/Adapters.md` gets a "Cheap-model pilot set" section with
  usage snippet and the full rate table.
- "First-class run path": the gateway adapter (`OpenRouterAdapter`) already exists on
  main (PR #288); this diff correctly plugs the pilot set into the existing
  `api_pins` registry + import-time `validate_registry()` instead of building a new path.
- Scope creep: none. Every hunk serves the spec.

**Spec verdict: PASS** (1 finding: none. Caveat noted above about live-API verification.)

## Standards

**F1 (hard): stale invariant comment contradicts the new semantics.**
`python/peira/api_pins.py` ~lines 251-256 (the `_VENDOR_ID_PATTERNS` block comment) still
states: "The inner model part must itself look like a real vendor ID (checked by
`_passes_vendor_semantics`), so a fabricated inner ID cannot ride in behind the slash."
Commit `29ad9731` changed `_passes_vendor_semantics` to no longer do this (inner part
now only needs gateway ID shape `^[A-Za-z0-9][A-Za-z0-9._-]*$`), and rewrote the comment
*inside* the function — but left this older comment asserting the abandoned invariant.
A reader of the patterns block will believe fabricated inner IDs are rejected; they are
not. Fix: rewrite those lines to match the new rationale ("anti-fabrication is the
live-API verification recorded at each registry entry").

**F2 (hard): tautological test with a false claim.**
`tests/test_api_pins.py::test_get_openrouter_cheap_model_all_bindings` loops over
`OPENROUTER_CHEAP_MODELS` and reads expected values from the same dict it validates, so
a key<->ID swap inside the dict can never fail it — yet its comment claims "A swap
between two keys must fail this test." That claim is false. Per the repo's
no-tautological-tests rule, either assert against an independent literal mapping or drop
the test and fix the comment.

**F3 (judgement): two near-tautological tests.**
`test_all_ids_match_openrouter_format` and `test_all_ids_pass_gateway_semantics` use the
module's own regex/semantics to validate the module's own dict — and `validate_registry()`
is called at import time, so the module cannot import without passing. They cannot fail
independently of import. Belt-and-braces, but low value; consider dropping or documenting
the redundancy.

**F4 (minor): docs table decimal inconsistency.** `docs/Adapters.md` rows show `$0.05/$0.1`
(gemma) and `$1.0/$5.0` (claude) vs two-decimal elsewhere. Make them `$0.10`, `$1.00/$5.00`.

**F5 (minor): pricing `_comment` changelog not appended.** The `_comment` carries a dated
changelog ending 2026-10-02; the new rates weren't appended there (each entry's `_note`
does carry provenance, and `source` was bumped, so nothing is lost — convention only).

**F6 (minor): `pricing.json` `source` rewrite drops history.** The old `source` string's
detailed provenance (GPT-5.6 tiers verified 2026-09-23, etc.) was replaced with a one-line
summary; the history survives in `_comment`. Acceptable, but thinner than before.

Smell sweep: no duplicated code, no speculative generality (`get_openrouter_cheap_model`
adds real fail-closed behavior + valid-key listing, not a bare delegator), no message
chains, no shotgun surgery. `_looks_like_any_vendor_id` still has module-internal callers
in `validate_registry`; not dead code.

**Standards verdict: FAIL** — fixable. F1 (stale invariant comment) and F2 (tautological
test with false claim) need repair before merge; F3-F6 are judgement/minor.

## Summary

- Spec axis: PASS, 0 findings (1 evidence caveat: live-API verification claim recorded,
  not independently re-verified from this sandbox).
- Standards axis: FAIL, 6 findings — worst is F1, the stale "inner part must look like a
  real vendor ID" comment that now contradicts the function it documents.
- All 37 tests + 78 subtests green; cost arithmetic independently confirmed ($95.67
  total, matching the "~$96" claim).
