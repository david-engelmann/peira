# Announcement package

**Status** Launch brief, verified on 23 October 2026
**Scope** Repository announcement copy, LinkedIn copy, and publication standards for the v2 launch
**Live board** [peiratrial.dev](https://peiratrial.dev/)

This package gives the publisher launch copy for peira v2. It records the verified state of the current board and the refresh rule for the freeze publish that lands later on 23 October 2026.

## Verified launch facts

**Board.** The live board at [peiratrial.dev](https://peiratrial.dev/) presents the v2 results.

**Dataset.** The full v2 suite uses dataset v2.6.0. It contains 4,701 paired benign and attacked cases across 11 attack families. The board also carries guardrail slice rows measured on their defined 373-case abstain population. Slice results describe that subpopulation and are not full-suite results.

**Coverage.** The current board carries 36 published entries covering 35 distinct models. One distinct model has ranked measurements on two wires, so the entry count and the model count differ.

**Standing.** Thirty-one distinct models are ranked and four are flagged. A flagged model appears without a rank because its malformed response rate is above the 5 percent admission threshold.

**Evidence.** A data integrity audit reconciled all 36 published entries to their sealed artifacts. It matched 396 of 396 compared fields, and every staged artifact passed verification.

**Robustness tax.** The tax applies to full-suite ranked entries. It adds 0.9872 minus benign accuracy and attacked ECE minus 0.0479. The benign frontier is set by `jev-1.14.0`, and the attacked ECE frontier is set by `claude-sonnet-5-5`. Slice rows do not set the full-suite frontier and carry no tax.

**Measured field.** Celeris and Perplexity `pplx-decider` are measured and published on the current board. Clef omni has a verified seal and joins the board in the freeze publish, completing the Clef family.

## Launch refresh rule

A freeze publish lands later on 23 October 2026. It adds newly sealed models and the rebuilt front end. Before either announcement below is posted, refresh the counts, named results, and tax frontier from the new published payload. Preserve the distinctions in this brief between entries and distinct models, full-suite rows and slice rows, and ranked and flagged models.

## Repository announcement copy

**Title** peira v2 results are live

Peira measures whether hostile input can flip a decision model's typed output. Accuracy on clean input answers only part of the deployment question. Peira asks whether an attacker can change the answer.

The v2 board is live at [peiratrial.dev](https://peiratrial.dev/). It publishes sealed measurements on dataset v2.6.0 with paired benign and attacked cases, Wilson 95 percent confidence intervals, benign accuracy, calibration, malformed rate, cost, and per-family results.

The launch field includes Celeris and Perplexity `pplx-decider`. Four models are flagged under the published admission rules because their malformed response rates exceed 5 percent.

The robustness tax compares full-suite ranked entries with the full-suite frontier. Jev 1.14.0 sets the benign accuracy frontier at 0.9872. Claude Sonnet 5-5 sets the attacked ECE frontier at 0.0479. Slice rows stay outside that frontier because they measure a defined subpopulation rather than the full suite.

A low attack success rate is not a safety certificate. It means the model held against the attacks peira measures, under the published methodology and on the stated population. Peira is a measurement, not a certification or a guarantee.

Read the results on the [live board](https://peiratrial.dev/) and the code and methodology in the [repository](https://github.com/david-engelmann/peira).

## LinkedIn copy

We built peira to answer a narrow question. When hostile input tries to change a decision, does the model hold?

The v2 board is live at peiratrial.dev. It reports 36 entries covering 35 distinct models on dataset v2.6.0. Thirty-one distinct models are ranked, and four are flagged because their malformed response rates exceed the admission threshold.

Each result traces to a sealed run artifact. The board reports attack success with Wilson 95 percent confidence intervals and shows benign accuracy, calibration, malformed rate, cost, and per-family results beside it.

The robustness tax uses the full-suite frontier set by Jev 1.14.0 on benign accuracy and Claude Sonnet 5-5 on attacked ECE. Slice runs do not set that frontier. That distinction keeps a 373-case subpopulation measurement from defining the benchmark for runs that measured all 4,701 paired cases.

Peira is open source and reproducible. It is not a safety certification. It is a public measurement of how decision models behave when the input is trying to move the answer.

Results at peiratrial.dev
Code and methodology at github.com/david-engelmann/peira

## Publication standards

- Publish only numbers that appear on the live board or in a sealed run artifact.
- Count each distinct model once, even when that model has measurements on more than one wire.
- Keep entry counts separate from distinct model counts.
- State the admission reason when describing a flagged model, and present its results without a rank.
- Keep slice rows outside the full-suite robustness tax frontier.
- Do not describe peira as a certification, a safety guarantee, or evidence about attacks outside the published suite.
- Refresh this package from the freeze payload before external posting, then rerun the public surface check and the copy scan.
