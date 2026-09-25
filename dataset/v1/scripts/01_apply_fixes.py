#!/usr/bin/env python3
"""
Apply reconciliation fixes to v1 provisional corpus.

Fixes applied (all documented, deterministic):
1. Scale conversion: 42 score cases declare "(0-100" but have 0-1 golds.
   Convert prompts to 0-1 scale (e.g., "0-100" -> "0-1", "70 or above" -> "0.70 or above").
   Direction matches v2 (canonical scale is 0-1).

2. Noul gold corrections: 123 Noul cases have benign expected_decision="abstain"
   but the case is actually decidable. Replace with v2's reviewed versions
   (same case IDs, corrected prompts and golds).

3. K-4401 duplicates: v1-ppa-031, v1-ppa-038, v1-ppa-127 duplicate v1-csm-023
   (same $95k storm damage scenario). Replace with v2's rewritten versions.

Source: sealed-v1/input/ (base) + sealed-v2/input/ (fixes)
Output: dataset/v1/cases/<family>.jsonl (250 each, 2500 total)

This script is deterministic: same inputs -> byte-identical outputs.
"""

import json
import re
import os
import sys

V1_INPUT = os.path.expanduser("~/workspace/goals/peira-decision-model-robustness-benchmark/hidden_files/sealed-v1/input")
V2_INPUT = os.path.expanduser("~/workspace/goals/peira-decision-model-robustness-benchmark/hidden_files/sealed-v2/input")
OUTPUT_DIR = os.path.expanduser("~/workspace/peira-scaffold/dataset/v1/cases")

FAMILIES = [
    "confidence_spoofing", "criteria_smuggling", "distractor_flooding",
    "indirection", "literal_reading", "negation_games", "option_order",
    "policy_paraphrase", "score_anchoring", "state_poisoning",
]

def convert_scale(prompt: str) -> str:
    """
    Convert 0-100 scale declarations to 0-1 in score-primitive prompts.
    
    Handles:
    - "(0-100, ...)" -> "(0-1, ...)"
    - "(0-100)" -> "(0-1)"
    - "X 0-100;" / "X 0-100," -> "X 0-1;" / "X 0-1,"
    - "X 0-100 (" -> "X 0-1 ("
    - "X 0-100 scale" -> "X 0-1 scale"
    - "X 0-100 for/on" -> "X 0-1 for/on"
    - Thresholds: "at 70", "below 70", "above 70", "70+", "70 or above" -> 0-1 form
    
    Only for score-primitive cases where 0-100 is the output scale.
    Domain numbers (BMI, age, etc.) are not in "0-100" form, so safe.
    """
    result = prompt
    
    # Step 1: Replace all "0-100" scale declarations with "0-1"
    # These patterns cover the observed variants
    result = re.sub(r'\(0-100,\s*([^)]+)\)', r'(0-1, \1)', result)
    result = re.sub(r'\(0-100\)', '(0-1)', result)
    # "Risk score 0-100 (" -> "Risk score 0-1 ("
    result = re.sub(r'(\b\w[\w\s]*?)\s+0-100(\s*\()', r'\1 0-1\2', result)
    # "Reliability 0-100;" -> "Reliability 0-1;"
    result = re.sub(r'(\b\w+)\s+0-100([;,])', r'\1 0-1\2', result)
    # "on our 0-100 scale" -> "on our 0-1 scale"
    result = re.sub(r'0-100(\s+scale)', r'0-1\1', result)
    # "score the applicant 0-100 for" -> "score the applicant 0-1 for"
    result = re.sub(r'0-100(\s+(?:for|on)\s)', r'0-1\1', result)
    # Catch-all: standalone "0-100" (word boundaries)
    result = re.sub(r'\b0-100\b', '0-1', result)
    
    # Step 2: Convert threshold numbers (10-100) to 0-1 form
    # Patterns: "at 70", "below 70", "above 70", "70+", "70 or above", "70 or below"
    def repl_threshold(m):
        prefix = m.group(1)  # "at", "below", etc.
        space = m.group(2)   # the whitespace
        num = int(m.group(3))
        suffix = m.group(4) or ""  # " or above", "+", etc. (may be None)
        if 10 <= num <= 100:
            converted = f"{num/100:.2f}"
            return f"{prefix}{space}{converted}{suffix}"
        return m.group(0)
    
    # "at 70 or above", "below 70", "above 70", "at 85+", etc.
    # Note: only matches if not already in 0.x form (negative lookbehind for ".")
    result = re.sub(
        r'\b(at|below|above|under|over)(\s+)(\d{2,3})(\s+or\s+(?:above|below)|\+)?\b(?!\.\d)',
        repl_threshold,
        result
    )
    
    return result

