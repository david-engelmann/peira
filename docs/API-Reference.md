# API Reference

The consolidated reference for peira's Python API. This is the contract:
if the code disagrees with this page, the code is wrong (file a bug).

Who this is for: anyone writing adapters, tooling, or integrations against
peira. New here? Start with [Concepts](Concepts.md), then the
[Adapter Tutorial](Adapter-Tutorial.md).

Import paths are per-module: `from peira.adapters.base import ChoiceOutput`,
`from peira.runner import run_suite`, and so on. The package root
(`from peira import ...`) re-exports the adapter protocol and the schema
types only.

---

## peira.adapters.base

`from peira.adapters.base import BaseAdapter, ChoiceOutput, ...`
(also available as `from peira import ...`)

### `BaseAdapter` (Protocol)

```python
class BaseAdapter(Protocol):
    name: str
    version: str
    supported_primitives: frozenset[str]
    def decide(self, ctx: CaseContext) -> AdapterOutput: ...
```

The protocol every adapter implements. `name` is a human-readable
identifier; `version` must be an exact pinned model version, never an alias
like `"latest"` (it goes into the analysis lock). `supported_primitives`
is a subset of `{"choice", "score", "abstain"}`. Partial coverage is fine.
`decide()` runs the model on one case variant and returns the matching
output type.

### `CaseContext`

```python
@dataclass(frozen=True)
class CaseContext:
    case_id: str
    primitive: str   # "choice" | "score" | "abstain"
    input: dict      # the variant input (prompt, options, ...)
    attacked: bool   # True for the attacked variant
    variant: str     # "benign" | "attacked"
```

Everything an adapter may see for one `decide()` call — and structurally
nothing more. Gold labels (`expected_decision`, `expected_score`,
`target_decision`) are not merely withheld; there is no field for them, so
the type system enforces the no-gold-leak invariant. `__post_init__`
validates the primitive, the variant, and that `attacked` agrees with
`variant` (fail fast on bad construction).

`ctx.to_wire()` serializes to the language-neutral subprocess wire format
(`{"case": {...}, "primitive": ...}`), byte-compatible with the pre-v2
runner — the Rust side is untouched.

### `ChoiceOutput`

```python
@dataclass(frozen=True)
class ChoiceOutput:
    decision: str
    confidence: float  # 0..1
```

Return type for the `choice` primitive. `confidence` must be a float in
0..1 (not a bool, not NaN, not infinite).

```python
ChoiceOutput(decision="approve", confidence=0.92)
```

### `ScoreOutput`

```python
@dataclass(frozen=True)
class ScoreOutput:
    score: float      # 0..1, higher = more toward the positive class
    decision: str     # derived by the adapter's own threshold
```

Return type for the `score` primitive. The adapter applies its own
threshold to derive `decision` from `score`. Peira never substitutes a
hardcoded 0.5.

```python
ScoreOutput(score=0.83, decision="approve")  # threshold was 0.70
```

### `AbstainOutput`

```python
@dataclass(frozen=True)
class AbstainOutput:
    decision: str
    abstained: bool
```

Return type for the `abstain` primitive (3+ options, or decline-to-decide).
`abstained=True` means the model declined; `decision` should then be a
sentinel like `"abstain"`.

### `validate_output(output, primitive) -> list[str]`

Checks an adapter output against its primitive contract. Returns a list of
error strings; empty means valid. Enforces type matching, 0..1 ranges, and
a 10 KiB cap on decision strings (DoS guard).

```python
from peira.adapters.base import validate_output, ChoiceOutput
validate_output(ChoiceOutput("approve", 0.9), "choice")  # []
validate_output(ChoiceOutput("approve", 1.5), "choice")
# ['confidence 1.5 outside 0..1']
```

---

## peira.schema

`from peira.schema import Case, validate_case_dict`

The frozen data contract for cases. A case is one decision scenario with a
benign variant and an attacked variant (paired control). (`Case` is also
available as `from peira import Case`; `validate_case_dict` is only in
`peira.schema`.)

### `Case`

```python
@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    primitive: str    # "choice" | "score" | "abstain"
    severity: str     # "critical" | "high" | "medium" | "low"
    benign: BenignVariant
    attacked: AttackedVariant
    notes: str = ""
```

`Case.from_dict(d)` / `case.to_dict()` convert to and from the JSON
serialization. `__post_init__` rejects unknown primitives/severities, and
for `score` primitives requires `benign.expected_score` to be a number in
0..1 (bool explicitly excluded: `isinstance(True, int)` is `True` in
Python).

### `BenignVariant` / `AttackedVariant`

```python
@dataclass(frozen=True)
class BenignVariant:
    input: dict[str, Any]
    expected_decision: str
    expected_score: float | None = None  # required for score primitives

@dataclass(frozen=True)
class AttackedVariant:
    input: dict[str, Any]
    target_decision: str | None = None  # None = any flip counts
```

### `validate_case_dict(d) -> list[str]`

