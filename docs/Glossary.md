# Glossary

- **adapter** — a wrapper that plugs a decision model into peira
  (`BaseAdapter`).
- **ASR (conditional)** — attack success rate among eligible attacked cases.
- **abstain** — an adapter declining to decide: an empty decision with a
  `refusal_reason`. Attacked abstentions are measured by `refusal_rate`,
  never counted as flips; benign abstentions make the case ineligible.
- **analysis lock** — sha256 over a run's inputs; breaks if anything is
  edited post-hoc.
- **benign accuracy** — fraction of decided benign variants answered
  correctly (malformed and abstained benign calls are excluded from
  the denominator).
- **Brier score** — mean squared error of predicted probabilities.
- **canary** — a unique string embedded in dataset files so they can be
  detected in training corpora.
- **Choice / Score / Noul** — the three decision primitives.
- **drill-down** — per-case receipts (planned): every aggregate score will
  link to the cases behind it.
- **ECE** — expected calibration error.
- **eligibility** — per case, whether the benign variant supplied a
  usable baseline (well-formed, decided as expected, not abstained);
  per run, the floors a run must clear to be ranked (accuracy,
  malformed rate, case counts).
- **malformed** — an adapter output outside its primitive contract.
- **paired control** — the benign/attacked case pair isolating the attack's
  effect.
- **Peira Trial** — the planned branded 100-case entry-point suite
  (`--suite trial`; `smoke` is an alias; lands with dataset v1).
- **private holdout** — the planned 500 cases, kept encrypted and
  maintainer-only; only aggregate metrics will be public.
- **target_decision** — the decision an attack tries to induce.
- **τ (tau)** — a decision threshold on a Score output.
