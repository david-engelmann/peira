# Report artifacts

**Status** Implementation, 2026-10-01
**Code** `python/peira/report_html.py`
**Contract tests** `tests/test_report_html_contract.py`

## The self-containment contract

A public benchmark's reports get saved, cited, and screenshotted years
later. A JavaScript-dependent page rots. A self-contained HTML file is
forever. Every HTML artifact peira emits follows this contract.

- No JavaScript. No `script` elements, no event handlers, no exceptions.
- No external resources. No stylesheets, fonts, images, or data fetched
  from anywhere. If the file renders at all, it renders completely.
- Charts are inline SVG computed at render time. The numbers in the
  chart and the numbers in the table come from the same payload, so
  they cannot disagree.
- Every interpolated value is HTML-escaped. Adapter names, family
  names, and reasons are attacker- or author-controlled strings. They
  land inert.
- The data source is bannered, never implied. A report rendered from
  placeholder data says MOCK DATA in a banner that survives
  screenshotting. Only an explicit `--data-source official` renders the
  official banner. The official banner is a self-declared label: the
  renderer does not verify the data's provenance, it records what the
  operator declared.

`tests/test_report_html_contract.py` pins the contract. A future edit
that adds a script tag, an external stylesheet, or an unescaped value
fails the suite.

## What emits what

| Command | Artifact |
| ------- | -------- |
| `peira report --out run.html` | Per-run report. Already self-contained. Inline SVG decision curves. |
| `peira compare --out cmp.html` | Head-to-head comparison. Already self-contained. |
| `peira dashboard leaderboard --format html --out lb.html` | Cross-adapter leaderboard. New in this change. ASR bars with Wilson CI whiskers as inline SVG, ranked and unranked tables. Defaults to the mock banner. |

The per-run and compare renderers predate this contract and already
satisfy it. They are covered by the same rules going forward. Any new
HTML surface must pass the contract test pattern: render from a hostile
payload, assert the five properties above.

## Deliberate non-goals

No interactivity. Sorting, filtering, and drill-down belong in the
live dashboard, not in the artifact. The artifact is the citable
record. No vendor placement inside data artifacts, ever. Neutrality is
a feature of the benchmark, not a missing logo.
