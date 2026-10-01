# Announcement package

**Status** Prepared draft, 2026-10-01. NOT PUBLISHED.
**Covers** Product and positioning lane announcement preparation.

This package holds the launch copy for peira's public announcement.
It is a draft. Nothing here is published, posted, or scheduled.
Publishing waits on three things. David's explicit approval, the
perfection gate (no announcements before it, per program rule), and
the open display decisions D5 (display scope), D6 (announcement
sequencing), and D16. The drafts assume the staged sequencing D6
recommends and mention v2 as in-progress work per the D10
recommendation.

Copy bar. No em dashes, no colons, no semicolons. Verified by
codepoint scan before this file is handed anywhere.

## Repo announcement draft

**Title** peira, an adversarial benchmark for decision models

If you use a language model to make decisions, you already know the
uncomfortable question. It works on your test set. What happens when
someone is actively trying to make it decide wrong.

peira is our attempt to answer that question properly. It is an open
benchmark that attacks decision models the way real attackers do and
measures whether the decision flips.

**What it tests.** Approve and deny decisions, numeric scores, and
abstentions across 25 attack families. Prompt injection buried in tool
output. Instructions hidden in retrieved documents. Fake
authorization signals. Reordered evidence. Flattery aimed at the judge
instead of the case. Each family is grounded in published research or
observed failures, and the taxonomy doc cites the source for every
one.

**How it measures.** Paired benign and attacked cases, so every number
is a causal claim about the attack, not a vibes-based score. 95%
confidence intervals on every number. A blind holdout set with
pseudonymized IDs so models cannot detect the evaluation. Severity
grading on every case, because a flipped wire transfer is not the
same event as a flipped lunch recommendation.

**What you get.** A leaderboard with per-family breakdowns,
calibration views, and a documentation pack per run that maps results
onto incident-severity tiers for teams that need the paperwork, not
just the score.

The code is MIT licensed. The dataset is CC-BY-4.0. Reproduce any
number from the sealed artifacts. The provenance chain is part of the
design.

v2 is in progress and grows the family set further. The benchmark
itself is the product. We are not selling a model or a guardrail.

[PLACEHOLDER. Headline results go here once the official runs land.
No numbers are claimed before then.]

## LinkedIn post draft

We built the benchmark we wanted to exist.

peira attacks decision models across 25 attack families, from prompt
injection in tool output to poisoned retrieval corpora to flattery
aimed at the judge, and measures whether the decision flips. Paired
cases, confidence intervals on everything, a blind holdout, and
severity grading because not all flips are equal.

Open source, reproducible down to the sealed artifact, with a per-run
documentation pack for teams that answer to regulators.

The official results are coming. The methodology is public today.

[PLACEHOLDER. Link to the leaderboard and the repo at publish time.]

## Publishing checklist

- [ ] David approves the final copy
- [ ] Perfection gate passed (no publication before it, per program
      rule)
- [ ] D5, D6, D16 display decisions resolved
- [ ] Official evaluation runs sealed (A12/A13) and artifacts published
- [ ] Placeholders above replaced with real numbers, each traceable to
      a sealed artifact
- [ ] peiratrial.dev leaderboard live with real data and no mock banner
- [ ] Copy bar re-verified on the final text by codepoint scan
- [ ] Public-surface CI check green on all new copy

## Notes for the publisher

Post the repo announcement first, then the LinkedIn post the same day
pointing at it. Do not post numbers anywhere that are not on the
leaderboard. Do not describe peira as a certification or a safety
guarantee. It is a measurement. If asked about coverage, point at the
foreseeable-misuse matrix and name the gaps. The gaps are part of the
story.
