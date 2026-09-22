"""Generate cross-language parity fixtures for the Rust port.

Run from the repo root:  python3 crates/peira-core/tests/fixtures/generate.py

Writes:
  float_parity.txt   "<f64 bits hex> <python json.dumps(float)>" per line
  string_parity.txt  one JSON string literal per line (input == expected
                     canonical output, since canonical string encoding is
                     exactly Python's ensure_ascii literal)
  lock_parity.jsonl  {"artifact": {...}, "lock": "<hex>",
                     "pretty": "<to_json()>"} per line

The fixtures pin the Python reference behavior; the Rust tests in
crates/peira-core assert byte-identical output. Regenerate only when the
Python reference changes its serialization.
"""

from __future__ import annotations

import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "python"))

from peira.artifacts import RunArtifact, results_to_dicts  # noqa: E402
from peira.metrics import PerCaseResult  # noqa: E402

OUT = Path(__file__).resolve().parent


def gen_floats() -> None:
    rng = random.Random(20260922)
    vals: set[float] = set()
    # Curated edges: zeros, ones, notation cutoffs, extremes, denormals.
    vals.update([
        0.0, -0.0, 1.0, -1.0, 0.1, 0.5, 0.9, 0.87, 100.0, 123.456,
        0.30000000000000004, 1e-4, 1e-5, 1e-6, 2.5e-7, 0.0001, 0.00001,
        1e15, 1e16, 1e17, 1e20, 1e21, 123456789012345680.0,
        5e-324, 2.2250738585072014e-308, 1.7976931348623157e308,
        1.0000000000000002, 0.9999999999999999,
    ])
    # Random bit patterns across the whole finite range.
    while len(vals) < 1500:
        bits = rng.getrandbits(64)
        f = struct.unpack("<d", struct.pack("<Q", bits))[0]
        if f != f or f in (float("inf"), float("-inf")):
            continue
        vals.add(f)
    # Dense in [0, 1]: the confidence domain that analysis locks see.
    while len(vals) < 2500:
        vals.add(rng.random())
    lines = []
    for f in sorted(vals, key=lambda v: struct.pack("<d", v)):
        bits = struct.unpack("<Q", struct.pack("<d", f))[0]
        lines.append(f"{bits:016x} {json.dumps(f)}")
    (OUT / "float_parity.txt").write_text("\n".join(lines) + "\n")
    print(f"float_parity.txt: {len(lines)} cases")


def gen_strings() -> None:
    rng = random.Random(777)
    pool = (
        list("abcXYZ019 \t\n\r\"'\\/~")
        + ["\x00", "\x01", "\x08", "\x0c", "\x1f", "\x7f"]
        + ["é", "ä", "中", "\u2028", "\u2029", "\U0001f600", "\U0001f4a9"]
    )
    strings = {
        "", " ", "~", "\x7f", "é", "\U0001f600", "a\"b\\c",
        "\x00\x1f\x7f\u0080", "tab\there", "line\nbreak",
        "quote's \"mixed\"", "\u2028\u2029", "z" * 200,
    }
    while len(strings) < 600:
        n = rng.randint(0, 12)
        strings.add("".join(rng.choice(pool) for _ in range(n)))
    lines = [json.dumps(s) for s in sorted(strings)]
    (OUT / "string_parity.txt").write_text("\n".join(lines) + "\n")
    print(f"string_parity.txt: {len(lines)} cases")


def gen_locks() -> None:
    results = results_to_dicts([
        PerCaseResult(
            case_id="sp-001", family="state_poisoning", primitive="choice",
            benign_correct=True, attacked_flipped=True,
            attacked_targeted=True, malformed=False, confidence=0.87,
            benign_malformed=False, has_target=True,
        ),
        PerCaseResult(
            case_id="ng-002", family="negation_games", primitive="noul",
            benign_correct=True, attacked_flipped=False,
            attacked_targeted=False, malformed=False, confidence=1e-05,
            benign_malformed=False, has_target=False,
        ),
        PerCaseResult(
            case_id="sa-003", family="score_anchoring", primitive="score",
            benign_correct=False, attacked_flipped=True,
            attacked_targeted=False, malformed=True, confidence=None,
            benign_malformed=True, has_target=True,
        ),
    ])
    artifacts = [
        RunArtifact(
            peira_version="0.1.0", dataset_version="0.1.0-demo",
            adapter_name="dummy", adapter_version="0",
            suite="trial-demo", created_utc="2026-09-22T00:00:00+00:00",
            config={"n_cases": 3, "note": "café \U0001f600",
                    "nested": {"b": [1, 2.5], "a": None}},
            results=results,
            metrics={"asr_conditional": 0.5},
        ),
        RunArtifact(
            peira_version="0.1.0", dataset_version="1.0.0",
            adapter_name="x", adapter_version="2.1",
            suite="trial", created_utc="2026-01-01T12:34:56+00:00",
            config={}, results=[], metrics={},
        ),
    ]
    lines = []
    for a in artifacts:
        a.seal()
        assert a.verify()
        from dataclasses import asdict

        lines.append(json.dumps({
            "artifact": asdict(a),
            "lock": a.analysis_lock,
            "pretty": a.to_json(),
        }))
    (OUT / "lock_parity.jsonl").write_text("\n".join(lines) + "\n")
    print(f"lock_parity.jsonl: {len(lines)} artifacts")


def gen_case_extras() -> None:
    from peira.schema import Case  # noqa: E402

    def base(**kw):
        c = {
            "case_id": "x-001",
            "family": "state_poisoning",
            "primitive": "choice",
            "severity": "high",
            "benign": {"input": {"prompt": "p"}, "expected_decision": "a"},
            "attacked": {"input": {"prompt": "p!"}, "target_decision": "b"},
            "notes": "n",
        }
        c.update(kw)
        return c

    cases = [
        base(),
        base(review_priority="p1", author="david"),
        base(custom={"nested": [1, 2.5, None], "flag": True},
             tags=["a", "b"], weight=3, ratio=0.25),
        base(note="café \U0001f600", empty_obj={}, empty_list=[],
             nothing=None, deep={"a": {"b": {"c": [1, {"d": "e"}]}}}),
    ]
    lines = []
    for c in cases:
        case = Case.from_dict(c)
        assert case.extras == {k: v for k, v in c.items()
                               if k not in ("case_id", "family", "primitive",
                                            "severity", "benign", "attacked",
                                            "notes")}
        lines.append(json.dumps(case.to_dict(), sort_keys=True))
    (OUT / "case_extras.jsonl").write_text("\n".join(lines) + "\n")
    print(f"case_extras.jsonl: {len(lines)} cases")


if __name__ == "__main__":
    gen_floats()
    gen_strings()
    gen_locks()
    gen_case_extras()
