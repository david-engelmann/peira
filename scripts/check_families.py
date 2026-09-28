#!/usr/bin/env python3
"""CI docs check: the family registry and docs/Taxonomy.md never drift (stdlib only).

peira/families.py is the machine-readable registry; docs/Taxonomy.md
carries the same list in prose. This check asserts:

  - every registry id appears exactly once as a numbered **id** entry
    under the "## Attack families" section of docs/Taxonomy.md,
  - no documented id is missing from the registry,
  - the (Tier 1) / (Tier 2) markers in the doc match the registry tiers
    (v1 families carry no marker),
  - the numbering runs 1..N in order.

Usage:
    python3 scripts/check_families.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.families import FAMILIES  # noqa: E402

ENTRY_RE = re.compile(r"^(\d+)\.\s+\*\*([a-z0-9_]+)\*\*\s*(\(Tier [12]\))?")


def entry_text_hash(text: str) -> str:
    """Stable hash of one family entry's prose (whitespace-normalized)."""
    import hashlib

    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def documented_families(taxonomy: Path) -> list[tuple[int, str, str | None]]:
    """Parse (number, family id, tier marker) from the Attack families section."""
    lines = taxonomy.read_text(encoding="utf-8").splitlines()
    in_section = False
    found: list[tuple[int, str, str | None]] = []
    for line in lines:
        if line.startswith("## "):
            in_section = line.strip() == "## Attack families"
            continue
        if not in_section:
            continue
        m = ENTRY_RE.match(line)
        if m:
            number = int(m.group(1))
            marker = m.group(3)
            tier = marker.strip("()").split()[1] if marker else "v1"
            found.append((number, m.group(2), tier))
    return found


def documented_entry_blocks(taxonomy: Path) -> dict[str, str]:
    """Map family id -> full entry prose block (numbered line plus its
    continuation lines, up to the next entry or the section end)."""
    lines = taxonomy.read_text(encoding="utf-8").splitlines()
    in_section = False
    blocks: dict[str, str] = {}
    current_id: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if in_section:
                break
            in_section = line.strip() == "## Attack families"
            continue
        if not in_section:
            continue
        m = ENTRY_RE.match(line)
        if m:
            if current_id is not None:
                blocks[current_id] = "\n".join(current_lines)
            current_id = m.group(2)
            current_lines = [line]
        elif current_id is not None and line.strip():
            current_lines.append(line)
    if current_id is not None:
        blocks[current_id] = "\n".join(current_lines)
    return blocks


#: Expected entry-prose hashes. A meaning change to a family's
#: Taxonomy entry must update the hash here deliberately; silent
#: rewording fails the check.
EXPECTED_ENTRY_HASHES: dict[str, str] = {
    'state_poisoning': 'ce4f1be060b4f810',
    'criteria_smuggling': '911e64e3d697c41a',
    'option_order': '3a4de13e60386c7e',
    'distractor_flooding': '921a591e12ec1665',
    'score_anchoring': 'b267df73b05f1102',
    'literal_reading': '4d7c5941e4322f64',
    'negation_games': '02df43daeadfe687',
    'policy_paraphrase': '0523f65da4bf9407',
    'indirection': 'a66a89cc2b144b3f',
    'confidence_spoofing': 'e512f282c219b10f',
    'instruction_override': 'fc45375a7ef6549e',
    'indirect_injection': '5b42165367cb2521',
    'authority_fabrication': '3e043c617a3798ce',
    'self_advocacy': 'd8d3737b3d10ead8',
    'criteria_order': '8be1cbd6141a1ddf',
    'precedent_stacking': '16719da4c951bc2d',
    'contradiction_injection': '630a9c9744654e4f',
    'temporal_numeric_traps': 'af7e233d73345439',
    'encoding_evasion': 'b8aa7481a261acf9',
    'abstain_forcing': 'a2524ce248716d94',
}


def check() -> list[str]:
    problems: list[str] = []
    taxonomy = REPO_ROOT / "docs" / "Taxonomy.md"
    if not taxonomy.is_file():
        return ["docs/Taxonomy.md missing"]

    documented = documented_families(taxonomy)
    doc_ids = [fam for _, fam, _ in documented]

    # Numbering runs 1..N in order.
    numbers = [n for n, _, _ in documented]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(
            f"docs/Taxonomy.md: family numbering is not 1..{len(numbers)} "
            f"in order (got {[n for n, _, _ in documented]})"
        )

    # No duplicates in the doc.
    seen: set[str] = set()
    for fam in doc_ids:
        if fam in seen:
            problems.append(f"docs/Taxonomy.md: duplicate family entry **{fam}**")
        seen.add(fam)

    # Registry vs doc, both directions.
    for fam in FAMILIES:
        if fam not in seen:
            problems.append(
                f"peira/families.py: {fam!r} has no entry in docs/Taxonomy.md"
            )
    for fam in seen:
        if fam not in FAMILIES:
            problems.append(
                f"docs/Taxonomy.md: **{fam}** is not in peira/families.py"
            )

    # Tier markers match the registry.
    for _, fam, doc_tier in documented:
        if fam in FAMILIES and FAMILIES[fam].tier != doc_tier:
            problems.append(
                f"docs/Taxonomy.md: **{fam}** is marked Tier {doc_tier} "
                f"but the registry says tier {FAMILIES[fam].tier!r}"
            )

    # Entry prose has not drifted in meaning: each family's block must
    # match its checked-in hash. Rewording an entry requires updating
    # EXPECTED_ENTRY_HASHES deliberately.
    blocks = documented_entry_blocks(taxonomy)
    for fam in FAMILIES:
        block = blocks.get(fam)
        if block is None:
            continue  # already reported as missing above
        expected = EXPECTED_ENTRY_HASHES.get(fam)
        if expected is None:
            problems.append(
                f"docs/Taxonomy.md: **{fam}** has no expected entry hash; "
                f"add one to EXPECTED_ENTRY_HASHES"
            )
        elif entry_text_hash(block) != expected:
            problems.append(
                f"docs/Taxonomy.md: **{fam}** entry prose changed; if the "
                f"meaning change is intentional, update its hash in "
                f"EXPECTED_ENTRY_HASHES"
            )
    return problems


def main() -> int:
    problems = check()
    for p in problems:
        print(f"families: {p}")
    if problems:
        print(f"families: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"families: registry and docs/Taxonomy.md agree "
          f"({len(FAMILIES)} families)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
