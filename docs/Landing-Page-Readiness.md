# Landing-page readiness checklist

**Status** Checklist, 2026-10-01
**Covers** peiratrial.dev landing-page readiness.

The leaderboard site scaffold exists at `site/`. This checklist is
what "ready" means before the landing page is treated as a public
surface. Each item can be checked off by whoever does the final pass.

## Copy

- [ ] Every public sentence passes the copy bar. No em dashes, no
      colons, no semicolons. Verify with a codepoint scan, not by eye.
- [ ] The headline says what peira is in one line, an adversarial
      benchmark for decision models. No hype words, no superlatives,
      no claims about being first or best.
- [ ] The page states the license split plainly. MIT for code and
      CC-BY-4.0 for the dataset.
- [ ] SEO basics are in place. Title tag, meta description, and Open
      Graph tags using the terms people actually search for, such as
      adversarial benchmark, LLM evaluation, prompt injection,
      guardrail testing, AI red teaming, decision models,
      LLM-as-a-judge, and EU AI Act.
- [ ] The methodology summary links to the full Methodology doc. The
      page summarizes. It does not fork the methodology into a second
      copy that can drift.

## Data honesty

- [ ] While any number on the page is synthetic, the mock-data banner
      renders on every page. No build with mock data is presented as
      real results.
- [ ] Public and holdout numbers are never blended. The toggle is
      visible and the holdout view explains why it exists.
- [ ] Every leaderboard row links to its provenance. Dataset version,
      manifest SHA, artifact seal. Numbers without provenance do not
      ship.
- [ ] Confidence intervals render next to every point estimate. A
      number without its interval is a draft, not a result.

## Functionality

- [ ] Leaderboard, Families, Calibration, Frontier, Compare, Cases,
      and Methodology views all render from the same ingested data.
- [ ] View state is URL-addressable. A shared link reproduces the
      exact view.
- [ ] CSV, PNG, and SVG exports work from the leaderboard and compare
      views.
- [ ] The page loads fast on a mid-range phone over a slow
      connection. No render-blocking surprises.

## Trust

- [ ] The "not a safety certification" caveat from the README is
      present in short form on the landing page.
- [ ] The foreseeable-misuse coverage matrix is linked with its gap
      list intact. Gaps are shown, not hidden.
- [ ] Contact and responsible-disclosure paths exist before launch.

## Launch sequence

The landing page goes live with real data only. Official runs sealed,
artifacts published, ingest run without the mock flag, and the mock
banner verified absent. The announcement package
([Announcement-Package](Announcement-Package.md)) publishes after the
page is live, not before.
