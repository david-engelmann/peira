# RUNPATH-AUDIT findings (peira FINAL-AUDIT, 2026-10-03)

Worktree: `~/workspace/peira-final-audit` @ `2821b7fd` (branch `final-audit-2026-10-03`).
Method: real `peira run --adapter mock --suite trial-demo` (PEIRA_NO_RUST=1),
hand-recomputation of metrics from sealed per-case results, read-only code
review of `runner.py` / `metrics.py` / `artifacts.py` / `runs_registry.py` /
`site/scripts/ingest.py`, plus throwaway forgery experiments in /tmp
(never touching the repo).

## What was checked and is CLEAN

- **Metric internal consistency.** Recomputed ASR/BenignAcc/malformed_rate
  from sealed per-case results via `PerCaseResult.from_dict`: all match the
  sealed metrics (ASR 4/12 = 0.3333; the 5th-decimal difference is the
  documented deliberate `_round4` rounding, "well below every effect size").
  `check_eligibility` recomputed from results matches sealed
  `ranking_eligible`.
- **Malformed gate boundary.** `check_eligibility` uses `> 0.05`: exactly
  5.00% malformed passes, 5.5% fails. Matches the documented "malformed
  rate at most 5%" rule. Not a hole (verified empirically with 200-case
  synthetic fixtures).
- **Runner→metrics boundary.** Final artifact and checkpoint paths both
  build `ordered` → `result_dicts` from the same list, then score
  `ordered`; sealed results and sealed metrics are the same data.
- **Resume path.** `validate_partial` requires lock verify, suite/dataset/
  seed/flag match, and termination ∈ {partial,budget,timeout}; final
  scoring runs over the merged result list. Strict; no stale-metrics hole.
- **Ingest mechanical gates that work:** lock verify, artifact_version=="3",
  mock discipline, NaN/Inf rejection (`check_finite`), duplicate
  (adapter,version,suite) identity rejection, division declaration gate,
  closed vocabularies on the legacy v3 block.
- **Registry honesty.** `runs_registry` index is an mtime-fresh cache;
  `verify_runs` is documented as self-consistency only. No false claims.

## P0

### P0-1. `qualifies_for_leaderboard` trusts the sealed `ranking_eligible` flag instead of recomputing it — full forgery path demonstrated end to end
`runs_registry.py:1054` reads `metrics.get("ranking_eligible")` from the
artifact rather than recomputing `check_eligibility` from the sealed
per-case results. Combined with the documented holder-adversary limit of
`verify()` (anyone holding the file can edit and re-seal; `verify()`
returns True — `artifacts.py:845`), the ranking gate is pure
self-attestation.

Demonstrated with throwaway copies in /tmp (repo untouched):
1. Took the real 12-case trial-demo run (true ASR 0.3333, true n=12).
2. Relabeled `suite`→"public", `dataset_version`→"2.5.1",
   `manifest_sha256`→real v2 SHA, added `config.division`, hand-edited
   `metrics.asr_conditional`→0.01 and `metrics.ranking_eligible`→true,
   re-sealed. `verify()` → True.
3. `qualifies_for_leaderboard` → `(True, 'qualifies')`.
4. `site/scripts/ingest.py` accepted it into site-data.json as a v2
   public row: ASR 0.01, ranking_eligible=true, 12 cases.

Fix direction: recompute `check_eligibility` (and ideally the headline
metrics) from `artifact.results` inside `qualifies_for_leaderboard`;
fail closed on mismatch. The data needed is already in the artifact.

### P0-2. No append-only out-of-band lock log exists for run artifacts
`verify()`'s own docstring (`artifacts.py:845-854`) says tamper detection
"for the official run" requires "publishing original lock values
out-of-band (append-only log)". Append-only logs exist for dataset tags
(`scripts/check_dataset_tags.py`) and holdout queries, but nothing
publishes run-artifact lock values. Until that exists, a re-sealed
forgery is indistinguishable from the original — which is what makes
P0-1 exploitable rather than theoretical. Before the $906 run: stand up
the lock log (or document that official runs are self-reported).

## P1

### P1-1. Runner/site vocabulary mismatch on `suite`: ingest rejects real runner output
The runner seals the suite ID (`suite="trial-demo"`, would be `"v2"` for
the official run). `ingest.py` fails closed on `suite not in
("public","holdout")` (schema: `site/SITE_DATA_SCHEMA.md` rule 5).
Demonstrated: a genuine, division-declared, lock-valid `peira run
--suite trial-demo` artifact is rejected:
`ingest: error: ... suite 'trial-demo' must be 'public' or 'holdout'`.
There is no adapter step between runner output and ingest in any
documented procedure, so either official v2 runs cannot ingest, or
someone hand-rewrites `suite` — which both loses the suite identity and
is exactly the relabeling operation P0-1 abuses. Decide the canonical
meaning of `artifact.suite` and fix one side before the official run.

