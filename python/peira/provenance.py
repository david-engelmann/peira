"""R-10 provenance package: dataset release provenance.

This module is the machine-readable side of peira's data governance:

- :func:`build_croissant` / :func:`write_croissant` generate a
  Croissant 1.0 metadata record (MLCommons) for a dataset directory.
  ``write_manifest`` in :mod:`peira.dataset` writes one automatically
  next to every ``manifest.json`` it seals, so a croissant record
  exists for every manifest-build.
- The immutable tag registry (``data/dataset-releases.json``) binds
  git tags to manifest digests. :func:`verify_releases` checks that
  every registered tag still resolves and still points at the exact
  manifest bytes it was cut from. ``scripts/check_dataset_tags.py``
  runs this in CI.
- :func:`record_release` appends a new registry entry; it is the
  programmatic half of the release procedure documented in
  ``docs/Provenance.md`` ("Cutting a dataset release").

Only the standard library is used, keeping the base package
dependency-free.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peira.dataset import atomic_write_text, sha256_file

CROISSANT_NAME = "croissant.json"
RELEASES_REL = Path("data/dataset-releases.json")

# Croissant 1.0 context, verbatim from the canonical 1.0 example
# (mlcommons/croissant, datasets/1.0/gpt-3/metadata.json). Bare terms
# like recordSet, field, and dataType are Croissant terms with no
# schema.org IRI; without these mappings they would expand through
# @vocab to nonexistent schema.org IRIs that conformant consumers
# silently ignore.
CROISSANT_CONTEXT = {
    "@language": "en",
    "@vocab": "https://schema.org/",
    "citeAs": "cr:citeAs",
    "column": "cr:column",
    "conformsTo": "dct:conformsTo",
    "cr": "http://mlcommons.org/croissant/",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    "dct": "http://purl.org/dc/terms/",
    "examples": {"@id": "cr:examples", "@type": "@json"},
    "extract": "cr:extract",
    "field": "cr:field",
    "fileProperty": "cr:fileProperty",
    "fileObject": "cr:fileObject",
    "fileSet": "cr:fileSet",
    "format": "cr:format",
    "includes": "cr:includes",
    "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath",
    "key": "cr:key",
    "md5": "cr:md5",
    "parentField": "cr:parentField",
    "path": "cr:path",
    "recordSet": "cr:recordSet",
    "references": "cr:references",
    "regex": "cr:regex",
    "repeated": "cr:repeated",
    "replace": "cr:replace",
    "sc": "https://schema.org/",
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
}

# Marks the record as Croissant 1.0 (spec section 2.1).
CROISSANT_CONFORMS_TO = "http://mlcommons.org/croissant/1.0"

REPO_URL = "https://github.com/david-engelmann/peira"
DATASET_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/deed.en"

# Human-readable field documentation for the croissant recordSet. Kept
# as data so the record and the docs cannot drift: the same table feeds
# docs/Provenance.md, pinned verbatim by
# test_docs_table_matches_case_fields in tests/test_provenance.py.
# Descriptions avoid colons and semicolons because they ship verbatim
# into the public croissant.json files.
CASE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("case_id", "Text", "Stable case identifier, e.g. v1-spo-001."),
    ("family", "Text", "Attack family id from the peira taxonomy."),
    ("primitive", "Text", "Decision primitive, either choice, score, or abstain."),
    ("severity", "Text", "Consequence-based severity, either critical, high, medium, or low."),
    ("benign.input.prompt", "Text", "The unattacked decision prompt."),
    ("benign.input.options", "Text", "The explicit decision vocabulary."),
    ("benign.expected_decision", "Text", "Gold decision on the benign variant."),
    ("attacked.input.prompt", "Text", "The attacked decision prompt."),
    ("attacked.target_decision", "Text",
     "Decision the attacker tries to induce, or null when the attack "
     "only tries to change the decision."),
    ("provenance", "Object",
     "Optional PROV-style object with generated_by, generated_at, "
     "was_derived_from, and was_attributed_to."),
    ("evaluation_only", "Boolean", "True. Benchmark data, never train on it."),
    ("do_not_train", "Boolean", "True. Exclude from training corpora."),
)

# JSON-LD data types for the recordSet fields, keyed by the short type
# name used in CASE_FIELDS.
_FIELD_DATA_TYPES = {
    "Text": "sc:Text",
    "Boolean": "sc:Boolean",
    # The provenance field is a JSON object, not a scalar. Schema.org
    # has no Object type; sc:Thing is the honest generic.
    "Object": "sc:Thing",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _repo_relative_dir(cases_dir: Path) -> Path | None:
    """Repo-relative directory of a cases dir, found via .git walk-up.

    Returns None when no enclosing git repo is found (e.g. a temp dir
    in tests); callers then omit contentUrl rather than emit a wrong
    one.
    """
    resolved = Path(cases_dir).resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            return resolved.relative_to(parent)
    return None


def default_croissant_args(cases_dir: Path,
                           manifest: dict[str, Any]) -> dict[str, Any]:
    """The label/description/version/content_dir `write_manifest` uses.

    A single defaulting path so checked-in records are reproducible by
    the pipeline: regenerating through `write_croissant` yields the
    same record. The label is the manifest's dataset name; the content
    dir is the cases directory relative to the repo root.

    The trial suite's manifest declares dataset "peira-v1" (pre-existing
    data), which would collide with the v1 suite's Croissant @id. The
    @id is node identity in JSON-LD, so the trial record gets its own
    label "peira-trial" to keep every record's ids unique.
    """
    version = str(manifest.get("dataset_version", "0.0.0-unknown"))
    label = str(manifest.get("dataset", "peira"))
    rel = _repo_relative_dir(cases_dir)
    content_dir = rel.as_posix() if rel is not None else None
    if content_dir == "dataset/trial":
        label = "peira-trial"
    return {
        "dataset_label": label,
        "description": (f"{label}. Paired adversarial decision-model "
                        f"cases, dataset version {version}."),
        "version": version,
        "content_dir": content_dir,
    }


def build_croissant(manifest: dict[str, Any], *,
                    dataset_label: str,
                    description: str,
                    version: str,
                    content_dir: str | None = None,
                    creators: list[dict[str, str]] | None = None,
                    date_published: str | None = None) -> dict[str, Any]:
    """Build a Croissant 1.0 metadata record for a dataset manifest.

    ``manifest`` is the dict ``build_manifest`` produced (its ``files``
    section carries per-file SHA-256 digests). The record describes
    every case file as a ``cr:FileObject`` distribution and documents
    the paired-case fields as a ``cr:RecordSet``. ``content_dir`` is
    the cases directory relative to the repo root, used to build the
    per-file ``contentUrl``; when None the URL is omitted rather than
    guessed. Raises ``ValueError`` when the manifest has no ``files``
    section.
    """
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest has no 'files' section")
    # Note: created_utc may be absent in test manifests; use wall-clock
    # as fallback. Checked-in manifests all carry created_utc, which
    # keeps their records reproducible.
    created = manifest.get("created_utc") or _utcnow()
    # Stable @id values: Croissant consumers address entities by id,
    # so every FileObject, the RecordSet, and each Field gets a
    # deterministic id rooted at the dataset label.
    dataset_id = dataset_label
    record_set_id = f"{dataset_id}/paired_cases"
    distributions: list[dict[str, Any]] = []
    for name in sorted(files):
        entry = files[name]
        if not isinstance(entry, dict) or entry.get("kind") != "cases":
            continue
        n_cases = entry.get("n_cases", 0)
        dist: dict[str, Any] = {
            "@type": "cr:FileObject",
            "@id": f"{dataset_id}/{name}",
            "name": name,
            "description": (
                f"{n_cases} paired adversarial decision cases "
                f"({dataset_label} {version})."
            ),
            "encodingFormat": "application/x-ndjson",
            "sha256": entry.get("sha256", ""),
        }
        if content_dir:
            # Raw content URL: the record is machine-readable, so it
            # points at the fetchable file, not the GitHub HTML page.
            dist["contentUrl"] = (
                f"https://raw.githubusercontent.com/david-engelmann/"
                f"peira/main/{content_dir}/{name}")
        distributions.append(dist)
    record_set = {
        "@type": "cr:RecordSet",
        "@id": record_set_id,
        "name": "paired_cases",
        "description": (
            "One record per line of each JSONL distribution file. Each "
            "line is a benign decision variant paired with its attacked "
            "variant."
        ),
        "field": [
            {"@type": "cr:Field",
             "@id": f"{record_set_id}/{fname}",
             "name": fname,
             "description": fdesc, "dataType": _FIELD_DATA_TYPES[ftype]}
            for fname, ftype, fdesc in CASE_FIELDS
        ],
    }
    return {
        "@context": CROISSANT_CONTEXT,
        "@type": "sc:Dataset",
        "@id": dataset_id,
        "conformsTo": CROISSANT_CONFORMS_TO,
        "name": dataset_label,
        "description": description,
        "version": version,
        "url": REPO_URL,
        "license": DATASET_LICENSE_URL,
        "creator": creators or [
            {"@type": "Person", "name": "peira project",
             "url": REPO_URL},
        ],
        "datePublished": date_published or created,
        "keywords": ["adversarial robustness", "decision models",
                     "benchmark", "AI safety", "jailbreak"],
        "distribution": distributions,
        "recordSet": [record_set],
    }


def write_croissant_record(cases_dir: Path,
                           record: dict[str, Any]) -> Path:
    """Atomically write a pre-built croissant record next to a manifest."""
    out = Path(cases_dir) / CROISSANT_NAME
    atomic_write_text(
        out, json.dumps(record, indent=2, sort_keys=True) + "\n")
    return out


def write_croissant(cases_dir: Path, manifest: dict[str, Any], *,
                    dataset_label: str | None = None,
                    description: str | None = None,
                    content_dir: str | None = None) -> Path:
    """Write ``croissant.json`` next to a dataset's ``manifest.json``.

    Label, description, and content dir default to the pipeline values
    from :func:`default_croissant_args`, so the checked-in records are
    reproducible. Returns the path written. The write is atomic (see
    :func:`peira.dataset.atomic_write_text`).
    """
    cases_dir = Path(cases_dir)
    args = default_croissant_args(cases_dir, manifest)
    if dataset_label is not None:
        args["dataset_label"] = dataset_label
    if description is not None:
        args["description"] = description
    if content_dir is not None:
        args["content_dir"] = content_dir
    record = build_croissant(manifest, **args)
    return write_croissant_record(cases_dir, record)


# ---------------------------------------------------------------------------
# Immutable tag registry
#
# data/dataset-releases.json binds immutable git tags to the exact
# manifest bytes they were cut from:
#
#   {"releases": [{"tag": "dataset-v1-1.0.0",
#                  "dataset": "peira-v1",
#                  "dataset_version": "1.0.0",
#                  "manifest_path": "dataset/v1/cases/manifest.json",
#                  "manifest_sha256": "<sha256 of manifest.json AT the tag>",
#                  "croissant_sha256": "<sha256 of croissant.json AT the tag>",
#                  "commit": "<full sha the tag points at>",
#                  "created_utc": "..."}]}
#
# Tags are never moved and registry entries are never edited: a
# correction ships as a new tag + a new entry. CI
# (scripts/check_dataset_tags.py) verifies every entry.
# ---------------------------------------------------------------------------


def registry_path(repo_root: Path | str) -> Path:
    """Path of the tag registry inside a repo checkout."""
    return Path(repo_root) / RELEASES_REL


def load_releases(path: Path | str) -> list[dict[str, Any]]:
    """Load the registry's release entries (empty list when absent)."""
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    releases = data.get("releases", [])
    if not isinstance(releases, list) or not all(
            isinstance(r, dict) for r in releases):
        raise ValueError(f"{p}: 'releases' is not a list of objects")
    return releases


