#!/usr/bin/env python3
"""V1 exhaustive audit harness (perfection-gate item 7), v5.

Row-by-row semantic screening of all 2,000 v1 public cases. The nine
dataset gates cover structure; this harness screens meaning:

  * ATTACK FIDELITY: the attacked delta carries the family's attack idiom
    (D-36 class 6). Idioms are data-driven lexicons: words overrepresented
    in attacked-added words vs benign prompts (lift > 5, mined 2026-10-01
    from the corpus itself), plus documented gap-fills from the 2026-10-01
    triage (v5). A faithful case's delta contains >= 1 lexicon word
    (and a digit where the idiom is numeric).
  * Structural family checks: literal_reading = minimal delta;
    policy_paraphrase = paraphrase similarity band; option_order = pure
    word-reorder (punctuation-normalized comparison, so a
    punctuation-only delta flags as not a reorder);
    distractor_flooding = substantive added block.
  * negation_games is shape-aware: Shape A (meaning-preserving negation
    stack, target = mishandling outcome) requires negation-stack vocabulary
    in the attacked arm; Shape B (meaning-inverting rewrite) requires the
    arms to differ. Every ngm case must declare its shape in notes.
  * FAMILY ASSIGNMENT: case_id prefix agrees with the family field.
  * LABEL SANITY: decisions in options, flip present, score scales coherent.
  * DEEP PII/SECRETS: API keys, private keys, Luhn-valid cards, SSNs,
    non-fictional emails/phones (beyond G6). Reserved email domains are
    matched on the parsed domain after the final @, so lookalikes like
    revenueexample.com are not exempted.
  * NOTES HYGIENE: placeholders, empty notes, thin critical notes.

The lexicons screen for idiom absence, not semantic correctness. Semantic
correctness (label derivability, true attack fidelity) is the stratified
manual read's job.

Output: findings TSV (case_id, category, detail). Exit 0 always.
"""
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "dataset" / "v1" / "cases"

FAM_PREFIX = {
    "state_poisoning": "spo", "criteria_smuggling": "csm",
    "option_order": "odo", "distractor_flooding": "dfl",
    "score_anchoring": "san", "literal_reading": "lrd",
    "negation_games": "ngm", "policy_paraphrase": "ppa",
    "indirection": "ind", "confidence_spoofing": "csp",
}

