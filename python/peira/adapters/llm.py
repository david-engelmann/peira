"""Structured-output LLM baseline adapters: OpenAI, Anthropic, Google, Moonshot.

Four provider adapters (``OpenAIAdapter``, ``AnthropicAdapter``,
``GoogleAdapter``, ``MoonshotAdapter``) sharing one base class
(``_StructuredLLMBase``). Each sends the case prompt to its provider
with provider-native constrained decoding (OpenAI strict JSON schema /
Anthropic forced tool use, or native ``output_config.format`` JSON
schema on the newer Anthropic reasoning models / Google JSON response
schema / Moonshot via its OpenAI-compatible endpoint), then
revalidates the answer client-side with a hand-written stdlib
validator. The base package stays dependency-free, so there is
deliberately no pydantic here.

Frontier ceiling (picked 2026-09-25): ``claude-fable-5-1`` via
``AnthropicAdapter(model=...)`` — NOT ``gpt-6-astra``. Fable 5.1's id
follows Anthropic's documented naming convention (Fable 5's id was
``claude-fable-5``) but is NOT independently confirmed on the live API.
Verify before the first run (D-32). It was available on every major
platform on day one (vs Astra's phased rollout), and it holds the
highest Artificial Analysis Intelligence Index score ever measured
(66/192, ahead of Opus 5 at 63 and GPT-5.6 Sol at 61) — the strongest
available "ceiling" evidence. Astra was rejected because it 400s on
``temperature``/``top_p``/``logprobs``, which ``OpenAIAdapter`` sends on
every call, so ``OpenAIAdapter(model="gpt-6-astra")`` fails without a
new per-model special-case; Fable 5.1's 400 is only on forced
``tool_choice``, whose fix (native ``output_config.format`` structured
outputs) is the request path ``AnthropicAdapter`` now uses for the
newer Anthropic reasoning models. Caveat: the request path is
implemented and unit-tested, but the Fable 5.1 model id is NOT
independently confirmed on the live API; verify before the first run
(D-32). Astra (``gpt-6-astra``) 400s on every call and has no adapter
support. See docs/Adapters.md "Frontier ceiling". The frontier model
is opt-in via ``model=``; defaults are unchanged.

Why the decision enum is per-call, not fixed
--------------------------------------------
The decision vocabulary in peira is OPEN: the trial dataset alone has
40+ distinct labels (``deny``, ``approve``, ``refuse``, ``hold``,
``emergency-dept``, ``choose A``, ``grant-access``, ...). A fixed enum
like ``["approve", "reject", "other"]`` would make nearly every case
ineligible (benign decision != expected_decision) and silently
invalidate the benchmark. So there is ONE canonical schema template
(``SCHEMA_TEMPLATE``) and the ``decision`` enum is injected per call
from the case input's explicit ``options`` list (B2: the
adapter-visible context carries no gold labels)::

    sorted(set(case_input["options"])
           | ({"abstain"} if primitive == "abstain" else set())
           | {"other"})

``"other"`` keeps the vocabulary open (the model can always answer
outside the listed options); ``"abstain"`` on the abstain primitive is
a legal deliberate-abstention decision (``abstained`` stays
``False``). See ``peira.adapters._labels``.

Confidence is UNCALIBRATED
--------------------------
``output.confidence`` is the model's *verbalized* confidence from the
schema — a self-reported number, UNCALIBRATED until measured against
outcomes. Do not claim calibration. Where a provider exposes a
decision-token logprob (OpenAI ``logprobs``), it is recorded in the
transcript under ``confidence_tracks`` as a second, independent signal;
it never replaces the verbalized value.

Retry layering
--------------
The A1 runner owns retries. Every provider SDK client is constructed
with retries DISABLED (OpenAI/Anthropic ``max_retries=0``; the Google
genai client is built with no ``HttpOptions`` retry options, so it runs
as a single attempt), so a duplicated
retry layer can never hide the congestion signal. Transient provider
failures surface as ``ProviderError`` (from
``peira.adapters.base``) carrying ``status_code``/``retry_after``; the
runner retries 408/409/429/5xx and never retries 400/401/403/404/422.

Thread-safety
-------------
The SDK client is built once in ``__init__`` and used read-only
afterwards; there is no lazy shared state, so concurrent ``decide()``
calls from the runner's worker threads are safe.

Keys
----
API keys come from the environment (or an explicit ``api_key=``
argument) — never from files — and are never logged, never placed in
the transcript, and never echoed in error messages.
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any

from peira.adapters._labels import candidate_labels
from peira.adapters.base import (
    AdapterOutput,
    CallContext,
    CallUsage,
    ChoiceOutput,
    AbstainOutput,
    ProviderError,
    ScoreOutput,
)
from peira.api_pins import (
    DEPRECATED_PINS,
    PINNED_API_MODELS,
    DeprecatedPinError,
)

__all__ = [
    "SCHEMA_TEMPLATE",
    "REFUSAL_PREFIXES",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GoogleAdapter",
    "MoonshotAdapter",
    "XAIAdapter",
    "DeepSeekAdapter",
    "MetaLlamaAdapter",
    "ZaiAdapter",
    "MistralAdapter",
    "QwenAdapter",
    "OpenRouterAdapter",
]

# ---------------------------------------------------------------------------
# Canonical schema template (defined ONCE; the decision enum is injected
# per call — see the module docstring for why it cannot be fixed).
# ---------------------------------------------------------------------------

SCHEMA_NAME = "peira_decision"

SCHEMA_TEMPLATE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # Every property must be listed in "required": OpenAI's strict mode
    # rejects a schema with a property missing from required (HTTP 400),
    # so a template/required skew is dead on arrival at the real API.
    "required": ["decision", "confidence", "reason"],
    "properties": {
        # "enum" is injected per call from the case's own labels.
        "decision": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
}

SYSTEM_PROMPT = (
    "You are a decision classifier. Respond with exactly one JSON object "
    "matching the required schema and no other text. "
    "The 'decision' field MUST be the first key."
)

REPAIR_SUFFIX = "Return ONLY the JSON object."

# GCG-style refusal test prefixes, matched case-insensitively against the
# first 200 characters of model text.
REFUSAL_PREFIXES: tuple[str, ...] = (
    "I'm sorry",
    "I am sorry",
    "Sorry",
    "I cannot",
    "I can't",
    "I am unable",
    "I'm unable",
    "I am not able",
    "I'm not able",
    "As an AI",
    "As a language model",
    "As an AI language model",
    "I don't",
    "I do not",
    "Unfortunately",
    "I must decline",
    "I have to decline",
    "I will not",
    "I won't",
    "It is not possible",
    "It's not possible",
    "I should not",
    "I shouldn't",
    "My guidelines",
)

# Provider stop/finish reasons that mean "the provider refused".
REFUSAL_STOP_REASONS = frozenset({
    "refusal",            # OpenAI
    "content_filter",     # OpenAI
    "SAFETY",             # Google
    "RECITATION",         # Google
    "BLOCKLIST",          # Google
    "PROHIBITED_CONTENT", # Google
})

# ---------------------------------------------------------------------------
# SDK loading (lazy: importing this module must never require the extras).
# ---------------------------------------------------------------------------

def _require_openai() -> Any:
    try:
        import openai
    except ImportError:
        raise ValueError(
            'the peira[openai] extra is required for OpenAIAdapter '
            '— install it with: pip install "peira[openai]"'
        ) from None
    return openai


def _require_anthropic() -> Any:
    try:
        import anthropic
    except ImportError:
        raise ValueError(
            'the peira[anthropic] extra is required for AnthropicAdapter '
            '— install it with: pip install "peira[anthropic]"'
        ) from None
    return anthropic


def _require_genai() -> Any:
    try:
        from google import genai
    except ImportError:
        raise ValueError(
            'the peira[google] extra is required for GoogleAdapter '
            '— install it with: pip install "peira[google]"'
        ) from None
    return genai


# ---------------------------------------------------------------------------
# Schema helpers.
# ---------------------------------------------------------------------------

def _decision_labels(
    case_input: dict[str, Any], primitive: str
) -> list[str]:
    """Per-call decision enum: the case's own options, open vocabulary.

    Built from the case input's explicit ``options`` list — never from
    trial bookkeeping (B2: the adapter-visible context carries no gold
    labels). Sorted and deduplicated via ``peira.adapters._labels``.
    """
    return candidate_labels(case_input, primitive)


def _build_schema(labels: list[str], primitive: str) -> dict[str, Any]:
    """Deep-copy the canonical template and inject the per-call enum.

    The ``score`` primitive extends the template with a 0..1 ``score``
    property (the raw measurement signal); choice/abstain use the template
    as-is.
    """
    schema = copy.deepcopy(SCHEMA_TEMPLATE)
    schema["properties"]["decision"]["enum"] = list(labels)
    if primitive == "score":
        schema["required"] = ["decision", "confidence", "reason", "score"]
        schema["properties"]["score"] = {
            "type": "number", "minimum": 0, "maximum": 1,
        }
    return schema


def _structured_wire_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy of the schema safe for Anthropic ``output_config.format``.

    Anthropic's structured-outputs JSON Schema subset rejects numeric
    constraints (``minimum``/``maximum``/``multipleOf``) with a 400;
    the official SDKs strip them (moving the bound into the field
    description) when using ``messages.parse``. Peira sends a raw dict
    through ``messages.create``, so strip them here on the structured
    path only. The forced-tool path keeps the constraints: a tool's
    ``input_schema`` allows full JSON Schema. The 0..1 bound stays
    enforced client-side in ``_validate_value`` either way.
    """
    wire = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            lo = node.pop("minimum", None)
            hi = node.pop("maximum", None)
            node.pop("multipleOf", None)
            if lo is not None or hi is not None:
                bound = f"Must be between {lo} and {hi}."
                desc = node.get("description")
                node["description"] = (
                    f"{desc} {bound}" if desc else bound
                )
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(wire)
    return wire


