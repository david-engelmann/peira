"""Pinned model versions for API adapters (execution methodology, Layer 3: Adapter).

API adapters measure models the vendors can change behind the scenes, so
the benchmark pins the exact model ID each API adapter uses by default:
the same discipline the HF adapters apply to ``hf_revision``, adapted to
each vendor's actual versioning scheme (re-verified 2026-09-27 against
the vendor docs linked below).

Per-vendor schemes:
- OpenAI: ``gpt-5.6-luna`` (https://developers.openai.com/api/docs/models/gpt-5.6-luna).
  Luna has NO snapshot mechanism: no dated snapshots exist (GA was
  2026-07-09), so the bare ID is the only ID. The pin is therefore
  best-effort: the registry records the exact ID and the runner seals it
  into the run artifact, but if OpenAI swaps the weights behind the
  name, the fail-closed machinery cannot detect it. Honest about the
  limit.
- Anthropic: ``claude-sonnet-5`` (https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).
  From the 4.6 generation onward the dateless ID IS the pinned snapshot
  by vendor guarantee: weights and configuration stay fixed for the life
  of the ID, and updates ship under new IDs. This strengthens the story:
  the pin is as strong as a dated one.
- Google: ``gemini-3.8-flash`` (https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
  The stable model code. The ``-001`` suffix is the 1.5/2.0-era
  convention and is not used for 3.x.
- Moonshot: ``kimi-k3`` (https://platform.kimi.ai/docs/guide/kimi-k3-quickstart).
  Moonshot never published dated IDs; the quickstart examples all use
  ``kimi-k3``.

This module is the single source of truth for those pins. It is
stdlib-only (the base ``peira`` tier has zero third-party runtime
dependencies) and makes no network calls: pin validity is maintained by
review, not probed live. ``peira doctor`` warns when an API adapter's
default model is not the pinned version, and the runner seals the
resolved ``adapter_version`` into the run artifact's analysis lock, so a
pinned run is reproducible and an unpinned run is visibly marked by its
version string.

Registry maintenance: when a vendor ships a new model ID, update
``PINNED_API_MODELS`` in a PR and add the old ID to ``DEPRECATED_PINS``
with its replacement. Never delete a deprecated entry outright: old
artifacts name the old ID, and the registry must keep explaining them.
Re-verify every pin against the vendor docs before each release.
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
# Pins are the vendors' own canonical IDs, not invented dated variants:
#   OpenAI:    gpt-5.6-luna        (bare; Luna has no snapshot mechanism)
#   Anthropic: claude-sonnet-5     (dateless; pinned snapshot by vendor
#                                   guarantee from the 4.6 generation on)
#   Google:    gemini-3.8-flash    (stable model code; no -NNN suffix on 3.x)
#   Moonshot:  kimi-k3             (Moonshot never published dated IDs)
#
# These pins were verified 2026-09-27 against the vendor docs linked in
# the module docstring. Re-verify against the vendor docs before each
# release. Pricing rates for these IDs live in
# python/peira/data/pricing.json under the same IDs.

PINNED_API_MODELS: dict[str, str] = {
    "openai-structured": "gpt-5.6-luna",
    "anthropic-structured": "claude-sonnet-5",
    "google-structured": "gemini-3.8-flash",
    "moonshot-structured": "kimi-k3",
}

# Old pins the vendors have retired: old ID -> replacement ID.
# get_pinned_model() fails closed on these (DeprecatedPinError naming
# the replacement) instead of handing out a dead model ID. Entries are
# never removed: old artifacts reference them.
DEPRECATED_PINS: dict[str, str] = {
    # No deprecated pins yet. Example shape when one lands:
    # "claude-sonnet-4-5-20250929": "claude-sonnet-5",
}


# ---------------------------------------------------------------------------
# Errors: fail closed, never guess.
# ---------------------------------------------------------------------------


class UnknownAdapterPinError(ValueError):
    """No pin registered for this adapter name.

    Raised by get_pinned_model() for an adapter the registry does not
    know. The caller must register the adapter (with a verified model
    ID). Silently returning an alias would make the run
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

