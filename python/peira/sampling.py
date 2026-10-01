"""R-04: effective sampling-config capture + fail-closed validation.

Why this exists: a benchmark number is meaningless if the harness
cannot say what sampling parameters were actually sent on the wire.
Two runs of the "same" adapter with different temperatures are not
the same measurement, and a provider silently substituting its own
default temperature invalidates every comparison built on the run.
This module answers "what sampling config produced this call" for
every transcript entry, and refuses to run sampling-capable adapters
that cannot answer it (fail closed).

The contract (see ``peira.adapters.base.BaseAdapter``):

- Sampling-capable adapters declare ``_supports_temperature`` (peira
  already had ``_supports_seed``; temperature gets its own flag for
  the provider deprecation trend where temperature control is being
  removed) and expose the decode parameters actually sent via
  ``decode_params``.
- :func:`effective_sampling_config` resolves the per-call config plus
  a ``sampling_source`` flag from the closed vocabulary below, so a
  transcript reader always knows how much to trust the numbers.
- :func:`validate_sampling_config` fails closed: a sampling-capable
  adapter with unset temperature or seed raises instead of running
  with provider defaults. Adapters that never opted into the contract
  (no ``_supports_temperature`` attribute) are left alone for
  backward compatibility: their source is ``"unknown"``.

Determinism is explicitly NOT claimed, even at temperature 0 with a
fixed seed: provider-side nondeterminism (batching, hardware, silent
model swaps) is outside the harness's control. The stability probe
(:mod:`peira.stability_probe`) quantifies the resulting generation
instability instead of pretending it away.
"""

from __future__ import annotations

from typing import Any

#: The adapter declared the config it sent (via ``decode_params``).
SAMPLING_SOURCE_DECLARED = "adapter-declared"
#: The provider cannot control sampling (``_supports_temperature`` is
#: False): temperature/seed are meaningfully absent, not unknown.
SAMPLING_SOURCE_INCAPABLE = "provider-incapable"
#: The adapter never opted into the sampling contract: no
#: ``decode_params``, no ``_supports_temperature``. Backward
#: compatibility, not a claim.
SAMPLING_SOURCE_UNKNOWN = "unknown"

#: Closed vocabulary for ``sampling_config["sampling_source"]``.
SAMPLING_SOURCES = frozenset({
    SAMPLING_SOURCE_DECLARED,
    SAMPLING_SOURCE_INCAPABLE,
    SAMPLING_SOURCE_UNKNOWN,
})


def sampling_cache_namespace(sampling_config: dict | None) -> str:
    """Cache-namespace fragment covering the effective sampling config.

    lm-eval-harness #3881 class: a cache key that omits sampling params
    silently reuses entries recorded under a different temperature/seed.
    The runner folds this fragment into the adapter's cache namespace
    when building call keys, so the key covers the *effective* config:
    the values actually sent on the wire, not just what the adapter
    declared. Non-None temperature/seed/max_tokens each contribute;
    adapters with no sampling knobs set produce an empty fragment, so
    their existing cache entries keep working.
    """
    if not sampling_config:
        return ""
    parts = []
    for key in ("temperature", "seed", "max_tokens"):
        value = sampling_config.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    return ",".join(parts)


def with_sampling_namespace(namespace: str, sampling_config: dict | None) -> str:
    """Fold the effective sampling config into a cache namespace.

    Returns ``namespace`` unchanged when the sampling fragment is empty
    (adapters with no sampling knobs set), so their existing cache
    entries keep working; otherwise appends the fragment after a ``|``.
    """
    fragment = sampling_cache_namespace(sampling_config)
    if not fragment:
        return namespace
    return f"{namespace}|{fragment}" if namespace else fragment


class SamplingConfigError(ValueError):
    """A sampling-capable adapter cannot say what it will send.

    Raised by :func:`validate_sampling_config` before any case runs:
    running with provider-default sampling would silently invalidate
    the measurement, so the run fails closed instead.
    """


