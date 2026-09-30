# Runner performance contract

This document defines what peira's per-call timing numbers mean, how
the three timeout layers behave, and the statistical policy applied to
timing summaries. It is the contract behind the `timing_ms` field on
every call record and the `timing_ms` block in every run summary.

## The four timing components

Every call record carries a `timing_ms` decomposition with four
non-negative components, in milliseconds. The boundaries are exact.

**Admission wait.** Time spent queued for an AIMD controller slot,
from just before requesting the slot to just after acquiring it. It
measures runner scheduling pressure, not provider speed. On the
synchronous single-call path there is no queue, so admission wait is
always zero there. Admission wait is deliberately excluded from buyer
latency (see below).

**Adapter execution.** Exactly `adapter.decide()`'s wall time,
measured inside the worker thread around the decide call itself.
Thread-pool scheduling delay is not adapter execution. It is runner
scheduling, so it falls into harness overhead. A failed attempt still
contributes the time until it raised. An attempt cancelled before its
worker started contributes nothing, because the adapter never ran. An
attempt abandoned by a timeout contributes the elapsed thread time up
to the timeout's fire time: the adapter was executing when the ceiling
fired. Post-abandonment event-loop delay is never counted as adapter
execution.

**Harness overhead.** The residual. Total call wall time minus
admission wait minus adapter execution minus backoff, clamped at zero
against floating-point dust. The components are nested sub-windows of
one monotonic clock, so the true residual is non-negative by
construction; only rounding can push it negative. It covers input
deepcopy, output validation, usage pricing, cache reads and writes,
transcript entry assembly, and record assembly. It also covers
thread-pool scheduling delay on the async path. Transcript entry
assembly and serialization are both excluded: the measurement covers
call start through timing assembly, and no measurement can include
its own write.

**Backoff.** Total sleep time between attempts for this call. Zero
when the first attempt succeeded.

## Buyer latency versus runner scheduling latency

Two different questions get two different numbers.

Buyer latency is `latency_ms_total` on the call record. It is every
attempt's wall time plus the backoff between attempts. It answers how
long a buyer waits for a decision through peira, including retries. It
excludes admission wait, because slot queueing is a property of the
runner's concurrency setting, not of the adapter or the provider.

Runner scheduling latency is admission wait plus harness overhead. It
answers how much of the observed wall time was the harness itself. On
a healthy run both are small next to adapter execution. When they are
not small, something is wrong with the run configuration, not with
the adapter.

The four components plus admission wait reconstruct the full call
wall time. `latency_ms_total` is attempts plus backoff only. Neither
number is derivable from the other. Both are reported.

## Retry and backoff treatment

Each attempt's wall time contributes to adapter execution, including
attempts that failed. Backoff between attempts is its own component
and also folds into `latency_ms_total`. A call that succeeded on its
third attempt shows the adapter execution of all three attempts and
the backoff slept between them. There is no separate per-attempt
breakdown on the record. The transcript carries per-attempt latencies
for audit.

## Cache-hit treatment

A cache hit made no provider call, so it carries no adapter
measurement. Cache-hit records report zero admission wait, zero
adapter execution, zero backoff, and their measured wall time as
harness overhead. They are real records with real timing, and they
are excluded from timing percentile inputs, because a cache lookup is
not a provider measurement. Every timing summary reports how many
cache hits were excluded, so the exclusion is auditable.

## Timeout semantics

Three layers, three different meanings.

**Per-attempt timeout (`call_timeout`, `--call-timeout`).** Bounds
one attempt. A timed-out attempt fails transiently and is retried
until `--max-attempts` is exhausted. When attempts are exhausted the
call seals as a malformed blank record with `timed_out` set and
`timeout_kind` set to `"attempt"`. The attempt's partial wall time
counts as adapter execution, because the adapter was executing when
the ceiling fired. Default 300 seconds. `None` disables the ceiling,
which is not recommended for untrusted adapters.

**Item timeout (`item_timeout`, `--item-timeout`).** Bounds one
case's wall-clock time, covering both variants and all attempts.
When the budget fires, the in-flight arm's task is cancelled (its
adapter threads are abandoned; they cannot be safely killed) and the
arm seals as a malformed blank record with `timed_out` set and
`timeout_kind` set to `"item"`. A completed arm is retained: if the
benign arm finished and the attacked arm exhausts the budget, the
sealed case pairs the real benign record with only an attacked
item-timeout record. If the budget fires during the benign arm, the
attacked arm never started; its record is a typed item timeout with
zero timing (nothing was measured). The timed-out arm's record
attributes only elapsed adapter execution (up to the budget's fire
time), never the whole item budget; admission wait, backoff, and
harness work actually incurred are preserved. The run continues with
the next case. Item timeouts are excluded from timing percentile
inputs and reported as their own count. No timeout budget by default.

