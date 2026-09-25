"""SemIf adapter (TheoLeeCJ, MIT).

SemIf (formerly OpenJev — renamed ~2026-09-18; the CLI was renamed
from ``openjev-score`` to ``semif-score`` at the same time) reads
typed option probabilities directly from a frozen open model in one
forward pass: no answer sentence, no JSON repair, no decoding loop. It
is the most-starred Jev-pattern open project (~4.3k stars, MIT).

Interface: this is a **subprocess adapter**. Each ``decide()`` call
builds SemIf input rows, spawns the ``semif-score`` CLI in
``--mode direct`` (batch JSONL in → JSONL out), and maps the returned
option probabilities to peira outputs. The model loads inside the CLI
process, so per-call spawning is expensive — a cold start reloads the
4B weights every call; the adapter is correct but slow, and a future
batch mode could amortize it. ``timeout_s`` defaults to 600s to
accommodate cold loads.

CLI contract (per SemIf's published README/docs, 2026-09-22+):

- ``semif-score --mode direct --model Qwen/Qwen3.5-4B
  --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
  --input rows.jsonl --output results.jsonl``
- Input rows: ``{"id", "state", "question",
  "options": [{"id", "description"}]}``.
- Output rows: "typed option scores, timing, the exact model
  revision, and a prompt hash" per row.

The exact output-row JSON keys are UNVERIFIED (not documented in the
public pages and never exercised live): the parser below accepts a
small set of candidate key shapes and raises a terminal
``ProviderError`` when no recognizable option-probability shape is
found. If SemIf's real output keys differ, this module is the one
place to update.

Model pin: ``Qwen/Qwen3.5-4B`` @ revision
``851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`` (the full revision whose
``851bf6e8`` prefix the landscape report pinned; the same id appears
in every published SemIf scoring command). Both are validated at
construction — floating revisions are rejected.

Lazy binary: ``shutil.which`` is checked at construction only when
the default runner is used (an injected ``runner=`` skips the check,
so tests never need the CLI). A missing binary raises an actionable
error saying how to install SemIf; a pre-rename install exposing
``openjev-score`` is picked up automatically.

NOTE — abstain boundary mapping: SemIf's CLI has no ``"noul"`` wire
type — unlike Jev/Kev/Laya, there is no separate abstain question
type to translate at the boundary. Peira's ``abstain`` primitive is
expressed as an ordinary yes/no question ("Should this case be
abstained?") with ``"yes"``/``"no"`` options, and the ``"yes"``
probability is read back as the abstain signal with the same
>= 0.5 threshold the Jev-family adapters use.

NOTE — score mapping: the score primitive is a 5-level rubric
question (worst → best), mirroring ``JevAdapter``'s rubric; the score
is the probability-weighted rubric position normalized to 0..1, and a
paired decision row carries the label (like Jev's paired choice
question).

Verified vs unverified (2026-09-25): the CLI name, flags, input-row
shape, model id, and revision are verified against SemIf's published
README/REPRODUCE docs. The output-row key shapes, token accounting
(the docs mention timing but not token counts), and the exact argv
behavior are UNVERIFIED — this adapter has NOT been exercised against
a real ``semif-score`` install.

Retry layering: the adapter performs exactly one CLI spawn per call
and never retries. Every CLI failure (missing binary, timeout,
nonzero exit, unparseable output, unrecognized shapes) is raised as a
terminal ``ProviderError`` with no ``status_code`` — the runner treats
that as permanent and records the variant malformed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable

from peira.adapters._labels import (
    candidate_labels,
    non_abstain_placeholder,
)
from peira.adapters.base import (
    AdapterOutput,
    CallContext,
    CallUsage,
    ChoiceOutput,
    AbstainOutput,
    ProviderError,
    ScoreOutput,
)

MODEL_ID = "Qwen/Qwen3.5-4B"
"""Pinned model id."""

MODEL_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
"""Pinned full revision (the 851bf6e8 prefix from the landscape report)."""

CLI_BINARY = "semif-score"
"""Current CLI name (post-rename)."""

LEGACY_BINARY = "openjev-score"
"""Pre-rename CLI name; picked up automatically if semif-score is absent."""

VERSION = f"{MODEL_ID}@{MODEL_REVISION}"
"""Exact pinned version — never an alias."""

INSTALL_HINT = (
    "the semif adapter needs the `semif-score` CLI on PATH: clone "
    "https://github.com/theoleecj/semif, create the venv, and run "
    "`pip install -e '.[test]'` (per SemIf's README), then retry. "
    "A pre-rename install exposing `openjev-score` is picked up "
    "automatically; otherwise pass binary= with the CLI's path."
)

# UNVERIFIED output-shape candidates (see module docstring): the
# published docs only promise "typed option scores, timing, the exact
# model revision, and a prompt hash" per row. The parser tries these
# keys in order and takes the first that yields a usable mapping.
_PROBABILITY_KEYS = (
    "probabilities",
    "option_probabilities",
    "option_scores",
    "scores",
    "scores_by_option",
    "option_logprobs",
)
_PROBABILITY_SUBKEYS = ("probability", "prob", "score", "p")
_REVISION_KEYS = ("model_revision", "revision")

_SCORE_LEVELS = [
    "clearly the wrong decision",
    "probably the wrong decision",
    "uncertain — could go either way",
    "probably the right decision",
    "clearly the right decision",
]
"""Ordered score rubric, worst to best — mirrors JevAdapter's rubric so
the 0..1 normalization is comparable across the Jev-family adapters."""


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order.

    Built from the case input's explicit ``options`` list (B2: the
    adapter-visible context carries no gold labels), plus ``"other"``.
    Shared with jev/laya via ``peira.adapters._labels``.
    """
    return candidate_labels(case_input, "choice")


