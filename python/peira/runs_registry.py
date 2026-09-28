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
import math
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
-- Per-family metrics, one row per (run, family). Withheld rates are
-- stored as NULL, never 0.0 (mirrors metrics.per_family).
CREATE TABLE IF NOT EXISTS family_results (
    run_path TEXT NOT NULL,
    family TEXT NOT NULL,
    n INTEGER NOT NULL,
    n_eligible INTEGER NOT NULL,
    asr REAL,
    asr_lo REAL,
    asr_hi REAL,
    refusal_rate REAL,
    PRIMARY KEY (run_path, family)
);
CREATE INDEX IF NOT EXISTS idx_family_results_family ON family_results(family);
"""


def _get_runs_dir(runs_dir: Path | str | None = None) -> Path:
    if runs_dir is None:
        return DEFAULT_RUNS_DIR
    return Path(runs_dir)


def _index_path(runs_dir: Path) -> Path:
    return runs_dir / INDEX_DB_NAME


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open the index with a patient busy timeout and WAL mode.

    WAL lets readers proceed while a writer holds the lock; the 30s
    timeout lets a second writer wait out a concurrent scan instead of
    raising "database is locked".
    """
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _unlink_index(db_path: Path) -> None:
    """Remove the index and any WAL sidecars.

    A manually deleted index.db (which the module docstring promises is
    always safe) can leave stale -wal/-shm files behind; they belong to
    a deleted database and must not be recovered.
    """
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)


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
        "per_family": _per_family_rows(data),
    }


