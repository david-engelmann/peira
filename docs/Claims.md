# Claims

What peira claims, what it doesn't, and what's still unverified. If a
claim isn't on this page, we don't make it.

## We claim

- peira measures whether hostile input manipulations change typed decision
  outputs, with paired benign/attacked controls, across the documented
  attack families.
- Run artifacts are sealed with a tamper-evident analysis lock; verify with
  `peira verify --run <artifact.json>` (exit 0 = intact, 1 = tampered).
- The private holdout's raw cases are never published; only aggregate
  metrics leave the maintainer's machine.

## We don't claim

- That a good score certifies a model as safe. (Non-certification notice,
  README.)
- That the 10 families cover every attack shape. They don't.
- That synthetic cases equal real incidents. They model attack shapes.

## Unverified

- Calibration of the headline numbers against real-world deployment
  outcomes. That's future work, tracked in the issue tracker, not asserted
  here.
