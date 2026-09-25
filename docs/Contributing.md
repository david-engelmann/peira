# Contributing

## The mechanical checklist

Every PR must:

1. Keep `python -m unittest discover tests` green.
2. Keep `cargo test --workspace` green (once the Rust core has logic).
   Porting or changing Rust code? Read `docs/Rust-Parity.md` first — the
   port must stay bit-exact with the Python reference.
3. Keep `python scripts/check_public_surface.py` green — strategy language
   is never committed (see below).
4. If you added a user-facing error string, add it to
   `docs/Troubleshooting.md` in the same PR.
5. If you changed the dataset, bump the dataset version and add a
   CHANGELOG entry.
6. Sign off your commits (DCO): `git commit -s`.

## Public-content boundary

This repo is the product's public face. Never commit strategy: no
dominance intent, no speed/urgency language, no vendor plays, no internal
memos — in any file, issue, discussion post, or commit message. The CI
`public-surface` job enforces this mechanically. When in doubt, leave it
out and ask in Discussions.

## What happens after you open a PR

CI runs (tests, public-surface check, README quickstart on three OSes).
The maintainer reviews for correctness against `docs/Methodology.md`.
Adapter PRs also run the Trial suite and post the score as a comment —
that's the whole review for a new adapter: green CI plus a posted score.