### P1-2. Ingest never consults the published dataset release registry
`ingest.py` requires all artifacts in a build to *agree* on
`dataset_version`/`manifest_sha256`, but never checks them against
`data/dataset-releases.json` (v2 tag `dataset-v2-2.5.1` →
`b8b877fa…`). Demonstrated: a batch with `manifest_sha256 = "f"*64`
ingested cleanly. Likewise no check that n/case-ids/families match the
manifest — a wrong-suite run relabeled to the v2 version string is
undetectable at ingest. Cross-check the manifest SHA (and ideally
case-count coverage) against the release registry at ingest time.

### P1-3. `ingest.py` does not call `qualifies_for_leaderboard` — ranking gates live only in `dashboard.leaderboard()`
Ingest enforces lock/schema/division/vocabulary but NOT: malformed-rate
gate, benign-accuracy gate, n≥200 / ≥20-per-family gates,
`termination=="complete"`, or declared cache state. Those live in
`runs_registry.qualifies_for_leaderboard`, which the site build never
invokes. Ineligible rows land in site-data.json with
`ranking_eligible=false` (or `true` if forged per P0-1); the JS display
is the only thing withholding rank. Per the task's question: the
malformed gate is `>` and it is enforced by the display path, not by
ingest. Decide whether site-data.json should contain rows that must
never rank.

## P2

### P2-1. `latency_summary` discards runner-measured latency for usage-less records
`_arm_latency_data` (`metrics.py:5465`) skips records with
`usage is None` ("a missing usage is not a zero-latency call"), even
though `latency_ms_total` is runner-measured and nonzero. On the real
trial run all 12 cases had `latency_ms_total` 0.29–3.04 ms
(`cached=false`), yet the sealed block reports `n=0`, all percentiles
null. This contradicts `latency_summary`'s own docstring ("Latency is
the cumulative buyer latency (CallRecord.latency_ms_total)... measured
by the runner"). Affects adapters that report no usage (mock,
subprocess/local adapters); API adapters are unaffected. Fix: skip on
`latency_ms_total <= 0`, not on `usage is None`.

### P2-2. Ingest's `run_status=="success"` gate is dead code for real v3 artifacts
`validate_v3` is only reached via `config["v3"]` — the legacy prototype
block. Real v3 artifacts carry top-level fields and no `config["v3"]`
(confirmed on the real run), so the gate is skipped; the comments admit
migration is "separate future work". `qualifies_for_leaderboard` covers
`termination=="complete"` instead, so no open hole — but a live gate on
a dead path invites false confidence. Migrate or delete.

### P2-3. Docs drift: SITE_DATA_SCHEMA rule 2 says artifact_version "2"; ingest enforces "3"
One-line fix in `site/SITE_DATA_SCHEMA.md`.

### P2-4. Adapter pin mismatch is undetectable at every gate
Nothing compares `artifact.adapter_version`/`adapter_pins` against
`api_pins.PINNED_API_MODELS` — `qualifies` requires only non-empty
version; ingest ignores `adapter_pins` entirely; only `peira doctor`
warns (advisory). A submission claiming a pinned model ID while running
something else passes mechanically. (Partially inherent to
self-report; the api_pins module is honest about best-effort limits.)
Related: Admission-Rules requires a "signed attestation" in the
submission bundle, but no signature mechanism exists anywhere in the
pipeline — policy-only control.

## Handoff-by-handoff validation map

| Boundary | Validation at boundary | One concrete undetected slip |
|---|---|---|
| runner → metrics | `summarize()` scores the same `ordered` list that is serialized to `result_dicts`; resume re-validates partials | P2-1: usage-less records silently dropped from latency summary |
| metrics → artifact | analysis lock covers metrics + results + env + v3 blocks; seal normalizes | none found (lock coverage is comprehensive) |
| artifact → registry | registry records `lock_valid` at index time; index is mtime-fresh | registry is a local cache, not a trust root; no out-of-band lock log (P0-2) |
| registry → ingest | ingest does not use the registry at all (globs a directory) | ingest is strictly weaker than `qualifies_for_leaderboard` (P1-3); never recomputes eligibility (P0-1) |
| ingest → leaderboard | site JS withholds rank on `ranking_eligible=false` | forged `ranking_eligible=true` ranks (P0-1); `suite` vocabulary rejects real runs (P1-1); forged manifest SHA accepted (P1-2) |

## Open questions for David
1. Canonical meaning of `artifact.suite` for the official v2 pipeline
   (suite ID vs public/holdout tier) — P1-1 blocks the official ingest.
2. Is the append-only lock log for official runs planned before the $906
   spend, or are official submissions self-reported by policy (P0-2)?
3. Should `qualifies_for_leaderboard` recompute eligibility + headline
   metrics from per-case results (cheap, data is in the artifact) — P0-1?
