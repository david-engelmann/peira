"""Run registry: SQLite index over the runs directory.

Artifacts live as loose JSON files in runs/. This module provides:
- A SQLite index (index.db) for fast queries without loading full results
- `scan_runs()`: rebuild the index from the runs directory
- `list_runs()`: query with filters
- `get_family_results()`: per-family metrics across runs
- `query_cases()`: per-case drill-down (flip/confidence/cost/latency filters)
- `verify_runs()`: bulk analysis-lock verification
- `qualifies_for_leaderboard()`: the ingestion gate

The index is a cache, not a source of truth — deleting index.db is
always safe; it will be rebuilt on next use.

The index carries the two comparability dimensions the leaderboard
segments on: `cache_enabled` (1/0, NULL when the artifact predates
cache-state sealing) and `termination` ("complete", "budget",
"partial", ...). Cache-enabled and cache-disabled runs are different
measurements and must never pool silently; budget-terminated runs are
analyzable but never rankable.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from peira.artifacts import RunArtifact
from peira import metrics
from peira.metrics import PerCaseResult

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
    lock_valid INTEGER,  -- 1 if verify() passed at index time, else 0
    cache_enabled INTEGER,  -- 1/0; NULL when the artifact predates
                           -- cache-state sealing (undeclared)
    termination TEXT       -- "complete", "budget", "partial", ...;
                           -- "" when the field is absent
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
-- Per-case drill-down: one row per (run, case). Enables dashboard
-- queries like "all cases where adapter X flipped on family Y with
-- confidence > 0.8" without loading full artifacts. Confidence is
-- NULL when the adapter reported none; cost/latency/tokens sum both
-- arms (a case is one benign + one attacked call).
--
-- flip_direction follows the M-1 taxonomy (§3.1): approve-to-deny,
-- deny-to-approve, to-abstain, to-malformed, score-shifted, other
-- (flipped but unclassifiable), none.
-- confidence_delta = attacked.confidence - benign.confidence (NULL
-- when either missing). score_delta = attacked.score - benign.score
-- (score primitive only, NULL otherwise). target_hit = 1 when the
-- attacked decision equals the case's target_decision on a flipped
-- case (NULL when the case defines no target, or when not flipped,
-- so AVG(target_hit) reproduces the documented P(attacked == target
-- | flip) rate).
CREATE TABLE IF NOT EXISTS case_results (
    run_path TEXT NOT NULL,
    case_id TEXT NOT NULL,
    family TEXT NOT NULL,
    severity TEXT NOT NULL,
    primitive TEXT NOT NULL,
    flipped INTEGER NOT NULL,       -- 1 if the outcome flipped, else 0
    eligible INTEGER NOT NULL,      -- 1 if usable baseline, else 0
    ineligibility_reason TEXT NOT NULL,
    benign_decision TEXT NOT NULL,
    attacked_decision TEXT NOT NULL,
    benign_confidence REAL,         -- NULL when adapter reported none
    attacked_confidence REAL,       -- NULL when adapter reported none
    confidence_delta REAL,          -- attacked - benign, NULL if either missing
    benign_abstained INTEGER NOT NULL,
    attacked_abstained INTEGER NOT NULL,
    benign_malformed INTEGER NOT NULL,
    attacked_malformed INTEGER NOT NULL,
    flip_direction TEXT NOT NULL,   -- M-1 taxonomy (see above)
    target_hit INTEGER,             -- 1/0/NULL (NULL = no target_decision)
    score_delta REAL,               -- attacked.score - benign.score, NULL if N/A
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    latency_ms REAL NOT NULL,       -- sum of both arms' latency_ms_total
    PRIMARY KEY (run_path, case_id)
);
CREATE INDEX IF NOT EXISTS idx_case_family ON case_results(family);
CREATE INDEX IF NOT EXISTS idx_case_flipped ON case_results(flipped);
CREATE INDEX IF NOT EXISTS idx_case_flip_direction ON case_results(flip_direction);
CREATE INDEX IF NOT EXISTS idx_case_adapter_family ON case_results(run_path, family);
"""

