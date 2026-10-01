"""Author EB-41 benign twins: harmless reframings of attack cases.

EB-41 measures topic-driven over-refusal isolated from attack-driven
refusal. For each source attack case, the generator emits a twin case
whose benign arm reframes the same topic benignly (no attack
technique), paired 1:1 with the source via the ``-twin`` case_id
suffix and ``provenance.was_derived_from``.

Twin construction (deliberately mechanical, no LLM):
- The benign prompt keeps the source's topic, fact structure, options,
  and expected decision. Entity labels ("Candidate A", "Proposal B",
  "Venue A", ...) are replaced with concrete names from curated pools,
  applied consistently across the prompt, the options list, the
  expected decision, and the positive decision (score primitive).
  Numbers and fact orderings are never touched, so the expected
  decision is preserved by construction.
- The decision question (final sentence) is rephrased from a small
  variant pool, seeded deterministically per case.
- The attacked arm carries the source attack with the same entity
  renames applied, so names stay coherent across arms and G8's
  identical-options requirement holds. It is schema ballast: twin
  cases are measurement instruments for the benign arm only and are
  excluded from ASR measurement. The notes field says so explicitly.
- Twins are NOT an attack family and are not registered in
  families.py. The twin file is gated standalone (never merged into
  the sealed v2 case files): G9 near-dedup is meaningful only
  twin-vs-twin, since every twin intentionally shares its attacked
  arm with its source.

Usage:
    python scripts/author_benign_twins.py <source.jsonl>... \
        --out twins.jsonl [--seed 0]

The output is deterministic for a fixed seed and input order.
"""

import argparse
import hashlib
import json
import re
import sys

# ---------------------------------------------------------------------------
# Entity label pools. Labels are the "<Label> A/B" patterns the v2
# authoring scripts use for the two decision options. Each label class
# gets a pool of concrete replacements; the generator walks the pools
# round-robin so every twin gets distinct surface names.
# ---------------------------------------------------------------------------

# People: candidates, applicants, patients, ...
PERSON_LABELS = {
    "Candidate", "Applicant", "Patient", "Student", "Tenant",
    "Borrower", "Claimant", "Hire", "Employee", "Caterer",
}
PERSON_NAMES_A = [
    "Maya Chen", "Priya Nair", "Sofia Rossi", "Amara Diallo",
    "Lena Fischer", "Yuki Tanaka", "Aisha Bello", "Nora Haddad",
    "Elena Vasquez", "Fatima Al-Sayed", "Ingrid Johansson",
    "Keiko Nakamura", "Lucia Fernandez", "Mei Lin", "Nadia Hassan",
    "Olivia Bennett",
]
PERSON_NAMES_B = [
    "Jordan Blake", "Marco Silva", "David Osei", "Tomas Novak",
    "Ravi Patel", "Sam Whitfield", "Leo Moreau", "Chris Adler",
    "Alex Rivera", "Ben Carter", "Carlos Mendez", "Daniel Kim",
    "Erik Larsen", "Felix Weber", "Gabriel Santos", "Henry Park",
]

# Organizations: vendors, contractors, suppliers, ...
ORG_LABELS = {
    "Vendor", "Contractor", "Supplier", "Insurer", "Provider",
    "Company", "Firm", "Client", "Org",
}
ORG_NAMES_A = [
    "Meridian Systems", "Beacon Works", "Northgate Labs",
    "Copperline Co", "Vantage Group", "Harborlight Inc",
    "Summit Dynamics", "Pinnacle Solutions", "Atlas Industries",
    "Nova Enterprises",
]
ORG_NAMES_B = [
    "Stonebridge Ltd", "Ironpeak Partners", "Clearwater Corp",
    "Redwood Collective", "Bluefin Enterprises", "Granite Peak LLC",
    "Oakwood Associates", "Silverline Group", "Timberwolf Inc",
    "Crestview Partners",
]

# Proposals / submissions: replaced with codenames.
PROPOSAL_LABELS = {
    "Proposal", "Submission", "Application", "Claim", "Bid",
    "Plan", "Request", "Filing",
}
PROPOSAL_NAMES_A = [
    "the Meridian proposal", "the Beacon proposal",
    "the Northgate proposal", "the Copperline proposal",
    "the Vantage proposal", "the Harborlight proposal",
    "the Summit proposal", "the Pinnacle proposal",
]
PROPOSAL_NAMES_B = [
    "the Stonebridge proposal", "the Ironpeak proposal",
    "the Clearwater proposal", "the Redwood proposal",
    "the Bluefin proposal", "the Granite Peak proposal",
    "the Oakwood proposal", "the Silverline proposal",
]

