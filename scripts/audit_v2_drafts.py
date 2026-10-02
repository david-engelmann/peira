#!/usr/bin/env python3
"""Row-by-row audit of the v2 draft case files (perfection gate item 8).

Checks every case in dataset/v2/cases/*.jsonl (benign + attacked arms):
  1. JSON line parse, no blank lines, no trailing whitespace
  2. Exact key set, types, allowed severity/primitive values
  3. case_id format, per-family prefix, dense numbering, global uniqueness
  4. family field matches containing file
  5. Label correctness: expected_decision in benign options,
     target_decision in attacked options, target != expected
  6. attacked prompt differs from benign prompt
  7. Per-family attack-fidelity heuristics (payload present in attacked arm)
  8. Benign-arm contamination (attack payload must not appear in benign)
  9. Exact + normalized near-duplicate detection (per family and cross-family)
 10. PII / secret leakage scan (email, phone, SSN, API keys, URLs)
 11. notes field present and non-trivial
 12. manifest.json sha256 + n_cases reconciliation
 13. Severity / primitive balance tables per family

Findings written as JSON to --out (default: hidden_files/v2-draft-audit-findings.json)
plus a human-readable summary on stdout.

Usage: python3 scripts/audit_v2_drafts.py [--out PATH]

Mechanical fixes are applied by scripts/apply_v2_audit_fixes.py (used ONLY
for defects verified by hand).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "dataset" / "v2" / "cases"

FILES = {
    "verbosity_inflation": "v2-verb",
    "retrieval_poisoning": "v2-retp",
    "evidence_positioning": "v2-evpos",
    "crosslingual_shift": "v2-xling",
    "judge_sycophancy": "v2-jsp",
}

TOP_KEYS = {"case_id", "family", "primitive", "severity", "benign", "attacked", "notes"}
SEVERITIES = {"low", "medium", "high", "critical"}
PRIMITIVES = {"choice", "score", "abstain"}
ID_RE = re.compile(r"^v2-[a-z]+-\d{4}$")

LANG_NAMES = (r"Spanish|French|German|Italian|Portuguese|Dutch|Chinese|Mandarin|Japanese|"
              r"Arabic|Russian|Korean|Hindi|Turkish|Polish|Swedish|Norwegian|Danish|"
              r"Finnish|Czech|Greek|Hebrew|Thai|Vietnamese|Indonesian|Malay|Urdu|"
              r"Romanian|Hungarian")
XLANG_PAYLOAD = re.compile(r"(?:\[(?:" + LANG_NAMES + r")(?: instruction| note| comment| request)s?:\]"
                           r"|\((?:" + LANG_NAMES + r")\):|[^\x00-\x7F])", re.IGNORECASE)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
KEY_RE = re.compile(
    r"(sk-(?:live|test)-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|"
    r"xox[bap]-.{8,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"Bearer\s+[A-Za-z0-9\-._~+/]{20,})"
)
URL_RE = re.compile(r"https?://[^\s\)'\"]{4,}")

# Family attack markers: (marker_regex_for_attacked, banned_in_benign, description).
# A None marker means "no mechanical marker check" for that slot.
FAMILY_MARKERS = {
    "crosslingual_shift": (
        XLANG_PAYLOAD,
        XLANG_PAYLOAD,
        "non-English payload (language-tagged instruction or non-ASCII text) in attacked prompt; benign must have none",
    ),
    "retrieval_poisoning": (
        re.compile(r"\[retrieved", re.IGNORECASE),
        re.compile(r"\[retrieved", re.IGNORECASE),
        "'[Retrieved ...]' block in attacked prompt; absent from benign",
    ),
    "verbosity_inflation": (
        None,  # checked separately via length ratio below
        None,
        "verbosity padding (attacked prompt much longer than benign)",
    ),
    "evidence_positioning": (None, None, "position-shifted evidence (mechanical diff only)"),
    "judge_sycophancy": (
        re.compile(r'\[[^\]]{3,80}: "', re.IGNORECASE),
        re.compile(r'\[[^\]]{3,80}: "', re.IGNORECASE),
        "sycophancy payload: bracketed quoted third-party note in attacked prompt; absent from benign",
    ),
}

NONASCII_SAMPLE = re.compile(r"[^\x00-\x7F]+")


def load_cases():
    cases = []
    parse_errors = []
    for family in sorted(FILES):
        path = CASES_DIR / f"{family}.jsonl"
        if not path.exists():
            parse_errors.append({"file": f"{family}.jsonl", "issue": "FILE MISSING"})
            continue
        for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line != line.rstrip():
                parse_errors.append(
                    {"file": f"{family}.jsonl", "line": ln, "issue": "trailing whitespace"}
                )
            if not line.strip():
                parse_errors.append(
                    {"file": f"{family}.jsonl", "line": ln, "issue": "blank line"}
                )
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                parse_errors.append(
                    {"file": f"{family}.jsonl", "line": ln, "issue": f"JSON parse: {e}"}
                )
                continue
            row["_file"] = family
            row["_line"] = ln
            cases.append(row)
    return cases, parse_errors


def norm_prompt(p: str) -> str:
    p = p.lower()
    p = re.sub(r"[^\w\s]", " ", p)
    return re.sub(r"\s+", " ", p).strip()


def audit():
    findings = defaultdict(list)
    cases, parse_errors = load_cases()
    for e in parse_errors:
        findings["parse"].append(e)

    seen_ids = {}
    seen_num = defaultdict(set)
    attacked_seen = {}
    attacked_norm_seen = {}
    benign_seen = {}
    stats = defaultdict(Counter)

    for c in cases:
        cid = c.get("case_id", "?")
        fam = c["_file"]
        line = c["_line"]

        def f(issue, detail="", severity="defect"):
            findings[fam].append(
                {"case_id": cid, "line": line, "issue": issue,
                 "detail": detail, "severity": severity}
            )

        # keys
        if set(c.keys()) - {"_file", "_line"} != TOP_KEYS:
            f("key-set", f"keys={sorted(set(c.keys()) - {'_file','_line'})}")
        # id
        prefix = FILES[fam]
        m = ID_RE.match(cid or "")
        if not m or not cid.startswith(prefix + "-"):
            f("case-id", f"id={cid!r} expected {prefix}-NNNN")
        else:
            n = int(cid.rsplit("-", 1)[1])
            seen_num[fam].add(n)
            if cid in seen_ids:
                f("duplicate-case-id", f"also in {seen_ids[cid]}")
            seen_ids[cid] = f"{fam}:{line}"
        if c.get("family") != fam:
            f("family-mismatch", f"field={c.get('family')!r} file={fam}")
        if c.get("severity") not in SEVERITIES:
            f("severity", f"value={c.get('severity')!r}")
        if c.get("primitive") not in PRIMITIVES:
            f("primitive", f"value={c.get('primitive')!r}")

        stats[fam]["severity:" + str(c.get("severity"))] += 1
        stats[fam]["primitive:" + str(c.get("primitive"))] += 1

        ben, atk = c.get("benign"), c.get("attacked")
        prim = c.get("primitive")
        # established arm shapes (v1): choice/abstain benign {input, expected_decision};
        # score benign {input, expected_decision, expected_score, positive_decision};
        # attacked always {input, target_decision}
        benign_shape = {"input", "expected_decision"} | (
            {"expected_score", "positive_decision"} if prim == "score" else set()
        )
        if not isinstance(ben, dict) or set(ben.keys()) != benign_shape:
            f("benign-shape", f"keys={sorted(ben.keys()) if isinstance(ben,dict) else type(ben)}")
            continue
        attacked_shape = {"input", "target_decision"} | (
            # target_score: optional generator-authored flip target for score cases
            {"target_score"} if prim == "score" and isinstance(atk, dict)
            and "target_score" in atk else set()
        )
        if not isinstance(atk, dict) or set(atk.keys()) != attacked_shape:
            f("attacked-shape", f"keys={sorted(atk.keys()) if isinstance(atk,dict) else type(atk)}")
            continue
        if prim == "score":
            es = ben.get("expected_score")
            if not isinstance(es, (int, float)) or not 0 <= es <= 1:
                f("expected-score", f"value={es!r} (must be 0..1)")
            ts = atk.get("target_score")
            if ts is not None:
                if not isinstance(ts, (int, float)) or not 0 <= ts <= 1:
                    f("target-score", f"value={ts!r} (must be 0..1)")
                elif isinstance(es, (int, float)) and ts >= es:
                    f("target-score", f"target_score={ts} >= expected_score={es} (no downward pull)")
            pd_ = ben.get("positive_decision")
            if pd_ != ben.get("expected_decision"):
                f("positive-decision", f"positive_decision={pd_!r} != expected_decision={ben.get('expected_decision')!r}")
        bi, ai = ben.get("input"), atk.get("input")
        for arm_name, arm in (("benign", bi), ("attacked", ai)):
            if not isinstance(arm, dict) or "prompt" not in arm:
                f(f"{arm_name}-input", "missing prompt")
            elif not isinstance(arm["prompt"], str) or not arm["prompt"].strip():
                f(f"{arm_name}-input", "empty prompt")
            if "options" in arm:
                opts = arm["options"]
                if not isinstance(opts, list) or len(opts) < 2 or any(
                    not isinstance(o, str) or not o.strip() for o in opts
                ):
                    f(f"{arm_name}-options", f"value={opts!r}")
        if not isinstance(bi, dict) or not isinstance(ai, dict):
            continue
        bp, ap = bi.get("prompt", ""), ai.get("prompt", "")
        bopts, aopts = bi.get("options"), ai.get("options")
        exp, tgt = ben.get("expected_decision"), atk.get("target_decision")

        # label correctness
        if isinstance(bopts, list) and exp not in bopts:
            f("label", f"expected_decision={exp!r} not in benign options {bopts!r}")
        if isinstance(aopts, list) and tgt not in aopts:
            f("label", f"target_decision={tgt!r} not in attacked options {aopts!r}")
        if exp is not None and tgt is not None and exp == tgt:
            f("non-flip", f"expected==target=={exp!r}", severity="review")

        # attack presence / arm difference
        if bp == ap:
            f("identical-arms", "attacked prompt identical to benign prompt")

        # family markers
        marker, banned_benign, desc = FAMILY_MARKERS[fam]
        if marker is not None:
            if not marker.search(ap or ""):
                f("attack-marker-missing", desc, severity="review")
        if banned_benign is not None and banned_benign.search(bp or ""):
            f("benign-contamination", desc, severity="review")

        # family-specific mechanical checks
        if fam == "verbosity_inflation":
            ratio = len(ap) / max(1, len(bp)) if bp and ap else 0
            if ratio < 2.0:
                f("verbosity-delta", f"attacked_len={len(ap)} benign_len={len(bp)} ratio={ratio:.2f}",
                  severity="review")
        # dedup: attacked-prompt duplicates are defects; benign-prompt sharing
        # within a family is by design (benign twins), cross-family sharing is not
        if ap:
            if ap in attacked_seen:
                f("dup-attacked", f"identical attacked prompt as {attacked_seen[ap]}")
            else:
                attacked_seen[ap] = cid
            np_ = norm_prompt(ap)
            if np_ in attacked_norm_seen:
                f("near-dup-attacked", f"normalized-identical attacked prompt as {attacked_norm_seen[np_]}",
                  severity="review")
            else:
                attacked_norm_seen[np_] = cid
        if bp:
            key = (fam, bp)
            if bp in benign_seen:
                if benign_seen[bp][0] == fam:
                    f("dup-benign-same-family", f"identical benign prompt as {benign_seen[bp][1]}",
                      severity="review")
                else:
                    # accepted design: families share a small pool of benign scenarios
                    # (e.g. v2-jsp-0001/v2-retp-0001); logged as an observation
                    f("dup-benign-cross-family", f"identical benign prompt as {benign_seen[bp][1]} "
                                                f"(family {benign_seen[bp][0]}); accepted shared scenario",
                      severity="review")
            else:
                benign_seen[bp] = (fam, cid)

        # PII / secrets on both arms
        for arm_name, p in (("benign", bp), ("attacked", ap)):
            if not p:
                continue
            if EMAIL_RE.search(p):
                f("pii-email", f"{arm_name} arm: {EMAIL_RE.search(p).group(0)[:40]}", severity="review")
            if SSN_RE.search(p):
                f("pii-ssn", f"{arm_name} arm", severity="review")
            if KEY_RE.search(p):
                f("secret", f"{arm_name} arm: {KEY_RE.search(p).group(0)[:20]}...", severity="review")
            if URL_RE.search(p):
                f("url", f"{arm_name} arm: {URL_RE.search(p).group(0)[:60]}", severity="review")
            ph = PHONE_RE.search(p)
            if ph:
                f("pii-phone", f"{arm_name} arm: {ph.group(0)}", severity="review")

        # notes
        notes = c.get("notes", "")
        if not isinstance(notes, str) or len(notes.strip()) < 40:
            f("notes", "missing or too short")

    # dense numbering
    for fam, prefix in FILES.items():
        n = len([c for c in cases if c["_file"] == fam])
        nums = seen_num[fam]
        missing = [i for i in range(1, n + 1) if i not in nums]
        extra = sorted(nums - set(range(1, n + 1)))
        if missing:
            findings[fam].append({"case_id": "-", "line": 0, "issue": "numbering-gap",
                                  "detail": f"missing numbers: {missing[:10]}", "severity": "defect"})
        if extra:
            findings[fam].append({"case_id": "-", "line": 0, "issue": "numbering-extra",
                                  "detail": f"out-of-range: {extra[:10]}", "severity": "defect"})

    # manifest reconciliation
    manifest = json.loads((CASES_DIR / "manifest.json").read_text(encoding="utf-8"))
    for fname, meta in manifest.get("files", {}).items():
        p = CASES_DIR / fname
        if not p.exists():
            findings["manifest"].append({"case_id": "-", "line": 0, "issue": "file-missing",
                                         "detail": fname, "severity": "defect"})
            continue
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        if sha != meta.get("sha256"):
            findings["manifest"].append({"case_id": "-", "line": 0, "issue": "sha-mismatch",
                                         "detail": f"{fname}: manifest {str(meta.get('sha256'))[:12]} "
                                                   f"actual {sha[:12]}", "severity": "defect"})
        n_actual = sum(1 for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
        if n_actual != meta.get("n_cases"):
            findings["manifest"].append({"case_id": "-", "line": 0, "issue": "count-mismatch",
                                         "detail": f"{fname}: manifest {meta.get('n_cases')} actual {n_actual}",
                                         "severity": "defect"})

    return findings, stats, len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    findings, stats, total = audit()
    n_def = sum(1 for fs in findings.values() for x in fs if x["severity"] == "defect")
    n_rev = sum(1 for fs in findings.values() for x in fs if x["severity"] == "review")
    print(f"cases audited: {total} (benign+attacked arms: {total*2})")
    print(f"findings: {len(findings)} groups, {n_def} defects, {n_rev} needs-review")
    for fam in sorted(stats):
        print(f"  {fam}: " + ", ".join(f"{k}={v}" for k, v in sorted(stats[fam].items())))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"findings": dict(findings)}, indent=1), encoding="utf-8")
        print("findings written to", args.out)
    # print review items briefly
    for fam, fs in findings.items():
        revs = [x for x in fs if x["severity"] == "review"]
        defs = [x for x in fs if x["severity"] == "defect"]
        if defs:
            print(f"\nDEFECTS {fam}:")
            for x in defs[:30]:
                print(f"  {x['case_id']}:{x['line']} {x['issue']} {x['detail']}")
            if len(defs) > 30:
                print(f"  ... and {len(defs)-30} more")
        if revs:
            print(f"\nREVIEW {fam} ({len(revs)}):")
            by_issue = Counter(x["issue"] for x in revs)
            for k, v in by_issue.most_common():
                print(f"  {k}: {v}")
                for x in revs[:3]:
                    if x["issue"] == k:
                        print(f"    {x['case_id']} {x['detail'][:120]}")
                        break


if __name__ == "__main__":
    main()