def _validate_value(key: str, value: Any, subschema: dict[str, Any]) -> list[str]:
    """Validate one property against its subschema (stdlib only)."""
    errors: list[str] = []
    want = subschema.get("type")
    if want == "string":
        if not isinstance(value, str):
            return [f"{key!r} must be a string, got {type(value).__name__}"]
        enum = subschema.get("enum")
        if enum is not None and value not in enum:
            errors.append(f"{key!r} {value!r} is not one of {list(enum)}")
    elif want == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{key!r} must be a number, got {type(value).__name__}"]
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return [f"{key!r} must be a finite number"]
        minimum = subschema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{key!r} {value} below minimum {minimum}")
        maximum = subschema.get("maximum")
        if maximum is not None and value > maximum:
            errors.append(f"{key!r} {value} above maximum {maximum}")
    return errors


def _validate_schema_object(
    obj: Any, schema: dict[str, Any]
) -> list[str]:
    """Hand-written JSON-schema validation: required keys, enum values,
    numeric ranges, additionalProperties. No third-party dependency."""
    if not isinstance(obj, dict):
        return [f"response must be a JSON object, got {type(obj).__name__}"]
    errors: list[str] = []
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in obj:
            errors.append(f"missing required key: {key!r}")
    if schema.get("additionalProperties") is False:
        for key in obj:
            if key not in properties:
                errors.append(f"unexpected key: {key!r}")
    for key, subschema in properties.items():
        if key in obj:
            errors.extend(_validate_value(key, obj[key], subschema))
    return errors


def _extract_json(text: Any) -> dict[str, Any] | None:
    """Parse a JSON object out of model text.

    Tries the whole (stripped) text first, then the span from the first
    ``{`` to the last ``}`` — models sometimes wrap the object in prose
    despite the system prompt. Returns None when nothing parses.
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        obj = None
    if isinstance(obj, dict):
        return obj
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def _parse_and_validate(
    text: Any, schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    obj = _extract_json(text)
    if obj is None:
        return None, ["no JSON object found in model output"]
    return obj, _validate_schema_object(obj, schema)


# ---------------------------------------------------------------------------
# Refusal detection.
# ---------------------------------------------------------------------------

def _refusal_stop_reason(stop_reason: Any) -> str | None:
    """The provider's own stop/finish reason, when it means refusal."""
    if isinstance(stop_reason, str) and stop_reason in REFUSAL_STOP_REASONS:
        return stop_reason
    return None


def _match_refusal_prefix(text: Any) -> str | None:
    """GCG-style check: a well-known refusal prefix in the first 200 chars."""
    if not isinstance(text, str) or not text:
        return None
    head = text[:200].casefold().lstrip()
    for prefix in REFUSAL_PREFIXES:
        if head.startswith(prefix.casefold()):
            return prefix
    return None


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------

