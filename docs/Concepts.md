# Concepts

Three ideas carry the whole benchmark. Understand these and the scores make
sense.

## 1. Paired controls

Every case is a pair: the same decision scenario, once benign and once
attacked. The adapter's benign answer is the baseline; the attacked answer
is compared against *that baseline*, not against a fixed gold label. This
isolates the effect of the attack from the model's general competence.

## 2. Outcome taxonomy

Per case, per variant, we record a small fixed vocabulary:
`benign_correct`, `decision_changed`, `targeted_attack_success`,
`malformed`. Every metric in the methodology is an aggregation over these
four fields. If you can read the taxonomy, you can audit any score down to
the case that produced it — that's what drill-down receipts are for.

## 3. Analysis lock

A run artifact is sealed with a sha256 hash over its inputs (config,
dataset version, peira version). Change anything after the fact and the
lock breaks; CI rejects the artifact. This is what makes the leaderboard
trustworthy without trusting the submitter: the numbers are either
reproducible from the locked inputs or they're rejected.
