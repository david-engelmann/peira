"""Combination-attack (combo) evaluation suite: schema, gates, metrics.

The combo suite is a SEPARATE suite, not a v1/v2 family: it measures
interaction effects between attack-family pairs with a 2x2 factorial
design (control, A-only, B-only, A+B arms per substrate). See
``python/peira/combo_schema.py`` for the case format,
``python/peira/combo_gates.py`` for the authoring gates, and
``python/peira/combo_metrics.py`` for the paired interaction contrast.

Combo results are never blended with the paired single-decision v1/v2
numbers.
"""

from peira.combo_gates import (
    COMBO_GATES,
    ComboGateResult,
    gate_cg1_schema,
    gate_cg2_arm_completeness,
    gate_cg3_pair_separation,
    gate_cg4_with_corpus,
    gate_cg5_near_dedup,
    run_combo_gates,
)
from peira.combo_metrics import (
    InteractionResult,
    format_interaction,
    paired_interaction,
)
from peira.combo_schema import (
    COMBO_ARMS,
    COMBO_HYPOTHESIS,
    COMBO_PAIRS,
    COMBO_PRIMARY_OUTCOME,
    COMBO_PRIMARY_OUTCOMES,
    COMBO_SUITE_ID,
    ComboCase,
    combo_case_id,
    combo_pair_id,
    load_combo_cases,
    parse_combo_case_id,
    validate_combo_dict,
)

__all__ = [
    "COMBO_ARMS",
    "COMBO_GATES",
    "COMBO_HYPOTHESIS",
    "COMBO_PAIRS",
    "COMBO_PRIMARY_OUTCOME",
    "COMBO_PRIMARY_OUTCOMES",
    "COMBO_SUITE_ID",
    "ComboCase",
    "ComboGateResult",
    "InteractionResult",
    "combo_case_id",
    "combo_pair_id",
    "format_interaction",
    "gate_cg1_schema",
    "gate_cg2_arm_completeness",
    "gate_cg3_pair_separation",
    "gate_cg4_with_corpus",
    "gate_cg5_near_dedup",
    "load_combo_cases",
    "paired_interaction",
    "parse_combo_case_id",
    "run_combo_gates",
    "validate_combo_dict",
]
