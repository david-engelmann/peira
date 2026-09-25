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
continuous score. Choice and abstain primitives; score is not supported.

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

**Exception: `safety_policy` cases.** On the safety-policy family the
case labels *are* the guardrail's native vocabulary (`allow` / `block`),
so the veto translation is dropped and the adapter emits native
verdicts: safe/benign → `allow`; unsafe/malicious → `block`, or
`block-<category>` for category classifiers (Llama Guard 4, WildGuard,
ShieldGemma) using the category slugs in
`dataset/v1/safety_policy_SPEC.md` §2. Policy-adaptive Shieldstral
judges the content against the safety policy stated in the case prompt
(violation → `block`, otherwise `allow`). Confidence stays `|2p − 1|`
on every primitive. ASR on this family therefore reads as the
*attacker's* success rate (evasion + false-positive induction) — lower
is better — the inverse of the D-23 detection-rate reading on the
other ten families; never compare the two naively. Full mapping table
and the coarse-equivalence scoring rule (`block-<x>` ≡ `block` for
flip/eligibility; exact-category agreement is a diagnostic) live in
the family spec.

## Structured-output LLM baselines

One adapter per provider, one extra each — install only what you need:

| Adapter | Extra | Dotted path | Default model | API key |
|---|---|---|---|---|
| OpenAI | `peira[openai]` | `peira.adapters.llm:OpenAIAdapter` | `gpt-5.6-luna` | `OPENAI_API_KEY` |
| Anthropic | `peira[anthropic]` | `peira.adapters.llm:AnthropicAdapter` | `claude-sonnet-5` | `ANTHROPIC_API_KEY` |
| Google | `peira[google]` | `peira.adapters.llm:GoogleAdapter` | `gemini-3.8-flash` | `GOOGLE_API_KEY` |
| Moonshot (Kimi) | `peira[openai]` | `peira.adapters.llm:MoonshotAdapter` | `kimi-k3` | `MOONSHOT_API_KEY` |

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
enum is built from the trial context's labels (`CallContext`), not a
fixed list and not the case input. Temperature
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

### Frontier ceiling (candidate — NOT runnable yet)

The strongest model peira can measure against — the upper bound every
other adapter is compared to. Candidate picked 2026-09-25:
**`claude-fable-5-1`** (Anthropic, GA 2026-09-01, $10/$50 per 1M in the
pinned pricing table), to be used opt-in via
`AnthropicAdapter(model="claude-fable-5-1")` **after** the
`output_config.format` migration lands. Defaults are unchanged — the
ceiling is never the default. This is a docs + pricing entry only:
do not run it on the current adapter shapes.

Why Fable 5.1 over GPT-6 Astra (`gpt-6-astra`, also $10/$50, GA
2026-09-03):

- **Availability.** Fable 5.1 shipped on every major platform (Claude
  API, Bedrock, Vertex AI, Foundry, AWS) on day one of GA (2026-09-01,
  per 9to5Mac). Astra rolled out in phases (Daybreak program first,
  then API) — a ceiling nobody can run is decorative.
- **Benchmark evidence.** Fable 5.1 holds the highest Artificial
  Analysis Intelligence Index score reported to date (66 of 192 models —
  ahead of Claude Opus 5 at 63, Fable 5 at 62, GPT-5.6 Sol at 61). No
  independent comparative index score was found for Astra (its public
  numbers, e.g. GPQA Diamond 96.1%, are vendor-adjacent).
- **Adapter compatibility.** Neither candidate is a pure `model=`
  drop-in, but Fable 5.1's fix is already peira's decided direction:
  it rejects forced `tool_choice` (400), and its documented structured
  path is native `output_config.format` JSON schema — exactly the
  migration the adapter matrix already chose for the newer Anthropic
  reasoning models. Astra instead 400s on `temperature`, `top_p`, and
  `logprobs`, which `OpenAIAdapter` sends on every call, so
  `OpenAIAdapter(model="gpt-6-astra")` fails on every call without a
  new per-model special-case.

**Honest caveats:** (1) the model id `claude-fable-5-1` follows
Anthropic's documented naming convention (Fable 5's id was
`claude-fable-5`) but is NOT independently confirmed on the live API —
verify before the first run; (2) the current `AnthropicAdapter` still
uses forced tool use — a live ceiling run 400s until the
`output_config.format` migration lands. Do not run it before then;
the 400 is a loud terminal provider error, not a measurement. Full
rationale is recorded as D-32 in `docs/Decisions.md`.
error, not a silent mismeasurement.

### Kimi K3 (Moonshot)

```bash
pip install "peira[openai]"
export MOONSHOT_API_KEY=...
peira run --adapter peira.adapters.llm:MoonshotAdapter --suite trial-demo
```