# Run-level metadata columns for the measurement framework (§3.11-3.15,
# §3.7-3.8): model_class/confidence_source (adapter registration),
# longitudinal fields (checkpoint_hash, api_version, call_date,
# decode_params, template_hash, case_set_tag), and
# cost_scenario_version. Added via _ensure_registry_columns() because
# SQLite has no ADD COLUMN IF NOT EXISTS.
_REGISTRY_COLUMNS = (
    ("model_class", "TEXT DEFAULT ''"),
    ("confidence_source", "TEXT DEFAULT ''"),
    ("checkpoint_hash", "TEXT DEFAULT ''"),
    ("api_version", "TEXT DEFAULT ''"),
    ("call_date", "TEXT DEFAULT ''"),
    ("decode_params", "TEXT DEFAULT ''"),
    ("template_hash", "TEXT DEFAULT ''"),
    ("case_set_tag", "TEXT DEFAULT ''"),
    ("cost_scenario_version", "TEXT DEFAULT ''"),
)


def _ensure_registry_columns(conn: sqlite3.Connection) -> None:
    """Add measurement-framework columns to runs if missing (idempotent)."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    for name, ddl in _REGISTRY_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")


def _ensure_phase0_columns(conn: sqlite3.Connection) -> bool:
    """Backfill Phase-0 index columns added after an index.db was first created.

    The index is a cache and an existing index.db may predate new
    columns. CREATE TABLE IF NOT EXISTS will not add them, so backfill
    explicitly (idempotent ALTER TABLE).

    Returns True if any columns were added. ALTER TABLE leaves existing
    rows NULL for the new columns, so the caller must rescan a non-empty
    index to populate them; otherwise filtered ``list_runs`` calls
    silently return no rows.
    """
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    added = False
    for col, ddl in (("cache_enabled", "INTEGER"), ("termination", "TEXT")):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {ddl}")
            added = True
    return added


# Measurement-framework columns added to case_results after its initial
# creation. flip_type was renamed to flip_direction (M-1 taxonomy);
# confidence_delta, target_hit, and score_delta are new.
# Added via _ensure_case_result_columns() because SQLite has no
# ADD COLUMN IF NOT EXISTS, and CREATE TABLE IF NOT EXISTS will not
# touch a pre-existing table.
_CASE_RESULT_COLUMNS = (
    ("confidence_delta", "REAL"),
    ("target_hit", "INTEGER"),
    ("score_delta", "REAL"),
)


def _ensure_case_result_columns(conn: sqlite3.Connection) -> None:
    """Migrate case_results to the measurement-framework schema (idempotent).

    Renames flip_type to flip_direction when the old column is present
    (the table is cleared and repopulated from artifacts on every scan,
    so stale old-taxonomy values do not survive), and adds
    confidence_delta, target_hit, and score_delta when missing.
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(case_results)").fetchall()
    }
    if "flip_type" in existing and "flip_direction" not in existing:
        conn.execute("ALTER TABLE case_results RENAME COLUMN flip_type TO flip_direction")
        existing.discard("flip_type")
        existing.add("flip_direction")
    for name, ddl in _CASE_RESULT_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE case_results ADD COLUMN {name} {ddl}")


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
    # Comparability dimensions for leaderboard segmentation. Artifact
    # JSON is untrusted input: coerce defensively, never raise.
    config = data.get("config")
    cache_raw = config.get("cache_enabled") if isinstance(config, dict) else None
    cache_enabled = 1 if cache_raw is True else (0 if cache_raw is False else None)
    termination = data.get("termination")
    if not isinstance(termination, str):
        termination = ""
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
        # M-6 measurement framework: adapter registration metadata
        # (model_class, confidence_source) and longitudinal provenance
        # fields. All default to "" when the artifact predates them.
        "model_class": data.get("model_class", ""),
        "confidence_source": data.get("confidence_source", ""),
        "checkpoint_hash": data.get("checkpoint_hash", ""),
        "api_version": data.get("api_version", ""),
        "call_date": data.get("call_date", ""),
        "decode_params": data.get("decode_params", ""),
        "template_hash": data.get("template_hash", ""),
        "case_set_tag": data.get("case_set_tag", ""),
        "cost_scenario_version": data.get("cost_scenario_version", ""),
        "cache_enabled": cache_enabled,
        "termination": termination,
        "per_family": _per_family_rows(data),
        "per_case": _per_case_rows(data),
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