def _coerce_int(value: Any) -> int | None:
    """Coerce a count to int; None when the value is not a non-negative integer.

    Artifact JSON is untrusted input (hand-editable): numeric strings
    coerce, garbage yields None instead of raising. Booleans, negative
    values, and non-integer floats are not counts, so they yield None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _coerce_rate(value: Any) -> float | None:
    """Coerce a rate to float; None when missing, withheld, or garbage.

    Garbage includes non-finite values (inf, nan) and values outside
    the [0, 1] rate range: a rate cannot be infinite or negative, so
    such values are data corruption, not measurements.
    """
    if value is None or isinstance(value, bool):
        return None
    rate: float | None = None
    if isinstance(value, (int, float)):
        rate = float(value)
    elif isinstance(value, str):
        try:
            rate = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
        return None
    return rate


def _coerce_ci(value: Any) -> tuple[float | None, float | None]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _coerce_rate(value[0]), _coerce_rate(value[1])
    return None, None


def _per_family_rows(data: dict[str, Any]) -> list[tuple]:
    """Extract per-family metric rows from raw artifact JSON.

    Reads metrics.per_family (asr, asr_ci95 [lo, hi], refusal_rate, n,
    n_eligible). Withheld rates (None in the artifact) become None here
    and are stored as NULL, never 0.0. Malformed values never abort the
    scan: a row whose counts do not coerce is skipped, and garbage
    rates become NULL.
    """
    rows: list[tuple] = []
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return rows
    per_family = metrics.get("per_family")
    if not isinstance(per_family, dict):
        return rows
    for family, fam in per_family.items():
        if not isinstance(fam, dict):
            continue
        n = _coerce_int(fam.get("n"))
        n_eligible = _coerce_int(fam.get("n_eligible"))
        if n is None or n_eligible is None:
            continue
        lo, hi = _coerce_ci(fam.get("asr_ci95"))
        rows.append((
            str(family),
            n,
            n_eligible,
            _coerce_rate(fam.get("asr")),
            lo,
            hi,
            _coerce_rate(fam.get("refusal_rate")),
        ))
    return rows


def _scan_runs_into(conn: sqlite3.Connection, runs_dir: Path) -> int:
    """Index every artifact in runs_dir into an already-open connection.

    Returns the number of artifacts indexed. The caller owns the
    connection and the corruption-recovery policy.
    """
    conn.executescript(_SCHEMA)
    # Clear existing index
    conn.execute("DELETE FROM runs")
    conn.execute("DELETE FROM family_results")

    count = 0
    for path in sorted(runs_dir.glob("*.json")):
        if path.name == INDEX_DB_NAME:
            continue
        meta = _artifact_metadata(path)
        if meta is None:
            continue
        mtime = path.stat().st_mtime
        run_path = str(path.resolve())
        conn.execute(
            """INSERT INTO runs
               (path, mtime, run_id, created_utc, adapter_name,
                adapter_version, suite, dataset_version, manifest_sha256,
                env_sha256, seed, max_concurrency, n_results, lock_valid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_path, mtime, meta["run_id"], meta["created_utc"],
                meta["adapter_name"], meta["adapter_version"],
                meta["suite"], meta["dataset_version"],
                meta["manifest_sha256"], meta["env_sha256"],
                meta["seed"], meta["max_concurrency"],
                meta["n_results"], meta["lock_valid"],
            ),
        )
        for family, n, n_eligible, asr, lo, hi, refusal_rate in meta["per_family"]:
            conn.execute(
                """INSERT INTO family_results
                   (run_path, family, n, n_eligible, asr, asr_lo, asr_hi,
                    refusal_rate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_path, family, n, n_eligible, asr, lo, hi,
                 refusal_rate),
            )
        count += 1
    conn.commit()
    return count


def scan_runs(runs_dir: Path | str | None = None) -> int:
    """Scan the runs directory and rebuild the SQLite index.

    A missing, truncated, or otherwise corrupt index.db is unlinked and
    rebuilt (once) rather than raising; anything worse propagates.

    Returns the number of artifacts indexed.
    """
    runs_dir = _get_runs_dir(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    db_path = _index_path(runs_dir)
    if not db_path.exists():
        _unlink_index(db_path)

    def _build() -> int:
        conn = _connect(db_path)
        try:
            return _scan_runs_into(conn, runs_dir)
        finally:
            conn.close()

    try:
        return _build()
    except sqlite3.DatabaseError:
        # Corrupt index (truncated file, not a database, ...): the module
        # docstring promises deleting index.db is always safe, so do
        # exactly that and rebuild once.
        _unlink_index(db_path)
        return _build()


def _indexed_snapshot(runs_dir: Path) -> dict[str, float] | None:
    """Return the indexed {path: mtime} snapshot.

    Returns None when the index is missing or unreadable; both are
    rebuild triggers.
    """
    db_path = _index_path(runs_dir)
    if not db_path.exists():
        return None
    try:
        conn = _connect(db_path)
    except sqlite3.DatabaseError:
        return None
    try:
        try:
            rows = conn.execute("SELECT path, mtime FROM runs").fetchall()
        except sqlite3.Error:
            return None
        return {str(path): float(mtime) for path, mtime in rows}
    finally:
        conn.close()


def _ensure_index_fresh(runs_dir: Path) -> None:
    """Rebuild the index when it disagrees with the runs directory.

    Any mismatch triggers a rescan: added artifacts, modified artifacts,
    and deleted artifacts (deletions bump no mtime, so a pure "newer
    than the index" comparison would leave phantom rows forever). A
    missing or corrupt index is also a rebuild trigger.
    """
    actual: dict[str, float] = {}
    for path in runs_dir.glob("*.json"):
        if path.name == INDEX_DB_NAME:
            continue
        actual[str(path.resolve())] = path.stat().st_mtime
    if _indexed_snapshot(runs_dir) != actual:
        scan_runs(runs_dir)


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

    conn = _connect(_index_path(runs_dir))
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


def get_family_results(
    runs_dir: Path | str | None = None,
    adapter: str | None = None,
    suite: str | None = None,
    dataset_version: str | None = None,
) -> list[dict[str, Any]]:
    """Per-family metrics across runs, joined with run metadata.

    One row per (run, family): adapter_name, adapter_version, suite,
    dataset_version, family, n, n_eligible, asr, asr_lo, asr_hi,
    refusal_rate. Withheld rates come back as None (stored as NULL,
    never 0.0). The index is rebuilt if stale.
    """
    runs_dir = _get_runs_dir(runs_dir)
    if not runs_dir.exists():
        return []
    _ensure_index_fresh(runs_dir)

    conn = sqlite3.connect(_index_path(runs_dir))
    try:
        conn.row_factory = sqlite3.Row
        query = (
            "SELECT r.adapter_name, r.adapter_version, r.suite, "
            "r.dataset_version, f.family, f.n, f.n_eligible, f.asr, "
            "f.asr_lo, f.asr_hi, f.refusal_rate "
            "FROM family_results f JOIN runs r ON f.run_path = r.path "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if adapter:
            query += " AND r.adapter_name = ?"
            params.append(adapter)
        if suite:
            query += " AND r.suite = ?"
            params.append(suite)
        if dataset_version:
            query += " AND r.dataset_version = ?"
            params.append(dataset_version)
        query += " ORDER BY r.adapter_name, r.created_utc, f.family"
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
    - metrics.ranking_eligible is true (the documented ranking gates:
      malformed rate at most 5%, benign accuracy at least 0.5, at least
      200 eligible cases overall, at least 20 eligible per required
      family (computed by metrics.check_eligibility at scoring time))

    Note: the full reproducibility grade (Layer 3b) is not yet
    implemented; this is the minimal gate.
    """
    if not artifact.verify():
        return False, "analysis lock invalid"
    if not artifact.manifest_sha256:
        return False, "not bound to a dataset manifest"
    if not artifact.adapter_version:
        return False, "adapter version not pinned"
    metrics = artifact.metrics or {}
    if not metrics.get("ranking_eligible", False):
        notes = metrics.get("eligibility_notes") or []
        detail = (
            "; ".join(str(n) for n in notes)
            if notes
            else "ranking eligibility not recorded"
        )
        return False, f"ranking-ineligible: {detail}"
    return True, "qualifies"