def _parse_retry_after(headers: Any) -> float | None:
    try:
        value = headers.get("retry-after") if headers else None
    except AttributeError:
        return None
    try:
        delay = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return delay if delay >= 0 else None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _status_error(provider: str, exc: BaseException) -> ProviderError:
    """Map an SDK status error to ProviderError.

    Transient statuses (408/409/429/5xx) are retried by the runner;
    permanent ones (400/401/403/404/422) become terminal errors — never
    retried.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    return ProviderError(
        f"{provider} API error: {exc}",
        status_code=getattr(exc, "status_code", None),
        retry_after=_parse_retry_after(headers),
    )


def _google_error(exc: BaseException) -> ProviderError:
    """Duck-typed mapping for google-genai / google-api-core errors.

    Status is read from ``status_code`` (genai) or ``code`` (api-core);
    429/5xx are transient and retried by the runner, everything else is
    terminal.
    """
    status = _coerce_int(getattr(exc, "status_code", None))
    if status is None:
        status = _coerce_int(getattr(exc, "code", None))
    return ProviderError(
        f"Google API error: {exc}",
        status_code=status,
        retry_after=_parse_retry_after(getattr(exc, "headers", None)),
    )


# ---------------------------------------------------------------------------
# Shared base.
# ---------------------------------------------------------------------------

@dataclass
class _RawResult:
    """One provider call, normalized across providers."""

    text: str                        # model text ("" when the answer came
                                     # back as a parsed tool call)
    stop_reason: str | None          # provider-native, normalized to a string
    parsed: dict[str, Any] | None    # pre-parsed object (Anthropic tool
                                     # input); None when text must be parsed
    tokens_in: int
    tokens_out: int
    logprob_tokens: Any              # provider logprob payload, or None
    request_shape: dict[str, Any]     # redacted request description
    response_shape: dict[str, Any]    # provider-native response summary


class _StructuredLLMBase:
    """Shared machinery for the structured-output LLM baselines."""

    name = "structured-llm-base"  # overridden per provider
    _doctor_skip = True  # abstract base: not a usable adapter
    # M-2: confidence is the model's verbalized confidence (D-23).
    confidence_source = "verbalized"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # M-7 longitudinal provenance: structured-output LLM baselines.
    model_class = "llm-baseline"

    # Overridden per provider:
    _extra = "peira[?]"            # e.g. "peira[openai]"
    _env_vars: tuple[str, ...] = ()  # API key env vars, in lookup order
    _supports_seed = True          # False where the provider has no seed
    # R-04: the provider accepts a temperature parameter. Fail-closed:
    # a sampling-capable adapter with unset temperature refuses to run
    # rather than silently using provider defaults.
    _supports_temperature = True   # False where the provider has none

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        if isinstance(model, str) and model in DEPRECATED_PINS:
            raise DeprecatedPinError(
                f"model {model!r} was retired by its vendor; use "
                f"{DEPRECATED_PINS[model]!r} instead."
            )
        self._model = model
        self._temperature = temperature
        self._seed = seed
        self._max_tokens = max_tokens
        # The runner's adapter contract: exact pinned model version and
        # the cache namespace. Deterministic only at temperature 0 with
        # a fixed seed — an adapter-author obligation the runner cannot
        # verify.
        self.version = model
        seed_part = f":s{seed}" if self._supports_seed else ""
        self.cache_namespace = (
            f"{self.name}:{model}:t{temperature}:mt{max_tokens}{seed_part}"
            f"{self._cache_namespace_suffix()}"
        )
        self._api_key = self._resolve_api_key(api_key)
        # Subclasses build the SDK client here, with retries disabled.
        # The client is used read-only afterwards: no lazy shared state,
        # so concurrent decide() calls from worker threads are safe.
        self._client: Any = None
        self._sdk: Any = None

    def _cache_namespace_suffix(self) -> str:
        """Extra cache-namespace component for request-shape variants.

        The namespace is the runner's cache-dedup identity: two
        adapters that send different request shapes for the same model
        must not share cache entries. The default path keeps the
        historical namespace (empty suffix); adapters with a second
        request shape override this. Consulted by ``__init__`` and
        ``with_seed`` so copies keep the suffix.
        """
        return ""

    @property
    def generation_max_tokens(self) -> int:
        """EB-10(a): the adapter's declared generation cap.

        This is the cap the adapter enforces on generation; the runner
        seals it into the run artifact so length analyses can audit
        observed lengths against the declared cap.
        """
        return self._max_tokens

    @property
    def decode_params(self) -> dict[str, Any]:
        """M-7 longitudinal provenance: decode params actually sent.

        The seed is included when the provider supports one: two runs
        with different provider seeds are not the same measurement.
        """
        params: dict[str, Any] = {
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._supports_seed:
            params["seed"] = self._seed
        return params

    def with_seed(self, seed: int | None) -> "_StructuredLLMBase":
        """Return a copy of this adapter pinned to a provider seed.

        M-7 multi-seed protocol: each seed run gets its own provider
        sampling seed, so the k runs are independent measurements. The
        copy shares the read-only SDK client; only the seed and the
        seed-dependent cache namespace change.
        """
        new = copy.copy(self)
        new._seed = seed
        seed_part = f":s{seed}" if self._supports_seed else ""
        new.cache_namespace = (
            f"{self.name}:{self._model}:t{self._temperature}:"
            f"mt{self._max_tokens}{seed_part}"
            f"{self._cache_namespace_suffix()}"
        )
        return new

    # -- construction helpers -------------------------------------------

    def _resolve_api_key(self, api_key: str | None) -> str:
        key = api_key
        if not key:
            for var in self._env_vars:
                key = os.environ.get(var)
                if key:
                    break
        if not key:
            if len(self._env_vars) == 1:
                missing = f"{self._env_vars[0]} is not set"
            elif len(self._env_vars) == 2:
                missing = (
                    f"neither {self._env_vars[0]} nor {self._env_vars[1]} "
                    "is set"
                )
            else:
                missing = "none of " + ", ".join(self._env_vars) + " is set"
            raise ValueError(
                f"{missing} — {type(self).__name__} "
                f"needs it (and the {self._extra} extra)"
            )
        return key

    # -- the decide() flow -----------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> AdapterOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(
                f"{self.name} does not support primitive {primitive!r}"
            )
        # The input dict is the case's verbatim input; the candidate
        # decision labels (the open vocabulary needs them per call) come
        # from the input's explicit "options" list — never from trial
        # bookkeeping (B2: the context carries no gold).
        prompt = case_input.get("prompt", "")
        if not isinstance(prompt, str):
            prompt = str(prompt)
        labels = _decision_labels(case_input, primitive)
        schema = _build_schema(labels, primitive)
        user_text = "DECISION CONTEXT:\n" + prompt

        started = time.perf_counter()
        raw = self._request(user_text, schema, repair=False)
        attempts = 1

        refusal = _refusal_stop_reason(raw.stop_reason)
        if refusal is not None:
            return self._abstain(
                primitive, f"stop_reason: {raw.stop_reason}",
                raw, started, attempts,
            )
        prefix = _match_refusal_prefix(raw.text)
        if prefix is not None:
            return self._abstain(
                primitive, f"refusal prefix: {prefix!r}",
                raw, started, attempts,
            )

        obj, errors = self._resolve(raw, schema)
        if errors:
            # Parse-then-repair: one repair attempt with an explicit
            # "JSON only" nudge before giving up on the call.
            raw = self._request(user_text, schema, repair=True)
            attempts = 2
            refusal = _refusal_stop_reason(raw.stop_reason)
            if refusal is not None:
                return self._abstain(
                    primitive, f"stop_reason: {raw.stop_reason}",
                    raw, started, attempts,
                )
            prefix = _match_refusal_prefix(raw.text)
            if prefix is not None:
                return self._abstain(
                    primitive, f"refusal prefix: {prefix!r}",
                    raw, started, attempts,
                )
            obj, errors = self._resolve(raw, schema)

        if errors:
            # No judge: validation failed twice and no refusal signal
            # matched either attempt — a terminal provider error
            # (no status code, so the runner will NOT retry it).
            raise ProviderError(
                f"{self.name}: model output failed schema validation "
                f"twice: {'; '.join(errors)}",
                status_code=None,
            )
        assert obj is not None
        return self._build_output(primitive, obj, raw, started, attempts)

    def _resolve(
        self, raw: _RawResult, schema: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if raw.parsed is not None:
            return raw.parsed, _validate_schema_object(raw.parsed, schema)
        return _parse_and_validate(raw.text, schema)

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        """One provider call. Implemented per provider."""
        raise NotImplementedError

    # -- outputs ----------------------------------------------------------

    def _usage(self, raw: _RawResult, started: float) -> CallUsage:
        return CallUsage(
            model=self._model,  # exact pinned model id, never an alias
            tokens_in=max(0, int(raw.tokens_in or 0)),
            tokens_out=max(0, int(raw.tokens_out or 0)),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            cost_usd=0.0,  # the runner recomputes cost; ignored on input
        )

    def _transcript(
        self,
        raw: _RawResult,
        started: float,
        attempts: int,
        verbalized: float | None,
        logprob: float | None,
    ) -> dict[str, Any]:
        # Redacted by construction: the request shape names the endpoint,
        # model, and schema — never the API key.
        return {
            "model": self._model,
            "seed": self._seed if self._supports_seed else None,
            "parameters": {
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            },
            "request": raw.request_shape,
            "response": {**raw.response_shape, "attempts": attempts},
            "confidence_tracks": {
                # Verbalized confidence is UNCALIBRATED until measured —
                # see the module docstring. The decision-token logprob is
                # a second, independent signal where the provider exposes
                # one (OpenAI); None elsewhere.
                "verbalized": verbalized,
                "decision_token_logprob": logprob,
            },
        }

    def _build_output(
        self,
        primitive: str,
        obj: dict[str, Any],
        raw: _RawResult,
        started: float,
        attempts: int,
    ) -> AdapterOutput:
        decision = obj["decision"]
        confidence = float(obj["confidence"])
        logprob = self._decision_logprob(raw, decision)
        usage = self._usage(raw, started)
        transcript = self._transcript(raw, started, attempts, confidence, logprob)
        if primitive == "choice":
            return ChoiceOutput(
                decision=decision, confidence=confidence,
                usage=usage, transcript=transcript,
            )
        if primitive == "score":
            return ScoreOutput(
                score=float(obj["score"]),
                decision=decision, confidence=confidence,
                usage=usage, transcript=transcript,
            )
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _abstain(
        self,
        primitive: str,
        reason: str,
        raw: _RawResult,
        started: float,
        attempts: int,
    ) -> AdapterOutput:
        """A detected refusal: empty decision, abstained=True.

        An attacked refusal counts as flipped (abstention-state change);
        a benign refusal makes the case ineligible. Either way the call
        also counts in refusal stats, reported separately.

        Follows the convention in tests/test_refusal.py: ChoiceOutput and
        AbstainOutput carry decision="", ScoreOutput carries score=0.0 and
        decision="", confidence is None (no usable measurement).
        """
        usage = self._usage(raw, started)
        transcript = self._transcript(raw, started, attempts, None, None)
        if primitive == "choice":
            return ChoiceOutput(
                decision="", abstained=True, refusal_reason=reason,
                confidence=None, usage=usage, transcript=transcript,
            )
        if primitive == "score":
            return ScoreOutput(
                score=0.0, decision="", abstained=True,
                refusal_reason=reason, confidence=None,
                usage=usage, transcript=transcript,
            )
        return AbstainOutput(
            decision="", abstained=True, refusal_reason=reason,
            confidence=None, usage=usage, transcript=transcript,
        )

    def _decision_logprob(
        self, raw: _RawResult, decision: str
    ) -> float | None:
        """Top-1 logprob of the decision token, where exposed."""
        return None


# ---------------------------------------------------------------------------
# OpenAI.
# ---------------------------------------------------------------------------

def _openai_decision_logprob(choice: Any, decision: str) -> float | None:
    """Best-effort: logprob of a token carrying the decision label.

    Takes the first token whose text merely *contains* the label (a
    substring match — ``"deny"`` also matches ``"denying"``), so this is
    a rough signal, not a true top-1 logprob. The system prompt forces
    ``decision`` to be the first key, so in practice the label appears
    in one of the first content tokens.
    """
    logprobs = getattr(choice, "logprobs", None)
    content = getattr(logprobs, "content", None) if logprobs else None
    if not content or not decision:
        return None
    for tok in content:
        token_text = getattr(tok, "token", "")
        if isinstance(token_text, str) and decision in token_text:
            logprob = getattr(tok, "logprob", None)
            if isinstance(logprob, (int, float)) and not isinstance(
                logprob, bool
            ):
                return float(logprob)
    return None


class OpenAIAdapter(_StructuredLLMBase):
    """Baseline: OpenAI chat completions with strict JSON schema."""

    name = "openai-structured"
    _extra = "peira[openai]"
    _env_vars = ("OPENAI_API_KEY",)
    _supports_seed = True
    _provider_label = "OpenAI"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["openai-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model, temperature, seed, max_tokens, api_key)
        self._sdk = _require_openai()
        # Retries DISABLED: the runner owns the retry policy (see the
        # RETRY LAYERING rule in peira.adapters.base).
        self._client = self._sdk.OpenAI(api_key=self._api_key, max_retries=0)

    def _request_kwargs(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the ``chat.completions.create`` kwargs.

        Separated so subclasses (Moonshot) can adjust the payload —
        e.g. omitting provider-unsupported fields — without
        duplicating the error handling or result parsing.
        """
        return {
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAME,
                    "strict": True,
                    "schema": schema,
                },
            },
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "seed": self._seed,
            "logprobs": True,
        }

    def _request_shape_overrides(
        self, sent: dict[str, Any]
    ) -> dict[str, Any]:
        """Extra/override keys for the transcript's request shape.

        The base shape records the OpenAI wire fields. Subclasses
        whose provider renames a parameter (Mistral's ``random_seed``)
        or requires provider-specific body fields (Qwen's
        ``enable_thinking``) override this so the transcript records
        what was actually sent. Keys returned here win over the base
        shape's keys.
        """
        return {}

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        if repair:
            messages.append({"role": "user", "content": REPAIR_SUFFIX})
        try:
            resp = self._client.chat.completions.create(
                **self._request_kwargs(messages, schema)
            )
        except self._sdk.APIStatusError as exc:
            raise _status_error(self._provider_label, exc) from exc
        except self._sdk.APITimeoutError as exc:
            # A timeout has no status; 408 keeps it retryable for the runner.
            raise ProviderError(
                f"{self._provider_label} request timed out: {exc}",
                status_code=408,
            ) from exc
        except self._sdk.APIConnectionError as exc:
            # Builtin ConnectionError is retryable per
            # peira.concurrency.classify_exception; wrapping it in
            # ProviderError(status_code=None) would wrongly make it
            # terminal.
            raise ConnectionError(
                f"{self._provider_label} connection failed: {exc}"
            ) from exc

        choices = getattr(resp, "choices", None) or []
        if not choices:
            raise ProviderError(
                f"{self._provider_label} returned no choices",
                status_code=None,
            )
        choice = choices[0]
        text = choice.message.content or ""
        usage = getattr(resp, "usage", None)
        sent = self._request_kwargs(messages, schema)
        return _RawResult(
            text=text,
            stop_reason=getattr(choice, "finish_reason", None),
            parsed=None,
            tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
            logprob_tokens=choice,
            request_shape={
                "endpoint": "chat.completions.create",
                "model": self._model,
                "response_format": f"json_schema:{SCHEMA_NAME}:strict",
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
                # Only the fields actually sent — subclasses may omit
                # seed/logprobs (Moonshot), so read them back from the
                # kwargs rather than assuming.
                "seed": sent.get("seed"),
                "logprobs": sent.get("logprobs", False),
                **self._request_shape_overrides(sent),
            },
            response_shape={
                "finish_reason": getattr(choice, "finish_reason", None),
                "text": text[:4000],
            },
        )

    def _decision_logprob(
        self, raw: _RawResult, decision: str
    ) -> float | None:
        return _openai_decision_logprob(raw.logprob_tokens, decision)


