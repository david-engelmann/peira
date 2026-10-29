"""Restart-surviving checkpointing for the seal summarize.

:func:`peira.metrics.summarize` spends its time in a handful of
bootstrap primitives, each a replicate loop over a fresh
``random.Random(seed)``. The loops are monolithic: a process death
(VM restart, OOM kill, operator interrupt) near the end of a long
seal loses the whole computation. On 2026-10-27 the seal of a
4,701-case run died seven times this way before this machinery
landed in the trial drivers.

The wrappers in this module replace those primitives (the module
globals in :mod:`peira.metrics` and :mod:`peira.eb_analysis`) for
the duration of one summarize call. Each wrapper copies its
original's validation and loop body verbatim; the only change is
that the loop runs in wall-clock chunks and persists (RNG state,
accumulated replicate values) to a JSON sidecar after every chunk.
``random.Random.getstate``/``setstate`` round-trips the complete
Mersenne-Twister state bit-exactly and the replicate values are
JSON floats (repr round-trip), so chunk boundaries are invisible
to the arithmetic: the draw sequence, the per-replicate float
operations and their order, and the final reduction over the full
values list are the original code's. Results are bit-identical to
the monolithic path, which the test suite proves on every
primitive and on full summaries (``tests/test_seal_checkpointing.py``).

Completed calls cache their result in the sidecar, so a restarted
summarize replays finished bootstraps in O(1) and resumes the one
that was interrupted. Entries are keyed by call ordinal (execution
order, deterministic for a pure summarize) and guarded by a run
fingerprint over the results payload, the summarize parameters,
and the metrics/eb source files: a sidecar written for other
inputs or other code is ignored wholesale. Correctness never
depends on a checkpoint: the worst case is a recompute.

Opt-in only. :func:`peira.metrics.summarize` and
:func:`peira.runner.run_suite` checkpoint only when the caller
passes a checkpoint directory, and the ``PEIRA_SEAL_MONOLITHIC``
environment variable (any non-empty value) forces the monolithic
path even then, matching the trial drivers' kill switch.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import random
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import peira.eb_analysis as _eb_mod
import peira.metrics as _metrics_mod

#: Sidecar format version. A sidecar with any other format value
#: is ignored (treated as absent), never migrated.
SEAL_CKPT_FORMAT = 1

#: File name of the checkpoint sidecar inside the checkpoint dir.
SIDECAR_FILENAME = "sealckpt.json"

#: File name of the runner's pre-seal snapshot inside the
#: checkpoint dir (see :func:`peira.runner.run_suite`).
SNAPSHOT_FILENAME = "sealartifact.json"

#: Kill switch: any non-empty value forces the monolithic path.
KILL_SWITCH_ENV = "PEIRA_SEAL_MONOLITHIC"

#: Chunk-length override (seconds), read once at import.
CHUNK_SECONDS_ENV = "PEIRA_SEAL_CHUNK_SECONDS"

_DEFAULT_CHUNK_SECONDS = 45.0


def _read_chunk_seconds() -> float:
    """Parse ``PEIRA_SEAL_CHUNK_SECONDS`` defensively.

    An invalid, negative, or non-finite value falls back to the
    default instead of breaking the import of this module (and
    with it, of the runner) for runs that never opt into
    checkpointing.
    """
    raw = os.environ.get(CHUNK_SECONDS_ENV, "")
    if not raw:
        return _DEFAULT_CHUNK_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_CHUNK_SECONDS
    if not math.isfinite(value) or value < 0:
        return _DEFAULT_CHUNK_SECONDS
    return value


_CHUNK_SECONDS = _read_chunk_seconds()


def seal_checkpointing_active(checkpoint_dir: Path | str | None) -> bool:
    """True when a summarize should run its checkpointed path.

    Checkpointing is on only when the caller supplied a directory
    AND the kill switch is unset (or empty). This is the single
    gate every entry point consults, so the kill switch behaves
    identically for direct summarize calls and runner seals.
    """
    if checkpoint_dir is None:
        return False
    return not os.environ.get(KILL_SWITCH_ENV)


def _rng_state_to_json(rng: random.Random) -> list:
    ver, internal, gauss = rng.getstate()
    return [ver, list(internal), gauss]


def _rng_from_json(state: list, seed: int) -> random.Random:
    rng = random.Random(seed)
    ver, internal, gauss = state
    rng.setstate((int(ver), tuple(int(x) for x in internal), gauss))
    return rng


def _encode_result(result: Any, kind: str) -> Any:
    if kind == "float":
        return float(result)
    if result is None:
        return None
    return [result[0], result[1]]


def _decode_result(entry: dict) -> Any:
    raw = entry["result"]
    if entry["kind"] == "float":
        return float(raw)
    if raw is None:
        return None
    return (raw[0], raw[1])


def _call_fp(name: str, seed: int, n_boot: int, n: Any,
             stat_fp: str = "") -> str:
    h = hashlib.sha256()
    h.update(f"{name}|{seed}|{n_boot}|{n}|{stat_fp}".encode())
    return h.hexdigest()[:32]


#: Bounded retry policy shared by the sidecar flush and the
#: runner's snapshot persist. Some filesystems refuse writes with
#: EPERM for tens of seconds at a time (observed 2026-10-27 in the
#: sandbox); ride bursts out with backoff for up to ~10 minutes.
_WRITE_RETRY_DEADLINE_S = 600.0
_WRITE_RETRY_INITIAL_DELAY_S = 5.0
_WRITE_RETRY_MAX_DELAY_S = 30.0


def _with_write_retry(operation):
    """Run ``operation(attempt)`` retrying OSError with backoff.

    Returns the operation's result on the first success. Raises
    the last OSError once the shared deadline has passed.
    """
    last_exc: OSError | None = None
    deadline = time.monotonic() + _WRITE_RETRY_DEADLINE_S
    delay = _WRITE_RETRY_INITIAL_DELAY_S
    attempt = 0
    while True:
        try:
            return operation(attempt)
        except OSError as exc:
            last_exc = exc
            if time.monotonic() >= deadline:
                raise last_exc
            time.sleep(delay)
            delay = min(delay * 1.5, _WRITE_RETRY_MAX_DELAY_S)
            attempt += 1


def _rng_state_shape_ok(state: Any) -> bool:
    """True for a JSON RNG state of [version, 625 ints, gauss]."""
    if not isinstance(state, (list, tuple)) or len(state) != 3:
        return False
    ver, internal, gauss = state
    if isinstance(ver, bool) or not isinstance(ver, int):
        return False
    if not isinstance(internal, (list, tuple)):
        return False
    if len(internal) != 625:
        return False
    if any(
        isinstance(x, bool) or not isinstance(x, int)
        or not 0 <= x < 2**32
        for x in internal
    ):
        return False
    return gauss is None or (
        not isinstance(gauss, bool)
        and isinstance(gauss, (int, float))
        and math.isfinite(gauss)
    )


def _is_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _entry_shape_ok(entry: Any) -> bool:
    """True when a sidecar entry carries a usable, decodable payload.

    Entries that fail this are accidental corruption (hand edits,
    torn state the atomic publish could not produce). The store
    drops them at load so the affected calls recompute.
    """
    if not isinstance(entry, dict):
        return False
    if not isinstance(entry.get("fp"), str):
        return False
    if entry.get("done"):
        kind = entry.get("kind")
        if kind not in ("float", "tuple2", "tuple2_or_none"):
            return False
        if "result" not in entry:
            return False
        raw = entry["result"]
        if kind == "float":
            return _is_number(raw)
        if raw is None:
            return kind == "tuple2_or_none"
        return (
            isinstance(raw, (list, tuple)) and len(raw) == 2
            and all(_is_number(x) for x in raw)
        )
    if "raw" in entry:
        raw = entry["raw"]
        if not isinstance(raw, dict):
            return False
        if raw.get("loop_done"):
            return isinstance(raw.get("p_values"), list)
        return (
            isinstance(raw.get("ti"), int)
            and not isinstance(raw.get("ti"), bool)
            and isinstance(raw.get("reps"), int)
            and not isinstance(raw.get("reps"), bool)
            and isinstance(raw.get("cur"), list)
            and isinstance(raw.get("p_values"), list)
            and _rng_state_shape_ok(raw.get("rng"))
        )
    if "values" in entry:
        return (
            isinstance(entry.get("values"), list)
            and isinstance(entry.get("reps"), int)
            and not isinstance(entry.get("reps"), bool)
            and _rng_state_shape_ok(entry.get("rng"))
        )
    return False


def _stat_fp(stat: Any) -> str:
    code = getattr(stat, "__code__", None)
    parts = [getattr(stat, "__qualname__", type(stat).__name__)]
    if code is not None:
        parts.append(hashlib.sha256(code.co_code).hexdigest()[:16])
    cells = []
    for cell in (getattr(stat, "__closure__", None) or ()):
        try:
            value = cell.cell_contents
        except ValueError:
            value = "<empty>"
        cells.append(
            repr(value)
            if isinstance(value, (int, float, str, bool, type(None)))
            else type(value).__name__)
    parts.append(";".join(cells))
    parts.append(repr(getattr(stat, "__defaults__", None)))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class SealCheckpointStore:
    """JSON sidecar with per-call bootstrap checkpoints for one seal.

    Entry shapes, keyed by call ordinal:
      partial: {"fp", "done": False, "rng", "values", "reps"}
      done:    {"fp", "done": True, "result", "kind"}
      raw:     {"fp", "raw": {...}}  (length_confound_diagnostics)
    A fingerprint mismatch at ordinal k discards entries >= k: the
    execution order is assumed shifted, so later checkpoints can no
    longer be trusted to belong to the calls now taking those
    ordinals. Correctness never depends on a checkpoint: worst case
    is a recompute.
    """

    def __init__(self, path: Path | str, run_fp: str) -> None:
        self._path = Path(path)
        self._data: dict[str, Any] = {
            "format": SEAL_CKPT_FORMAT, "run_fp": run_fp, "calls": {},
        }
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                loaded = None
            if (isinstance(loaded, dict)
                    and loaded.get("format") == SEAL_CKPT_FORMAT
                    and loaded.get("run_fp") == run_fp
                    and isinstance(loaded.get("calls"), dict)):
                self._data = loaded
        self._calls: dict[str, Any] = self._data["calls"]
        self._prune_malformed_entries()

    def _prune_malformed_entries(self) -> None:
        """Drop entries whose shape cannot be trusted.

        Keys that do not parse as ordinals are dropped on their
        own. A malformed entry at ordinal k prunes every entry
        >= k, consistent with the fingerprint-mismatch rule in
        :meth:`_claim` (execution order may have shifted, so
        later checkpoints can no longer be trusted either).
        The affected calls recompute.
        """
        bad_from: int | None = None
        for key in list(self._calls):
            try:
                ordinal = int(key)
            except (TypeError, ValueError):
                del self._calls[key]
                continue
            if str(ordinal) != key or not _entry_shape_ok(
                self._calls[key]
            ):
                if bad_from is None or ordinal < bad_from:
                    bad_from = ordinal
        if bad_from is not None:
            for key in list(self._calls):
                try:
                    ordinal = int(key)
                except (TypeError, ValueError):
                    del self._calls[key]
                    continue
                if ordinal >= bad_from:
                    del self._calls[key]
        self._ordinal = 0
        self._active: int | None = None
        self._active_fp: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _flush(self) -> None:
        # Atomic publish: write a tmp sibling, then os.replace. Some
        # filesystems refuse writes with EPERM for tens of seconds at
        # a time (observed 2026-10-27 in the sandbox: two crashes, the
        # second after 6 retries over ~15 s). Ride them out: retry
        # with backoff for up to ~10 minutes across rotating tmp
        # names. Giving up even then is safe: the exception aborts
        # the seal attempt and the next launch resumes from the last
        # successfully flushed state.
        payload = json.dumps(self._data)

        def _attempt(attempt: int) -> None:
            tmp = self._path.with_name(
                self._path.name + f".tmp{attempt % 3}")
            tmp.write_text(payload, encoding="utf-8")
            # fsync before the replace, matching the snapshot
            # writer's durability: a crash must not lose a chunk
            # the flush reported as persisted.
            fd = os.open(tmp, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self._path)

        _with_write_retry(_attempt)

    def _claim(self, fp: str) -> dict | None:
        """Assign the next ordinal; prune on fingerprint mismatch."""
        ordinal = self._ordinal
        self._ordinal += 1
        self._active = ordinal
        self._active_fp = fp
        entry = self._calls.get(str(ordinal))
        if not isinstance(entry, dict):
            entry = None
        if entry is not None and entry.get("fp") != fp:
            for key in list(self._calls):
                try:
                    key_ordinal = int(key)
                except (TypeError, ValueError):
                    del self._calls[key]
                    continue
                if key_ordinal >= ordinal:
                    del self._calls[key]
            entry = None
        return entry

    def begin(self, fp: str, seed: int) -> tuple:
        """("cached", result) | ("run", rng, values, reps)."""
        entry = self._claim(fp)
        if entry is not None and entry.get("done"):
            return ("cached", _decode_result(entry))
        if entry is not None and "values" in entry:
            rng = _rng_from_json(entry["rng"], seed)
            return ("run", rng, list(entry["values"]),
                    int(entry["reps"]))
        return ("run", random.Random(seed), [], 0)

    def save(self, rng: random.Random, values: list, reps: int) -> None:
        self._calls[str(self._active)] = {
            "fp": self._active_fp, "done": False,
            "rng": _rng_state_to_json(rng),
            "values": list(values), "reps": reps,
        }
        self._flush()

    def finish(self, result: Any, kind: str) -> None:
        self._calls[str(self._active)] = {
            "fp": self._active_fp, "done": True,
            "result": _encode_result(result, kind), "kind": kind,
        }
        self._flush()

    def begin_raw(self, fp: str) -> dict | None:
        entry = self._claim(fp)
        if entry is not None and "raw" in entry:
            return entry["raw"]
        return None

    def save_raw(self, raw: dict) -> None:
        self._calls[str(self._active)] = {
            "fp": self._active_fp, "raw": raw,
        }
        self._flush()


def _chunk_loop(store: SealCheckpointStore, rng: random.Random,
                values: list, reps: int, n_boot: int, rep_fn) -> int:
    """Run rep_fn(values) until reps == n_boot, saving per chunk."""
    while reps < n_boot:
        deadline = time.monotonic() + _CHUNK_SECONDS
        while reps < n_boot:
            rep_fn(values)
            reps += 1
            if reps % 16 == 0 and time.monotonic() >= deadline:
                break
        store.save(rng, values, reps)
    return reps


# ------------------------------------------------------------ metrics primitives

def _ck_paired_bootstrap_ci(store, xs, ys, n_boot=10000, seed=0):
    _metrics_mod._check_paired(xs, ys, "xs", "ys")
    _metrics_mod._check_n_boot(n_boot)
    _metrics_mod._check_finite(xs, "xs")
    _metrics_mod._check_finite(ys, "ys")
    fp = _call_fp("paired_bootstrap_ci", seed, n_boot, len(xs))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, diffs, reps = begun
    randbelow = _metrics_mod._bootstrap_randbelow(rng)
    n = len(xs)
    xs_get = xs.__getitem__
    ys_get = ys.__getitem__

    def _rep(values):
        idx = [randbelow(n) for _ in range(n)]
        values.append(
            sum(map(xs_get, idx)) / n - sum(map(ys_get, idx)) / n
        )

    _chunk_loop(store, rng, diffs, reps, n_boot, _rep)
    diffs = sorted(diffs)
    out = (diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)])
    store.finish(out, "tuple2")
    return out


def _ck_unpaired_bootstrap_ci(store, xs, ys, n_boot=10000, seed=0):
    if not xs or not ys:
        raise ValueError("xs and ys must be non-empty")
    _metrics_mod._check_n_boot(n_boot)
    _metrics_mod._check_finite(xs, "xs")
    _metrics_mod._check_finite(ys, "ys")
    fp = _call_fp("_unpaired_bootstrap_ci", seed, n_boot,
                  (len(xs), len(ys)))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, diffs, reps = begun
    randbelow = _metrics_mod._bootstrap_randbelow(rng)
    nx, ny = len(xs), len(ys)
    xs_get = xs.__getitem__
    ys_get = ys.__getitem__

    def _rep(values):
        idx_x = [randbelow(nx) for _ in range(nx)]
        idx_y = [randbelow(ny) for _ in range(ny)]
        values.append(
            sum(map(xs_get, idx_x)) / nx
            - sum(map(ys_get, idx_y)) / ny
        )

    _chunk_loop(store, rng, diffs, reps, n_boot, _rep)
    diffs = sorted(diffs)
    out = (diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)])
    store.finish(out, "tuple2")
    return out


def _ck_paired_bootstrap_se(store, xs, ys, n_boot=10000, seed=0):
    _metrics_mod._check_paired(xs, ys, "xs", "ys")
    _metrics_mod._check_n_boot(n_boot)
    _metrics_mod._check_finite(xs, "xs")
    _metrics_mod._check_finite(ys, "ys")
    fp = _call_fp("paired_bootstrap_se", seed, n_boot, len(xs))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, diffs, reps = begun
    randbelow = _metrics_mod._bootstrap_randbelow(rng)
    n = len(xs)
    xs_get = xs.__getitem__
    ys_get = ys.__getitem__

    def _rep(values):
        idx = [randbelow(n) for _ in range(n)]
        values.append(
            sum(map(xs_get, idx)) / n - sum(map(ys_get, idx)) / n
        )

    _chunk_loop(store, rng, diffs, reps, n_boot, _rep)
    mean = sum(diffs) / n_boot
    var = sum((d - mean) ** 2 for d in diffs) / (n_boot - 1)
    out = math.sqrt(var)
    store.finish(out, "float")
    return out


def _ck_paired_bootstrap_weighted_ci(store, w_xs, xs, w_ys, ys,
                                     n_boot=10000, seed=0):
    _metrics_mod._check_paired(w_xs, xs, "w_xs", "xs")
    _metrics_mod._check_paired(w_ys, ys, "w_ys", "ys")
    _metrics_mod._check_paired(xs, ys, "xs", "ys")
    _metrics_mod._check_finite(xs, "xs")
    _metrics_mod._check_finite(ys, "ys")
    _metrics_mod._check_weights(w_xs, "w_xs")
    _metrics_mod._check_weights(w_ys, "w_ys")
    _metrics_mod._check_n_boot(n_boot)
    fp = _call_fp("paired_bootstrap_weighted_ci", seed, n_boot,
                  len(xs))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, diffs, reps = begun
    randbelow = _metrics_mod._bootstrap_randbelow(rng)
    n = len(xs)

    def _rep(values):
        # Discard degenerate resamples (zero total weight) and
        # redraw, verbatim from the original, redraws included:
        # the RNG state is checkpointed, never a draw count, so the
        # variable stream consumption is reproduced exactly.
        for _ in range(_metrics_mod._MAX_DEGENERATE_REDRAWS):
            idx = [randbelow(n) for _ in range(n)]
            num_x = 0.0
            den_x = 0.0
            num_y = 0.0
            den_y = 0.0
            for i in idx:
                wx = w_xs[i]
                wy = w_ys[i]
                num_x += wx * xs[i]
                den_x += wx
                num_y += wy * ys[i]
                den_y += wy
            if den_x > 0.0 and den_y > 0.0:
                break
        else:
            raise ValueError(
                "weights too sparse for bootstrap resampling: 100 "
                "consecutive resamples drew only zero-weight indices"
            )
        values.append(num_x / den_x - num_y / den_y)

    _chunk_loop(store, rng, diffs, reps, n_boot, _rep)
    diffs = sorted(diffs)
    out = (diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)])
    store.finish(out, "tuple2")
    return out


def _ck_bootstrap_case_ci(store, items, stat, n_boot, seed):
    _metrics_mod._check_n_boot(n_boot)
    if not items:
        raise ValueError("items must be non-empty")
    # Validate inputs ONCE upfront, as the original does.
    for item in items:
        if isinstance(item, _metrics_mod.PerCaseResult):
            _metrics_mod._require_result_strings(item)
    fp = _call_fp("_bootstrap_case_ci", seed, n_boot, len(items),
                  _stat_fp(stat))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, diffs, reps = begun
    _metrics_mod._bootstrap_ctx.active = True
    try:
        randbelow = _metrics_mod._bootstrap_randbelow(rng)
        n = len(items)

        def _rep(values):
            values.append(
                stat([items[randbelow(n)] for _ in range(n)]))

        _chunk_loop(store, rng, diffs, reps, n_boot, _rep)
    finally:
        _metrics_mod._bootstrap_ctx.active = False
    diffs = sorted(diffs)
    out = (diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)])
    store.finish(out, "tuple2")
    return out


# ------------------------------------------------------------ eb primitives

def _ck_slope_ci(store, xs, ys, n_boot, seed):
    fp = _call_fp("_slope_ci", seed, n_boot, len(xs))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, slopes, reps = begun
    n = len(xs)
    randrange = rng.randrange

    def _rep(values):
        idx = [randrange(n) for _ in range(n)]
        try:
            values.append(
                _eb_mod._ols_slope(
                    [xs[i] for i in idx],
                    [float(ys[i]) for i in idx])
            )
        except ValueError:
            pass  # original: continue (skip this resample)

    _chunk_loop(store, rng, slopes, reps, n_boot, _rep)
    if len(slopes) < 10:
        store.finish(None, "tuple2_or_none")
        return None
    slopes = sorted(slopes)
    out = (_eb_mod._percentile(slopes, 0.025),
           _eb_mod._percentile(slopes, 0.975))
    store.finish(out, "tuple2_or_none")
    return out


def _ck_adjusted_slope_ci(store, xs_len, xs_delta, ys, n_boot, seed):
    fp = _call_fp("_adjusted_slope_ci", seed, n_boot, len(xs_len))
    begun = store.begin(fp, seed)
    if begun[0] == "cached":
        return begun[1]
    _, rng, slopes, reps = begun
    n = len(xs_len)
    randrange = rng.randrange

    def _rep(values):
        idx = [randrange(n) for _ in range(n)]
        try:
            b1, _ = _eb_mod._ols_2var(
                [xs_len[i] for i in idx],
                [xs_delta[i] for i in idx],
                [float(ys[i]) for i in idx],
            )
            values.append(b1)
        except ValueError:
            pass  # original: continue (skip this resample)

    _chunk_loop(store, rng, slopes, reps, n_boot, _rep)
    if len(slopes) < 10:
        store.finish(None, "tuple2_or_none")
        return None
    slopes = sorted(slopes)
    out = (_eb_mod._percentile(slopes, 0.025),
           _eb_mod._percentile(slopes, 0.975))
    store.finish(out, "tuple2_or_none")
    return out


def _ck_length_confound_diagnostics(store, results, n_boot=2000,
                                    seed=0, alpha=0.05):
    """Verbatim copy of eb_analysis.length_confound_diagnostics with

    the coupled bootstrap loop checkpointed. The original serves a
    sequence of per-(family, predictor) loops from ONE RNG stream
    and derives joint p-values, so the checkpoint state is (current
    test index, reps within it, its slopes so far, p-values so
    far, RNG state): the stream is never reset. The tail assembly
    calls the (patched) slope primitives, which checkpoint
    independently.
    """
    _eb_mod._check_results(results)
    _eb_mod._check_n_boot(n_boot)
    _eb_mod._check_seed(seed)
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not 0 < alpha < 1
    ):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    pairs = _eb_mod.length_pairs(results)
    by_family: dict = {}
    for fam, flipped, a_len, delta in pairs:
        d = by_family.setdefault(
            fam, {"len": ([], []), "delta": ([], []),
                  "joint": ([], [], [])})
        d["len"][0].append(a_len)
        d["len"][1].append(flipped)
        if delta is not None:
            d["delta"][0].append(delta)
            d["delta"][1].append(flipped)
            # Joint sample for the bivariate fit: attacked length,
            # verbosity delta, and flip indicator, same cases.
            d["joint"][0].append(a_len)
            d["joint"][1].append(delta)
            d["joint"][2].append(flipped)

    # Collect raw p-values via the bootstrap CI (see the original).
    tests: list = []
    for fam in sorted(by_family):
        for pred in ("len", "delta"):
            xs, ys = by_family[fam][pred]
            if len(xs) >= _eb_mod.MIN_OBSERVATIONS:
                try:
                    _eb_mod._ols_slope(xs, [float(y) for y in ys])
                except ValueError:
                    continue
                tests.append((fam, pred, xs, ys))

    fp = _call_fp("length_confound_diagnostics", seed, n_boot,
                  len(tests))
    raw = store.begin_raw(fp)
    if raw is not None and raw.get("loop_done"):
        p_values = list(raw["p_values"])
    else:
        if raw is None:
            ti, reps, cur, p_values = 0, 0, [], []
            rng = random.Random(seed)
        else:
            ti = int(raw["ti"])
            reps = int(raw["reps"])
            cur = list(raw["cur"])
            p_values = list(raw["p_values"])
            rng = _rng_from_json(raw["rng"], seed)
        randrange = rng.randrange
        while ti < len(tests):
            deadline = time.monotonic() + _CHUNK_SECONDS
            while ti < len(tests):
                fam, pred, xs, ys = tests[ti]
                n = len(xs)
                while reps < n_boot:
                    idx = [randrange(n) for _ in range(n)]
                    try:
                        cur.append(_eb_mod._ols_slope(
                            [xs[i] for i in idx],
                            [float(ys[i]) for i in idx]))
                    except ValueError:
                        pass  # original: continue
                    reps += 1
                    if reps % 16 == 0 and \
                            time.monotonic() >= deadline:
                        break
                if reps < n_boot:
                    break  # chunk deadline: save below, keep looping
                if len(cur) < 10:
                    p_values.append(1.0)
                else:
                    p_le = sum(1 for s in cur if s <= 0) / len(cur)
                    p_ge = sum(1 for s in cur if s >= 0) / len(cur)
                    p_values.append(
                        min(1.0, 2.0 * min(p_le, p_ge)))
                ti += 1
                reps = 0
                cur = []
            store.save_raw({
                "ti": ti, "reps": reps, "cur": cur,
                "p_values": p_values,
                "rng": _rng_state_to_json(rng),
            })
        store.save_raw({"loop_done": True, "p_values": p_values})

    adj = _eb_mod.holm_adjust(p_values, alpha=alpha) if p_values \
        else []
    sig_map = {
        (fam, pred): (a < alpha)
        for (fam, pred, _, _), a in zip(tests, adj)
    }

    families: dict = {}
    for fam in sorted(by_family):
        preds: dict = {}
        for pred in ("len", "delta"):
            xs, ys = by_family[fam][pred]
            sl = _eb_mod._length_slice(xs, ys, n_boot, seed + 1)
            d = _eb_mod._length_slice_dict(sl)
            key = (fam, pred)
            d["holm_significant"] = (
                sig_map.get(key))
            preds["attacked_length" if pred == "len"
                  else "verbosity_delta"] = d
        cov = any(
            p.get("holm_significant") is True
            for p in preds.values()
        )
        families[fam] = {
            "predictors": preds,
            "covariate_recommended": cov,
            # EB-7: the de-confounded quantity (see the original).
            "adjusted": _eb_mod._adjusted_length_dict(
                _eb_mod._adjusted_length_slice(
                    by_family[fam]["joint"][0],
                    by_family[fam]["joint"][1],
                    by_family[fam]["joint"][2],
                    n_boot, seed + 2)),
        }
    return {
        "alpha": alpha,
        "n_tests": len(tests),
        "n_cases_with_length": len(pairs),
        "by_family": families,
    }


# ------------------------------------------------------------ install / remove

_SEAL_ORIGINALS: dict | None = None


def install_seal_checkpoints(store: SealCheckpointStore) -> None:
    """Replace the bootstrap primitives with checkpointed wrappers.

    The replacement is process-global (module globals in
    :mod:`peira.metrics` and :mod:`peira.eb_analysis`) and must be
    paired with :func:`uninstall_seal_checkpoints`; prefer the
    :func:`seal_checkpoints` context manager. Not re-entrant and
    not thread-safe by design: a seal is a single-threaded,
    one-at-a-time computation, and a second install is a bug, so
    it raises instead of stacking wrappers.
    """
    global _SEAL_ORIGINALS
    if _SEAL_ORIGINALS is not None:
        raise RuntimeError("seal checkpoints already installed")
    M = _metrics_mod
    EB = _eb_mod
    _SEAL_ORIGINALS = {
        "paired_bootstrap_ci": M.paired_bootstrap_ci,
        "_unpaired_bootstrap_ci": M._unpaired_bootstrap_ci,
        "paired_bootstrap_se": M.paired_bootstrap_se,
        "paired_bootstrap_weighted_ci":
            M.paired_bootstrap_weighted_ci,
        "_bootstrap_case_ci": M._bootstrap_case_ci,
        "_slope_ci": EB._slope_ci,
        "_adjusted_slope_ci": EB._adjusted_slope_ci,
        "length_confound_diagnostics":
            EB.length_confound_diagnostics,
    }

    def paired_bootstrap_ci(xs, ys, n_boot=10000, seed=0):
        return _ck_paired_bootstrap_ci(store, xs, ys, n_boot, seed)

    def _unpaired_bootstrap_ci(xs, ys, n_boot=10000, seed=0):
        return _ck_unpaired_bootstrap_ci(store, xs, ys, n_boot, seed)

    def paired_bootstrap_se(xs, ys, n_boot=10000, seed=0):
        return _ck_paired_bootstrap_se(store, xs, ys, n_boot, seed)

    def paired_bootstrap_weighted_ci(w_xs, xs, w_ys, ys,
                                     n_boot=10000, seed=0):
        return _ck_paired_bootstrap_weighted_ci(
            store, w_xs, xs, w_ys, ys, n_boot, seed)

    def _bootstrap_case_ci(items, stat, n_boot, seed):
        return _ck_bootstrap_case_ci(store, items, stat, n_boot,
                                     seed)

    def _slope_ci(xs, ys, n_boot, seed):
        return _ck_slope_ci(store, xs, ys, n_boot, seed)

    def _adjusted_slope_ci(xs_len, xs_delta, ys, n_boot, seed):
        return _ck_adjusted_slope_ci(store, xs_len, xs_delta, ys,
                                     n_boot, seed)

    def length_confound_diagnostics(results, n_boot=2000, seed=0,
                                    alpha=0.05):
        return _ck_length_confound_diagnostics(
            store, results, n_boot, seed, alpha)

    M.paired_bootstrap_ci = paired_bootstrap_ci
    M._unpaired_bootstrap_ci = _unpaired_bootstrap_ci
    M.paired_bootstrap_se = paired_bootstrap_se
    M.paired_bootstrap_weighted_ci = paired_bootstrap_weighted_ci
    M._bootstrap_case_ci = _bootstrap_case_ci
    EB._slope_ci = _slope_ci
    EB._adjusted_slope_ci = _adjusted_slope_ci
    EB.length_confound_diagnostics = length_confound_diagnostics


def uninstall_seal_checkpoints() -> None:
    """Restore the original primitives saved by the install."""
    global _SEAL_ORIGINALS
    if _SEAL_ORIGINALS is None:
        return
    M = _metrics_mod
    EB = _eb_mod
    M.paired_bootstrap_ci = _SEAL_ORIGINALS["paired_bootstrap_ci"]
    M._unpaired_bootstrap_ci = \
        _SEAL_ORIGINALS["_unpaired_bootstrap_ci"]
    M.paired_bootstrap_se = _SEAL_ORIGINALS["paired_bootstrap_se"]
    M.paired_bootstrap_weighted_ci = \
        _SEAL_ORIGINALS["paired_bootstrap_weighted_ci"]
    M._bootstrap_case_ci = _SEAL_ORIGINALS["_bootstrap_case_ci"]
    EB._slope_ci = _SEAL_ORIGINALS["_slope_ci"]
    EB._adjusted_slope_ci = _SEAL_ORIGINALS["_adjusted_slope_ci"]
    EB.length_confound_diagnostics = \
        _SEAL_ORIGINALS["length_confound_diagnostics"]
    _SEAL_ORIGINALS = None


@contextlib.contextmanager
def seal_checkpoints(
    store: SealCheckpointStore,
) -> Iterator[SealCheckpointStore]:
    """Install the checkpointed primitives for one summarize call."""
    install_seal_checkpoints(store)
    try:
        yield store
    finally:
        uninstall_seal_checkpoints()


def seal_run_fingerprint(results: list, params: Mapping) -> str:
    """Bind a sidecar to one exact summarize input + code version.

    ``results`` may be PerCaseResult objects or their serialized
    dicts; both normalize to the same canonical form. ``params``
    carries every other summarize input that can move the output
    (families, mappings, n_boot, seed, termination, pricing table).
    The metrics, eb_analysis, and seal_checkpoint source files are
    hashed in as well: a sidecar written by different code is
    ignored wholesale.
    """
    result_dicts = [r if isinstance(r, dict) else dataclasses.asdict(r)
                    for r in results]
    h = hashlib.sha256()
    h.update(json.dumps(
        result_dicts, sort_keys=True,
        separators=(",", ":")).encode())
    h.update(json.dumps(
        dict(params), sort_keys=True, default=repr).encode())
    for module in (_metrics_mod, _eb_mod):
        h.update(Path(module.__file__).read_bytes())
    # This module computes the cached results itself (the wrapper
    # loop bodies, reductions, and result decoding live here), so
    # its source is hashed in as well: a wrapper-only code change
    # must not replay results the old code produced.
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()
