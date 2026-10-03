"""Automated dataset validation gates (stdlib only).

Gates are the authoring-time contract: they run over every ``*.jsonl``
case file in a dataset directory and report per-gate findings. Findings
are either errors (fail the suite — fix before building a manifest) or
warnings (reported; the suite still passes and a human reviews them in
the review queue).

The gates never judge case quality or difficulty — only structural
integrity a machine can check.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from heapq import nsmallest
from pathlib import Path
from typing import Any

from peira._rust import _impl as _rust, STRICT_RUST
from peira.dataset import iter_case_lines
from peira.schema import GATE_KNOWN_IDS, validate_case_dict


@dataclass
class GateResult:
    gate_id: str
    name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _canon_input(variant: dict[str, Any]) -> str:
    """Canonical JSON for input comparison with semantic normalization.

    Applies Unicode NFC normalization, strips zero-width/format
    characters (U+200B, U+200C, U+200D, U+FEFF), and normalizes numeric
    values (int/float equivalence) so semantically-null "attacks" that
    differ only in encoding details are caught by G2.
    """
    import unicodedata
    inp = variant.get("input", {})

    def normalize(obj):
        if isinstance(obj, str):
            # NFC normalize, strip zero-width/format chars
            s = unicodedata.normalize("NFC", obj)
            s = s.replace("\u200b", "").replace("\u200c", "")
            s = s.replace("\u200d", "").replace("\ufeff", "")
            return s
        if isinstance(obj, dict):
            return {normalize(k): normalize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [normalize(x) for x in obj]
        if isinstance(obj, float):
            # Normalize int-valued floats to int for equivalence
            if obj.is_integer():
                return int(obj)
            return obj
        return obj

    return json.dumps(normalize(inp), sort_keys=True)


def _to_rust_gate_cases(valid_cases) -> list[tuple[str, int, dict]]:
    """Convert (path, lineno, case) tuples to Rust GateCase format.

    Returns list of (path_name, lineno, case_dict) for PyO3 conversion.
    """
    return [
        (path.name if hasattr(path, "name") else str(path), lineno, case)
        for path, lineno, case in valid_cases
    ]


def _from_rust_gate_result(packed) -> GateResult:
    """Convert Rust (gate_id, name, errors, warnings) to GateResult."""
    gate_id, name, errors, warnings = packed
    return GateResult(gate_id, name, errors=errors, warnings=warnings)


def gate_schema(checked) -> GateResult:
    """G1: every case parses and satisfies the frozen schema.

    `checked` is (path, lineno, case_or_None, error_or_None) with the
    error pre-computed by the caller (see `run_gates`): validation runs
    once per case, and G1 only reports. `path` may be None in unit
    tests.
    """
    r = GateResult("G1", "schema")
    for path, lineno, _case, error in checked:
        if error:
            where = f"{path.name}:{lineno}" if path is not None else f"case:{lineno}"
            r.errors.append(f"{where}: {error}")
    return r


def _gate_paired_variants_py(valid_cases) -> GateResult:
    """G2: the attacked variant actually differs from its benign control.

    An attacked variant identical to its benign control is a broken case:
    there is no attack to measure. (G1 already guarantees both inputs are
    non-empty objects carrying options lists.)
    """
    r = GateResult("G2", "paired-variants")
    for path, lineno, case in valid_cases:
        if _canon_input(case["benign"]) == _canon_input(case["attacked"]):
            r.errors.append(f"{path.name}:{lineno}: attacked input is "
                            f"identical to benign input (no attack)")
    return r


def gate_paired_variants(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_paired_variants(_to_rust_gate_cases(valid_cases))
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
    return _gate_paired_variants_py(valid_cases)


def _gate_dedup_py(valid_cases) -> GateResult:
    """G3: case ids are unique; no two cases share a content pair."""
    r = GateResult("G3", "dedup")
    seen_ids: dict[str, str] = {}
    seen_pairs: dict[str, str] = {}
    for path, lineno, case in valid_cases:
        loc = f"{path.name}:{lineno}"
        cid = case["case_id"]
        if cid in seen_ids:
            r.errors.append(f"{loc}: duplicate case_id {cid!r} "
                            f"(first seen at {seen_ids[cid]})")
        else:
            seen_ids[cid] = loc
        pair = (_canon_input(case["benign"]), _canon_input(case["attacked"]))
        key = "\x00".join(pair)
        if key in seen_pairs:
            r.errors.append(f"{loc}: duplicate content pair "
                            f"(first seen at {seen_pairs[key]})")
        else:
            seen_pairs[key] = loc
    return r


def gate_dedup(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_dedup(_to_rust_gate_cases(valid_cases))
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
            pass
    return _gate_dedup_py(valid_cases)


def _gate_families_py(valid_cases) -> GateResult:
    """G4: every case uses a canonical attack-family id."""
    r = GateResult("G4", "families")
    for path, lineno, case in valid_cases:
        if case["family"] not in GATE_KNOWN_IDS:
            r.errors.append(f"{path.name}:{lineno}: unknown family "
                            f"{case['family']!r} (see docs/Taxonomy.md)")
    return r


def gate_families(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_families(
                _to_rust_gate_cases(valid_cases), list(GATE_KNOWN_IDS)
            )
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
            pass
    return _gate_families_py(valid_cases)


def _gate_target_coherence_py(valid_cases) -> GateResult:
    """G5: a named target decision must differ from the benign expectation.

    A targeted attack aiming at the decision the benign input already
    produces is incoherent — there is nothing to steer toward.
    """
    r = GateResult("G5", "target-coherence")
    for path, lineno, case in valid_cases:
        target = case["attacked"].get("target_decision")
        expected = case["benign"].get("expected_decision")
        if target is not None and target == expected:
            r.errors.append(f"{path.name}:{lineno}: target_decision "
                            f"{target!r} equals the benign expected decision")
    return r


_PII_PATTERNS = [
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone number", re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

# The email pattern above has catastrophic backtracking on long
# word-character runs without an @ (quadratic: 32k chars -> ~2s).
# Windowed scan: only run the regex on a bounded window around each @.
# Emails are <=254 chars per RFC 5321; the local part before @ is <=64.
_EMAIL_WINDOW_BEFORE = 64
_EMAIL_WINDOW_AFTER = 255


def _pii_scan_text(text: str) -> str | None:
    """Return the PII label if text contains PII, else None.

    The email check uses a windowed scan to avoid ReDoS on long inputs:
    the regex only runs on text[i-64:i+255] for each @ at position i,
    and is skipped entirely when there is no @ in the text.
    """
    # Email: windowed to avoid catastrophic backtracking.
    if "@" in text:
        pattern = _PII_PATTERNS[0][1]
        start = 0
        while True:
            at = text.find("@", start)
            if at < 0:
                break
            lo = max(0, at - _EMAIL_WINDOW_BEFORE)
            hi = min(len(text), at + _EMAIL_WINDOW_AFTER)
            if pattern.search(text[lo:hi]):
                return "email address"
            start = at + 1
    # Phone and SSN: fixed-width patterns, no backtracking risk.
    for label, pattern in _PII_PATTERNS[1:]:
        if pattern.search(text):
            return label
    return None


def gate_target_coherence(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_target_coherence(_to_rust_gate_cases(valid_cases))
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
            pass
    return _gate_target_coherence_py(valid_cases)


def _gate_pii_scan_py(valid_cases) -> GateResult:
    """G6: flag identifier-like strings in case inputs.

    Warnings, not errors: attack payloads sometimes contain synthetic
    identifiers by design (a phishing case *about* a suspicious email).
    Every warning goes to the human review queue.
    """
    r = GateResult("G6", "pii-scan")
    for path, lineno, case in valid_cases:
        for variant in ("benign", "attacked"):
            text = json.dumps(case[variant].get("input", {}), sort_keys=True)
            label = _pii_scan_text(text)
            if label is not None:
                r.warnings.append(f"{path.name}:{lineno}: possible "
                                  f"{label} in {variant} input")
                break
    return r


def gate_pii_scan(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_pii_scan(_to_rust_gate_cases(valid_cases))
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
            pass
    return _gate_pii_scan_py(valid_cases)


def _gate_score_reference_py(valid_cases) -> GateResult:
    """G7: score-primitive cases carry the author's reference score.

    Score diagnostics (A3 S6) measure adapter-vs-author agreement
    against benign.expected_score; a score case without one cannot
    contribute. Errors, not warnings: on release-track datasets a
    missing reference is a broken case, not a judgment call.
    """
    r = GateResult("G7", "score-reference")
    for path, lineno, case in valid_cases:
        if case["primitive"] == "score":
            if case["benign"].get("expected_score") is None:
                r.errors.append(f"{path.name}:{lineno}: score case missing "
                                f"benign expected_score (author reference)")
    return r


def gate_score_reference(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_score_reference(_to_rust_gate_cases(valid_cases))
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
            pass
    return _gate_score_reference_py(valid_cases)


def _gate_options_coherence_py(valid_cases) -> GateResult:
    """G8: options lists are canonical across both variants.

    Adapters build one decision enum per options list; a vocabulary
    that shifts between arms makes the benign baseline and the
    attacked measurement non-comparable. Every case's benign and
    attacked inputs must therefore carry the identical options list
    (order-sensitive), and each list must be sorted with unique
    labels — the canonical form the dataset ships in. (G1 already
    guarantees each list is present, non-empty, all strings, and that
    the gold labels are members of their own list.)
    """
    r = GateResult("G8", "options-coherence")
    for path, lineno, case in valid_cases:
        loc = f"{path.name}:{lineno}"
        opts = {}
        for variant in ("benign", "attacked"):
            o = case[variant].get("input", {}).get("options")
            # G1 rejects non-list options; the gate only checks
            # canonical form on lists.
            if not isinstance(o, list):
                continue
            opts[variant] = o
            if len(set(o)) != len(o):
                r.errors.append(
                    f"{loc}: {variant} input options contain "
                    f"duplicate labels"
                )
            if o != sorted(o):
                r.errors.append(
                    f"{loc}: {variant} input options are not in "
                    f"sorted order"
                )
        if (
            "benign" in opts
            and "attacked" in opts
            and opts["benign"] != opts["attacked"]
        ):
            r.errors.append(
                f"{loc}: benign and attacked input options differ — "
                f"the decision vocabulary must be identical across arms"
            )
    return r


def gate_options_coherence(valid_cases) -> GateResult:
    """Dispatch to Rust when available, else the pure-Python reference."""
    if _rust is not None:
        try:
            packed = _rust.gates_options_coherence(_to_rust_gate_cases(valid_cases))
            return _from_rust_gate_result(packed)
        except (TypeError, ValueError):
            if STRICT_RUST:
                raise
            pass
    return _gate_options_coherence_py(valid_cases)


# G9: near-dedup calibration. Thresholds come from
# scripts/calibrate_g9_threshold.py, calibrated 2026-09-28 on 50
# hand-labeled paraphrase pairs (tests/fixtures/g9_paraphrase_pairs.jsonl):
# 20 near-duplicates all scored >= 0.8018, 30 distinct pairs all scored
# <= 0.7089. The warning threshold sits inside that separation gap,
# biased toward precision (fewer false flags for human review).
G9_WARN_THRESHOLD = 0.78
# Near-identical texts (only trivial edits apart) fail outright. This is
# a judgment call anchored in the calibration fixture, not a calibrated
# value: the 20 hand-labeled near-duplicate pairs top out at similarity
# 0.9217, so the error band only fires on pairs strictly more similar
# than anything a human labeled a mere paraphrase. In practice that
# means prompts differing by a few characters, which score at or above
# the error band on typical prompt lengths.
G9_ERROR_THRESHOLD = 0.98
# Candidate blocking: a bottom-k MinHash-style sketch (k smallest md5
# hashes of the case's trigram set) with an inverted index. A candidate
# pair must share at least G9_MIN_OVERLAP sketch hashes. Tuned 2026-09-28
# on the v1 corpus (2,000 cases): k=96 / overlap=38 gives 100% recall of
# the 20 hand-labeled positives at 0.66% of all pairs as candidates
# (~45s for 2,000 cases, stdlib only). The sketch is a heuristic filter;
# every candidate is verified with the exact trigram-cosine, so the
# reported findings are exact. Cases with fewer distinct trigrams than
# the overlap threshold bypass the sketch and are compared exactly, so
# short near-duplicates are never silently skipped.
G9_SKETCH_K = 96
G9_MIN_OVERLAP = 38


def _g9_trigram_counter(text: str) -> Counter:
    t = text.lower()
    return Counter(t[i:i + 3] for i in range(len(t) - 2))


def _g9_case_text(case: dict[str, Any]) -> str:
    """Text the G9 gate compares: benign + attacked prompts.

    Must match the extraction used by scripts/calibrate_g9_threshold.py;
    the calibrated threshold is only valid for this exact text.
    """
    b = case.get("benign", {}).get("input", {}).get("prompt", "")
    a = case.get("attacked", {}).get("input", {}).get("prompt", "")
    return (b + "\n" + a).strip()


def _g9_cosine(a: Counter, norm_a: float, b: Counter, norm_b: float) -> float:
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    if len(a) > len(b):
        a, b, norm_a, norm_b = b, a, norm_b, norm_a
    get = b.get
    dot = 0
    for k, c in a.items():
        d = get(k)
        if d:
            dot += c * d
    return dot / (norm_a * norm_b)


def _g9_sketch(trigrams: set[str]) -> set[int]:
    """Bottom-k sketch: k smallest md5 hashes of the trigram set."""
    it = (int.from_bytes(hashlib.md5(t.encode()).digest(), "little")
          for t in trigrams)
    return set(nsmallest(G9_SKETCH_K, it))


def _g9_pair_id(case: dict) -> str | None:
    """The declared minimal-pair id of a case, if any.

    EB-3 counterfactual probes (and EB-2 dialect pairs) are minimal
    pairs by design: two cases differing only in one demographic
    attribute or register. They declare the link in the top-level
    ``fairness.pair_id`` field.
    """
    f = case.get("fairness")
    if not isinstance(f, dict):
        return None
    pid = f.get("pair_id")
    return pid if isinstance(pid, str) and pid else None


def gate_near_dedup(valid_cases) -> GateResult:
    """G9: flag near-duplicate cases via trigram-cosine similarity.

    Compares the concatenated benign + attacked prompt text of every
    case pair (stdlib only, no embedding model). Pairs at or above
    G9_ERROR_THRESHOLD are errors (near-identical); pairs at or above
    G9_WARN_THRESHOLD are warnings for human review.

    Declared minimal-pair instruments are excluded by design: two
    cases sharing a non-empty ``fairness.pair_id`` (EB-3
    counterfactual probes, EB-2 dialect pairs) are *supposed* to be
    near-identical — that is the measurement. The carve-out is
    narrow (both cases must declare the same pair id) and documented
    in dataset/safety-policy/SPEC.md. Everything else is compared
    exactly as before.

    Candidate pairs come from a bottom-k sketch inverted index (see
    G9_SKETCH_K / G9_MIN_OVERLAP), so the exact cosine is computed for
    well under 1% of pairs on a diverse corpus instead of O(n^2).
    Cases too short to reach the overlap threshold are compared exactly
    against every other case, so short near-duplicates are not missed.
    Findings are deterministic: cases are visited in input order,
    posting lists are built in index order, and candidates are compared
    in index order.
    """
    r = GateResult("G9", "near-dedup")
    items = [(path, lineno, case) for path, lineno, case in valid_cases]
    vecs: list[tuple[Counter, float]] = []
    sketches: list[set[int]] = []
    for _path, _lineno, case in items:
        vec = _g9_trigram_counter(_g9_case_text(case))
        norm = math.sqrt(sum(c * c for c in vec.values()))
        vecs.append((vec, norm))
        sketches.append(_g9_sketch(set(vec)))

    # Inverted index: sketch hash -> case indices (ascending, since we
    # append in order). bisect_right skips j <= i without scanning.
    index: dict[int, list[int]] = defaultdict(list)
    for i, sk in enumerate(sketches):
        for h in sk:
            index[h].append(i)

    # A case with fewer distinct trigrams than G9_MIN_OVERLAP can never
    # reach the overlap threshold through the sketch, so the index
    # would silently skip it. Such short cases bypass the sketch and
    # are compared exactly against every later case.
    n = len(items)
    short = {i for i, sk in enumerate(sketches)
             if len(sk) < G9_MIN_OVERLAP}

    for i, (vec_i, norm_i) in enumerate(vecs):
        overlap: dict[int, int] = {}
        for h in sketches[i]:
            post = index[h]
            start = bisect.bisect_right(post, i)
            for j in post[start:]:
                overlap[j] = overlap.get(j, 0) + 1
        candidates = {j for j, o in overlap.items()
                      if o >= G9_MIN_OVERLAP}
        if i in short:
            candidates.update(range(i + 1, n))
        else:
            candidates.update(j for j in short if j > i)
        for j in sorted(candidates):
            # Declared minimal-pair instruments skip the comparison:
            # near-identity is their design, not an authoring defect.
            # The carve-out is bounded: both cases must share a family,
            # otherwise the pair_id is ignored and the pair is compared
            # normally (prevents smuggling arbitrary near-duplicates
            # past G9 via a forged pair_id).
            pid_i = _g9_pair_id(items[i][2])
            pid_j = _g9_pair_id(items[j][2])
            if pid_i is not None and pid_i == pid_j:
                fam_i = items[i][2].get("family")
                fam_j = items[j][2].get("family")
                if fam_i is not None and fam_i == fam_j:
                    continue
            vec_j, norm_j = vecs[j]
            sim = _g9_cosine(vec_i, norm_i, vec_j, norm_j)
            if sim < G9_WARN_THRESHOLD:
                continue
            loc_i = f"{items[i][0].name}:{items[i][1]}"
            loc_j = f"{items[j][0].name}:{items[j][1]}"
            msg = (f"{loc_i} ~ {loc_j}: trigram-cosine {sim:.3f} "
                   f"(cases {items[i][2]['case_id']} / {items[j][2]['case_id']})")
            if sim >= G9_ERROR_THRESHOLD:
                r.errors.append(msg + " is near-identical; keep only one")
            else:
                r.warnings.append(msg + "; review for near-duplication")
    return r


def run_gates(dataset_dir: Path) -> list[GateResult]:
    """Run all gates over a dataset directory, in order."""
    # One pass: every line is parsed and validated exactly once. Each
    # entry is (path, lineno, case_or_None, error_or_None) — G1 reports
    # the collected errors, G2–G9 consume the valid subset, so no case
    # is ever validated twice.
    checked: list[tuple[Path, int, Any, str | None]] = []
    for path, lineno, case, json_error in iter_case_lines(dataset_dir):
        if json_error is not None:
            checked.append((path, lineno, None, json_error))
            continue
        errors = validate_case_dict(case)
        checked.append((path, lineno, case,
                        "; ".join(errors) if errors else None))
    results = [gate_schema(checked)]
    valid = [(p, n, c) for p, n, c, e in checked if e is None]
    results.append(gate_paired_variants(valid))
    results.append(gate_dedup(valid))
    results.append(gate_families(valid))
    results.append(gate_target_coherence(valid))
    results.append(gate_pii_scan(valid))
    results.append(gate_score_reference(valid))
    results.append(gate_options_coherence(valid))
    results.append(gate_near_dedup(valid))
    return results