def _choice_row(row_id: str, prompt: str, labels: list[str]) -> dict[str, Any]:
    return {
        "id": row_id,
        "state": prompt,
        "question": (
            "Given the decision context above, which option is the "
            "correct decision? Choose exactly one."
        ),
        "options": [
            {
                "id": label,
                "description": (
                    "None of the listed options is the correct decision."
                    if label == "other"
                    else f"Decide {label!r} for this case."
                ),
            }
            for label in labels
        ],
    }


def _score_row(prompt: str) -> dict[str, Any]:
    return {
        "id": "score",
        "state": prompt,
        "question": (
            "Rate the quality of the correct decision for this case on "
            "the ordered scale below, from the worst to the best level."
        ),
        "options": [
            {"id": f"level-{i}", "description": desc}
            for i, desc in enumerate(_SCORE_LEVELS)
        ],
    }


def _abstain_row(prompt: str) -> dict[str, Any]:
    # NOTE: SemIf has no "noul" wire type — peira's "abstain"
    # primitive is an ordinary yes/no question (see module docstring).
    return {
        "id": "abstain",
        "state": prompt,
        "question": (
            "Should this case be abstained — is there no confident "
            "correct decision?"
        ),
        "options": [
            {"id": "yes",
             "description": "There is no confident correct decision; abstain."},
            {"id": "no",
             "description": "There is a confident correct decision; do not abstain."},
        ],
    }


def _resolve_binary(binary: str | None) -> str:
    """Locate the SemIf CLI, with the pre-rename fallback.

    Returns the binary name/path to invoke. Raises an actionable error
    when neither ``semif-score`` nor ``openjev-score`` is on PATH.
    """
    if binary is not None:
        found = shutil.which(binary)
        if found is None:
            raise FileNotFoundError(
                f"semif adapter: CLI binary {binary!r} not found on PATH. "
                + INSTALL_HINT
            )
        return binary
    found = shutil.which(CLI_BINARY)
    if found is not None:
        return CLI_BINARY
    if shutil.which(LEGACY_BINARY) is not None:
        # Pre-rename install (SemIf was OpenJev before ~2026-09-18).
        return LEGACY_BINARY
    raise FileNotFoundError(
        "semif adapter: neither `semif-score` nor the pre-rename "
        f"`{LEGACY_BINARY}` was found on PATH. " + INSTALL_HINT
    )