**Run timeout (`run_timeout`, `--run-timeout`).** Bounds the whole
run's wall-clock time. When the ceiling fires, dispatch stops and the
in-flight cases drain to completion: they finish honestly instead of
being cancelled mid-call, so their records and timing are complete.
(Draining is bounded: every in-flight case is subject to the
per-attempt timeout, so a stuck adapter burns at most
`max_attempts` x `call_timeout` before its case completes.)
Completed cases are checkpointed and the partial stays resumable: a
timeout-terminated run is resumable, not lost. The artifact seals
with `termination` set to `"timeout"`. A run that ended this way is
analyzable but never rankable, the same rule as the spend-budget
termination. It is hang insurance, not a performance target. No
timeout budget by default.

Timeouts are data, not missing data. Every timeout record carries an
explicit `timeout_kind`: `"attempt"` for per-attempt exhaustion,
`"item"` for the case-level item budget. The kind is what lets
analysis distinguish "the adapter was slow on every attempt" from
"the whole case budget fired". A timeout rate of zero is reported,
never withheld. The absence of timeouts is a measurement too.

## Warmup policy

The runner performs no warmup and excludes no warmup samples. The
AIMD controller starts at concurrency one and ramps up, so the first
calls in a run may be slower than steady state. Cold TLS handshakes,
cold model loads, and controller ramp all stay in the data. The raw
samples are retained, so anyone analyzing a run can see the ramp and
account for it. No samples are ever dropped for being early.

## Statistical policy

Timing summaries are per family and per component. The policy has
five rules.

**Percentile method.** Percentiles use linear interpolation between
closest ranks, the same method as numpy's linear mode. It is
deterministic and backend independent.

**Observation thresholds.** `n` is always reported. Minimum,
median, and the 95th percentile are published whenever `n` is greater
than zero. The 99th percentile needs at least 100 observations per
family. Below a threshold the value is withheld as null, not published
as a number. The 99th percentile on a tiny sample is noise, and
publishing it would be dishonest. The 95th percentile on a tiny sample
is inspectable, not misleading, because `n` is always reported
alongside it.

**Raw sample retention.** Every timing summary retains the raw
samples for each family and component, verbatim at full float
precision: no rounding, no trimming. Rounding to four decimals is
presentation and applies only to the derived statistics (min, median,
percentiles, mean, cv), never to the retained samples.

**No silent outlier trimming.** Extreme samples are data, not noise.
No summary in peira trims, winsorizes, or otherwise drops extreme
timing samples. Anyone who wants a trimmed view computes it from the
retained raw samples and says so.

**Coefficient of variation.** Each component block reports the
coefficient of variation, defined as the population standard
deviation divided by the mean. It is a dimensionless instability
measure, comparable across families and components. When the mean is
zero the coefficient is null. When it exceeds 5 percent the block
sets an `investigate` flag. The flag means look at the raw samples.
It is not a verdict on the adapter.

## Interpreting per-family results

Timing blocks are per family only. Heterogeneous families are never
averaged into a single performance claim, because different families
stress different paths and their latencies are not comparable. There
is no cross-family timing rollup anywhere in peira.

When comparing adapters, compare the same family and the same
component. Adapter execution is the provider-facing number. Harness
overhead and admission wait describe the run, not the adapter. A
family with high backoff had retry storms, which usually means an
unreliable provider or an aggressive timeout setting, not a slow
model.

Cache hits and timeouts are excluded from percentile inputs and
reported as counts next to them. A family with a high timeout count
and fast percentiles did not get faster. It gave up more often.
Read the counts first.

## Provenance

The timing decomposition rides the transcript entry, so replay
rebuilds the exact original measurement. Records written before this
contract existed carry the zero breakdown, which is honest. Nothing
was measured then. The timeout budgets are measurement inputs. They
are sealed in the artifact config, recorded in checkpoints, and
validated on resume. A partial recorded under different ceilings
refuses to merge into a new run.
