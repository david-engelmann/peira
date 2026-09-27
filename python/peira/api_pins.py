"""Pinned model versions for API adapters (execution methodology, Layer 3a).

An API model name like ``"gpt-5.6-luna"`` is a floating alias: the vendor
can change the weights behind it at any time, so two runs months apart
can measure different models under the same ``adapter_version``. The
benchmark therefore pins the exact dated/numeric model version each API
adapter uses by default — the same discipline the HF adapters apply to
``hf_revision``.

This module is the single source of truth for those pins. It is
stdlib-only (the base ``peira`` tier has zero third-party runtime
dependencies) and makes no network calls: pin validity is maintained by
review, not probed live. ``peira doctor`` warns when an API adapter's
default model is not the pinned version, and the runner seals the
resolved ``adapter_version`` into the run artifact's analysis lock, so a
pinned run is reproducible and an unpinned run is visibly marked by its
version string.

Registry maintenance: when a vendor ships a new dated model ID, update
``PINNED_API_MODELS`` in a PR and add the old ID to ``DEPRECATED_PINS``
with its replacement. Never delete a deprecated entry outright — old
artifacts name the old ID, and the registry must keep explaining them.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "PINNED_API_MODELS",
    "DEPRECATED_PINS",
    "UnknownAdapterPinError",
    "DeprecatedPinError",
    "get_pinned_model",
    "is_pinned_model",
    "pin_status",
    "validate_registry",
]

# ---------------------------------------------------------------------------
# The registry: adapter name -> pinned model version.
# ---------------------------------------------------------------------------
#
# Pin IDs follow each vendor's own versioning convention:
#   OpenAI:    <name>-YYYY-MM-DD  (cf. gpt-4o-2024-08-06)
#   Anthropic: <name>-YYYYMMDD    (cf. claude-3-5-sonnet-20241022)
#   Google:    <name>-<NNN>       (cf. gemini-1.5-flash-001)
#   Moonshot:  <name>-YYYY-MM-DD
#
# These pins were chosen 2026-09-27 from the adapter matrix's current
# 2026 model lineup (see docs/Adapters.md): they are the dated versions
# of the models the adapters already defaulted to. Re-verify against the
# vendor docs before each release.

PINNED_API_MODELS: dict[str, str] = {
    "openai-structured": "gpt-5.6-luna-2026-08-01",
    "anthropic-structured": "claude-sonnet-5-20260915",
    "google-structured": "gemini-3.8-flash-001",
    "moonshot-structured": "kimi-k3-2026-08-01",
}

# Old pins the vendors have retired: old ID -> replacement ID.
# get_pinned_model() fails closed on these (DeprecatedPinError naming
# the replacement) instead of handing out a dead model ID. Entries are
# never removed: old artifacts reference them.
DEPRECATED_PINS: dict[str, str] = {
    # No deprecated pins yet. Example shape when one lands:
    # "gpt-5.6-luna-2026-05-01": "gpt-5.6-luna-2026-08-01",
}


# ---------------------------------------------------------------------------
# Errors: fail closed, never guess.
# ---------------------------------------------------------------------------


class UnknownAdapterPinError(ValueError):
    """No pin registered for this adapter name.

    Raised by get_pinned_model() for an adapter the registry does not
    know. The caller must register the adapter (with a verified dated
    model ID) — silently returning an alias would make the run
    unreproducible without anyone noticing.
    """


class DeprecatedPinError(ValueError):
    """The requested pin was retired by its vendor.

    Carries the replacement pin. Callers must upgrade: a deprecated ID
    may 404 or, worse, resolve to different weights than when pinned.
    """


# ---------------------------------------------------------------------------
# Validation helpers.
# ---------------------------------------------------------------------------

# Dated/numeric version suffixes, per vendor convention.
_VERSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^.+-(\d{4}-\d{2}-\d{2})$"),  # OpenAI / Moonshot
    re.compile(r"^.+-(\d{8})$"),              # Anthropic
    re.compile(r"^.+-(\d{3})$"),              # Google
)


def _looks_like_versioned_id(model_id: Any) -> bool:
    """True when the ID carries a vendor-style version suffix.

    This is a format check, not a proof the model exists: it rejects
    obvious floating aliases (``"gpt-5.6-luna"``, ``"latest"``) while
    accepting dated IDs. Real availability is maintained by registry
    review — there is no live probe by design (stdlib-only, offline).
    """
    if not isinstance(model_id, str) or not model_id:
        return False
    return any(p.match(model_id) is not None for p in _VERSION_PATTERNS)


def validate_registry() -> None:
    """Fail fast when the registry itself is corrupt.

    Every pin must be versioned-format and none may be deprecated.
    Called at import time: a bad registry is a packaging bug and must
    be loud immediately, never discovered mid-run.
    """
    for adapter_name, pin in PINNED_API_MODELS.items():
        if not _looks_like_versioned_id(pin):
            raise ValueError(
                f"api_pins registry corrupt: pin {pin!r} for adapter "
                f"{adapter_name!r} is not a versioned model ID"
            )
        if pin in DEPRECATED_PINS:
            raise ValueError(
                f"api_pins registry corrupt: pin {pin!r} for adapter "
                f"{adapter_name!r} is marked deprecated"
            )


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def get_pinned_model(adapter_name: str) -> str:
    """Return the pinned model version for an API adapter.

    Fails closed:
    - unknown adapter name -> UnknownAdapterPinError (never guesses);
    - pin retired by the vendor -> DeprecatedPinError naming the
      replacement;
    - pin not versioned-format -> ValueError (registry corrupt).

    No network calls: the registry is the source of truth.
    """
    try:
        pin = PINNED_API_MODELS[adapter_name]
    except KeyError:
        known = sorted(PINNED_API_MODELS)
        raise UnknownAdapterPinError(
            f"no pinned model registered for adapter {adapter_name!r} "
            f"(known: {', '.join(known)}). Register a verified dated "
            "model ID in peira.api_pins.PINNED_API_MODELS first."
        ) from None
    if pin in DEPRECATED_PINS:
        raise DeprecatedPinError(
            f"pinned model {pin!r} for adapter {adapter_name!r} was "
            f"retired by its vendor; use {DEPRECATED_PINS[pin]!r} instead."
        )
    if not _looks_like_versioned_id(pin):
        raise ValueError(
            f"pinned model {pin!r} for adapter {adapter_name!r} is not "
            "a versioned model ID — the registry is corrupt."
        )
    return pin


def is_pinned_model(model_id: Any) -> bool:
    """True when the ID is exactly a current pinned model version.

    Exact match against the registry — a floating alias that merely
    *looks* dated is not pinned, and a deprecated pin is not current.
    """
    return (
        isinstance(model_id, str)
        and model_id in PINNED_API_MODELS.values()
        and model_id not in DEPRECATED_PINS
    )


def pin_status(
    adapter_name: str, model_id: Any
) -> tuple[str, str]:
    """Classify (adapter, model) for reproducibility reporting.

    Returns (status, detail) with status one of:
      "pinned"          — exactly the registry pin;
      "deprecated"      — a retired pin (upgrade required);
      "unpinned"        — anything else (floating alias or unknown ID);
      "unknown_adapter" — the adapter has no registry entry.

    Never raises: doctor and reporting paths must not crash on bad input.
    """
    try:
        pin = get_pinned_model(adapter_name)
    except UnknownAdapterPinError:
        return (
            "unknown_adapter",
            f"adapter {adapter_name!r} has no registered pin",
        )
    except (DeprecatedPinError, ValueError) as exc:
        # A corrupt or stale registry is reported, not hidden.
        return ("unpinned", str(exc))
    if isinstance(model_id, str) and model_id in DEPRECATED_PINS:
        return (
            "deprecated",
            f"model {model_id!r} was retired; use "
            f"{DEPRECATED_PINS[model_id]!r} instead",
        )
    if model_id == pin:
        return ("pinned", f"model {model_id!r} matches the registry pin")
    return (
        "unpinned",
        f"model {model_id!r} is not the pinned version "
        f"({pin!r}); runs are not reproducible",
    )


# Fail fast on a corrupt registry: this runs at import time, before any
# adapter can resolve a pin.
validate_registry()
