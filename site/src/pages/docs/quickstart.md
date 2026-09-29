---
layout: ../../layouts/Docs.astro
title: Quickstart
---

# Quickstart

From a fresh checkout to a scored run in about five minutes. No API
keys, no network, no cost. The mock adapter and the trial-demo fixture
run fully offline.

## Install

You need Python 3.10 or later, and a checkout of the repo.

```bash
pip install -e .
```

The base tier has zero third-party runtime dependencies, so this
finishes fast.

## Run the demo suite

```bash
peira run --adapter mock --suite trial-demo --out /tmp/demo
```

Real output from an actual run follows.

```
  [1/12]
  [12/12]
done: 12 cases (12 eligible)
  spend:           $0.0000 (uncapped)
  ASR (conditional): 0.3333 95% CI 0.1381–0.6094
  benign accuracy:   1.0000 95% CI 0.7575–1.0000
  malformed rate:    0.0000
  refusal rate:      0.0000 95% CI 0.0000–0.2425
  ineligible:        0 (benign_malformed=0, benign_wrong_decision=0, benign_abstained=0)
  ranking eligible:  False (fewer than 200 eligible cases (12); family 'criteria_smuggling' has 4 eligible cases (< 20); family 'score_anchoring' has 4 eligible cases (< 20); family 'state_poisoning' has 4 eligible cases (< 20))
artifact: /tmp/demo/mock-trial-demo.json
analysis lock: 4805b776986b909d…
```

What this tells you. Twelve cases across three families, all eligible.
The mock flipped on 4 of 12, hence ASR 0.3333, and the interval is wide
(0.14 to 0.61) because 12 cases is a tiny sample. The mock is a
reference mechanism exerciser, not a real model, so treat this number as
proof the machinery works, not as a benchmark result. Ranking eligible
is False because real leaderboards need 200 or more eligible cases per
suite, and this fixture is far below that.

## Make a report

```bash
peira report --run /tmp/demo/mock-trial-demo.json --out /tmp/demo/report.html
```

This writes an HTML report with per-family breakdowns, Wilson
confidence intervals, and calibration plots. Open the file in a browser
to look around.

## Compare two adapters

Run a second adapter, or the same adapter with a different seed. Then
compare the two artifacts.

```bash
peira compare /tmp/demo/mock-trial-demo.json /tmp/demo/other.json
```

The compare output shows paired tests, per-family win/tie/loss counts,
and which differences actually clear the statistical bar. The
[interpreting results](interpreting-results) page explains how to read
every number and when a difference counts as real.

## Next steps

- [Adapter setup](adapter-setup) for real models (local Hugging Face
  guardrails, hosted APIs, and local baselines)
- [Interpreting results](interpreting-results) for the leaderboard,
  Families, Calibration, Frontier, and Compare views
- [FAQ](faq) for the usual questions

That is the whole loop. Twelve cases, five minutes, one HTML report.
From here the only change is swapping the mock adapter for a real one.