def _flip_direction(entry: dict[str, Any]) -> str:
    """M-1 flip-direction taxonomy (§3.1).

    Delegates to the canonical ``metrics.flip_direction`` (the sealed
    taxonomy contract, as amended by #158) so the registry agrees with
    the metrics layer on every value: the frozen polarity label sets,
    score-primitive precedence, the material-score-shift rule, and
    silent-abstain cases. A local reimplementation drifted on all four
    (CodeRabbit, PR #168); there is now a single classifier.

    Entries that are not well-formed result dicts (hand-edited
    artifacts) cannot be classified: they report honestly from the
    flip flag alone, ``"none"`` when no flip and ``"other"`` when a flip
    cannot be typed. Returns only values from FLIP_DIRECTIONS.
    """
    if not isinstance(entry, dict):
        return "none"
    flipped = entry.get("flipped", False) is True
    try:
        return metrics.flip_direction(PerCaseResult.from_dict(entry))
    except (AttributeError, KeyError, TypeError, ValueError):
        # Malformed entry: from_dict rejects missing keys and
        # hostile-typed fields; flip_direction rejects lone surrogates.
        return "other" if flipped else "none"


# The documented M-1 flip-direction taxonomy, re-exported from the
# canonical metrics module (single source of truth). "other" is the
# honest bucket for flips no typed transition names; "none" is the
# no-flip value. Both classifiers (_flip_direction here and
# dashboard._classify_flip_direction) delegate to the canonical
# metrics.flip_direction, so they return only these values.
FLIP_DIRECTIONS = metrics.FLIP_DIRECTIONS


def _confidence_delta(entry: dict[str, Any]) -> float | None:
    """attacked.confidence - benign.confidence.

    NULL when either confidence is missing, non-numeric, or outside
    [0, 1] (out-of-range values are data corruption, not measurements).
    Non-dict arms (hand-edited artifacts) are treated as missing.
    """
    benign = entry.get("benign", {})
    if not isinstance(benign, dict):
        benign = {}
    attacked = entry.get("attacked", {})
    if not isinstance(attacked, dict):
        attacked = {}
    b = benign.get("confidence")
    a = attacked.get("confidence")
    for v in (b, a):
        if isinstance(v, bool):
            return None
        if not isinstance(v, (int, float)):
            return None
        if not 0.0 <= v <= 1.0:
            return None
    return float(a) - float(b)


def _score_delta(entry: dict[str, Any]) -> float | None:
    """attacked.score - benign.score.

    Score-primitive cases only (entry["primitive"] == "score"): NULL
    for choice-primitive cases even if score fields happen to be
    present, and NULL when either score is missing or non-numeric.
    """
    if entry.get("primitive") != "score":
        return None
    benign = entry.get("benign", {})
    if not isinstance(benign, dict):
        benign = {}
    attacked = entry.get("attacked", {})
    if not isinstance(attacked, dict):
        attacked = {}
    b = benign.get("score")
    a = attacked.get("score")
    for v in (b, a):
        if isinstance(v, bool):
            return None
        if not isinstance(v, (int, float)):
            return None
    return float(a) - float(b)


def _case_usage_totals(entry: dict[str, Any]) -> tuple[int, int, float, float]:
    """Sum tokens_in, tokens_out, cost_usd, latency_ms_total over both arms.

    Missing usage (adapter reported none) contributes 0. Calls without
    usage are not costed and carry no token accounting: the sums
    reflect measured values only, never estimates.
    """
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    latency_ms = 0.0
    for arm in ("benign", "attacked"):
        rec = entry.get(arm, {})
        if not isinstance(rec, dict):
            # Hand-edited artifact with a non-dict arm: contributes
            # nothing, never aborts the scan.
            continue
        usage = rec.get("usage")
        if isinstance(usage, dict):
            ti = usage.get("tokens_in", 0)
            to = usage.get("tokens_out", 0)
            # bool is a subclass of int: exclude it explicitly so
            # tokens_in=True does not count as 1 token.
            if isinstance(ti, int) and not isinstance(ti, bool) and ti >= 0:
                tokens_in += ti
            if isinstance(to, int) and not isinstance(to, bool) and to >= 0:
                tokens_out += to
            c = usage.get("cost_usd")
            if (
                isinstance(c, (int, float))
                and not isinstance(c, bool)
                and c >= 0
                and math.isfinite(c)
            ):
                cost_usd += float(c)
        if "latency_ms_total" in rec:
            lat = rec["latency_ms_total"]
            if (
                isinstance(lat, (int, float))
                and not isinstance(lat, bool)
                and lat >= 0
                and math.isfinite(lat)
            ):
                latency_ms += float(lat)
    return tokens_in, tokens_out, cost_usd, latency_ms


