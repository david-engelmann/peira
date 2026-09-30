---
layout: ../../layouts/Docs.astro
title: Adapter setup
---

# Adapter setup

Three kinds of adapters, three setup patterns. Local Hugging Face
guardrails, hosted APIs with OpenAI-compatible endpoints, and local or
rule-based baselines. Every adapter loads by dotted path and is
instantiated with no arguments, so all configuration happens through
environment variables. API keys never appear in transcripts or logs.

Start by checking the machine is ready.

```bash
peira doctor
```

It reports on the system, the installed datasets, and which adapters
can run. Fix whatever it flags, then come back here.

## Local Hugging Face guardrails

The guardrail adapters run open models locally through transformers.
One install covers all seven.

```bash
pip install "peira[hf]"
```

This pulls torch and transformers. Transformers stays pinned below v5
until the adapters are verified against it. Models download from the
Hugging Face Hub on first use and are cached locally, so the first run
needs network access and disk space while later runs are fully offline.
Every model is pinned to an exact commit revision, never main, so the
weights you score are the weights everyone scores. The resolved
revision is sealed into the run artifact.

Walkthrough with Shieldstral, the policy-adaptive guardrail.

```bash
peira run --adapter peira.adapters.hf:ShieldstralAdapter --suite trial-demo --out /tmp/shieldstral
```

The seven adapters and their one-time setup needs.

| Adapter | Dotted path | Setup note |
|---|---|---|
| Shieldstral | peira.adapters.hf:ShieldstralAdapter | none |
| ProtectAI prompt injection | peira.adapters.hf:ProtectAIAdapter | none |
| Llama Prompt Guard 2 86M | peira.adapters.hf:LlamaPromptGuard2Adapter | gated model, see below |
| Qwen3Guard-Gen 4B | peira.adapters.hf:Qwen3GuardAdapter | none, Apache-2.0 |
| Granite Guardian 4.1 8B | peira.adapters.hf:GraniteGuardianAdapter | none, Apache-2.0 |
| ShieldGemma 2B | peira.adapters.hf:ShieldGemmaAdapter | gated model, see below |
| WildGuard | peira.adapters.hf:WildGuardAdapter | needs sentencepiece and protobuf for its tokenizer |

Gated models need one manual step each. For Llama Prompt Guard 2,
accept the license on its Hugging Face page, then authenticate.

```bash
huggingface-cli login
peira run --adapter peira.adapters.hf:LlamaPromptGuard2Adapter --suite trial-demo --out /tmp/lpg2
```

It ships under the Llama 4 Community License, not an OSI-approved
license, and it works on a 512-token window, so longer inputs are
segmented and the worst segment wins. For ShieldGemma 2B, accept the
Gemma Terms of Use on Hugging Face before first use. WildGuard is
auto-gated under AI2's Responsible Use Guidelines, which means no
manual approval step, but do install its tokenizer dependencies.

```bash
pip install sentencepiece protobuf
```

Two behavior notes worth knowing before you read numbers. ProtectAI
has a known false-positive tendency on system-prompt-style content.
Long instruction-like text can read as an injection to it, so treat
its verdicts on policy-heavy prompts with skepticism. Qwen3Guard runs
in strict mode, which means a Controversial verdict counts as unsafe.
A guardrail that cannot clear content as Safe has not cleared it.

## Hosted APIs (LLM baselines)

These are peira's LLM-as-judge adapters. Each one makes a frontier
model return a typed decision through the provider's native
constrained decoding, with temperature 0 and a pinned seed where the
provider supports one. Install only the extra you need, export the
key, and run.

| Provider | Extra | Dotted path | Key |
|---|---|---|---|
| OpenAI | peira[openai] | peira.adapters.llm:OpenAIAdapter | OPENAI_API_KEY |
| Anthropic | peira[anthropic] | peira.adapters.llm:AnthropicAdapter | ANTHROPIC_API_KEY |
| Google | peira[google] | peira.adapters.llm:GoogleAdapter | GOOGLE_API_KEY |
| Moonshot (Kimi) | peira[openai] | peira.adapters.llm:MoonshotAdapter | MOONSHOT_API_KEY |
| xAI (Grok) | peira[openai] | peira.adapters.llm:XAIAdapter | XAI_API_KEY |
| DeepSeek | peira[openai] | peira.adapters.llm:DeepSeekAdapter | DEEPSEEK_API_KEY |
| Meta (Llama API) | peira[openai] | peira.adapters.llm:MetaLlamaAdapter | META_API_KEY |
| Zhipu (GLM) | peira[openai] | peira.adapters.llm:ZaiAdapter | ZAI_API_KEY |

Walkthrough with OpenAI.

```bash
pip install "peira[openai]"
export OPENAI_API_KEY=...
peira run --adapter peira.adapters.llm:OpenAIAdapter --suite trial-demo --out /tmp/openai
```

Walkthrough with Kimi K3, the cheapest way to put a
frontier-adjacent model on the board at $3/$15 per 1M.

```bash
pip install "peira[openai]"
export MOONSHOT_API_KEY=...
peira run --adapter peira.adapters.llm:MoonshotAdapter --suite trial-demo --out /tmp/kimi
```

The pattern is identical for the rest. Export the key named in the
table and swap the dotted path. Keys are sent as bearer tokens and
never land in transcripts. The transcript records the base URL and
the request shape, never the key.

