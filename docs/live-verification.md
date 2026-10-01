# Live adapter verification

This document describes how peira verifies an adapter against its live
API before any measured run may use it. Verification is wire
verification, not measurement. It answers whether the adapter
authenticates, whether the configured model id resolves to a working
endpoint, whether the
provider honors the request shape the adapter sends, and whether
decisions come back parseable and directionally sane. It does not
produce numbers anyone may publish. Per the D-33 policy recorded in
`Adapters.md`, the publication block lifts only for adapters that
pass.

## When verification is required

Any adapter that has never completed a successful call against its live
API is unverified. Its docstring and its section in `Adapters.md` carry
an honest caveat to that effect, and no measured numbers from it may be
published until a live smoke test passes. Re-verification is required
when a pin changes, when the request shape changes, when a provider
announces a wire-level behavior change, or when a provider alias
resolves to a different model version.

## The smoke procedure

Run each unverified adapter over a fixed 20-case slice of the trial
suite. The slice is `score_anchoring` plus `negation_games`, which
together cover all three primitives (10 score, 7 abstain, 3 choice).
The runner classifies both arms of every case, so the smoke is 40 paid
calls per adapter in the expected case. A malformed response triggers
one repair retry, so the ceiling is 80 calls per adapter. The 5x abort
threshold below covers that path.

Every adapter under test needs these preconditions in place first.

- The provider API key is exported and funded (`peira doctor` reports
  the adapter ready, not `missing_api_key`).
- `pip install "peira[openai]"` (all four current smoke adapters use
  the OpenAI-compatible path).
- A cost-guard plan exists for the run (`costguard.py plan`), and the
  paid-run authorization for the estimate is in hand. The cost-guard
  is the operator's cost-control tooling in the agent environment. It
  is not installed from this repo. Outside the agent environment,
  substitute any equivalent cost-control step that records an up-front
  estimate and a planned ledger entry before paid calls.

Run one adapter at a time so spend attributes cleanly. The exact invocation per adapter follows.

```bash
peira run --adapter peira.adapters.llm:XAIAdapter \
  --suite trial --families score_anchoring,negation_games \
  --out runs/a6-smoke --seeds 1 --max-concurrency 4 --call-timeout 120
```

Replace the adapter path with `peira.adapters.llm:DeepSeekAdapter`,
`peira.adapters.llm:MetaLlamaAdapter`, or
`peira.adapters.llm:ZaiAdapter`. Do not raise `--seeds` or
`--max-attempts` to force a pass. Retries are transient-only and the
runner owns them.

Wrap each adapter run with the cost-guard verbs for its plan id, as
shown below.

```bash
python3 ~/workspace/openrouter/bin/costguard.py begin <PLAN_ID>
# ... the peira run ...
python3 ~/workspace/openrouter/bin/costguard.py end <PLAN_ID>
```

Spend on these adapters lands on vendor API keys, not the OpenRouter
key, so the begin/end snapshots will show a zero OpenRouter delta.
Record the vendor-console actuals in the run report and pass them to
`end` with `--note`.

## Cost estimate

Per-adapter estimates use the live OpenRouter pricing snapshot of
2026-10-01. Each adapter is 40 calls (20 cases x 2 arms), 1000 prompt
+ 300 completion tokens per call, which is conservative against the
measured mean case prompt of about 507 chars. The model under test
cannot be substituted, so each row uses the closest OpenRouter price
as a proxy. Spend lands on vendor API keys, not the OpenRouter key.

| adapter | configured id | OpenRouter proxy | in / 1M | out / 1M | 40-call estimate | plan |
|---|---|---|---|---|---|---|
| XAIAdapter | grok-4 | x-ai/grok-4.7 | $2.00 | $6.00 | $0.152 | CG-0016 (closed, fresh plan needed) |
| DeepSeekAdapter | deepseek-flash | deepseek/deepseek-v4-flash | $0.042 | $0.084 | $0.0027 | CG-0017 |
| MetaLlamaAdapter | Llama-4-Maverick-17B-128E-Instruct-FP8 | meta-llama/llama-4-maverick | $0.1875 | $0.6525 | $0.0153 | CG-0018 |
| ZaiAdapter | glm-4-plus | z-ai/glm-4.5 | $0.60 | $2.20 | $0.0504 | CG-0019 |

