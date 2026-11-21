"""Submit a project's uv.lock dependencies to the dependency graph.

GitHub's dependency graph does not parse uv.lock (the supported
Python manifests are requirements.txt, Pipfile.lock and poetry.lock),
so the Python dependencies are invisible to dependency review and to
Dependabot alerts unless they are submitted. This script converts a
uv.lock into the snapshot format of the dependency submission API
and POSTs it:

    POST /repos/{owner}/{repo}/dependency-graph/snapshots

It runs in two places, under one correlator so the graph treats the
submissions as one producer: the submit job in dependency-review.yml
submits for each PR head, and dependency-submission.yml submits on
every push to main. Only a snapshot for the default branch updates
the repository's standing dependency results; a PR-head snapshot
feeds the dependency-review comparison for that PR.

Conversion rules (uv.lock is the only input):

- Direct dependencies and their scopes come from the lock's root
  package (the editable or virtual one). Its plain dependencies and
  its optional-dependencies groups other than "dev" are runtime;
  the "dev" group and any dev-dependencies are development. A name
  that appears in both is runtime.
- Transitive scopes follow reachability from those direct sets,
  runtime winning over development. A locked package reachable from
  neither set is submitted with scope "unknown" and named in a
  warning on stderr; on a well-formed lock there are none.
- Extras are honored: when an entry requests extras of a package
  (torch asking cuda-toolkit for its cudart group, for example), the
  extra's dependencies, recorded in the target's own
  optional-dependencies, become edges of the target. Extra requests
  are collected from every entry list in the lock (dependencies,
  optional-dependencies and dev-dependencies alike), root included.
- Package names are keyed by their PEP 503 normalization, the same
  normalization the Package URLs use.

The script fails, rather than submit a graph it knows is wrong,
when: a dependency entry names a package (or a pinned version) that
is not in the lock, root entries included; the lock has no root
package or more than one; two locked packages collide under PEP 503
normalization at the same version; or a package's source is not a
registry (a git, archive or directory source has no PyPI Package
URL, and inventing one would misstate the package's identity).

Known limitations, stated plainly:

- uv.lock is a universal lock, so this is a faithful flattening,
  not one environment's resolution. A dependency entry that does not
  pin a version may resolve to several locked versions of the same
  name (one per environment marker); edges point at every locked
  candidate the entry can mean, and markers are not evaluated.
- Extra requests are collected lock-wide by package name, so an
  extra requested of one locked version activates that extra's
  edges on every locked version of the package. Both limitations
  over-report edges rather than miss them, which is the safe
  direction for vulnerability scanning.

The script is standard-library only and needs Python 3.11 or newer
(tomllib). The submission token is read from GH_TOKEN, falling back
to GITHUB_TOKEN.

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
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone

DETECTOR_NAME = "uv-lock-dependency-submission"
DETECTOR_VERSION = "1.0.0"


def normalize(name):
    """PEP 503 normalization, as used in Package URLs for PyPI."""
    return re.sub(r"[-_.]+", "-", name).lower()


def purl(name, version):
    return f"pkg:pypi/{normalize(name)}@{urllib.parse.quote(version, safe='._-')}"


def load_lock(path):
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"lock file not found: {path}")
    except tomllib.TOMLDecodeError as err:
        raise SystemExit(f"lock file does not parse: {path}: {err}")


def entry_lists(pkg):
    """Every dependency entry a lock package carries, in any list."""
    entries = list(pkg.get("dependencies", []))
    for group_entries in pkg.get("optional-dependencies", {}).values():
        entries.extend(group_entries)
    for group_entries in pkg.get("dev-dependencies", {}).values():
        entries.extend(group_entries)
    return entries


def index_packages(lock):
    """Split the lock into (root, {normalized name: [packages]}).

    Fails on the shapes the converter cannot represent honestly: no
    root or several, a PEP 503 collision at one version, or a
    non-registry source on a non-root package.
    """
    try:
        packages = lock["package"]
    except KeyError:
        raise SystemExit("uv.lock has no [[package]] entries")
    root = None
    by_name = defaultdict(list)
    seen = set()
    for pkg in packages:
        source = pkg.get("source", {})
        if "editable" in source or "virtual" in source:
            if root is not None:
                raise SystemExit(
                    "uv.lock has more than one editable/virtual package "
                    f"({root['name']}, {pkg['name']}); workspace locks "
                    "are not supported")
            root = pkg
            continue
        if "registry" not in source:
            raise SystemExit(
                f"{pkg['name']} {pkg['version']} has a non-registry "
                f"source ({', '.join(sorted(source)) or 'none'}); only "
                "registry packages have a PyPI Package URL")
        key = (normalize(pkg["name"]), pkg["version"])
        if key in seen:
            raise SystemExit(
                f"two locked packages collide as {key[0]} {key[1]} "
                "under PEP 503 normalization")
        seen.add(key)
        by_name[key[0]].append(pkg)
    if root is None:
        raise SystemExit("uv.lock has no editable/virtual root package; "
                         "cannot identify the project's direct dependencies")
    return root, by_name


def resolve(entry, by_name, owner):
    """Locked packages a dependency entry can mean; fail if none."""
    name = entry["name"]
    candidates = by_name.get(normalize(name), [])
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


def direct_sets(root, by_name):
    """{normalized name: scope} for the root's direct dependencies.

    Every root entry is resolved against the lock, so a root entry
    naming an absent package fails here rather than being dropped.
    """
    direct = {}

    def add(entries, scope):
        for entry in entries:
            resolve(entry, by_name, "the root package")
            name = normalize(entry["name"])
            if scope == "runtime" or name not in direct:
                direct[name] = scope

    add(root.get("dependencies", []), "runtime")
    for group, entries in root.get("optional-dependencies", {}).items():
        add(entries, "development" if group == "dev" else "runtime")
    for entries in root.get("dev-dependencies", {}).values():
        add(entries, "development")
    return direct


def requested_extras(packages):
    """{normalized package name: {extra names requested of it}}.

    Collected from every entry list of every package, root included:
    an extra chain that passes through an optional group activates
    exactly like one in a plain dependencies list.
    """
    requested = defaultdict(set)
    for pkg in packages:
        for entry in entry_lists(pkg):
            extras = entry.get("extra", [])
            if isinstance(extras, str):
                extras = [extras]
            requested[normalize(entry["name"])].update(extras)
    return requested


def build_edges(packages, root, by_name, requested):
    """{(normalized name, version): {purls the package depends on}}."""
    edges = {}
    for pkg in packages:
        if pkg is root:
            continue
        key = (normalize(pkg["name"]), pkg["version"])
        entries = list(pkg.get("dependencies", []))
        for group, group_entries in pkg.get(
                "optional-dependencies", {}).items():
            if group in requested.get(key[0], ()):
                entries.extend(group_entries)
        targets = set()
        for entry in entries:
            for cand in resolve(entry, by_name,
                                f"{pkg['name']} {pkg['version']}"):
                targets.add(purl(cand["name"], cand["version"]))
        edges[key] = targets
    return edges


def reachable(direct_names, by_name, edges):
    """Package keys reachable from the given direct names."""
    key_by_purl = {}
    for group in by_name.values():
        for pkg in group:
            key_by_purl[purl(pkg["name"], pkg["version"])] = (
                normalize(pkg["name"]), pkg["version"])
    seen = set()
    queue = deque()
    for name in direct_names:
        for cand in by_name.get(name, []):
            key = (normalize(cand["name"]), cand["version"])
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


def build_manifest(lock):
    """Return the snapshot `manifests` mapping for one uv.lock."""
    root, by_name = index_packages(lock)
    direct = direct_sets(root, by_name)
    requested = requested_extras(lock["package"])
    edges = build_edges(lock["package"], root, by_name, requested)

    runtime_keys = reachable(
        [n for n, s in direct.items() if s == "runtime"], by_name, edges)
    dev_keys = reachable(
        [n for n, s in direct.items() if s == "development"],
        by_name, edges) - runtime_keys

    resolved = {}
    unreachable = []
    for name, group in sorted(by_name.items()):
        for pkg in group:
            key = (name, pkg["version"])
            url = purl(pkg["name"], pkg["version"])
            if key in runtime_keys:
                scope = "runtime"
            elif key in dev_keys:
                scope = "development"
            else:
                scope = "unknown"
                unreachable.append(url)
            resolved[url] = {
                "package_url": url,
                "relationship": "direct" if name in direct else "indirect",
                "scope": scope,
                "dependencies": sorted(edges.get(key, ())),
            }
    if unreachable:
        print(f"warning: {len(unreachable)} locked package(s) are not "
              "reachable from the root's direct dependencies and were "
              "submitted with scope 'unknown': "
              + ", ".join(sorted(unreachable)), file=sys.stderr)
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
        "detector": {
            "name": DETECTOR_NAME,
            "version": DETECTOR_VERSION,
            "url": f"https://github.com/{args.repo}/blob/main/"
                   "scripts/uv_lock_snapshot.py",
        },
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
    req.add_header("User-Agent", DETECTOR_NAME)
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
    except urllib.error.URLError as err:
        print(f"submission failed: {err.reason}", file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert uv.lock to a dependency-graph snapshot "
                    "and submit it to GitHub's dependency submission API.")
    parser.add_argument("--lock", default="uv.lock",
                        help="path to uv.lock (default: uv.lock)")
    parser.add_argument("--repo", required=True,
                        help="owner/name of the repository")
    parser.add_argument("--sha", required=True,
                        help="commit SHA the snapshot describes")
    parser.add_argument("--ref", required=True,
                        help="ref the snapshot describes, e.g. refs/heads/main")
    parser.add_argument("--correlator", required=True,
                        help="job correlator grouping this producer's snapshots")
    parser.add_argument("--job-id", required=True,
                        help="job id recorded in the snapshot (the run id)")
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
