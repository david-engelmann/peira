# Live adapter verification

This document describes how peira verifies an adapter against its live
API before any measured run may use it. Verification is wire
verification, not measurement. It answers whether the adapter
authenticates, whether the pinned model id resolves, whether the
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
when a pin changes, when the request shape changes, or when a provider
announces a wire-level behavior change.

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
  is not installed from this repo.

Run one adapter at a time so spend attributes cleanly. The exact invocation per adapter follows.

```bash
peira run --adapter peira.adapters.llm:XAIAdapter \
  --suite trial --families score_anchoring,negation_games \
  --out runs/a6-smoke --max-concurrency 4 --call-timeout 120
```

Replace the adapter path with `peira.adapters.llm:DeepSeekAdapter`,
`peira.adapters.llm:MetaLlamaAdapter`, or
`peira.adapters.llm:ZaiAdapter`. Keep `--seeds 1`. Do not raise
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

## What the smoke checks per adapter

Each adapter below was built from vendor docs, not the live API. The
smoke resolves the documented open question for each one, listed
next.

- **XAIAdapter** (`grok-4` on `https://api.x.ai/v1`). Open question is
  whether `json_schema` response_format is honored, or only plain
  `json_object`.
- **DeepSeekAdapter** (`deepseek-flash` on `https://api.deepseek.com`).
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
`Adapters.md`, following the Lakera precedent (date, endpoint, call
count, wire shape observed, and the outcome against the pass criteria
above). On a fail,
record the failure mode and the repair needed. Per the D-33 policy in
`Adapters.md`, the publication block lifts for the passing adapters
only.

The A6 smoke instance is planned, not yet executed. It covers the four
adapters above. The Lakera adapter was verified separately on
2026-09-30 and is not part of this smoke. HF gated-license acceptance
for Prompt Guard 2 and ShieldGemma is a license click plus
`huggingface-cli login`, not a paid call, and is tracked alongside this
smoke. Per-adapter outcomes get recorded here only after execution.
