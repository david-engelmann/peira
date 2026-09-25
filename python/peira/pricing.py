"""Pinned model pricing for cost accounting (stdlib-only).

Cost is a measurement sidecar, never a blended score: the runner fills
``cost_usd`` on every call record from this table so per-run cost figures
are reproducible and traceable. The table's ``source`` and ``date`` are
sealed into the run artifact (``pricing_source`` / ``pricing_date``), so a
cost number always points at the table that produced it.

An unknown model prices at 0.0 — cost is then explicitly unaccounted,
never silently wrong.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

_TABLE_PATH = Path(__file__).parent / "data" / "pricing.json"


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
    return table


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
    """
    if tokens_in < 0 or tokens_out < 0:
        raise ValueError(
            f"token counts must be non-negative, got in={tokens_in} out={tokens_out}"
        )
    table = table if table is not None else load_pricing_table()
    entry = table["models"].get(model)
    if entry is None:
        return 0.0
    return (
        tokens_in / 1_000_000 * float(entry["usd_per_1m_in"])
        + tokens_out / 1_000_000 * float(entry["usd_per_1m_out"])
    )
