# Economics Policy

Peira's economics answer a buyer's question, not a bill-payer's. The question is "what will this guardrail cost me to run," and every dollar figure on the leaderboard is produced by the rules below. Economics are a measurement instrument. Like every instrument in peira, the policy is conservative by default and honest about its blind spots.

## 1. The unpriced rule

An adapter or model without a published rate stays unpriced. It never inherits a neighbor's rate, never inherits another tier from the same vendor, and is never estimated from any analog.

The mechanical meaning of "unpriced" is below.

- Its calls contribute $0 to `total_cost_usd`.
- They are counted in `n_unpriced`, not `n_priced`.
- Any leaderboard cell that cannot price all of its calls displays "unpriced", never "free". Free is a priced $0.0 and is distinct from unpriced. See `docs/Methodology.md` for the priced/unpriced call split.
- Cost totals are a lower bound whenever `n_unpriced > 0` (unpriced calls contribute $0 to the total but count in the denominator). When no call is priced at all, the cost is unknown, not zero, and totals are withheld (`None`, `sufficient: False`).

The budget cap binds priced spend only. Unpriced calls contribute $0 and dilute the running mean, so an all-unpriced run never trips the gate.

## 2. The rate table

`python/peira/data/pricing.json` is a pinned list-price table in USD per 1M tokens at the provider's standard tier. Every entry carries three things.

- `usd_per_1m_in` and `usd_per_1m_out`, or `usd_per_call` for per-call billing (Azure Prompt Shields at $0.00038 per call, Lakera at ~$0.002 per call).
- `confidence`, one of two levels. "official" means the rate was verified against the vendor's live pricing page, or is a first-party $0.0 assertion for a self-hosted checkpoint. "secondary" means carried over unverified from a pre-launch table, or reported by a gateway or third-party integration guide.
- `_note` with provenance, source URL, verification date, and any caveats.

The table header carries `date`, `pricing_version` (date plus intra-day revision, e.g. "2026-09-25.1"), and `basis`. All three plus the source are sealed into every run artifact as `pricing_source`, `pricing_date`, and `pricing_version` (`python/peira/artifacts.py`). A cost figure is always traceable to the exact table version that produced it.

Self-hosted checkpoints with first-party $0.0 assertions (Kev and Laya) price at 0.0 with confidence "official". This is a first-party assertion that peira pays no API cost, not a claim that local inference is free. Local compute is explicitly unaccounted. Self-hosted checkpoints without a table entry (SemIf and OpenJev today) are unpriced until a maintainer adds the first-party $0.0 assertion. They are never silently treated as free.

Two entries carry `cost_accounted: false` (GCP Model Armor, Cloudflare Llama Guard). Their APIs return no token usage, so peira cannot meter per-token spend. They price at 0.0 but are unaccounted, not free, and are displayed accordingly.

## 3. Scope bound

These are estimates of API list-price token rates at standard tier, not provider invoices. The table models no prompt caching, no batch discounts, and no long-context surcharges. Gateway markups are modeled only when separately verified against the gateway's live pricing. The `basis` field states this in the JSON itself. Anyone reproducing a peira cost figure should expect their own invoice to differ. The comparison across guardrails is the product, not the absolute number.

## 4. Reconciliation when rates change

Providers change prices. When one does, and they do, the procedure below applies. Google's announced step-up for gemini-3.8-flash to $1.50/$7.50 per 1M effective 2027-01-01 is the live example.

- The table maintainer updates the affected entry, bumps `date` and `pricing_version` together, and adds a dated changelog line to the table's `_comment` header. Date and version are never bumped separately.
- Sealed artifacts are never repriced retroactively. A run keeps the table version it ran against, which is exactly what the sealed `pricing_version` is for.
- The changelog records what changed, the new rate, the effective date, and the source. Announced future changes are noted in the entry's `_note` with their effective date (the gemini step-up entry is the pattern) and applied when the date arrives.

Any maintainer that spots an announcement may update the table. Waiting for a scheduled review is not required. The bump procedure above is.

## 5. Conflict resolution

When a rate's sourcing turns out to be wrong, the correction follows the 2026-09-23 Jev amendment, which is the honesty bar for this file.

The original adapter-pin decision in `docs/Decisions.md` called the Jev $0.042/1M rate "TypeSafe's published". That was wrong. The rate is secondary-sourced via gateway announcements (Vercel, Netlify, Spring AI, Sept 2026), unconfirmed on any official TypeSafe pricing page. The correction was made in place in pricing.json with the caveat, and the stale original wording was kept in `docs/Decisions.md`, explicitly labeled as the historical record.

The rule says correct in place, keep the stale original labeled as the historical record, never silently edit. A reader comparing versions must be able to see what changed and why.

## 6. The D13 re-verification procedure

GOAL.md D13 requires the pricing table to be re-verified against live provider pages at A8, before ledger estimates. The re-verifier works through this checklist.

1. Open every vendor pricing page or first-party source linked in the entry's `_note` (or in `source_urls`).
2. Confirm the model id or route, the input rate, and the output rate match the table entry.
3. Record the verification date in the entry's `_note`, then bump `date` and `pricing_version` together.
4. For gateway routes (for example `google/gemini-3.8-flash` on OpenRouter), verify against the gateway's live pricing, not the direct vendor's. A gateway rate carried over from the direct vendor stays "secondary" until this happens.

A pass means every priced entry is either "official" with a current verification date, or "secondary" with its provenance stated. On a mismatch, the re-verifier downgrades the entry to "secondary" with a dated note, or marks it unpriced by removing the rate when no reliable source exists. Never ship a guessed rate. If a rate cannot be verified, the model runs unpriced until it can.

Re-verification is a dated event, recorded in the table header. The next A8 does it again.
