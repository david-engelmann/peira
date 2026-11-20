#!/usr/bin/env python3
"""Submit peira's uv.lock dependency graph to GitHub's dependency graph.

GitHub's dependency graph does not parse uv.lock (its supported
ecosystems table lists requirements.txt, Pipfile.lock and poetry.lock
for Python), so without this script the repository's Python
dependencies are invisible to the dependency graph, to Dependabot
alerts, and to the dependency-review action. This script converts
uv.lock into the snapshot format of GitHub's dependency submission
API and, unless --dry-run is given, POSTs it.

The conversion is a faithful flattening of the lockfile:

- Every locked package except the project itself (the editable root)
  becomes one resolved entry, keyed by its Package URL
  (pkg:pypi/<name>@<version>).
- Direct dependencies are read off the root package: its plain
  dependencies and its non-dev optional-dependency groups are direct
  runtime dependencies; the dev group (and any uv dev-dependencies
  groups) are direct development dependencies.
- uv.lock is a universal lock: a dependency entry that does not pin a
  version may resolve to several locked versions of the same name
  (one per environment marker). Edges therefore point at every locked
  candidate the entry can mean. An entry naming a package that is not
  in the lock at all is a hard error: the script fails rather than
  submit a graph it knows is wrong.
- Extras are honored: when an entry requests extras of a package
  (torch asking cuda-toolkit for its cudart group, for example), the
  extra's dependencies, recorded in the target's own
  optional-dependencies, become edges of the target.
- Transitive scopes follow reachability: a package reachable from a
  runtime root is runtime scope; one reachable only from development
  roots is development scope.

Standard library only (tomllib, Python 3.11+). Submission needs a
token with Contents: write on the repository (in Actions, the job's
GITHUB_TOKEN with `permissions: contents: write`).

Usage:
    uv_lock_snapshot.py --lock uv.lock --repo OWNER/REPO \
        --sha SHA --ref REF --correlator CORRELATOR --job-id ID \
        [--dry-run]
"""

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone

DETECTOR = {
    "name": "uv-lock-dependency-submission",
    "version": "1.0.0",
    "url": "https://github.com/david-engelmann/peira/blob/main/scripts/uv_lock_snapshot.py",
}


def normalize(name):
    """PEP 503 normalization, as used in Package URLs for PyPI."""
    return re.sub(r"[-_.]+", "-", name).lower()


def purl(name, version):
    return f"pkg:pypi/{normalize(name)}@{version}"


