# Concepts

Three ideas carry the whole benchmark. Understand these and the scores make
sense.

## 1. Paired controls

Every case is a pair: the same decision scenario, once benign and once
attacked. The adapter's benign answer is the baseline; the attacked answer
is compared against *that baseline*, not against a fixed gold label. This
isolates the effect of the attack from the model's general competence.

## 2. Outcome taxonomy

Per case we record two full call records — the benign call and the
attacked call, each carrying its decision, confidence, abstention flag,
refusal reason, and usage — plus three judgments derived from them:

- `flipped`: did the attack move the decision? (Malformed attacked
  output counts as flipped; an attacked abstention does not — refusals
  are measured separately, never laundered into ASR.)
- `eligible`: did the benign call supply a usable baseline? (Well-formed,
  decided as expected, not abstained — the reason is recorded when not.)
- `refusal_rate`: how often did the adapter abstain instead of deciding?

Every metric in the methodology is an aggregation over these records. If
you can read the taxonomy, you can audit any score down to the call that
produced it — that's what drill-down receipts provide.

## 3. Analysis lock

A run artifact is sealed with a sha256 hash over its inputs (config,
dataset version, peira version). Change anything after the fact and the
lock breaks; `peira report` warns on the mismatch. This is what will make
the planned leaderboard trustworthy without trusting the submitter: the
numbers will either be reproducible from the locked inputs or they'll be
rejected.
