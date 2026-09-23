#!/usr/bin/env python3
"""Emit leaderboard.json from sealed peira run artifacts.

Each input artifact's analysis lock is verified before its row is
included — an artifact that fails verification is refused, never
silently included. The emitted document is the machine-readable feed
the static site builds from (see docs/LeaderboardJson.md).

Usage:
    python3 scripts/emit_leaderboard.py runs/a.json runs/b.json --out leaderboard.json
    python3 scripts/emit_leaderboard.py --dir runs --out leaderboard.json

Stdlib only. Additive: reads artifacts, never modifies them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from peira import __version__ as emitter_peira_version
from peira.artifacts import RunArtifact
from peira.dataset import atomic_write_text

LEADERBOARD_SCHEMA_VERSION = "1"

# Suites that are never published to a public leaderboard (D-8). The
# emitter excludes them by default so the guarantee is mechanical, not
# just a documentation obligation on future publishers. The CI smoke
# workflow opts out explicitly with --exclude-suite= (empty).
DEFAULT_EXCLUDED_SUITES = ("trial", "trial-demo")

# Metrics keys the projection reads from the sealed artifact. A missing
# key fails the emission: a leaderboard row must never silently drop a
# contracted field.
_REQUIRED_METRIC_KEYS = (
    "n_cases",
    "n_eligible",
    "asr_conditional",
    "asr_ci95",
    "benign_accuracy",
    "benign_accuracy_ci95",
    "refusal_rate",
    "refusal_rate_ci95",
    "malformed_rate",
    "ranking_eligible",
    "eligibility_notes",
    "ineligible_by_reason",
    "per_family",
)

_REQUIRED_FAMILY_KEYS = ("n", "n_eligible", "asr", "asr_ci95", "refusal_rate")


class LeaderboardError(Exception):
    """The emission cannot proceed honestly (usage, I/O, verification)."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_artifact_paths(
    files: list[str], directory: str | None
) -> list[Path]:
    """Expand CLI inputs into a deterministic, de-duplicated path list."""
    paths: list[Path] = [Path(f) for f in files]
    if directory is not None:
        d = Path(directory)
        if not d.is_dir():
            raise LeaderboardError(f"not a directory: {directory}")
        paths.extend(sorted(d.glob("*.json")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(p)
    # Sort by resolved path so CLI argument order cannot change the output.
    return sorted(unique, key=lambda p: p.resolve().as_posix())


def load_verified(path: Path) -> tuple[RunArtifact, str]:
    """Load an artifact, verify its analysis lock, return it with its digest.

    The digest is the SHA-256 of the artifact file bytes — the row's
    content identity. Anything the lock does not bind (file framing)
    the digest does.
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise LeaderboardError(f"cannot read {path}: {e}") from e
    digest = hashlib.sha256(raw).hexdigest()
    try:
        artifact = RunArtifact.from_json(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise LeaderboardError(f"cannot load {path}: {e}") from e
    if not artifact.verify():
        raise LeaderboardError(
            f"analysis lock verification FAILED for {path}: "
            "refusing to include it"
        )
    return artifact, digest


def _checked(metrics: dict, key: str, kind: str, artifact_id: str):
    """Fetch a sealed metric value, failing closed on wrong shape.

    Presence is checked by the caller; this checks the value has the
    shape the projection assumes, so a malformed value raises
    LeaderboardError instead of silently producing nonsense (e.g. a
    string CI spreading into a char list).
    """
    value = metrics[key]
    ok = (
        (kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
        or (kind == "interval" and isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))
        or (kind == "strlist" and isinstance(value, list)
            and all(isinstance(v, str) for v in value))
        or (kind == "strmap" and isinstance(value, dict)
            and all(isinstance(k, str) for k in value))
        or (kind == "bool" and isinstance(value, bool))
    )
    if not ok:
        raise LeaderboardError(
            f"artifact {artifact_id} has malformed sealed metric {key!r}: "
            f"expected {kind}, got {type(value).__name__}"
        )
    return value


def row_for_artifact(artifact: RunArtifact, digest: str) -> dict:
    """Project one verified artifact into one leaderboard row.

    Metric numbers are the runner's sealed summary, passed through
    unchanged: they are deterministic from the sealed results, which the
    verified lock binds.
    """
    metrics = artifact.metrics
    artifact_id = f"{artifact.adapter_name}@{artifact.adapter_version}"
    missing = [k for k in _REQUIRED_METRIC_KEYS if k not in metrics]
    if missing:
        raise LeaderboardError(
            f"artifact {artifact_id} "
            f"is missing sealed metrics keys: {missing}"
        )
    # Shape-check every value the projection consumes. Presence alone
    # is not enough: a wrong-typed value must fail loudly, not spread.
    _checked(metrics, "n_cases", "number", artifact_id)
    _checked(metrics, "n_eligible", "number", artifact_id)
    _checked(metrics, "asr_conditional", "number", artifact_id)
    _checked(metrics, "asr_ci95", "interval", artifact_id)
    _checked(metrics, "benign_accuracy", "number", artifact_id)
    _checked(metrics, "benign_accuracy_ci95", "interval", artifact_id)
    _checked(metrics, "refusal_rate", "number", artifact_id)
    _checked(metrics, "refusal_rate_ci95", "interval", artifact_id)
    _checked(metrics, "malformed_rate", "number", artifact_id)
    _checked(metrics, "ranking_eligible", "bool", artifact_id)
    _checked(metrics, "eligibility_notes", "strlist", artifact_id)
    _checked(metrics, "ineligible_by_reason", "strmap", artifact_id)
    per_family: dict[str, dict] = {}
    for family in sorted(metrics["per_family"]):
        fam = metrics["per_family"][family]
        fam_missing = [k for k in _REQUIRED_FAMILY_KEYS if k not in fam]
        if fam_missing:
            raise LeaderboardError(
                f"artifact {artifact_id} "
                f"family {family!r} is missing sealed metrics keys: "
                f"{fam_missing}"
            )
        fam_id = f"{artifact_id} family {family!r}"
        _checked(fam, "n", "number", fam_id)
        _checked(fam, "n_eligible", "number", fam_id)
        _checked(fam, "asr", "number", fam_id)
        _checked(fam, "asr_ci95", "interval", fam_id)
        _checked(fam, "refusal_rate", "number", fam_id)
        per_family[family] = {k: fam[k] for k in _REQUIRED_FAMILY_KEYS}
    return {
        "run_id": digest,
        "artifact_sha256": digest,
        "adapter_name": artifact.adapter_name,
        "adapter_version": artifact.adapter_version,
        "suite": artifact.suite,
        "dataset_version": artifact.dataset_version,
        "manifest_sha256": artifact.manifest_sha256,
        "manifest_bound": bool(artifact.manifest_sha256),
        "peira_version": artifact.peira_version,
        "pricing_source": artifact.pricing_source,
        "pricing_date": artifact.pricing_date,
        "seed": artifact.seed,
        "created_utc": artifact.created_utc,
        "analysis_lock": artifact.analysis_lock,
        "lock_verified": True,
        "n_cases": metrics["n_cases"],
        "n_eligible": metrics["n_eligible"],
        "asr_conditional": metrics["asr_conditional"],
        "asr_ci95": list(metrics["asr_ci95"]),
        "benign_accuracy": metrics["benign_accuracy"],
        "benign_accuracy_ci95": list(metrics["benign_accuracy_ci95"]),
        "refusal_rate": metrics["refusal_rate"],
        "refusal_rate_ci95": list(metrics["refusal_rate_ci95"]),
        "malformed_rate": metrics["malformed_rate"],
        "ranking_eligible": metrics["ranking_eligible"],
        "eligibility_notes": list(metrics["eligibility_notes"]),
        "ineligible_by_reason": dict(metrics["ineligible_by_reason"]),
        "per_family": per_family,
    }


def emit_leaderboard(
    paths: list[Path],
    out_path: Path,
    generated_utc: str | None = None,
    exclude_suites: tuple[str, ...] = DEFAULT_EXCLUDED_SUITES,
) -> dict:
    """Build the leaderboard document and write it to ``out_path``.

    Artifacts whose suite is in ``exclude_suites`` are skipped (D-8:
    trial suites never reach a public leaderboard). The write is
    atomic: readers never see a half-written document.
    """
    if not paths:
        raise LeaderboardError("no artifacts given: nothing to emit")
    rows = []
    seen_ids: set[str] = set()
    excluded = 0
    for p in paths:
        artifact, digest = load_verified(p)
        if artifact.suite in exclude_suites:
            excluded += 1
            continue
        if digest in seen_ids:
            # Same bytes, same row — e.g. a file passed both directly
            # and via --dir. The run_id is the content identity, so this
            # is a duplicate, not a second run.
            continue
        seen_ids.add(digest)
        rows.append(row_for_artifact(artifact, digest))
    rows.sort(key=lambda r: r["run_id"])
    doc = {
        "leaderboard_schema_version": LEADERBOARD_SCHEMA_VERSION,
        "generated_utc": generated_utc or _utcnow(),
        "generator": "scripts/emit_leaderboard.py",
        "emitter_peira_version": emitter_peira_version,
        "n_rows": len(rows),
        "n_excluded_suites": excluded,
        "rows": rows,
    }
    atomic_write_text(
        out_path, json.dumps(doc, indent=2, sort_keys=True) + "\n"
    )
    if excluded:
        print(
            f"note: excluded {excluded} artifact(s) from trial suite(s)",
            file=sys.stderr,
        )
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit leaderboard.json from sealed peira run artifacts."
    )
    parser.add_argument("artifacts", nargs="*", help="run artifact JSON files")
    parser.add_argument(
        "--dir",
        default=None,
        help="also include every *.json in this directory",
    )
    parser.add_argument("--out", required=True, help="output leaderboard.json path")
    parser.add_argument(
        "--exclude-suite",
        default=",".join(DEFAULT_EXCLUDED_SUITES),
        help=(
            "comma-separated suite ids to exclude from the output "
            f"(default: {','.join(DEFAULT_EXCLUDED_SUITES)}; "
            "pass empty string to include everything)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        paths = collect_artifact_paths(args.artifacts, args.dir)
        excluded = tuple(
            s for s in args.exclude_suite.split(",") if s
        )
        emit_leaderboard(paths, Path(args.out), exclude_suites=excluded)
    except LeaderboardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
