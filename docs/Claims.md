# Claims

What peira claims, what it doesn't, and what's still unverified. This page
indexes the load-bearing claims; detail lives in the linked docs.

## We claim

- peira measures whether hostile input manipulations change typed decision
  outputs, with paired benign/attacked controls, across the documented
  attack families.
- Every public score will link to per-case drill-down receipts.
- Run artifacts are sealed with an analysis lock; `peira report` warns on
  lock mismatch.
- The private holdout's raw cases will never be published while they are
  holdout cases; aged-out cases enter the public set on the declared
  schedule (see `Holdout-OpSec.md`), and only aggregate metrics leave the
  maintainer's machine.

## We don't claim

- That a good score certifies a model as safe. (Non-certification notice,
  README.)
- That the 10 families cover every attack shape. They don't.
- That synthetic cases equal real incidents. They model attack shapes.

## Unverified

- Calibration of the headline numbers against real-world deployment
  outcomes. That's future work, tracked in the issue tracker, not asserted
  here.