# Per-vendor model-ID formats, from the vendor docs (re-verified
# 2026-09-27; see the module docstring for links). The validator is a
# format check, not a proof of existence: pin validity is maintained by
# review, never probed live (stdlib-only, offline by design).
#
# Acceptance rule per vendor:
#   openai:    gpt-<version>-<name>, optionally with the legacy dated
#              suffix (cf. gpt-4o-2024-08-06). Note the dated form is
#              accepted for format only: no dated Luna ID has ever
#              existed, so a dated Luna ID in the registry is a review
#              failure, not a validator failure.
#   anthropic: claude-<tier>-<n>[-<m>] dateless (4.6 generation onward;
#              pinned snapshots by vendor guarantee), or the pre-4.6
#              dated form claude-<tier>-<m>-YYYYMMDD (kept so retired
#              pins can be recorded in DEPRECATED_PINS).
#   google:    gemini-<major>.<minor>-<name> (3.x carries no -NNN
#              suffix). The legacy -NNN form is still accepted so
#              retired 1.5/2.0-era pins can be recorded.
#   moonshot:  kimi-k<n> (Moonshot never published dated IDs, so any
#              dated suffix is rejected as malformed).
_VENDOR_ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai": re.compile(r"^gpt-[0-9][a-z0-9]*(\.\d+)?(-[a-z0-9]+)*(-\d{4}-\d{2}-\d{2})?$"),
    "anthropic": re.compile(r"^claude-[a-z]+(-\d+)+(-\d{8})?$"),
    "google": re.compile(r"^gemini-\d+(\.\d+)?-[a-z]+(-\d{3})?$"),
    "moonshot": re.compile(r"^kimi-k\d+[a-z]?(-[a-z]+)?$"),
}


def _looks_like_pinned_id(adapter_name: Any, model_id: Any) -> bool:
    """True when the ID matches its vendor's real ID format.

    The vendor is taken from the adapter name (``"openai-structured"``
    -> ``"openai"``). Unknown vendors fail closed: an ID for a vendor
    the registry does not know is never "probably fine".
    """
    if not isinstance(adapter_name, str) or not adapter_name:
        return False
    if not isinstance(model_id, str) or not model_id:
        return False
    vendor = adapter_name.split("-")[0]
    pattern = _VENDOR_ID_PATTERNS.get(vendor)
    if pattern is None:
        return False
    return pattern.match(model_id) is not None


def _looks_like_any_vendor_id(model_id: Any) -> bool:
    """True when the ID matches at least one vendor's ID format.

    Used for DEPRECATED_PINS entries, which name retired IDs without an
    adapter context: the key must at least look like a real model ID
    some vendor shipped, not a typo or a placeholder.
    """
    if not isinstance(model_id, str) or not model_id:
        return False
    return any(p.match(model_id) is not None for p in _VENDOR_ID_PATTERNS.values())


def validate_registry() -> None:
    """Fail fast when the registry itself is corrupt.

    Every pin must match its vendor's ID format, no pin may be
    deprecated, and every deprecated entry must name plausible
    vendor-format IDs on both sides. Called at import time: a bad
    registry is a packaging bug and must be loud immediately, never
    discovered mid-run.
    """
    for adapter_name, pin in PINNED_API_MODELS.items():
        if not _looks_like_pinned_id(adapter_name, pin):
            raise ValueError(
                f"api_pins registry corrupt: pin {pin!r} for adapter "
                f"{adapter_name!r} does not match the vendor's model ID format"
            )
        if pin in DEPRECATED_PINS:
            raise ValueError(
                f"api_pins registry corrupt: pin {pin!r} for adapter "
                f"{adapter_name!r} is marked deprecated"
            )
    for old_id, new_id in DEPRECATED_PINS.items():
        if not _looks_like_any_vendor_id(old_id):
            raise ValueError(
                f"api_pins registry corrupt: deprecated pin {old_id!r} "
                "does not match any vendor's model ID format"
            )
        if not _looks_like_any_vendor_id(new_id):
            raise ValueError(
                f"api_pins registry corrupt: replacement pin {new_id!r} "
                "does not match any vendor's model ID format"
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
    - pin not matching its vendor's ID format -> ValueError
      (registry corrupt).

    No network calls: the registry is the source of truth.
    """
    try:
        pin = PINNED_API_MODELS[adapter_name]
    except KeyError:
        known = sorted(PINNED_API_MODELS)
        raise UnknownAdapterPinError(
            f"no pinned model registered for adapter {adapter_name!r} "
            f"(known: {', '.join(known)}). Register a verified model "
            "ID in peira.api_pins.PINNED_API_MODELS first."
        ) from None
    if pin in DEPRECATED_PINS:
        raise DeprecatedPinError(
            f"pinned model {pin!r} for adapter {adapter_name!r} was "
            f"retired by its vendor; use {DEPRECATED_PINS[pin]!r} instead."
        )
    if not _looks_like_pinned_id(adapter_name, pin):
        raise ValueError(
            f"pinned model {pin!r} for adapter {adapter_name!r} does not "
            "match the vendor's model ID format: the registry is corrupt."
        )
    return pin


def is_pinned_model(model_id: Any) -> bool:
    """True when the ID is exactly a current pinned model version.

    Exact match against the registry: a different model ID, however
    plausible-looking, is not pinned, and a deprecated pin is not
    current.
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
      "pinned":          exactly the registry pin;
      "deprecated":      a retired pin (upgrade required);
      "unpinned":        anything else (a different model ID or unknown ID);
      "unknown_adapter": the adapter has no registry entry.

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