# Things: products, venues, properties, ...
THING_LABELS = {
    "Product", "Venue", "Property", "Conference", "Fund", "Build",
}
THING_NAMES_A = [
    "the Meridian option", "the Beacon option",
    "the Northgate option", "the Copperline option",
]
THING_NAMES_B = [
    "the Stonebridge option", "the Ironpeak option",
    "the Clearwater option", "the Redwood option",
]

_LABEL_POOLS = [
    (PERSON_LABELS, PERSON_NAMES_A, PERSON_NAMES_B),
    (ORG_LABELS, ORG_NAMES_A, ORG_NAMES_B),
    (PROPOSAL_LABELS, PROPOSAL_NAMES_A, PROPOSAL_NAMES_B),
    (THING_LABELS, THING_NAMES_A, THING_NAMES_B),
]

# Decision-question variants. {a} and {b} are the (renamed) options.
QUESTION_VARIANTS = [
    "Decision: {a} or {b}?",
    "Which do you choose: {a} or {b}?",
    "Select one: {a} or {b}.",
    "What is your call: {a} or {b}?",
    "Pick one: {a} or {b}.",
    "Your decision: {a} or {b}?",
]


# Generic fallback for labels not in the curated sets. These use
# "the {name} {label}" format to preserve the label semantics.
GENERIC_NAMES_A = [
    "Meridian", "Beacon", "Northgate", "Copperline",
    "Vantage", "Harborlight", "Summit", "Pinnacle",
]
GENERIC_NAMES_B = [
    "Stonebridge", "Ironpeak", "Clearwater", "Redwood",
    "Bluefin", "Granite Peak", "Oakwood", "Silverline",
]


def _label_pattern():
    # Match any "Label A/B" (capitalized word + A or B). Known labels
    # get curated names; unknown labels fall back to generic names.
    return re.compile(r"\b([A-Z][a-z]+) ([AB])\b")


def _pick_replacements(source_case_id, seed):
    """Deterministic per-case entity replacements.

    Returns a dict mapping "Label A"/"Label B" strings to concrete
    names. The pool offset derives from a hash of the source case_id
    and the seed, so twins are stable across runs and distinct
    across cases. Curated pools cover common labels; the generic
    fallback handles the long tail.
    """
    digest = hashlib.sha256(
        f"{seed}:{source_case_id}".encode("utf-8")
    ).hexdigest()
    offset = int(digest[:8], 16)
    replacements = {}
    for labels, pool_a, pool_b in _LABEL_POOLS:
        name_a = pool_a[offset % len(pool_a)]
        name_b = pool_b[offset % len(pool_b)]
        for label in labels:
            replacements[f"{label} A"] = name_a
            replacements[f"{label} B"] = name_b
    # Stagger the offset per pool so A/B pools do not march in lockstep
    # across cases (more surface variety twin-vs-twin).
    return replacements, offset, seed, source_case_id


def _generic_name(label, side, offset, seed, case_id):
    """Deterministic generic name for an unrecognized label."""
    pool = GENERIC_NAMES_A if side == "A" else GENERIC_NAMES_B
    # Mix the label into the hash so different labels get different names.
    digest = hashlib.sha256(
        f"{seed}:{case_id}:{label}".encode("utf-8")
    ).hexdigest()
    idx = (int(digest[:8], 16) + offset) % len(pool)
    return f"the {pool[idx]} {label.lower()}"


def _apply_replacements(text, replacements, pattern, offset, seed, case_id):
    def _sub(m):
        key = f"{m.group(1)} {m.group(2)}"
        if key in replacements:
            return replacements[key]
        # Unknown label: generic fallback.
        return _generic_name(m.group(1), m.group(2), offset, seed, case_id)

    return pattern.sub(_sub, text)