def check_sampling_config(config: dict[str, Any] | None) -> None:
    """Hostile-input check for a ``sampling_config`` mapping.

    Raises :class:`ValueError` unless ``config`` is None (records
    sealed before R-04) or a dict whose ``sampling_source`` belongs to
    the closed :data:`SAMPLING_SOURCES` vocabulary. Transcript replay
    and sealed-artifact readers use this so a hand-edited
    ``sampling_source`` fails loudly instead of riding through as
    trusted metadata.
    """
    if config is None:
        return
    if not isinstance(config, dict):
        raise ValueError(
            "sampling_config: must be a mapping or null, got "
            f"{type(config).__name__}"
        )
    source = config.get("sampling_source")
    if source is not None and source not in SAMPLING_SOURCES:
        raise ValueError(
            f"sampling_config: unknown sampling_source {source!r} "
            f"(expected one of {sorted(SAMPLING_SOURCES)})"
        )


def _decode_params(adapter: Any) -> dict[str, Any] | None:
    """The adapter's declared wire params, or None if undeclared.

    Never raises: a ``decode_params`` that blows up is itself evidence
    the config is unknown, and the fail-closed gate downstream turns
    "unknown" into a refusal for declared-capable adapters.
    """
    raw = getattr(adapter, "decode_params", None)
    if raw is None:
        return None
    if callable(raw):
        try:
            raw = raw()
        except Exception:
            return None
    if isinstance(raw, dict):
        return dict(raw)
    # The contract allows a JSON string of decode parameters.
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return dict(parsed) if isinstance(parsed, dict) else None
    return None


def effective_sampling_config(adapter: Any) -> dict[str, Any]:
    """Resolve the effective sampling config for one adapter.

    Returns a JSON-shaped dict with ``temperature``, ``seed``,
    ``max_tokens`` (each the effective value or None when not
    applicable/declared) and ``sampling_source`` from the closed
    vocabulary. Never raises for a well-formed adapter: unknown is a
    valid answer, silent provider defaults are not.
    """
    params = _decode_params(adapter)
    supports_temperature = getattr(adapter, "_supports_temperature", None)
    supports_seed = getattr(adapter, "_supports_seed", None)

    if supports_temperature is False:
        # Provider-incapable: the adapter opted in far enough to say
        # temperature control does not exist here. The capability flag
        # is authoritative for temperature (a provider that cannot
        # control it did not send one), so temperature is meaningfully
        # absent even when decode_params names one. The seed is
        # reported when the adapter claims seed support and declared
        # wire params, since a provider can drop temperature control
        # while still honoring seeds; max_tokens rides along when
        # declared.
        return {
            "temperature": None,
            "seed": (
                params.get("seed")
                if (params is not None and supports_seed)
                else None
            ),
            "max_tokens": (
                params.get("max_tokens") if params is not None else None
            ),
            "sampling_source": SAMPLING_SOURCE_INCAPABLE,
        }
    if params is not None:
        return {
            "temperature": params.get("temperature"),
            "seed": params.get("seed"),
            "max_tokens": params.get("max_tokens"),
            "sampling_source": SAMPLING_SOURCE_DECLARED,
        }
    return {
        "temperature": None,
        "seed": None,
        "max_tokens": None,
        "sampling_source": SAMPLING_SOURCE_UNKNOWN,
    }


def validate_sampling_config(adapter: Any) -> dict[str, Any]:
    """Fail closed on unset temperature/seed for sampling-capable adapters.

    Returns the effective config (see :func:`effective_sampling_config`)
    so callers resolve once. Raises :class:`SamplingConfigError` when
    an adapter declares sampling capability (``_supports_temperature``
    / ``_supports_seed``) but its effective config leaves the
    corresponding parameter unset: the run would otherwise proceed on
    provider defaults, silently invalidating every comparison.
    Adapters that never declared ``_supports_temperature`` skip the
    check (backward compatibility).
    """
    config = effective_sampling_config(adapter)
    name = getattr(adapter, "name", type(adapter).__name__)
    if getattr(adapter, "_supports_temperature", None) is True:
        if config["temperature"] is None:
            raise SamplingConfigError(
                f"adapter {name!r} declares _supports_temperature but "
                "its effective temperature is unset: declare an explicit "
                "temperature or set _supports_temperature = False"
            )
    if getattr(adapter, "_supports_seed", None) is True:
        if config["seed"] is None:
            raise SamplingConfigError(
                f"adapter {name!r} declares _supports_seed but its "
                "effective seed is unset: declare an explicit seed or "
                "set _supports_seed = False"
            )
    return config