def record_release(path: Path | str, entry: dict[str, Any]) -> Path:
    """Append one release entry to the registry (atomic write).

    The entry must carry ``tag``, ``dataset``, ``dataset_version``,
    ``manifest_path``, ``manifest_sha256``, ``croissant_sha256``, and
    ``commit``. Raises ``ValueError`` on a missing key or a duplicate
    tag: registry entries are append-only, never edited.

    The read-modify-write is not locked: releases are cut by a human
    running ``scripts/record_dataset_release.py`` one at a time, so
    concurrent recorders are out of scope. CI additionally enforces
    append-only by diffing the registry against the merge base (see
    ``scripts/check_dataset_tags.py --check-append-only``).
    """
    required = ("tag", "dataset", "dataset_version", "manifest_path",
                "manifest_sha256", "croissant_sha256", "commit")
    missing = [k for k in required if not entry.get(k)]
    if missing:
        raise ValueError(f"release entry missing: {', '.join(missing)}")
    # Fail fast on malformed digests: a 64-char hex string is the
    # contract, and garbage recorded now fails only later at verify.
    import re
    _hex64 = re.compile(r"^[0-9a-f]{64}$")
    for k in ("manifest_sha256", "croissant_sha256"):
        if not _hex64.match(entry[k]):
            raise ValueError(f"release entry {k!r} is not a sha256 hex digest")
    p = Path(path)
    releases = load_releases(p)
    if any(r.get("tag") == entry["tag"] for r in releases):
        raise ValueError(f"tag {entry['tag']!r} already registered")
    entry = dict(entry)
    entry.setdefault("created_utc", _utcnow())
    releases.append(entry)
    payload = {"releases": releases}
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        p, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return p


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo_root), capture_output=True,
        text=True, check=True,
    ).stdout.strip()


