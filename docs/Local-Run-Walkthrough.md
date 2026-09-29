# Local run walkthrough

This guide takes you from a fresh checkout to a scored peira run.
Every command below was run on 2026-09-29 and the output is real.

## Prerequisites

Python 3.10 or later. No API keys needed. The mock adapter and the
trial-demo fixture run fully offline.

## Step 1: Install

```bash
pip install -e .
```

This installs the `peira` package in editable mode. The base tier has
zero third-party runtime dependencies.

## Step 2: Run the demo suite

```bash
peira run --adapter mock --suite trial-demo --out /tmp/demo
```

Real output:

```
  [1/12]
  [12/12]
done: 12 cases (12 eligible)
  spend:           $0.0000 (uncapped)
  ASR (conditional): 0.3333 95% CI 0.1381-0.6094
  benign accuracy:   1.0000 95% CI 0.7575-1.0000
  malformed rate:    0.0000
  refusal rate:      0.0000 95% CI 0.0000-0.2425
  ineligible:        0 (benign_malformed=0, benign_wrong_decision=0, benign_abstained=0)
  ranking eligible:  False (fewer than 200 eligible cases (12); family 'criteria_smuggling' has 4 eligible cases (< 20); family 'score_anchoring' has 4 eligible cases (< 20); family 'state_poisoning' has 4 eligible cases (< 20))
artifact: /tmp/demo/mock-trial-demo.json
analysis lock: 4805b776986b909d…
```

What this tells you:

- **12 cases, 12 eligible.** The trial-demo fixture has 12 cases across
  3 families. All passed the eligibility gates.
- **ASR 0.3333.** The mock adapter flipped on 4 of 12 cases. The mock
  is a reference mechanism exerciser, not a real model, so this number
  is a pipeline check, not a benchmark result.
- **Benign accuracy 1.0000.** The mock got every benign case right.
- **Ranking eligible: False.** The demo fixture is too small to rank.
  Real leaderboards need 200+ eligible cases per suite.

## Step 3: Generate a report

```bash
peira report --run /tmp/demo/mock-trial-demo.json --out /tmp/demo/report.html
```

This writes an HTML report with per-family breakdowns, Wilson
confidence intervals, and calibration plots. Open `/tmp/demo/report.html`
in a browser.

## Step 4: Compare two adapters

Run a second adapter (or the same one with a different seed), then:

```bash
peira compare --runs /tmp/demo/mock-trial-demo.json /tmp/demo/other.json
```

The compare view shows paired McNemar tests, Bradley-Terry strengths,
and per-family win/tie/loss counts. See `docs/Compare-Report-Guide.md`
for how to read the output.

## Next steps

- `docs/What-Peira-Does.md` explains the measurement with a worked example.
- `docs/Adapters.md` covers real adapters (HF models, hosted APIs).
- `docs/Methodology.md` is the full measurement contract.