# ---------------------------------------------------------------------------
# Moonshot (Kimi) — OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

class MoonshotAdapter(OpenAIAdapter):
    """Baseline: Moonshot Kimi through its OpenAI-compatible API.

    Reuses the OpenAI request shape verbatim (strict JSON schema via
    ``response_format``) against ``https://api.moonshot.ai/v1`` with a
    ``MOONSHOT_API_KEY`` bearer key — the ``openai`` SDK package drives
    the compat endpoint, so the extra stays ``peira[openai]``. The
    request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    Default model is ``kimi-k3`` (the pinned version of Moonshot's
    2.8T open-weight flagship, $3/$15 per 1M): the self-host audience's
    flagship model, and the cheapest way to put a frontier-adjacent
    model on the board.

    Request shape: Moonshot's API 400s on ``seed`` and ``logprobs``
    (per third-party parameter surveys — the adapter omits both
    fields rather than negotiating), so there is NO decision-token
    logprob track on this adapter; the transcript honestly records
    ``"seed": None`` and ``"logprobs": False``. Moonshot documents
    ``temperature`` only on the 0..1 range, and whether ``json_schema``
    ``response_format`` (vs plain ``json_object``) is honored for
    ``kimi-k3`` is unverified. If the live endpoint rejects or ignores
    any of these, you will see terminal provider errors, not silent
    mismeasurement — verify against the live API before any measured
    run. Not exercised against the live API yet.
    """

    name = "moonshot-structured"
    _extra = "peira[openai]"
    _env_vars = ("MOONSHOT_API_KEY",)
    _provider_label = "Moonshot"
    _supports_seed = False

    _base_url = "https://api.moonshot.ai/v1"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["moonshot-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # Moonshot's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key, base_url=self._base_url, max_retries=0
        )

    def _request_kwargs(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        kwargs = super()._request_kwargs(messages, schema)
        # Moonshot 400s on seed and logprobs — omit both rather than
        # negotiating. No decision-token logprob track on this adapter.
        kwargs.pop("seed", None)
        kwargs.pop("logprobs", None)
        return kwargs

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# xAI (Grok) — OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

class XAIAdapter(OpenAIAdapter):
    """Baseline: xAI Grok through its OpenAI-compatible API.

    Reuses the OpenAI request shape verbatim (strict JSON schema via
    ``response_format``) against ``https://api.x.ai/v1`` with an
    ``XAI_API_KEY`` Bearer token — the ``openai`` SDK package drives
    the compat endpoint, so the extra stays ``peira[openai]``. The
    request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    Default model is ``grok-4`` (xAI's current flagship; the vendor
    also publishes dated variants such as ``grok-4-0709``).

    Request shape: xAI documents ``seed`` as supported (best-effort
    deterministic), so the seed is sent; whether ``json_schema``
    ``response_format`` (vs plain ``json_object``) is honored for
    ``grok-4`` is unverified. If the live endpoint rejects or ignores
    any of these, you will see terminal provider errors, not silent
    mismeasurement — verify against the live API before any measured
    run. Not exercised against the live API yet.
    """

    name = "xai-structured"
    _extra = "peira[openai]"
    _env_vars = ("XAI_API_KEY",)
    _provider_label = "xAI"
    _supports_seed = True

    _base_url = "https://api.x.ai/v1"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["xai-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # xAI's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key, base_url=self._base_url, max_retries=0
        )

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# DeepSeek — OpenAI-compatible endpoint (no /v1 suffix).
# ---------------------------------------------------------------------------

class DeepSeekAdapter(OpenAIAdapter):
    """Baseline: DeepSeek through its OpenAI-compatible API.

    Reuses the OpenAI request shape verbatim (strict JSON schema via
    ``response_format``) against ``https://api.deepseek.com`` with a
    ``DEEPSEEK_API_KEY`` Bearer token — the ``openai`` SDK package drives
    the compat endpoint, so the extra stays ``peira[openai]``. The
    request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    Note the base URL carries NO ``/v1`` suffix: DeepSeek's documented
    endpoint is ``POST https://api.deepseek.com/chat/completions``.

    Default model is ``deepseek-flash`` (the vendor's alias for the
    current DeepSeek-V4.1 Flash; the legacy ``deepseek-chat`` /
    ``deepseek-reasoner`` IDs were discontinued 2026-07-24).

    Request shape: DeepSeek's thinking mode is DISABLED
    (``thinking: {"type": "disabled"}``) per the evaluation design —
    reasoning traces would otherwise leak into the decision channel.
    Whether ``json_schema`` ``response_format`` (vs plain
    ``json_object``, which DeepSeek documents) is honored for
    ``deepseek-flash`` is unverified. If the live endpoint rejects or
    ignores any of these, you will see terminal provider errors, not
    silent mismeasurement — verify against the live API before any
    measured run. Not exercised against the live API yet.
    """

    name = "deepseek-structured"
    _extra = "peira[openai]"
    _env_vars = ("DEEPSEEK_API_KEY",)
    _provider_label = "DeepSeek"
    _supports_seed = True

    _base_url = "https://api.deepseek.com"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["deepseek-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # DeepSeek's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key, base_url=self._base_url, max_retries=0
        )

    def _request_kwargs(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        kwargs = super()._request_kwargs(messages, schema)
        # ``thinking`` is not an OpenAI SDK body parameter, so it
        # travels via ``extra_body`` (the same pattern QwenAdapter
        # uses for ``enable_thinking``). Thinking stays disabled per
        # the evaluation design: reasoning traces must not leak into
        # the decision channel.
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["thinking"] = {"type": "disabled"}
        kwargs["extra_body"] = extra_body
        return kwargs

    def _request_shape_overrides(
        self, sent: dict[str, Any]
    ) -> dict[str, Any]:
        # The thinking kill-switch is load-bearing for this adapter —
        # record it in the transcript, not just the wire kwargs.
        extra_body = sent.get("extra_body") or {}
        return {"thinking": extra_body.get("thinking")}

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# Meta Llama API — OpenAI-compatible endpoint (/compat/v1 path).
# ---------------------------------------------------------------------------

class MetaLlamaAdapter(OpenAIAdapter):
    """Baseline: Meta Llama API through its OpenAI-compatible endpoint.

    Reuses the OpenAI request shape verbatim (strict JSON schema via
    ``response_format``) against ``https://api.llama.com/compat/v1``
    with a ``META_API_KEY`` Bearer token — the ``openai`` SDK package
    drives the compat endpoint, so the extra stays ``peira[openai]``.
    The request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    Note the ``/compat/v1`` path: Meta's native API lives at
    ``https://api.llama.com/v1`` with a different response shape; only
    the ``/compat/v1`` prefix speaks the OpenAI wire protocol.

    Default model is ``Llama-4-Maverick-17B-128E-Instruct-FP8`` (Meta's
    documented example model for the compat endpoint).

    Request shape: Meta documents that some OpenAI client features are
    NOT supported on the compat endpoint — whether ``json_schema``
    ``response_format``, ``seed``, and ``logprobs`` are honored is
    unverified. If the live endpoint rejects or ignores any of these,
    you will see terminal provider errors, not silent mismeasurement —
    verify against the live API before any measured run. Not exercised
    against the live API yet.
    """

    name = "meta-structured"
    _extra = "peira[openai]"
    _env_vars = ("META_API_KEY",)
    _provider_label = "Meta"
    _supports_seed = True

    _base_url = "https://api.llama.com/compat/v1"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["meta-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # Meta's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key, base_url=self._base_url, max_retries=0
        )

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# Zhipu Z.ai (GLM) — OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

class ZaiAdapter(OpenAIAdapter):
    """Baseline: Zhipu GLM through its OpenAI-compatible API.

    Reuses the OpenAI request shape verbatim (strict JSON schema via
    ``response_format``) against ``https://open.bigmodel.cn/api/paas/v4``
    with a ``ZAI_API_KEY`` Bearer token — the ``openai`` SDK package
    drives the compat endpoint, so the extra stays ``peira[openai]``.
    The request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    Auth note: Zhipu also supports JWT auth built from the API key ID
    plus secret, but the OpenAI-compatible endpoint accepts the API key
    directly as the Bearer token (per Zhipu's own OpenAI-compat docs),
    which is what this adapter uses.

    Default model is ``glm-4-plus`` (Zhipu's current paid flagship in
    the GLM-4 family).

    Request shape: whether ``json_schema`` ``response_format``, ``seed``,
    and ``logprobs`` are honored for ``glm-4-plus`` is unverified. If
    the live endpoint rejects or ignores any of these, you will see
    terminal provider errors, not silent mismeasurement — verify against
    the live API before any measured run. Not exercised against the
    live API yet.
    """

    name = "zai-structured"
    _extra = "peira[openai]"
    _env_vars = ("ZAI_API_KEY",)
    _provider_label = "Zhipu"
    _supports_seed = True

    _base_url = "https://open.bigmodel.cn/api/paas/v4"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["zai-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # Zhipu's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key, base_url=self._base_url, max_retries=0
        )

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# Mistral — OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

class MistralAdapter(OpenAIAdapter):
    """Baseline: Mistral Large through La Plateforme's chat completions.

    Reuses the OpenAI request shape (strict JSON schema via
    ``response_format``) against ``https://api.mistral.ai/v1`` with a
    ``MISTRAL_API_KEY`` Bearer <redacted> — the ``openai`` SDK package drives
    the compat endpoint, so the extra stays ``peira[openai]``. The
    request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    Default model is ``mistral-large-2512`` (Mistral Large 3, the
    December 2025 dated snapshot behind ``mistral-large-latest``;
    $0.50/$1.50 per 1M): Mistral's open-weight flagship and the
    European lab's frontier entry.

    Request shape: Mistral names the seed parameter ``random_seed``
    (not ``seed``), and ``logprobs`` is not documented for chat
    completions, so the adapter sends ``random_seed`` instead of
    ``seed`` and omits ``logprobs`` rather than negotiating. There is
    NO decision-token logprob track on this adapter; the transcript
    records the seed under the wire name it was sent with. If the live
    endpoint rejects or ignores any of these, you will see terminal
    provider errors, not silent mismeasurement — verify against the
    live API before any measured run. Not exercised against the live
    API yet.
    """

    name = "mistral-structured"
    _extra = "peira[openai]"
    _env_vars = ("MISTRAL_API_KEY",)
    _provider_label = "Mistral"
    _supports_seed = True
    _base_url = "https://api.mistral.ai/v1"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["mistral-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # Mistral's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            # Retries DISABLED: the runner owns the retry policy.
            max_retries=0,
        )

    def _request_kwargs(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        kwargs = super()._request_kwargs(messages, schema)
        # Mistral's wire name for the seed is ``random_seed``; the
        # OpenAI ``seed`` field is dropped, not sent alongside it.
        # ``logprobs`` is undocumented for chat completions — omit,
        # don't negotiate. No decision-token logprob track.
        kwargs.pop("seed", None)
        kwargs.pop("logprobs", None)
        if self._seed is not None:
            kwargs["random_seed"] = self._seed
        return kwargs

    def _request_shape_overrides(
        self, sent: dict[str, Any]
    ) -> dict[str, Any]:
        # Record the seed under the wire name it was actually sent
        # with, so the transcript never claims an unsent ``seed``.
        return {"seed": sent.get("random_seed")}

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# Qwen — Alibaba DashScope OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

class QwenAdapter(OpenAIAdapter):
    """Baseline: Qwen through DashScope's OpenAI-compatible endpoint.

    Reuses the OpenAI request shape (strict JSON schema via
    ``response_format``) against DashScope's compatible-mode endpoint
    with a ``DASHSCOPE_API_KEY`` Bearer <redacted> — the ``openai`` SDK
    package drives the compat endpoint, so the extra stays
    ``peira[openai]``. The request's ``base_url`` is recorded in the
    transcript's request shape; the key itself never is.

    Default model is ``qwen3.8-max`` (Alibaba's August 2026 flagship,
    2.4T MoE; $2.00/$6.00 per 1M on the international endpoint):
    ``qwen-max`` is the rolling alias for the same tier, but the pin
    uses the versioned id for reproducibility.

    Request shape: DashScope requires ``enable_thinking`` to be set
    explicitly on every request, and rejects the request when the
    parameter is absent; for non-streaming calls it must be ``false``. Qwen's
    hybrid-thinking models also reject ``response_format:
    json_schema`` when thinking is enabled, so the adapter sets
    ``enable_thinking: false`` via ``extra_body`` on every call —
    thinking is off by construction, never by omission. ``seed`` is
    passed through as documented. If the live endpoint rejects or
    ignores any of these, you will see terminal provider errors, not
    silent mismeasurement — verify against the live API before any
    measured run. Not exercised against the live API yet.
    """

    name = "qwen-structured"
    _extra = "peira[openai]"
    _env_vars = ("DASHSCOPE_API_KEY",)
    _provider_label = "Qwen"
    _supports_seed = True
    # International endpoint. China-region keys are minted per host;
    # a key issued for dashscope.aliyuncs.com will not authenticate
    # here — see the docs section for the regional hostnames.
    _base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["qwen-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # DashScope's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            # Retries DISABLED: the runner owns the retry policy.
            max_retries=0,
        )

    def _request_kwargs(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        kwargs = super()._request_kwargs(messages, schema)
        # ``enable_thinking`` is not an OpenAI SDK body parameter, so
        # it travels via ``extra_body`` (the pattern DashScope's own
        # docs use). Explicit ``false``: the endpoint rejects requests
        # that omit it, and json_schema is honored only with thinking
        # disabled.
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["enable_thinking"] = False
        kwargs["extra_body"] = extra_body
        return kwargs

    def _request_shape_overrides(
        self, sent: dict[str, Any]
    ) -> dict[str, Any]:
        # The thinking kill-switch is load-bearing for this adapter —
        # record it in the transcript, not just the wire kwargs.
        extra_body = sent.get("extra_body") or {}
        return {"enable_thinking": extra_body.get("enable_thinking")}

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# OpenRouter — unified gateway for structured-output LLM baselines.
# ---------------------------------------------------------------------------

class OpenRouterAdapter(OpenAIAdapter):
    """Baseline: any OpenRouter model through the unified gateway.

    Reuses the OpenAI request shape verbatim (strict JSON schema via
    ``response_format``) against ``https://openrouter.ai/api/v1`` with
    an ``OPENROUTER_API_KEY`` Bearer token — the ``openai`` SDK package
    drives the compat endpoint, so the extra stays ``peira[openai]``.
    The request's ``base_url`` is recorded in the transcript's request
    shape; the key itself never is.

    This is the one adapter that can reach any of OpenRouter's 400+
    models: ``OpenRouterAdapter(model="vendor/model-id")``. It exists
    so new LLM baselines do not each need a bespoke adapter — the
    gateway is the default route for one-off or exploratory models,
    and per-provider adapters stay reserved for models peira measures
    repeatedly (where provider-native quirks earn their own code).

    Default model is ``google/gemini-3.8-flash``: the same model family
    as the GoogleAdapter default, reached through the gateway instead
    of the vendor API — the direct-vs-gateway comparison is the point
    of the default. Flash-tier, so it stays inside the cost guard.

    Request shape: OpenRouter translates ``response_format``
    ``json_schema`` to each provider's native structured-output
    mechanism (Anthropic ``output_config.format``, Google native
    schema, OpenAI passthrough). Whether a given model honors it is a
    per-model property of the upstream provider: models that ignore or
    reject the schema surface as terminal provider errors or failed
    schema validation — never silent mismeasurement — so verify a new
    model id against the live API before any measured run. ``seed``
    and ``logprobs`` are sent (OpenRouter documents both as supported
    request parameters); per-model passthrough is likewise unverified.

    Deliberately NOT used: OpenRouter's ``models`` fallback array. A
    fallback would silently substitute a different model mid-run,
    breaking the cache namespace and the measurement identity (one
    adapter instance = one pinned model id, always). If you need
    failover, run two adapter instances.

    App-identification headers (``HTTP-Referer``/``X-Title``) follow
    OpenRouter's documented convention; they carry the project domain
    and name, never the key.

    Not exercised against the live API yet.
    """

    name = "openrouter-structured"
    _extra = "peira[openai]"
    _env_vars = ("OPENROUTER_API_KEY",)
    _provider_label = "OpenRouter"
    _supports_seed = True

    _base_url = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        model: str = PINNED_API_MODELS["openrouter-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        # Not OpenAIAdapter.__init__: that constructor pins the client
        # to api.openai.com. Rebuild the identical client against
        # OpenRouter's OpenAI-compatible endpoint — retries still
        # DISABLED, the runner owns the retry policy. App-identification
        # headers follow OpenRouter's documented convention.
        _StructuredLLMBase.__init__(
            self, model, temperature, seed, max_tokens, api_key
        )
        self._sdk = _require_openai()
        self._client = self._sdk.OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            max_retries=0,
            default_headers={
                "HTTP-Referer": "https://peiratrial.dev",
                "X-Title": "peira",
            },
        )

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        raw = super()._request(user_text, schema, repair)
        # The inherited request shape names the endpoint and model but
        # not the host it was sent to — record it for traceability.
        raw.request_shape["base_url"] = self._base_url
        return raw


# ---------------------------------------------------------------------------
# Anthropic.
# ---------------------------------------------------------------------------

# Newer Anthropic reasoning models reject forced ``tool_choice``
# (HTTP 400; only ``auto``/``none`` are accepted), so they are driven
# through native ``output_config.format`` JSON-schema structured
# outputs instead of the forced-tool path. This is an explicit
# allowlist of repo-documented ids: do NOT extend it with unconfirmed
# ids (D-32; even ``claude-fable-5-1`` itself is still unverified
# against the live API). Any other model opts in explicitly via
# ``AnthropicAdapter(..., structured_outputs=True)``.
#
# D3 reconciliation (2026-09-30): the Opus 5.5 API id is
# ``claude-opus-5-5`` (verified against Anthropic's model docs, AWS
# Bedrock, and launch coverage — released 2026-09-22), and Claude
# Sonnet 5.5 shipped 2026-09-28 as ``claude-sonnet-5-5``. Both are
# 5.x reasoning models, so both route here. The default pin stays
# ``claude-sonnet-5`` until a live smoke test decides D3's
# (a)/(b)/(c); pass ``model="claude-opus-5-5"`` explicitly to measure
# Opus 5.5. All ids in this set are live-UNVERIFIED from this
# environment (no API calls in the authoring lane).
_STRUCTURED_OUTPUT_MODELS = frozenset({
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
})


# Anthropic rejects ``temperature``/``top_p`` with a 400 on the Opus
# 4.6 generation and later, so the adapter omits the field for these
# ids instead of sending it. Explicit allowlist, same discipline as
# ``_STRUCTURED_OUTPUT_MODELS``: do NOT extend with unconfirmed ids.
# Live-UNVERIFIED (no API calls in the authoring lane).
_NO_TEMPERATURE_MODELS = frozenset({
    "claude-opus-5-5",
    "claude-sonnet-5-5",
})


def _wants_structured_outputs(model: str, flag: bool | None) -> bool:
    """Route an Anthropic model to its constrained-decoding path.

    An explicit ``structured_outputs=True/False`` always wins;
    ``None`` (the default) auto-routes the known newer reasoning
    models in ``_STRUCTURED_OUTPUT_MODELS``. Older models keep the
    forced-tool path, so defaults are unchanged.
    """
    if flag is not None:
        return flag
    return model in _STRUCTURED_OUTPUT_MODELS


class AnthropicAdapter(_StructuredLLMBase):
    """Baseline: Anthropic messages with constrained decoding.

    Two request paths, one typed contract. Older models use forced
    tool use: the schema is sent as a tool's ``input_schema`` with
    ``tool_choice`` forced to that tool, so the model must answer
    through the schema. Newer reasoning models (``claude-fable-5-1``
    and friends; see ``_STRUCTURED_OUTPUT_MODELS``) reject forced
    ``tool_choice`` with a 400, so they use native
    ``output_config.format`` JSON-schema structured outputs instead:
    no ``tools``, no ``tool_choice``. On that path the JSON arrives in
    text blocks and is parsed by the shared ``_parse_and_validate``,
    so both paths produce the same typed decision contract
    (choice/score/abstain) through the same ``_resolve`` →
    ``_build_output`` machinery.

    Routing: ``structured_outputs=None`` (default) auto-routes the
    known newer models and keeps everything else on forced tool use;
    pass ``True``/``False`` to force a path explicitly.

    Anthropic has NO seed parameter: ``seed`` is accepted for a
    uniform constructor signature but ignored, and recorded as null.
    """

    name = "anthropic-structured"
    _extra = "peira[anthropic]"
    _env_vars = ("ANTHROPIC_API_KEY",)
    _supports_seed = False

    def __init__(
        self,
        model: str = PINNED_API_MODELS["anthropic-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
        structured_outputs: bool | None = None,
    ) -> None:
        # Set before super().__init__: the cache-namespace suffix hook
        # reads it while the base constructor builds the namespace.
        self._structured_outputs = _wants_structured_outputs(
            model, structured_outputs
        )
        super().__init__(model, temperature, seed, max_tokens, api_key)
        self._sdk = _require_anthropic()
        # Retries DISABLED: the runner owns the retry policy.
        self._client = self._sdk.Anthropic(
            api_key=self._api_key, max_retries=0
        )

    def _cache_namespace_suffix(self) -> str:
        # The constrained-decoding path is part of the measurement
        # identity: a cached forced-tool response must never satisfy
        # an output_config request for the same model (or vice versa).
        # The default path keeps the historical namespace.
        return ":so" if self._structured_outputs else ""

    def _request_kwargs(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the ``messages.create`` kwargs for the routed path.

        Separated (like ``OpenAIAdapter._request_kwargs``) so the exact
        request shape is assertable in tests without touching the
        response parsing.
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        }
        if self._model not in _NO_TEMPERATURE_MODELS:
            # Opus 4.6+ rejects temperature with a 400 — omit it for
            # those ids rather than negotiating.
            kwargs["temperature"] = self._temperature
        if self._structured_outputs:
            # Native structured outputs: no tools, no tool_choice.
            # Forced tool_choice 400s on the newer reasoning models.
            # The wire schema is sanitized: output_config.format
            # rejects numeric constraints (minimum/maximum) with a 400.
            kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": _structured_wire_schema(schema),
                },
            }
        else:
            kwargs["tools"] = [
                {"name": SCHEMA_NAME, "input_schema": schema}
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": SCHEMA_NAME}
        return kwargs

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        messages = [{"role": "user", "content": user_text}]
        if repair:
            messages.append({"role": "user", "content": REPAIR_SUFFIX})
        # Bound once so the transcript's request shape can record the
        # fields actually sent (temperature is omitted for some ids).
        sent = self._request_kwargs(messages, schema)
        try:
            resp = self._client.messages.create(**sent)
        except self._sdk.APIStatusError as exc:
            raise _status_error("Anthropic", exc) from exc
        except self._sdk.APITimeoutError as exc:
            raise ProviderError(
                f"Anthropic request timed out: {exc}", status_code=408
            ) from exc
        except self._sdk.APIConnectionError as exc:
            raise ConnectionError(
                f"Anthropic connection failed: {exc}"
            ) from exc

        stop_reason = getattr(resp, "stop_reason", None)
        text_parts: list[str] = []
        tool_input: dict[str, Any] | None = None
        for block in getattr(resp, "content", None) or []:
            block_type = getattr(block, "type", "")
            if (
                block_type == "tool_use"
                and getattr(block, "name", "") == SCHEMA_NAME
            ):
                candidate = getattr(block, "input", None)
                if isinstance(candidate, dict):
                    tool_input = candidate
            elif block_type == "text":
                part = getattr(block, "text", "")
                if isinstance(part, str):
                    text_parts.append(part)
        text = "".join(text_parts)
        usage = getattr(resp, "usage", None)
        if self._structured_outputs:
            request_shape: dict[str, Any] = {
                "endpoint": "messages.create",
                "model": self._model,
                "system": "peira system prompt",
                "output_config": "json_schema",
                # Only the temperature actually sent — omitted for
                # the _NO_TEMPERATURE_MODELS ids.
                "temperature": sent.get("temperature"),
                "max_tokens": self._max_tokens,
            }
        else:
            request_shape = {
                "endpoint": "messages.create",
                "model": self._model,
                "system": "peira system prompt",
                "tool": SCHEMA_NAME,
                "tool_choice": "forced",
                "temperature": sent.get("temperature"),
                "max_tokens": self._max_tokens,
            }
        return _RawResult(
            text=text,
            stop_reason=stop_reason,
            # Forced-tool path: the answer arrives pre-parsed as tool
            # input. Structured-outputs path: the JSON arrives in text
            # blocks and goes through the shared _parse_and_validate.
            # Both funnel into the same typed contract.
            parsed=tool_input,
            tokens_in=int(getattr(usage, "input_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "output_tokens", 0) or 0),
            logprob_tokens=None,  # Anthropic exposes no token logprobs
            request_shape=request_shape,
            response_shape={
                "stop_reason": stop_reason,
                "text": text[:4000],
            },
        )


# ---------------------------------------------------------------------------
# Google (google-genai SDK).
# ---------------------------------------------------------------------------

class GoogleAdapter(_StructuredLLMBase):
    """Baseline: Google genai with JSON response schema.

    ``GOOGLE_API_KEY`` is tried first, then ``GEMINI_API_KEY``. The genai
    client is constructed with no ``HttpOptions`` retry options, so
    generate_content is a single attempt, which is what the runner's
    retry layering requires. Token logprobs are not exposed by this
    API — recorded as null.
    """

    name = "google-structured"
    _extra = "peira[google]"
    _env_vars = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
    _supports_seed = True

    def __init__(
        self,
        model: str = PINNED_API_MODELS["google-structured"],
        temperature: float = 0.0,
        seed: int | None = 0,
        max_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model, temperature, seed, max_tokens, api_key)
        self._sdk = _require_genai()
        # No retry config exists on genai.Client: a single attempt, as
        # the runner's retry layering requires.
        self._client = self._sdk.Client(api_key=self._api_key)

    def _request(
        self, user_text: str, schema: dict[str, Any], repair: bool
    ) -> _RawResult:
        genai = self._sdk
        config = genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=self._temperature,
            max_output_tokens=self._max_tokens,
            seed=self._seed,
        )
        contents = [user_text]
        if repair:
            contents.append(REPAIR_SUFFIX)
        try:
            resp = self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except Exception as exc:  # noqa: BLE001 — duck-typed below
            # Only the SDK call is wrapped: parsing happens outside, so
            # adapter bugs are never misclassified as provider errors.
            raise _google_error(exc) from exc

        text = getattr(resp, "text", "") or ""
        candidates = getattr(resp, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) \
            if candidates else None
        finish_name = getattr(finish, "name", finish)
        if not isinstance(finish_name, str):
            finish_name = None if finish is None else str(finish)
        prompt_feedback = getattr(resp, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None)
        block_name = getattr(block_reason, "name", block_reason)
        stop_reason = finish_name
        if block_name:
            # A blocked prompt is a refusal; normalized to SAFETY for the
            # refusal pipeline, with the raw reason kept in the transcript.
            stop_reason = "SAFETY"
        usage = getattr(resp, "usage_metadata", None)
        return _RawResult(
            text=text if isinstance(text, str) else "",
            stop_reason=stop_reason,
            parsed=None,
            tokens_in=int(getattr(usage, "prompt_token_count", 0) or 0),
            tokens_out=int(getattr(usage, "candidates_token_count", 0) or 0),
            logprob_tokens=None,  # not exposed by generate_content
            request_shape={
                "endpoint": "models.generate_content",
                "model": self._model,
                "response_mime_type": "application/json",
                "response_schema": SCHEMA_NAME,
                "temperature": self._temperature,
                "max_output_tokens": self._max_tokens,
                "seed": self._seed,
            },
            response_shape={
                "finish_reason": finish_name,
                "prompt_block_reason": (
                    block_name if isinstance(block_name, str)
                    else (str(block_name) if block_name else None)
                ),
                "text": (text if isinstance(text, str) else "")[:4000],
            },
        )
