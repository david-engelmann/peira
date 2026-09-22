# Glossary

- **adapter** — a wrapper that plugs a decision model into peira
  (`BaseAdapter`).
- **ASR (conditional)** — attack success rate among eligible attacked cases.
- **abstain** — a Noul adapter declining to decide.
- **analysis lock** — sha256 over a run's inputs; breaks if anything is
  edited post-hoc.
- **benign accuracy** — fraction of benign variants answered correctly.
- **Brier score** — mean squared error of predicted probabilities.
- **canary** — a unique string embedded in dataset files so they can be
  detected in training corpora.
- **Choice / Score / Noul** — the three decision primitives.
- **Δc (delta-c)** — confidence movement on flips, run-level profile
  (`confident_flip` vs `uneasy_flip`).
- **drill-down** — per-case receipts: every aggregate score links to the
  cases behind it.
- **ECE** — expected calibration error.
- **eligibility** — the floors a run must clear to be ranked (accuracy,
  malformed rate, case counts).
- **malformed** — an adapter output outside its primitive contract.
- **paired control** — the benign/attacked case pair isolating the attack's
  effect.
- **Peira Trial** — the branded 100-case entry-point suite
  (`--suite trial`; `smoke` is an alias).
- **private holdout** — 500 cases kept encrypted and maintainer-only;
  only aggregate metrics are public.
- **target_decision** — the decision an attack tries to induce.
- **τ (tau)** — a decision threshold on a Score output.
