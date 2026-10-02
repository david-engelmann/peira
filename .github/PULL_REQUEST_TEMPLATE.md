## What this PR does

<!-- One or two sentences. What changed and why. -->

## How it was verified

<!-- Exact commands and their exit codes. Docs-only PRs still need the
docs build and link check. -->

- [ ] Full Python suite passed in Rust-active mode (`python -m pytest tests -n auto`), exit 0
- [ ] Full Python suite passed with `PEIRA_NO_RUST=1`, exit 0
- [ ] Docs build and link check passed (for docs changes)

## Checklist

- [ ] No test was weakened or deleted to make the suite pass. A test
      that fails on correct behavior is itself a defect. Weakening it
      is not a fix.
- [ ] The docs-update map in AGENTS.md was consulted, and every doc
      it names for this change is updated in this PR or marked N/A below.
- [ ] Public surface is green: quickstart, CLI help, and README code
      blocks still run as documented.
- [ ] Copy bar: no em dashes, no semicolons, no strategy-talk in
      public copy.

## Schema or dataset changes

<!-- Delete this section if the PR touches neither. -->

- [ ] Migration path documented in `docs/Dataset-Changelog.md`
- [ ] `DATASHEET.md` updated
- [ ] Provenance fields on derived artifacts follow the distilled
      convention in `docs/Provenance.md`

## Docs this PR updates

<!-- List each doc the AGENTS.md map names for this change, or write N/A. -->
