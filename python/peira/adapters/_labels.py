"""Shared decision-label helpers for adapters (B2).

Under B2 (D-25 amended) the adapter-visible ``CallContext`` carries no
trial bookkeeping — no case id, no arm, no gold labels. Adapters that
need a per-call candidate label set (constrained LLM enums, Jev-family
choice criteria) build it from the case input's explicit ``options``
list instead. This module holds that logic once so the Jev-family
adapters (jev, laya, semif) and the generic LLM adapter share one
implementation instead of three diverging copies.

Two labels are always available beyond the case's own options:

- ``"other"``: the model can always answer outside the listed
  vocabulary ("none of the listed options is the correct decision").
  Every adapter that presents a closed label set includes it.
- ``"abstain"`` (abstain primitive only): a deliberate abstention is a
  legal *decision* label on the abstain primitive (``abstained`` stays
  ``False``). A provider refusal is a different thing and is reported
  via ``abstained=True``.

The result is sorted and deduplicated so the label order is
deterministic for a given case input, independent of dataset key order.
"""

from __future__ import annotations

from typing import Any

#: Placeholder decision for abstain-primitive adapters whose model
#: answered "should I abstain?" with no. The model never emitted a
#: decision label, so the placeholder must not be gold-derived — and
#: under B2 there is no gold to derive it from anyway. Flip detection
#: keys off the ``abstained`` flag, not this placeholder.
NON_ABSTAIN_PLACEHOLDER = "other"


def candidate_labels(
    case_input: dict[str, Any], primitive: str
) -> list[str]:
    """Sorted, deduplicated candidate labels from the input's options.

    ``case_input["options"]`` is the case's explicit, non-empty option
    list (required by the v1 case schema on both arms). Non-string or
    empty entries are ignored defensively; the schema guarantees they
    never occur in real cases.
    """
    options = case_input.get("options")
    labels: set[str] = set()
    if isinstance(options, list):
        for option in options:
            if isinstance(option, str) and option:
                labels.add(option)
    if primitive == "abstain":
        labels.add("abstain")
    labels.add(NON_ABSTAIN_PLACEHOLDER)
    return sorted(labels)


def non_abstain_placeholder() -> str:
    """The decision placeholder when an abstain-primitive call does not
    abstain.

    The model answered "should I abstain?" with no — it never emitted a
    decision label. Returning ``"other"`` keeps the placeholder honest:
    it is not a claim about the correct decision, just a marker that a
    decision-shaped output was produced. Flip detection uses the
    ``abstained`` flag.
    """
    return NON_ABSTAIN_PLACEHOLDER
