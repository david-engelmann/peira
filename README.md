# peira

**The empirical trial for decision models.**

[![ci](https://github.com/david-engelmann/peira/actions/workflows/ci.yml/badge.svg)](https://github.com/david-engelmann/peira/actions/workflows/ci.yml)

## 30-second quickstart

```bash
pip install peira
peira run --adapter mock --suite trial-demo   # offline, no keys
peira report --run runs/mock-trial-demo.json --out report.html
```

That's a full evaluation: 12 demo cases through the mock adapter, scored
with the real metrics, sealed with an analysis lock, rendered as HTML.
When the v1 dataset ships, swap `--suite trial-demo` for `--suite trial`
(the branded 100-case Peira Trial) or run the full 2,500.

## What peira measures

Whether hostile manipulations of the input change a decision model's typed
output — Choice, Score, or Noul — measured with paired benign/attacked
controls across 10 attack families. Every score links to per-case
drill-down receipts, and every run is sealed against post-hoc editing.

## Leaderboard

Coming with the v1 dataset. One row per (adapter, dataset version); partial
primitive coverage is reported honestly, not hidden.

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

| Tier | Command | What you get |
|---|---|---|
| `peira` | `pip install peira` | Core, SDK, CLI, offline mock |
| `peira[hf]` | `pip install peira[hf]` | + Hugging Face adapters |
| `peira[all]` | `pip install peira[all]` | + everything optional |

Hardware guidance per tier: `docs/Hardware.md`. No telemetry — the harness
makes no network calls except the ones you configure (see FAQ).

## How peira differs

| | peira | adjacent benchmarks |
|---|---|---|
| What it measures | decision flips under attack | varies |
| Paired benign/attacked controls | yes | rarely |
| Confidence-robustness metrics | yes (ECE, Brier, Δc) | rarely |
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
