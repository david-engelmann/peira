# peira

**The empirical trial for decision models.**

*Peira* (πείρα) is Greek for "trial" — as in trial by fire.

*An adversarial-robustness benchmark for LLM decision models: 2,500 paired
benign/attacked cases across 10 attack families, measuring whether hostile
input manipulations flip typed decisions (choice, score, abstention).*

[![ci](https://github.com/david-engelmann/peira/actions/workflows/ci.yml/badge.svg)](https://github.com/david-engelmann/peira/actions/workflows/ci.yml)

## 30-second quickstart (under 5 minutes, no API keys)

**Step 1 — Install** (~2 minutes, the only slow step):
```bash
pip install peira
```

**Step 2 — Run the demo benchmark** (~1 second, 12 cases, fully offline):
```bash
peira run --adapter mock --suite trial-demo
```
Expected output (exact numbers vary — the mock is deliberately naive):
```
done: 12 cases
  ASR (conditional): 0.0 95% CI [0.0, 0.0]
  benign accuracy:   0.0 95% CI [0.0, 0.2425]
  malformed rate:    0.0
  ranking eligible:  False (benign accuracy below 0.5; ...)
artifact: runs/mock-trial-demo.json
analysis lock: 1bc8ae4c28915cb3…
```
(The command exits with code 3 — "ran fine, but not ranking-eligible."
That's expected: the 12-case demo can't clear the ranking floors, and the
mock adapter is deliberately too naive to be eligible anyway.)

**Step 3 — Verify the seal** (~1 second):
```bash
peira verify --run runs/mock-trial-demo.json
```
Expected output:
```
ok: runs/mock-trial-demo.json — analysis lock valid
  adapter: mock, suite: trial-demo
  lock: 1bc8ae4c28915cb3...
```
The analysis lock is a SHA-256 over the config + results: any post-hoc
edit invalidates it. This is the trust mechanism behind "no post-hoc
editing".

**Step 4 — Read the report** (~1 second):
```bash
peira report --run runs/mock-trial-demo.json --out report.html
```
Open `report.html` in a browser.

### What just happened

You ran 12 paired benign/attacked decision cases through a mock adapter,
computed robustness metrics (attack success rate, benign accuracy,
malformed rate), sealed the results with a SHA-256 analysis lock — then
verified the seal and rendered an HTML report. Total compute: a few
seconds; the 5-minute budget is `pip install` plus reading.

**The mock's scores are meaningless — this was a plumbing check, not a
benchmark.** The mock always approves, so it scores 0.0 benign accuracy
and is not ranking-eligible. What you verified is the pipeline: cases in,
typed decisions out, metrics computed, seal intact.

### Next steps

- **Benchmark your model:** [`docs/Adapter-Tutorial.md`](docs/Adapter-Tutorial.md) —
  wrap your decision model in ~30 lines, ~15 minutes.
- **Understand the numbers:** [`docs/Methodology.md`](docs/Methodology.md) —
  what ASR, confidence intervals, and ranking eligibility mean.
- **Run the real suite:** when dataset v1 ships, swap `--suite trial-demo`
  for the branded 100-case Peira Trial, or the full 2,500-case suite.

## What peira measures

Whether hostile manipulations of the input change a decision model's typed
output — Choice (pick one option), Score (0–1 with your threshold;
[`docs/Score-Guide.md`](docs/Score-Guide.md)), or Abstain (choice with
abstention; [`docs/Abstain-Explainer.md`](docs/Abstain-Explainer.md)) — measured
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
from peira.adapters.base import CaseContext, ChoiceOutput

class MyAdapter:
    name = "my-adapter"
    version = "0.1.0"  # exact pinned version — never "latest"
    supported_primitives = frozenset({"choice"})

    def decide(self, ctx: CaseContext):
        # ctx.input is the variant input (prompt, options, ...);
        # ctx.case_id, ctx.primitive, ctx.attacked / ctx.variant included.
        # Gold labels are structurally absent — there is no field to leak.
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
| `peira[hf]` | `pip install peira[hf]` | + Hugging Face deps (for adapters you write) |
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
