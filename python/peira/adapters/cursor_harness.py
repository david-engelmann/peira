"""Cursor harness adapter: models measured through Cursor's agent CLI.

This adapter measures a model the way a Cursor user actually reaches
it: through Cursor's own agent (the ``agent`` CLI in headless print
mode, ``--mode ask``), with Cursor's system prompt, Cursor's model
configuration, and Cursor's serving choices in the loop. It is NOT a
bare-wire measurement of the underlying model, and it does not claim
to be one: the run's provenance names the harness, the model id is
Cursor's own variant label (``grok-4.7-high-fast``, not xAI's
``grok-4.7``), and the sampling record is ``provider-incapable``
because the harness exposes no temperature or seed control.

Why it exists: some models are reachable through a Cursor plan when
no direct provider route is available (no credits on the vendor
account, no direct API). A harness measurement, honestly labeled,
says something true and useful about the product surface users
actually touch. It must never be pooled silently with bare-wire
measurements of the same underlying model: the cache namespace, the
adapter name, and the model id all carry the harness identity.

Wire facts, verified live 2026-10-24 against the account's key:

- The CLI is Cursor's official ``agent`` binary (version
  2026.10.22-27dcf5f), installed from cursor.com. Print mode with
  ``--output-format json`` returns one JSON envelope: ``result``
  (the agent's final text), ``usage`` with ``inputTokens``,
  ``outputTokens`` and ``cacheReadTokens``, plus ``session_id`` and
  ``request_id``.
- One trivial prompt ("Reply with exactly one word: ready") used
  13,366 input tokens: the harness overhead is large, real, and
  recorded per call from the envelope, never estimated. A call
  whose usage object or primary counters cannot be read fails
  closed as a provider error rather than recording zeros.
- ``--mode ask`` keeps the agent read-only: it answers the prompt
  and cannot edit files or run tools against the workspace. The
  workspace is an empty directory created for the purpose.
  ``--trust`` is passed so the CLI runs non-interactively against
  that fresh directory instead of stopping on its workspace-trust
  prompt (which a headless subprocess cannot answer, so the call
  would hang until the timeout). It trusts the adapter's own
  empty directory only, and ask mode still bars edits and tools.

The prompt sent is the structured pipeline's own composed prompt,
the same case text the bare-wire structured adapters send, with one
transport difference: a text harness has no response_format channel,
so the decision schema the other wires carry out-of-band is rendered
into the prompt text itself (see ``_request``). The case text is
untouched. The agent's reply text goes through the same strict JSON
parse and schema validation as every structured adapter: prose
around the JSON, a refusal, or an agent error surface exactly as
they do on other wires (parse failure, refusal, provider error),
never as silent reinterpretation.

Sampling: ``_supports_temperature`` and ``_supports_seed`` are False.
The harness accepts neither parameter, so the sealed record says
``provider-incapable`` with temperature and seed meaningfully absent,
per the sampling contract (R-04). ``max_tokens`` is declared at the
structured pipeline's 512 for comparability; the harness cannot
enforce it, and the runner's per-call token accounting flags any
call whose reported output exceeds it, as on any wire.

Auth: the key is a Cursor User API key (cursor.com dashboard),
passed to the CLI only through the ``CURSOR_API_KEY`` environment
variable of the subprocess. It never appears in argv, in the
transcript, or in any file this adapter writes.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..api_pins import PINNED_API_MODELS
from .base import ProviderError
from .llm import _RawResult, _StructuredLLMBase

API_KEY_ENV = "CURSOR_API_KEY"

# The one pinned model this adapter was built and verified for. The
# label is Cursor's variant id, recorded verbatim: a measurement must
# name the exact surface that answered.
SUPPORTED_MODEL_IDS = frozenset({"grok-4.7-high-fast"})

_DEFAULT_TIMEOUT_S = 300.0


def _default_agent_bin() -> str:
    override = os.environ.get("CURSOR_AGENT_PATH", "")
    if override:
        return override
    return str(Path.home() / ".local" / "bin" / "agent")


# No real call processes anywhere near a trillion tokens. The bound
# exists so a corrupt counter is refused here, by exact integer
# comparison, instead of reaching a downstream float conversion,
# where a several-hundred-digit int raises OverflowError and escapes
# as an unclassified error (the sibling adapters' #494 lesson).
_MAX_USAGE_TOKENS = 10**12


def _usage_tokens(
    usage: dict[str, Any], field: str, *, required: bool = False,
) -> int:
    """One envelope usage field as a non-negative int.

    The envelope is raw subprocess JSON, unvalidated by any SDK, so
    a field can arrive as the wrong type or a negative number. Both
    are provider-side corruption: fail the call here with a
    ProviderError instead of letting a bad figure reach the sealed
    record, where the artifact contract would reject the whole run.

    A required field that is absent fails the same way: a missing
    counter is unknown usage, and recording an unknown as zero
    would fabricate a free call (the repo's unavailable-rather-
    than-zero rule). Optional fields are the ones the live-verified
    envelope does not always carry.
    """
    value = usage.get(field)
    if value is None:
        if required:
            raise ProviderError(
                f"cursor-agent usage field {field} is missing")
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(
            f"cursor-agent usage field {field} is not a number: "
            f"{value!r}")
    if isinstance(value, float):
        if not value.is_integer():
            raise ProviderError(
                f"cursor-agent usage field {field} is not a whole "
                f"number: {value!r}")
        value = int(value)
    if value < 0:
        raise ProviderError(
            f"cursor-agent usage field {field} is negative: {value}")
    if value > _MAX_USAGE_TOKENS:
        raise ProviderError(
            f"cursor-agent usage field {field} is implausibly "
            f"large: {value}")
    return value


# Error text from the harness that means throttling. Phrase-matched:
# a bare "rate" or "limit" substring also fires on "generated",
# "accurate" and "separate", misclassifying ordinary agent errors
# as 429s the runner would retry as throttling.
_RATE_LIMIT_PHRASES = (
    "rate limit", "rate_limit", "too many requests", "quota",
)


class CursorHarnessAdapter(_StructuredLLMBase):
    """A model measured through Cursor's agent harness (CLI ask mode).

    See the module docstring for what this measurement is and is not.
    The structured pipeline (prompt composition, JSON parse, schema
    validation, outputs) is inherited unchanged; only the transport
    differs: one ``agent`` subprocess per call.
    """

    name = "cursor-harness"
    _extra = "Cursor agent CLI"
    _env_vars = (API_KEY_ENV,)
    _provider_label = "Cursor"
    _supports_seed = False
    _supports_temperature = False

    def __init__(
        self,
        model: str = PINNED_API_MODELS["cursor-harness"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        agent_bin: str | None = None,
        workspace: str | None = None,
        runner_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if model not in SUPPORTED_MODEL_IDS:
            pins = " or ".join(repr(m) for m in sorted(SUPPORTED_MODEL_IDS))
            raise ValueError(
                f"cursor-harness adapter pins model {pins}; "
                f"got {model!r}. A measurement must name the exact "
                "Cursor variant label that answered."
            )
        # Temperature and seed are accepted for constructor-shape
        # compatibility with the structured pipeline and are NOT
        # sent anywhere: the class flags declare the harness
        # incapable of both, so the sealed sampling record reports
        # them as meaningfully absent (provider-incapable).
        # The base resolves the API key (explicit argument, else the
        # CURSOR_API_KEY environment variable), stores it on
        # self._api_key, and raises when none is available. There is
        # deliberately no second resolution here.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self.timeout_s = timeout_s
        self._agent_bin = agent_bin or _default_agent_bin()
        if workspace is None:
            # A fresh, private directory per adapter instance: ask
            # mode only needs an empty workspace to run against, and
            # a shared predictable path would couple instances.
            workspace = tempfile.mkdtemp(
                prefix="peira-cursor-harness-ws-")
        self._workspace = workspace
        # Injectable transport for tests: fn(prompt) -> parsed envelope.
        self._runner_fn = runner_fn or self._subprocess_runner

    # -- transport ------------------------------------------------------

    def _subprocess_runner(self, prompt: str) -> dict[str, Any]:
        env = dict(os.environ)
        env[API_KEY_ENV] = self._api_key
        cmd = [
            self._agent_bin,
            "-p", prompt,
            "--model", self._model,
            "--mode", "ask",
            "--output-format", "json",
            "--trust",
            "--workspace", self._workspace,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout_s, env=env,
            )
        except FileNotFoundError as exc:
            raise ProviderError(
                f"cursor-agent binary not found at {self._agent_bin}: "
                "install the Cursor CLI from cursor.com"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"cursor-agent call timed out after {self.timeout_s}s",
                status_code=408,
            ) from exc
        except OSError as exc:
            # Any other launch failure (a non-executable binary, an
            # argument list the OS rejects) is a harness failure like
            # the ones above, not a bare OSError escaping the
            # adapter's error contract. FileNotFoundError is an
            # OSError subclass and keeps its own message above.
            raise ProviderError(
                f"cursor-agent could not be started: {exc}"
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise ProviderError(
                f"cursor-agent exited {proc.returncode}: {detail}",
                status_code=502,
            )
        try:
            envelope = json.loads(proc.stdout)
        except ValueError as exc:
            # JSONDecodeError is the ordinary malformed-output case.
            # The wider ValueError catch also covers the plain
            # ValueError json raises for an integer literal past the
            # interpreter's conversion limit: an oversized counter in
            # the envelope is malformed output too, and must fail
            # closed here rather than escape as a bare ValueError.
            raise ProviderError(
                "cursor-agent returned non-JSON output on stdout"
            ) from exc
        if not isinstance(envelope, dict):
            raise ProviderError("cursor-agent envelope is not an object")
        return envelope

    # -- structured pipeline hook ----------------------------------------

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool,
        prior_text: str | None = None,
    ) -> _RawResult:
        # The CLI has no schema channel: on the bare wires the output
        # contract travels in response_format or a tool definition,
        # so here it is rendered into the prompt text itself, from
        # the same per-call schema the pipeline built. The case text
        # is untouched; only the contract every wire conveys is made
        # explicit in words.
        prompt = (
            user_text
            + "\n\nRespond with a single JSON object matching this "
              "schema, and nothing else:\n"
            + json.dumps(schema)
        )
        if repair:
            prompt += "\nReturn ONLY the JSON object."
        envelope = self._runner_fn(prompt)
        if not isinstance(envelope, dict):
            raise ProviderError("cursor-agent envelope is not an object")
        if envelope.get("is_error"):
            result_text = str(envelope.get("result") or "")
            lowered = result_text.lower()
            status = 429 if any(
                phrase in lowered for phrase in _RATE_LIMIT_PHRASES
            ) else 502
            raise ProviderError(
                f"cursor-agent reported an error: {result_text[:300]}",
                status_code=status,
            )
        usage = envelope.get("usage")
        if not isinstance(usage, dict):
            # Usage accounting fails closed, as on the sibling
            # decision wires: a call whose counters cannot be read
            # cannot be recorded, and defaulting them to zero would
            # seal fabricated usage into the run.
            raise ProviderError(
                "cursor-agent envelope carries no usage object")
        text = envelope.get("result")
        if not isinstance(text, str):
            raise ProviderError(
                "cursor-agent envelope carries no text result")
        # The live-verified envelope always carries these three;
        # cacheWriteTokens is the one field it does not promise, so
        # that one alone may be absent and read as zero.
        fresh_in = _usage_tokens(usage, "inputTokens", required=True)
        cache_read = _usage_tokens(
            usage, "cacheReadTokens", required=True)
        cache_write = _usage_tokens(usage, "cacheWriteTokens")
        return _RawResult(
            text=text,
            stop_reason=str(envelope.get("subtype") or "success"),
            parsed=None,
            # Cursor reports its input components disjointly: one
            # canary call came back with 35,072 cache-read tokens
            # against 5,167 input tokens, which no subset reading
            # survives. tokens_in therefore records the TOTAL input
            # processed (fresh + cache read + cache write), the same
            # convention as the OpenAI wire, with the cache-read part
            # kept in cached_tokens_in where it is a true subset.
            # Every component is validated non-negative by
            # _usage_tokens, so the subset relation holds by
            # construction.
            tokens_in=fresh_in + cache_read + cache_write,
            tokens_out=_usage_tokens(
                usage, "outputTokens", required=True),
            logprob_tokens=None,
            request_shape={
                "endpoint": "cursor-agent-cli",
                "mode": "ask",
                "model": self._model,
                "harness": "Cursor agent CLI, headless print mode",
            },
            response_shape={
                "session_id": envelope.get("session_id"),
                "request_id": envelope.get("request_id"),
                "duration_api_ms": envelope.get("duration_api_ms"),
            },
            cached_tokens_in=cache_read or None,
        )
