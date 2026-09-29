# Holdout Query Budget

Each blind holdout re-execution is an adaptive query. Reusable-holdout
theory (Dwork et al., Science 2015) shows that validity degrades with
unbounded reuse. The holdout therefore carries a published query
budget. The budget bounds how many times the holdout can be queried
before it must rotate. The counter is public. The contents never are.

## The budget

Twelve blind re-executions per adapter line per calendar year. An
adapter line is a named adapter at a pinned revision, for example a
specific model checkpoint or a versioned guardrail release. A new
revision starts a new line with a fresh budget.

Twelve per year is a monthly cadence. It is enough for quarterly
ranking refreshes, tiebreak disputes, and incident re-checks, with
headroom. It is small enough that adaptive overfitting cannot
accumulate silently across years.

## The public counter

`docs/Holdout-Query-Log.md` records every blind re-execution. Each entry
carries the date, the adapter line, and the execution count used. It
carries no case IDs, no prompts, no scores, and no per-case outcomes.
The log is append-only. The maintainer updates it within one business
day of each re-execution.

When an adapter line exhausts its twelve executions, further blind
re-executions for that line wait for the next calendar year or for a
holdout rotation, whichever comes first. The public leaderboard keeps
showing the last valid blind score with its date.

## Rotation policy

The holdout rotates on two triggers.

**Scheduled rotation.** Every calendar quarter, the maintainer tops up
the pool with newly authored cases and retires the oldest shard into
the public set. The rotation is announced in the query log. The new
contents are never disclosed.

**Budget rotation.** If total executions across all adapter lines reach
four hundred in a calendar year, the maintainer rotates the full pool
early. Four hundred is a policy limit on total yearly executions, set
conservatively. It is not derived from a specific reusable-holdout
bound for the 500-case pool.
The rotation is announced in the query log.

**Compromise rotation.** On suspected leak, the affected shard rotates
immediately, per `docs/Holdout-OpSec.md`. This is independent of the
query budget.

## What the counter does not reveal

The counter reveals how many times the holdout was queried and by which
adapter lines. It reveals nothing about the cases, the prompts, the
correct decisions, or the scores. An adapter line that appears in the
log has not necessarily seen any particular case. The blind execution
protocol in `docs/Holdout-OpSec.md` ensures adapters cannot detect
holdout runs from public runs.
