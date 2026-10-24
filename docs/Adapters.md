# Adapters

The decision models peira can measure, how to install them, and what
each one actually does. Nothing here ships a number. A row appears on
the leaderboard only after a measured run with name + version + date.

All adapters load by dotted path; classes are instantiated with no
arguments, so configuration is via environment variables:

```bash
peira run --adapter peira.adapters.hf:ShieldstralAdapter --suite trial-demo
```

## Community adapters (third-party plugin registry)

The adapters above are first-party: their code lives in this repo.
Third-party adapters ship as their own PyPI packages
(`peira-adapter-<slug>`) and register under the `peira.adapters`
entry-point group. They run isolated in a subprocess by default
(never inside peira's process). The full author guide, including
the conformance kit (`peira adapter check`), is in
`docs/third-party-adapters.md`.

A row below is a link, not an endorsement. It states that a given
set of bits passed conformance on a given date, nothing more. The
badge never follows a package to a new version without a new check;
verify with `peira adapter check --verify <report>` before relying
on the numbers. Run artifacts seal the adapter's provenance
(`adapter_trust`, `adapter_transport`, dist name/version, module
SHA-256). No vendor marks appear inside data artifacts (N-1); the
leaderboard never carries sponsor placement.

| Registry id | Adapter | Conformance | Checked | Distribution | Module SHA-256 |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

To get listed: publish your package, run
`peira adapter check <your-id>` until it is green, then open a docs
PR adding your row. A maintainer re-runs the check on a clean
machine and reviews measurement honesty before merging. Delisting
is a docs PR too: a row is removed if a later check fails or
measurement dishonesty is found.

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
| Qwen3Guard-Gen 4B | `peira.adapters.hf:Qwen3GuardAdapter` | `Qwen/Qwen3Guard-Gen-4B` | `6ec42827da0c1ff11e7a49dc269d2e810d27e108` |
| Granite Guardian 4.1 8B | `peira.adapters.hf:GraniteGuardianAdapter` | `ibm-granite/granite-guardian-4.1-8b` | `ab01ccca5dcfb80246369a086a4a87a29198f5af` |
| ShieldGemma 2B | `peira.adapters.hf:ShieldGemmaAdapter` | `google/shieldgemma-2b` | `d1dffc9c8c9237a90aab09c61383791e718ef9e8` |
| WildGuard | `peira.adapters.hf:WildGuardAdapter` | `allenai/wildguard` | `cbba4823f3e8020e5a74a5e29bf85072def6f2ff` |
| HarmBench classifier | `peira.adapters.hf:HarmBenchAdapter` | `cais/HarmBench-Llama-2-13b-cls` | `bda705349d1144fa618770bea64d99ce54e3835b` |
| Granite Guardian HAP-125M | `peira.adapters.hf:GraniteGuardianHapAdapter` | `ibm-granite/granite-guardian-hap-125m` | `a76ccfd3ddb790fa7c23db58149bfec7ba1aa57f` |
| Qwen3Guard-Gen 8B | `peira.adapters.hf:Qwen3Guard8BAdapter` | `Qwen/Qwen3Guard-Gen-8B` | `4505cb1a6f1864f21f8b27f7daf1b9a1aab6edbb` |
| ShieldGemma 9B | `peira.adapters.hf:ShieldGemma9BAdapter` | `google/shieldgemma-9b` | `b8b636016df4540721a098c7aab91c97ec6ee508` |
| Nemotron Safety Guard 8B v3 | `peira.adapters.hf:NemotronSafetyGuardAdapter` | `nvidia/llama-3.1-nemotron-safety-guard-8b-v3` | `8fdc246ba3d56db9c469d534233b9f582d3afafa` |
| Llama Guard 4 12B | `peira.adapters.hf:LlamaGuard4Adapter` | `meta-llama/Llama-Guard-4-12B` | `87acb4b94e930c3d679e6e7ee9d57e2feab9ea71` |
| gpt-oss-safeguard 20B | `peira.adapters.hf:GptOssSafeguardAdapter` | `openai/gpt-oss-safeguard-20b` | `8a11e17b25c973a24099d4016bf2e17dd7ec1574` |
| Llama Guard 3 1B | `peira.adapters.hf:LlamaGuard3_1BAdapter` | `meta-llama/Llama-Guard-3-1B` | `acf7aafa60f0410f8f42b1fa35e077d705892029` |
| Llama Guard 3 8B | `peira.adapters.hf:LlamaGuard3_8BAdapter` | `meta-llama/Llama-Guard-3-8B` | `7327bd9f6efbbe6101dc6cc4736302b3cbb6e425` |

**Shieldstral** is policy-adaptive: it judges content against the policy
in its prompt, not a fixed category list. It emits a single yes/no
token; the adapter renormalizes the yes/no first-token logprobs into a
continuous score. Choice and abstain primitives; score is not supported.

**ProtectAI** is a binary prompt-injection detector (SAFE / INJECTION).
It has a known false-positive tendency on system-prompt-style content:
long instruction-like text can read as an injection to it. Treat its
verdicts on policy-heavy prompts with skepticism.

**Llama Prompt Guard 2** is a binary BENIGN / MALICIOUS classifier with
a 512-token window (longer inputs are segmented, worst segment wins).
Two caveats: the model is **gated**. Accept the license on its HF page
and run `huggingface-cli login` before first use, and it ships under
the Llama 4 Community License, not an OSI-approved license. Note this
is v2's deliberate binary scheme; v1's three-label mapping does not
apply.

**Qwen3Guard-Gen** is a three-tier generative guard (Safe / Unsafe /
Controversial) run in prompt-moderation mode through its own chat
template, with `Safety: ` prefilled so the verdict is the next token.
The adapter renormalizes the first-token logprobs over the three label
tokens and takes P(Unsafe) + P(Controversial) as the malicious score:
**Strict mode**: Controversial counts as unsafe, since a guardrail that
cannot clear content as Safe has not cleared it. The model's argmax
label is recorded in the transcript. Caveat: independent robustness
work found Qwen3Guard accuracy collapsing on novel adversarial prompts,
so expect below-leaderboard numbers on peira's semantic arms. That is
signal about the guardrail, not an adapter defect. Apache-2.0, ungated.

**Granite Guardian 4.1** is IBM's yes/no generative safety judge, run in
prompt-moderation mode through its own chat template: the case text as
the first user message, then the official guardian block (no-think
mode, pre-baked Harm criterion, prompt-classification scoring schema)
as the final user message, with `<think>\n</think>\n\n<score>`
prefilled so the verdict is the next token. The adapter takes
P(yes) / (P(yes) + P(no)) over the first-token logprobs as the
malicious score (IBM's own logprob practice); yes means the text meets
the Harm criterion. The Harm criterion is frozen rather than BYOC per
family: v1 is abstain-primitive-only, so a single universal-harm test
is the honest mapping. Apache-2.0, ungated.

**ShieldGemma 2B** is Google's prompt-classification guard, run through
its own chat template with a frozen combined guideline covering all
four v1 harm categories (sexually explicit, dangerous content, hate
speech, harassment). The adapter reads the first-token logits from a
single forward pass (no generation) and renormalizes P(Yes) over the
Yes/No label tokens. Scope limitation: v1 has no general-harm
catch-all, unlike Granite Guardian. Gated model (requires accepting
Gemma Terms of Use on HuggingFace).

**WildGuard** is AllenAI's open instruction-tuning safety classifier,
run through its upstream `WILDGUARD_INPUT_FORMAT` prompt (not a chat
template) with an empty response slot and a trailing `Harmful request:`
probe. The adapter scores the next-token yes/no logits from a single
forward pass and renormalizes over the Yes/No label tokens. Yes maps
to the `abstain` primitive; No maps to `other`. Requires
`sentencepiece` and `protobuf` for the Mistral tokenizer. Auto-gated
under AI2's Responsible Use Guidelines (no manual approval needed).
Apache-2.0.

**HarmBench** is the cais Llama-2-13b classifier used as the
attack-success-rate judge across jailbreak papers. Peira uses the
same judge with a repurposed mapping, not the (behavior,
model-generation) pairs the published numbers use. Despite the
`-cls` repo name it is a generative classifier (`LlamaForCausalLM`
in the pinned config), so the adapter scores it like Shieldstral:
greedy-generate one token and renormalize over the Yes/No
first-token logprobs. The prompt is the model's official
`LLAMA2_CLS_PROMPT` template from the model card, reproduced
byte-exact. HarmBench judges (behavior, response) pairs; peira
screens prompts, so the case text goes in the `Generation:` slot
and `Behavior:` carries the fixed descriptor `harmful request`.
Putting the case text in `Behavior:` with an empty generation would
ask whether an empty string exemplifies the behavior, which is
always no, so that mapping is deliberately not used. Caveat: the
template's own rules discount vague behavior instances, and
"harmful request" is vague, so this mapping is conservative (biased
toward `No`) by construction. MIT, ungated. Live-UNVERIFIED: the
13B weights have not been loaded in this environment; the labels
are capitalized Yes/No because that is what the fine-tuned model
emits (the model card's own example shows `['Yes', 'Yes', 'No',
.....]`). Before any measured use, the first load must
empirically confirm the Yes/No token ids resolve AND that the
model actually emits the resolved piece as its first token on
probe prompts. Generate a few and inspect the real first token
id, since reading the wrong piece would silently score everything
to one side.

**Granite Guardian HAP-125M** is IBM's tiny (125M) RoBERTa
hate/abuse/profanity classifier, the same family as the 8B
generative Guardian 4.1 but a specialist head. Binary (safe / HAP),
softmax over the HAP class. The 64x size contrast inside one model
family is the point: it answers what you lose going smaller, at
near-zero inference cost. Scope is HAP only, so expect
underperformance on non-HAP attack families. That is signal about
the guardrail's coverage, not an adapter defect. The pinned config
carries no `id2label`; labels are named for the model's documented
purpose with index 1 as the malicious class, to be confirmed at
first load. Apache-2.0, ungated. Live-UNVERIFIED.

**Qwen3Guard-Gen 8B** is the 4B's sibling pin: same chat-template
contract, same `Safety:` prefill, same Strict-mode renormalization
over Safe / Unsafe / Controversial. It was probed and canaried
against the real weights during the October 2026 sweep. One known
dependency: if the Controversial label's mass splits across more
than one token, the first-token read can miss part of it; the
multi-token repair is tracked separately and, when it lands on the
4B adapter, this subclass inherits it. Apache-2.0, ungated.

**ShieldGemma 9B** is the 2B's sibling pin: same frozen combined
guideline, same single-forward-pass Yes/No scoring at the larger
checkpoint. Gated model (requires accepting the Gemma Terms of
Use on HuggingFace; accepted on the trial account).

**Nemotron Safety Guard 8B v3** is NVIDIA's Llama-3.1-based
moderation guard. It is prompted with NVIDIA's published taxonomy
template (23 categories, reproduced verbatim from the checkpoint's
own `inference_script.py`) rendered with the case text as the user
message and no agent response, through the model's chat template.
The adapter prefills `{"User Safety": "` so the next token is the
rating, and renormalizes the first-token logprobs over safe/unsafe.
NVIDIA Open Model License, ungated. Live-UNVERIFIED in this repo:
the adapter was staged during the sweep but its run window never
opened, so the first load must confirm the label-token resolution
on the real tokenizer before measured use.

**Llama Guard 4 12B** is Meta's multimodal guard, wired for the
text path only (peira's cases are text). It is prompted through
the checkpoint's own guard chat template and scored from the
first-token safe/unsafe logprobs, renormalized. The card documents
no probability; the score is peira's standard generative-guard
construction from the label logits. Gated (Llama 4 Community
License; the gate passes on the trial account). Live-UNVERIFIED
in this repo, on the same terms as Nemotron above.

**gpt-oss-safeguard 20B** is OpenAI's bring-your-own-policy
reasoner, served exactly as shipped (its MXFP4 weights are the
checkpoint's native format, not an applied quantization). Unlike
the rest of this family it generates: the model reasons in the
harmony analysis channel under a frozen policy (structured as
OpenAI's safeguard guide prescribes, with the verdict alphabet
fixed to one character, 0 or 1), and the adapter reads the
renormalized 0/1 logprobs at the verdict position in the final
channel. A generation with no final channel or no verdict in it
is an error, never a repaired score. The GPU load path passes
`device_map="cuda"` and so requires `accelerate` in the serving
environment. Apache-2.0, ungated. Probe-only at landing: the
sweep's pod probe failed on the missing `accelerate`, and the
probe is re-run before any measured use.
**Llama Guard 3 (1B and 8B)** is Meta's Llama-3.1 safety
classifier pair, aligned to the MLCommons hazards taxonomy (the
model card's table runs S1 Violent Crimes through S14 Code
Interpreter Abuse). Both checkpoints run prompt classification
the way Meta publishes it: the case text as a single user message
through the model's own chat template, unmodified — the taxonomy
and its definitions ship inside that template, so no policy text
is retyped in the adapter. The two shipped templates are not
identical: the 8B carries all 14 categories and renders string
message content, while the 1B carries the 13-category variant
(S1–S13, shorter names) and renders text-part content — a plain
string renders an empty conversation in the 1B template, so the
1B adapter wraps the case text in a text part, the shape its
template is written for. Each checkpoint is judged against the
policy Meta shipped with it.
The model answers with a first line of `safe` or `unsafe`; the
adapter renormalizes the first-token logprobs over the two label
tokens and takes P(unsafe) as the malicious score, the model card's
own classifier-score construction. The two sizes share one
implementation and differ only in their pinned checkpoint, so the
pair measures what the 8x size step buys inside one model family.
Both are **gated** under the Llama 3.1 Community License: accept
the license on each model's HF page and run
`huggingface-cli login` before first use.

Guardrail verdict mapping: content judged benign keeps the case's
expected decision (the guardrail vetoes nothing); content judged
malicious becomes the adapter's fixed veto label `"reject"`. That is
what makes ASR read as the guardrail's detection rate. See D-23.

**Separate suite: `safety_policy`.** Classifier guardrails are measured
on the separate safety-policy suite (`dataset/safety-policy/`), not on
v1 (D-30 superseded by D-34). On that suite the case labels *are* the
guardrail's native vocabulary (`allow` / `block`), so the veto
translation is dropped and the adapter emits native verdicts:
safe/benign → `allow`; unsafe/malicious → `block`, or
`block-<category>` for category classifiers (Llama Guard 4, WildGuard,
ShieldGemma) using the category slugs in
`dataset/safety-policy/SPEC.md` §2. Policy-adaptive Shieldstral
judges the content against the safety policy stated in the case prompt
(violation → `block`, otherwise `allow`). Self-reported confidence stays `|2p − 1|`
on every primitive. ASR on this suite therefore reads as the
*attacker's* success rate (evasion + false-positive induction). Lower
is better; the inverse of the D-23 detection-rate reading on the
v1 families; the two are never compared, which is why the suite is
separate. Full mapping table and the coarse-equivalence scoring rule
(`block-<x>` ≡ `block` for flip/eligibility; exact-category agreement
is a diagnostic) live in the suite spec.

## Structured-output LLM baselines

These are peira's LLM-as-judge adapters: each one makes a frontier model
return a typed decision through the provider's native constrained
decoding, rather than through a dedicated decision-model API like Jev.

One adapter per provider, one extra each. Install only what you need:

| Adapter | Extra | Dotted path | Default model | API key |
|---|---|---|---|---|
| OpenAI | `peira[openai]` | `peira.adapters.llm:OpenAIAdapter` | `gpt-5.6-luna` | `OPENAI_API_KEY` |
| Anthropic | `peira[anthropic]` | `peira.adapters.llm:AnthropicAdapter` | `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` |
| Google | `peira[google]` | `peira.adapters.llm:GoogleAdapter` | `gemini-3.8-flash` | `GOOGLE_API_KEY` |
| Moonshot (Kimi) | `peira[openai]` | `peira.adapters.llm:MoonshotAdapter` | `kimi-k3` | `MOONSHOT_API_KEY` |
| xAI (Grok) | `peira[openai]` | `peira.adapters.llm:XAIAdapter` | `grok-4` | `XAI_API_KEY` |
| DeepSeek | `peira[openai]` | `peira.adapters.llm:DeepSeekAdapter` | `deepseek-flash` | `DEEPSEEK_API_KEY` |
| Meta (Llama API) | `peira[openai]` | `peira.adapters.llm:MetaLlamaAdapter` | `Llama-4-Maverick-17B-128E-Instruct-FP8` | `META_API_KEY` or `LLAMA_API_KEY` |
| Zhipu (GLM) | `peira[openai]` | `peira.adapters.llm:ZaiAdapter` | `glm-4-plus` | `ZAI_API_KEY` |
| Mistral | `peira[openai]` | `peira.adapters.llm:MistralAdapter` | `mistral-large-2512` | `MISTRAL_API_KEY` |
| Qwen (Alibaba) | `peira[openai]` | `peira.adapters.llm:QwenAdapter` | `qwen3.8-max` | `DASHSCOPE_API_KEY` |
| OpenRouter gateway | `peira[openai]` | `peira.adapters.llm:OpenRouterAdapter` | `google/gemini-3.8-flash` | `OPENROUTER_API_KEY` |
| OpenRouter gateway (tool calling) | `peira[openai]` | `peira.adapters.llm:OpenRouterToolAdapter` | `google/gemini-3.8-flash` | `OPENROUTER_API_KEY` |

Default models are pinned per each vendor's versioning scheme
(verified 2026-09-27 against the vendor docs, re-verified per
release; Mistral and Qwen verified 2026-09-30). Anthropic is the
strongest case: from the 4.6 generation onward the dateless id IS the
pinned snapshot by vendor guarantee, with weights and config fixed
for the life of the id and updates shipped under new ids. Google's
3.x ids carry no `-001`-style suffix (that convention is 1.5/2.0-era);
Moonshot never published dated ids at all. Mistral and Qwen sit in
the middle: Mistral publishes dated snapshots, so the pin uses
`mistral-large-2512` rather than the rolling `mistral-large-latest`
alias; Qwen's `qwen-max` is a rolling alias, so the pin uses the
versioned `qwen3.8-max` id. The OpenAI pin is the honest weak spot:
Luna publishes no dated snapshots (the vendor docs render a
Snapshots section but list none), so `gpt-5.6-luna` is a best-effort
pin on the bare id. If OpenAI swaps the weights behind the name,
nothing in peira can detect it. The pin registry lives in
`peira.api_pins`: `get_pinned_model(adapter_name)` resolves the
exact id, `is_pinned_model()` checks one, and `peira doctor` warns
when an API adapter's default is not the pinned version. The
resolved version is sealed into the run artifact
(`adapter_version`, part of the analysis lock), so a pinned run is
reproducible and an unpinned one is visibly marked by its version
string.

You can still pass a different model explicitly with `model=`.
The adapter uses it verbatim and the version string records it
honestly, but a run on an unpinned model is not reproducible by
construction. Passing a model id the vendor has retired fails closed
with a `DeprecatedPinError` naming the replacement.

Each sends one JSON schema to the provider's native constrained
decoding (OpenAI strict `json_schema`, Anthropic forced tool choice on
older models / native `output_config.format` JSON schema on the newer
reasoning models, Gemini `responseSchema`), then revalidates the
response client-side.
The decision vocabulary is per-call. Peira cases use open label sets
(`deny`, `emergency-dept`, `choose A`, …), so the schema's decision
enum is built from the case input's explicit `options` list, not a
fixed list. Temperature
0, pinned seed where the provider supports one (Anthropic has no seed
parameter).

Confidence is the model's **self-reported** confidence: verbalized
confidence plus the decision-token logprob where the provider exposes
one (Anthropic exposes none). Self-reported confidence is uncalibrated
until measured; peira reports it, it does not vouch for it. Every
public label says "self-reported confidence" so no reader mistakes the
adapter's number for a calibrated probability. See D-22, D-23.

Refusals become abstentions with a reason, never silent: provider stop
reason first, then a refusal-prefix scan. If the output validates
against the schema, it is used; after one repair retry, persistent
validation failure is a terminal provider error. The
adapter never retries. The runner owns retries, and the SDKs are
configured for a single attempt so the runner's congestion signal stays
honest.

### Google auth transport

The `google-genai` SDK sends the API key in the `x-goog-api-key` HTTP
header. It has no query parameter mode. Any credential proxy or
connector in front of `GoogleAdapter` must use header placement for
the key. A query parameter placement is silently ignored by the SDK
and requests will not authenticate. On 2026-10-03 the connector was
registered for query parameter placement and live requests failed at
the transport layer ("Server disconnected"). The
`TestGoogleAuthTransport` test pins the SDK side of this contract
against the installed SDK. It does not verify the connector
registration itself.

### Google thinking disabled

`GoogleAdapter` sends `thinking_config=ThinkingConfig(thinking_budget=0)`
on every call. Thinking is off by construction. The evaluation design
requires it, since reasoning traces must not leak into the decision
channel, and `DeepSeekAdapter` and `QwenAdapter` enforce the same rule.
It is also a reliability fix. With thinking on, `gemini-3.8-flash`
intermittently spent the whole `max_output_tokens` budget on thought,
because thinking tokens count toward the cap in the Gemini API, and
truncated the JSON answer into a `MAX_TOKENS` finish. The v2 trial
measured this as a ~10-22% malformed rate before the halt. The budget
is recorded in the transcript's `request_shape` as `thinking_budget`
set to 0.

### Gemini 4 Argon (Google)

`gemini-4-argon` is Google's Gemini 4 flagship, listed Stable on the
official models page (page updated 2026-10-22), the new version of
the charted `gemini-3.8-flash` line. It runs through the same
`GoogleAdapter`: `response_schema` structured outputs and
`thinking_budget=0` on every call. Verified live 2026-10-23 by the
standard driver canary: 10 cases, all calls parsed, zero auth or
wire-shape errors, sealed under pricing version 2026-10-23.1. The
run also served on the free tier in trickle mode without quota
blockage, so no paid-credits gate was observed for this model.
Pricing carried is the introductory $2/$10 per 1M through
2026-11-30 (Google lists a step to $4/$20 from 2026-12-01, which
the pinned table does not model; secondary confidence pending
direct confirmation of the rate attribution).

### Anthropic workspace id

`AnthropicAdapter` accepts an optional `workspace_id`. Anthropic
issues two kinds of API keys. A workspace-scoped key belongs to one
workspace and needs nothing extra. An organization-level key belongs
to no workspace, and Anthropic rejects its Messages calls unless
every request names a workspace in the `anthropic-workspace-id`
header. When `workspace_id` is set, the adapter passes it to the SDK
as that default header on every request. When it is not set, the
adapter sends no workspace header, which is the right behavior for
workspace-scoped keys.

### Anthropic pin reconciliation (D3, 2026-09-30)

D3 asked whether the Anthropic baseline should be `claude-sonnet-5`,
Opus 5.5, or both. The reconciliation landed 2026-09-30:

- **The Opus 5.5 API id is `claude-opus-5-5`.** Verified against
  Anthropic's model docs, AWS Bedrock, and launch coverage (released
  2026-09-22). Pricing is $4/$20 per 1M.
- **The adapter supports it.** `AnthropicAdapter` auto-routes
  `claude-opus-5-5` to native `output_config.format` JSON-schema
  structured outputs (forced `tool_choice` returns a 400 on this
  model) and omits `temperature` (rejected with a 400 on the Opus 4.6
  generation and later). Pass `model="claude-opus-5-5"` explicitly to
  measure it.
- **Sonnet 5.5 exists.** Anthropic released Claude Sonnet 5.5 on
  2026-09-28 as `claude-sonnet-5-5` ($2/$10 per 1M). It gets the same
  routing and temperature handling as Opus 5.5.
- **The default pin is `claude-sonnet-5-5`.** D3 decided 2026-10-02:
  latest only. The pin moved from `claude-sonnet-5` to `claude-sonnet-5-5`
  (released 2026-09-28, $2/$10 per 1M).

### Anthropic pin (D3, 2026-10-02, latest model only)

The Anthropic default is **`claude-sonnet-5-5`** (Sonnet 5.5), per
David's latest-model directive ("latest Anthropic model only"). The
adapter uses native `output_config.format` JSON-schema structured
outputs and omits temperature. Pricing is $2/$10 per 1M tokens in the
pinned pricing table. The ceiling is never the default; frontier
comparisons are snapshots in time, never blended across versions.

**Honest caveats.** The adapter path is no longer mock-only.
`claude-sonnet-5-5` completed a full live trial run through this
adapter and its measured numbers are published. `claude-opus-5-5`
and `claude-fable-5-1` were canaried live through the adapter on
2026-10-14. One routing question is still open. Whether
`claude-haiku-5-5` accepts forced `tool_choice` is unverified,
because the temperature rejection fired first on every canary
call, and the canary after this fix settles it. Full rationale is
recorded in `docs/Decisions.md`.

### claude-fable-5-1 and claude-haiku-5-5 (Anthropic)

Both models reject the `temperature` field outright. An owner-run
canary on 2026-10-14 drove the real `AnthropicAdapter` (with the
workspace header) on real v2 trial cases, and every call for both
ids returned HTTP 400 with the provider message
"`temperature` is deprecated for this model." Both ids are
therefore in `_NO_TEMPERATURE_MODELS`, and the adapter sends no
temperature for them, matching Opus 5.5 and Sonnet 5.5.

`claude-fable-5-1` already routes to native `output_config.format`
structured outputs (see the D3 reconciliation above), so the
omission is its only wire change. `claude-haiku-5-5` is not in
`_STRUCTURED_OUTPUT_MODELS`. Whether it accepts forced
`tool_choice` is unknown, because the temperature rejection fired
first on every canary call. That question is settled by a canary
after this fix lands, not by assumption, and the adapter keeps
Haiku on the forced-tool path until then.

Pricing for `claude-haiku-5-5` is $0.10 per 1M input tokens and
$0.50 per 1M output tokens, verified 2026-10-14 against
Anthropic's official pricing page
(docs.claude.com/en/docs/about-claude/pricing). Anthropic prices
this model by prompt length, and prompts over 100,000 tokens pay
$0.50/$2.50 per 1M instead. The pinned table in
`python/peira/data/pricing.json` carries only the base tier,
because trial prompts run a few hundred tokens and the higher
tier is unreachable. Select either model by passing it
explicitly, for example
`--adapter 'peira.adapters.llm:AnthropicAdapter(model="claude-haiku-5-5")'`.

### gpt-5.6-luna (OpenAI)

`gpt-5.6-luna` is a reasoning model whose chat-completions endpoint
only accepts `temperature=1` (any other value 400s with
"Unsupported value: 'temperature' does not support 0.0 with this
model. Only the default (1) value is supported.", observed live
2026-10-03), so the adapter forces it via
`_MODEL_TEMPERATURE_OVERRIDES` and records the actual value in the
transcript and `decode_params`. Determinism is sacrificed for this
model, honestly recorded: the cache namespace, the request kwargs,
and the transcript all carry `1.0`. Models without an override entry
keep the constructor's `temperature=0.0` default.

The same endpoint also rejects `logprobs` outright (400:
"Unsupported parameter: 'logprobs' is not supported with this
model.", observed live 2026-10-03), so the adapter omits the field
for this model via `_NO_LOGPROBS_MODELS`, following the per-model
pattern `_MAX_COMPLETION_TOKENS_MODELS` established. The transcript records
`"logprobs": False`, the decision-token logprob track is `None`, and
confidence stays on the verbalized track. Models without an entry
keep sending `logprobs=True` as before.

### gpt-6.1-sol (OpenAI)

`gpt-6.1-sol` runs through the same `OpenAIAdapter` with
`model="gpt-6.1-sol"`. Its wire behavior was probed live on
2026-10-13 for this model on its own evidence (eleven canary calls
against `api.openai.com` on real v2 trial cases, both arms), not
inherited from the 5.6 family. All three Luna quirks hold for it.
`max_tokens` 400s ("Unsupported parameter: 'max_tokens' is not
supported with this model. Use 'max_completion_tokens' instead."),
so the model is in `_MAX_COMPLETION_TOKENS_MODELS`. `logprobs`
400s ("Unsupported parameter: 'logprobs' is not supported with
this model."), so it is in `_NO_LOGPROBS_MODELS` and its
decision-token logprob track is `None`. `temperature=0.0` 400s
("Unsupported value: 'temperature' does not support 0.0 with this
model. Only the default (1) value is supported."), so
`_MODEL_TEMPERATURE_OVERRIDES` forces 1.0 and determinism is
sacrificed for this model, honestly recorded in the transcript,
`decode_params`, and cache namespace. `seed=0` is accepted. With
that shape, eight of eight confirmation calls across four case
families returned schema-valid decisions in the option set with
finish reason `stop`. Reasoning tokens appear inside the
completion total on some calls (0 to 80 observed).

Published pricing is $2.00 per 1M input tokens and $10.00 per 1M
output tokens at the standard short-context tier (OpenAI pricing
page, verified 2026-10-13), and the pinned table in
`python/peira/data/pricing.json` carries the entry at that rate.
The adapter default stays `gpt-5.6-luna`. Select this model with
`--adapter 'peira.adapters.llm:OpenAIAdapter(model="gpt-6.1-sol")'`.

### gpt-6-luna (OpenAI)

`gpt-6-luna` runs through the same `OpenAIAdapter` with
`model="gpt-6-luna"`. Its wire behavior was probed live on
2026-10-13 for this model on its own evidence (seven canary calls
against `api.openai.com` on real v2 trial cases, both arms), not
inherited from the 5.6 family. All three Luna quirks hold for it.
`max_tokens` 400s ("Unsupported parameter: 'max_tokens' is not
supported with this model. Use 'max_completion_tokens' instead."),
so the model is in `_MAX_COMPLETION_TOKENS_MODELS`. `logprobs`
400s ("Unsupported parameter: 'logprobs' is not supported with
this model."), so it is in `_NO_LOGPROBS_MODELS` and its
decision-token logprob track is `None`. `temperature=0.0` 400s
("Unsupported value: 'temperature' does not support 0.0 with this
model. Only the default (1) value is supported."), so
`_MODEL_TEMPERATURE_OVERRIDES` forces 1.0 and determinism is
sacrificed for this model, honestly recorded in the transcript,
`decode_params`, and cache namespace. `seed=0` is accepted. With
that shape, four of four confirmation calls across two case
families returned schema-valid decisions in the option set with
finish reason `stop`. Reasoning tokens appear inside the
completion total on some calls (17 to 49 observed).

Published pricing is $0.10 per 1M input tokens and $0.50 per 1M
output tokens at the standard short-context tier (OpenAI pricing
page, verified 2026-10-13), and the pinned table in
`python/peira/data/pricing.json` carries the entry at that rate.
The adapter default stays `gpt-5.6-luna`. Select this model with
`--adapter 'peira.adapters.llm:OpenAIAdapter(model="gpt-6-luna")'`.

### gpt-5.6-terra (OpenAI)

`gpt-5.6-terra` runs through the same `OpenAIAdapter` with
`model="gpt-5.6-terra"`. Its wire behavior was probed live on
2026-10-13 for this model on its own evidence (seven canary calls
against `api.openai.com` on real v2 trial cases, both arms), not
inherited from its 5.6 siblings. All three Luna quirks hold for
it. `max_tokens` 400s ("Unsupported parameter: 'max_tokens' is
not supported with this model. Use 'max_completion_tokens'
instead."), so the model is in `_MAX_COMPLETION_TOKENS_MODELS`.
`logprobs` 400s ("Unsupported parameter: 'logprobs' is not
supported with this model."), so it is in `_NO_LOGPROBS_MODELS`
and its decision-token logprob track is `None`. `temperature=0.0`
400s ("Unsupported value: 'temperature' does not support 0.0 with
this model. Only the default (1) value is supported."), so
`_MODEL_TEMPERATURE_OVERRIDES` forces 1.0 and determinism is
sacrificed for this model, honestly recorded in the transcript,
`decode_params`, and cache namespace. `seed=0` is accepted. With
that shape, four of four confirmation calls across two case
families returned schema-valid decisions in the option set with
finish reason `stop`. Reasoning tokens appear inside the
completion total on some calls (0 to 24 observed).

Published pricing is $2.00 per 1M input tokens and $12.00 per 1M
output tokens at the standard short-context tier (OpenAI model
page, verified 2026-10-13), and the pinned table in
`python/peira/data/pricing.json` already carried the entry at
that rate. The adapter default stays `gpt-5.6-luna`. Select this
model with `--adapter
'peira.adapters.llm:OpenAIAdapter(model="gpt-5.6-terra")'`.

### gpt-6-astra (OpenAI)

`gpt-6-astra` runs through the same `OpenAIAdapter` with
`model="gpt-6-astra"`. Its wire behavior was probed live on
2026-10-13 for this model on its own evidence (seven canary calls
against `api.openai.com` on real v2 trial cases, both arms), not
inherited from the 5.6 family. All three Luna quirks hold for it.
`max_tokens` 400s ("Unsupported parameter: 'max_tokens' is not
supported with this model. Use 'max_completion_tokens' instead."),
so the model is in `_MAX_COMPLETION_TOKENS_MODELS`. `logprobs`
400s ("Unsupported parameter: 'logprobs' is not supported with
this model."), so it is in `_NO_LOGPROBS_MODELS` and its
decision-token logprob track is `None`. `temperature=0.0` 400s
("Unsupported value: 'temperature' does not support 0.0 with this
model. Only the default (1) value is supported."), so
`_MODEL_TEMPERATURE_OVERRIDES` forces 1.0 and determinism is
sacrificed for this model, honestly recorded in the transcript,
`decode_params`, and cache namespace. `seed=0` is accepted. With
that shape, four of four confirmation calls across two case
families returned schema-valid decisions in the option set with
finish reason `stop`. Reasoning tokens appear inside the
completion total on some calls (0 to 74 observed).

Published pricing is $10.00 per 1M input tokens and $50.00 per 1M
output tokens at the standard short-context tier (OpenAI pricing
page, verified 2026-10-13), and the pinned table in
`python/peira/data/pricing.json` carries the entry at that rate.
The adapter default stays `gpt-5.6-luna`. Select this model with
`--adapter 'peira.adapters.llm:OpenAIAdapter(model="gpt-6-astra")'`.

### Kimi K3 (Moonshot)

```bash
pip install "peira[openai]"
export MOONSHOT_API_KEY=...
peira run --adapter peira.adapters.llm:MoonshotAdapter --suite trial-demo
```

Kimi K3 (Moonshot AI, July 2026) is a 2.8T sparse mixture-of-experts
model (16 of 896 experts active per token) with a 1M-token context
window, the biggest open-weight release to date, under the Kimi K3
License, and at $3/$15 per 1M it is the self-host audience's flagship
model: the cheapest way to put a frontier-adjacent model on the board.
The adapter drives Moonshot's OpenAI-compatible endpoint
(`https://api.moonshot.ai/v1`, model id `kimi-k3`) with the same strict
JSON-schema request shape as `OpenAIAdapter`; the base URL is recorded
in the transcript's request shape, and the key is never logged.
`max_retries=0`. The runner owns retries, same as every other LLM
baseline.

The adapter has been exercised against the live API extensively.
The v2 trial ran 3,274 cases through it before halting, and a
targeted live check on 2026-10-12 verified the thinking fix with
three clean calls out of three. `json_schema` `response_format`
is honored, with clean parses whenever content is returned.
Thinking is disabled through `extra_body` with
`{"thinking": {"type": "disabled"}}` because kimi-k3 otherwise
spends the whole output budget on reasoning and returns empty
content. That failure halted the v2 trial at 3,274 of 4,701 cases.
Moonshot mandates temperature 1 while thinking is on and
temperature 0.6 while thinking is off, observed live on
2026-10-12. The adapter therefore forces temperature 0.6 for
`kimi-k3` and records both the temperature and the thinking
setting in the transcript. Determinism is sacrificed for this
model, honestly recorded. On `seed` and `logprobs` the API
400s when either field is sent, so the adapter omits both fields
from the request rather than negotiating. There is no
decision-token logprob track on this adapter, and the transcript
honestly records `"seed": None`. Mismatches surface as terminal
provider errors, not silent mismeasurement.

### Grok 4 (xAI)

```bash
pip install "peira[openai]"
export XAI_API_KEY=<your-key>
peira run --adapter peira.adapters.llm:XAIAdapter --suite trial-demo
```

Grok 4 is xAI's current flagship model. The adapter drives xAI's
OpenAI-compatible endpoint (`https://api.x.ai/v1`, model id `grok-4`)
with the same strict JSON-schema request shape as `OpenAIAdapter`;
the base URL is recorded in the transcript's request shape, and the
key is never logged. `max_retries=0`. The runner owns retries, same
as every other LLM baseline.

The adapter was built from xAI's published docs and verified
against the live API on 2026-10-02. All 40 verification calls parsed
against `grok-4` with zero auth or wire-shape errors, and the seed-0
handling from PR #355 held up. Whether `json_schema` `response_format`
(vs plain `json_object`) is honored for `grok-4` remains unverified
beyond successful parsing. Mismatches surface as terminal provider
errors, not silent mismeasurement.

### Grok 4.7 (xAI)

`grok-4.7` is xAI's current flagship (released 2026-09-21, 500K
context), the newest version of the charted `grok-4` line, at the
same $2/$6 per 1M rates (verified 2026-10-23 against xAI's official
models page, docs.x.ai/docs/models). It runs through the same
`XAIAdapter` and the same wire shape; `seed=1` is still sent because
xAI 400s on non-positive seeds. One wire note from the same xAI
docs page: models `grok-4.20` and newer silently ignore `logprobs`
and `top_logprobs`, so this model's confidence rides the verbalized
track (D-23) rather than the decision-token logprob track.

Access status (2026-10-23): the standard driver canary halted with
10 consecutive benign-arm errors, all HTTP 403 permission-denied:
the xAI team's credits are exhausted or its monthly spending limit
is reached. The wire itself was reached and authenticated (the 403
is a billing refusal, not an auth or wire-shape failure), so
`grok-4.7` is ready to measure the moment the account is funded.
Priced in `python/peira/data/pricing.json` under the 2026-10-23.1
refresh.

### DeepSeek V4.1 Flash (DeepSeek)

```bash
pip install "peira[openai]"
export DEEPSEEK_API_KEY=<your-key>
peira run --adapter peira.adapters.llm:DeepSeekAdapter --suite trial-demo
```

DeepSeek-V4.1 Flash is DeepSeek's current fast flagship (the
`deepseek-flash` alias; the legacy `deepseek-chat` / `deepseek-reasoner`
ids were discontinued 2026-07-24). The adapter drives DeepSeek's
OpenAI-compatible endpoint (`https://api.deepseek.com`; note: no
`/v1` suffix, per DeepSeek's docs) with `response_format`
`json_object`. DeepSeek's live API REJECTS the `json_schema`
`response_format` with a 400 ("This response_format type is
unavailable now"), observed live 2026-10-03. The schema (required keys,
types, decision enum) is inlined in the system prompt instead, so
schema adherence is best-effort, not server-enforced; the transcript
records the actual mode. The base URL is recorded in the transcript's
request shape, and the key is never logged.
`max_retries=0`. The runner owns retries, same as every other LLM
baseline.

Thinking is DISABLED (`thinking: {"type": "disabled"}`) per the
evaluation design: reasoning traces must not leak into the decision
channel.

Scale normalization: DeepSeek's best-effort `json_object` mode
sometimes emits `confidence`/`score` on a 0-100 scale despite the
schema requiring 0-1 (observed 2026-10-04). The adapter normalizes
values in (1, 100] by dividing by 100 at parse time, before
validation; values in [0, 1] pass through, and out-of-range values
are still rejected.

Honest caveat: the `json_object` shape has NOT yet been exercised
against the live API. Verify before any measured run. Mismatches
surface as terminal provider errors, not silent mismeasurement.

### DeepSeek V4 Pro (DeepSeek)

`deepseek-v4-pro` is DeepSeek's flagship V4 model (snapshot 0813),
alongside the `deepseek-flash` alias on DeepSeek's API, which lists
exactly these two models. It runs through the same `DeepSeekAdapter`
and the same wire shape as the flash alias, with thinking disabled
by the adapter per the evaluation design (reasoning traces must not
leak into the decision channel). Verified live 2026-10-23 by the
standard driver canary: 10 cases, all calls parsed, zero auth or
wire-shape errors, sealed under pricing version 2026-10-23.1.
Pricing is peak $1.32/$3.96 per 1M in the pinned table, the
deepseek-flash convention of planning on peak rates. Wire quirks
observed live: none beyond the flash line's.

### Llama 4 Maverick (Meta Llama API)

```bash
pip install "peira[openai]"
export META_API_KEY=<your-key>
peira run --adapter peira.adapters.llm:MetaLlamaAdapter --suite trial-demo
```

Llama-4-Maverick-17B-128E-Instruct-FP8 via Meta's Llama API. The
adapter drives the OpenAI-compatible endpoint
(`https://api.llama.com/compat/v1`; note the `/compat/v1` path;
Meta's native API at `/v1` uses a different response shape) with the
same strict JSON-schema request shape as `OpenAIAdapter`; the base URL
is recorded in the transcript's request shape, and the key is never
logged. `max_retries=0`. The runner owns retries, same as every other
LLM baseline.

Honest caveat: the adapter is built from Meta's published docs, not
the live API. Meta documents that some OpenAI client features are NOT
supported on the compat endpoint; whether `json_schema`
`response_format`, `seed`, and `logprobs` are honored is unverified.
Verify against the live API before any measured run; mismatches
surface as terminal provider errors, not silent mismeasurement.

### GLM-4 Plus (Zhipu)

```bash
pip install "peira[openai]"
export ZAI_API_KEY=<your-key>
peira run --adapter peira.adapters.llm:ZaiAdapter --suite trial-demo
```

GLM-4 Plus is Zhipu's current paid flagship in the GLM-4 family. The
adapter drives Zhipu's OpenAI-compatible endpoint
(`https://open.bigmodel.cn/api/paas/v4`, model id `glm-4-plus`) with
a `json_object` request shape (not the strict JSON-schema shape):
Zhipu's endpoint does not support `json_schema` `response_format`
and silently ignores it, so the adapter inlines the schema
(required keys, types, decision enum) in the system prompt.
Schema adherence is best-effort, not server-enforced. The base URL
is recorded in the transcript's request shape, and the key is never
logged. `max_retries=0`. The runner owns retries, same as every
other LLM baseline.

Auth note: Zhipu also supports JWT auth built from the API key ID
plus secret, but the OpenAI-compatible endpoint accepts the API key
directly as the Bearer token (per Zhipu's own OpenAI-compat docs),
which is what this adapter uses.

Scale normalization. GLM-4 Plus sometimes emits `confidence`/`score`
on a 0-100 scale despite the prompt-inlined schema requiring 0-1
(observed 2026-10-07 in the v2 trial, where nearly all zai errors
were this shape). The adapter normalizes values in (1, 100] by
dividing by 100 at parse time, before validation, the same repair
DeepSeekAdapter runs. Values in [0, 1] pass through, and out-of-range
values are still rejected.

The adapter was built from Zhipu's published docs and
verified against the live API on 2026-10-02. All 40 verification calls
parsed against `glm-4-plus` with zero auth or wire-shape errors, and the
`json_object` plus prompt-inlined schema shape from PR #367 held up.
Whether `seed` and `logprobs` are honored for `glm-4-plus` remains
unverified beyond successful parsing. Mismatches surface as terminal
provider errors, not silent mismeasurement.

### GLM-5.3 (Zhipu)

`glm-5.3` is Zhipu's current flagship (live on the API since
2026-08-14), the newest version of the charted `glm-4-plus` line. It
runs through the same `ZaiAdapter` against the same
`https://open.bigmodel.cn/api/paas/v4` endpoint, with `json_object`
response format and the prompt-inlined schema. GLM-5.3 reasoning is
always on and cannot be disabled; the adapter sends no thinking
parameter and the config-only wire held. Verified live 2026-10-23
by the standard driver canary: 10 cases, all calls parsed, zero
auth or wire-shape errors, sealed under pricing version
2026-10-23.1. The canary measured ~302 output tokens per call
against the sibling's ~91, the always-on reasoning showing as
expected, with no truncation. Pricing is $1.40/$4.40 per 1M in the
pinned table (secondary-sourced, the `glm-4-plus` convention).

### Mistral Large 3 (Mistral)

```bash
pip install "peira[openai]"
export MISTRAL_API_KEY=<your-key>
peira run --adapter peira.adapters.llm:MistralAdapter --suite trial-demo
```

Mistral Large 3 is Mistral's open-weight flagship (Apache 2.0), a
675B sparse mixture-of-experts model with a 256K context window. The
adapter drives Mistral's OpenAI-compatible endpoint
(`https://api.mistral.ai/v1`, model id `mistral-large-2512`, the
December 2025 dated snapshot behind the rolling
`mistral-large-latest` alias) with the same strict JSON-schema
request shape as `OpenAIAdapter`; the base URL is recorded in the
transcript's request shape, and the key is never logged.
`max_retries=0`. The runner owns retries, same as every other LLM
baseline. At $0.50/$1.50 per 1M it is the cheapest frontier-adjacent
model on the board.

Two honest caveats: the adapter is built from Mistral's published
docs and third-party parameter surveys, not the live API. Mistral
names the seed parameter `random_seed` (not `seed`), which the
adapter sends inside `extra_body` (the OpenAI SDK rejects unknown
top-level kwargs). `logprobs` is undocumented for chat completions, so
the adapter omits it rather than negotiating. There is no
decision-token logprob track on this adapter, and the transcript
records the seed under the wire name it was sent with.
**Live-UNVERIFIED**: no real call has been made from this
environment as of 2026-09-30. Verify against the live API before any
measured run; mismatches surface as terminal provider errors, not
silent mismeasurement.

### Qwen3.8-Max (Alibaba)

```bash
pip install "peira[openai]"
export DASHSCOPE_API_KEY=<your-key>
peira run --adapter peira.adapters.llm:QwenAdapter --suite trial-demo
```

Qwen3.8-Max is Alibaba's August 2026 flagship, a 2.4T sparse
mixture-of-experts model with a 1M-token context window. The adapter
drives Alibaba's DashScope OpenAI-compatible endpoint
(`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, model id
`qwen3.8-max`; the `qwen-max` alias is rolling, so the pin uses the
versioned id) with the same strict JSON-schema request shape as
`OpenAIAdapter`; the base URL is recorded in the transcript's
request shape, and the key is never logged. `max_retries=0`. The
runner owns retries, same as every other LLM baseline. At $2.00/$6.00
per 1M on the international endpoint it is priced well below the
Western frontier tier.

Two honest caveats: the adapter is built from Alibaba's published
docs and third-party parameter surveys, not the live API. DashScope
requires `enable_thinking` to be set explicitly on every request
(the endpoint rejects requests that omit it), and Qwen's
hybrid-thinking models honor `json_schema` `response_format` only
with thinking disabled, so the adapter sends
`enable_thinking: false` via `extra_body` on every call. Thinking is
off by construction, never by omission, and the transcript records
it. Regional note: DashScope keys are minted per host; a key issued
for the China endpoint (`dashscope.aliyuncs.com`) will not
authenticate against the international endpoint this adapter uses.
**Live-UNVERIFIED**: no real call has been made from this
environment as of 2026-09-30. Verify against the live API before any
measured run; mismatches surface as terminal provider errors, not
silent mismeasurement.

### OpenRouter gateway

```bash
pip install "peira[openai]"
export OPENROUTER_API_KEY=<redacted>
peira run --adapter peira.adapters.llm:OpenRouterAdapter --suite trial-demo
# any OpenRouter model id (vendor/model):
peira run --adapter 'peira.adapters.llm:OpenRouterAdapter(model="anthropic/claude-sonnet-4.6")' --suite trial-demo
```

`OpenRouterAdapter` is the unified gateway for structured-output LLM
baselines. One adapter reaches any of OpenRouter's 400+ models through
`https://openrouter.ai/api/v1` with the same strict JSON-schema request
shape as `OpenAIAdapter`. New one-off or exploratory models go through
the gateway. Per-provider adapters stay reserved for models peira
measures repeatedly. The default model is `google/gemini-3.8-flash`,
the same model family as the Google baseline's default reached through
the gateway, so the direct-vs-gateway comparison is the default
measurement. `max_retries=0`. The runner owns retries, same as every
other LLM baseline.

OpenRouter translates the `json_schema` `response_format` to each
provider's native structured-output mechanism. The adapter deliberately
does NOT use OpenRouter's `models` fallback array. A fallback would
silently substitute a different model mid-run, breaking the cache
namespace and the measurement identity. One adapter instance is one
pinned model id, always. App-identification headers (`HTTP-Referer`,
`X-Title`) follow OpenRouter's documented convention.

The adapter is built from OpenRouter's published docs. The translated
schema path was live-verified for the default model below. Schema
support for other model ids remains unverified, and the live test did
not verify `seed` or `logprobs`, which stay unverified per-model
behaviors. Verify a new model id against the live API before any
measured run. Mismatches surface as terminal provider errors or failed
schema validation, not silent mismeasurement.

Live-verified 2026-10-01 for the default model `google/gemini-3.8-flash`.
Forty calls (a 20-case trial slice spanning `score_anchoring` and
`negation_games`, benign and attacked arms) against
`POST https://openrouter.ai/api/v1/chat/completions` returned 38
schema-valid decisions with zero 401/403/400 responses. The
strict `json_schema` response shape was honored on the translated path,
and the adapter's app-identification headers (`HTTP-Referer`,
`X-Title`) were sent. The two failures were attacked-arm cases where
the model emitted no JSON object even after the repair retry, and no
provider-side content-filter refusal was observed. Other model ids
through the gateway remain unverified until smoke-tested.

Two newer gateway versions were added by the 2026-10-23 API version
refresh, verified 2026-10-23 against the live OpenRouter model
catalog and priced in `python/peira/data/pricing.json`:
`inception/mercury-3` ($0.10/$0.35 per 1M; Inception's successor
chat model to the charted `inception/mercury-2.5` row, whose access
for existing users ends 2026-11-15) and
`inclusionai/ling-3.1-flash` ($0.075/$0.225 per 1M; the successor to
the charted `inclusionai/ling-3.0-flash` row, released 2026-10-02).
Both ride the same `OpenRouterAdapter` wire; the standard driver
canary is each one's first measured exercise.

### OpenRouter gateway, tool-calling variant

```bash
pip install "peira[openai]"
export OPENROUTER_API_KEY=<redacted>
peira run --adapter 'peira.adapters.llm:OpenRouterToolAdapter(model="inclusionai/ling-3.0-flash")' --suite trial-demo
```

`OpenRouterToolAdapter` is the forced-tool-calling twin of
`OpenRouterAdapter`. It uses the same gateway endpoint, auth, and
app-identification headers. The peira schema travels as a forced
`peira_decision` function tool instead of `response_format` JSON
schema. Some gateway models ignore the translated schema and answer
in free text. In October 2026, `inclusionai/ling-3.0-flash` and
`inclusionai/ling-3.0-flash-vl` ignored `response_format` on about
22% of trial calls. Forced tool calling is the vendor-blessed
structured path for those models. The adapter name differs from
`openrouter-structured` on purpose. The name is part of the runner's
cache namespace. Tool-calling runs therefore never share cache
entries with `response_format` runs of the same model id.

The verdict mapping has two lossy points. When the model answers in
text instead of calling the function, the shared JSON extractor
parses the text as a fallback. When validation fails, two cheap
repairs run before the repair retry. Confidence and score values on
a 0-100 scale are divided by 100. The `rereason` and `re reason`
key typos are aliased to `reason`. Both repairs only fire after a
validation failure and are visible in the transcript.

Live-verified 2026-10-10. Twenty calls (10-case trial canaries for
`inclusionai/ling-3.0-flash` and `inclusionai/ling-3.0-flash-vl`,
benign and attacked arms) returned 20 successes and 0 errors. Two
attacked-arm errors on the VL canary were recovered through the
repair path.

### MiniMax M3 (MiniMax)

```bash
pip install peira
export MINIMAX_API_KEY=<redacted>
peira run --adapter peira.adapters.llm:MiniMaxAdapter --suite trial-demo
```

MiniMax-M3 is MiniMax's flagship reasoning model (1M context). The
adapter drives MiniMax's OpenAI-compatible endpoint
(`https://api.minimax.io/v1`, model id `MiniMax-M3`, case-sensitive)
over plain HTTPS with the standard library (`urllib`), deliberately
not the `openai` SDK package, whose HTTP client bypassed the Hatch
egress proxy's vault-surrogate exchange. No third-party package is
needed, so the adapter lives in the base `peira` tier. The runner owns
retries, same as every other LLM baseline. At ~$0.30/$1.20 per 1M it
is priced well below the Western frontier tier.

The request shape differs from every other LLM baseline in one
load-bearing way. MiniMax does not reliably support `response_format`
with JSON schema on the OpenAI-compatible endpoint (undocumented
there, and third-party probing found it unreliable across M3/M2.x).
The vendor-blessed structured path is tool calling, so the adapter
defines a `peira_decision` function carrying the peira schema and
forces the model to call it (`tool_choice` pinned to the function).
The verdict arrives pre-parsed in the tool-call arguments and flows
through the shared schema validation. When the model answers in text
instead, the text path (think-stripped, then the shared JSON
extractor) is the fallback. The schema is also inlined in the system
prompt, so the model sees the required keys before reading the tool
definition. The transcript records `response_format:
tool_call:peira_decision:forced`, honestly naming the mechanism.

M3's thinking cannot be reliably disabled, so reasoning is handled
two ways. The adapter sends `thinking: {"type": "disabled"}` at the
payload top level (honored on M3) and strips `<think>...</think>`
blocks from every text surface defensively, so a reasoning leak can
never corrupt decision parsing. Any `reasoning_content` field is
recorded in the transcript but never parsed. MiniMax exposes no token
logprobs, so there is no decision-token logprob track. `logprobs` is
omitted and the transcript records `"logprobs": False`. Confidence
stays on the verbalized track (D-23).

Error mapping follows the shared convention for HTTP statuses
(429/5xx retryable, 400/401/403 terminal), with one addition. A
MiniMax native error envelope (`base_resp.status_code`) arriving
inside an HTTP 200 is mapped defensively. 1002 (rate limit) becomes
429 so the runner backs off and retries. 1004 and 2049 (auth), 1008
(insufficient balance), 1026 (content flagged), and 2013 (invalid
parameters) become terminal.

Verified live on 2026-10-08 and 2026-10-09 by the full v2 trial run
(4,701 cases sealed). The forced tool-call path, the
`thinking: disabled` flag, and `seed` passthrough were all exercised
end-to-end against the real endpoint.

### MiniMax M3.1 Flash (MiniMax)

`MiniMax-M3.1-Flash` (launched 2026-10-19; the id is case-sensitive)
is MiniMax's newest model, the new version of the charted M3 line.
It runs through the same `MiniMaxAdapter` and the same forced
tool-call wire, with one per-model difference observed live
2026-10-23: M3.1-Flash requires adaptive thinking and rejects
`thinking.type="disabled"` with a 400, so the adapter omits the
thinking flag for this id and reasoning runs in the vendor's
default adaptive mode. Verified live 2026-10-23 by the standard
driver canary: 10 cases sealed with zero errors (18 of 20 calls
parsed; the two parse failures are recorded as measurement data,
not errors). Pricing is $0.15/$0.60 per 1M in the pinned table
(secondary-sourced, corroborated by OpenRouter's live catalog).

#### Cheap-model pilot set

One cheap model per major lab, plus the most discounted structured-output
models on the gateway, reachable on a single OpenRouter credits
balance. This is the pilot-run set for gathering real measurement data
before the flagship run. Every ID was verified 2026-10-03 against
OpenRouter's live model list with structured-output support advertised.

```python
from peira.adapters.llm import OpenRouterAdapter
from peira.api_pins import get_openrouter_cheap_model

adapter = OpenRouterAdapter(model=get_openrouter_cheap_model("or-mistral-nemo"))
```

| Key | OpenRouter model id | Lab | $/1M in/out | Est. v2 cost |
|-----|---------------------|-----|-------------|--------------|
| `or-mistral-nemo` | `mistralai/mistral-nemo` | Mistral | $0.02/$0.03 | ~$0.50 |
| `or-deepseek-flash` | `deepseek/deepseek-v4-flash` | DeepSeek | $0.03/$0.06 | ~$0.75 |
| `or-gpt-oss-20b` | `openai/gpt-oss-20b` | OpenAI | $0.02/$0.09 | ~$0.70 |
| `or-qwen-flash` | `qwen/qwen3.7-flash` | Qwen | $0.03/$0.13 | ~$1.00 |
| `or-llama-8b` | `meta-llama/llama-3.1-8b-instruct` | Meta | $0.05/$0.08 | ~$1.15 |
| `or-gemma-4b` | `google/gemma-3-4b-it` | Google | $0.05/$0.10 | ~$1.25 |
| `or-glm-flash` | `z-ai/glm-4.7-flash` | Zhipu | $0.06/$0.40 | ~$2.75 |
| `or-kimi-k2.5` | `moonshotai/kimi-k2.5` | Moonshot | $0.45/$2.25 | ~$17 |
| `or-grok-4.3` | `x-ai/grok-4.3` | xAI | $1.25/$2.50 | ~$32 |
| `or-claude-haiku` | `anthropic/claude-haiku-4.5` | Anthropic | $1.00/$5.00 | ~$39 |
| `or-mercury-2.5` | `inception/mercury-2.5` | Inception | $0.04/$0.15 | ~$1.30 |
| `or-qwen3-235b` | `qwen/qwen3-235b-a22b-2507` | Qwen | $0.0875/$0.35 | ~$3.00 |
| `or-ling-flash-vl` | `inclusionai/ling-3.0-flash-vl` | inclusionAI | $0.021/$0.0616 | ~$0.60 |
| `or-solar-pro4` | `upstage/solar-pro4` | Upstage | $0.09/$0.36 | ~$3.05 |
| `or-ling-flash` | `inclusionai/ling-3.0-flash` | inclusionAI | $0.021/$0.063 | ~$0.60 |

The whole set runs roughly $105. Each model id needs a live smoke test before
any measured run. Pricing lives in `python/peira/data/pricing.json`
under the same IDs.

## TypeSafe Jev

No extra needed (stdlib transport). Set `TYPESAFE_API_KEY`:

```bash
export TYPESAFE_API_KEY=...
peira run --adapter peira.adapters.jev:JevAdapter --suite trial-demo
```

Jev is a decision-model API, not a chat model: the adapter sends the
case prompt as `state` plus named typed questions (each question
carries `instructions`; choice and score questions also carry
`criteria`) and reads back `choice`
(choice), `score` (score), or `abstain` (abstain) answers. The score
question uses five described levels ("clearly the wrong decision" …
"clearly the right decision"), not raw numbers. The adapter supports
two pinned snapshots, `jev-1.13.0` and `jev-1.14.0`, and `jev-1.13.0`
remains the default when no model is named. Construction rejects
floating tags such as `jev-latest` and `jev-preview`, along with any
other model id, so a run always names one exact snapshot. Each
instance records its snapshot as its adapter version and caches under
that snapshot's own namespace, so the two snapshots can be measured
side by side without sharing state. Reported pricing is $0.042 per
1M input tokens with output free. The 1.13.0 rate is secondary-sourced
via gateway announcements and carries that caveat in the pinned table
in `python/peira/data/pricing.json`. The 1.14.0 rate was verified
against the TypeSafe models page on 2026-10-14, and an owner probe
that same day called the live API with model `jev-1.14.0` and received
HTTP 200 with the response model field naming `jev-1.14.0`. Access is
gated; without a key the error tells you exactly where to get one.
429/529/5xx and transport timeouts surface as retryable provider
errors for the runner. 401/422 are terminal. One live-API quirk,
observed 2026-10-07 in the v2 trial, where the abstain answer returns its
probability under TypeSafe's own field name (`noul`) rather than the
documented key, so the adapter reads the documented key first and
falls back to the native field. The adapter ran the full v2 trial
against the live API (4,701 cases sealed). See D-24.

## OpenAI Decisions

No extra needed (stdlib transport). Set `OPENAI_API_KEY` first.

```bash
export OPENAI_API_KEY=<redacted>
peira run --adapter peira.adapters.openai_decisions:OpenAIDecisionsAdapter --suite trial-demo
```

OpenAI's Decisions API (public beta) is a decision-model endpoint in
the same family as Jev. The adapter sends the case prompt as `input`
plus named typed questions and reads back typed answers. A `choice`
answer carries the chosen option, a per-option probability
distribution, and a separate confidence field. A `score` answer
carries a probability-weighted average over the same five-level
rubric the Jev adapter uses ("clearly the wrong decision" …
"clearly the right decision") plus per-level probabilities. A
`predicate` answer carries a probability, and the abstain primitive
is mapped onto it (probability at or above 0.5 is the deliberate
decision label `abstain`. Below it the decision is the `other`
placeholder, exactly as on the Jev wire). Any question can instead
return a `refusal` answer while the other questions in the request
are still answered, and a refusal on the question that carries the
primitive maps to an abstained output. Score arms send two questions
in one request, the rubric score and the paired decision, and the
reported decision and confidence come from the paired choice answer.
The question text (instructions, rubric, label construction) is the
Jev adapter's unchanged, so the two wires see identical decision
spaces. The model is pinned to `gpt-6-luna`, the only model the
endpoint supports, and any other model string is rejected at
construction. Pricing is $0.10 per 1M input tokens with no output
charge (the wire reports `output_tokens` 0), and the pinned table's
existing `gpt-6-luna` entry computes the cost exactly. 408/409/429/
529/5xx and transport timeouts surface as retryable provider errors
for the runner, 400/401/403/404/422 are terminal, and the provider's
error code rides in the error message so a billing-side 429 reads as
what it is. The choice and score shapes were exercised live on
2026-10-14 (three probe calls on real v2 cases, all 200s). The
predicate and refusal shapes are documented in the API reference and
are first exercised by the post-merge canary. One beta caveat
applies. OpenAI publishes no SLA or schema freeze for this endpoint,
so the adapter
pins the wire-shape version into its cache namespace (`v1`) and a
field rename lands in this one module.

General availability (2026-10-22): OpenAI took the Decisions API to
GA for all customers, adding voice and image modalities, up to 400
questions per request, prompt caching, and geographic routing. GA
pricing is $0.10 per 1M input tokens with no output charge. The
charted `gpt-6-luna` row on this wire was measured on the beta
surface; a re-canary against the GA surface is the standard
verification that the wire still behaves as measured.

## OpenRouter Decisions

No extra needed (stdlib transport). Set `OPENROUTER_API_KEY` first.

```bash
export OPENROUTER_API_KEY=<redacted>
peira run --adapter peira.adapters.openrouter_decisions:OpenRouterDecisionsAdapter --suite trial-demo
```

OpenRouter serves hosted decision models behind a System One API
(`POST https://openrouter.ai/api/v1/systemone`) that takes the Jev
request shape: a `model`, a `state`, and named typed questions.
`OpenRouterDecisionsAdapter` is the Jev adapter's shape on this
surface: the question text (instructions, rubric, label
construction) is the Jev adapter's unchanged, so every wire in the
decision family sees identical decision spaces. Answers parse the
same way: `choice` (choice), `score` (score), `noul` (abstain).

The pinned model is `microsoft/microsoft-decision-1`, Microsoft's
hosted decision model (a Qwen3.5-9B post-train, weights not
distributed), served by Azure through OpenRouter since 2026-10-09 at
$0.042 per 1M input tokens with output free, the same rate as its
Foundry list price. Pinning caveat: the served id carries no version
suffix and Microsoft has stated it will rebase the model under the
same product name, so a run under this id names the route and the
run date, not immutable weights; the sealed artifact's run date is
part of this row's identity. Any other model string is rejected at
construction.

The adapter is live-UNVERIFIED at authoring time (2026-10-23). Its
first measured exercise is the standard driver canary. 408/429/
529/5xx and transport timeouts surface as retryable provider errors
for the runner; 400/401/403/404/422 are terminal.

## Laya

```bash
pip install laya
peira run --adapter peira.adapters.laya:LayaAdapter --suite trial-demo
```

Laya (Convai Innovations, Sept 2026) is the open-source Jev
alternative: a 421M ModernBERT-based decision classifier (Apache 2.0)
run locally: no API key, no gating. The adapter sends the case prompt
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
published API and hasn't been exercised against the real package yet.
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
reuses the Jev wire logic wholesale: the same `{"model", "state",
"questions"}` requests and `choice`/`score`/`noul` answers, including
the abstain-to-`"noul"` boundary mapping. The differences from Jev:
no API key (local server, no auth header), `api_url=` pointing at the
server (default `http://127.0.0.1:8008/v1/systemone`, kev.serve's
documented port), and the pinned model id.

Seven sizes, pinned by exact Hub id (backbones per each repo's Hub
tags, verified live against the `jaredpalmer/kev` collection on
2026-09-25), selectable via `model=` (short names accepted):

- `jaredpalmer/kev-0.5b`: Qwen2.5-0.5B, the original prototype;
  its own card says it is superseded by 0.8B/4B/9B. Kept for
  reproducibility.
- `jaredpalmer/kev-0.6b`: Qwen3-0.6B, previous generation, no
  longer developed. Kept for reproducibility.
- `jaredpalmer/kev-0.8b`: Qwen3.5-0.8B, current family, small arm.
- `jaredpalmer/kev-4b` (default): Qwen3.5-4B, current family.
- `jaredpalmer/kev-8b`: Qwen3-8B, previous generation, no longer
  developed. Kept for reproducibility.
- `jaredpalmer/kev-9b`: Qwen3.5-9B, current family.
- `jaredpalmer/kev-27b`: Qwen3.8-27B, newest checkpoint (2026-09-24),
  the biggest available size, large arm.

The current generation is Qwen3.5-based (0.8b / 4b / 9b) plus the
newest Qwen3.8-based 27b. Floating tags like `kev-latest` are rejected
at construction; each size gets its own `cache_namespace`.

A server that cannot be reached is a terminal provider error whose
message tells you exactly how to start it. The runner never retries
a missing local server. HTTP error statuses keep their status codes
for the runner's classifier. The model is local and self-hosted, so
cost is $0. One honest caveat: the adapter is built from kev's
published docs and hasn't been exercised against a live `kev.serve`
instance. If the server answers differently than the shared
TypeSafe-shaped contract, you'll see terminal provider errors, not
silent mismeasurement.

## SemIf

```bash
# Clone github.com/theoleecj/semif, create the venv, then:
pip install -e '.[test]'
peira run --adapter peira.adapters.semif:SemifAdapter --suite trial-demo
```

SemIf (TheoLeeCJ, MIT; formerly OpenJev, renamed ~2026-09-18, ~4.3k
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
("Should this case be abstained?"). SemIf's CLI has no `"noul"` wire
type, so there is no boundary translation here; the `"yes"`
probability is the abstain signal with the same >= 0.5 threshold the
Jev-family adapters use. The score primitive is a five-level rubric
question plus a paired decision row, mirroring the Jev adapter's
two-question score shape.

Every CLI failure (missing binary, timeout, nonzero exit, unparseable
output) is a terminal provider error with no status code. The runner
never retries a broken CLI. The model is local and self-hosted, so
cost is $0. Two honest caveats: the CLI loads the 4B weights per
process, so per-call spawning is correct but slow on cold starts
(`timeout_s` defaults to 600s), and the adapter hasn't been exercised
against a real `semif-score` install. The output-row key shapes are
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
exposes Jev-compatible `POST /v1/systemone`: the same `{"model",
"state", "questions"}` → `{"answers": {...}}` shape, with the same
typed `choice`/`score`/`noul` questions including the
abstain-to-`"noul"` boundary mapping. The adapter reuses the
self-hosted wire plumbing it shares with Kev: configurable `api_url=`
(default `http://localhost:8000/v1/systemone`), plus optional Bearer
auth. The project's README documents `OPENJEV_API_KEY`, and the
adapter sends it as `Authorization: Bearer <redacted>` when set
(`api_key=` or the env var); without it, requests go keyless. The key
never appears in transcripts.

The model is `Qwen/Qwen3.6-35B-A3B` MoE (verified against the
project's published BoolQ eval report, 2026-09-18) and is baked into
the server deployment, so the adapter accepts only that id.
anything else is rejected at construction. The model is local and
self-hosted, so cost is $0. One honest caveat: the adapter hasn't been
exercised against a live openjev-sglang deployment. Field names are
our best reading of the project's documented request examples, and a
server that answers differently produces terminal provider errors,
not silent mismeasurement. The project's published parity number
(95.5% vs Jev 96.3% on the aligned subset, overlapping CIs) is their
claim, not a peira measurement.

## Von

```bash
pip install von-sdk
von serve --port 8000 --noul-decision raw --on-overflow refuse
peira run --adapter peira.adapters.von:VonAdapter --suite trial-demo
```

Von (wfzyx, Apache 2.0) is an open-source non-autoregressive System
One decision model. A 395M ModernBERT-large encoder plus an
option-marker scoring head answers typed choice, score, and noul
questions in one forward pass, with a probability over every option
and no token generation. `von serve` exposes a TypeSafe-compatible
`POST /v1/systemone` endpoint and runs on CPU through OpenVINO, so
the adapter reuses the self-hosted wire plumbing it shares with Kev
and openjev-sglang. The differences are the pinned model id, the
default endpoint (`http://127.0.0.1:8000/v1/systemone`), and optional
Bearer auth.

The model is pinned to `von-1.3.0`, the checkpoint `von serve`
serves (`wfzyx/von` on the Hub; its model card identifies it as
Von 1.3, an engine release whose weights are unchanged from 1.2).
The checkpoint is baked into the server deployment, so any other
model id is rejected at construction, and the pinned id namespaces
the runner cache. The server fetches the weights from the Hub on
first use. Von takes no auth unless the server was started
with `VON_API_KEY` set. Pass the same key to the adapter with
`api_key=` or the `VON_API_KEY` environment variable and requests
carry it as a Bearer token to whatever endpoint `api_url` names,
so a remote deployment should be reached over HTTPS or a tunnel.
The key never appears in transcripts.

Two server settings matter for measurement, and the adapter cannot
see either of them, so both belong in the serve command:

- Noul decision rule. The server default passes the abstain
  probability through a band rule that pushes every returned value
  outside the 0.2 to 0.8 range. The abstain decision is unchanged,
  but the confidence derived from the returned value is inflated.
  Serve with `--noul-decision raw` so peira measures the calibrated
  posterior.
- State truncation. The server default middle-truncates a state
  that exceeds its token window, and the answer then measures the
  truncated text. Serve with `--on-overflow refuse` so an oversize
  state fails with a 422 instead.

A server that cannot be reached is a terminal provider error whose
message tells you how to start it. The runner never retries a
missing local server. HTTP error statuses keep their status codes
for the runner's classifier. The model is local and self-hosted, so
cost is $0.

Canary record (2026-10-15): the adapter was exercised end to end
against a real `von serve` on this project's trial VM (CPU device,
the two serve flags above). All three primitives returned valid
outputs. It also produced one operational note: the server's first
request loads the weights lazily and can exceed the adapter's 60
second default timeout on a loaded CPU box, so a trial on shared
hardware should pass a larger `timeout_s`.

Pin history: the adapter was first written with a `von-1.1.0` pin.
A pre-merge checkpoint review established that no servable von-1.1
checkpoint exists. The SDK accepts `von-1.1` only as an alias that
resolves to the current model and stamps every response with the
version actually served, and the one older Hub tree (2026-09-19)
identifies itself as Von-1.0 and predates the Option-Marker scoring
head the server loads, so it cannot be served as itself. The pin
was corrected to `von-1.3.0` before merge, so a sealed run names
the weights that produced it. The adapter enforces the server's
own model stamp on every response, so a server that starts
serving a different model, or answers without a stamp, fails the
run instead of relabelling it. A deployment that serves a specific checkpoint directory with
`VON_CHECKPOINT_DIR` says so in the run record, because the stamp
cannot distinguish one checkpoint directory from another; that
choice is an operator attestation.
## Strands Decider

```bash
pip install strands-decider
strands-decider serve StrandsAgents/strands-decider-2B-hobson-v21 --device cpu --port 8000
peira run --adapter peira.adapters.strands_decider:StrandsDeciderAdapter --suite trial-demo
```

Strands Decider (AWS Strands Labs, Apache 2.0) is a small decision
model. A Qwen3.5-2B base with its LM head removed, a rank-16 LoRA,
and a pointer readout head answers typed choice, score, and noul
questions in one forward pass, with a probability distribution per
question and no generated text. `strands-decider serve` exposes
`POST /v1/systemone` on 127.0.0.1 with no authentication, and
JevBench's TypeSafe adapter runs against it unmodified, so the
adapter reuses the self-hosted wire plumbing it shares with Kev.
The differences are the pinned checkpoint and the default endpoint
(`http://127.0.0.1:8000/v1/systemone`).

The checkpoint is pinned to
`StrandsAgents/strands-decider-2B-hobson-v21`, the current
published reference weights. The checkpoint is baked into the
server deployment, so any other model id is rejected at
construction, and the pinned id namespaces the runner cache. The
adapter also checks the model name every response reports and
fails the call when it is not the pinned checkpoint's name, so
an endpoint serving other weights cannot be measured under the
pin by mistake. A server started with its `--model-name`
override is out of contract for the same reason. The
first server start downloads the checkpoint repo plus the
Qwen3.5-2B base weights, about 4.5 GB.

One wire difference from Jev matters, and the adapter corrects for
it. The server's `confidence` field on a choice answer is a
rescaled value, stretched so an even split gives 0 and certainty
gives 1 whatever the number of options. Peira's confidence
contract is the model's probability for the chosen option, so
the adapter reports `probabilities[decision]` and leaves the
rescaled figure in the transcript only. A decision answer with
no numeric probability for its chosen option is a terminal
error, never a fallback to the rescaled figure. The same
correction applies to the paired
decision answer on score calls. A score answer's `score` field is
the probability weighted level position on the 0..levels-1 scale,
which is the shape the Jev score mapping already normalizes.

Device selection is the server's. Pass `--device cuda`, `mps`,
or `cpu` to `strands-decider serve`. The server binds to
127.0.0.1 by default and has no authentication, and its authors
have not verified its behaviour under concurrent requests, so run
it locally only and run peira against it at concurrency 1.

CPU practicality, measured on the project's 2 vCPU trial VM
with `--device cpu` (2026-10-15). The package installs and the
checkpoint and base weights download and load fully on CPU,
and a live CPU serve canary answered all three primitives at
build time. A later rerun under lane contention was OOM-killed
at a measured peak resident set of about 4.2 GB before its
first answer. The honest verdict is that a full CPU trial
needs either this VM to itself (the 2B weights in float32 plus
runtime overhead want roughly half the machine) or a GPU
host. Full peira trials on CPU will be slow in any case, and
the honest expectation is hours rather than minutes. The
model is local and self-hosted, so cost is $0.

Serve device changes the numbers. The server engine runs the
torso in float32 on CPU and in bfloat16 on CUDA by design,
and the two stacks give materially different probabilities
for this checkpoint. A live canary pair on the
duplicate-charge refund case makes the size of it concrete.
On CPU the choice probability for approve was 0.6487 and the
abstain probability was 0.9667. Served on an RTX 3090 the
same case gave 0.8446 and 0.4791, and the abstain arm crossed
its halfway threshold on the GPU values alone. Neither stack
is wrong. The numbers are the model's as served on that
device, and results from different devices are not
interchangeable. The adapter cannot see which device served
it, so the serve device is recorded with the run's own
configuration rather than by the adapter.

A server that cannot be reached is a terminal provider error whose
message tells you exactly how to start it. The runner never
retries a missing local server. HTTP error statuses keep their
status codes for the runner's classifier.
## Decider

```bash
pip install decider-ai
peira run --adapter peira.adapters.decider:DeciderAdapter --suite trial-demo
```

Decider (Mapika AI, Apache 2.0) is a family of System One-style
models fine-tuned from Qwen3.5 bases. A Decider reads a state plus
typed questions and returns, from one forward pass, a probability
distribution for every question. This adapter measures the small
arm, `Mapika/decider-0.8b` (Qwen3.5-0.8B base, 32k context), in
process through the package's library API. Its `system_one` method
takes the same question shapes the Jev wire takes and returns the
same answer shapes, so the adapter sends Jev's question builders
unchanged and the rubric text and abstain question are the same
measurement instrument every Jev-family adapter sends.

Two answer readings matter. A choice answer's `confidence` field
is the TypeSafe rescaled figure, so the adapter reports the raw
probability for the chosen option from the answer's
`probabilities` map and leaves the rescaled figure in the
transcript only. And a score answer's `score` arrives on the
0..levels-1 index scale, so the adapter normalizes it with the
same divisor the Jev adapter uses.

Every answer is a softmax over its option letters divided by a
temperature from the checkpoint's `decider_config.json`, one
fitted value per question type where the checkpoint carries a
per-type map. Those temperatures are part of the measured
instrument, and the adapter never overrides them, so a run
measures the checkpoint as its authors shipped it.

The device is picked at construction (CUDA, then MPS, then CPU)
and can be forced with `device=`. On CPU the package runs float32
eager, and the 0.8B checkpoint is the family's CPU-sized arm. The
model is local, so cost is $0, and a failure is a terminal
provider error with no status code.

The checkpoint is pinned to `Mapika/decider-0.8b` at a pinned Hub
revision. Any other checkpoint id or revision is rejected at
construction. The pinned pair is the adapter version and
namespaces the runner cache.

Canary record (2026-10-15): the adapter's package calls were
verified line by line against the installed `decider-ai` source
(the constructor takes no revision argument, so the pin is a
local snapshot of the pinned revision, and the `system_one`
question and answer shapes match what the adapter sends and
reads). The live canary then passed on a rented RTX 3090 pod,
with the engine holding about 1.9 GB of GPU memory. Choice
answered approve at 0.9213, score answered 0.89 with confidence
0.9257, and abstain answered other at 0.2944. Every output was
valid, the pin was verified in process, and every decision
agreed with the builders' local CPU canary. Two runtime
requirements came out of that run. The package needs its own
torch pairing (decider-ai 1.9.0 uses torch 2.7 APIs, with
transformers 5.19.0 the known-good partner), and its
torch.compile path needs a C compiler in the environment. On
the project's 8 GB trial VM the first inference peaks at about
3.3 GB resident, so a local run wants a drained box.

## GLiNER2.5-Decide

```bash
pip install "gliner2[local]"
peira run --adapter peira.adapters.gliner_decide:GlinerDecideAdapter --suite trial-demo
```

GLiNER2.5-Decide (Fastino Labs, Apache 2.0) is a 340M DeBERTa-v3
encoder fine-tuned for operational decisions. It is a schema
classifier, not a question-answering wire. One `classify_text` call
scores several named tasks over the same text, and each task is a
caller-supplied label set whose labels may carry a description
each. The adapter always asks for confidences, and a task result is
the winning label plus the model's probability for it. The model
runs locally on CPU, so cost is $0 and a failure is a terminal
provider error with no status code.

The label mapping is the adapter's design, and it is fixed:

- Choice becomes one task named `decision`. Its labels are the
  case's candidate labels (the case options plus `other`), each
  described the way the Jev choice criteria describe them. The
  winning label is the decision and its probability is the
  confidence.
- Score becomes two tasks in one call. The `score` task's labels
  are the five ordered rubric levels the Jev wire uses, worst to
  best (the middle level carries a comma where Jev's copy
  carries an em dash; these labels are this adapter's own
  instrument text), and the winning level's position normalized
  to 0..1 is the score. The `decision` task carries the decision
  label and the reported confidence, the same pairing the Jev
  adapter uses.
- Abstain becomes one task named `abstain` with two labels, `yes`
  (the case should be abstained, because there is no confident
  correct decision) and `no` (a confident correct decision exists).
  The yes probability is the winner's confidence, or one minus it
  when the winner is `no`. The decision threshold and the
  confidence formula then follow the Jev abstain mapping.

Two honest limitations. The model takes no instructions, so the
question a case asks is carried only by the task name, the labels,
and their descriptions. Cases whose prompt does not itself state
the decision context will measure worse, and that is the model's
score to earn. And the public `classify_text` API returns only the
winning label and its confidence per task, so the score is the
winning level's position rather than a probability weighted
expectation over levels. Both task results are recorded verbatim in
the transcript, so the reading stays auditable.

The checkpoint is pinned to `fastino/GLiNER2.5-Decide` at a pinned
Hub revision. Any other checkpoint id is rejected at construction.
The pinned pair is the adapter version and namespaces the runner
cache.

Canary record (2026-10-15): the package installs from PyPI, the
checkpoint downloads in full, and the `classify_text` API shape
was verified against the installed package. The first live CPU
canary attempts on the project's shared trial VM were OOM-killed
the same day (measured peak resident set 2.3 GB and still rising
when killed, while other lanes held most of the VM's 8 GB), a
host capacity state rather than an adapter defect. The rerun
later that day, launched at the best memory the shared box
offered, passed through the real adapter: exit 0, peak resident
set 2,770 MB, with choice approve at confidence 0.4867, score
0.75 (approve) at confidence 0.4486, and abstain at confidence
0.3668, every output validating against the adapter contract.

## Lakera Guard

No extra needed (stdlib transport). Set `LAKERA_API_KEY` to your API key,
then run

```bash
export LAKERA_API_KEY="<your-lakera-key>"
peira run --adapter peira.adapters.lakera:LakeraAdapter --suite trial-demo
```

Lakera Guard (Check Point AI Guardrails) is a commercial
threat-detection API. The adapter sends the case prompt as a single
user message to `POST https://api.lakera.ai/v2/guard` with
`breakdown: true` and reads back the `flagged` boolean plus
per-detector results. Empty or whitespace-only prompts are never sent.
The adapter returns `"other"` locally for those with no API call.
Per B2, guardrails are abstain-primitive-only. A
flagged verdict is the explicit `"abstain"` label (a deliberate
abstain-decision, not a refusal). Unflagged content is the `"other"`
placeholder (the guardrail vetoes nothing and never claims to know the
correct decision). The score comes from the breakdown's highest
detector confidence, mapping the ordinal levels (`l1_confident` … `l5_unlikely`) linearly to 0..1. When the breakdown is absent the
`flagged` boolean is authoritative. 401/422 are terminal. 429/5xx and
transport timeouts surface as retryable provider errors for the
runner. The API version is pinned to v2. Reported pricing is a free
Community tier (10k calls/month) with paid entry around $99/month for
50k calls (~$0.002/call). That figure is secondary-sourced via
third-party integration guides and not confirmed on an official Lakera
pricing page. The pinned table in `python/peira/data/pricing.json`
reflects that with the caveat attached. Live-verified 2026-09-30. Two
real calls against `POST https://api.lakera.ai/v2/guard` returned
HTTP 200 with the documented wire shape. The response carries a
`flagged` boolean, a `breakdown` array
(`detector_type`/`detected`/`result`), and
`metadata.request_uuid`. A benign message came back `flagged: false`
with all detectors at `l5_unlikely`. A prompt-injection probe came
back `flagged: true` with `prompt_attack` at `l1_confident`. The
response also carries `action: "enforce"` plus per-entry
`detector_id`/`message_id`/`policy_id`/`project_id`, which the adapter
ignores.

## OpenAI omni-moderation

No extra needed (stdlib transport). Set `OPENAI_API_KEY` to your API key,
then run

```bash
export OPENAI_API_KEY=<redacted>
peira run --adapter peira.adapters.omni_moderation:OmniModerationAdapter --suite trial-demo
```

OpenAI's production moderation endpoint, the industry reference for
"content moderation in production." The adapter sends the case prompt
to `POST https://api.openai.com/v1/moderations` with
`{"model": "omni-moderation-latest", "input": text}` and reads back
the `flagged` boolean plus 13 per-category confidence scores in the
0-1 range (`harassment`, `harassment/threatening`, `hate`,
`hate/threatening`, `illicit`, `illicit/violent`, `self-harm`,
`self-harm/intent`, `self-harm/instructions`, `sexual`,
`sexual/minors`, `violence`, `violence/graphic`). Empty or
whitespace-only prompts are never sent. The adapter returns `"other"`
locally for those with no API call. Per B2, guardrails are
abstain-primitive-only. A flagged verdict is the explicit `"abstain"`
label (a deliberate abstain-decision, not a refusal). Unflagged
content is the `"other"` placeholder (the guardrail vetoes nothing
and never claims to know the correct decision). The score is
`max(category_scores)`, the honest aggregation when categories do
not map 1:1 to peira's families; the `flagged` boolean is
authoritative for the decision. The response's `model` field (what
was actually served behind the pinned alias) is recorded in the
transcript per call. 401/403 are terminal. 429/5xx and transport
timeouts surface as retryable provider errors for the runner. The
endpoint is free to use. Known blind
spot: a 2026-04 probe found phishing-style credential-theft prompts
can pass silently. Treat clean verdicts on credential-solicitation
cases with skepticism. **Live-UNVERIFIED**: no real call has been
made from this environment as of 2026-09-30. The wire shape above is
from the official OpenAI API reference; confirm it against one live
call before first measured use.

## Google Cloud Model Armor

No extra needed (stdlib transport). Set `MODEL_ARMOR_PROJECT_ID`,
`MODEL_ARMOR_TEMPLATE_ID`, and `MODEL_ARMOR_ACCESS_TOKEN` (mint one
with `gcloud auth print-access-token`), then run

```bash
export MODEL_ARMOR_PROJECT_ID="<your-gcp-project>"
export MODEL_ARMOR_TEMPLATE_ID="<your-template>"
export MODEL_ARMOR_ACCESS_TOKEN="$(gcloud auth print-access-token)"
peira run --adapter peira.adapters.model_armor:ModelArmorAdapter --suite trial-demo
```

Google Cloud's managed prompt screening service. The adapter sends the
case prompt as a user prompt to the `:sanitizeUserPrompt` action on
your template and reads back
`sanitizationResult.filterMatchState` (`MATCH_FOUND` or
`NO_MATCH_FOUND`) plus the per-filter breakdown. The template decides
which filters run, covering CSAM, malicious URIs, responsible-AI
categories, prompt injection and jailbreak, and sensitive-data
protection. The region defaults to `us-central1` and can be overridden
with `MODEL_ARMOR_LOCATION`. Empty or whitespace-only prompts are
never sent. The adapter returns `"other"` locally for those with no
API call. Per B2, guardrails are abstain-primitive-only. A
`MATCH_FOUND` verdict is the explicit `"abstain"` label (a deliberate
abstain-decision, not a refusal). `NO_MATCH_FOUND` is the `"other"`
placeholder (the guardrail vetoes nothing and never claims to know the
correct decision). Model Armor returns a boolean verdict with no
calibrated score, so the reported confidence is the M-2/D-23 boundary
distance at its degenerate value of 1.0, stated honestly rather than
invented. 401/403 are terminal. 404 means the template resource name
is wrong. 429/5xx and transport timeouts surface as retryable provider
errors for the runner. Pricing is secondary-sourced, but cost is
explicitly unaccounted. The sanitizeUserPrompt API returns no token
usage, so peira cannot meter per-token spend and records $0.00. The
pinned pricing entry carries the machine-readable `cost_accounted`
marker set to false, so the zero is read as unaccounted rather than
as a free call, never a silent estimate. The list price for
reference is the first 2M tokens per month free, then $0.10 per 1M
tokens, per third-party integration guides, and that figure is not
confirmed on an official GCP pricing page. The pinned table in
`python/peira/data/pricing.json` carries that caveat. One known caveat
is that the prompt-injection filter has a roughly 512-token analysis
window, so its signal degrades on very long case prompts. Model Armor
is text-only. **Live-UNVERIFIED**. No real call has been made from this
environment as of 2026-09-30. The wire shape above is from the Model
Armor REST reference. Confirm it against one live call before first
measured use.

Live verification was attempted 2026-10-02 and could not start. No
Model Armor credential is provisioned in this environment
(`MODEL_ARMOR_PROJECT_ID`, `MODEL_ARMOR_TEMPLATE_ID`, and
`MODEL_ARMOR_ACCESS_TOKEN` are all unset), so no call could be made.
The adapter stays out of measured runs until a live smoke passes.
Backfill once the GCP project, template, and token are
provisioned.

## Azure Prompt Shields

No extra needed (stdlib transport). Set
`AZURE_CONTENT_SAFETY_ENDPOINT` and `AZURE_CONTENT_SAFETY_KEY`, then
run

```bash
export AZURE_CONTENT_SAFETY_ENDPOINT="https://<resource>.cognitiveservices.azure.com"
export AZURE_CONTENT_SAFETY_KEY="<your-key>"
peira run --adapter peira.adapters.azure_prompt_shields:AzurePromptShieldsAdapter --suite trial-demo
```

Microsoft's dedicated prompt-injection detector, exposed through the
Azure AI Content Safety REST API. The adapter sends the case prompt as
the user prompt with an empty document list to `POST
{endpoint}/contentsafety/text:shieldPrompt?api-version=2024-09-01` and
reads back `userPromptAnalysis.attackDetected`. Empty or
whitespace-only prompts are never sent. The adapter returns `"other"`
locally for those with no API call. Per B2, guardrails are
abstain-primitive-only. An attack-detected verdict is the explicit
`"abstain"` label (a deliberate abstain-decision, not a refusal). No
attack detected is the `"other"` placeholder (the guardrail vetoes
nothing and never claims to know the correct decision). Prompt Shields
returns a boolean verdict with no calibrated score, so the reported
confidence is the M-2/D-23 boundary distance at its degenerate value
of 1.0, stated honestly rather than invented. 401/403 are terminal.
429/5xx and transport timeouts surface as retryable provider errors
for the runner. Pricing follows the Azure Content Safety page. The
first 5,000 text records per month are free, then $0.38 per 1,000 text
records, and one peira call is one record. The pinned table in
`python/peira/data/pricing.json` reflects that. That one-record-per-call
mapping is an unverified assumption. Whether Prompt Shields requests
are metered as standard text records is not established on the Azure
pricing page, and prompts over 1,000 characters may consume multiple
records (up to 10 for the 10,000-character API maximum), so longer
prompts may be under-accounted. Prompts over 10,000 characters are
refused locally by the adapter and never sent. One known caveat is
that an independent 2025 evaluation found large evasion gaps for
hosted prompt-injection detectors, including Prompt Shields, under
adaptive attacks. Treat it as defense-in-depth signal, not complete
mitigation. **Live-UNVERIFIED**. No real call has been made from this
environment as of 2026-09-30. The wire shape above is from the Azure
Content Safety quickstart and the `text:shieldPrompt` REST reference.
Confirm it against one live call before first measured use.

Live verification was attempted 2026-10-02 and could not start. No
Azure Content Safety credential is provisioned in this environment
(`AZURE_CONTENT_SAFETY_ENDPOINT` and `AZURE_CONTENT_SAFETY_KEY` are
both unset), so no call could be made. The adapter stays out of
measured runs until a live smoke passes. Backfill once
an Azure AI Content Safety resource is provisioned.

## Cloudflare Workers AI (Llama Guard 3 8B)

No extra needed (stdlib transport). Set `CLOUDFLARE_ACCOUNT_ID` and
`CLOUDFLARE_API_TOKEN` (with Workers AI read scope), then run

```bash
export CLOUDFLARE_ACCOUNT_ID="<your-account-id>"
export CLOUDFLARE_API_TOKEN="<your-api-token>"
peira run --adapter peira.adapters.cloudflare_workers_ai:CloudflareWorkersAiAdapter --suite trial-demo
```

Cloudflare's callable AI-security API. Note that Cloudflare's
"Firewall for AI" is a WAF ruleset product with no API to call, so it
cannot be exercised as an adapter. What Cloudflare does expose is
Workers AI, and this adapter runs Meta's Llama Guard 3 8B
(`@cf/meta/llama-guard-3-8b`) through it. The adapter wraps the case
prompt in the Llama Guard 3 prompt-classification template and sends
it as a single user message to `POST
https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/meta/llama-guard-3-8b`,
then parses the first line of `result.response` for `safe` or
`unsafe`. An `unsafe` verdict may carry a second line of
comma-separated violated category codes, which the adapter records in
the transcript. A verdict that parses as neither `safe` nor `unsafe`
fails closed to a provider error, never silently treated as clean.
Empty or whitespace-only prompts are never sent. The adapter returns
`"other"` locally for those with no API call. Per B2, guardrails are
abstain-primitive-only. An `unsafe` verdict is the explicit `"abstain"`
label (a deliberate abstain-decision, not a refusal). `safe` is the
`"other"` placeholder (the guardrail vetoes nothing and never claims
to know the correct decision). Llama Guard emits text with no
calibrated score, so the reported confidence is the M-2/D-23 boundary
distance at its degenerate value of 1.0, stated honestly rather than
invented. 401/403 are terminal. 429/5xx and transport timeouts surface
as retryable provider errors for the runner. Cost is explicitly unaccounted. The Workers AI API
returns no token usage, so peira cannot meter per-token spend and
records $0.00. The pinned pricing entry carries the machine-readable
`cost_accounted` marker set to false, so the zero is read as
unaccounted rather than as a free call, never a silent estimate. The
list price for reference follows the Cloudflare model page, $0.484
per 1M input tokens and $0.03 per 1M output tokens. The pinned table
in `python/peira/data/pricing.json` carries that caveat. One known
caveat is that the Llama Guard 3 task prompt in the adapter follows
Meta's documented task format with the raw chat-template tokens
removed (Workers AI applies the chat template to `messages` itself)
and has not been confirmed byte-for-byte against a live call. **Live-UNVERIFIED**. No real call has been made from this
environment as of 2026-09-30. Confirm the wire shape and the template
against one live call before first measured use.

Live verification was attempted 2026-10-02 and could not complete.
The sandbox reaches api.cloudflare.com and the provisioned connector
credential authenticates for account reads, but the Workers AI
endpoint rejects the call with HTTP 401 (authentication error). The
provisioned token lacks Workers AI scope, or Workers AI is not
enabled on the account. The adapter's exact payload was sent, but no
usable response was ever returned, so the wire shape stays
unconfirmed. The adapter stays out of measured runs until a live
smoke passes. Backfill once a token with Workers AI
scope is provisioned.

## Cloudflare Clef

No extra needed (stdlib transport). Set `CLOUDFLARE_ACCOUNT_ID` and
`CLOUDFLARE_API_TOKEN` (the token needs Workers AI scope on the
account), then run

```bash
export CLOUDFLARE_ACCOUNT_ID="<your-account-id>"
export CLOUDFLARE_API_TOKEN="<your-api-token>"
peira run --adapter peira.adapters.clef:ClefAdapter --suite trial-demo
```

Clef is Cloudflare's decision-model family on Workers AI, launched
2026-10-01 as a drop-in compatible implementation of the System One
API and benchmarked by Cloudflare head-to-head against TypeSafe's
Jev. The adapter sends the case prompt as `state` plus named typed
questions to `POST
https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}`
and reads the answers back out of the Workers AI envelope's
`result.answers`. Each question carries `instructions`. Choice and
score questions also carry `criteria`. The question text is the Jev
adapter's unchanged,
so the wires see identical decision spaces. Answers carry `choice`
(choice), `score` (score), or `noul` (abstain). The score question
uses the same five described levels as the Jev adapter, and the
abstain primitive follows the Jev placeholder rule exactly (at or
above probability 0.5 the decision is the deliberate label `abstain`,
below it the `other` placeholder). A `success: false` envelope is
terminal.

Three pinned models are supported. Each is named by its full
Workers AI id, and the per-instance version and cache namespace
follow the pin. The three are `@cf/cloudflare/clef-flash` (9B, the
default, $0.038 per 1M input
tokens after the 2026-10-09 price cut from $0.090, which also cut its
hosted context to 24,576 tokens), `@cf/cloudflare/clef` (27B, $0.24
per 1M input tokens, 65,536-token context), and
`@cf/cloudflare/clef-omni` (30B-A3B, $0.15 per 1M input tokens,
64,000-token context). Peira's cases are text, so omni is exercised
on its text path. Output is free on all three. The rates were
verified against Cloudflare's official Workers AI pricing page on
2026-10-15 and are pinned in `python/peira/data/pricing.json`. Short model names
and every other id are rejected at construction, so a run always
names one exact model. 408, 409, 429, 529 and 5xx statuses and
transport timeouts surface as retryable provider errors for
the runner, with any server `Retry-After` passed through.
401/403, 404 and 400/422 are terminal.

**Live-UNVERIFIED.** An access probe on 2026-10-15 sent the adapter's
exact payload to the run endpoint for `@cf/cloudflare/clef-flash`.
The account's provisioned Cloudflare token answered HTTP 401 (error
code 10000, authentication error) on the run endpoint and HTTP 403 on
the model search endpoint, while the same token verified active and
listed zones. It carries no Workers AI scope. The wire shape above
follows Cloudflare's official Clef documentation and is confirmed by
the first canary once a Workers AI scoped token is provisioned. The
adapter stays out of measured runs until that canary passes.

## Perplexity pplx-decider

No extra needed (stdlib transport). Set `PERPLEXITY_API_KEY` (API
access is prepaid, so the account also needs API credit), then run

```bash
export PERPLEXITY_API_KEY=<redacted>
peira run --adapter peira.adapters.pplx_decider:PplxDeciderAdapter --suite trial-demo
```

pplx-decider is Perplexity's decision model, served through the
Decisions API and positioned by Perplexity directly against
TypeSafe's Jev. The adapter sends the case prompt as `state` plus
named typed questions to `POST
https://api.perplexity.ai/v1/decisions` and reads the answers back
out of the body's top-level `answers`. Each question carries
`instructions`. Choice and score questions also carry `criteria`.
The question text is the Jev adapter's unchanged, so the wires see
identical decision spaces. Answers carry `choice` (choice), `score`
(score), or `noul` (abstain). The score question uses the same five
described levels as the Jev adapter, and the abstain primitive
follows the Jev placeholder rule exactly (at or above probability
0.5 the decision is the deliberate label `abstain`, below it the
`other` placeholder).

The response is not enveloped. Its top level carries `answers`, a
`model` echo of the id sent, and `usage`. The adapter refuses a
response whose echoed model differs from the pin, so a measurement
can never seal under the wrong model's name.

Two pinned models are supported. Each is named by its full served
id, and the per-instance version and cache namespace follow the pin.
The two are `pplx-decider-v1.1-27b` (the current version, the
default) and `pplx-decider-v1-27b` (the launch version). Both are
Qwen3.8-27B fine-tunes with Apache-2.0 weights, priced at $0.02 per
1M input tokens with output free. The rates were verified against
Perplexity's official Decisions API documentation on 2026-10-15 and
are pinned in `python/peira/data/pricing.json`. Unversioned names
and every other id are rejected at construction, so a run always
names one exact model. 408, 409, 429, 529 and 5xx statuses and
transport timeouts surface as retryable provider errors for
the runner, with any server `Retry-After` passed through. 401
and 403 (key rejected), 402 (out of API credit), 404 and
400/422 are terminal.
The organization rate limit
is 10 requests per second. The runner owns concurrency.

**Live-verified wire, canary pending.** The wire shape above was
verified against the live API on 2026-10-15, before the adapter was
written, with a probe call carrying the adapter's exact question
text. The probe returned HTTP 200 for `pplx-decider-v1.1-27b` with
all three primitives answered. The abstain probability arrived under
the `noul` key only. The `usage` object carried integer counters. The
adapter's first measured exercise is the standard driver canary.

### pplx-decider-v1.2 and pplx-decider-flash-v1.2 (Perplexity)

Perplexity released `pplx-decider-v1.2` (27B) and
`pplx-decider-flash-v1.2` (4B) on 2026-10-16, after the freeze
closed. The adapter's pinned-id table accepts all four ids; the
default flipped to `pplx-decider-v1.2` on 2026-10-24, because the
v1.1 and v1 ids no longer serve their named weights (see the
re-pointing hazard below), so a default run must name the weights
it actually measures. Pricing: $0.02 per 1M input
tokens with output free for v1.2, $0.01 per 1M input with output free
for the flash, both verified 2026-10-23 against Perplexity's official
Decisions API documentation (page updated 2026-10-20). Both run the
same wire shape and question text as the older pins.

Re-pointing hazard, documented in the same Perplexity docs:
requests naming `pplx-decider-v1.1-27b` or `pplx-decider-v1-27b` now
select v1.2 server-side. A measurement under either old pin taken
after 2026-10-16 may therefore not measure the weights it names.
The adapter's echo check refuses a response whose echoed model
differs from the requested pin, which guards against the
echo-the-served-model behavior; if the API echoes the requested id
instead, the transcript cannot distinguish the weights, so treat
any post-2026-10-16 run under the v1.1 or v1 ids as suspect until
the echo behavior is confirmed live. The owner's options are
re-pinning the driver row to `pplx-decider-v1.2` explicitly or
flipping the adapter default; neither is decided in this change set.

## Celeris

No extra needed (stdlib transport). Set `CELERIS_API_KEY`, then run

```bash
export CELERIS_API_KEY="<your-api-key>"
peira run --adapter peira.adapters.celeris:CelerisAdapter --suite trial-demo
```

Celeris-1-decision is a diffusion decision model launched by Celeris
on 2026-10-08. It serves the System One wire at `POST
https://inference.celeris.ai/celeris-1-decision/v1/systemone`. The
adapter sends the case prompt as `state` plus named typed questions
and reads the answers from the top level of the response. The
response is not enveloped. It also carries a `model` echo and a
`usage` object with integer token counters.

The question text is the Jev adapter's unchanged, so the wires see
identical decision spaces. Answers carry `choice` (choice), `score`
(score), or `noul` (abstain). The score question uses the same five
described levels as the Jev adapter. The abstain primitive follows
the Jev placeholder rule exactly. The adapter refuses a response
whose model echo differs from the pin, so a measurement can never
seal under the wrong model's name. A response without usage counters
is terminal. A call that cannot be priced cannot be recorded as
free.

One pinned model is supported. The pin is `celeris-1-decision` at
$0.04 per 1M input tokens with output free. The rate is the
vendor-stated price and is pinned in `python/peira/data/pricing.json`.
The per-instance version and cache namespace follow the pin. Every
other id is rejected at construction, so a run always names one
exact model. Vendor material describes per-answer reasons in an
`x_celeris` extension object. No probe response carried one. The
adapter reads only the standard answer fields, so extension content
never enters a metric.

Errors are FastAPI-shaped. The body carries a `detail` list and the
adapter surfaces its message text. 408, 409, 429, 529 and 5xx
statuses and transport timeouts surface as retryable provider
errors for the runner, with any server `Retry-After` passed
through. 401/403, 404 and 400/422 are terminal.

**Live-verified.** A probe on 2026-10-15 sent the adapter's exact
question text to the endpoint and returned HTTP 200. A combined call
carried all three questions. Each per-primitive call shape also
returned HTTP 200 with only the requested answers present. The
choice answer carried a confidence of 0.94 against a chosen-option
probability of 0.96, so the confidence field is its own value. The
score answer carried 3.82 on the 0-based rubric scale. The abstain
answer carried the probability under `noul` only. Usage reported 300
input tokens for the combined call and output tokens at 0 on every
call. The first call on the account took about 31 seconds. Warm
calls took 1.0 to 2.2 seconds and four concurrent calls all
succeeded. An unknown model and an unknown question type each
returned HTTP 422. The adapter's first measured exercise is the
standard driver canary.

## Inception Mercury Decide

No extra needed (stdlib transport). Set `INCEPTION_API_KEY`, then run

```bash
export INCEPTION_API_KEY=<redacted>
peira run --adapter peira.adapters.mercury_decide:MercuryDecideAdapter --suite trial-demo
```

Mercury Decide is Inception's decision model, served only through
the Decisions endpoint and positioned by Inception directly against
TypeSafe's Jev. The adapter sends the case prompt as `state` plus
named typed questions to `POST
https://api.inceptionlabs.ai/v1/decisions` and reads the answers back
out of the body's top-level `answers`. Each question carries
`instructions`. Choice and score questions also carry `criteria`.
The question text is the Jev adapter's unchanged, so the wires see
identical decision spaces. Answers carry `choice` (choice), `score`
(score), or `noul` (abstain). The score question uses the same five
described levels as the Jev adapter, and the abstain primitive
follows the Jev placeholder rule exactly (at or above probability
0.5 the decision is the deliberate label `abstain`, below it the
`other` placeholder).

The response is not enveloped. Its top level carries `answers`, a
`model` echo of the id sent, and `usage`. The adapter refuses a
response whose echoed model differs from the pin, so a measurement
can never seal under the wrong model's name.

One pinned model is supported. It is named by its full served id,
and the per-instance version and cache namespace follow the pin. It
is `mercury-decide`, the typed-decision preview model the account's
models list serves on the decisions endpoint only. It is priced at
$0.02 per 1M input tokens with output free. The rate was verified
against the models list served by Inception's API on 2026-10-16 and
is pinned in `python/peira/data/pricing.json`. The account's chat
models (`mercury-2`, `mercury-2.5`) are not the decision model and
are rejected at construction. Unversioned names and every other id
are rejected too, so a run always names the exact model. 408, 429
and 5xx responses and transport failures surface as retryable
provider errors for the runner. 401 and 403 (key rejected), 402 (billing
inactive or quota exhausted), 404, 413 and 400/422 are terminal.
The runner owns concurrency.

**Live-verified wire, canary pending.** The wire shape above was
verified against the live API on 2026-10-16, before the adapter was
written, with a probe call carrying one question of each type. The
probe returned HTTP 200 for `mercury-decide` with all three
primitives answered in about 1.4 seconds. The abstain probability
arrived under the `noul` key only. The `usage` object carried
integer counters. The adapter's first measured exercise is the
standard driver canary.

## Cerno

```bash
peira run --adapter peira.adapters.cerno:CernoAdapter --suite trial-demo
```

Cerno (Apertix, Apache 2.0) is a family of open-weights System
One decision models, `apertixai/cerno-27b`, `apertixai/cerno-9b`
and `apertixai/cerno-4b`, each a Qwen3.5 text base fine-tuned to
answer typed choice, score, and noul questions in one forward
pass, with a probability distribution per question and no
generated text. The vendor's inference code renders the state
and questions into option slots and reads each option's
probability off the label-token logits, dividing by the
calibration temperature the checkpoint ships in
`decider_config.json` (1.534 for the 4B at the pinned revision).

The vendor ships no server. The deployment under test is a
local sidecar that wraps the vendored Decider class and exposes
`POST /v1/systemone` on 127.0.0.1 with no authentication, the
wire shape the Jev adapter speaks, so the adapter reuses the
self-hosted wire plumbing it shares with Kev and Strands
Decider. The differences are the pinned checkpoint, the default
endpoint (`http://127.0.0.1:8017/v1/systemone`), and the answer
validation below. Run it locally only, and run peira against it
at concurrency 1.

The checkpoint is pinned to `apertixai/cerno-4b` at Hub
revision ed4b5c59b542ee96c227ee874776c973980c640b, the only
family member small enough to serve on the trial VM. Any other
model id is rejected at construction, and the pinned id
namespaces the runner cache. The sidecar loads exactly the
pinned snapshot and stamps every response with the checkpoint
name and Hub revision it loaded, `cerno-4b` and
`ed4b5c59b542ee96c227ee874776c973980c640b`. The vendored
Decider's own response name is `decider-dev` for this
checkpoint, because its config carries no version field, so
both stamps come from the sidecar, not the library. The
adapter fails the call when either stamp is absent or
different, so an endpoint serving other weights, or the same
repo at another revision, cannot be measured under the pin
by mistake.

The other two family members carry sibling pins of their own:
`peira.adapters.cerno:Cerno9BAdapter` measures
`apertixai/cerno-9b` at Hub revision
80010f97eaa989b41c908ecba7d7b7fadaa99239 (sidecar on
127.0.0.1:8018, response stamp `cerno-9b`), and
`peira.adapters.cerno:Cerno27BAdapter` measures
`apertixai/cerno-27b` at Hub revision
c2f7efe54fe4d3dfd7136bb2e9daf2c0c0633e3d (sidecar on
127.0.0.1:8019, response stamp `cerno-27b`). Both revisions
were resolved live from the Hub on 2026-10-23. The wire,
the stamp check, the fail-closed answer validation, and the
confidence normalization are identical across the three
classes; each class rejects the other members' ids at
construction, so a sibling's deployment cannot be measured
under the wrong pin.

The weights are FP8 W8A8 as shipped. That is the checkpoint's
native format, served as published and never re-quantized or
converted. The sidecar's CPU serving keeps the weights FP8 in
memory and dequantizes each layer transiently for the forward
pass, which is the standard CPU execution of an FP8 checkpoint.
Serve device and execution stack change the numbers, as with
Strands Decider, so the serving device is recorded with the
run's own records.

Peira's confidence is the model's probability for the chosen
option. The vendored answer format emits that figure both as
the answer's `confidence` and in its `probabilities` map, and
the vendor's published answer format omits the `confidence`
field because it duplicates the map entry. The adapter
normalizes the decision answer to the map entry before
parsing, so the recorded confidence is the probability under
either format, and never the inherited parser's 0.5 default
for an absent field. A present but malformed `confidence` is
still a terminal error, since neither format emits one. What
the adapter does not accept at all is a malformed
distribution. A probability that is missing, non-numeric,
non-finite, or outside [0, 1], a distribution whose mass does
not sum to 1 within rounding, a score outside the level
range, or a noul value that is not a probability is a
terminal error, never a clamped or defaulted number, because
for a pinned local deployment those shapes are server drift
against a fixed answer schema, not measurement.

The model is local and self-hosted, so cost is $0 (pricing
version 2026-10-15.7). A forward pass is a full prefill of the
case state on CPU. Measured at build time on the 2 vCPU trial
VM under its usual load, a short case state took about 318
seconds for a single choice call, so the adapter's default
timeout is 1,200 seconds and a full trial is a long run, on
the order of days of wall time on that VM rather than hours.

## Pricing

`peira run` recomputes cost from the pinned table in
`python/peira/data/pricing.json`. Adapter-reported cost is ignored.
The table's source and pin date are sealed into every run artifact.
