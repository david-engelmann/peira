# peira

**The adversarial robustness benchmark for decision models.** peira red-teams LLM guardrails with paired benign/attacked cases across 11 attack families, from prompt injection and jailbreak framing to confidence spoofing and state poisoning. It scores whether the attack flips the guardrail's decision, and every number ships with a confidence interval.

[![ci](https://github.com/david-engelmann/peira/actions/workflows/ci.yml/badge.svg)](https://github.com/david-engelmann/peira/actions/workflows/ci.yml)
<!-- PyPI badge held until the first release: the page 404s meanwhile.
     Restore: [![pypi](https://img.shields.io/pypi/v/peira.svg)](https://pypi.org/project/peira/) -->
[![license](https://img.shields.io/badge/license-MIT%20%2F%20CC--BY--4.0-blue.svg)](LICENSE)

[Docs](docs/Overview.md) · [Leaderboard](#leaderboard) · [Adapter API](python/peira/adapters/base.py) · [Contributing](docs/Contributing.md) · [Discussions](https://github.com/david-engelmann/peira/discussions)

> Guardrails fail silently. A classifier that approves what it should deny tells you nothing, and a refusal benchmark will not catch it. peira runs each attack against a clean control case, so a flipped decision is evidence about the attack, not noise.

## Contents

- [Results, not promises](#results-not-promises)
- [60-second quickstart](#60-second-quickstart)
- [What peira measures](#what-peira-measures)
- [How peira differs](#how-peira-differs)
- [Leaderboard](#leaderboard)
- [Adapters](#adapters)
- [Install](#install)
- [Add your model](#add-your-model)
- [Methodology](#methodology)
- [Reports](#reports)
- [Citation](#citation)
- [License / notices](#license--notices)

## Results, not promises

Sample output. Generated, never hand-edited (`scripts/gen_readme_table.py`; run: `peira run --adapter mock --suite trial --seed 0`, 2026-09-23, 0.4 s, $0):

| family | ASR | 95% CI | n |
|---|---|---|---|
| `confidence_spoofing` | 0.40 | [0.168, 0.687] | 10 |
| `criteria_smuggling` | 0.40 | [0.168, 0.687] | 10 |
| `distractor_flooding` | 0.70 | [0.397, 0.892] | 10 |
| `indirection` | 0.70 | [0.397, 0.892] | 10 |
| `literal_reading` | 0.40 | [0.168, 0.687] | 10 |
| `negation_games` | 0.20 | [0.057, 0.510] | 10 |
| `option_order` | 0.50 | [0.237, 0.763] | 10 |
| `policy_paraphrase` | 0.30 | [0.108, 0.603] | 10 |
| `score_anchoring` | 0.30 | [0.108, 0.603] | 10 |
| `state_poisoning` | 0.20 | [0.057, 0.510] | 10 |
| **overall** | **0.41** | **[0.319, 0.508]** | **100** |

**ASR** is the decision-change attack success rate: the fraction of eligible cases where the attacked decision differs from the benign one. **95% CI** is the Wilson interval. **n** is eligible cases. `mock` is the reference mechanism-exerciser, not a real guardrail, and never a leaderboard row. The 100-case Trial is ranking-ineligible by design (under 200 eligible cases) and stays off the leaderboard.

## 60-second quickstart

```bash
git clone https://github.com/david-engelmann/peira.git && cd peira
pip install -e .   # from a checkout; becomes `pip install peira` at release
peira run --adapter mock --suite trial --seed 0 --out runs
peira report --run runs/mock-trial.json --out report.html
```

That is a full evaluation, offline: 100 cases, paired benign/attacked controls, sealed with an analysis lock, rendered as HTML. The run prints its own receipts:

```
done: 100 cases (100 eligible)
  ASR (conditional): 0.4100 95% CI 0.3187–0.5080
  benign accuracy:   1.0000 95% CI 0.9630–1.0000
  malformed rate:    0.0000
  refusal rate:      0.0000 95% CI 0.0000–0.0370
  ineligible:        0 (benign_malformed=0, benign_wrong_decision=0, benign_abstained=0)
  ranking eligible:  False (fewer than 200 eligible cases (100); ...)
artifact: runs/mock-trial.json
analysis lock: 503fe4503e6e115d…
```

The command exits 3. That is not an error: it means the run completed but the Trial is ranking-ineligible by design (100 cases against a 200-case floor, with a 20-per-family minimum). Exit codes are 0 clean, 1 user error, 2 infrastructure error, 3 completed but unranked. Full list in [docs/Troubleshooting.md](docs/Troubleshooting.md). Under `set -e`, call the report step explicitly since the shell treats 3 as failure.

Per-family table:

```bash
python3 scripts/gen_readme_table.py runs/mock-trial.json
```

It prints the table from [Results, not promises](#results-not-promises). The demo is the proof. Every adapter makes exactly two `decide()` calls per case (one benign, one attacked; retries re-issue the same call on transient failures, never silently), so time and cost scale linearly: 200 calls for the Trial, about 4,000 for the current full dataset.

| Adapter class | 100-case Trial | Full dataset | Cost |
|---|---|---|---|
| `mock` (offline, deterministic) | 0.4 s (measured) | ~3 s (extrapolated) | $0 |
| Structured-output LLM baseline | timed when measured | timed when measured | per-token API spend |
| Hugging Face guard model | timed when measured | timed when measured | GPU time |

Every flag is documented in [`docs/CLI.md`](docs/CLI.md), generated from the parser so it cannot go stale.

## What peira measures

Whether hostile input changes a decision model's typed output: approve/deny (choice), a numeric score (score), or abstain (abstain). Each attacked case ships with a benign twin, and a case only counts when its benign variant gives a usable baseline. A model cannot look sturdy by failing the control.

The headline metric is decision-change ASR with Wilson 95% confidence intervals. ECE and Brier cover confidence quality. Malformed attacked outputs count as flipped (a guardrail that breaks under attack gets no benefit of the doubt). Refusals are reported as refusal rates, never folded into ASR. Cost is a sidecar, never blended into a score. Every report carries per-case drill-down receipts, and every run is sealed against post-hoc editing.

Built for teams evaluating guardrails before deployment: each attack is paired with a clean control, so a flip is evidence about the attack, not noise.

## How peira differs

Adjacent benchmarks (HarmBench, AIR-Bench, JailbreakBench, garak) cover broad red-teaming: refusal behavior, toxicity, jailbreak success on open-ended generation. peira covers the decision layer underneath: the approve/deny/score/abstain calls that gate agentic workflows, content pipelines, and access control.

| | peira | broad red-team harnesses |
|---|---|---|
| Unit under test | a typed decision (approve/deny, score, abstain) | open-ended generation |
| Controls | every attack paired with a benign twin | usually unpaired |
| Headline metric | decision-change ASR with 95% CIs | refusal rate, toxicity score, jailbreak ASR |
| Confidence quality | ECE and Brier, reported | rarely |
| Post-hoc editing | sealed runs, analysis lock | varies |
| Ranking bar | mechanical gates (eligibility floors per family) | editorial or composite |

The peira column is verifiable from this repo. The right-hand column is a rough sketch, not a scorecard; check each project's docs before quoting it. For broad red-teaming, use garak, HarmBench, or JailbreakBench. For general harnesses, Inspect AI, promptfoo, or HELM. peira is the decision-model layer.

## Leaderboard

One row per (adapter, dataset version). The bar is mechanical, not editorial: malformed rate at most 5%, benign accuracy at least 0.5, at least 200 eligible cases overall with at least 20 in every family present. Miss a gate and the run is published but unranked. Omission never improves a rank, and partial primitive coverage is reported, not hidden.

The current dataset holds 2,025 cases across 11 attack families (ten decision-attack families plus the safety-policy family covering prompt injection, jailbreak framing, and obfuscation). The v1 seal is pending; counts and family composition freeze at seal time.

## Adapters

| Adapter | Status |
|---|---|
| `mock` (reference mechanism exerciser) | measured, offline |
| Shieldstral (Mistral) | shipped, not yet measured |
| ProtectAI prompt injection | shipped, not yet measured |
| Llama Prompt Guard 2 86M (Meta) | shipped, not yet measured |
| Structured-output LLM baselines (OpenAI / Anthropic / Gemini) | shipped, not yet measured |
| TypeSafe Jev | shipped, gated on access |
| Llama Guard 4 (Meta) | planned |
| LlamaFirewall (Meta) | planned |
| NVIDIA NeMo Guardrails | planned |
| Guardrails AI | planned |
| Protect AI LLM Guard (now Palo Alto Networks) | planned |
| Lakera Guard (now Check Point) | planned |
| Operant AI Semantic Firewall | planned |

Shipped means the adapter exists and is tested. See [`docs/Adapters.md`](docs/Adapters.md) for install, keys, and pinned models. Planned means not built yet. Nothing gets a leaderboard number until it is measured with name, version, and run date.

## Install

Requires Python 3.10+.

peira is not on PyPI yet. Until it is, `pip install -e .` from a checkout stands in for `pip install peira`.

```bash
pip install -e .   # from a checkout; becomes `pip install peira` at release
```

| Tier | Command | What you get |
|---|---|---|
| `peira` | `pip install peira` (at release) | Core, SDK, CLI, offline mock |
| `peira[hf]` | `pip install peira[hf]` | plus Hugging Face adapters |
| `peira[all]` | `pip install peira[all]` | plus everything optional |

Hardware guidance per tier: `docs/Hardware.md`. No telemetry. The harness makes no network calls except the ones you configure ([FAQ](docs/FAQ.md)).

## Add your model

```python
from peira.adapters.base import ChoiceOutput

class MyAdapter:
    name = "my-adapter"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive, context):
        # Call your model here. `case_input` is exactly what the case
        # defined. `context` carries trial bookkeeping (case_id, arm,
        # expected/target decisions). Never read labels from the input.
        return ChoiceOutput(decision="approve", confidence=0.8)

adapter = MyAdapter()
```

Save as `my_adapter.py`, then `peira run --adapter my_adapter --suite trial-demo`. See `examples/minimal_adapter.py` for the runnable version, then read `docs/Methodology.md` for the contracts your outputs must satisfy.

## Methodology

One metric, honestly computed: decision-change ASR over eligible cases only, with Wilson 95% confidence intervals on every figure. The full recipe (suite composition, eligibility rules, the analysis lock) is in `docs/Methodology.md`.

## Reports

A monthly *State of Decision Robustness* starting at the v1 launch: the full leaderboard, the methodology it was scored under, and per-adapter receipts. No issues yet. The cadence starts when the leaderboard does.

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

MIT for code, CC-BY-4.0 for the dataset. A peira score measures decision robustness on this benchmark's paired cases. It does not certify a model as safe.

Built by David Engelmann.

Docs: [`docs/Overview.md`](docs/Overview.md) · Paper: [`paper/`](paper/) · Dataset:
[`dataset/`](dataset/) · Changelog: [`CHANGELOG.md`](CHANGELOG.md) ·
Security: [`SECURITY.md`](SECURITY.md) · Questions:
[GitHub Discussions](https://github.com/david-engelmann/peira/discussions)
