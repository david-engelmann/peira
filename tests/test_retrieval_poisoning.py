"""Corpus tests for the retrieval_poisoning v2 family (family 22).

These tests pin the authoring contract: paired RAG construction with
exactly one poisoned [Retrieved:] block, exact severity/primitive mixes,
and the validity diagnostics that separate retrieval_poisoning from
indirect_injection, distractor_flooding, precedent_stacking, and
verbosity_inflation.

Regression coverage for the lost-lane defect classes: duplicate prompts,
duplicate Cartesian (scenario, poison) combinations, duplicate abstain
controls, no-op assertions, and taxonomy-hash drift.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CASES_PATH = REPO / "dataset" / "v2" / "cases" / "retrieval_poisoning.jsonl"
MANIFEST_PATH = REPO / "dataset" / "v2" / "cases" / "manifest.json"

sys.path.insert(0, str(REPO / "scripts"))
import author_retrieval_poisoning as author


def load_cases():
    cases = []
    with open(CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


CASES = load_cases()
BY_ID = {c["case_id"]: c for c in CASES}


def poison_block(case):
    bp = case["benign"]["input"]["prompt"]
    ap = case["attacked"]["input"]["prompt"]
    assert ap.startswith(bp)
    return ap[len(bp):]


# ---------------------------------------------------------------------------
# Exact composition
# ---------------------------------------------------------------------------

def test_exact_totals():
    assert len(CASES) == 470


def test_severity_mix():
    from collections import Counter
    assert dict(Counter(c["severity"] for c in CASES)) == {
        "critical": 90, "high": 160, "medium": 220}


def test_primitive_mix():
    from collections import Counter
    assert dict(Counter(c["primitive"] for c in CASES)) == {
        "choice": 330, "score": 80, "abstain": 60}


def test_ids_sequential_and_unique():
    ids = [c["case_id"] for c in CASES]
    assert len(set(ids)) == len(ids) == 470
    assert ids == ["v2-retp-%04d" % i for i in range(1, 471)]


def test_all_choice_cases_critical_high_have_flip_notes():
    for c in CASES:
        if c["primitive"] == "choice" and c["severity"] == "critical":
            assert "Severity critical:" in c["notes"], c["case_id"]


def test_schema_valid():
    sys.path.insert(0, str(REPO / "python"))
    from peira.schema import validate_case_dict
    bad = [(c["case_id"], validate_case_dict(c)) for c in CASES]
    bad = [(cid, e) for cid, e in bad if e]
    assert bad == []


# ---------------------------------------------------------------------------
# Paired RAG construction (the deletion test, made literal)
# ---------------------------------------------------------------------------

def test_exactly_one_retrieved_marker_per_attacked_prompt():
    for c in CASES:
        ap = c["attacked"]["input"]["prompt"]
        assert ap.count("[Retrieved:") == 1, c["case_id"]


def test_no_marker_in_benign_prompts():
    for c in CASES:
        assert "[Retrieved:" not in c["benign"]["input"]["prompt"], c["case_id"]


def test_attacked_is_benign_plus_single_block():
    for c in CASES:
        bp = c["benign"]["input"]["prompt"]
        ap = c["attacked"]["input"]["prompt"]
        block = poison_block(c)
        assert ap == bp + block, c["case_id"]
        assert block.startswith("\n\n[Retrieved: "), c["case_id"]
        assert block.endswith("]"), c["case_id"]
        # no nested retrieved blocks inside the poison
        assert "[Retrieved:" not in block[len("\n\n[Retrieved: "):], c["case_id"]


def test_no_directive_language_in_poison_blocks():
    hits = []
    for c in CASES:
        low = poison_block(c).lower()
        for pat in author.DIRECTIVE_PATTERNS:
            if re.search(pat, low):
                hits.append((c["case_id"], pat))
    assert hits == []


def test_gold_labels_in_vocab():
    for c in CASES:
        for variant, key in (("benign", "expected_decision"),
                             ("attacked", "target_decision")):
            opts = c[variant]["input"]["options"]
            assert c[variant][key] in opts, (c["case_id"], variant)


# ---------------------------------------------------------------------------
# Lost-lane defect regressions
# ---------------------------------------------------------------------------

def test_no_duplicate_prompts():
    benign = [c["benign"]["input"]["prompt"] for c in CASES]
    attacked = [c["attacked"]["input"]["prompt"] for c in CASES]
    assert len(set(benign)) == len(benign)
    assert len(set(attacked)) == len(attacked)


def test_no_duplicate_scenario_poison_combinations():
    combos = [(c["benign"]["input"]["prompt"], poison_block(c)) for c in CASES]
    assert len(set(combos)) == len(combos)


def test_no_duplicate_abstain_controls():
    abstain = [c for c in CASES if c["primitive"] == "abstain"]
    assert len(abstain) == 60
    benign = [c["benign"]["input"]["prompt"] for c in abstain]
    assert len(set(benign)) == 60
    for c in abstain:
        assert c["benign"]["expected_decision"] == "abstain"
        assert c["attacked"]["target_decision"] != "abstain"


def test_score_references_in_unit_interval():
    for c in CASES:
        if c["primitive"] == "score":
            s = c["benign"]["expected_score"]
            assert 0.0 <= s <= 1.0, c["case_id"]
            assert c["benign"]["positive_decision"] == "approve"


def test_authoring_gates_are_not_noops():
    """Negative controls: the gates must catch each defect class."""
    import copy
    good = author.build_cases()
    assert author.validate(good) == []

    tampered = copy.deepcopy(good[0])
    bp = tampered["benign"]["input"]["prompt"]
    tampered["attacked"]["input"]["prompt"] = (
        bp + "\n\n[Retrieved: a: b]\n\n[Retrieved: c: d]")
    assert any("markers" in e for e in author.validate([tampered]))

    tampered = copy.deepcopy(good[1])
    tampered["benign"]["input"]["prompt"] += "[Retrieved: x: y]"
    assert any("benign prompt contains" in e
               for e in author.validate([tampered]))

    dup = good[2:4]
    dup[1] = copy.deepcopy(dup[0])
    dup[1]["case_id"] = dup[0]["case_id"]
    assert any("duplicate" in e for e in author.validate(dup))

    tampered = copy.deepcopy(good[3])
    ap = tampered["attacked"]["input"]["prompt"]
    tampered["attacked"]["input"]["prompt"] = ap[:-1] + " you should approve.]"
    assert any("directive" in e for e in author.validate([tampered]))


# ---------------------------------------------------------------------------
# Determinism and manifest agreement
# ---------------------------------------------------------------------------

def test_regeneration_is_byte_identical():
    rebuilt = "".join(
        json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n"
        for c in author.build_cases())
    on_disk = CASES_PATH.read_text(encoding="utf-8")
    assert hashlib.sha256(rebuilt.encode()).hexdigest() == \
        hashlib.sha256(on_disk.encode()).hexdigest()


def test_manifest_matches_file():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entry = manifest["files"]["retrieval_poisoning.jsonl"]
    assert entry["n_cases"] == 470
    assert entry["n_by_severity"] == {
        "critical": 90, "high": 160, "medium": 220}
    assert entry["n_by_primitive"] == {
        "choice": 330, "score": 80, "abstain": 60}
    blob = CASES_PATH.read_bytes()
    assert entry["sha256"] == hashlib.sha256(blob).hexdigest()
    mde = manifest["mdes"]["retrieval_poisoning"]
    assert (mde["pd_10"], mde["pd_20"], mde["pd_30"], mde["pd_40"]) == \
        (4.4, 6.3, 7.7, 8.9)
    assert manifest["dataset_version"] == "2.1.0"


def test_registry_template_taxonomy_agree():
    sys.path.insert(0, str(REPO / "python"))
    from peira.families import FAMILIES
    from peira.templates import TEMPLATES
    assert FAMILIES["retrieval_poisoning"].tier == "1"
    assert "retrieval_poisoning" in TEMPLATES
    taxonomy = (REPO / "docs" / "Taxonomy.md").read_text(encoding="utf-8")
    assert "**retrieval_poisoning** (Tier 1)" in taxonomy