A few honest notes. Default models are pinned per each vendor's
versioning scheme, and the resolved model id is sealed into the run
artifact, so a pinned run is reproducible. You can pass a different
model explicitly with model=, and the version string records it
honestly, but a run on an unpinned model is not reproducible by
construction. Passing a model id the vendor has retired fails closed
and names the replacement. Confidence on these adapters is
self-reported, verbalized by the model plus the decision-token
logprob where the provider exposes one, and peira reports it without
vouching for it. Every public label says self-reported confidence.

Several of these adapters were built from published docs rather than
the live API. Moonshot, xAI, DeepSeek, Meta, and Zhipu fall in this
group. Whether
strict JSON schema response format is honored for each model id is
unverified. Verify against the live API before any measured run.
Mismatches surface as loud terminal provider errors, not silent
mismeasurement. The runner owns retries and the SDKs are configured
for a single attempt, so a transient 429 or 5xx is retried by the
runner and anything else fails fast.

One thing not to try. The frontier ceiling candidate,
claude-fable-5-1, is a docs entry, not a runnable target. The current
Anthropic adapter shape returns a 400 on every call for it until the
output_config.format migration lands. Do not run it before then.

On cost. peira run recomputes cost from its pinned pricing table and
ignores adapter-reported cost. The table's source and pin date are
sealed into every artifact. For paid runs, set `--budget-usd` to cap
spend. A budget-stopped run is fully analyzable but never rankable.

## Local and rule-based baselines

The mock adapter needs nothing and runs offline. It is the pipeline
check from the quickstart. Its numbers exercise the machinery and are
never a benchmark result.

```bash
peira run --adapter mock --suite trial-demo --out /tmp/demo
```

TypeSafe Jev is a decision-model API, not a chat model. No extra
install needed, just the key.

```bash
export TYPESAFE_API_KEY=...
peira run --adapter peira.adapters.jev:JevAdapter --suite trial-demo
```

The model is pinned to jev-1.13.0 and floating tags are rejected at
construction. Without a key the error tells you exactly where to get
one. One honest caveat. The request shape is built from TypeSafe's
published SDK examples and the adapter has not been exercised against
the live API yet. If the service answers differently than documented,
you will see terminal provider errors, not silent mismeasurement.

Laya is the open Jev alternative, a local 421M classifier under
Apache 2.0. No key, no gating.

```bash
pip install laya
peira run --adapter peira.adapters.laya:LayaAdapter --suite trial-demo
```

Three checkpoints are available through checkpoint=, including a
multilingual one and a typed-decisions fine-tune. Each checkpoint gets
its own cache namespace, so runs never share cached responses across
checkpoints. Same honest caveat as Jev. Built from published docs,
not yet exercised against the real package.

Kev is an open decision model in the Jev style, served locally. Start
the server first, then point the adapter at it.

```bash
python -m kev.serve --run jaredpalmer/kev-4b --port 8008
peira run --adapter peira.adapters.kev:KevAdapter --suite trial-demo
```

The adapter defaults to 127.0.0.1 on port 8008 at the /v1/systemone
path, and override with api_url= if your server lives elsewhere.
Seven sizes are available through model=, from the 0.5B prototype up
to the 27B checkpoint, with jaredpalmer/kev-4b as the default.
Floating tags are rejected. A server that cannot be reached is a
terminal error whose message tells you how to start it, and the
runner never retries a missing local server. Cost is $0.

SemIf reads typed option probabilities from a frozen open model in
one forward pass. It is a subprocess adapter, so install its CLI
first.

```bash
# from a clone of the SemIf repo, inside a venv
pip install -e '.[test]'
peira run --adapter peira.adapters.semif:SemifAdapter --suite trial-demo
```

The CLI loads 4B weights per process, so cold starts are slow and
timeout_s defaults to 600 seconds. Every CLI failure is a terminal
provider error the runner never retries. Cost is $0. Same honest
caveat. The adapter has not been exercised against a real semif-score
install yet.

openjev-sglang is a self-hosted server implementing the Jev HTTP API
on open models with prefill-only inference. Deploy it per its own
docs, then point the adapter at it.

```bash
peira run --adapter peira.adapters.openjev_sglang:OpenJevSglangAdapter --suite trial-demo
```

The default address is localhost on port 8000 at the /v1/systemone
path. If your deployment requires auth, set OPENJEV_API_KEY and it is
sent as a bearer token, never logged. Without it, requests go
keyless. Cost is $0. Same honest caveat about the wire shape.

Lakera Guard is a commercial threat-detection API. No extra install.

```bash
export LAKERA_API_KEY=...
peira run --adapter peira.adapters.lakera:LakeraAdapter --suite trial-demo
```

The API version is pinned to v2. Pricing in the pinned table is a
free Community tier at 10k calls per month with paid entry around
$99 per month for 50k calls, secondary-sourced and flagged as such.
The wire shape is from Lakera's published API docs and the adapter
has not been exercised against the live API yet.

## What a run prints

Every peira run ends with the same summary block. Progress counts,
spend, ASR with its 95% interval, benign accuracy, malformed and
refusal rates, the ineligible breakdown, and the ranking eligibility
verdict. The sealed artifact lands in `--out`. How to read those
numbers is on the [interpreting results](interpreting-results) page.

When something fails, start with peira doctor. Then check that the
key environment variable is actually exported, that gated models
have their license accepted, and that local servers are listening on
the address the adapter expects. Provider errors are loud by design.
Terminal means fix the configuration. Retryable means the runner
already retried and it still failed.