def verify_releases(repo_root: Path | str,
                    path: Path | str | None = None) -> list[str]:
    """Verify every registered release against the git object store.

    For each entry: the tag must resolve (``git rev-parse --verify``),
    it must point at the recorded commit, and the manifest bytes at the
    tag must hash to the recorded ``manifest_sha256``, and likewise for
    the croissant file. All ``git show`` reads are pinned to the
    resolved commit SHA, so a tag move mid-verification cannot swap
    the bytes under the check. Returns the list of problems (empty =
    all releases verify).
    """
    root = Path(repo_root)
    reg = Path(path) if path is not None else registry_path(root)
    problems: list[str] = []
    for entry in load_releases(reg):
        tag = entry.get("tag", "")
        prefix = f"release {tag!r}"
        try:
            resolved = _git(root, "rev-parse", "--verify", f"{tag}^{{commit}}")
        except subprocess.CalledProcessError:
            problems.append(f"{prefix}: tag does not resolve")
            continue
        if resolved != entry.get("commit"):
            problems.append(
                f"{prefix}: tag moved (points at {resolved[:12]}, "
                f"registry says {str(entry.get('commit'))[:12]})")
        manifest_path = entry.get("manifest_path", "")
        croissant_rel = str(Path(manifest_path).parent / CROISSANT_NAME)
        blobs: dict[str, bytes] = {}
        for key, rel in (("manifest_sha256", manifest_path),
                         ("croissant_sha256", croissant_rel)):
            try:
                # Pinned to the resolved commit, not re-addressed via
                # the tag: a concurrent tag move cannot change the
                # bytes being verified.
                blobs[rel] = subprocess.run(
                    ["git", "show", f"{resolved}:{rel}"], cwd=str(root),
                    capture_output=True, check=True,
                ).stdout
            except subprocess.CalledProcessError:
                problems.append(f"{prefix}: {rel} not found at tag")
                continue
            digest = hashlib.sha256(blobs[rel]).hexdigest()
            if digest != entry.get(key):
                problems.append(
                    f"{prefix}: {rel} digest mismatch at tag "
                    f"(registry {str(entry.get(key))[:12]}, "
                    f"tag has {digest[:12]})")
        # The manifest at the tag must agree with the registry on the
        # dataset version: a registry entry pointing at the wrong
        # manifest is a lie even when the bytes verify. Both sides are
        # normalized to str so a missing version cannot false-positive.
        if manifest_path in blobs:
            try:
                at_tag = json.loads(blobs[manifest_path].decode("utf-8"))
            except ValueError:
                problems.append(f"{prefix}: manifest at tag is not JSON")
                continue
            if (str(at_tag.get("dataset_version", ""))
                    != str(entry.get("dataset_version", ""))):
                problems.append(
                    f"{prefix}: dataset_version at tag "
                    f"({at_tag.get('dataset_version')!r}) != registry "
                    f"({entry.get('dataset_version')!r})")
    return problems


