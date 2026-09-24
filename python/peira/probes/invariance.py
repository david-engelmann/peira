"""Variant-flip rate: the reported metric for slot-substitution probes.

Run the adapter on the original case and on ``n`` slot-substituted
variants (see :mod:`peira.probes.slots`); the flip rate is the fraction of
variants whose decision differs from the original case's decision. A
decision model doing its job shouldn't change its verdict because
``"Acme Corp"`` became ``"Globex Inc"`` — a high flip rate is consistent
with surface memorization of the public case text, which is exactly what
the private holdout exists to re-test (see ``docs/Holdout-OpSec.md``).

This helper is pure: it takes decision strings, not adapters. Running the
adapter is the harness's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class InvarianceReport:
    """Flip-rate summary for one case's variant set."""

    baseline: str  # decision on the original (unsubstituted) case
    n_variants: int
    n_flips: int
    flip_rate: float  # n_flips / n_variants, in [0, 1]
    flipped_indices: tuple[int, ...]  # positions in variant_decisions


def invariance_report(
    baseline_decision: str, variant_decisions: Sequence[str]
) -> InvarianceReport:
    """Compare variant decisions against the baseline decision.

    A flip is any decision string inequality — including a variant that
    abstains (``""``) where the baseline decided, or vice versa: for a
    decision model, refusing where it previously decided *is* a
    behavioral change.

    Raises:
        ValueError: if ``variant_decisions`` is empty. An empty variant
            set measures nothing; fail loudly instead of reporting 0.0.
    """
    decisions = tuple(variant_decisions)
    if not decisions:
        raise ValueError("variant_decisions must be non-empty")
    flipped = tuple(i for i, d in enumerate(decisions) if d != baseline_decision)
    return InvarianceReport(
        baseline=baseline_decision,
        n_variants=len(decisions),
        n_flips=len(flipped),
        flip_rate=len(flipped) / len(decisions),
        flipped_indices=flipped,
    )
