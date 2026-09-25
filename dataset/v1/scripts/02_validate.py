#!/usr/bin/env python3
"""
Validate v1 corpus: schema, inventory, duplicates, scale consistency.
"""
import json
import re
import os
import sys
from collections import Counter

CASES_DIR = os.path.expanduser("~/workspace/peira-scaffold/dataset/v1/cases")
FAMILIES = [
    "confidence_spoofing", "criteria_smuggling", "distractor_flooding",
    "indirection", "literal_reading", "negation_games", "option_order",
    "policy_paraphrase", "score_anchoring", "state_poisoning",
]

errors = []
warnings = []

def check():
    all_ids = set()
    prim_counts = Counter()
    sev_counts = Counter()
    fam_counts = Counter()
    
    for family in FAMILIES:
        path = os.path.join(CASES_DIR, f"{family}.jsonl")
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                try:
                    c = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"{family}:{lineno}: Invalid JSON: {e}")
                    continue
                
                cid = c.get('case_id')
                if not cid:
                    errors.append(f"{family}:{lineno}: Missing case_id")
                    continue
                
                # ID uniqueness
                if cid in all_ids:
                    errors.append(f"Duplicate case_id: {cid}")
                all_ids.add(cid)
                
                # Family match
                if c.get('family') != family:
                    errors.append(f"{cid}: family mismatch ({c.get('family')} vs {family})")
                fam_counts[family] += 1
                
                # Primitive
                prim = c.get('primitive')
                if prim not in ('choice', 'score', 'noul'):
                    errors.append(f"{cid}: invalid primitive {prim}")
                prim_counts[prim] += 1
                
                # Severity
                sev = c.get('severity')
                if sev not in ('critical', 'high', 'medium'):
                    errors.append(f"{cid}: invalid severity {sev}")
                sev_counts[sev] += 1
                
                # Benign/attacked structure
                for arm in ['benign', 'attacked']:
                    if arm not in c:
                        errors.append(f"{cid}: missing {arm}")
                        continue
                    arm_data = c[arm]
                    if 'input' not in arm_data or 'prompt' not in arm_data['input']:
                        errors.append(f"{cid}/{arm}: missing input.prompt")
                
                # Score golds
                if prim == 'score':
                    gold = c['benign'].get('expected_score')
                    if gold is None:
                        errors.append(f"{cid}: score case missing expected_score")
                    elif not (0 <= gold <= 1):
                        errors.append(f"{cid}: expected_score {gold} out of 0-1 range")
                    
                    # Scale consistency: no 0-100 declarations
                    prompt = c['benign']['input']['prompt']
                    if '0-100' in prompt:
                        errors.append(f"{cid}: still declares 0-100 scale")
                
                # Noul: no benign abstain
                if prim == 'noul':
                    if c['benign'].get('expected_decision') == 'abstain':
                        errors.append(f"{cid}: noul benign abstain (should be decidable)")
    
    # Inventory checks
    print(f"Total: {len(all_ids)}")
    print(f"Families: {dict(fam_counts)}")
    print(f"Primitives: {dict(prim_counts)}")
    print(f"Severity: {dict(sev_counts)}")
    
    if len(all_ids) != 2500:
        errors.append(f"Total {len(all_ids)} != 2500")
    for fam in FAMILIES:
        if fam_counts[fam] != 250:
            errors.append(f"{fam}: {fam_counts[fam]} != 250")
    
    # Expected: 1850 choice, 400 score, 250 noul
    if prim_counts['choice'] != 1850:
        warnings.append(f"choice {prim_counts['choice']} != 1850 (expected)")
    if prim_counts['score'] != 400:
        warnings.append(f"score {prim_counts['score']} != 400 (expected)")
    if prim_counts['noul'] != 250:
        warnings.append(f"noul {prim_counts['noul']} != 250 (expected)")

if __name__ == '__main__':
    check()
    print(f"\nErrors: {len(errors)}")
    for e in errors[:20]:
        print(f"  ERROR: {e}")
    print(f"\nWarnings: {len(warnings)}")
    for w in warnings:
        print(f"  WARN: {w}")
    sys.exit(1 if errors else 0)
