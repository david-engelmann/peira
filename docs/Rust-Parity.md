# Rust parity

For contributors: how the Rust port stays bit-exact with the Python
reference, and how to keep it that way.

## What's ported

`crates/peira-core` reimplements the hot paths. Python remains the reference
— the Rust code must match it, not the other way around.

| Function | Python | Rust | Exposed via PyO3 |
|---|---|---|---|
| `wilson_ci` | `metrics.py` | `metrics.rs` | yes |
| `mcnemar` | `metrics.py` | `metrics.rs` | yes |
| `brier_score` | `metrics.py` | `metrics.rs` | yes |
| `ece` | `metrics.py` | `metrics.rs` | yes |
| sha256 (analysis lock) | `artifacts.py` | `artifacts.rs` | yes (`sha256_hex`) |
| schema validation | `schema.py` | `schema.rs` | no (Rust-side use) |
| run loop | `runner.py` | `runner.rs` | no (Rust CLI) |
| adapter subprocess protocol | — | `adapter_protocol.rs` | no (Rust-side use) |

The PyO3 bindings live in `src/python.rs`. At import time, `metrics.py`
replaces its own `wilson_ci`, `ece`, `brier_score`, and `mcnemar` with the
Rust versions — but only if the compiled extension is importable. The
pure-Python functions stay as the reference. Set `PEIRA_PURE_PYTHON=1` to
force the reference implementation (useful when debugging parity).

## The byte-exact JSON contract

The analysis lock is sha256 over a canonical JSON serialization. Both sides
must produce byte-identical input, or locks won't match. The contract:

- **Key order:** sorted (`sort_keys=True`; Rust uses `BTreeMap`).
- **Separators:** `", "` and `": "` — with spaces, *not* compact. This is
  Python's `json.dumps` default, and the single easiest thing to get wrong
  in a port.
- **ASCII:** `ensure_ascii=True` — non-ASCII escaped as `\uXXXX`, with
  surrogate pairs for characters outside the BMP. Control characters,
  quotes, and backslashes escaped per the JSON spec.
- **Numbers:** Python `repr()` float formatting. Integers plain.

The Rust serializer (`python_compatible_json` in `artifacts.rs`) implements
this by hand rather than trusting `serde_json`'s defaults, because the
defaults differ (compact separators, unescaped non-ASCII). There are tests
asserting exact output against known Python-produced strings
(`python_compat_separators`, `python_compat_ascii`, `hash_matches_python`).

If you touch anything in the serialization path, run the artifact tests on
both sides before anything else.

## How to add a parity test

1. Compute the reference value in Python:
   `PYTHONPATH=python python3 -c "from peira.metrics import ece; print(repr(ece([...], [...])))"`
2. Add a Rust test asserting equality to 1e-12 (see the existing
   `parity_with_python` test in `metrics.rs`).
3. Cover the edges, not just the middle: empty inputs, bin boundaries
   (for ECE), zero discordant pairs (for McNemar), `hits=0` (for Wilson).

The 1e-12 tolerance (not exact `==`) is deliberate: it absorbs float
formatting noise while catching any real algorithmic divergence.

## The `math.fsum` story

Why summation matters enough to have its own section: the original Rust
port of `brier_score` and `ece` diverged from Python by 1 ulp on some
inputs. The cause was not a Rust bug — it was that Python's builtin `sum()`
is **interpreter-build-dependent**. Some builds correctly round; stock
CPython accumulates naively left-to-right. Same code, different numbers on
different machines: a reproducibility hazard for a benchmark.

The fix, on both sides:

- **Python** pins `math.fsum` in `brier_score` and in `ece`'s per-bin
  confidence mean. `math.fsum` is correctly rounded on every build, so the
  reference is now build-independent. (Invisible in practice: the runner
  rounds metrics to 4 decimals.)
- **Rust** implements `accurate_sum`, a line-by-line port of CPython's
  `math.fsum` algorithm (Shewchuk non-overlapping partials, Fast2Sum,
  half-even fixup — including NaN/inf and overflow semantics). Correct
  rounding is unique, so it is bit-exact with `math.fsum` on every
  platform, verified even on the tricky `fsum([1e-16, 1, 1e16])` half-even
  case.

The lesson for future ports: never use a naive accumulation in either
language when the result feeds a metric. If Python uses `math.fsum`, Rust
uses `accurate_sum`. If you add a new metric that sums floats, follow the
same pattern and add a cancellation-heavy parity test
(`fsum_cancellation` in `metrics.rs` is the template).