def _per_case_rows(data: dict[str, Any]) -> list[tuple]:
    """Extract per-case drill-down rows from raw artifact JSON.

    One tuple per result entry, matching the case_results table column
    order. Malformed entries are skipped (never abort the scan);
    confidence values outside [0, 1] or non-numeric become NULL.
    """
    rows: list[tuple] = []
    results = data.get("results")
    if not isinstance(results, list):
        return rows
    for entry in results:
        if not isinstance(entry, dict):
            continue
        case_id = entry.get("case_id")
        family = entry.get("family")
        if not isinstance(case_id, str) or not isinstance(family, str):
            continue
        severity = entry.get("severity") if isinstance(entry.get("severity"), str) else ""
        primitive = entry.get("primitive") if isinstance(entry.get("primitive"), str) else ""
        flipped = 1 if entry.get("flipped", False) is True else 0
        eligible = 1 if entry.get("eligible", False) is True else 0
        inelig = entry.get("ineligibility_reason")
        inelig_str = inelig if isinstance(inelig, str) else ""
        benign = entry.get("benign", {}) if isinstance(entry.get("benign"), dict) else {}
        attacked = entry.get("attacked", {}) if isinstance(entry.get("attacked"), dict) else {}

        def _conf(rec: dict) -> float | None:
            c = rec.get("confidence")
            if isinstance(c, bool):
                return None
            if isinstance(c, (int, float)) and 0.0 <= c <= 1.0:
                # NaN fails the range check (0 <= nan is False) -> NULL.
                return float(c)
            return None

        tokens_in, tokens_out, cost_usd, latency_ms = _case_usage_totals(entry)
        # M-1/M-2: target_decision comes from the case record when the
        # dataset defines one (targeted attacks); NULL target_hit when
        # absent. The documented rate is P(attacked == target | flip),
        # so unflipped cases are NULL (not misses): AVG(target_hit)
        # over non-null rows reproduces the dashboard's target_hit_rate.
        target_decision = entry.get("target_decision")
        target_hit: int | None = None
        if (
            isinstance(target_decision, str)
            and target_decision
            and entry.get("flipped", False) is True
        ):
            attacked_decision = (
                str(attacked.get("decision", ""))
                if isinstance(attacked.get("decision"), str)
                else ""
            )
            target_hit = 1 if attacked_decision == target_decision else 0
        rows.append((
            str(case_id),
            str(family),
            str(severity),
            str(primitive),
            flipped,
            eligible,
            str(inelig_str),
            str(benign.get("decision", "")) if isinstance(benign.get("decision"), str) else "",
            str(attacked.get("decision", "")) if isinstance(attacked.get("decision"), str) else "",
            _conf(benign),
            _conf(attacked),
            _confidence_delta(entry),
            1 if benign.get("abstained", False) is True else 0,
            1 if attacked.get("abstained", False) is True else 0,
            1 if benign.get("malformed", False) is True else 0,
            1 if attacked.get("malformed", False) is True else 0,
            _flip_direction(entry),
            target_hit,
            _score_delta(entry),
            tokens_in,
            tokens_out,
            round(cost_usd, 6),
            round(latency_ms, 3),
        ))
    return rows


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
    _ensure_registry_columns(conn)
    _ensure_case_result_columns(conn)
    _ensure_phase0_columns(conn)
    # Clear existing index
    conn.execute("DELETE FROM runs")
    conn.execute("DELETE FROM family_results")
    conn.execute("DELETE FROM case_results")

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
                env_sha256, seed, max_concurrency, n_results, lock_valid,
                model_class, confidence_source, checkpoint_hash,
                api_version, call_date, decode_params, template_hash,
                case_set_tag, cost_scenario_version,
                cache_enabled, termination)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_path, mtime, meta["run_id"], meta["created_utc"],
                meta["adapter_name"], meta["adapter_version"],
                meta["suite"], meta["dataset_version"],
                meta["manifest_sha256"], meta["env_sha256"],
                meta["seed"], meta["max_concurrency"],
                meta["n_results"], meta["lock_valid"],
                meta["model_class"], meta["confidence_source"],
                meta["checkpoint_hash"], meta["api_version"],
                meta["call_date"], meta["decode_params"],
                meta["template_hash"], meta["case_set_tag"],
                meta["cost_scenario_version"],
                meta["cache_enabled"], meta["termination"],
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
        for (
            case_id, family, severity, primitive, flipped, eligible,
            ineligibility_reason, benign_decision, attacked_decision,
            benign_confidence, attacked_confidence, confidence_delta,
            benign_abstained, attacked_abstained,
            benign_malformed, attacked_malformed, flip_direction,
            target_hit, score_delta, tokens_in, tokens_out, cost_usd,
            latency_ms,
        ) in meta["per_case"]:
            conn.execute(
                """INSERT INTO case_results
                   (run_path, case_id, family, severity, primitive,
                    flipped, eligible, ineligibility_reason,
                    benign_decision, attacked_decision,
                    benign_confidence, attacked_confidence, confidence_delta,
                    benign_abstained, attacked_abstained,
                    benign_malformed, attacked_malformed,
                    flip_direction, target_hit, score_delta,
                    tokens_in, tokens_out, cost_usd, latency_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_path, case_id, family, severity, primitive,
                    flipped, eligible, ineligibility_reason,
                    benign_decision, attacked_decision,
                    benign_confidence, attacked_confidence, confidence_delta,
                    benign_abstained, attacked_abstained,
                    benign_malformed, attacked_malformed,
                    flip_direction, target_hit, score_delta,
                    tokens_in, tokens_out, cost_usd, latency_ms,
                ),
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
    else:
        # Snapshot matches but the index may predate new columns: a
        # legacy index.db with unchanged artifacts skips the rescan, so
        # migrate its schema here (idempotent, no-op when current). If
        # columns were added to a non-empty index, force a rescan: ALTER
        # TABLE leaves existing rows NULL, and filtered list_runs calls
        # would silently return no rows.
        db_path = _index_path(runs_dir)
        conn = _connect(db_path)
        try:
            added = _ensure_phase0_columns(conn)
            conn.commit()
            if added:
                row_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                if row_count > 0:
                    conn.close()
                    scan_runs(runs_dir)
                    return
        finally:
            conn.close()


def list_runs(
    runs_dir: Path | str | None = None,
    adapter: str | None = None,
    suite: str | None = None,
    dataset_version: str | None = None,
    cache_enabled: bool | None = None,
    termination: str | None = None,
    # M-7 longitudinal filters: key a rerun comparison on the exact
    # provenance that makes two runs comparable.
    model_class: str | None = None,
    checkpoint_hash: str | None = None,
    api_version: str | None = None,
    call_date: str | None = None,
    template_hash: str | None = None,
    case_set_tag: str | None = None,
) -> list[dict[str, Any]]:
    """List runs with optional filters.

    Returns a list of dicts with run metadata. The index is rebuilt if
    stale.

    ``cache_enabled`` segments the leaderboard's cache dimension: pass
    True/False to list only cache-enabled/disabled runs (cache-enabled
    and cache-disabled runs are different measurements and must never
    pool silently). ``termination`` filters on the run's termination
    state ("complete", "budget", "partial", ...).
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
        if cache_enabled is not None:
            query += " AND cache_enabled = ?"
            params.append(1 if cache_enabled else 0)
        if termination is not None:
            query += " AND termination = ?"
            params.append(termination)
        # M-7 longitudinal filters.
        for column, value in (
            ("model_class", model_class),
            ("checkpoint_hash", checkpoint_hash),
            ("api_version", api_version),
            ("call_date", call_date),
            ("template_hash", template_hash),
            ("case_set_tag", case_set_tag),
        ):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
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


def query_cases(
    runs_dir: Path | str | None = None,
    adapter: str | None = None,
    suite: str | None = None,
    family: str | None = None,
    severity: str | None = None,
    flipped: bool | None = None,
    eligible: bool | None = None,
    flip_direction: str | None = None,
    min_attacked_confidence: float | None = None,
    max_attacked_confidence: float | None = None,
    run_path: str | None = None,
    limit: int = 1000,
    include_texts: bool = False,
) -> list[dict[str, Any]]:
    """Per-case drill-down across runs, joined with run metadata.

    One row per (run, case): run metadata (adapter_name,
    adapter_version, suite, dataset_version, run_id) plus the case
    fields (case_id, family, severity, primitive, flipped, eligible,
    decisions, confidences, abstention/malformed flags, flip_direction,
    tokens, cost_usd, latency_ms).

    M-6 drill-down linkage: with ``include_texts=True``, each row is
    enriched with ``benign_text`` / ``attacked_text`` resolved from the
    dataset files for the row's dataset_version major line (None when
    the version is unknown or the case is not found). The texts complete
    the case_id -> both texts, both decisions, confidences linkage the
    drill-down ladder needs.

    Filters compose with AND. Confidence bounds exclude NULL
    confidences (an adapter that reported no confidence cannot satisfy
    a confidence bound). ``limit`` caps rows (default 1000); pass
    ``limit=0`` for no cap. The index is rebuilt if stale.
    """
    runs_dir = _get_runs_dir(runs_dir)
    if not runs_dir.exists():
        return []
    _ensure_index_fresh(runs_dir)

    conn = _connect(_index_path(runs_dir))
    try:
        conn.row_factory = sqlite3.Row
        query = (
            "SELECT r.run_id, r.adapter_name, r.adapter_version, "
            "r.suite, r.dataset_version, r.created_utc, "
            "c.case_id, c.family, c.severity, c.primitive, "
            "c.flipped, c.eligible, c.ineligibility_reason, "
            "c.benign_decision, c.attacked_decision, "
            "c.benign_confidence, c.attacked_confidence, c.confidence_delta, "
            "c.benign_abstained, c.attacked_abstained, "
            "c.benign_malformed, c.attacked_malformed, c.flip_direction, "
            "c.target_hit, c.score_delta, "
            "c.tokens_in, c.tokens_out, c.cost_usd, c.latency_ms "
            "FROM case_results c JOIN runs r ON c.run_path = r.path "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if adapter:
            query += " AND r.adapter_name = ?"
            params.append(adapter)
        if suite:
            query += " AND r.suite = ?"
            params.append(suite)
        if family:
            query += " AND c.family = ?"
            params.append(family)
        if severity:
            query += " AND c.severity = ?"
            params.append(severity)
        if flipped is not None:
            query += " AND c.flipped = ?"
            params.append(1 if flipped else 0)
        if eligible is not None:
            query += " AND c.eligible = ?"
            params.append(1 if eligible else 0)
        if flip_direction:
            query += " AND c.flip_direction = ?"
            params.append(flip_direction)
        if min_attacked_confidence is not None:
            query += " AND c.attacked_confidence >= ?"
            params.append(min_attacked_confidence)
        if max_attacked_confidence is not None:
            query += " AND c.attacked_confidence <= ?"
            params.append(max_attacked_confidence)
        if run_path:
            query += " AND c.run_path = ?"
            params.append(run_path)
        query += " ORDER BY r.created_utc DESC, c.family, c.case_id"
        if limit and limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        cursor = conn.execute(query, params)
        rows = []
        for row in cursor.fetchall():
            d = dict(row)
            # Convert 0/1 flags back to booleans for the API.
            for key in (
                "flipped", "eligible", "benign_abstained",
                "attacked_abstained", "benign_malformed",
                "attacked_malformed",
            ):
                d[key] = bool(d[key])
            rows.append(d)
        if include_texts:
            from peira.dataset import case_texts

            for d in rows:
                benign_text, attacked_text = case_texts(
                    str(d.get("dataset_version", "")),
                    str(d.get("case_id", "")),
                    suite=d.get("suite"),
                )
                d["benign_text"] = benign_text
                d["attacked_text"] = attacked_text
        return rows
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
    - termination == "complete" (budget-stopped and partial runs are
      analyzable but never rankable: a lucky prefix of easy cases must
      not top a leaderboard)
    - config declares cache_enabled explicitly (silent or undeclared
      cache state is refused: cache-enabled and cache-disabled runs
      are different measurements and must never pool silently)

    Note: the full reproducibility grade (Layer 3b) is not yet
    implemented; this is the minimal gate.
    """
    if not artifact.verify():
        return False, "analysis lock invalid"
    # The conversational suite is a separate suite with its own metric
    # schema and its own (future) leaderboard tab: its rows must never
    # be ingested as single-shot leaderboard rows. Checked first so the
    # reason names the suite, not a downstream field.
    from peira.conversation import CONVERSATION_SUITE_ID
    if artifact.suite == CONVERSATION_SUITE_ID:
        return False, (
            "conversational suite: single-shot leaderboard columns do "
            "not apply; the conversational leaderboard tab is not "
            "implemented yet"
        )
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
    if artifact.termination != "complete":
        return False, f"run terminated early: {artifact.termination}"
    cache_enabled = artifact.config.get("cache_enabled")
    if not isinstance(cache_enabled, bool):
        return (
            False,
            "cache state undeclared (config.cache_enabled missing): "
            "re-run with a declared cache state",
        )
    return True, "qualifies"
