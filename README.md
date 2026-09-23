# peira

**The empirical trial for decision models.**

[![ci](https://github.com/david-engelmann/peira/actions/workflows/ci.yml/badge.svg)](https://github.com/david-engelmann/peira/actions/workflows/ci.yml)

## 30-second quickstart

```bash
pip install -e .   # from a peira checkout (PyPI release pending)
peira run --adapter mock --suite trial-demo   # offline, no keys
peira report --run runs/mock-trial-demo.json --out report.html
```

That's a full evaluation: 12 demo cases through the mock adapter, scored
with the real metrics, sealed with an analysis lock, rendered as HTML.
For the real thing, swap `--suite trial-demo` for `--suite trial` — the
branded 100-case Peira Trial (100 v1-quality cases, 10 per attack family,
with 100% of critical cases human-reviewed). The full v1 dataset (2,500
cases) ships later.

### What a run costs

Every adapter makes exactly two `decide()` calls per case — one benign,
one attacked — so time and cost scale linearly with suite size: 200 calls
for the Trial, 5,000 for v1.

| Adapter class | 100-case Trial | 2,500-case v1 | Cost |
|---|---|---|---|
| `mock` (offline, deterministic) | <1 s (measured) | ≈3 s (extrapolated) | $0 |
| Structured-output LLM baseline | _ships with the adapter_ | _ships with the adapter_ | per-token API spend |
| Hugging Face guard model | _ships with the adapter_ | _ships with the adapter_ | GPU time |

## What peira measures

Whether hostile manipulations of the input change a decision model's typed
output — Choice, Score, or Noul — measured with paired benign/attacked
controls across 10 attack families. Every report carries per-case
drill-down receipts, and every run is sealed against post-hoc editing.

## Leaderboard

Coming with the v1 dataset. One row per (adapter, dataset version);
partial primitive coverage will be reported honestly, not hidden.

## Add your model

```python
from peira.adapters.base import ChoiceOutput

class MyAdapter:
    name = "my-adapter"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        # call your model here
        return ChoiceOutput(decision="approve", confidence=0.8)
```

See `examples/minimal_adapter.py` (30 lines, runs in CI), then read
`docs/Methodology.md` for the contracts your outputs must satisfy.

## Install

peira isn't on PyPI yet — until it is, `pip install -e .` from a repo
checkout stands in for `pip install peira` below.

| Tier | Command | What you get |
|---|---|---|
| `peira` | `pip install peira` | Core, SDK, CLI, offline mock |
| `peira[hf]` | `pip install peira[hf]` | + Hugging Face adapters (planned) |
| `peira[all]` | `pip install peira[all]` | + everything optional |

Hardware guidance per tier: `docs/Hardware.md`. No telemetry — the harness
makes no network calls except the ones you configure (see FAQ).

## How peira differs

| | peira | adjacent benchmarks |
|---|---|---|
| What it measures | decision flips under attack | varies |
| Paired benign/attacked controls | yes | rarely |
| Confidence-robustness metrics | yes (ECE, Brier) | rarely |
| Analysis freeze (no post-hoc edits) | yes, mechanical | rarely |
| Scale (v1) | 2,500 cases | varies |

Rows are verifiable facts; the methodology is in `docs/Methodology.md`.

## Citation

```bibtex
@software{peira2026,
  title = {peira: the empirical trial for decision models},
  author = {Engelmann, David},
  year = {2026},
  url = {https://github.com/david-engelmann/peira}
}
```

## License / notices

MIT for code, CC-BY-4.0 for the dataset. **A peira score measures
robustness on this benchmark's paired decision cases. It does not certify
a model as safe.**

Docs: [`docs/`](docs/) · Paper: [`paper/`](paper/) · Dataset:
[`dataset/`](dataset/) · Changelog: [`CHANGELOG.md`](CHANGELOG.md) ·
Security: [`SECURITY.md`](SECURITY.md) · Questions:
[GitHub Discussions](https://github.com/david-engelmann/peira/discussions)
