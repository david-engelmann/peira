# Holdout Query Log

Public counter for blind holdout re-executions. See
`docs/Holdout-Query-Budget.md` for the budget policy.

Each entry records the date, the adapter line, and the cumulative
execution count for that line in the calendar year. No case IDs, no
prompts, no scores, no per-case outcomes appear here.

## 2026

No blind re-executions have been run yet. The holdout was sealed on
2026-09-27. The budget is twelve executions per adapter line per
calendar year.
<!--
Entry format (append-only, newest last):

- 2026-10-15 | example-guardrail v1.2.3 | execution 1 of 12 in 2026

On rotation, add a line like:

- 2026-10-01 | ROTATION | scheduled quarterly rotation announced
-->
