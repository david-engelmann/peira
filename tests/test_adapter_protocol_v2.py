"""Tests for the adapter protocol v2 (CaseContext, typed RunSummary,
keyword-only run_suite, Windows-safe artifact filenames).

Protocol v2 changes the adapter contract from
``decide(case_input: dict, primitive: str)`` to
``decide(ctx: CaseContext)``. The context carries everything an adapter
may see — and structurally excludes gold labels.
"""
import dataclasses

import pytest

from peira.adapters.base import CaseContext, ChoiceOutput
from peira.cli import sanitize_filename_stem
from peira.runner import (
    RunSummary,
    summarize,
    run_suite,
)
from peira.metrics import PerCaseResult
from peira.schema import AttackedVariant, BenignVariant, Case


def make_ctx(**overrides):
    kwargs = dict(
        case_id="c-001",
        primitive="choice",
        input={"prompt": "p", "options": ["approve", "deny"]},
        attacked=False,
        variant="benign",
    )
    kwargs.update(overrides)
    return CaseContext(**kwargs)


# ------------------------------------------------------------------
# CaseContext validation
# ------------------------------------------------------------------
def test_valid_benign_context():
    ctx = make_ctx()
    assert ctx.case_id == "c-001"
    assert ctx.primitive == "choice"
    assert ctx.input == {"prompt": "p", "options": ["approve", "deny"]}
    assert ctx.attacked is False
    assert ctx.variant == "benign"


def test_valid_attacked_context():
    ctx = make_ctx(attacked=True, variant="attacked")
    assert ctx.attacked is True
    assert ctx.variant == "attacked"


def test_context_is_frozen():
    ctx = make_ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.primitive = "score"  # type: ignore[misc]


def test_gold_labels_structurally_absent():
    """Audit C1: there is no field a gold label could leak through."""
    fields = {f.name for f in dataclasses.fields(CaseContext)}
    assert fields == {"case_id", "primitive", "input", "attacked", "variant"}
    for leaked in ("expected_decision", "expected_score", "target_decision"):
        assert leaked not in fields


def test_invalid_primitive_rejected():
    with pytest.raises(ValueError, match="unknown primitive"):
        make_ctx(primitive="bogus")


def test_all_valid_primitives_accepted():
    for prim in ("choice", "score", "abstain"):
        assert make_ctx(primitive=prim).primitive == prim


def test_invalid_variant_rejected():
    with pytest.raises(ValueError, match="unknown variant"):
        make_ctx(variant="sneaky")


def test_attacked_variant_disagreement_rejected():
    with pytest.raises(ValueError, match="disagrees"):
        make_ctx(attacked=True, variant="benign")
    with pytest.raises(ValueError, match="disagrees"):
        make_ctx(attacked=False, variant="attacked")


# ------------------------------------------------------------------
# Wire format: byte-compatible with the pre-v2 runner
# ------------------------------------------------------------------
def test_to_wire_benign_matches_old_shape():
    wire = make_ctx().to_wire()
    assert wire == {
        "case": {
            "prompt": "p",
            "options": ["approve", "deny"],
            "case_id": "c-001",
        },
        "primitive": "choice",
    }
    assert "attacked" not in wire["case"]


def test_to_wire_attacked_matches_old_shape():
    wire = make_ctx(attacked=True, variant="attacked").to_wire()
    assert wire["case"]["attacked"] is True
    assert wire["case"]["case_id"] == "c-001"
    assert wire["primitive"] == "choice"


def test_to_wire_does_not_mutate_context_input():
    ctx = make_ctx()
    before = dict(ctx.input)
    ctx.to_wire()
    assert ctx.input == before


# ------------------------------------------------------------------
# run_case hands the adapter a CaseContext (never raw dicts)
# ------------------------------------------------------------------
class RecordingAdapter:
    name = "recording"
    version = "1.0"
    supported_primitives = frozenset({"choice"})
    instances = []

    def __init__(self):
        self.seen = []
        RecordingAdapter.instances.append(self)

    def decide(self, ctx):
        self.seen.append(ctx)
        return ChoiceOutput(decision="approve", confidence=0.9)


def make_choice_case(case_id="v2-001"):
    return Case(
        case_id=case_id,
        family="state_poisoning",
        primitive="choice",
        severity="high",
        benign=BenignVariant(
            input={"prompt": "p", "options": ["approve", "deny"]},
            expected_decision="approve",
        ),
        attacked=AttackedVariant(
            input={"prompt": "p!", "options": ["approve", "deny"]},
            target_decision="deny",
        ),
    )


