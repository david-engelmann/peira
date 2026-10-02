# Signals layer

**Status** Design and implementation, 2026-10-01
**Code** `python/peira/signals.py`
**Tests** `tests/test_signals.py`

A leaderboard that only ranks is a scoreboard. The signals layer is what
makes the monthly State-of-Robustness reports actionable for model
builders. Each monthly report emits `signal:*` items beyond the ranking.
Every signal carries the evidence, a suggestion, a named action, and a
falsifiable success metric. The next report checks the metric. This is
the difference between publishing numbers and closing the loop.

## Signal shape

```json
{
  "signal_id": "high-asr-family:shieldstral-1.0:prompt_injection",
  "type": "high_asr_family",
  "title": "shieldstral-1.0 is highly vulnerable to prompt_injection (ASR 0.65)",
  "evidence": {"adapter": "shieldstral-1.0", "family": "prompt_injection",
               "asr": 0.65, "asr_ci95": [0.60, 0.70], "n_eligible": 400},
  "suggestion": "Treat this family as the top hardening target...",
  "action": "Review prompt_injection cases for shieldstral-1.0...",
  "success_metric": "prompt_injection ASR for shieldstral-1.0 drops below 0.50 by the next report",
  "success_check": {"kind": "family_asr_below", "adapter": "shieldstral-1.0",
                    "family": "prompt_injection", "value": 0.50},
  "score": 80.0,
  "status": "open"
}
```

The `success_metric` is prose for the report reader. The
`success_check` is the same bar in machine form, evaluated by
`check_success` against the next report's data. A metric that cannot be
checked is not a success metric. It is a wish.

## Signal taxonomy

Issue signals flag real robustness problems. Volume signals flag
measurement capacity. The two classes are scored in separate bands.

| Type | Class | Fires when |
| ---- | ----- | ---------- |
| `asr_regression` | issue | Adapter ASR rose more than 5pp vs the previous report |
| `high_asr_family` | issue | Family ASR above 0.50 with at least 20 eligible cases |
| `benign_utility_drop` | issue | Benign accuracy below 0.80 |
| `abstention_spike` | issue | Attacked-arm abstention above 20 percent |
| `calibration_gap` | issue | Attacked-arm ECE above 0.15 |
| `underpowered` | volume | ASR Wilson CI wider than 0.25 |
| `cost_concentration` | volume | Top 3 families take over 60 percent of evaluation spend |

Thresholds live in `DEFAULT_THRESHOLDS` in `signals.py`. They are
parameters, not constants of nature. Tune them in the open and say when
you did.

## The scoring invariant

Volume alone is never a problem, so a volume signal must lose to every
signal that flags an actual issue. The invariant is structural. Issue
signals score in the 50 to 100 band. Volume signals score in the 1 to 49
band. No tuning of thresholds can cross the bands. `test_signals.py`
pins this with the worst case it can construct.

## Open and implemented tracking

Signal status persists in a registry, one JSON file per report series.

```json
{"version": 1, "signals": {
  "high-asr-family:shieldstral-1.0:prompt_injection": {
    "status": "open", "months_open": 3,
    "first_seen": "2026-10", "title": "...", "success_metric": "..."}
}}
```

`roll_forward` carries the registry month to month. New signals enter as
open. An open signal whose `success_check` now holds becomes
implemented. Everything else stays open and its `months_open` counter
increments. Implemented signals stay implemented. The registry is
append-only history, and the monthly report prints the open list with
ages. A signal open for six months is itself a finding.

## Monthly workflow

1. Build the leaderboard payload from the official runs.
2. Run `detect_signals` with the previous report's leaderboard for
   regression detection.
3. A human reviews the emitted signals before publication. Signals are
   computed, not decreed. A signal with bad evidence gets dropped with
   a written reason, not silently.
4. Publish the report with the signal list, each showing its
   evidence, action, and success metric.
5. Roll the registry forward. The next report is graded against this
   one's metrics.

## What signals are not

Signals do not change the ranking. The leaderboard stays a pure
measurement. Signals are the interpretation layer beside it, clearly
labeled as such. Metric definitions and anti-misuse sentences live in
`docs/Analytics-Methodology.md`, which is the canonical home for what
each number means and what it must not be read as. This document does
not duplicate those definitions.
