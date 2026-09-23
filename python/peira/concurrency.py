"""Concurrency, retry, caching, and transcripts for the runner.

The runner dispatches adapter calls concurrently (``asyncio`` +
``asyncio.to_thread``, since ``decide()`` is a blocking call) and adapts
itself to the provider instead of assuming a fixed rate:

- :class:`AdaptiveConcurrency` — a reactive AIMD controller. Slow start
  (doubling) until the first congestion signal, then additive increase
  (+5%) gated on saturation (the limit only grows when the workload is
  actually using it — peak in-flight at least 80% of the limit) with
  multiplicative decrease (x0.8) on 429/503 and a 15s debounce between
  cuts, and a floor of 1. Proactive rate limiting (client-side token
  buckets, pre-computed delays) is deliberately not used: the
  provider's own 429s are the congestion signal, and reacting to them
  keeps the runner correct against any provider without per-provider
  tuning.
- Retry is transient-only: 408/409/429/5xx and timeouts are retried with
  full-jitter exponential backoff; 400/401/403/404/422 are permanent
  and never retried. A bounded ``Retry-After`` is honored (capped at
  60s). The jitter RNG is seeded from the run seed, so retry timing is
  reproducible.
- :class:`ResponseCache` — an opt-in, content-hash response cache for
  deterministic adapters (temperature 0 + fixed seed). Off by default;
  never on the measurement path unless the user passes ``--cache-dir``.
- Transcripts — every request/response pair, written as JSONL, enough
  to re-score a run without calling the provider again
  (``peira replay``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from peira.adapters.base import ProviderError
from peira.dataset import atomic_write_text

# Statuses the runner retries: rate limiting, conflicts that resolve on
# retry, and server-side failures. Timeouts (no status at all) retry
# too. Everything else — including unknown statuses — does not: a
# retry the provider didn't ask for is a measurement artifact.
TRANSIENT_STATUSES = frozenset({408, 409, 429}) | frozenset(range(500, 600))
# Permanent client errors: retrying cannot help and may burn quota.
PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 422})
# Congestion signals: these feed the AIMD controller's multiplicative
# decrease (not just a retry — the send rate itself must drop).
CONGESTION_STATUSES = frozenset({429, 503})

# A provider-asked delay is honored, but bounded: an unbounded sleep on
# a hostile Retry-After would hang the run.
MAX_RETRY_AFTER_S = 60.0


def classify_exception(exc: BaseException) -> tuple[bool, bool, float | None]:
    """Classify an adapter-call failure.

    Returns ``(retryable, congestion_cut, retry_after)``:

    - ``retryable``: True only for transient failures (408/409/429/5xx,
      timeouts, connection resets, or a provider-asked ``retry_after``).
      Permanent client errors (400/401/403/404/422) and unknown statuses
      are never retried; anything else (validation bugs, adapter code
      errors) becomes a malformed record, not a retry.
    - ``congestion_cut``: True when the failure is a congestion signal
      (429/503, or any failure carrying a ``retry_after``) — the AIMD
      controller should multiplicatively decrease, not just retry.
    - ``retry_after``: the provider's requested delay in seconds, or
      None. Callers must cap it at ``MAX_RETRY_AFTER_S``.
    """
    retry_after = getattr(exc, "retry_after", None)
    if (
        isinstance(retry_after, bool)
        or not isinstance(retry_after, (int, float))
        or not retry_after >= 0
    ):
        retry_after = None
    status = getattr(exc, "status_code", None)
    if isinstance(status, bool):
        status = None
    if isinstance(status, int):
        if status in PERMANENT_STATUSES:
            return (False, False, None)
        if status in TRANSIENT_STATUSES:
            cut = status in CONGESTION_STATUSES or retry_after is not None
            return (True, cut, retry_after)
        # Unknown status: do not retry blind.
        return (False, False, None)
    if retry_after is not None:
        # No status, but the provider asked for a delay: honor it.
        return (True, True, retry_after)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return (True, False, None)
    if isinstance(exc, ConnectionError):
        # Includes ConnectionResetError / BrokenPipeError: the network
        # dropped, not the model — retrying is safe.
        return (True, False, None)
    return (False, False, None)


def classify_provider_error(
    status_code: int | None, retry_after: float | None = None
) -> tuple[bool, bool, float | None]:
    """Classify from parts (for adapters/tests that don't raise)."""
    return classify_exception(
        ProviderError("", status_code=status_code, retry_after=retry_after)
    )


def retry_jitter_seed(
    seed: int | None, dispatch_index: int, attempt: int
) -> str:
    """Deterministic jitter-RNG seed for one retry.

    Derived from the run seed, the call's dispatch index, and the
    attempt number, so retry timing is reproducible for a given run
    seed and independent of completion order. ``random.Random`` does
    not accept tuples, so the components are joined into a string.
    """
    return f"{seed}:{dispatch_index}:{attempt}"


def backoff_delay(
    attempt: int,
    rng: random.Random,
    base_s: float = 1.0,
    cap_s: float = 60.0,
) -> float:
    """Full-jitter exponential backoff for retry ``attempt`` (0-based).

    ``uniform(0, min(cap, base * 2**attempt))`` — equal expected wait to
    plain exponential backoff, but decorrelated across concurrent calls
    so a fleet of retries doesn't re-hit the provider in lockstep.
    ``rng`` is the run-seeded generator, so retry timing is
    reproducible for a given seed.
    """
    return rng.uniform(0.0, min(cap_s, base_s * (2.0**attempt)))


class AdaptiveConcurrency:
    """Reactive AIMD concurrency controller (one per adapter).

    Slow start: the limit doubles on every success until the first
    congestion signal. Then congestion avoidance: +5% per success gated
    on saturation (the limit only grows when the peak in-flight count
    reached at least 80% of the current limit, so an idle workload
    never inflates the limit), x0.8 multiplicative decrease on a
    congestion cut (429/503), at most one cut per 15s (debounce), and a
    floor of 1. There is deliberately no permanent post-cut ceiling: a
    cut backs the limit off, and the controller recovers through the
    same saturated additive growth once congestion clears. A ceiling
    that never recovers would ratchet a long run down to 1 after a few
    transient 429 bursts.

    The limiter is dynamic (the limit changes as signals arrive), so it
    is implemented as a condition-variable gate that re-checks the live
    limit rather than a fixed-size ``asyncio.Semaphore``: a semaphore
    cannot change capacity mid-run. The contract is the same — at most
    ``limit`` calls in flight — and is pinned by tests.

    The limit only ever *bounds* in-flight calls — it never changes
    what is computed, so concurrency is a performance parameter, not a
    measurement input: two runs with different limits score identical
    records (only timing differs).
    """

    def __init__(
        self,
        max_limit: int,
        *,
        initial: int = 1,
        debounce_s: float = 15.0,
        time_fn: Any = time.monotonic,
    ) -> None:
        if max_limit < 1:
            raise ValueError(f"max_limit must be >= 1, got {max_limit}")
        self._max = max_limit
        self._limit = float(min(max(initial, 1), max_limit))
        self._slow_start = True
        self._debounce_s = debounce_s
        self._time_fn = time_fn
        self._last_cut: float | None = None
        self._in_flight = 0
        self._peak_in_flight = 0
        self._cond = asyncio.Condition()

    @property
    def limit(self) -> int:
        """Current effective concurrency (always >= 1)."""
        return max(1, int(self._limit))

    @property
    def in_slow_start(self) -> bool:
        return self._slow_start

    def on_success(self) -> None:
        """A call completed without a congestion signal: probe upward."""
        if self._slow_start:
            self._limit = min(float(self._max), self._limit * 2.0)
        elif self._peak_in_flight >= 0.8 * self._limit:
            # Saturated: the workload actually wants the headroom.
            self._limit = min(float(self._max), self._limit * 1.05)
        # Decay the peak toward current demand so a quiet workload does
        # not keep the gate open on stale history.
        self._peak_in_flight = self._in_flight

    def on_congestion(self) -> bool:
        """A 429/503 arrived: cut multiplicatively (debounced).

        Returns True when the cut was applied, False when it was
        debounced (a cut happened less than ``debounce_s`` ago — the
        controller is already backing off, don't pile on).
        """
        now = self._time_fn()
        if self._last_cut is not None and now - self._last_cut < self._debounce_s:
            return False
        self._last_cut = now
        self._slow_start = False
        self._limit = float(max(1, math.floor(self._limit * 0.8)))
        return True

    @asynccontextmanager
    async def slot(self):
        """Async context manager bounding in-flight calls to the limit."""
        async with self._cond:
            await self._cond.wait_for(lambda: self._in_flight < self.limit)
            self._in_flight += 1
            self._peak_in_flight = max(self._peak_in_flight,
                                       self._in_flight)
        try:
            yield
        finally:
            async with self._cond:
                self._in_flight -= 1
                # A release always follows a limit change (on_success /
                # on_congestion are called by the task holding the
                # slot), so waiters re-evaluate the predicate here.
                self._cond.notify_all()


def cache_key(
    *,
    adapter_name: str,
    adapter_version: str,
    cache_namespace: str,
    primitive: str,
    variant: str,
    case_id: str,
    case_input: dict[str, Any],
    manifest_sha256: str,
) -> str:
    """Content-hash key for one adapter call.

    Covers the adapter identity + its declared sampling namespace, the
    primitive, the variant arm (``"benign"``/``"attacked"``), the case
    id, the exact input bytes, and the dataset snapshot: any change to
    what is computed changes the key. The arm is key material on its own
    because the input dicts are the case's verbatim inputs — a case
    whose benign and attacked inputs are identical would otherwise
    collide across arms. The case id is key material because an
    adapter's output may legitimately depend on trial bookkeeping it
    receives (the mock's seeded flip is per case id); two cases with
    byte-identical inputs still get separate entries. The key does NOT
    cover the peira version — a runner upgrade must not silently reuse
    entries recorded under different runner semantics; operators
    clearing the cache on upgrade is the documented practice.
    """
    payload = json.dumps(
        {
            "adapter_name": adapter_name,
            "adapter_version": adapter_version,
            "cache_namespace": cache_namespace,
            "primitive": primitive,
            "variant": variant,
            "case_id": case_id,
            "input": case_input,
            "manifest_sha256": manifest_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    """Opt-in on-disk response cache for deterministic adapters.

    One JSON file per key under ``cache_dir`` (atomic writes, so a
    killed run never leaves a half-written entry). Entries store the
    validated output fields; on a hit the runner reconstructs the
    output object and re-validates it exactly like a live call — a
    corrupt entry is treated as a miss, never trusted.

    The cache is OFF unless the user passes ``--cache-dir``. It is only
    valid for deterministic adapters (temperature 0 + fixed seed),
    declared via the adapter's ``cache_namespace`` — an obligation the
    runner cannot verify. Cache use is sealed into the artifact config
    (hits/misses), so a cached run is auditable as cached.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(
                f"cannot use cache directory {cache_dir}: {e.strerror or e}"
            ) from e
        # A probe file proves writability now, not mid-run.
        probe = cache_dir / ".peira-cache-probe"
        try:
            atomic_write_text(probe, "ok")
            probe.unlink()
        except OSError as e:
            raise ValueError(
                f"cache directory {cache_dir} is not writable: "
                f"{e.strerror or e}"
            ) from e
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the stored ``{"primitive": ..., "output": {...}}`` or None."""
        path = self._path(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            self.misses += 1
            return None
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            # Corrupt entry: treat as a miss; it gets overwritten on
            # the next store.
            self.misses += 1
            return None
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("primitive"), str)
            or not isinstance(entry.get("output"), dict)
        ):
            self.misses += 1
            return None
        self.hits += 1
        return entry

    def put(self, key: str, primitive: str, output: dict[str, Any]) -> None:
        # Best-effort: the cache is a pure optimization, so a failed
        # store must never fail the measurement run it accelerates. A
        # missing entry is just a future miss.
        try:
            atomic_write_text(
                self._path(key),
                json.dumps(
                    {"primitive": primitive, "output": output}, sort_keys=True
                ),
            )
        except OSError:
            pass


# -- Transcripts -----------------------------------------------------------
#
# One JSONL line per variant call: the request the runner sent, the
# response it got (or the terminal error), and the provider identity.
# Enough to re-score the run without calling the provider again
# (`peira replay` reconstructs the call records from these entries).
# Only the *final* outcome per variant is recorded — retry
# intermediaries are transport, not measurement — with the attempt
# count kept for provenance.

TRANSCRIPT_REQUIRED = (
    "dispatch_index",
    "case_id",
    "variant",
    "primitive",
    "request",
    "response",
    "provider",
    "seed",
    "dispatch_limit",
    "max_concurrency",
)


def validate_transcript_entry(entry: Any, lineno: int) -> dict[str, Any]:
    """Strictly validate one transcript JSONL entry (replay input)."""
    where = f"transcript line {lineno}"
    if not isinstance(entry, dict):
        raise ValueError(f"{where}: expected an object")
    for key in TRANSCRIPT_REQUIRED:
        if key not in entry:
            raise ValueError(f"{where}: missing field {key!r}")
    if entry["variant"] not in ("benign", "attacked"):
        raise ValueError(
            f"{where}: variant must be 'benign' or 'attacked', "
            f"got {entry['variant']!r}"
        )
    for key in ("dispatch_index", "seed", "dispatch_limit",
                "max_concurrency"):
        value = entry[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{where}: {key} must be an integer, "
                f"got {type(value).__name__}"
            )
    response = entry["response"]
    if not isinstance(response, dict) or response.get("kind") not in (
        "output",
        "error",
    ):
        raise ValueError(f"{where}: response.kind must be 'output' or 'error'")
    if response["kind"] == "output" and not isinstance(
        response.get("output"), dict
    ):
        raise ValueError(f"{where}: response.output must be an object")
    provider = entry["provider"]
    if not isinstance(provider, dict) or not provider.get("adapter_name"):
        raise ValueError(f"{where}: provider.adapter_name is required")
    return entry


def load_transcript(path: Path) -> list[dict[str, Any]]:
    """Read and strictly validate a transcript JSONL file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(
            f"cannot read transcript {path}: {e.strerror or e}"
        ) from e
    entries: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"transcript line {lineno}: invalid JSON: {e}"
            ) from e
        entries.append(validate_transcript_entry(entry, lineno))
    if not entries:
        raise ValueError(f"transcript {path} has no entries")
    return entries


def transcript_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