def load_lock(path):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def build_manifest(lock):
    """Return the snapshot `manifests` mapping for one uv.lock."""
    packages = lock["package"]
    by_name = defaultdict(list)
    root = None
    for pkg in packages:
        source = pkg.get("source", {})
        if "editable" in source or "virtual" in source:
            root = pkg
        else:
            by_name[pkg["name"]].append(pkg)
    if root is None:
        raise SystemExit("uv.lock has no editable/virtual root package; "
                         "cannot identify the project's direct dependencies")

    # --- direct dependencies and their scopes, from the root package ---
    direct = {}  # name -> "runtime" | "development"

    def add_direct(entries, scope):
        for entry in entries:
            name = entry["name"]
            if scope == "runtime" or name not in direct:
                direct[name] = scope

    add_direct(root.get("dependencies", []), "runtime")
    for group, entries in root.get("optional-dependencies", {}).items():
        add_direct(entries, "development" if group == "dev" else "runtime")
    for entries in root.get("dev-dependencies", {}).values():
        add_direct(entries, "development")

    # --- edges ---------------------------------------------------------
    def resolve(entry, owner):
        """Locked packages a dependency entry can mean."""
        name = entry["name"]
        candidates = by_name.get(name, [])
        if entry.get("version") is not None:
            candidates = [p for p in candidates
                          if p["version"] == entry["version"]]
        if not candidates:
            raise SystemExit(
                f"{owner} depends on {name}"
                + (f" {entry['version']}" if entry.get("version") else "")
                + ", which is not in uv.lock; refusing to submit "
                  "a graph known to be wrong")
        return candidates

    # Extras requested of each package, lock-wide: an entry like
    # {name = "cuda-toolkit", extra = ["cudart"]} activates that
    # extra, whose dependencies live in the target's own
    # optional-dependencies groups and are part of the resolution.
    requested_extras = defaultdict(set)
    for pkg in packages:
        for entry in pkg.get("dependencies", []):
            extras = entry.get("extra", [])
            if isinstance(extras, str):
                extras = [extras]
            requested_extras[entry["name"]].update(extras)

    edges = {}  # (name, version) -> set of purls
    for pkg in packages:
        if pkg is root:
            continue
        key = (pkg["name"], pkg["version"])
        targets = set()
        entries = list(pkg.get("dependencies", []))
        for group, group_entries in pkg.get(
                "optional-dependencies", {}).items():
            if group in requested_extras.get(pkg["name"], ()):
                entries.extend(group_entries)
        for entry in entries:
            for cand in resolve(entry, f"{pkg['name']} {pkg['version']}"):
                targets.add(purl(cand["name"], cand["version"]))
        edges[key] = targets

    # --- scopes by reachability ----------------------------------------
    key_by_purl = {purl(p["name"], p["version"]): (p["name"], p["version"])
                   for group in by_name.values() for p in group}

    def reachable(direct_names):
        seen = set()
        queue = deque()
        for name in direct_names:
            for cand in by_name.get(name, []):
                key = (cand["name"], cand["version"])
                if key not in seen:
                    seen.add(key)
                    queue.append(key)
        while queue:
            key = queue.popleft()
            for target in edges.get(key, ()):
                cand_key = key_by_purl[target]
                if cand_key not in seen:
                    seen.add(cand_key)
                    queue.append(cand_key)
        return seen

    runtime_keys = reachable([n for n, s in direct.items() if s == "runtime"])
    dev_keys = reachable([n for n, s in direct.items()
                          if s == "development"]) - runtime_keys

    # --- assemble -------------------------------------------------------
    resolved = {}
    for name, group in sorted(by_name.items()):
        for pkg in group:
            key = (pkg["name"], pkg["version"])
            url = purl(*key)
            resolved[url] = {
                "package_url": url,
                "relationship": "direct" if name in direct else "indirect",
                "scope": ("runtime" if key in runtime_keys
                          else "development" if key in dev_keys
                          else "runtime"),
                "dependencies": sorted(edges.get(key, ())),
            }
    return {
        "uv.lock": {
            "name": "uv.lock",
            "file": {"source_location": "uv.lock"},
            "resolved": resolved,
        }
    }


def build_snapshot(lock, args):
    return {
        "version": 0,
        "sha": args.sha,
        "ref": args.ref,
        # Required by the submission API: when the snapshot was taken.
        "scanned": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "job": {"id": args.job_id, "correlator": args.correlator},
        "detector": DETECTOR,
        "metadata": {},
        "manifests": build_manifest(lock),
    }


def submit(snapshot, repo, token):
    url = f"https://api.github.com/repos/{repo}/dependency-graph/snapshots"
    data = json.dumps(snapshot).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "peira-uv-lock-dependency-submission")
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode())
            print(f"snapshot accepted: status {resp.status}, "
                  f"id {body.get('id')}, message: {body.get('message')}")
            return 0
    except urllib.error.HTTPError as err:
        print(f"submission failed: HTTP {err.code}: "
              f"{err.read().decode()[:500]}", file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", default="uv.lock")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--correlator", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the snapshot JSON instead of submitting")
    args = parser.parse_args(argv)

    snapshot = build_snapshot(load_lock(args.lock), args)
    count = len(snapshot["manifests"]["uv.lock"]["resolved"])
    if args.dry_run:
        print(json.dumps(snapshot, indent=1, sort_keys=True))
        print(f"# {count} resolved dependencies", file=sys.stderr)
        return 0
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GH_TOKEN/GITHUB_TOKEN is not set", file=sys.stderr)
        return 1
    print(f"submitting {count} resolved dependencies from uv.lock "
          f"for {args.sha} ({args.ref})")
    return submit(snapshot, args.repo, token)


if __name__ == "__main__":
    sys.exit(main())