def check_append_only(repo_root: Path | str, base: str,
                      path: Path | str | None = None) -> list[str]:
    """Require registry entries to be append-only since ``base``.

    Every entry present at ``base`` (the PR merge base commit) must
    still be present byte-identically in the working-tree registry.
    New tags may be appended; existing entries may not be edited or
    removed. Returns the list of problems (empty = clean).
    """
    root = Path(repo_root)
    reg = Path(path) if path is not None else registry_path(root)
    try:
        old_blob = subprocess.run(
            ["git", "show", f"{base}:{RELEASES_REL.as_posix()}"],
            cwd=str(root), capture_output=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        # No registry at base: nothing to protect.
        return []
    try:
        old_data = json.loads(old_blob.decode("utf-8"))
    except ValueError:
        return [f"registry at {base} is not valid JSON"]
    old = {r.get("tag"): r for r in old_data.get("releases", [])
           if isinstance(r, dict)}
    new = {r.get("tag"): r for r in load_releases(reg)
           if isinstance(r, dict)}
    problems: list[str] = []
    for tag, old_entry in old.items():
        new_entry = new.get(tag)
        if new_entry is None:
            problems.append(f"release {tag!r} removed from the registry")
        elif (json.dumps(new_entry, sort_keys=True)
                != json.dumps(old_entry, sort_keys=True)):
            problems.append(
                f"release {tag!r} edited in the registry "
                f"(entries are append-only)")
    return problems


def manifest_digest_at_tag(repo_root: Path | str, tag: str,
                           manifest_path: str,
                           commit: str | None = None) -> tuple[str, str]:
    """Return (manifest_sha256, croissant_sha256) of the files at a tag.

    Helper for the release procedure: the caller cuts the tag first,
    then records these digests in the registry. Reads are pinned to
    the tag's resolved commit SHA. Pass ``commit`` when the caller has
    already resolved the tag, to avoid a re-resolve TOCTOU window.
    """
    root = Path(repo_root)
    resolved = commit if commit is not None else _git(
        root, "rev-parse", "--verify", f"{tag}^{{commit}}")
    out: list[str] = []
    for rel in (manifest_path,
                str(Path(manifest_path).parent / CROISSANT_NAME)):
        blob = subprocess.run(
            ["git", "show", f"{resolved}:{rel}"], cwd=str(root),
            capture_output=True, check=True,
        ).stdout
        out.append(hashlib.sha256(blob).hexdigest())
    manifest_sha256, croissant_sha256 = out
    return manifest_sha256, croissant_sha256


def sha256_of_file(path: Path | str) -> str:
    """SHA-256 hex digest of a file (re-exported for release scripts)."""
    return sha256_file(Path(path))
