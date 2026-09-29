# Reader-journey audit

Audit of the peira docs from a new user's perspective, conducted
2026-09-29 on main at 7ced5cab. This informed the PR-2 usability work.

## The journey

### 1. Landing (README.md)

A new user lands on the README. It answers "what is peira" clearly and
the adapter table is now complete (D-P1-4 fixed). The "How peira differs"
section gives the pitch. Good.

Gap: the README jumps from pitch to install without a concrete "here is
what a run looks like" moment. A new user cannot visualize the product
before installing. **Fixed by** `docs/What-Peira-Does.md` (worked example
with a real case).

### 2. Orientation (docs/Overview.md)

The Overview is the docs landing page with three audience paths. It
covers the map well. The "adversarial robustness" SEO term is now present
(D-P2-1 fixed).

Gap: no copy-paste path from "I understand the concept" to "I ran it."
The Overview links to Methodology (the contract) but not to a hands-on
walkthrough. **Fixed by** `docs/Local-Run-Walkthrough.md` (new, linked
from Overview's next-steps).

### 3. First run (no walkthrough existed)

Before PR-2, there was no single document showing the exact commands to
go from install to scored run with real output. The README quickstart
exists but the trial-demo path was not spelled out with expected output.
A new user would have to guess the `--out` flag and interpret the
summary statistics cold.

**Fixed by** `docs/Local-Run-Walkthrough.md`: copy-paste commands with
real output captured 2026-09-29, explaining each line of the summary.

### 4. Understanding results (no interpretation guide existed)

The run summary prints ASR, CIs, eligibility counts, and a ranking
eligibility verdict. Without guidance, a new user cannot tell whether
"ASR 0.3333 CI 0.1381-0.6094" is good, bad, or meaningless. The
"not resolvable at this n" convention and the "overlapping CIs are not
ties" rule live in Methodology but were not surfaced for report readers.

**Fixed by** `docs/Compare-Report-Guide.md`: how to read every number,
when a difference is real, what not to do.

### 5. Adapter setup (docs/Adapters.md)

Adapters.md covers install, keys, and pinned models per adapter. The
"LLM-as-judge" term is now present (D-P2-1 fixed). This page is reference
material, not a walkthrough, which is the right shape. No gap found at
the audit level; per-adapter setup walkthroughs remain future work.

## What was not done

- **Terminal-recording GIFs.** No `vhs` or `asciinema` available in this
  environment. The walkthrough docs serve as static fallbacks. GIFs need
  a machine with recording tooling.
- **Per-adapter setup walkthroughs.** Each adapter (HF, OpenAI, etc.)
  deserves a copy-paste setup guide. Deferred; the reference page exists.
- **Video walkthrough.** Out of scope for docs PR.

## Verification

All new files pass the em-dash verification script (zero U+2014 hits).
All command output shown is real output captured 2026-09-29, not
invented. The `peira run` and `peira report` commands were executed in
the PR-2 worktree.