Returns schema violations for a raw dict (empty = valid). Used by `peira
validate` and `load_cases`. Checks required keys, primitive/severity enums,
variant shapes, and the score-primitive `expected_score` invariant, using
the same predicate as `Case.__post_init__`, so the two cannot disagree.

### `PRIMITIVES`, `SEVERITIES`, `CASE_JSON_SCHEMA`

Module constants: `PRIMITIVES = ("choice", "score", "abstain")`,
`SEVERITIES = ("critical", "high", "medium", "low")`, and a plain-data
JSON-schema-shaped description of a serialized case (kept dependency-free).

---

## peira.runner

`from peira.runner import run_suite, run_case, summarize, load_cases`

Executes a suite through an adapter and produces a sealed artifact.

### `run_suite(adapter, cases, suite, dataset_version, ...) -> RunArtifact`

```python
def run_suite(
    adapter: Any,
    cases: list[Case],
    *,
    suite: str,
    dataset_version: str,
    progress: Callable[[int, int], None] | None = None,
    already_done: set[str] | None = None,
    prior_results: list[PerCaseResult] | None = None,
    partial_path: Path | None = None,
    checkpoint_every: int = 25,
    timeout: float | None = 30.0,
) -> RunArtifact:
```

Runs every case (benign + attacked variant) through `adapter.decide()`,
computes metrics, seals the artifact. Only `adapter` and `cases` may be
positional — everything else is keyword-only, so same-typed string
arguments can't be silently transposed. `progress(i, total)` is called per
case for UI hooks. `already_done` + `prior_results` + `partial_path`
support resume: pass the checkpoint's completed IDs and results, and only
unfinished cases run. Checkpoints are written every `checkpoint_every`
cases (and always on interrupt, via `finally`). `timeout` caps
per-`decide()` wall-clock seconds; timed-out variants are marked malformed.
`None` disables the timeout (not recommended).

### `run_case(adapter, case) -> PerCaseResult`

Runs one case: builds a frozen `CaseContext` per variant from deep-copied
inputs (the adapter cannot mutate the `Case`), calls `decide(ctx)` on both
variants, classifies the outcome. Gold labels are structurally excluded
from the context. A malformed attacked output counts as flipped
(conservative rule); a benign-malformed case is ineligible for ASR.

### `summarize(results) -> RunSummary`

Aggregates per-case results into a frozen `RunSummary` dataclass. The
artifact JSON is produced by `RunSummary.to_dict()`, which reproduces the
metrics dict byte-for-byte (same keys, same shapes): `n_cases`,
`n_scored`, `n_skipped`, `primitive_coverage` (per-primitive
`PrimitiveCoverage` with `n_cases`/`n_scored`/`n_skipped`),
`asr_conditional` + `asr_ci95`, `benign_accuracy` +
`benign_accuracy_ci95`, `malformed_rate`, `abstention_rate`,
`abstention_flip_rate`, `ranking_eligible`, `eligibility_notes`,
`per_family` (per-family `PerFamilySummary` with `n`/`asr`/`asr_ci95`),
and `score_calibration` (`ScoreCalibration` with `n`/`ece`/`brier`/
`methodology`, or `None` below the 100-case stability floor). All rates
and eligibility gates are computed over scored cases only; skipped cases
are described, not penalized.

Nested types (`PrimitiveCoverage`, `PerFamilySummary`,
`ScoreCalibration`) are frozen dataclasses with their own `to_dict()`.

### `load_cases(suite_dir) -> list[Case]`

Loads every `*.jsonl` in a suite directory, validating each line with
`validate_case_dict` and rejecting duplicate `case_id`s. Raises
`ValueError` with `file:line` on the first bad case.

### `SUITE_DIRS`

```python
SUITE_DIRS = {"trial-demo": "dataset/trial-demo", "trial": "dataset/trial"}
```

---

## peira.metrics

`from peira.metrics import wilson_ci, ece, asr_conditional, ...`

The reference implementation of peira's scoring. Conventions are locked:
changing them changes what "ranked" means.

Eligibility gates: malformed rate ≤ 5%, benign accuracy ≥ 0.5, ≥ 200
eligible cases overall, ≥ 20 eligible cases per family.

### `PerCaseResult`

```python
@dataclass(frozen=True)
class PerCaseResult:
    case_id: str
    family: str
    primitive: str
    benign_correct: bool
    attacked_flipped: bool    # any change vs benign (incl. attacked-malformed)
    attacked_targeted: bool   # reached target_decision
    malformed: bool
    confidence: float | None
    benign_malformed: bool = False
    benign_score: float | None = None
    expected_score: float | None = None
    skipped: bool = False     # primitive not in adapter's supported_primitives
```

One row per case. A case is ASR-eligible only if the benign variant was
correct and well-formed (`benign_correct and not benign_malformed`).
Skipped cases are never scored: they are excluded from every metric and
reported via the coverage keys in `summarize()`.

### `wilson_ci(hits, n, z=1.96) -> tuple[float, float]`

