"""Build dataset/conversational/cases/multi_turn_escalation-p1.jsonl.

Assembles the 210 authored multi_turn_escalation cases (conv-mte-0001
.. conv-mte-0210) from the mte_d1..mte_d8 data modules, enforces every
schema and design rule, and writes the JSONL file.

Run from the worktree root:
    python3 dataset/conversational/work/build_mte.py
"""

import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

from mte_d1 import CASES as _d1  # noqa: E402
from mte_d2 import CASES as _d2  # noqa: E402
from mte_d3 import CASES as _d3  # noqa: E402
from mte_d4 import CASES as _d4  # noqa: E402
from mte_d5 import CASES as _d5  # noqa: E402
from mte_d6 import CASES as _d6  # noqa: E402
from mte_d7 import CASES as _d7  # noqa: E402
from mte_d8 import CASES as _d8  # noqa: E402

CASES = _d1 + _d2 + _d3 + _d4 + _d5 + _d6 + _d7 + _d8

OUT = WORK.parent / "cases" / "multi_turn_escalation-p1.jsonl"


def _scan_text(x, where, errors):
    """Reject em dashes and other non-ASCII tells anywhere in the case."""
    if isinstance(x, str):
        for ch in x:
            if ord(ch) > 127:
                errors.append(
                    f"{where}: non-ASCII char U+{ord(ch):04X} in {x[:60]!r}"
                )
                return
    elif isinstance(x, list):
        for i, v in enumerate(x):
            _scan_text(v, f"{where}[{i}]", errors)
    elif isinstance(x, dict):
        for k, v in x.items():
            _scan_text(v, f"{where}.{k}", errors)


def _interleave(users, assistants):
    """Alternate user/assistant turns, starting and ending with user.

    Assistant turns attach after user turns while any remain; trailing
    user turns without an assistant response stay consecutive (valid:
    only consecutive *assistant* turns are forbidden).
    """
    turns = []
    for i, u in enumerate(users):
        turns.append({"role": "user", "content": u})
        if i < len(assistants):
            turns.append({"role": "assistant", "content": assistants[i]})
    return turns


def _check_roles(turns, where, errors):
    roles = [t["role"] for t in turns]
    if roles[0] != "user":
        errors.append(f"{where}: first turn must be user")
    if roles[-1] != "user":
        errors.append(f"{where}: last turn must be user")
    if any(a == b == "assistant" for a, b in zip(roles, roles[1:])):
        errors.append(f"{where}: consecutive assistant turns")
    n_user = sum(1 for r in roles if r == "user")
    if n_user < 2:
        errors.append(f"{where}: need >= 2 user turns (got {n_user})")
    if n_user > 16:
        errors.append(f"{where}: > 16 user turns (got {n_user})")
    for i, t in enumerate(turns):
        if not t["content"]:
            errors.append(f"{where}.turns[{i}]: empty content")


def build_case(c):
    """Assemble one schema case dict; return (case_dict, errors)."""
    errors = []
    cid = f"conv-mte-{c['id']:04d}"
    _scan_text(c, cid, errors)

    opts = c["opts"]
    if not (isinstance(opts, list) and len(opts) >= 2):
        errors.append(f"{cid}: need >= 2 options")
    if len(set(opts)) != len(opts):
        errors.append(f"{cid}: options not unique")
    if any(not isinstance(o, str) or not o for o in opts):
        errors.append(f"{cid}: options must be non-empty strings")
    for gold_key, gold in (("bdec", c["bdec"]), ("adec", c["adec"])):
        if gold not in opts:
            errors.append(f"{cid}: {gold_key}={gold!r} not in options")

    if len(c["an"]) != len(c["au"]) - 1:
        errors.append(
            f"{cid}: need len(an)==len(au)-1 "
            f"(got {len(c['an'])} notes for {len(c['au'])} user turns)"
        )
    if any(not n for n in c["an"]):
        errors.append(f"{cid}: empty attack_note")

    b_turns = _interleave(c["bu"], c["ba"])
    _check_roles(b_turns, f"{cid}.benign", errors)

    a_turns_raw = _interleave(c["au"], c["aa"])
    _check_roles(a_turns_raw, f"{cid}.attacked", errors)
    # Attack marks: every user turn from the second onward advances the
    # attack, each with its mechanism note. The benign arm carries none.
    a_turns = []
    u_idx = 0
    for t in a_turns_raw:
        if t["role"] == "user" and u_idx > 0:
            a_turns.append(
                {
                    "role": "user",
                    "content": t["content"],
                    "attack": True,
                    "attack_note": c["an"][u_idx - 1],
                }
            )
        else:
            a_turns.append(
                {
                    "role": t["role"],
                    "content": t["content"],
                    "attack": False,
                    "attack_note": "",
                }
            )
        if t["role"] == "user":
            u_idx += 1
    b_turns = [
        {"role": t["role"], "content": t["content"],
         "attack": False, "attack_note": ""}
        for t in b_turns
    ]

    benign = {
        "turns": b_turns,
        "options": list(opts),
        "expected_decision": c["bdec"],
    }
    if c["prim"] == "score":
        if "escore" not in c or not 0.0 <= c["escore"] <= 1.0:
            errors.append(f"{cid}: score primitive needs escore in 0..1")
        if "pdec" not in c or c["pdec"] not in opts:
            errors.append(f"{cid}: score primitive needs pdec in options")
        benign["expected_score"] = c["escore"]
        benign["positive_decision"] = c["pdec"]
    elif "escore" in c or "pdec" in c:
        errors.append(f"{cid}: non-score primitive carries score fields")

    case = {
        "case_id": cid,
        "family": "multi_turn_escalation",
        "primitive": c["prim"],
        "severity": c["sev"],
        "benign": benign,
        "attacked": {
            "turns": a_turns,
            "options": list(opts),
            "target_decision": c["adec"],
        },
        "notes": c["note"],
        "evaluation_only": True,
        "do_not_train": True,
        "technique": c["tech"],
        "domain": c["dom"],
    }
    return case, errors


def main():
    ids = sorted(c["id"] for c in CASES)
    assert len(CASES) == 210, f"expected 210 cases, got {len(CASES)}"
    assert ids == list(range(1, 211)), "case ids must be 1..210 exactly"

    built, all_errors = [], []
    for c in CASES:
        case, errors = build_case(c)
        built.append(case)
        all_errors.extend(errors)
    if all_errors:
        for e in all_errors:
            print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(f"{len(all_errors)} build errors; wrote nothing")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for case in built:
            f.write(json.dumps(case, ensure_ascii=True) + "\n")
    print(f"wrote {len(built)} cases -> {OUT}")


if __name__ == "__main__":
    main()
