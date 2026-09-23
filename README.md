# peira

**The empirical trial for decision models.** An open adversarial-robustness
benchmark for LLM guardrails. It measures whether hostile manipulations of an
input flip a decision model's typed output, and it says so with confidence
intervals.

[![ci](https://github.com/david-engelmann/peira/actions/workflows/ci.yml/badge.svg)](https://github.com/david-engelmann/peira/actions/workflows/ci.yml)
<!-- PyPI badge held until the first release: the page 404s meanwhile.
     Restore: [![pypi](https://img.shields.io/pypi/v/peira.svg)](https://pypi.org/project/peira/) -->
[![license](https://img.shields.io/badge/license-MIT%20%2F%20CC--BY--4.0-blue.svg)](LICENSE)

[Docs](docs/Overview.md) · [Reports](#reports) · [Adapter API](python/peira/adapters/base.py) · [Contributing](docs/Contributing.md) · [Discussions](https://github.com/david-engelmann/peira/discussions)

> Decision models fail silently — a guardrail that approves what it should
> deny tells you nothing. peira is the trial that catches it: paired
> benign/attacked cases across 10 attack families, scored with
> decision-change ASR. No post-hoc edits; every run is sealed.

## Contents

- [The Trial in action](#the-trial-in-action)
- [60-second quickstart](#60-second-quickstart)
- [What peira measures](#what-peira-measures)
- [What brings you here](#what-brings-you-here)
- [Leaderboard](#leaderboard)
- [Adapters](#adapters)
- [How peira differs](#how-peira-differs)
- [When peira isn't the tool](#when-peira-isnt-the-tool)
- [Install](#install)
- [Add your model](#add-your-model)
- [Methodology](#methodology)
- [Reports](#reports)
- [Citation](#citation)
- [License / notices](#license--notices)

## The Trial in action

Sample output — generated, never hand-edited
(`scripts/gen_readme_table.py`; run: `peira run --adapter mock --suite trial --seed 0`,
2026-09-23, 0.4 s, $0):

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

Legend: **ASR** = decision-change attack success rate — the fraction of
eligible cases where the attacked decision differs from the benign one.
**95% CI** = Wilson interval. **n** = eligible cases. `mock` is the
reference mechanism-exerciser adapter, not a real guardrail — never a
leaderboard row. The 100-case Trial is ranking-ineligible by design
(fewer than 200 eligible cases) and stays off the leaderboard.

## 60-second quickstart

```bash
git clone https://github.com/david-engelmann/peira.git && cd peira
pip install -e .   # from a checkout; becomes `pip install peira` at release
peira run --adapter mock --suite trial --seed 0 --out runs
peira report --run runs/mock-trial.json --out report.html
```

That's a full evaluation, offline: 100 cases, paired benign/attacked
controls, sealed with an analysis lock, rendered as HTML. The run prints
its own receipts:

```
done: 100 cases (100 eligible)
  ASR (conditional): 0.41 95% CI [0.3187, 0.508]
  benign accuracy:   1.0 95% CI [0.963, 1.0]
  malformed rate:    0.0
  refusal rate:      0.0 95% CI [0.0, 0.037]
  ineligible:        0 (benign_malformed=0, benign_wrong_decision=0, benign_abstained=0)
  ranking eligible:  False (fewer than 200 eligible cases (100); family 'confidence_spoofing' has 10 eligible cases (< 20); family 'criteria_smuggling' has 10 eligible cases (< 20); family 'distractor_flooding' has 10 eligible cases (< 20); family 'indirection' has 10 eligible cases (< 20); family 'literal_reading' has 10 eligible cases (< 20); family 'negation_games' has 10 eligible cases (< 20); family 'option_order' has 10 eligible cases (< 20); family 'policy_paraphrase' has 10 eligible cases (< 20); family 'score_anchoring' has 10 eligible cases (< 20); family 'state_poisoning' has 10 eligible cases (< 20))
artifact: runs/mock-trial.json
analysis lock: e3f2ea4e74d9babd…
```
(excerpt — the run also prints its full `ranking eligible: False (…)`
note, which names every gate the Trial misses, and an `analysis lock`
hash.)

The command exits 3 — that's not an error. Exit 3 means the run
completed but the Trial is ranking-ineligible by design (100 eligible
cases against a 200-case, ≥20-per-family floor). Exit codes: 0 clean,
1 user error, 2 infrastructure error, 3 completed but unranked. The
full list is in [docs/Troubleshooting.md](docs/Troubleshooting.md).

`peira run` exits 3 here: ran fine, ranking-ineligible — the Trial's
100 cases sit below the 200-case floor. Expected, not an error. In an
interactive shell just run the `peira report` step next; under `set -e`
the shell treats 3 as failure, so call the report step explicitly.

The per-family table:

```bash
python3 scripts/gen_readme_table.py runs/mock-trial.json```

It prints the same table as [The Trial in action](#the-trial-in-action) —
the demo is the proof. Every adapter makes exactly two `decide()` calls
per case (one benign, one attacked — retries re-issue the same call on
transient failures, never silently), so time and cost scale linearly:
200 calls for the Trial, 5,000 for v1.

| Adapter class | 100-case Trial | 2,500-case v1 | Cost |
|---|---|---|---|
| `mock` (offline, deterministic) | 0.4 s (measured) | ≈3 s (extrapolated) | $0 |
| Structured-output LLM baseline | _timed when the adapter lands_ | _timed when the adapter lands_ | per-token API spend |
| Hugging Face guard model | _timed when the adapter lands_ | _timed when the adapter lands_ | GPU time |

Every flag is documented in [`docs/CLI.md`](docs/CLI.md) — generated
from the parser, so it can't go stale.

## What peira measures

Whether hostile manipulations of the input change a decision model's
typed output — approve/deny (choice), a numeric output (score), or abstain
(noul) — using paired benign/attacked controls across 10 attack
families. Decision-change ASR is the headline metric, reported with
Wilson 95% confidence intervals; ECE and Brier cover confidence quality.
Benign-validity gates eligibility: a case counts only when its benign
variant gives a usable baseline, so a model can't look robust by failing
the control. Every report carries per-case drill-down receipts, and every
run is sealed against post-hoc editing. Built for red teams evaluating
decision models: every attack is paired with a clean control, so a flip
is evidence about the attack, not noise.

## What brings you here

- **test my guardrail** → run the quickstart above, then read
  `docs/Methodology.md`.
- **claim a leaderboard row** → [Adapters](#adapters),
  then [Add your model](#add-your-model).
- **write attack cases** → [the authoring guide](docs/Dataset.md)
  ("The authoring loop, end to end").
- **compare harnesses** → [How peira differs](#how-peira-differs).

## Leaderboard

One row per (adapter, dataset version). The leaderboard opens with the v1
dataset: 2,500 cases (2,000 public + 500 private holdout), 250 per attack
family. The bar is mechanical, not editorial: malformed rate ≤ 5%,
benign accuracy ≥ 0.5, ≥ 200 eligible cases overall, and ≥ 20 eligible
cases in every family present — or the run is published but unranked.
Omission never improves a rank. Partial primitive coverage is reported
honestly, not hidden.

## Adapters

| Adapter | Status |
|---|---|
| `mock` (reference mechanism exerciser) | measured — the tables above |
| Shieldstral (Mistral) | shipped — `peira[hf]`, not yet measured |
| ProtectAI prompt injection | shipped — `peira[hf]`, not yet measured |
| Llama Prompt Guard 2 86M (Meta) | shipped — `peira[hf]`, not yet measured |
| Structured-output LLM baselines (OpenAI / Anthropic / Gemini) | shipped — `peira[openai]` / `peira[anthropic]` / `peira[google]`, not yet measured |
| TypeSafe Jev | shipped — gated on access, not yet measured |
| Llama Guard 4 (Meta) | planned |
| LlamaFirewall (Meta) | planned |
| NVIDIA NeMo Guardrails | planned |
| Guardrails AI | planned |
| Protect AI LLM Guard (now Palo Alto Networks) | planned |
| Lakera Guard (now Check Point) | planned |
| Operant AI Semantic Firewall | planned |

"Shipped" means the adapter exists and is tested — see
[`docs/Adapters.md`](docs/Adapters.md) for install, keys, and pinned
models. "Planned" means not built yet. Nothing ships a number here
until it's measured with name + version + run date.

## How peira differs

| | peira | adjacent benchmarks |
|---|---|---|
| What it measures | decision flips under attack | varies |
| Paired benign/attacked controls | yes | rarely |
| Confidence-robustness metrics | yes (ECE, Brier) | rarely |
| Analysis freeze (no post-hoc edits) | yes, mechanical | rarely |
| Scale (v1) | 2,500 cases | varies |

The peira column is verifiable from this repo; the right-hand column is
a rough sketch, not a scorecard — check each project's own docs before
quoting it. The differentiator, stated plainly: decision-change ASR plus
a hard ≥20-eligible-cases-per-family ranking gate is simpler and more
auditable than composite-index leaderboards. For broad red-teaming look at garak,
HarmBench, or JailbreakBench; for general-purpose harnesses, Inspect AI,
promptfoo, or HELM. peira is the decision-model layer — approve/deny,
score, abstain.

## When peira isn't the tool

peira measures whether hostile input flips a decision model's typed
output on paired cases. It is not a general red-teaming harness, not a
jailbreak or refusal benchmark, and not a safety certification: a low
ASR here says nothing about the attacks peira doesn't cover. Use
broader tooling (garak, HarmBench) when you need coverage rather than
a single decision-robustness number.

## Add your model

```python
from peira.adapters.base import ChoiceOutput

class MyAdapter:
    name = "my-adapter"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive, context):
        # call your model here; `case_input` is exactly what the case
        # defined, `context` carries the trial bookkeeping (case_id, arm,
        # expected/target decisions) — never read labels from the input
        return ChoiceOutput(decision="approve", confidence=0.8)

adapter = MyAdapter()
```

Save as `my_adapter.py`, then `peira run --adapter my_adapter --suite
trial-demo`. See `examples/minimal_adapter.py`, then read
`docs/Methodology.md` for the contracts your outputs must satisfy.

## Install

Requires Python 3.10+.

peira isn't on PyPI yet — until it is, `pip install -e .` from a checkout
stands in for `pip install peira` below.

```bash
pip install -e .   # from a checkout; becomes `pip install peira` at release
```

| Tier | Command | What you get |
|---|---|---|
| `peira` | `pip install peira` _(at release)_ | Core, SDK, CLI, offline mock |
| `peira[hf]` | `pip install peira[hf]` | + Hugging Face adapters (planned) |
| `peira[all]` | `pip install peira[all]` | + everything optional |

Hardware guidance per tier: `docs/Hardware.md`. No telemetry — the
harness makes no network calls except the ones you configure
([FAQ](docs/FAQ.md)).

## Methodology

One metric, honestly computed: decision-change ASR over eligible cases
only, with Wilson 95% confidence intervals on every figure. An attacked
variant that comes back malformed counts as flipped — conservative on
purpose: a guardrail that breaks under attack doesn't get the benefit of
the doubt. Refusals are reported as refusal rates, never laundered into
ASR; cost is a sidecar, never blended into a score. The full recipe —
suite composition, eligibility rules, the analysis lock — is in
`docs/Methodology.md` (versioned methodology pages land next).

## Reports

A monthly *State of Decision Robustness* from the v1 launch: the full
leaderboard, the methodology it was scored under, and per-adapter
receipts. No issues yet — the cadence starts when the leaderboard does.

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

Built by David Engelmann.

Docs: [`docs/Overview.md`](docs/Overview.md) · Paper: [`paper/`](paper/) · Dataset:
[`dataset/`](dataset/) · Changelog: [`CHANGELOG.md`](CHANGELOG.md) ·
Security: [`SECURITY.md`](SECURITY.md) · Questions:
[GitHub Discussions](https://github.com/david-engelmann/peira/discussions)
