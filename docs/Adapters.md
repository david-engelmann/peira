# Adapters

The decision models peira can measure, how to install them, and what
each one actually does. Nothing here ships a number — a row appears on
the leaderboard only after a measured run with name + version + date.

All adapters load by dotted path; classes are instantiated with no
arguments, so configuration is via environment variables:

```bash
peira run --adapter peira.adapters.hf:ShieldstralAdapter --suite trial-demo
```

## Guardrails (`peira[hf]`)

Local Hugging Face models. Install with `pip install peira[hf]`
(torch + transformers, transformers pinned below v5 until the adapters
are verified against it). Models download from the HF Hub on first use
and are cached; every model is pinned to an exact commit revision, never
`main`.

| Adapter | Dotted path | Model | Revision |
|---|---|---|---|
| Shieldstral | `peira.adapters.hf:ShieldstralAdapter` | `mistralai/Shieldstral-1.0-3B` | `003ec7e2b0bab5f0e6307edbaf186fa5822b76f5` |
| ProtectAI prompt injection | `peira.adapters.hf:ProtectAIAdapter` | `protectai/deberta-v3-base-prompt-injection-v2` | `90c9989b1a342275dd0d1a95aad283c04e075671` |
| Llama Prompt Guard 2 86M | `peira.adapters.hf:LlamaPromptGuard2Adapter` | `meta-llama/Llama-Prompt-Guard-2-86M` | `a8ded8e697ce7c355e395a0df51f94adb4a2fd27` |

**Shieldstral** is policy-adaptive: it judges content against the policy
in its prompt, not a fixed category list. It emits a single yes/no
token; the adapter renormalizes the yes/no first-token logprobs into a
continuous score. Choice and noul primitives; score is not supported.

**ProtectAI** is a binary prompt-injection detector (SAFE / INJECTION).
It has a known false-positive tendency on system-prompt-style content —
long instruction-like text can read as an injection to it. Treat its
verdicts on policy-heavy prompts with skepticism.

**Llama Prompt Guard 2** is a binary BENIGN / MALICIOUS classifier with
a 512-token window (longer inputs are segmented, worst segment wins).
Two caveats: the model is **gated** — accept the license on its HF page
and run `huggingface-cli login` before first use — and it ships under
the Llama 4 Community License, not an OSI-approved license. Note this
is v2's deliberate binary scheme; v1's three-label mapping does not
apply.

Guardrail verdict mapping: content judged benign keeps the case's
expected decision (the guardrail vetoes nothing); content judged
malicious becomes the adapter's fixed veto label `"reject"`. That is
what makes ASR read as the guardrail's detection rate. See D-23.

## Structured-output LLM baselines

One adapter per provider, one extra each — install only what you need:

| Adapter | Extra | Dotted path | Default model | API key |
|---|---|---|---|---|
| OpenAI | `peira[openai]` | `peira.adapters.llm:OpenAIAdapter` | `gpt-5.6-luna` | `OPENAI_API_KEY` |
| Anthropic | `peira[anthropic]` | `peira.adapters.llm:AnthropicAdapter` | `claude-sonnet-5` | `ANTHROPIC_API_KEY` |
| Google | `peira[google]` | `peira.adapters.llm:GoogleAdapter` | `gemini-3.8-flash` | `GOOGLE_API_KEY` |

Default model ids are best-known guesses, not verified facts: the
Anthropic and Google ids above haven't been confirmed against the
live providers. If a provider rejects the default id, pass the exact
model you want with `model=` — and let us know, so the default gets
corrected.

Each sends one JSON schema to the provider's native constrained
decoding (OpenAI strict `json_schema`, Anthropic forced tool choice,
Gemini `responseSchema`), then revalidates the response client-side.
The decision vocabulary is per-call — peira cases use open label sets
(`deny`, `emergency-dept`, `choose A`, …), so the schema's decision
enum is built from the case's own labels, not a fixed list. Temperature
0, pinned seed where the provider supports one (Anthropic has no seed
parameter).

Confidence is the model's **verbalized** confidence plus the
decision-token logprob where the provider exposes one (Anthropic
exposes none). Verbalized confidence is uncalibrated until measured —
peira reports it, it does not vouch for it. See D-22, D-23.

Refusals become abstentions with a reason, never silent: provider stop
reason first, then a refusal-prefix scan. If the output validates
against the schema, it is used; after one repair retry, persistent
validation failure is a terminal provider error. The
adapter never retries — the runner owns retries, and the SDKs are
configured for a single attempt so the runner's congestion signal stays
honest.

## TypeSafe Jev

No extra needed (stdlib transport). Set `TYPESAFE_API_KEY`:

```bash
export TYPESAFE_API_KEY=...
peira run --adapter peira.adapters.jev:JevAdapter --suite trial-demo
```

Jev is a decision-model API, not a chat model: the adapter sends the
case prompt as `state` plus named typed questions — each question
carries `instructions` and `criteria` — and reads back `choice`
(choice), `score` (score), or `noul` (noul) answers. The score
question uses five described levels ("strongly favor deny" …
"strongly favor approve"), not raw numbers. The model is pinned to
`jev-1.13.0` — floating tags are rejected at construction. Reported
pricing is $0.042 per 1M input tokens with output free (secondary-sourced
via gateway announcements — not confirmed on an official TypeSafe pricing
page), and the pinned table in `python/peira/data/pricing.json` reflects
that with the caveat attached. Access is
gated; without a key the error tells you exactly where to get one.
429/529/5xx and transport timeouts surface as retryable provider
errors for the runner; 401/422 are terminal. One honest caveat: the
request shape is built from TypeSafe's published SDK examples, but the
adapter hasn't been exercised against the live API yet — if the
service answers differently than documented, you'll see terminal
provider errors, not silent mismeasurement. See D-24.

## Pricing

`peira run` recomputes cost from the pinned table in
`python/peira/data/pricing.json` — adapter-reported cost is ignored.
The table's source and pin date are sealed into every run artifact.
