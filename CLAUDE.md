# CLAUDE.md

Repo conventions for coding agents working on peira.

## Build / test / lint

```bash
pip install -e .                    # install the Python package
python -m unittest discover tests   # Python tests — must stay green
cargo test --workspace              # Rust tests — must stay green
python scripts/check_public_surface.py   # strategy-language check — must stay green
peira run --adapter mock --suite trial-demo --dry-run   # CLI smoke
```

## Architecture map

- `python/peira/` — reference implementation and SDK. `schema.py` (case
  contract), `adapters/base.py` (adapter protocol), `adapters/mock.py`
  (deterministic offline adapter), `runner.py`, `metrics.py`, `artifacts.py`
  (sealed run records), `cli.py`.
- `crates/peira-core/` — Rust core. Ports the hot paths once the Python
  interfaces freeze (Phase 0). The Python package is the reference until then.
- `dataset/` — `trial-demo/` is the offline demo fixture; `v1/` lands the
  real 2,500-case dataset.
- `docs/` — the product's public face. Methodology is frozen; update docs
  when behavior changes, in the same PR.

## Contribution workflow

Mechanical checklist in `docs/Contributing.md` → green CI → merge.

## Hard rules

1. **Never edit scored artifacts post-hoc.** New config = new run = new
   analysis lock. The lock is the trust model.
2. **Never read or decrypt the private holdout** unless the human
   explicitly asks. It doesn't exist yet; when it does, this rule is
   absolute.
3. **Never commit strategy.** No dominance intent, speed language, vendor
   plays, or internal memos — in any file, issue, or commit message.
   `scripts/check_public_surface.py` enforces it; keep it green.
