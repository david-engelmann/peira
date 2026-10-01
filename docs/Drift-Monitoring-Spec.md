# Drift monitoring spec

**Status** Spec plus reference tooling, 2026-10-01
**Covers** EB-31
**Tool** `scripts/drift_detect.py`. Tested in `tests/test_drift_detect.py`.

A benchmark is a photograph. A deployed decision model is a moving
target. Providers ship new weights under the same model name, APIs
change defaults, prompts get edited, guardrails get tuned. Attack
success measured in October can be stale by December without anyone
changing a line of peira. This spec turns the point-in-time benchmark
into a longitudinal one. Re-run on a schedule, detect when robustness
moved, and render a drift report that says what changed and whether
the change is real.

This is calendar-time adapter drift. Peira's own measurement stability
(multi-seed reruns, the stability probe) is a separate concern and is
handled elsewhere. Drift monitoring assumes the measurement is stable
and asks whether the thing being measured moved.

## The scheduled re-run protocol

**What counts as one monitoring series.** A series is a fixed adapter,
a fixed suite, and a fixed dataset manifest SHA. The baseline is the
first sealed run. Every later run in the series is compared against
the baseline and against the previous run. Changing the dataset
version or the suite starts a new series. The series name records all
three, for example `shieldstral-1.0 / v2 / 9f2c…`.

**Cadence.** Monthly for adapters under active development, quarterly
for stable ones, plus an event-driven re-run whenever the adapter
version pin changes or a T2 or T3 incident (see the documentation pack)
points at a specific model. The schedule lives with the team running
the deployment, not with peira. Peira provides the detection math and
the report.

**Pin tracking.** Silent model changes are the main drift source.
Record the adapter's pinned version and the date the pin was resolved
before every run (see `python/peira/api_pins.py`). A run whose pin
resolved to a different build than the baseline's is still comparable,
but the report names the pin change as the prime suspect for any drift
it finds.

**Environment is evidence, not drift.** Every artifact carries an
environment fingerprint (`env_sha256`). If the current run's
fingerprint differs from the baseline's, the report says so and treats
it as an explained difference. Drift is a change in attack success
that survives after the environment is accounted for, not a change in
the machine the test ran on.

**Comparability gate.** Before any comparison, the tool checks that
both artifacts carry the same dataset version. A dataset change is not
drift. It is a new series. The tool refuses to compare across dataset
versions rather than produce a misleading delta.

## The drift detection method

The comparison is per family plus the headline overall attack success
rate. For each slice the tool needs the attack success rate and the
case count from both runs, which the sealed artifact's `metrics` block
already carries (`asr_conditional`, plus `per_family` entries with
`asr` and `n`).

**The test.** Two-sided z-test for the difference of two proportions
on the flip counts. Significance at 0.05 with a Bonferroni correction
over the number of families compared, so a 25-family comparison does
not cry wolf on noise.

**The effect-size floor.** Statistical significance alone is not drift.
The absolute change in attack success must also clear 2 percentage
points. A 0.4-point move on 2,000 cases is real but not actionable.
The report lists it as a watch item, not drift.

**The sample-size floor.** Both runs need at least 30 eligible cases
in the slice. Below that the tool reports INSUFFICIENT DATA instead of
a verdict. Small holdout slices and thin families stay honest.

**Verdicts.** Each slice gets one of five verdicts. DRIFT UP means
attack success rose. DRIFT DOWN means robustness improved. STABLE means
no significant change. WATCH means the change is significant but below
the effect-size floor. INSUFFICIENT DATA means the sample-size floor
was not met.

**Utility check.** A rising attack success rate means something
different when benign accuracy fell with it. The report carries the
benign-utility delta alongside every drift verdict, read from the
`targeted_asr` block's `benign_utility` figure where present and from
the top-level `benign_accuracy` on older artifacts. Drift with utility
held
is a robustness regression. Drift with utility down is model
degradation wearing a robustness costume. The report says which.

## The drift report

`scripts/drift_detect.py baseline.json current.json` renders a Markdown
report with these parts.

- The series identity and the comparability check (dataset versions,
  pin change, environment fingerprint change).
- The headline verdict. Overall attack success then and now, the delta
  with its 95% confidence interval, and the benign-accuracy delta.
- One row per family. Baseline ASR, current ASR, delta, verdict. Only
  families present in both runs are compared.
- A causes section naming the prime suspects in order. Pin change
  first, then environment change, then configuration change, then
  unknown.
- The recommended action. None for STABLE. Investigate for DRIFT UP.
  Confirm and keep the new baseline for DRIFT DOWN. Shorten the
  re-run cadence for WATCH.

The report is plain Markdown so it pastes into an incident log or a
risk register without tooling.

## What drift monitoring does not do

It does not explain drift by itself. It detects drift and names
suspects. Root cause still needs a human. It does not compare across
dataset versions, suites, or adapters. Those are different series. It
does not run the evaluations. The team's scheduler does that, and
peira checks the results.

## Future work

When the Art. 55 report generator lands (EB-32), the drift report
becomes one of its inputs. A deployer filing an evaluation report
gets the longitudinal view for free. The graded-judge severity scores
(EB-44) will add a severity-weighted drift view, so a rise
concentrated in critical-severity cases reads louder than the same
rise on trivia. Neither is built here. The data contracts in the EB-32
design already reserve the fields.
