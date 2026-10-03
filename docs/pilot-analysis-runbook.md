# Pilot Analysis Runbook

How to run the full pilot analysis when results land.

## Prerequisites

- Pilot runs completed and sealed in `runs/` (or `$PEIRA_RUNS_DIR`)
- Each run passes `qualifies_for_leaderboard`
- Suite is `v2`

## Generate the analysis

```bash
# From the repo root with the venv activated:
.venv/bin/python -m peira.pilot_report \
    --runs-dir runs \
    --output pilot-report.html
```

This runs the complete pipeline:
1. `pilot_analysis.load_pilot_runs` scans the registry for qualifying v2 runs
2. `pilot_analysis.analyze_pilot` computes the family matrix, attack
   effectiveness, pairwise McNemar + BH, Friedman + Nemenyi ranking,
   and cost effectiveness
3. `pilot_report.render_pilot_report` renders everything as a single
   self-contained HTML file with inline SVG charts

## What the report contains

- Per-model x per-family ASR heatmap with values in cells
- Most effective attacks ranked by mean ASR
- Friedman ranking with Nemenyi critical-difference whiskers
- All-pairs McNemar with Benjamini-Hochberg correction
- Cost vs ASR scatter (log scale) and cost-effectiveness table

## Interpreting results

- **ASR** (attack success rate). Lower is better. The model resisted
  the attack.
- **Conditional ASR** conditions on the model getting the benign case
  right. A model cannot look robust by failing easy cases.
- **McNemar p < 0.05 (BH-adjusted)** means two models differ
  significantly on paired cases.
- **Friedman p < 0.05** means the models differ somewhere. The
  Nemenyi whiskers show which pairs differ.
- **Cost per correct** is the most honest efficiency number. It
  counts both benign accuracy and attack resistance.

## Reproducibility

Every number traces to a sealed artifact. The analysis never modifies
artifacts. Re-running on the same `runs/` directory produces
byte-identical output (the loader sorts by adapter name).