The total planned estimate is $0.2204. That is under the $2
single-run ask-first threshold and October spend so far is well under
the $10 monthly threshold. David authorized the A6 live-verification
spend on 2026-10-01. The cost-guard gate stays in force anyway: an
up-front ledger estimate for every paid call, the $2 single-run and
$10 monthly ask-first thresholds, and cheapest-sufficient-model
default where substitution is allowed. The four models under test
cannot be substituted, the spend spans four vendor accounts, and
none of the four vendor keys is provisioned in the agent environment.
CG-0017 through CG-0019 are the open plans. They supersede the
earlier estimates from before the call count was corrected to 40
and the prices were refreshed. CG-0016 (XAI) was opened and closed
on 2026-10-01 with no run between its begin and end, so the XAI
smoke needs a fresh plan at the same estimate before execution.
No paid call has been made and no spend has occurred. The begin/end
pair against CG-0016 recorded a zero usage delta.

## What the smoke checks per adapter

Each adapter below was built from vendor docs, not the live API. The
smoke resolves the documented open question for each one, listed
next.

- **XAIAdapter** (`grok-4` on `https://api.x.ai/v1`). Open question is
  whether `json_schema` response_format is honored, or only plain
  `json_object`.
- **DeepSeekAdapter** (`deepseek-flash`, the vendor alias for the
  current DeepSeek-V4.1 Flash, on `https://api.deepseek.com`).
  Open question is whether strict `json_schema` is honored. Thinking is
  disabled by the adapter and must stay disabled on the wire.
- **MetaLlamaAdapter** (`Llama-4-Maverick-17B-128E-Instruct-FP8` on
  `https://api.llama.com/compat/v1`). Open question is whether
  `json_schema`, `seed`, and `logprobs` are honored on the compat
  endpoint.
- **ZaiAdapter** (`glm-4-plus` on
  `https://open.bigmodel.cn/api/paas/v4`). Open question is whether
  `json_schema`, `seed`, and `logprobs` are honored.

## Pass criteria

An adapter passes when all of the following hold on its 40 calls.

1. At least 38 of 40 calls return HTTP 200 with a decision that parses
   against the schema, and every non-parsing call has a documented
   provider-side cause.
2. Zero 401 or 403 responses. Authentication works on the first call.
3. Zero 400 responses against the request shape. If the provider
   rejects strict `json_schema`, that is a fail, not a fallback. The
   adapter gets a repair lane. The smoke does not paper over it.
4. Directional sanity holds. The attacked arm refuses or flags at a
   higher rate than the benign arm. This is a sanity check, not a
   measurement claim.
5. Provider-side content-filter refusals stay under 3 of 40 calls. More
   than that means the provider, not the attack, is driving the
   decisions.

## Abort criteria

Stop the adapter immediately, without burning retries, when any of
the following happen.

- A 401 or 403 on any call. Abort the adapter and record the
  provider's error body before doing anything else. A 401 usually
  means the key is wrong or unfunded. A 403 can also mean model access
  or account policy. Fix the actual cause. Do not retry the run.
- A 400 against the request shape on the first call. The wire shape is
  wrong. This needs a code fix, not more spend.
- More than 3 consecutive 5xx responses or timeouts. The provider is
  having an incident. Try again later.
- Projected spend for the adapter passes 5 times its estimate.
  Something is looping. The cost-guard snapshots cannot see vendor-key
  spend, so the operator checks the vendor console after each adapter
  and stops the remaining adapters when the threshold is hit. Where
  the provider supports it, set a vendor-side budget cap before the
  run as well.

A failed adapter does not block the others. Passing adapters unblock.
Failing adapters get repair lanes with their own estimates.

## Recording the result

On a pass, append a live-verification note to the adapter's section in
`Adapters.md`, following the Lakera precedent (date, endpoint,
configured model id, the model version the provider reported or a note
that the provider does not expose one, call count, wire shape
observed, and the outcome against the pass criteria above). On a fail,
record the failure mode and the repair needed. Per the D-33 policy in
`Adapters.md`, the publication block lifts for the passing adapters
only.

The A6 smoke instance is planned, not yet executed. It covers the four
adapters above. The Lakera adapter was verified separately on
2026-09-30 and is not part of this smoke. HF gated-license acceptance
for Prompt Guard 2 and ShieldGemma is a license click plus
`huggingface-cli login`, not a paid call, and is tracked alongside this
smoke. Per-adapter outcomes get recorded here only after execution.