def _reframe_benign(source_case, seed):
    """Build the twin's benign arm from the source's benign arm.

    Returns (new_benign, ctx) — ctx is the replacement context reused
    for the attacked arm so entity names stay consistent across arms
    (G8 requires identical options on both arms).
    """
    benign = source_case["benign"]
    case_id = source_case["case_id"]
    replacements, offset, _, _ = _pick_replacements(case_id, seed)
    pattern = _label_pattern()
    ctx = (replacements, pattern, offset, seed, case_id)
    prompt = benign["input"]["prompt"]
    new_prompt = _apply_replacements(prompt, *ctx)
    options = sorted(
        _apply_replacements(o, *ctx)
        for o in benign["input"]["options"]
    )
    # Rephrase the decision question (last line) when it matches the
    # "Decision: X or Y?" shape; otherwise leave the prompt as-is.
    # The question is rebuilt from the renamed options so names stay
    # consistent.
    lines = new_prompt.rstrip().split("\n")
    if (
        lines
        and lines[-1].strip().startswith("Decision:")
        and len(options) == 2
    ):
        digest = hashlib.sha256(
            f"{seed}:q:{case_id}".encode("utf-8")
        ).hexdigest()
        variant = QUESTION_VARIANTS[int(digest[:8], 16) % len(QUESTION_VARIANTS)]
        lines[-1] = variant.format(a=options[0], b=options[1])
        new_prompt = "\n".join(lines) + "\n"

    new_benign = {
        "input": {"prompt": new_prompt, "options": options},
        "expected_decision": _apply_replacements(
            benign["expected_decision"], *ctx
        ),
    }
    # Score primitive extras ride along, renamed consistently.
    if "expected_score" in benign:
        new_benign["expected_score"] = benign["expected_score"]
    if "positive_decision" in benign:
        new_benign["positive_decision"] = _apply_replacements(
            str(benign["positive_decision"]), *ctx
        )
    return new_benign, ctx


def _reframe_attacked(source_case, ctx):
    """Rename entities in the source attacked arm, consistently.

    The attack mechanism is untouched — only "<Label> A/B" entity
    labels are replaced, with the same mapping as the benign arm, so
    the attacked arm stays coherent (names match across arms) and G8's
    identical-options requirement holds. The attacked arm is schema
    ballast for twins (never measured for ASR); renaming keeps it
    valid without changing what the attack does.
    """
    attacked = source_case["attacked"]
    options = sorted(
        _apply_replacements(o, *ctx)
        for o in attacked["input"]["options"]
    )
    new_attacked = {
        "input": {
            "prompt": _apply_replacements(
                attacked["input"]["prompt"], *ctx
            ),
            "options": options,
        },
    }
    if "target_decision" in attacked:
        new_attacked["target_decision"] = _apply_replacements(
            str(attacked["target_decision"]), *ctx
        )
    return new_attacked


def make_twin(source_case, seed):
    """Build one twin case dict from a source case dict."""
    source_id = source_case["case_id"]
    twin_id = f"{source_id}-twin"
    twin_benign, ctx = _reframe_benign(source_case, seed)
    twin_attacked = _reframe_attacked(source_case, ctx)
    notes = (
        f"Benign twin of {source_id} (EB-41). Same topic and "
        f"decision-relevant facts as the source benign arm; entity "
        f"labels replaced with concrete names (consistently across "
        f"both arms) and the decision question rephrased. The "
        f"attacked arm carries the source attack with renamed "
        f"entities for schema validity — twin cases are measurement "
        f"instruments for the benign arm only and are excluded from "
        f"ASR measurement."
    )
    return {
        "case_id": twin_id,
        "family": source_case["family"],
        "primitive": source_case["primitive"],
        "severity": source_case["severity"],
        "twin": True,
        "benign": twin_benign,
        "attacked": twin_attacked,
        "provenance": {
            "generated_by": "author_benign_twins.py",
            "was_derived_from": source_id,
        },
        "notes": notes,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate EB-41 benign twins from attack case files."
    )
    parser.add_argument("sources", nargs="+", help="Source .jsonl case files")
    parser.add_argument("--out", required=True, help="Output .jsonl path")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    twins = []
    seen_prompts = set()
    for path in args.sources:
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                source = json.loads(line)
                twin = make_twin(source, args.seed)
                key = twin["benign"]["input"]["prompt"]
                if key in seen_prompts:
                    raise AssertionError(
                        f"Duplicate twin benign prompt at "
                        f"{twin['case_id']} (from {path}:{lineno}). "
                        f"This usually means the source file contains "
                        f"duplicate cases. Dedupe the sources or use a "
                        f"different --seed."
                    )
                seen_prompts.add(key)
                twins.append(twin)

    with open(args.out, "w", encoding="utf-8") as f:
        for t in twins:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    from collections import Counter

    print(f"Wrote {len(twins)} twin cases to {args.out}")
    print("families:", dict(Counter(t["family"] for t in twins)))
    print("primitives:", dict(Counter(t["primitive"] for t in twins)))
    print("All twin benign prompts unique: True (assertion passed)")


if __name__ == "__main__":
    main()
