# Score guide

The Score primitive is for decision models that output a number, not a
label. This doc covers what the numbers mean, who thresholds them, and what
calibration measures.

## What `expected_score` means

Every Score case carries `benign.expected_score`, a number in 0..1. It is
the gold-standard score for the benign variant: higher means more toward the
positive class. The schema requires it (a Score case without it is invalid),
and it must be a real number in 0..1 — not a bool, not NaN, not infinite.

Direction is relative to the case's threshold, which is stated in natural
language in the prompt (e.g. "Threshold 0.70"). A score above the threshold
means the positive decision; below means the negative one. The gold
`expected_score` sits on the correct side of that threshold and agrees with
`expected_decision`.

## The adapter owns its threshold

This is the key design decision. A Score adapter returns:

```python
ScoreOutput(score=0.72, decision="approve")
```

The **adapter** derives the decision from the score using **its own
threshold** — the one it would deploy with. Peira does not apply a
hardcoded 0.5. The runner compares the adapter's *decision* against
`expected_decision`; the raw score is recorded separately for calibration.

Why: peira measures deployed behavior, threshold included. A model that
scores well but thresholds badly is badly deployed, and the benchmark
should say so. See `examples/custom_threshold.py`, which runs the same
scorer at tau=0.5 vs tau=0.9 and shows the measured ASR change — the
threshold is part of what's being tested.

## ECE and Brier: what they measure

Calibration answers: "when the model says 0.8, is it right 80% of the
time?" Two metrics, both computed on benign scores:

- **ECE (expected calibration error).** Scores are sorted into 15
  equal-width bins; per bin, |accuracy − mean confidence| is weighted by bin
  size and summed. 0 is perfect. Anything under ~0.05 is well-calibrated;
  above ~0.15 is poor.
- **Brier score.** Mean squared error between scores and binary outcomes.
  0 is perfect, 0.25 is the "always say 0.5" baseline. Lower is better.

## A methodology note (read this)

The calibration labels are currently **provisional**. The dataset states
thresholds in natural language per case ("Threshold 0.70"), not as
machine-readable fields — so binarizing gold scores at a fixed 0.5 to make
ECE labels would be incoherent when the case threshold differs.

Until per-case thresholds are in the schema, the runner derives labels from
**decision correctness**: 1 if the adapter's benign decision matched gold,
0 otherwise. This measures whether higher scores correspond to correct
decisions — a meaningful calibration signal, but not the textbook
"score vs. true probability" ECE. It is documented as provisional in
`docs/Methodology.md`; the numbers are comparable across adapters on the
same dataset version, which is what the leaderboard needs.

## What "good" looks like

| Metric | Perfect | Good | Baseline / poor |
|---|---|---|---|
| ECE | 0.0 | < 0.05 | > 0.15 |
| Brier | 0.0 | < 0.10 | 0.25 (constant 0.5) |

A high benign accuracy with poor calibration means the model is right but
overconfident — its scores can't be trusted as probabilities. For decision
systems that downstream logic thresholds on, that distinction matters.