Wilson 95% confidence interval for a proportion. Returns `(0.0, 0.0)` for
`n == 0`.

### `asr_conditional(results) -> tuple[float, tuple[float, float]]`

Attack success rate among eligible attacked cases, with Wilson 95% CI.
Returns `(rate, (lo, hi))`.

### `benign_accuracy(results) -> tuple[float, tuple[float, float]]`

Fraction of benign variants answered correctly, with Wilson 95% CI.

### `malformed_rate(results) -> float`

Fraction of cases where either variant was malformed.

### `ece(probs, labels, bins=15) -> float`

Expected calibration error with equal-width bins. Bin 0 is closed on the
left so a probability of exactly 0.0 lands in a bin instead of being
dropped. Both lists must be non-empty and the same length.

```python
ece([0.9, 0.1, 0.8, 0.2], [1, 0, 1, 0])  # ~0.15, well-calibrated
```

### `brier_score(probs, labels) -> float`

Mean squared error between predicted probabilities and binary labels.
Lower is better; 0.25 is the "always predict 0.5" baseline.

### `mcnemar(b, c) -> float`

McNemar chi-square (no continuity correction) for `b` vs `c` discordant
pairs. Returns 0.0 when `b + c == 0`.

### `paired_bootstrap_ci(xs, ys, n_boot=10000, seed=0) -> tuple[float, float]`

Bootstrap 95% CI for `mean(xs) - mean(ys)` with paired resampling. Uses the
module-level `BOOTSTRAP_RESAMPLES` (10,000) and `BOOTSTRAP_ALPHA` (0.05)
defaults. Deterministic for a given seed.

Public API for downstream consumers (e.g. adapter-vs-adapter comparison
CIs). Not called by the single-run summarize path — family comparisons
use McNemar; run-vs-run bootstrap CIs are roadmap.

### `check_eligibility(results) -> Eligibility`

Applies the four ranking gates. Returns `Eligibility(eligible: bool,
reasons: tuple[str, ...])`. Empty reasons means eligible.

---

## peira.artifacts

`from peira.artifacts import RunArtifact, results_to_dicts`

The frozen record of one evaluation run.

### `RunArtifact`

```python
@dataclass
class RunArtifact:
    artifact_version: str = "1"
    peira_version: str = ...
    dataset_version: str = "0.1.0-demo"
    adapter_name: str = ""
    adapter_version: str = ""
    suite: str = ""
    created_utc: str = ...
    config: dict = ...
    results: list[dict] = ...
    metrics: dict = ...
    analysis_lock: str = ""
```

### `seal() -> RunArtifact`

Computes `analysis_lock` (sha256 over peira version, dataset version,
adapter name, adapter version, suite, config, results, and metrics, with
sorted keys) and returns `self`. Metrics and adapter version are
lock-covered: editing the headline numbers or the identified adapter
version after sealing invalidates the lock. Call once, after metrics are
attached. Artifacts sealed before metrics/adapter_version were lock-covered
(pre-2026-09-25) will fail `verify()` — re-run to re-seal.

### `verify() -> bool`

Recomputes the lock and compares. `True` = intact, `False` = tampered.
This is what `peira verify` checks.

### `to_json() / from_json(s)`

Serialize/deserialize. `to_json()` emits sorted keys with 2-space indent;
the lock is computed over a canonical payload, not over this rendering.

### `results_to_dicts(results) -> list[dict]`

Converts a list of `PerCaseResult` to plain dicts for the artifact.

---

## peira.cli

```
peira run [--adapter NAME] [--suite SUITE] [--out DIR] [--dry-run]
          [--json-progress] [--resume] [--timeout SECONDS]
peira validate --dataset DIR
peira report --run ARTIFACT [--out FILE]
peira verify --run ARTIFACT
```

Exit codes: 0 clean · 1 user error (bad config/adapter) · 2 infrastructure
failure · 3 run completed but not ranking-eligible (eligibility notes are
warnings, not failures; the artifact is still written and sealed).

### `peira run`

Runs a suite through an adapter. `--adapter` is `mock` or a dotted path
(`mymodule:MyAdapter` / `mymodule.MyAdapter`); the class is instantiated
with no arguments. `--suite` is `trial-demo` (12-case fixture) or `trial`
(`smoke` is an alias). `--dry-run` validates config without scoring.
`--resume` continues from the checkpoint in `--out` (the partial's
analysis lock is verified; tampered or mismatched partials are refused).
`--timeout` caps per-`decide()` seconds (default 30); timed-out variants
are marked malformed, never silently dropped.

### `peira validate`

Validates a dataset directory: every `.jsonl` line against the case
schema. Prints `file:line` and the rule for every invalid line.

### `peira report`

Renders an HTML report from a run artifact. `--run` is the artifact JSON,
`--out` the HTML file (default `report.html`). All artifact-derived fields
are HTML-escaped.

### `peira verify`

Checks a run artifact's analysis lock. Exit 0 = intact, 1 = tampered or
unreadable. The trust story behind "no post-hoc editing."
