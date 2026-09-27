"""Run registry: SQLite index over the runs directory.

Artifacts live as loose JSON files in runs/. This module provides:
- A SQLite index (index.db) for fast queries without loading full results
- `scan_runs()`: rebuild the index from the runs directory
- `list_runs()`: query with filters
- `verify_runs()`: bulk analysis-lock verification
- `qualifies_for_leaderboard()`: the ingestion gate

The index is a cache, not a source of truth — deleting index.db is
always safe; it will be rebuilt on next use.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from peira.artifacts import RunArtifact

# Default runs directory, overridable via PEIRA_RUNS_DIR env var.
import os
DEFAULT_RUNS_DIR = Path(os.environ.get("PEIRA_RUNS_DIR", "runs"))

INDEX_DB_NAME = "index.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    run_id TEXT,
    created_utc TEXT,
    adapter_name TEXT,
    adapter_version TEXT,
    suite TEXT,
    dataset_version TEXT,
    manifest_sha256 TEXT,
    env_sha256 TEXT,
    seed INTEGER,
    max_concurrency INTEGER,
    n_results INTEGER,
    lock_valid INTEGER  -- 1 if verify() passed at index time, else 0
);
CREATE INDEX IF NOT EXISTS idx_adapter ON runs(adapter_name);
CREATE INDEX IF NOT EXISTS idx_suite ON runs(suite);
CREATE INDEX IF NOT EXISTS idx_dataset ON runs(dataset_version);
"""


def _get_runs_dir(runs_dir: Path | str | None = None) -> Path:
    if runs_dir is None:
        return DEFAULT_RUNS_DIR
    return Path(runs_dir)


def _index_path(runs_dir: Path) -> Path:
    return runs_dir / INDEX_DB_NAME


def _artifact_metadata(path: Path) -> dict[str, Any] | None:
    """Read artifact metadata without loading full results.

    Returns None if the file is not a valid artifact.
    """
    try:
        text = path.read_text()
        data = json.loads(text)
    except (json.JSONDecodeError, OSError):
        return None
    # Minimal validation: must have the required fields
    if not isinstance(data, dict):
        return None
    if "peira_version" not in data or "dataset_version" not in data:
        return None
    # Verify the lock (cheap: just the hash comparison)
    try:
        artifact = RunArtifact.from_json(text)
        lock_valid = 1 if artifact.verify() else 0
    except Exception:
        lock_valid = 0
    return {
        "run_id": path.stem,
        "created_utc": data.get("created_utc", ""),
        "adapter_name": data.get("adapter_name", ""),
        "adapter_version": data.get("adapter_version", ""),
        "suite": data.get("suite", ""),
        "dataset_version": data.get("dataset_version", ""),
        "manifest_sha256": data.get("manifest_sha256", ""),
        "env_sha256": data.get("env_sha256", ""),
        "seed": data.get("seed", 0),
        "max_concurrency": data.get("max_concurrency", 0),
        "n_results": len(data.get("results", [])),
        "lock_valid": lock_valid,
    }


def scan_runs(runs_dir: Path | str | None = None) -> int:
    """Scan the runs directory and rebuild the SQLite index.

    Returns the number of artifacts indexed.
    """
    runs_dir = _get_runs_dir(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    db_path = _index_path(runs_dir)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        # Clear existing index
        conn.execute("DELETE FROM runs")

        count = 0
        for path in sorted(runs_dir.glob("*.json")):
            if path.name == INDEX_DB_NAME:
                continue
            meta = _artifact_metadata(path)
            if meta is None:
                continue
            mtime = path.stat().st_mtime
            conn.execute(
                """INSERT INTO runs
                   (path, mtime, run_id, created_utc, adapter_name,
                    adapter_version, suite, dataset_version, manifest_sha256,
                    env_sha256, seed, max_concurrency, n_results, lock_valid)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(path.resolve()), mtime, meta["run_id"], meta["created_utc"],
                    meta["adapter_name"], meta["adapter_version"],
                    meta["suite"], meta["dataset_version"],
                    meta["manifest_sha256"], meta["env_sha256"],
                    meta["seed"], meta["max_concurrency"],
                    meta["n_results"], meta["lock_valid"],
                ),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def _ensure_index_fresh(runs_dir: Path) -> None:
    """Rebuild the index if any artifact is newer than the index."""
    db_path = _index_path(runs_dir)
    if not db_path.exists():
        scan_runs(runs_dir)
        return
    db_mtime = db_path.stat().st_mtime
    for path in runs_dir.glob("*.json"):
        if path.name == INDEX_DB_NAME:
            continue
        if path.stat().st_mtime > db_mtime:
            scan_runs(runs_dir)
            return


def list_runs(
    runs_dir: Path | str | None = None,
    adapter: str | None = None,
    suite: str | None = None,
    dataset_version: str | None = None,
) -> list[dict[str, Any]]:
    """List runs with optional filters.

    Returns a list of dicts with run metadata. The index is rebuilt if
    stale.
    """
    runs_dir = _get_runs_dir(runs_dir)
    if not runs_dir.exists():
        return []
    _ensure_index_fresh(runs_dir)

    conn = sqlite3.connect(_index_path(runs_dir))
    try:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM runs WHERE 1=1"
        params: list[Any] = []
        if adapter:
            query += " AND adapter_name = ?"
            params.append(adapter)
        if suite:
            query += " AND suite = ?"
            params.append(suite)
        if dataset_version:
            query += " AND dataset_version = ?"
            params.append(dataset_version)
        query += " ORDER BY created_utc DESC"
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def verify_runs(
    paths: list[Path | str],
) -> list[tuple[str, bool, str]]:
    """Verify analysis locks for a list of artifact paths.

    Returns a list of (path, valid, message) tuples.
    """
    results = []
    for p in paths:
        path = Path(p)
        try:
            artifact = RunArtifact.from_json(path.read_text())
            if artifact.verify():
                results.append((str(path), True, "lock valid"))
            else:
                results.append(
                    (str(path), False, "analysis lock mismatch")
                )
        except Exception as e:
            results.append((str(path), False, f"load failed: {e}"))
    return results


def qualifies_for_leaderboard(artifact: RunArtifact) -> tuple[bool, str]:
    """Check if an artifact qualifies for leaderboard ingestion.

    Returns (qualifies, reason). The leaderboard only accepts:
    - verify() passes (lock valid)
    - manifest_sha256 is non-empty (bound to a sealed dataset)
    - adapter_version is non-empty (pinned, not floating)

    Note: the full reproducibility grade (Layer 3b) is not yet
    implemented; this is the minimal gate.
    """
    if not artifact.verify():
        return False, "analysis lock invalid"
    if not artifact.manifest_sha256:
        return False, "not bound to a dataset manifest"
    if not artifact.adapter_version:
        return False, "adapter version not pinned"
    return True, "qualifies"
