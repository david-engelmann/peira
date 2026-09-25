# peira

**The empirical trial for decision models.**

*Peira* (πείρα) is Greek for "trial" — as in trial by fire.

*An adversarial-robustness benchmark for LLM decision models: 2,500 paired
benign/attacked cases across 10 attack families, measuring whether hostile
input manipulations flip typed decisions (choice, score, abstention).*

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
output — Choice (pick one option), Score (0–1 with your threshold;
[`docs/Score-Guide.md`](docs/Score-Guide.md)), or Noul (choice with
abstention; [`docs/Noul-Explainer.md`](docs/Noul-Explainer.md)) — measured
with paired benign/attacked controls across 10 attack families.

The 10 attack families (full definitions in `docs/Taxonomy.md`):

| Family | What it tests |
|---|---|
| `state_poisoning` | hostile content in tool output / history authorizes the action |
| `criteria_smuggling` | text arguing for its own classification |
| `option_order` | reordering choice options moves the answer |
| `distractor_flooding` | large noisy state degrades accuracy |
| `score_anchoring` | planted reference points manipulate score outputs |
| `literal_reading` | face-value reading of scoping and negation |
| `negation_games` | double negatives and abstention inversions |
| `policy_paraphrase` | rewording to dodge natural-language safety policies |
| `indirection` | payload buried behind multi-hop indirection |
| `confidence_spoofing` | hostile content inflates confidence while flipping the answer |

Every run is sealed against post-hoc editing — the analysis lock (SHA-256)
guarantees the reported metrics match the actual results. Verify with
`peira verify --run <artifact.json>`. How the pieces connect (schema →
runner → metrics → artifacts → CLI, and where Rust lives):
[`docs/Architecture.md`](docs/Architecture.md).

## Leaderboard

Coming with the v1 dataset. One row per (adapter, dataset version); partial
primitive coverage is reported honestly, not hidden.

## Add your model

```python
from peira.adapters.base import ChoiceOutput

class MyAdapter:
    name = "my-adapter"
    version = "0.1.0"  # exact pinned version — never "latest"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        # call your model here
        return ChoiceOutput(decision="approve", confidence=0.8)
```

See `examples/minimal_adapter.py` (30 lines, runs in CI). For the full
guided walkthrough (primitives, running, interpreting results, pitfalls),
read [`docs/Adapter-Tutorial.md`](docs/Adapter-Tutorial.md), then
`docs/Methodology.md` for the contracts your outputs must satisfy. The
consolidated function reference is [`docs/API-Reference.md`](docs/API-Reference.md).

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

Code: [MIT](LICENSE-MIT) — maximum reuse.
Dataset: [CC-BY-4.0](dataset/LICENSE-CC-BY-4.0) — attribution required; please do not train on the public cases (a canary string is embedded so contamination is detectable). **A peira score measures
robustness on this benchmark's paired decision cases. It does not certify
a model as safe.**

Docs: [`docs/`](docs/) · Paper: [`paper/`](paper/) · Dataset:
[`dataset/`](dataset/) · Changelog: [`CHANGELOG.md`](CHANGELOG.md) ·
Security: [`SECURITY.md`](SECURITY.md) · Questions:
[GitHub Discussions](https://github.com/david-engelmann/peira/discussions)
