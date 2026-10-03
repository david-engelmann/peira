# V2 Readiness Punchlist

**Date:** 2026-10-02
**David's decisions:** v2 full data, every finished adapter, full holdout, money not a constraint.

## What's ready

- **V2 dataset:** 11 families, 4,701 cases, sealed at v2.6.0
- **Conversational suite:** 2 families, 840 cases
- **Combo suite:** 2 pairs, 800 cases
- **Total:** 6,341 cases, ~12,682 calls per adapter
- **11 LLM adapters:** code-complete, pinned (api_pins.py)
- **9 HF guardrails:** code-complete, run local
- **5 Jev-family:** code-complete, run local
- **Pricing:** all 11 paid adapters now cost-accounted (v2026-10-02.2)
- **V2 cut criteria:** defined in docs/V2-Cut-Criteria.md

## Blocked on David

| Item | What's needed |
|------|---------------|
| Meta Llama adapter | API key (David said he can provide) |
| DeepSeek adapter | Account credits (David said he can provide) |
| Model Armor | Credentials or drop from run |
| Azure Prompt Shields | Credentials or drop from run |
| Cloudflare Workers AI | Token with Workers AI scope or drop from run |

## Work needed before A12

1. **V2 cut:** Run 9 gates on v2, seal manifest, create immutable `dataset-v2-*` tag (R-10)
2. **Exhaustive v2 audit:** 4,400 drafts row-by-row (dataset-perfection checklist)
3. **Adapter smoke tests:** 10 remaining paid adapters (Anthropic pin updated, smoke blocked on key plumbing)
4. **Cost ledger:** A9 ledger entries with the ~$906 estimate
5. **A12 run:** Execute the official v2 run across all adapters
6. **A13 holdout:** Full blind holdout re-run (~$76)

## Cost estimate

| Component | Cost |
|-----------|------|
| Public v2 run (11 paid adapters) | ~$831 |
| Holdout run | ~$76 |
| **Total** | **~$906** |
| 14 free adapters (HF + Jev + Lakera) | $0 |

## What this lane did

- Filled 4 missing pricing entries (grok-4, deepseek-flash, glm-4-plus, Meta Llama)
- Defined formal v2 cut criteria
- Calculated full run cost estimate
