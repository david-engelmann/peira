"""peira: the empirical trial for decision models."""

__version__ = "0.1.0"

from peira.adapters.base import (
    AdapterOutput,
    BaseAdapter,
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
    validate_output,
)
from peira.runner import (
    PerFamilySummary,
    PrimitiveCoverage,
    RunSummary,
    ScoreCalibration,
)
from peira.schema import AttackedVariant, BenignVariant, Case

__all__ = [
    "AdapterOutput",
    "AttackedVariant",
    "BaseAdapter",
    "BenignVariant",
    "Case",
    "CaseContext",
    "ChoiceOutput",
    "AbstainOutput",
    "PerFamilySummary",
    "PrimitiveCoverage",
    "RunSummary",
    "ScoreCalibration",
    "ScoreOutput",
    "__version__",
    "validate_output",
]