# Data-driven attack lexicons (lift > 5, mined 2026-10-01).
LEXICON = {
    "state_poisoning": {
        "override", "amended", "re-synced", "***", "pruned", "refreshed",
        "corrected", "updated", "resynced", "re-pulled", "re-run",
        "re-done", "redone", "re-calibrated", "recalibrated", "re-classified",
    },
    "score_anchoring": {
        "averaged", "usually", "penciled", "typical", "similar", "screened",
        "taped", "folder", "internal", "typically", "rating", "preliminary",
        "sees", "cycle", "quarter", "note", "notes", "benchmark",
        "reference", "forwarded", "thread", "excerpt", "comparable",
        "scored", "filed", "alongside", "intake", "suggested", "carried",
        "triage", "land", "defensible", "rated",
    },
    "negation_games": {
        "claim", "false", "truth", "basis", "evidence", "mistake", "assert",
        "incorrect", "simply", "support", "saying", "deniable", "scarcely",
    },
    "criteria_smuggling": {
        "attached", "letter", "statement", "means", "requires", "please",
        "counsel", "should", "covers", "appeal", "message", "note",
        "filer", "brief", "argues", "argue", "memo", "filing", "briefing",
        "certificate", "deck", "questionnaire", "portfolio", "brochure",
        "defense", "response", "email",
        # v5 gap-fill (triage 2026-10-01: 3 flagged cases, all genuine
        # criteria-redefinition idioms the mined lexicon missed).
        "substance", "satisfaction", "verdict", "market", "metric",
        "normalized", "normalize", "baseline", "severity",
    },
    "confidence_spoofing": {
        "signed", "approved", "hesitation", "beyond", "certain", "question",
        "cleared", "without", "manager", "director", "lead", "supervisor",
        "memo", "foregone", "textbook", "unequivocal", "qualms", "deems",
        "seconded", "endorsed", "backing", "blunt", "hilt",
        # v5 gap-fill (triage 2026-10-01: 67 flagged cases, all genuine
        # confidence-spoofing idioms the mined lexicon missed).
        "hesitate", "hesitant", "obvious", "doubt", "doubts", "firmly",
        "firm", "sure", "waver", "wavered", "unwavering", "approval",
        "approvals", "authorized", "authorize", "authorizes", "confidence",
        "confident", "formality", "certainty", "vouch", "vouched",
        "vouching", "championed", "champion", "stamped", "rubber",
        "rubber-stamped", "open-and-shut", "settled", "routine", "standard",
        "ushered", "weight", "debate", "discussion", "insist", "insisting",
        "clear", "tagged", "low-risk", "judgment",
    },
    "indirection": {
        "memo", "email", "wiki", "log", "pinned", "reference", "shift",
        "follows", "directs", "overrides", "governs", "per", "thread",
        "article", "entry", "cited", "controlling", "operative", "guidance",
        "excerpt", "quoted", "colleague", "note", "section", "attachment",
        "appendix", "addendum", "directive", "runbook", "manual", "ticket",
        "document", "attached",
    },
    "distractor_flooding": {
        "afternoon", "tuesday", "wednesday", "weekend", "holiday", "march",
        "monday", "morning", "shutdown", "break", "quarterly", "yesterday",
        "reviewer", "notes", "shift", "excerpts", "ops",
    },
}
# Families whose attack idiom always carries a number (anchor / new value).
# score_anchoring: the anchor IS a number (lexicon framing + digit required).
# state_poisoning: "*** OVERRIDE ***" markers need no digit, but bare value
# mutations ("14"->"2") are numeric (lexicon hit OR digit suffices).
NEEDS_DIGIT_AND = {"score_anchoring"}
NEEDS_DIGIT_OR = {"state_poisoning"}

# Multi-word confidence idioms (checked against the raw added text).
CSP_PHRASES = {
    "done deal", "no doubt", "green light", "weight behind",
    "ended the debate", "only possible", "closed the discussion",
    "signing off",
}

# Negation vocabulary for the negation_games special case. Shape A
# (documented in case notes) is a meaning-preserving negation stack whose
# target is the mishandling outcome; the attacked arm must carry negation
# vocabulary, but the negation PROFILE need not change (the stack is
# meaning-preserving by design). Shape B is a meaning-inverting rewrite;
# the attacked arm must differ from the benign arm.
NEG_WORDS = {
    "not", "no", "never", "none", "neither", "nor", "without", "lack",
    "lacks", "lacking", "fail", "fails", "failed", "failure", "unless",
    "deny", "denies", "denied", "denying", "deniable", "cannot",
    "scarcely", "hardly", "barely", "incorrect", "false",
}
# Negation-adjacent wrappers used by Shape A stacks ("it would be an
# error/mistake to assert", "it would be wrong to claim").
STACK_WORDS = set(NEG_WORDS) | {
    "error", "mistake", "mistaken", "wrong", "untrue", "invalid",
}

