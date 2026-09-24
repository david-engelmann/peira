"""Slot-substitution probes for peira (stdlib-only).

Generate surface-form variants of a case (same decision semantics,
different names/amounts/dates) and measure whether an adapter's decision
is invariant across them. See ``docs/Holdout-Ranking-Design.md`` for how
probes fit the anti-gaming pipeline.
"""

from peira.probes.invariance import InvarianceReport, invariance_report
from peira.probes.slots import (
    SLOT_KINDS,
    ProbeVariant,
    SlotSpec,
    Substitution,
    generate_variants,
)

__all__ = [
    "SLOT_KINDS",
    "InvarianceReport",
    "ProbeVariant",
    "SlotSpec",
    "Substitution",
    "generate_variants",
    "invariance_report",
]
