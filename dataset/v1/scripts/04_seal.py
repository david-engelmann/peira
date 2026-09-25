#!/usr/bin/env python3
"""
Generate seal manifest for v1 dataset.

Creates dataset/v1/manifest.json with SHA-256 hashes of:
- cases/<family>.jsonl (full 250 each, canonical)
- public/<family>.jsonl (200 each)
- private/<family>.jsonl (50 each, blind IDs)
- split_manifest.json

This is a PROVISIONAL seal for review. Final sealing requires:
1. David's row-by-row review of critical cases
2. Three-review gate (red-team, line-by-line, assistant verification)
3. PR + CI + merged-main verification
"""
import json
import os
import sys
import hashlib

BASE = os.path.expanduser("~/workspace/peira-scaffold/dataset/v1")

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
    manifest = {
        "version": "1.0.0-provisional",
        "seed": 20260923,
        "status": "provisional - pending David's row-by-row review and three-review gate",
        "files": {},
    }
    
    for family in FAMILIES:
        for subdir in ["cases", "public", "private"]:
            path = os.path.join(BASE, subdir, f"{family}.jsonl")
            rel = f"dataset/v1/{subdir}/{family}.jsonl"
            manifest["files"][rel] = sha256_file(path)
    
    manifest["files"]["dataset/v1/split_manifest.json"] = sha256_file(
        os.path.join(BASE, "split_manifest.json")
    )
    
    # Count totals
    total_cases = 0
    for family in FAMILIES:
        path = os.path.join(BASE, "cases", f"{family}.jsonl")
        with open(path) as f:
            total_cases += sum(1 for _ in f)
    
    manifest["total_cases"] = total_cases
    manifest["public_cases"] = 2000
    manifest["private_cases"] = 500
    
    out_path = os.path.join(BASE, "manifest.json")
    with open(out_path, 'w') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    
    print(f"Manifest: {out_path}")
    print(f"Total: {total_cases} cases")
    print(f"Files hashed: {len(manifest['files'])}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