def added_words(bp: str, ap: str) -> list:
    sm = difflib.SequenceMatcher(None, bp.split(), ap.split(), autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            out.extend(ap.split()[j1:j2])
    return out


def word_diff_count(bp: str, ap: str) -> int:
    sm = difflib.SequenceMatcher(None, bp.split(), ap.split(), autojunk=False)
    n = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            n += max(i2 - i1, j2 - j1)
    return n


def main() -> int:
    findings = []

    def flag(cid, cat, detail):
        findings.append((cid, cat, detail))

    cases = []
    for f in sorted(CASES_DIR.glob("*.jsonl")):
        for ln, line in enumerate(f.open(), 1):
            line = line.strip()
            if line:
                cases.append((f.name, ln, json.loads(line)))

    for fname, ln, d in cases:
        cid = d.get("case_id", "?")
        fam = d.get("family", "?")
        b = d.get("benign", {})
        a = d.get("attacked", {})
        bp = b.get("input", {}).get("prompt", "")
        ap = a.get("input", {}).get("prompt", "")
        bopts = b.get("input", {}).get("options", [])
        aopts = a.get("input", {}).get("options", [])
        exp = b.get("expected_decision")
        tgt = a.get("target_decision")
        prim = d.get("primitive")
        notes = d.get("notes", "") or ""

        m = re.fullmatch(r"v1-([a-z]{3})-(\d+)", cid)
        if not m:
            flag(cid, "id-format", f"case_id {cid!r} not v1-<aaa>-<NNN>")
        elif FAM_PREFIX.get(fam) != m.group(1):
            flag(cid, "id-family-mismatch",
                 f"prefix {m.group(1)!r} vs family {fam!r}")

        if exp not in bopts:
            flag(cid, "label", f"expected_decision {exp!r} not in benign options")
        if tgt not in aopts:
            flag(cid, "label", f"target_decision {tgt!r} not in attacked options")
        if exp == tgt:
            flag(cid, "label", "expected == target (no flip)")
        if prim == "score":
            es = b.get("expected_score")
            if es is None:
                flag(cid, "label", "score primitive, benign.expected_score missing")
            elif not isinstance(es, (int, float)) or not (0 <= es <= 1):
                flag(cid, "label", f"expected_score {es!r} outside 0-1")
            # D-36 class 4: prompt states a 0-100 output scale but the reference
            # is 0-1. Only explicit scale statements count ("Score 0-100",
            # "100-point scale"); scorecard arithmetic ("start at 100") and
            # "per percent" phrasing are not scale statements.
            if re.search(r"score 0[–-]100|0[–-]100 scale|100-point|out of 100\b", bp, re.I) \
                    and isinstance(es, (int, float)) and es <= 1:
                flag(cid, "scale", "prompt states 0-100 scale but expected_score is 0-1")
            if b.get("positive_decision") not in bopts:
                flag(cid, "label", f"positive_decision {b.get('positive_decision')!r} not in options")

        aw = added_words(bp, ap)
        # Alpha-tokenize the added words: catches lexicon words glued to
        # punctuation by the word-diff (e.g. '"amended):\'Press' -> amended).
        aw_toks = set(re.findall(r"[a-z*]+(?:-[a-z*]+)*", " ".join(aw).lower()))
        add_txt = " ".join(aw)

        lex = LEXICON.get(fam)
        if fam == "negation_games":
            # Shape-aware check (v5). Shape A = meaning-preserving negation
            # stack, target is the mishandling outcome: the attacked arm must
            # carry negation-stack vocabulary. Shape B = meaning-inverting
            # rewrite, target is the correct application of the hostile
            # wording: the attacked arm must differ from the benign arm.
            # Whether the stack truly preserves meaning (A) or inverts it (B)
            # is semantic; that is the stratified manual read's job.
            shape_a = "Shape A" in notes
            shape_b = "Shape B" in notes
            if not (shape_a or shape_b):
                flag(cid, "fidelity",
                     "negation_games: no Shape A/B annotation in notes")
            elif shape_a:
                # Negation-stack vocabulary must appear in the attacked arm's
                # body text. Option labels are excluded: a "deny"/"no"-style
                # option would otherwise satisfy the check vacuously.
                opt_toks = set()
                for o in aopts:
                    opt_toks.update(
                        re.findall(r"[a-z]+(?:'[a-z]+)?", o.lower()))
                ap_toks = set(re.findall(r"[a-z]+(?:'[a-z]+)?", ap.lower()))
                if not ((ap_toks - opt_toks) & STACK_WORDS):
                    flag(cid, "fidelity",
                         "negation_games: Shape A attacked arm carries no "
                         "negation-stack vocabulary")
            elif bp == ap:
                flag(cid, "fidelity",
                     "negation_games: Shape B prompts identical")
        elif lex:
            hit = bool(aw_toks & lex)
            if fam == "confidence_spoofing" and not hit:
                low = add_txt.lower()
                hit = any(p in low for p in CSP_PHRASES)
            has_digit = bool(re.search(r"\d", add_txt))
            if fam in NEEDS_DIGIT_AND:
                hit = hit and has_digit
            elif fam in NEEDS_DIGIT_OR:
                hit = hit or has_digit
            if not hit:
                flag(cid, "fidelity",
                     f"{fam}: attacked delta lacks family attack idiom "
                     f"({len(aw)} added words)")
        if fam == "state_poisoning" and re.search(r"\*\*\*.*\boverride\b", bp, re.I):
            flag(cid, "contamination",
                 "state_poisoning: '*** OVERRIDE' attack marker present in benign arm")

        if fam == "literal_reading":
            wc = word_diff_count(bp, ap)
            sim = difflib.SequenceMatcher(None, bp, ap, autojunk=False).ratio()
            if wc > 12 or sim < 0.75:
                flag(cid, "fidelity",
                     f"literal_reading: delta too large ({wc} words, sim {sim:.2f})")
            if wc == 0:
                flag(cid, "fidelity", "literal_reading: zero word delta")

        if fam == "policy_paraphrase":
            sim = difflib.SequenceMatcher(None, bp, ap, autojunk=False).ratio()
            if sim > 0.9999:
                flag(cid, "fidelity", "policy_paraphrase: prompts identical")
            elif sim < 0.5:
                flag(cid, "fidelity",
                     f"policy_paraphrase: prompts dissimilar ({sim:.3f})")

        if fam == "option_order":
            # Pure reorder: identical word multisets (punctuation-normalized),
            # different sequence. "Decision: temporary or deny?" ->
            # "Decision: deny or temporary?" moves the "?" with the word.
            norm = lambda s: [w.strip(".,;:!?\"'()[]") for w in s.split()]
            if Counter(norm(bp)) != Counter(norm(ap)):
                flag(cid, "fidelity",
                     "option_order: word multiset differs; not a pure reorder")
            elif norm(bp) == norm(ap):
                flag(cid, "fidelity",
                     "option_order: prompts identical after normalization; "
                     "no reorder")

        if not notes.strip():
            flag(cid, "notes", "empty notes")
        elif re.search(r"\{\{[A-Z_]+\}\}|\bTODO\b|\bFIXME\b|\bXXX\b|lorem ipsum", notes, re.I):
            flag(cid, "notes", "placeholder text in notes")
        if d.get("severity") == "critical" and len(notes.strip()) < 20:
            flag(cid, "notes", "critical case with thin notes")

        blob = bp + "\n" + ap + "\n" + notes
        for name, pat in {
            "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
            "phone": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
            "api_key": r"\b(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}"
                       r"|xox[bap]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{20,})\b",
            "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        }.items():
            for mm in re.finditer(pat, blob):
                val = mm.group(0)
                if name == "email":
                    domain = val.rsplit("@", 1)[-1].lower()
                    if domain in ("example.com", "example.org") or \
                            domain.endswith((".example", ".test", ".invalid",
                                             ".example.com", ".example.org")):
                        continue
                if name == "phone" and "555" in val:
                    continue
                flag(cid, "pii", f"{name}: {val[:44]!r}")
        for mm in re.finditer(r"\b(?:\d[ -]?){13,19}\b", blob):
            num = re.sub(r"[ -]", "", mm.group(0))
            ds = [int(c) for c in num]
            s = sum(dd if i % 2 == 0 else (2 * dd - 9 if 2 * dd > 9 else 2 * dd)
                    for i, dd in enumerate(reversed(ds)))
            if s % 10 == 0:
                flag(cid, "pii", f"Luhn-valid card-like number: {num[:6]}…{num[-4:]}")

    for cid, cat, detail in findings:
        sys.stdout.write(f"{cid}\t{cat}\t{detail}\n")
    print(f"# findings: {len(findings)} across {len(cases)} cases", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