Kimi K3 (Moonshot AI, July 2026) is a 2.8T sparse mixture-of-experts
model (16 of 896 experts active per token) with a 1M-token context
window — the biggest open-weight release to date, under the Kimi K3
License — and at $3/$15 per 1M it is the self-host audience's flagship
model: the cheapest way to put a frontier-adjacent model on the board.
The adapter drives Moonshot's OpenAI-compatible endpoint
(`https://api.moonshot.ai/v1`, model id `kimi-k3`) with the same strict
JSON-schema request shape as `OpenAIAdapter`; the base URL is recorded
in the transcript's request shape, and the key is never logged.
`max_retries=0` — the runner owns retries, same as every other LLM
baseline.

Two honest caveats: the adapter is built from Moonshot's published
docs and third-party parameter surveys, not the live API — Moonshot
documents `temperature` only on the 0..1 range, and whether
`json_schema` `response_format` (vs plain `json_object`) is honored
for `kimi-k3` is unverified. On `seed`/`logprobs` the surveys agree
(both unsupported, both 400 when sent), so the adapter OMITS both
fields from the request rather than negotiating — there is no
decision-token logprob track on this adapter, and the transcript
honestly records `"seed": None`. Verify against the live API before
any measured run; mismatches surface as terminal provider errors, not
silent mismeasurement.

## TypeSafe Jev

No extra needed (stdlib transport). Set `TYPESAFE_API_KEY`:

```bash
export TYPESAFE_API_KEY=...
peira run --adapter peira.adapters.jev:JevAdapter --suite trial-demo
```

Jev is a decision-model API, not a chat model: the adapter sends the
case prompt as `state` plus named typed questions — each question
carries `instructions` and `criteria` — and reads back `choice`
(choice), `score` (score), or `abstain` (abstain) answers. The score
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

## Laya

```bash
pip install laya
peira run --adapter peira.adapters.laya:LayaAdapter --suite trial-demo
```

Laya (Convai Innovations, Sept 2026) is the open-source Jev
alternative: a 421M ModernBERT-based decision classifier (Apache 2.0)
run locally — no API key, no gating. The adapter sends the case prompt
as `state` plus named typed questions and reads back `choice`,
`score`, or `noul` answers. Peira's `abstain` primitive is sent as
Laya's `noul` question type at the boundary (Laya's API kept the
`noul` name after Peira's 2026-09-25 rename); the `noul` answer field
is read back as the abstain signal.

Three checkpoints, pinned by exact Hub id (floating tags rejected at
construction), selectable via `checkpoint=`:

- `convaiinnovations/laya` (default): 421M English, 76.6% accuracy
  (fine-tuned), ~33ms latency.
- `convaiinnovations/laya-multilingual`: 322M multilingual.
- `convaiinnovations/laya-typed-decisions`: fine-tuned checkpoint.

Each checkpoint gets its own `cache_namespace`, so runs never share
runner cache entries across checkpoints. The model is local, so there
are no HTTP status codes: a `predict()` failure surfaces as a
terminal provider error (never retried) and the variant is recorded
malformed. One honest caveat: the adapter is built from Laya's
published API and hasn't been exercised against the real package yet —
if it answers differently, you'll see terminal provider errors, not
silent mismeasurement. The `score` answer is assumed 0..1 and clamped;
scores clustering at the clamp edges would indicate a scale bug.

## Kev

```bash
# From a clone of github.com/jaredpalmer/kev (serve extra installed):
python -m kev.serve --run jaredpalmer/kev-4b --port 8008
peira run --adapter peira.adapters.kev:KevAdapter --suite trial-demo
```

Kev (Jared Palmer, Apache 2.0) is an open decision model in the
Jev/System One style: a LoRA adapter plus a pointer readout head on a
Qwen backbone that takes one document plus typed questions and returns
calibrated probabilities in a single forward pass. `kev.serve` exposes
a TypeSafe-compatible `POST /v1/systemone` endpoint, so the adapter
reuses the Jev wire logic wholesale — the same `{"model", "state",
"questions"}` requests and `choice`/`score`/`noul` answers, including
the abstain-to-`"noul"` boundary mapping. The differences from Jev:
no API key (local server, no auth header), `api_url=` pointing at the
server (default `http://127.0.0.1:8008/v1/systemone`, kev.serve's
documented port), and the pinned model id.

Seven sizes, pinned by exact Hub id (backbones per each repo's Hub
tags, verified live against the `jaredpalmer/kev` collection on
2026-09-25), selectable via `model=` (short names accepted):

- `jaredpalmer/kev-0.5b`: Qwen2.5-0.5B — the original prototype;
  its own card says it is superseded by 0.8B/4B/9B. Kept for
  reproducibility.
- `jaredpalmer/kev-0.6b`: Qwen3-0.6B — previous generation, no
  longer developed. Kept for reproducibility.
- `jaredpalmer/kev-0.8b`: Qwen3.5-0.8B — current family, small arm.
- `jaredpalmer/kev-4b` (default): Qwen3.5-4B — current family.
- `jaredpalmer/kev-8b`: Qwen3-8B — previous generation, no longer
  developed. Kept for reproducibility.
