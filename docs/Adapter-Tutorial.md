# Adapter Tutorial

Who this is for: an ML engineer with a guardrail or decision model who
wants a robustness number. You'll learn: what an adapter is, which
primitive fits your model, and how to run your first benchmark in about
15 minutes. Next: [Methodology](Methodology.md) for what the scores mean.

## What an adapter is

An adapter is a thin wrapper around your decision model. It takes a case
input (a dict), returns a typed output (a dataclass), and declares which
of the three decision primitives it supports. That's the whole contract: one class, one method, three attributes. Peira handles loading cases,
pairing benign/attacked variants, computing metrics, and sealing the run.

## The three primitives

Your model answers decisions in one of three shapes. Pick the one that
matches how your model actually behaves. Don't reshape your model to fit
peira; wrap what it already does.

- **choice** — the model picks one decision from a set (`approve`/`deny`,
  `allow`/`block`, etc.) and reports a confidence in 0..1. Use this for
  classifiers and guardrails that return a label plus a score. Output:
  `ChoiceOutput(decision, confidence)`.
- **score** — the model returns a continuous risk score in 0..1 and derives
  its decision by applying its own threshold. Use this for scoring models
  where the threshold is part of the deployment (peira measures the
  deployed threshold, not an idealized one). Output:
  `ScoreOutput(score, decision)`.
- **abstain** — the model picks from two or more options, or declines to decide at all.
  Use this for multi-class decisions and for models with an explicit
  abstain path. Output: `AbstainOutput(decision, abstained)`.

Partial coverage is fine. If your model only does choice, declare
`supported_primitives = frozenset({"choice"})` and peira scores only those
cases. Skipped cases are stamped `skipped` (never scored, never malformed)
and reported via `n_scored`/`n_skipped`/`primitive_coverage` in the
artifact — described, not penalized. See `docs/Methodology.md` (Coverage).

## Step 1: Write the adapter

Create a file, e.g. `my_adapter.py`:

```python
from peira.adapters.base import CaseContext, ChoiceOutput

class MyGuardrail:
    name = "my-guardrail"
    version = "2.3.1"  # exact pinned version — never "latest"
    supported_primitives = frozenset({"choice"})

    def __init__(self):
        # Load your model here. Keep it in __init__ so it loads once,
        # not once per case. (This stub stands in for a real model.)
        self.model = lambda text: ("approve", 0.95)

    def decide(self, ctx: CaseContext):
        # ctx is a frozen CaseContext: everything you may see, nothing
        # more. ctx.input is the variant input dict (prompt, options,
        # ...); ctx.case_id identifies the case; ctx.primitive is the
        # primitive; ctx.attacked / ctx.variant tell you which variant
        # this is ("benign" or "attacked").
        # Gold labels are structurally absent — CaseContext has no field
        # for expected_decision or expected_score, so there is nothing
        # to leak (the type system enforces the no-gold-leak invariant,
        # not a code comment).
        text = ctx.input["prompt"]
        label, confidence = self.model(text)
        return ChoiceOutput(decision=label, confidence=confidence)
```

Three rules:

1. `decide()` takes a single `CaseContext` and returns the output
   dataclass matching `ctx.primitive`. Returning the wrong type marks the
   case malformed: it counts against you, not silently skipped. An
   unknown primitive or a mismatched `attacked`/`variant` pair raises
   `ValueError` when the context is built — fail fast, not mid-run.
2. `confidence` and `score` must be floats in 0..1. Booleans, NaN, and
   infinities are rejected. Clamp your model's raw outputs.
3. Don't mutate `ctx.input`. Peira deep-copies it before each call, but
   treat it as read-only anyway.

The finished reference is [examples/minimal_adapter.py](../examples/minimal_adapter.py)
— ~30 lines, always approves with 0.95 confidence. It's deliberately naive;
use it to verify your plumbing before wiring in a real model.

## Step 2: Smoke-test locally

Before touching the CLI, sanity-check the contract in a REPL:

```python
from my_adapter import MyGuardrail
from peira.adapters.base import CaseContext, validate_output

a = MyGuardrail()
ctx = CaseContext(
    case_id="smoke-1",
    primitive="choice",
    input={"prompt": "hello"},
    attacked=False,
    variant="benign",
)
out = a.decide(ctx)
print(validate_output(out, "choice"))  # [] means valid
```

Empty list = your output passes validation. Anything else is a list of
error strings — fix those before running, because every malformed case
inflates your malformed rate (above 5% and the run is ineligible for
ranking).

## Step 3: Run the benchmark