def _default_runner(
    input_rows: list[dict[str, Any]], argv: list[str], timeout_s: float
) -> list[dict[str, Any]]:
    """Spawn the CLI once: JSONL in → JSONL out.

    Writes the rows to a temp input file, appends ``--input`` /
    ``--output``, runs with the given timeout, and parses the output
    file back into rows. Every failure mode is a terminal
    ``ProviderError`` with no ``status_code`` (the runner treats that
    as permanent — a broken CLI is a setup problem, not congestion).
    """
    binary = argv[0]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="peira-semif-") as tmp:
        in_path = os.path.join(tmp, "input.jsonl")
        out_path = os.path.join(tmp, "output.jsonl")
        with open(in_path, "w", encoding="utf-8") as f:
            for row in input_rows:
                f.write(json.dumps(row) + "\n")
        cmd = [binary, *argv[1:], "--input", in_path, "--output", out_path]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_s
            )
        except FileNotFoundError as e:
            raise ProviderError(
                f"semif CLI binary {binary!r} disappeared from PATH. "
                + INSTALL_HINT
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ProviderError(
                f"semif CLI timed out after {timeout_s}s "
                f"(model load is slow on a cold start): {e}"
            ) from e
        except OSError as e:
            raise ProviderError(f"semif CLI failed to spawn: {e}") from e
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()[-2000:]
            raise ProviderError(
                f"semif CLI exited with status {proc.returncode}"
                + (f": {stderr}" if stderr else "")
            )
        try:
            with open(out_path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError as e:
            raise ProviderError(
                "semif CLI exited 0 but wrote no output file — the "
                "install may be broken or the output shape changed."
            ) from e
        except (json.JSONDecodeError, OSError) as e:
            raise ProviderError(
                f"semif CLI output was not parseable JSONL: {e}"
            ) from e
    latency_ms = (time.perf_counter() - started) * 1000.0
    for row in rows:
        if isinstance(row, dict):
            row.setdefault("_latency_ms", latency_ms)
    return rows


def _option_probabilities(
    row: dict[str, Any], option_ids: list[str]
) -> dict[str, float]:
    """Extract option_id → probability from an UNVERIFIED result row.

    Tries the candidate key shapes in ``_PROBABILITY_KEYS`` order;
    accepts a dict, a list of {id, probability/score} objects, or a
    bare list parallel to the input option order. Raises a terminal
    ``ProviderError`` when nothing recognizable is found.
    """
    for key in _PROBABILITY_KEYS:
        if key not in row:
            continue
        value = row[key]
        probs: dict[str, float] = {}
        try:
            if isinstance(value, dict):
                items = value.items()
            elif isinstance(value, list) and all(
                isinstance(v, dict) for v in value
            ):
                def _oid(v: dict[str, Any]) -> Any:
                    return v.get("id", v.get("option_id", v.get("option")))
                def _oprob(v: dict[str, Any]) -> Any:
                    for sk in _PROBABILITY_SUBKEYS:
                        if sk in v:
                            return v[sk]
                    return None
                items = [(_oid(v), _oprob(v)) for v in value]
            elif isinstance(value, list) and all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                for v in value
            ):
                items = list(zip(option_ids, value))
            else:
                continue
            for oid, p in items:
                if not isinstance(oid, str) or isinstance(p, bool) \
                        or not isinstance(p, (int, float)):
                    raise ValueError("bad option probability entry")
                probs[oid] = float(p)
        except (ValueError, TypeError):
            continue
        if probs:
            return probs
    raise ProviderError(
        "semif result row has no recognizable option-probability field "
        f"(tried {_PROBABILITY_KEYS}); row keys: "
        f"{sorted(row)} — the CLI's output shape may have changed."
    )


def _check_revision(row: dict[str, Any]) -> str | None:
    """Return a transcript note when the row's revision differs, else None."""
    for key in _REVISION_KEYS:
        rev = row.get(key)
        if isinstance(rev, str) and rev:
            # Short and full revision ids match in either direction.
            if (rev == MODEL_REVISION
                    or MODEL_REVISION.startswith(rev)
                    or rev.startswith(MODEL_REVISION)):
                return None
            return (
                f"row reported revision {rev!r}, adapter pinned "
                f"{MODEL_REVISION!r}"
            )
    return None


RunnerFn = Callable[
    [list[dict[str, Any]], list[str], float], list[dict[str, Any]]
]
"""Test seam: ``runner(input_rows, argv, timeout_s) -> result rows``.

Inject a fake in tests so no subprocess is ever spawned; the fake
receives the exact rows and argv the adapter would hand to the CLI."""


class SemifAdapter:
    """Decision adapter for TheoLeeCJ's SemIf CLI (subprocess)."""

    name = "semif"
    version = VERSION
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # Pinned model + revision: same input → same decision, so the
    # runner's opt-in response cache is safe namespaced on both.
    cache_namespace = f"semif:{MODEL_ID}@{MODEL_REVISION}"

    @classmethod
    def doctor_requirements(cls) -> list[dict]:
        """What `peira doctor` checks for this adapter."""
        return [
            {"kind": "binary", "name": "semif-score",
             "alternatives": ["openjev-score"],
             "detail": "neither semif-score nor openjev-score on PATH",
             "hint": "clone github.com/theoleecj/semif, create the venv, "
                     "and run `pip install -e '.[test]'` per its README"},
            {"kind": "ram_gb", "min": 3.0,
             "detail": "SemIf CPU inference needs ~3GB RAM",
             "hint": "free up RAM or use a bigger machine"},
        ]

    def __init__(
        self,
        model: str | None = None,
        revision: str = MODEL_REVISION,
        binary: str | None = None,
        timeout_s: float = 600.0,
        extra_args: list[str] | None = None,
        runner: RunnerFn | None = None,
    ) -> None:
        # None resolves to the pinned model, matching the sibling
        # adapters' convention (Kev, openjev-sglang).
        resolved_model = MODEL_ID if model is None else model
        if resolved_model != MODEL_ID:
            raise ValueError(
                f"semif adapter pins model {MODEL_ID!r}; got {model!r}. "
                "Floating model ids are never allowed — a measurement "
                "must name the exact model."
            )
        if revision != MODEL_REVISION:
            raise ValueError(
                f"semif adapter pins revision {MODEL_REVISION!r}; got "
                f"{revision!r}. Floating revisions are never allowed."
            )
        for arg in extra_args or []:
            if arg in ("--input", "--output") or arg.startswith(
                ("--input=", "--output=")
            ):
                raise ValueError(
                    "semif adapter reserves --input/--output for its own "
                    f"temp files; got {arg!r} in extra_args."
                )
        self.model = resolved_model
        self.revision = revision
        self.timeout_s = timeout_s
        self.extra_args = list(extra_args or [])
        if runner is not None:
            # Test seam (mirrors JevAdapter's injectable transport):
            # no binary needed, nothing is spawned.
            self.binary = binary or CLI_BINARY
            self._runner = runner
        else:
            self.binary = _resolve_binary(binary)
            self._runner = _default_runner

    def _argv(self) -> list[str]:
        # --mode direct: one state, one forward pass per row. serial /
        # shared are batch optimizations that don't apply to per-call
        # decide(); the adapter is correct but slow on cold starts.
        return [
            self.binary,
            "--mode", "direct",
            "--model", self.model,
            "--revision", self.revision,
            *self.extra_args,
        ]

    # -- decide -----------------------------------------------------------

    def decide(
        self,
        case_input: dict[str, Any],
        primitive: str,
        context: CallContext,
    ) -> AdapterOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(f"semif does not support primitive {primitive!r}")
        prompt = str(case_input.get("prompt", ""))
        labels = _labels(case_input)

        if primitive == "choice":
            rows = [_choice_row("decision", prompt, labels)]
        elif primitive == "score":
            # The score row carries the measurement signal (a rubric
            # level); the paired decision row carries the label, like
            # JevAdapter's two-question score shape.
            rows = [_score_row(prompt), _choice_row("decision", prompt, labels)]
        else:  # abstain
            rows = [_abstain_row(prompt)]

        started = time.perf_counter()
        try:
            results = self._runner(rows, self._argv(), self.timeout_s)
        except ProviderError:
            raise
        except Exception as e:
            # A custom runner blew up in an unexpected way: terminal,
            # no status code — never retried.
            raise ProviderError(f"semif runner failed: {e}") from e
        wall_latency_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(results, list):
            raise ProviderError(
                "semif runner returned a non-list result: "
                f"{type(results).__name__}"
            )
        by_id: dict[str, dict[str, Any]] = {}
        for r in results:
            if not isinstance(r, dict):
                raise ProviderError(
                    "semif result row is not an object: "
                    f"{type(r).__name__}"
                )
            rid = r.get("id")
            if not isinstance(rid, str) or rid in by_id:
                raise ProviderError(
                    f"semif result row has a bad/duplicate id: {rid!r}"
                )
            by_id[rid] = r
        missing = [row["id"] for row in rows if row["id"] not in by_id]
        if missing:
            raise ProviderError(
                f"semif output is missing result rows for: {missing}"
            )

        revision_note: str | None = None
        for row in rows:
            note = _check_revision(by_id[row["id"]])
            if note is not None:
                revision_note = note
        usage = CallUsage(
            model=MODEL_ID,  # exact pricing-table key; the pinned
            # revision stays in transcript/version/cache namespace
            tokens_in=0,  # the CLI's documented output fields carry
            tokens_out=0,  # timing, not token counts (unverified)
            latency_ms=wall_latency_ms,
            cost_usd=0.0,  # self-hosted; the runner's pricing table rules
        )
        transcript: dict[str, Any] = {
            "model": self.model,
            "revision": self.revision,
            "binary": self.binary,
            "argv": [a for a in self._argv()[1:]],  # flags only, no binary
            "row_ids": [row["id"] for row in rows],
        }
        if revision_note is not None:
            transcript["revision_note"] = revision_note

        if primitive == "choice":
            return self._choice_output(by_id["decision"], labels, usage,
                                       transcript)
        if primitive == "score":
            return self._score_output(by_id["score"], by_id["decision"],
                                      labels, usage, transcript)
        return self._abstain_output(by_id["abstain"], usage,
                                    transcript)

    # -- per-primitive mapping --------------------------------------------

    def _choice_output(self, result, labels, usage, transcript):
        # The option ids we sent are exactly the labels offered.
        probs = _option_probabilities(result, labels)
        winner = max(probs, key=lambda oid: probs[oid])
        if winner not in labels:
            raise ProviderError(
                f"semif returned winning option {winner!r} outside the "
                f"offered labels {labels} — adapter bug or CLI drift."
            )
        confidence = _clamp01(probs[winner], "choice probability")
        return ChoiceOutput(
            decision=winner, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _score_output(self, score_result, decision_result, labels, usage,
                      transcript):
        option_ids = [f"level-{i}" for i in range(len(_SCORE_LEVELS))]
        probs = _option_probabilities(score_result, option_ids)
        # Renormalize defensively: typed option scores should sum to 1,
        # but never trust an unverified CLI shape to do so.
        total = sum(probs.get(f"level-{i}", 0.0) for i in range(len(_SCORE_LEVELS)))
        if total <= 0:
            raise ProviderError(
                f"semif score row has non-positive total probability: {probs}"
            )
        level = sum(
            i * probs.get(f"level-{i}", 0.0) / total
            for i in range(len(_SCORE_LEVELS))
        )
        score = _clamp01(level / (len(_SCORE_LEVELS) - 1), "score")
        # The paired decision row carries the label; its option ids
        # are exactly the labels offered.
        dec_probs = _option_probabilities(decision_result, labels)
        option = max(dec_probs, key=lambda oid: dec_probs[oid])
        if option not in labels:
            raise ProviderError(
                f"semif returned choice {option!r} outside the offered "
                f"labels {labels} — adapter bug or CLI drift."
            )
        confidence = _clamp01(dec_probs[option], "choice probability")
        return ScoreOutput(
            score=score, decision=option, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _abstain_output(self, result, usage, transcript):
        probs = _option_probabilities(result, ["yes", "no"])
        if "yes" not in probs:
            raise ProviderError(
                f"semif abstain row has no 'yes' option probability: "
                f"{sorted(probs)}"
            )
        p_yes = _clamp01(probs["yes"], "abstain probability")
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        if p_yes >= 0.5:
            decision = "abstain"
        else:
            # No abstention: the model emitted no decision label, so the
            # placeholder is "other" — never gold (B2: unreachable here).
            decision = non_abstain_placeholder()
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )


def _clamp01(value: Any, name: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"semif returned non-numeric {name}: {value!r}") from None
    return max(0.0, min(1.0, f))