- `jaredpalmer/kev-9b`: Qwen3.5-9B — current family.
- `jaredpalmer/kev-27b`: Qwen3.8-27B — newest checkpoint (2026-09-24),
  the biggest available size, large arm.

The current generation is Qwen3.5-based (0.8b / 4b / 9b) plus the
newest Qwen3.8-based 27b. Floating tags like `kev-latest` are rejected
at construction; each size gets its own `cache_namespace`.

A server that cannot be reached is a terminal provider error whose
message tells you exactly how to start it — the runner never retries
a missing local server. HTTP error statuses keep their status codes
for the runner's classifier. The model is local and self-hosted, so
cost is $0. One honest caveat: the adapter is built from kev's
published docs and hasn't been exercised against a live `kev.serve`
instance — if the server answers differently than the shared
TypeSafe-shaped contract, you'll see terminal provider errors, not
silent mismeasurement.

## SemIf

```bash
# Clone github.com/theoleecj/semif, create the venv, then:
pip install -e '.[test]'
peira run --adapter peira.adapters.semif:SemifAdapter --suite trial-demo
```

SemIf (TheoLeeCJ, MIT — formerly OpenJev, renamed ~2026-09-18, ~4.3k
stars) reads typed option probabilities directly from a frozen open
model in one forward pass: no answer sentence, no JSON repair, no
decoding loop. It is the most-starred Jev-pattern open project. This
is a subprocess adapter: each `decide()` spawns the `semif-score` CLI
(the pre-rename `openjev-score` binary is picked up automatically if
`semif-score` is absent) in `--mode direct`, feeding it a batch JSONL
file of input rows (`{"id", "state", "question", "options":
[{"id", "description"}]}`) and parsing the returned rows' typed
option probabilities.

Model and revision are both pinned and validated at construction:
`Qwen/Qwen3.5-4B` @ `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` (the
revision SemIf's own docs pin for every scoring command). Peira's
`abstain` primitive is expressed as an ordinary yes/no question
("Should this case be abstained?") — SemIf's CLI has no `"noul"` wire
type, so there is no boundary translation here; the `"yes"`
probability is the abstain signal with the same >= 0.5 threshold the
Jev-family adapters use. The score primitive is a five-level rubric
question plus a paired decision row, mirroring the Jev adapter's
two-question score shape.

Every CLI failure (missing binary, timeout, nonzero exit, unparseable
output) is a terminal provider error with no status code — the runner
never retries a broken CLI. The model is local and self-hosted, so
cost is $0. Two honest caveats: the CLI loads the 4B weights per
process, so per-call spawning is correct but slow on cold starts
(`timeout_s` defaults to 600s), and the adapter hasn't been exercised
against a real `semif-score` install — the output-row key shapes are
parsed tolerantly from the docs' "typed option scores, timing, model
revision, prompt hash" promise, and anything unrecognized raises a
terminal provider error, not silent mismeasurement.

## openjev-sglang

```bash
# Deploy per github.com/ekzhang/openjev-sglang (SGLang + FastAPI),
# then point the adapter at it:
peira run --adapter peira.adapters.openjev_sglang:OpenJevSglangAdapter --suite trial-demo
```

openjev-sglang (ekzhang) is a server implementing the TypeSafe/Jev
HTTP API on open models with prefill-only inference: a FastAPI process
fronts SGLang (Rust frontend, radix caching, prefill CUDA graphs) and
exposes Jev-compatible `POST /v1/systemone` — the same `{"model",
"state", "questions"}` → `{"answers": {...}}` shape, with the same
typed `choice`/`score`/`noul` questions including the
abstain-to-`"noul"` boundary mapping. The adapter reuses the
self-hosted wire plumbing it shares with Kev: configurable `api_url=`
(default `http://localhost:8000/v1/systemone`), plus optional Bearer
auth — the project's README documents `OPENJEV_API_KEY`, and the
adapter sends it as `Authorization: Bearer <redacted>` when set
(`api_key=` or the env var); without it, requests go keyless. The key
never appears in transcripts.

The model is `Qwen/Qwen3.6-35B-A3B` MoE (verified against the
project's published BoolQ eval report, 2026-09-18) and is baked into
the server deployment, so the adapter accepts only that id —
anything else is rejected at construction. The model is local and
self-hosted, so cost is $0. One honest caveat: the adapter hasn't been
exercised against a live openjev-sglang deployment — field names are
our best reading of the project's documented request examples, and a
server that answers differently produces terminal provider errors,
not silent mismeasurement. The project's published parity number
(95.5% vs Jev 96.3% on the aligned subset, overlapping CIs) is their
claim, not a peira measurement.

## Pricing

`peira run` recomputes cost from the pinned table in
`python/peira/data/pricing.json` — adapter-reported cost is ignored.
The table's source and pin date are sealed into every run artifact.
