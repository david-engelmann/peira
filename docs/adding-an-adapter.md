# Adding an adapter

A checklist for plugging a new decision model into peira. Follow it
in order. Every item is required. The review of your adapter PR will
walk this list, and a missing item sends the PR back.

## 1. Wire the adapter into the protocol

- [ ] Implement the adapter protocol in `python/peira/adapters/base.py`.
      One `decide()` method taking the primitive name, returning the
      typed output for that primitive (`ChoiceOutput`, `ScoreOutput`,
      or `AbstainOutput`). The protocol is a `Protocol`, not a base
      class to subclass.
- [ ] Declare `supported_primitives` honestly. Partial coverage is fine.
      Claimed coverage you do not have is a defect. The maintainer
      reviews this declaration by hand on every adapter PR.
- [ ] Load by dotted path with no constructor arguments. Deployment
      configuration goes through environment variables. Model
      identity is pinned in class constants (`HF_MODEL_ID`,
      `HF_REVISION`), never an alias, so a run is reproducible from
      the adapter path plus the environment.
- [ ] Read the reference implementation while you work.
      `peira.adapters.mock` is the minimal protocol skeleton.
      `peira.adapters.hf` ShieldstralAdapter is the best production
      example of a guardrail mapping done carefully.

## 2. Obey the contract rules

- [ ] Set the provider SDK to a single attempt (`max_retries=0` or the
      SDK equivalent). The runner owns retries. A second retry layer
      under the runner multiplies worst-case latency and hides the
      congestion signal the runner needs.
- [ ] Return a full measurement record on every call, never a bare
      decision string. Decision plus confidence plus abstained plus
      refusal reason plus usage.
- [ ] Never invent a measurement. Confidence is the adapter's
      self-reported confidence or None. Usage is real token and
      latency accounting or None. Cost is filled by the runner from
      the pinned pricing table. An adapter-set cost is ignored.
- [ ] Pin the model to an exact revision or versioned id. Never an
      alias like latest or a floating tag. The leaderboard row binds
      to the pinned id, and a floating id makes the row
      unreproducible.

## 3. File the capability report

Every adapter PR must include this table, filled in, in the PR
description. It states what the harness can and cannot observe
through your adapter, so reviewers can judge whether its numbers
are comparable with other adapters.

| Capability | Status | Notes |
|---|---|---|
| Confidence scores | reported / unavailable | 0..1 self-reported, or None when the model exposes nothing |
| Structured outputs | full / partial / unavailable | Which primitives carry typed outputs |
| Cost attribution | per-call / estimated / unavailable | Real usage records, or nothing |
| Reasoning tokens | reported / unavailable | Whether thinking traces are visible and priced |
| Transcript payloads | captured / unavailable | Raw request and response attached to the call record |
| Refusal behavior | distinguished / conflated | Can provider refusals be told apart from model abstentions |
| Score primitive | calibrated probability / thresholded label / unsupported | What the score means, if scores exist |

The governing rule is unavailable rather than zero. If your adapter
cannot observe a capability, say so in the table and report None in
the record. A zero in place of an unknown poisons every downstream
number that touches it. Reviewers treat a guessed zero as a
correctness defect, not a style nit.

## 4. Map the verdicts honestly

- [ ] Document the verdict mapping in `docs/Adapters.md`, in the same
      voice as the existing entries. What the model natively outputs,
      how it becomes a peira decision, and where the mapping is lossy.
- [ ] Name the known caveats of your mapping the way the existing
      entries do. A conservative bias, a gated license, a narrow
      category vocabulary. The caveat is part of the adapter, not an
      embarrassment about it.
- [ ] If the model needs a license acceptance, a login, or a gated
      download, document the exact steps. A future runner must be able
      to reproduce your setup from the doc alone.

## 5. Test fixtures and privacy

- [ ] Adapter tests run against recorded fixtures, never live provider
      calls. Record once, then replay.
- [ ] Fixtures are labeled with the adapter name, the pinned model id,
      and the recording date. An edited real transcript is marked as
      edited, never passed off as synthetic.
- [ ] No real user data in fixtures. Ever. If a fixture was derived
      from a real interaction, it is redacted before it enters the repo,
      and the redaction is noted on the fixture.

## 6. Before you open the PR

- [ ] Run the adapter against the trial-demo suite and confirm the run
      completes, the artifact seals, and the numbers are sane.
- [ ] Confirm `docs/Adapters.md` carries your entry and your capability
      table is in the PR description.
- [ ] Confirm no test was weakened or deleted to make the suite pass.
- [ ] Read the docs-update map in AGENTS.md and update every doc your
      change touches, in the same PR.
