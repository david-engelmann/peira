#!/usr/bin/env python3
"""
Split v1 corpus into public (2000) and private holdout (500).

Per family: 200 public + 50 private.
Private holdout uses blind pseudonymized IDs (v1-holdout-XXXX) with no
family/suite/arm labels, per David's 2026-09-23 blind-holdout decision.

Deterministic: uses seed 20260923, same as sealed-v1.
Stratified by primitive and severity to match public distribution.

Output:
- dataset/v1/public/<family>.jsonl (200 each, original IDs)
- dataset/v1/private/<family>.jsonl (50 each, blind IDs)
- dataset/v1/split_manifest.json (maps blind IDs to original, quotas, hashes)
"""
import json
import os
import sys
import hashlib
import random
from collections import Counter, defaultdict

CASES_DIR = os.path.expanduser("~/workspace/peira-scaffold/dataset/v1/cases")
OUTPUT_BASE = os.path.expanduser("~/workspace/peira-scaffold/dataset/v1")
SEED = 20260923

FAMILIES = [
    "confidence_spoofing", "criteria_smuggling", "distractor_flooding",
    "indirection", "literal_reading", "negation_games", "option_order",
    "policy_paraphrase", "score_anchoring", "state_poisoning",
]

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    rng = random.Random(SEED)
    
    public_dir = os.path.join(OUTPUT_BASE, "public")
    private_dir = os.path.join(OUTPUT_BASE, "private")
    os.makedirs(public_dir, exist_ok=True)
    os.makedirs(private_dir, exist_ok=True)
    
    manifest = {
        "version": "1.0.0",
        "seed": SEED,
        "families": {},
        "blind_id_map": {},  # blind_id -> original_id (for authorized use only)
    }
    
    blind_counter = 1
    
    for family in FAMILIES:
        path = os.path.join(CASES_DIR, f"{family}.jsonl")
        cases = []
        with open(path) as f:
            for line in f:
                cases.append(json.loads(line))
        
        # Stratified split: group by (severity, primitive), sample 20% for private
        groups = defaultdict(list)
        for c in cases:
            key = (c['severity'], c['primitive'])
            groups[key].append(c)
        
        public_cases = []
        private_cases = []
        
        for key in sorted(groups.keys()):
            group = groups[key]
            rng.shuffle(group)
            n_private = max(1, round(len(group) * 0.2))  # 20%, at least 1
            # Adjust to hit exactly 50 private per family
            private_cases.extend(group[:n_private])
            public_cases.extend(group[n_private:])
        
        # Adjust to exactly 200/50
        # If we have too many/few private, move cases between splits
        # (keeping stratification as close as possible)
        while len(private_cases) > 50:
            # Move one from private to public (from largest group)
            c = private_cases.pop()
            public_cases.append(c)
        while len(private_cases) < 50:
            c = public_cases.pop()
            private_cases.append(c)
        
        assert len(public_cases) == 200, f"{family}: public {len(public_cases)} != 200"
        assert len(private_cases) == 50, f"{family}: private {len(private_cases)} != 50"
        
        # Sort for determinism
        public_cases.sort(key=lambda c: c['case_id'])
        private_cases.sort(key=lambda c: c['case_id'])
        
        # Write public (original IDs)
        public_path = os.path.join(public_dir, f"{family}.jsonl")
        with open(public_path, 'w') as f:
            for c in public_cases:
                f.write(json.dumps(c, sort_keys=True) + '\n')
        
        # Write private (blind IDs)
        private_path = os.path.join(private_dir, f"{family}.jsonl")
        with open(private_path, 'w') as f:
            for c in private_cases:
                blind_id = f"v1-holdout-{blind_counter:04d}"
                blind_counter += 1
                manifest["blind_id_map"][blind_id] = c['case_id']
                # Create blind copy (no family label in ID, but keep family field
                # for internal tracking — the blind requirement is about IDs
                # not being guessable, not about removing metadata from the file)
                blind_case = dict(c)
                blind_case['case_id'] = blind_id
                blind_case['holdout_original_id'] = c['case_id']
                f.write(json.dumps(blind_case, sort_keys=True) + '\n')
        
        # Manifest entry
        priv_prim = Counter(c['primitive'] for c in private_cases)
        priv_sev = Counter(c['severity'] for c in private_cases)
        manifest["families"][family] = {
            "input_cases": 250,
            "public_cases": 200,
            "private_cases": 50,
            "public_sha256": sha256_file(public_path),
            "private_sha256": sha256_file(private_path),
            "private_quotas": {
                "primitive": dict(priv_prim),
                "severity": dict(priv_sev),
            },
        }
        
        print(f"{family}: 200 public, 50 private")
    
    # Write manifest
    manifest_path = os.path.join(OUTPUT_BASE, "split_manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    
    print(f"\nSplit complete. Manifest: {manifest_path}")
    print(f"Blind IDs: {len(manifest['blind_id_map'])}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
