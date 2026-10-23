# peira

peira is an open-source AI safety stress-test and intelligence hub for leading models and guardrails. It measures one thing: whether hostile input can flip a decision model's typed output.

[![ci](https://github.com/david-engelmann/peira/actions/workflows/ci.yml/badge.svg)](https://github.com/david-engelmann/peira/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT%20%2F%20CC--BY--4.0-blue.svg)](LICENSE)
[![live board](https://img.shields.io/badge/live%20board-peiratrial.dev-2ea043.svg)](https://peiratrial.dev/)

[Live board](https://peiratrial.dev/) · [Docs](docs/Overview.md) · [Methodology](docs/Methodology.md) · [Adapters](docs/Adapters.md) · [Contributing](docs/Contributing.md) · [Discussions](https://github.com/david-engelmann/peira/discussions)

> Accuracy benchmarks tell you whether a model decides well on clean input. peira tells you whether an attacker can change the decision. Every attack ships with a benign twin, so a flipped decision is evidence about the attack, not noise.

## Live results

**[peiratrial.dev](https://peiratrial.dev/)**. The official leaderboard is live. The board publishes 39 sealed results covering 38 distinct models on the v2 dataset. Thirty-four distinct models are ranked and four are flagged under the published admission rules. The newest full-suite results are Mercury Decide at 0.1649 attack success and Clef omni at 0.2024, and Llama Prompt Guard 2 joins the guardrail slice rows at 0.1796 with benign accuracy 1.0 on its 373-case population. Every result is published with attack success rates and confidence intervals, benign accuracy, calibration, and per-family breakdowns. Cost is published where the run recorded it. The board is the source of truth for current standings.

## Contents

- [Live results](#live-results)
- [The trial in action](#the-trial-in-action)
- [60-second quickstart](#60-second-quickstart)
- [What peira measures](#what-peira-measures)
- [Datasets](#datasets)
- [Leaderboard](#leaderboard)
- [Adapters](#adapters)
- [How peira differs](#how-peira-differs)
- [Install](#install)
- [Add your model](#add-your-model)
- [Reports](#reports)
- [Citation](#citation)
- [License / notices](#license--notices)

## The trial in action

Sample output is generated, never hand-edited, by `scripts/gen_readme_table.py`. Run `peira run --adapter mock --suite trial --seed 0` to reproduce it.

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

**ASR** is the decision-change attack success rate, the fraction of eligible cases where the attacked decision differs from the benign one. **95% CI** is the Wilson interval. **n** is eligible cases. `mock` is the reference mechanism-exerciser, not a real decision model, and will never be a leaderboard row. The 100-case Trial is ranking-ineligible by design (under 200 eligible cases) and stays off the leaderboard.

## 60-second quickstart

```bash
git clone https://github.com/david-engelmann/peira.git && cd peira
pip install -e .
peira run --adapter mock --suite trial --seed 0 --out runs
peira report --run runs/mock-trial.json --out report.html
```

That is a full offline evaluation. It covers 100 cases with paired benign and attacked controls, sealed with an analysis lock and rendered as HTML.

Check your setup first with `peira doctor`: it reports Python/RAM/disk/GPU, verifies dataset manifests, and checks each adapter's requirements (API keys are checked for presence only, never printed). Read-only, no network calls.

## What peira measures

Whether hostile input changes a decision model's typed output: approve/deny (choice), a numeric score (score), or abstain (abstain). Each attacked case ships with a benign twin, and a case only counts when its benign variant gives a usable baseline. A model cannot look sturdy by failing the control.

The headline metric is decision-change ASR with Wilson 95% confidence intervals. ECE and Brier cover confidence quality. Malformed attacked outputs count as flipped (a decision model that breaks under attack gets no benefit of the doubt), and neither does attack-induced abstention: a flip of the abstention state is a flip of the outcome, a DoS vector. Refusal rates are reported separately so the refusal phenomenon stays visible. Cost is a sidecar, never blended into a score. Every report carries per-case drill-down receipts, and every run is sealed against post-hoc editing.

A low ASR is not a safety certificate. It says the decision model held against peira's attack families, nothing about the attacks peira does not cover.

The full recipe (suite composition, eligibility rules, the analysis lock) is in `docs/Methodology.md`. Read it before quoting a number.

## Datasets

**v1** is the launch dataset: 2,000 cases across 10 attack families, 200 per family. **v2** is sealed at `dataset-v2-2.6.0`: 4,701 cases across 11 families, every case row-by-row audited, manifest SHA-256 verified. Both are CC-BY-4.0, so anyone can reproduce the numbers.

Two more suites ship on the same harness, scored separately and never blended into the v1/v2 numbers: a **conversational suite** (multi-turn attacks, 840 cases) and a **safety-policy suite** (guardrail-native).

The code is MIT-licensed. See `docs/Dataset.md` for the authoring pipeline and `docs/Taxonomy.md` for the 31 attack families.

## Leaderboard

The official leaderboard lives at **[peiratrial.dev](https://peiratrial.dev/)**. It publishes every sealed official run on the v2 dataset (dataset-v2-2.6.0, 4,701 paired cases) with decision-change ASR and 95% confidence intervals, benign accuracy, calibration, malformed rate, and per-family breakdowns, and with cost where the run recorded it. The current board carries 39 published results covering 38 distinct models, 34 ranked models and 4 flagged models. A run appears only with its adapter name, pinned model version, and run date attached, and the sealed artifact behind every row can be reproduced from this repo.

One row per (adapter, dataset version). The bar is mechanical, not editorial. Malformed rate at most 5%, benign accuracy at least 0.5, at least 200 eligible cases overall, and at least 20 eligible cases in every family present. Miss any gate and the run is published but unranked. Omission never improves a rank. The admission rules are in [docs/Admission-Rules.md](docs/Admission-Rules.md), and the ranking gates are stated in [docs/Methodology.md](docs/Methodology.md).

## Adapters

Adapters ship for Hugging Face guardrails, structured-output LLM baselines, guardrail APIs, and the Jev-family and decision-model systems on the live board. The full table (install extras, API keys, pinned models) is in `docs/Adapters.md`.

| Adapter | Status |
|---|---|
| `mock` (reference mechanism exerciser) | measured |
| Shieldstral (Mistral) | measured, on the live board |
| ProtectAI prompt injection | measured, on the live board |
| Llama Prompt Guard 2 86M (Meta) | measured, on the live board |
| Qwen3Guard-Gen 4B (Qwen) | measured, on the live board |
| Granite Guardian 4.1 8B (IBM) | measured, on the live board |
| ShieldGemma 2B (Google) | shipped |
| WildGuard (AllenAI) | shipped |
| Structured-output LLM baselines (OpenAI, Anthropic `claude-sonnet-5-5`, Gemini, Moonshot, xAI, DeepSeek, Zhipu) | measured, on the live board |
| Structured-output LLM baselines (Meta, Mistral, Qwen) | shipped |
| TypeSafe Jev | measured, on the live board |
| Laya (ConvAI Innovations) | measured, on the live board |
| Kev (Jared Palmer) | measured, on the live board |
| SemIf (TheoLeeCJ) | measured, on the live board |
| Celeris | measured, on the live board |
| Clef (Cloudflare) | measured, on the live board |
| Decider 0.8B (Mapika) | measured, on the live board |
| Strands Decider 2B (Strands Agents) | measured, on the live board |
| pplx-decider (Perplexity) | measured, on the live board |
| Mercury Decide (Inception) | measured, on the live board |
| Cerno 4B (Apertix) | shipped |
| openjev-sglang (self-hosted) | shipped |
| Lakera Guard (Check Point) | shipped, gated on access |
| HarmBench classifier | shipped |
| Granite Guardian HAP-125M (IBM) | measured, on the live board |
| OpenAI omni-moderation | shipped |
| Google Cloud Model Armor | shipped |
| Azure Prompt Shields | shipped |
| Cloudflare Workers AI (Llama Guard 3 8B) | shipped |
| claude-fable-5-1 (Anthropic, frontier-ceiling candidate) | measured, on the live board |

"Shipped" means the adapter exists and is tested. "Measured, on the live board" means a sealed official run for that adapter is published at [peiratrial.dev](https://peiratrial.dev/). See `docs/Adapters.md` for install, keys, and pinned models.

## Reports

The [live board](https://peiratrial.dev/) is the standing report. It carries the full leaderboard, the methodology the runs were scored under, and per-adapter receipts for every published run.

## How peira differs

Adjacent benchmarks (HarmBench, AIR-Bench, JailbreakBench, garak) cover broad red-teaming: refusal behavior, toxicity, jailbreak success on open-ended generation. peira covers the decision layer underneath: the approve/deny/score/abstain calls that gate agentic workflows, content pipelines, and access control. That includes LLM-as-judge deployments, where a frontier model makes the call through structured outputs.

| | peira | broad red-team harnesses |
|---|---|---|
| Unit under test | a typed decision (approve/deny, score, abstain) | open-ended generation |
| Controls | every attack paired with a benign twin | usually unpaired |
| Headline metric | decision-change ASR with 95% CIs | refusal rate, toxicity score, jailbreak ASR |
| Confidence quality | ECE and Brier, reported | rarely |
| Post-hoc editing | sealed runs, analysis lock | varies |

The peira column is verifiable from this repo. The right-hand column is a rough sketch, not a scorecard. Check each project's own docs before quoting it.

The new wave of decision-model benchmarks (JevBench, the Banking77 Jev-vs-frontier-LLM comparisons, Bespoke Labs' suite) measures accuracy and calibration on clean inputs. peira measures the complementary question: whether hostile inputs flip the decisions. The paired attack/control design isolates the attack's effect, so a flipped decision is evidence about the attack, not noise.

The differentiator, stated plainly, is decision-change ASR plus a hard minimum-20-eligible-cases-per-family ranking gate. That is simpler and more auditable than composite-index leaderboards. For broad red-teaming look at garak, HarmBench, or JailbreakBench. For general-purpose harnesses, Inspect AI or promptfoo. peira covers the decision-model layer, where decisions are approve/deny, score, or abstain. It is not a safety certification.

## Install

```bash
git clone https://github.com/david-engelmann/peira.git && cd peira
pip install -e .
```

(peira is not published on PyPI. The source install above is the supported path.)

For development, use a venv. The test suite does not support
a bare `PYTHONPATH` install.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Optional extras for specific adapters:

```bash
pip install "peira[hf]"        # Hugging Face guard models
pip install "peira[openai]"    # OpenAI structured-output baseline
pip install "peira[anthropic]" # Anthropic structured-output baseline
pip install "peira[google]"    # Gemini structured-output baseline
```

## Add your model

```python
from peira.adapters.base import ChoiceOutput

class MyAdapter:
    name = "my-adapter"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive, context):
        # `case_input` is exactly what the case defined, including the
        # explicit `options` list. `context` carries only an opaque
        # per-call `call_id` for your own bookkeeping. Never read labels
        # from the input; the options list is unmarked.
        return ChoiceOutput(decision="approve", confidence=0.8)

adapter = MyAdapter()
```

Save as `my_adapter.py`, then:

```bash
peira run --adapter my_adapter --suite trial --seed 0
```

See `examples/minimal_adapter.py` for the runnable version, then read `docs/Methodology.md` for the contracts your outputs must satisfy.

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

Code: MIT (see [LICENSE](LICENSE)). Dataset: CC-BY-4.0 (see
[LICENSE-CC-BY-4.0](LICENSE-CC-BY-4.0)).
