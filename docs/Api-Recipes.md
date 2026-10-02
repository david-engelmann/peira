# API recipes for programmatic consumers

**Status** Design, 2026-10-01
**Contract** `docs/schemas/api-contract.schema.json`

Agents are the primary consumers of peira's data. This document tells
them how to get a correct, reproducible snapshot from the leaderboard
API. It is written before the API ships so the contract is stable from
day one. When the API lands on peiratrial.dev, every response validates
against the schema above.

## Recipe 0. Authenticate before anything else

Every request carries an API key. The key is read-only. It can fetch
runs, leaderboards, families, and cases. It cannot start runs, modify
anything, or see private holdout material.

```
GET /v1/leaderboard
Authorization: Bearer peira_live_...
```

Rules.

- Request a key per agent, not per project. A leaked key is revoked
  in one place without touching the others.
- Send the key in the `Authorization` header. Never in the URL. URLs
  end up in logs and transcripts.
- A revoked or missing key returns the `unauthorized` code from
  Recipe 2. A key that lacks a scope returns `forbidden`. Treat both
  as credential problems, not as data problems.
- Rotate keys on your own schedule. Old keys keep working for seven
  days after rotation so in-flight analysis does not break.
- Never paste a key into a shared artifact, a report, or a chat
  transcript. If a key leaks, revoke it and request a new one.

## Recipe 1. Check freshness before analysis

Never analyze a snapshot you have not confirmed is complete. Every
response carries a `freshness` block.

```
GET /v1/leaderboard
{
  "data": [...],
  "freshness": {
    "run_id": "2026-11-a12-official",
    "status": "complete",
    "generated_at": "2026-11-15T02:00:00Z",
    "dataset_version": "1.4.0",
    "manifest_sha256": "abc123..."
  },
  "pagination": {"next_token": null, "total": 21}
}
```

Rules.

- Only `status: "complete"` is a reproducible snapshot. `running`
  means the run is still writing. `partial` means some adapters are
  missing. `superseded` means a newer snapshot exists and you should
  fetch it instead.
- Record `run_id`, `dataset_version`, and `manifest_sha256` with every
  number you quote. A number without its run is a rumor.
- If you poll a running evaluation, wait for `status: "complete"`
  before the first analysis pass. Do not analyze page 1 while page 3
  is still being written.

## Recipe 2. Handle errors by code, not by message

Every error uses the `{error, code}` envelope. Match on `code`. The
`error` string is prose and may be reworded at any time.

| Code | Meaning | What to do |
| ---- | ------- | ---------- |
| `run_not_found` | No run with that id | Check the id, list `/v1/runs` |
| `run_incomplete` | The run exists but is not complete | Poll `freshness.status` until `complete` |
| `invalid_token` | Bad pagination cursor | Restart from the first page |
| `expired_token` | Cursor is too old | Restart from the first page |
| `rate_limited` | Too many requests | Honor `retry_after_seconds`, then retry |
| `dataset_not_found` | No such dataset version | List `/v1/datasets` |
| `family_not_found` | No such family | List `/v1/families` |
| `adapter_not_found` | No such adapter | List `/v1/adapters` |
| `bad_request` | Your parameters are wrong | Read `detail`, fix, retry once |
| `unauthorized` | Missing or revoked API key | Check Recipe 0, then retry |
| `forbidden` | Key lacks the scope for this resource | Request a key with the scope |
| `internal` | Our problem | Retry with backoff, then report it |

## Recipe 3. Paginate with continuation tokens

All collections paginate with an opaque `next_token`. Request the next
page with `?page_token=<token>`. A page whose `next_token` is null is
the last page. Never assume a page is last because it came back short.
A short page with a non-null token has a next page.

```
GET /v1/runs/2026-11-a12-official/cases?page_token=eyJ9...
```

`total` tells you how many items exist across all pages at request
time. It can grow between your first and last page if a run is still
writing. If it grows, your snapshot is not reproducible. Go back to
Recipe 1.

## Recipe 4. A complete agent session

A worked example. An agent wants the current leaderboard, reproducibly.

1. `GET /v1/leaderboard`. Check `freshness.status`. If it is not
   `complete`, wait and retry. Do not proceed on `partial`.
2. Follow `pagination.next_token` until it is null, collecting pages.
3. Verify `total` did not change between the first and last page.
4. Store `run_id`, `dataset_version`, and `manifest_sha256` alongside
   every derived number.
5. Quote ASR with its confidence interval, never the point estimate
   alone. Check the per-family minimum detectable effect before
   claiming one adapter beats another. Metric definitions and
   anti-misuse statements live in `docs/Analytics-Methodology.md`.

## What the API will not do

The API serves measurements, not interpretations. Rankings are
computed from the same sealed artifacts as the HTML reports. There is
no endpoint that returns a bare winner without the intervals. There is
no vendor placement in any response. The signals layer
(`docs/Signals-Layer.md`) is the interpretation surface. It is
clearly labeled as such and never mixed into the measurement
endpoints.