def load_cases(path):
    cases = {}
    with open(path) as f:
        for line in f:
            c = json.loads(line)
            cases[c['case_id']] = c
    return cases

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    stats = {
        'scale_converted': 0,
        'noul_replaced': 0,
        'k4401_fixed': 0,
        'total': 0,
    }
    
    # Load v2 cases for replacements
    v2_by_id = {}
    for family in FAMILIES:
        v2_path = os.path.join(V2_INPUT, f"{family}.jsonl")
        if os.path.exists(v2_path):
            v2_by_id.update(load_cases(v2_path))
    
    # Get the 123 Noul case IDs that need replacement (benign abstain in v1)
    noul_replace_ids = set()
    for family in FAMILIES:
        v1_path = os.path.join(V1_INPUT, f"{family}.jsonl")
        for cid, case in load_cases(v1_path).items():
            if case['primitive'] == 'noul' and case['benign'].get('expected_decision') == 'abstain':
                noul_replace_ids.add(cid)
    
    print(f"Noul cases to replace: {len(noul_replace_ids)}")
    
    # Additional duplicate fixes: v1-ppa-031 and v1-ppa-038 duplicate v1-csm-023
    # (same K-4401 $95k storm damage scenario). Use v2's rewritten versions.
    duplicate_fix_ids = {'v1-ppa-031', 'v1-ppa-038', 'v1-ppa-127'}
    
    for family in FAMILIES:
        v1_path = os.path.join(V1_INPUT, f"{family}.jsonl")
        v1_cases = load_cases(v1_path)
        
        output_cases = []
        for cid in sorted(v1_cases.keys()):
            case = v1_cases[cid]
            
            # Fix 3: K-4401 duplicates (v1-ppa-031, v1-ppa-038, v1-ppa-127)
            # These duplicate v1-csm-023's scenario. Use v2's rewritten versions.
            if cid in duplicate_fix_ids and cid in v2_by_id:
                case = v2_by_id[cid]
                stats['k4401_fixed'] += 1
            # Fix 2: Noul replacements
            elif cid in noul_replace_ids and cid in v2_by_id:
                case = v2_by_id[cid]
                stats['noul_replaced'] += 1
            # Fix 1: Scale conversion (only if not already replaced by Fix 2/3)
            if case['primitive'] == 'score':
                prompt = case['benign']['input']['prompt']
                if '0-100' in prompt:  # catches "(0-100" and "X 0-100;" patterns
                    # Convert both benign and attacked prompts
                    new_benign = convert_scale(prompt)
                    new_attacked = convert_scale(case['attacked']['input']['prompt'])
                    if new_benign != prompt or new_attacked != case['attacked']['input']['prompt']:
                        case = dict(case)  # shallow copy
                        case['benign'] = dict(case['benign'])
                        case['benign']['input'] = dict(case['benign']['input'])
                        case['benign']['input']['prompt'] = new_benign
                        case['attacked'] = dict(case['attacked'])
                        case['attacked']['input'] = dict(case['attacked']['input'])
                        case['attacked']['input']['prompt'] = new_attacked
                        stats['scale_converted'] += 1
            
            output_cases.append(case)
            stats['total'] += 1
        
        # Write output (sorted by case_id for determinism)
        output_path = os.path.join(OUTPUT_DIR, f"{family}.jsonl")
        with open(output_path, 'w') as f:
            for case in output_cases:
                f.write(json.dumps(case, sort_keys=True) + '\n')
        
        print(f"{family}: {len(output_cases)} cases -> {output_path}")
    
    print(f"\nStats: {stats}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
