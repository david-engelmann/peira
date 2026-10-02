#!/usr/bin/env python3
"""Apply v2-new-families-audit mechanical fixes.

All fixes are pure copy edits to prompt text verified by hand;
no labels, options, scores, or case structure are touched.

Fix 1: article error in question_pair_incoherence v2-qpi-0347
       ("a employment gap" -> "an employment gap", both arms).
Fix 2: doubled words inside cryptographic_payload attack payloads
       (v2-cryp-0037 "choose choose", v2-cryp-0273 "support support",
       v2-cryp-0313 "select select", v2-cryp-0316 "choose choose").
       Fixed in BOTH the benign blocked-content display AND the
       attacked ciphertext (ROT13 / word-reversal), keeping the
       ciphertext decoding consistent with the displayed plaintext.

Usage: python3 scripts/apply_v2_newfam_audit_fixes.py [--check]
--check prints what would change without writing.
"""

from __future__ import annotations

import codecs
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "dataset" / "v2" / "cases"


def rot13(s: str) -> str:
    return codecs.encode(s, "rot_13")


def wordrev(s: str) -> str:
    return " ".join(w[::-1] for w in s.split(" "))


# case_id -> (plaintext doubled word, cipher doubled word, decode fn)
CRYPTO_FIXES = {
    "v2-cryp-0037": ("choose choose", "pubbfr pubbfr", rot13),
    "v2-cryp-0273": ("support support", "fhccbeg fhccbeg", rot13),
    "v2-cryp-0313": ("select select", "fryrpg fryrpg", rot13),
    "v2-cryp-0316": ("choose choose", "esoohc esoohc", wordrev),
}


def fix_file(path: Path, check: bool) -> dict:
    counts = {"article": 0, "crypto": 0}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        cid = row["case_id"]
        # Fix 1: QPI article
        if cid == "v2-qpi-0347":
            for arm in ("benign", "attacked"):
                p = row[arm]["input"]["prompt"]
                if "a employment gap" in p:
                    row[arm]["input"]["prompt"] = p.replace(
                        "a employment gap", "an employment gap"
                    )
                    counts["article"] += 1
        # Fix 2: crypto doubled words
        if cid in CRYPTO_FIXES:
            plain_dbl, cipher_dbl, decode = CRYPTO_FIXES[cid]
            plain_fix = plain_dbl.split()[0]
            cipher_fix = cipher_dbl.split()[0]
            bp = row["benign"]["input"]["prompt"]
            ap = row["attacked"]["input"]["prompt"]
            # idempotent: skip if already fixed
            if plain_dbl not in bp and cipher_dbl not in ap:
                rows.append(row)
                continue
            assert plain_dbl in bp, f"{cid}: plaintext doubled word not in benign"
            assert cipher_dbl in ap, f"{cid}: cipher doubled word not in attacked"
            # consistency: decoding the cipher must yield the plaintext
            assert decode(cipher_dbl) == plain_dbl, f"{cid}: cipher decode mismatch"
            row["benign"]["input"]["prompt"] = bp.replace(plain_dbl, plain_fix)
            row["attacked"]["input"]["prompt"] = ap.replace(cipher_dbl, cipher_fix)
            # post-fix consistency
            bp2 = row["benign"]["input"]["prompt"]
            ap2 = row["attacked"]["input"]["prompt"]
            assert decode(cipher_fix) == plain_fix, f"{cid}: post-fix decode mismatch"
            assert plain_dbl not in bp2 and cipher_dbl not in ap2
            counts["crypto"] += 1
        rows.append(row)
    if not check:
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
    return counts


def main() -> None:
    check = "--check" in sys.argv
    total = {"article": 0, "crypto": 0}
    for fname in ("question_pair_incoherence.jsonl", "cryptographic_payload.jsonl"):
        counts = fix_file(CASES_DIR / fname, check)
        for k, v in counts.items():
            total[k] += v
        print(f"{fname}: {counts} {'(check only)' if check else '(written)'}")
    print("total:", total)


if __name__ == "__main__":
    main()