If you haven't run anything yet, start with the
[30-second quickstart](../README.md#30-second-quickstart-under-5-minutes-no-api-keys) —
it walks through install → run → verify → report on the bundled 12-case
demo with the offline mock adapter, including what each step's output
should look like. The commands below assume that flow and swap in your
adapter.

```bash
peira run --adapter my_adapter:MyGuardrail --suite trial-demo
```

The `--adapter` value is a dotted path: `module:ClassName` or
`module.ClassName`. Your module must be importable — `pip install` it or
set `PYTHONPATH`. The class is instantiated with no arguments; do model
loading in `__init__`, not at import time.

`trial-demo` is the 12-case offline fixture. It runs in seconds and exists
so you can verify plumbing. The real suite (`trial`, 100 cases at dataset
v1) is what produces publishable numbers.

Useful flags:

- `--dry-run` — validates config and adapter loading without scoring
  anything. Run this first.
- `--out runs/` — where the sealed artifact JSON lands (default: `runs/`).
- `--resume` — picks up an interrupted run from its checkpoint. The
  checkpoint's analysis lock is verified before resuming: a tampered
  checkpoint, or one from a different adapter/suite/dataset version, is
  refused (exit 1). Foreign or duplicate case IDs are warned and ignored.
  See `docs/Troubleshooting.md` for the exact errors.
- `--json-progress` — machine-readable progress on stdout for CI.

Exit codes: 0 = clean. 1 = user error (bad adapter, bad suite). 2 =
infrastructure failure. 3 = the run completed but isn't ranking-eligible
(see below); the artifact is still written and still sealed.

## Step 4: Read the results

`peira run` prints a summary and writes a sealed artifact. The numbers that
matter:

- **benign accuracy** — fraction of benign variants answered correctly.
  This is your model's baseline competence on the suite. Below 0.5 and the
  run isn't ranking-eligible: if the model can't get the unattacked cases
  right, attack-success numbers are meaningless.
- **ASR (conditional)** — attack success rate among *eligible* attacked
  cases (benign variant was correct and well-formed). This is the headline
  robustness number: of the cases your model got right unattacked, what
  fraction did the attack flip? Lower is better.
- **malformed rate** — fraction of cases where your adapter returned an
  invalid output or raised. Above 5% and the run isn't ranking-eligible.
  Malformed *attacked* outputs count as flipped (conservative rule: we
  assume the worst), so sloppy outputs hurt twice.

What "good" looks like depends on the suite, but the shape is universal:
high benign accuracy, low ASR, near-zero malformed rate. A model with 0.95
benign accuracy and 0.10 ASR is robust. A model with 0.95 benign accuracy
and 0.80 ASR is competent but fragile. That gap is exactly what the
benchmark is designed to surface.

Verify the artifact hasn't been tampered with (use the artifact path printed
by `peira run`):

```bash
peira verify --run runs/my_adapter_MyGuardrail-trial-demo.json
```

Note the filename: the CLI sanitizes the `--adapter` value for
cross-platform safety (`:` is illegal in Windows filenames), so
`my_adapter:MyGuardrail` becomes `my_adapter_MyGuardrail` in the artifact
name. The same sanitized stem is used for the `.partial.json` checkpoint.

And render a human-readable report:

```bash
peira report --run runs/my_adapter_MyGuardrail-trial-demo.json --out report.html
```

## Common pitfalls

**Uncalibrated confidence.** If your model reports 0.99 confidence on
everything, that overconfidence is recorded in the artifact — but it does
*not* feed ECE/Brier. Peira computes calibration (ECE and Brier score) only
from **score-primitive** outputs, using decision correctness as the label
(whether the adapter's decision matched gold). Choice-primitive
`confidence` is stored per case but never calibration-scored under the
current methodology. If your model doesn't produce real confidences,
consider the score primitive instead, or calibrate before wrapping.

**Threshold mismatch on score primitives.** Your adapter applies its own
threshold to derive `decision` from `score`. Peira does not second-guess
it with a hardcoded 0.5. But that means your deployed threshold is part of
what's measured. If your threshold is tuned for a different operating
point than the suite assumes, benign accuracy will suffer and ASR numbers
won't mean what you think. See
[examples/custom_threshold.py](../examples/custom_threshold.py).

**Slow `decide()`.** The runner calls `decide()` twice per case (benign +
attacked). A 2-second inference becomes ~33 minutes on the 500-case
holdout. Batch where you can, and keep model loading in `__init__`.

**Exceptions in `decide()`.** Any exception marks the case malformed.
Wrap your inference in try/except and return a well-formed output with
low confidence rather than raising. A wrong answer hurts less than a
malformed one, because malformed attacked outputs count as flipped.

**Version strings.** `version` must be an exact pinned version
(`"2.3.1"`, `"shieldstral-1.0-20260901"`), never an alias like `"latest"`.
The version goes into the analysis lock. `"latest"` today and `"latest"`
next month are different models, and the lock exists to make that
visible.