def test_run_case_passes_case_context_to_adapter():
    from peira.runner import run_case

    adapter = RecordingAdapter()
    run_case(adapter, make_choice_case())
    assert len(adapter.seen) == 2
    benign_ctx, attacked_ctx = adapter.seen
    assert isinstance(benign_ctx, CaseContext)
    assert isinstance(attacked_ctx, CaseContext)
    assert (benign_ctx.attacked, benign_ctx.variant) == (False, "benign")
    assert (attacked_ctx.attacked, attacked_ctx.variant) == (True, "attacked")
    assert benign_ctx.case_id == attacked_ctx.case_id == "v2-001"
    # The adapter sees variant inputs, never gold labels.
    assert benign_ctx.input["prompt"] == "p"
    assert attacked_ctx.input["prompt"] == "p!"


# ------------------------------------------------------------------
# run_suite: keyword-only after (adapter, cases)
# ------------------------------------------------------------------
def test_run_suite_refuses_positional_suite_and_version():
    cases = [make_choice_case()]
    with pytest.raises(TypeError):
        run_suite(RecordingAdapter(), cases, "trial-demo", "0.1.0-demo")  # type: ignore[misc]


def test_run_suite_keyword_call_still_works():
    cases = [make_choice_case()]
    artifact = run_suite(
        RecordingAdapter(), cases, suite="trial-demo", dataset_version="0.1.0-demo"
    )
    assert artifact.metrics["n_cases"] == 1


# ------------------------------------------------------------------
# RunSummary.to_dict() preserves the artifact metrics shape
# ------------------------------------------------------------------
def test_run_summary_to_dict_matches_metrics_shape():
    results = [
        PerCaseResult(
            case_id="c1", family="f", primitive="choice",
            benign_correct=True, attacked_flipped=False,
            attacked_targeted=False, malformed=False, confidence=0.9,
        ),
        PerCaseResult(
            case_id="c2", family="f", primitive="choice",
            benign_correct=False, attacked_flipped=True,
            attacked_targeted=True, malformed=False, confidence=0.4,
        ),
    ]
    summary = summarize(results)
    assert isinstance(summary, RunSummary)
    d = summary.to_dict()
    # Exact key set of the pre-v2 metrics dict (byte-stable artifact format).
    assert set(d.keys()) == {
        "n_cases", "n_scored", "n_skipped", "primitive_coverage",
        "asr_conditional", "asr_ci95", "benign_accuracy",
        "benign_accuracy_ci95", "malformed_rate", "abstention_rate",
        "abstention_flip_rate", "ranking_eligible", "eligibility_notes",
        "per_family", "score_calibration",
    }
    assert d["n_cases"] == 2
    assert d["n_scored"] == 2
    assert d["n_skipped"] == 0
    assert d["primitive_coverage"] == {
        "choice": {"n_cases": 2, "n_scored": 2, "n_skipped": 0}
    }
    assert isinstance(d["asr_ci95"], list) and len(d["asr_ci95"]) == 2
    assert isinstance(d["benign_accuracy_ci95"], list)
    assert isinstance(d["eligibility_notes"], list)
    assert d["per_family"]["f"]["n"] == 2
    assert set(d["per_family"]["f"].keys()) == {"n", "asr", "asr_ci95"}
    assert d["score_calibration"] is None  # no score cases here


def test_run_summary_nested_types():
    results = [
        PerCaseResult(
            case_id="c1", family="f", primitive="choice",
            benign_correct=True, attacked_flipped=False,
            attacked_targeted=False, malformed=False, confidence=0.9,
        ),
    ]
    summary = summarize(results)
    assert summary.n_cases == 1
    assert summary.primitive_coverage["choice"].n_scored == 1
    assert summary.per_family["f"].n == 1
    assert isinstance(summary.asr_ci95, tuple)
    assert isinstance(summary.eligibility_notes, tuple)
    assert summary.score_calibration is None


# ------------------------------------------------------------------
# Windows-safe artifact filenames
# ------------------------------------------------------------------
def test_sanitize_colon_from_dotted_adapter_path():
    stem = sanitize_filename_stem("my_adapter:MyGuardrail-trial-demo")
    assert stem == "my_adapter_MyGuardrail-trial-demo"
    assert ":" not in stem


def test_sanitize_all_windows_illegal_chars():
    stem = sanitize_filename_stem('a<b>c"d/e\\f|g?h*i-trial')
    assert stem == "a_b_c_d_e_f_g_h_i-trial"
    for ch in '<>:"/\\|?*':
        assert ch not in stem


def test_sanitize_collapses_repeats_and_strips_dots():
    assert sanitize_filename_stem("a:::b") == "a_b"
    assert sanitize_filename_stem("...a...") == "a"


def test_sanitize_kills_path_traversal():
    stem = sanitize_filename_stem("../../etc/passwd-trial")
    assert "/" not in stem and "\\" not in stem
    assert ".." not in stem


def test_sanitize_empty_stem_raises():
    with pytest.raises(ValueError, match="no usable filename characters"):
        sanitize_filename_stem(":::")


def test_sanitize_keeps_legal_names_unchanged():
    assert sanitize_filename_stem("mock-trial-demo") == "mock-trial-demo"
