"""Re-seal the dataset manifest after S-1 Sweep A corrections.

Updates dataset_version (minor bump for retire+add), created_utc,
per-file SHA256 hashes, and severity/primitive counts.
"""
import json, glob, hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "dataset" / "v1" / "cases"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    manifest_path = CASES_DIR / "manifest.json"
    manifest = json.load(open(manifest_path))
    
    # Minor bump for retire+add (D-36)
    old_version = manifest["dataset_version"]
    major, minor, patch = map(int, old_version.split('.'))
    new_version = f"{major}.{minor+1}.0"
    
    files = {}
    for f in sorted(glob.glob(str(CASES_DIR / "*.jsonl"))):
        fname = Path(f).name
        cases = [json.loads(line) for line in open(f)]
        
        n_by_family = Counter(c["family"] for c in cases)
        n_by_primitive = Counter(c["primitive"] for c in cases)
        n_by_severity = Counter(c["severity"] for c in cases)
        
        files[fname] = {
            "kind": "cases",
            "n_by_family": dict(sorted(n_by_family.items())),
            "n_by_primitive": dict(sorted(n_by_primitive.items())),
            "n_by_severity": dict(sorted(n_by_severity.items())),
            "n_cases": len(cases),
            "sha256": sha256_file(f),
        }
    
    manifest["dataset_version"] = new_version
    manifest["created_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["files"] = files
    
    with open(manifest_path, 'w') as out:
        json.dump(manifest, out, indent=2)
        out.write('\n')
    
    print(f"Manifest re-sealed: {old_version} -> {new_version}")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
