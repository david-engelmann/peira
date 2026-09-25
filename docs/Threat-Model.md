# Threat model

## What peira measures

Whether a hostile manipulation of the input changes a decision model's
typed output (Choice / Score / Abstain), measured with paired benign/attacked
controls across 10 attack families.

## What peira does not measure

- Open-ended text generation safety (this is about *decisions*, not prose).
- Whether the model's reasoning is correct — only whether the decision
  changed under attack.
- Real-world deployment risk. A good peira score is evidence about the
  benchmark, not a safety certificate. See the non-certification notice in
  the README.

## Assumptions

- The attacker controls parts of the input (prompts, retrieved context,
  tool outputs) but not the model weights or the harness.
- The defender (adapter author) sets their own thresholds and abstention
  policy; peira measures the resulting behavior.
- Cases are synthetic and authored. They model real attack shapes; they are
  not sampled from real incidents.
