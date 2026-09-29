"""Pinned model pricing for cost accounting (stdlib-only).

Cost is a measurement sidecar, never a blended score: the runner fills
``cost_usd`` on every call record from this table so per-run cost figures
are reproducible and traceable. The table's ``source``, ``date``, and
``pricing_version`` are sealed into the run artifact
(``pricing_source`` / ``pricing_date`` / ``pricing_version``), so a cost
number always points at the exact table version that produced it. Runs
are never re-priced in place: a price change ships as a new table
version, and old artifacts keep their sealed numbers.

Each entry carries ``confidence``: ``"official"`` (verified against the
vendor's pricing page, or a first-party $0.0 assertion for self-hosted
checkpoints) or ``"secondary"`` (carried over unverified or
gateway-reported). The dashboard labels secondary-sourced prices; it
never treats them as official.

An unknown model prices at 0.0 — cost is then explicitly unaccounted,
never silently wrong.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from peira._rust import _impl as _rust

_TABLE_PATH = Path(__file__).parent / "data" / "pricing.json"

#: Allowed per-entry pricing confidence values.
PRICING_CONFIDENCES = ("official", "secondary")


@functools.lru_cache(maxsize=1)
def load_pricing_table() -> dict[str, Any]:
    """Load and minimally validate the pinned pricing table.

    The table is pinned package data — it never changes at runtime —
    so the parsed result is cached (one JSON parse per process, not
    per ``summarize()`` call). Callers that need a different table
    pass it explicitly (e.g. ``cost_summary(..., pricing_table=...)``);
    the cache never interferes with an explicit table.

    Raises RuntimeError (not ValueError: this is a packaging/installation
    bug, not a user input problem) when the table is missing or corrupt.
    """
    try:
        table = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        raise RuntimeError(
            f"peira pricing table is missing or unreadable: {_TABLE_PATH} ({e})"
        ) from e
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"peira pricing table is corrupt: {_TABLE_PATH} ({e})"
        ) from e
    if not isinstance(table, dict) or not isinstance(table.get("models"), dict):
        raise RuntimeError(
            f"peira pricing table has the wrong shape: {_TABLE_PATH} "
            "(need an object with a 'models' object)"
        )
    version = table.get("pricing_version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(
            f"peira pricing table is missing 'pricing_version': {_TABLE_PATH} "
            "(every table version must be machine-identifiable)"
        )
    for model, entry in table["models"].items():
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"peira pricing table entry {model!r} is not an object: "
                f"{_TABLE_PATH}"
            )
        confidence = entry.get("confidence")
        if confidence not in PRICING_CONFIDENCES:
            raise RuntimeError(
                f"peira pricing table entry {model!r} has bad "
                f"'confidence' {confidence!r}: {_TABLE_PATH} "
                f"(need one of {PRICING_CONFIDENCES})"
            )
    return table


def pricing_confidence(
    model: str,
    table: dict[str, Any] | None = None,
) -> str | None:
    """Pricing confidence for one model: "official", "secondary", or None.

    None means the model is not in the table (unpriced), distinct from
    a secondary-sourced price. Callers that need a different table pass
    it explicitly; the default is the pinned package table.
    """
    table = table if table is not None else load_pricing_table()
    entry = table["models"].get(model)
    if entry is None:
        return None
    return str(entry["confidence"])


def cost_usd_py(
    model: str,
    tokens_in: int,
    tokens_out: int,
    table: dict[str, Any] | None = None,
) -> float:
    """Reference implementation of :func:`cost_usd` (pure Python).

    List-price cost of one call in USD.

    Unknown models cost 0.0: cost is then explicitly unaccounted rather
    than silently estimated. Negative token counts are a caller bug and
    raise ValueError.
    """
    if tokens_in < 0 or tokens_out < 0:
        raise ValueError(
            f"token counts must be non-negative, got in={tokens_in} out={tokens_out}"
        )
    table = table if table is not None else load_pricing_table()
    entry = table["models"].get(model)
    if entry is None:
        return 0.0
    # Per-call billing (e.g. guardrail APIs like Lakera Guard): the
    # entry carries usd_per_call instead of per-token rates, and one
    # call costs that flat rate regardless of token counts.
    per_call = entry.get("usd_per_call")
    if isinstance(per_call, (int, float)) and not isinstance(per_call, bool):
        return float(per_call)
    return (
        tokens_in / 1_000_000 * float(entry["usd_per_1m_in"])
        + tokens_out / 1_000_000 * float(entry["usd_per_1m_out"])
    )


def cost_usd(
    model: str,
    tokens_in: int,
    tokens_out: int,
    table: dict[str, Any] | None = None,
) -> float:
    """List-price cost of one call in USD.

    Unknown models cost 0.0: cost is then explicitly unaccounted rather
    than silently estimated. Negative token counts are a caller bug and
    raise ValueError.

    Dispatches to the Rust core when available (the table itself is
    loaded here in Python — package-data I/O stays out of Rust); the
    pure-Python :func:`cost_usd_py` is the reference and the fallback.
    """
    if table is None:
        table = load_pricing_table()
    if _rust is not None:
        try:
            return _rust.pricing_cost_usd(model, tokens_in, tokens_out, table)
        except (TypeError, ValueError, OverflowError):
            pass
    return cost_usd_py(model, tokens_in, tokens_out, table)
