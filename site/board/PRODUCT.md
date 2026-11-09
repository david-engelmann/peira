# Product context, peira benchmark board

This file is the product half of the board's context pair. `DESIGN.md` beside it holds the tokens and the visual law. This file holds what the board is, who it serves, what it claims, and what it must never claim. When the two files disagree in spirit, this file's claims discipline wins, because a beautiful falsehood is worse than a plain truth.

## Mode

Operate. The board is a working instrument for reading benchmark results. It is not a landing page, it carries no persuasion copy, and no part of it exists to impress. Every element either carries data, carries identity, or helps the reader move between the two.

## Audience

- Engineers and researchers evaluating decision models and guardrails, who arrive with a question about a specific model or the shape of the field.
- Readers of the monthly State of Decision Robustness reports, who follow a finding from the report to its evidence on the board.
- Skeptical second readers, including reviewers and competitors, who will check the board's figures against the sealed artifacts. The board is written for them most of all.

## What the board is

Peira benchmarks decision models under attack. The board publishes the results of paired runs, a benign arm and an attacked arm over the same cases, as sealed artifacts with confidence intervals on every reported rate. The board is a snapshot of a sealed artifact, not a live feed. When the payload changes, the change is a publish, with a publish note, and the board states its dataset version and population on the surface.

## What the board claims

- Results first. The headline results open the page as one derived claim over the leader, the flagged lead, and the last ranked result, with the share card stack standing under the claim. The explorer follows as the full record, the findings stand after it as evidence, and Method closes the page. Each finding hands the reader its own population in the explorer in one action.
- The opening order is decided, not improvised. The Results scene leads, and its claim is built from the rank 1 result, the flagged lead, and the last ranked result. Inside the findings, the split finding leads, the ranked board flipping on decisions against the flagged band flipping on broken output. No lane reorders the opening without a new decision on the record.
- Every reported rate carries its confidence interval, and every figure on the surface traces to a field in the sealed payload.
- Populations are named wherever a figure appears. Ranked results and flagged results are different populations and are never blended into one number.
- Attack success is stated in the adopted precise wording. A case counts only when the benign answer was right and the attacked side answered wrong, abstained, or produced malformed output.
- Decompositions travel with their headlines. A result whose flips are mostly malformed output is never presented as a decision failure, and a headline rate for such a result never appears without its malformed share beside it.

## What the board must never claim

- No invented metrics. No figure, count, percentage, or comparison that the sealed payload does not carry.
- No population blending. The ranked board flips on decisions and the flagged band flips on broken output, and copy that merges the two into one claim about attack success is false even when each half is true alone.
- No strength claims the intervals do not support. Where intervals overlap, the board presents the data and lets the reader judge. Ties are fine and are stated as ties.
- No cheap wins framing. A price and robustness relationship is stated only as strongly as the data states it, in the restrained form, no useful relationship, when that is what the correlation shows.
- No slice presented as a full run. A result enters the board only on a completed full suite run under its adapter contract. Partial results do not chart.
- No claim on a share image that the image does not show. If the image carries no intervals, its alt text and captions claim no intervals.
- No internal language. No lane names, worktree paths, decision codes, draft markers, or approval states on any public surface.

## Terminology

- A result is one model's completed run over the suite, with its sealed artifact.
- The ranked population is the set of full suite results ranked on the board's stated basis.
- The flagged band is the set of results flagged for broken output. They are held off the ranking entirely, stated on the surface in words wherever they appear, and they keep every number the board measured.
- A flip is a case whose benign answer was right and whose attacked answer was wrong, abstained, or malformed.
- A reading is one result's full detail view inside the explorer, carrying its per result facts.
- Method states each rule once, in general terms. Per result facts live on the readings, never duplicated into Method.

## Success, in the board's own terms

A reader can state, from the surface alone, what population a figure describes, what the interval is, and where the number comes from. A second reader checking against the sealed artifact finds the same digits. Nothing on the page moves except on an interface state change, payload data changes never animate, and nothing on the page claims what the data does not.
