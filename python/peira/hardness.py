"""Hardness stratification and cross-adapter transfer ASR (M-4 diagnostics).

Aggregate ASR hides whether a family has a hard core: 20% ASR could mean
"every case flips 20% of the time" or "20% of cases always flip." The
second is far more dangerous. If a case that flips adapter X also flips
adapter Y, it is a general decision-layer weakness, not an implementation
quirk.

This module is pure aggregation over sealed per-case results. It is
diagnostic, not a headline metric: nothing here ranks adapters or enters
a leaderboard. The three views are:

1. **Flip distribution**: for N adapters, the fraction of cases flipped by
   exactly k adapters (k = 0..N). A U-shape (mass at 0 and N) means the
   family has a hard core; a bell shape means flips are scattered.
2. **Hardest-decile survival**: rank cases by flip count, take the hardest
   10%, and report what fraction of those each adapter survives (does not
   flip). An adapter that survives the hard core is robust where it
   matters.
3. **Transfer ASR matrix**: for each ordered pair (X, Y), the fraction of
   cases that flipped X which also flip Y. High off-diagonal transfer
   means the weakness is in the decision layer, not the adapter. Reported
   overall and per family.

Conventions (matching the headline ASR semantics):

- A "flip" counts only when the case was *eligible* for that adapter
  (usable benign baseline) and the attack changed the effective outcome.
- The flip-distribution and hardest-decile views use the common eligible
  universe: cases eligible for *all* N adapters, so flip counts are
  comparable across adapters.
- The transfer matrix uses pairwise eligibility: transfer X->Y is defined
  over cases eligible for both X and Y that X flipped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from peira._rust import _impl as _rust
from peira.concurrency import _require_json_str
from peira.metrics import PerCaseResult, _require_result_strings


def _flipped(r: PerCaseResult) -> bool:
    """Whether this result counts as a flip: eligible baseline, outcome changed."""
    return bool(r.eligible and r.flipped)


@dataclass(frozen=True)
class FlipDistribution:
    """Per-example flip-count histogram across N adapters.

    ``counts[k]`` is the number of cases (in the common eligible universe)
    flipped by exactly k of the N adapters. ``fractions[k]`` is the share.
    """

    adapters: tuple[str, ...]
    n_cases: int
    counts: tuple[int, ...]

    @property
    def n_adapters(self) -> int:
        return len(self.adapters)

    @property
    def fractions(self) -> tuple[float, ...]:
        if self.n_cases == 0:
            return tuple(0.0 for _ in self.counts)
        return tuple(c / self.n_cases for c in self.counts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": list(self.adapters),
            "n_cases": self.n_cases,
            "counts": list(self.counts),
            "fractions": list(self.fractions),
        }


@dataclass(frozen=True)
class HardestDecileSurvival:
    """Per-adapter survival rate on the hardest decile of cases.

    Cases are ranked by flip count (descending, ties broken by case_id for
    determinism); the hardest decile is the top ceil(10%) of the common
    eligible universe. ``survived[adapter]`` is the number of decile cases
    the adapter did *not* flip; ``rates[adapter]`` is the share.
    """

    adapters: tuple[str, ...]
    n_cases: int
    decile_size: int
    decile_case_ids: tuple[str, ...]
    survived: dict[str, int]

    @property
    def rates(self) -> dict[str, float | None]:
        if self.decile_size == 0:
            return {a: None for a in self.adapters}
        return {a: self.survived[a] / self.decile_size for a in self.adapters}

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": list(self.adapters),
            "n_cases": self.n_cases,
            "decile_size": self.decile_size,
            "decile_case_ids": list(self.decile_case_ids),
            "survived": dict(self.survived),
            "rates": {k: v for k, v in self.rates.items()},
        }


@dataclass(frozen=True)
class TransferMatrix:
    """Cross-adapter transfer ASR.

    ``rates[(src, dst)]`` is the fraction of cases that flipped ``src``
    (and were eligible for both) which also flipped ``dst``. ``None``
    when ``src`` flipped nothing eligible (no denominator). The diagonal
    is always 1.0 by construction (a case that flipped X trivially
    "transfers" to X).
    """

    adapters: tuple[str, ...]
    family: str | None  # None = all families pooled
    n_cases: int  # union of pairwise-eligible case ids across all ordered pairs
    flipped_by_source: dict[str, int]  # per source: flips over cases eligible
    # for src and at least one other adapter
    rates: dict[tuple[str, str], float | None] = field(default_factory=dict)

    @property
    def mean_off_diagonal(self) -> float | None:
        """Mean transfer rate over all ordered pairs with src != dst."""
        vals = [
            v
            for (s, d), v in self.rates.items()
            if s != d and v is not None
        ]
        if not vals:
            return None
        return sum(vals) / len(vals)

    def rate(self, src: str, dst: str) -> float | None:
        return self.rates.get((src, dst))

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": list(self.adapters),
            "family": self.family,
            "n_cases": self.n_cases,
            "flipped_by_source": dict(self.flipped_by_source),
            "rates": {
                f"{s} -> {d}": v for (s, d), v in self.rates.items()
            },
            "mean_off_diagonal": self.mean_off_diagonal,
        }


@dataclass
class HardnessReport:
    """The complete M-4 diagnostic report over N adapter runs."""

    adapters: tuple[str, ...]
    n_cases: int  # common eligible universe size
    flip_distribution: FlipDistribution
    hardest_decile: HardestDecileSurvival
    transfer_overall: TransferMatrix
    transfer_by_family: dict[str, TransferMatrix]

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": list(self.adapters),
            "n_cases": self.n_cases,
            "flip_distribution": self.flip_distribution.to_dict(),
            "hardest_decile": self.hardest_decile.to_dict(),
            "transfer_overall": self.transfer_overall.to_dict(),
            "transfer_by_family": {
                fam: m.to_dict() for fam, m in self.transfer_by_family.items()
            },
        }


def _common_universe(
    results_by_adapter: dict[str, list[PerCaseResult]],
) -> dict[str, dict[str, PerCaseResult]]:
    """Cases eligible for every adapter, keyed case_id -> adapter -> result.

    Adapters with no results contribute nothing; a case must appear and be
    eligible in every adapter's list to enter the universe.
    """
    adapters = sorted(results_by_adapter)
    per_adapter: dict[str, dict[str, PerCaseResult]] = {}
    for a in adapters:
        d: dict[str, PerCaseResult] = {}
        for r in results_by_adapter[a]:
            # Last record wins on duplicate case_id; the runner seals one
            # record per case, so duplicates indicate hostile input and
            # the deterministic choice keeps aggregation total.
            if r.eligible:
                d[r.case_id] = r
        per_adapter[a] = d
    if not adapters:
        return {}
    common_ids = set(per_adapter[adapters[0]])
    for a in adapters[1:]:
        common_ids &= set(per_adapter[a])
    return {
        cid: {a: per_adapter[a][cid] for a in adapters}
        for cid in sorted(common_ids)
    }


def _flip_distribution_py(
    results_by_adapter: dict[str, list[PerCaseResult]],
) -> FlipDistribution:
    """Reference implementation of :func:`flip_distribution` (pure Python)."""
    adapters = tuple(sorted(results_by_adapter))
    universe = _common_universe(results_by_adapter)
    n = len(adapters)
    counts = [0] * (n + 1)
    for cid, by_adapter in universe.items():
        k = sum(1 for a in adapters if _flipped(by_adapter[a]))
        counts[k] += 1
    return FlipDistribution(
        adapters=adapters, n_cases=len(universe), counts=tuple(counts)
    )


def _hardest_decile_survival_py(
    results_by_adapter: dict[str, list[PerCaseResult]],
    decile: float = 0.10,
) -> HardestDecileSurvival:
    """Per-adapter survival on the hardest decile of cases.

    Hardness is the flip count across adapters. The decile is the top
    ``ceil(decile * n)`` cases by (flip count desc, case_id asc).
    """
    if not 0 < decile <= 1:
        raise ValueError(f"decile must be in (0, 1], got {decile!r}")
    adapters = tuple(sorted(results_by_adapter))
    universe = _common_universe(results_by_adapter)
    ranked = sorted(
        universe.items(),
        key=lambda kv: (
            -sum(1 for a in adapters if _flipped(kv[1][a])),
            kv[0],
        ),
    )
    decile_size = math.ceil(len(ranked) * decile) if ranked else 0
    decile_ids = tuple(cid for cid, _ in ranked[:decile_size])
    survived = {a: 0 for a in adapters}
    for cid in decile_ids:
        by_adapter = universe[cid]
        for a in adapters:
            if not _flipped(by_adapter[a]):
                survived[a] += 1
    return HardestDecileSurvival(
        adapters=adapters,
        n_cases=len(universe),
        decile_size=decile_size,
        decile_case_ids=decile_ids,
        survived=survived,
    )


def _transfer_matrix_py(
    results_by_adapter: dict[str, list[PerCaseResult]],
    family: str | None = None,
) -> TransferMatrix:
    """Cross-adapter transfer ASR, optionally restricted to one family.

    transfer(src -> dst) = P(dst flips | src flipped), over cases eligible
    for both src and dst (and in ``family`` when given).
    """
    adapters = tuple(sorted(results_by_adapter))
    # Per-adapter eligible maps, optionally family-filtered.
    eligible: dict[str, dict[str, PerCaseResult]] = {}
    for a in adapters:
        d: dict[str, PerCaseResult] = {}
        for r in results_by_adapter[a]:
            if r.eligible and (family is None or r.family == family):
                d[r.case_id] = r
        eligible[a] = d
    rates: dict[tuple[str, str], float | None] = {}
    for src in adapters:
        for dst in adapters:
            if src == dst:
                rates[(src, dst)] = 1.0
                continue
            # Cases eligible for both, flipped by src.
            denom_ids = [
                cid
                for cid, r in eligible[src].items()
                if cid in eligible[dst] and _flipped(r)
            ]
            if not denom_ids:
                rates[(src, dst)] = None
                continue
            num = sum(1 for cid in denom_ids if _flipped(eligible[dst][cid]))
            rates[(src, dst)] = num / len(denom_ids)
    # Per-source denominators for the table header: cases eligible for
    # src and at least one other adapter, flipped by src.
    flipped_by_source: dict[str, int] = {}
    for src in adapters:
        union_ids: set[str] = set()
        for dst in adapters:
            if dst == src:
                continue
            union_ids |= set(eligible[src]) & set(eligible[dst])
        flipped_by_source[src] = sum(
            1 for cid in union_ids if _flipped(eligible[src][cid])
        )
    # Pooled case count: union of all pairwise-eligible case ids.
    seen: set[str] = set()
    for src in adapters:
        for dst in adapters:
            if src != dst:
                seen |= set(eligible[src]) & set(eligible[dst])
    return TransferMatrix(
        adapters=adapters,
        family=family,
        n_cases=len(seen),
        flipped_by_source=flipped_by_source,
        rates=rates,
    )


def _analyze_runs_py(
    results_by_adapter: dict[str, list[PerCaseResult]],
    decile: float = 0.10,
) -> HardnessReport:
    """Reference implementation of :func:`analyze_runs` (pure Python)."""
    adapters = tuple(sorted(results_by_adapter))
    universe = _common_universe(results_by_adapter)
    dist = _flip_distribution_py(results_by_adapter)
    hd = _hardest_decile_survival_py(results_by_adapter, decile=decile)
    overall = _transfer_matrix_py(results_by_adapter)
    families = sorted(
        {r.family for rs in results_by_adapter.values() for r in rs}
    )
    by_family = {
        fam: _transfer_matrix_py(results_by_adapter, family=fam)
        for fam in families
    }
    return HardnessReport(
        adapters=adapters,
        n_cases=len(universe),
        flip_distribution=dist,
        hardest_decile=hd,
        transfer_overall=overall,
        transfer_by_family=by_family,
    )


# ---------------------------------------------------------------------------
# Text rendering (diagnostic tables for stdout / --out).
# ---------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _report_text_py(report: HardnessReport) -> str:
    """Reference implementation of :func:`report_text` (pure Python).

    Labeled diagnostic throughout: these tables describe the shape of
    hardness and transfer; they do not rank adapters.
    """
    L: list[str] = []
    A = report.adapters
    L.append("Peira hardness and transfer diagnostics (M-4)")
    L.append("==============================================")
    L.append(
        "Diagnostic only: these tables describe hardness shape, not "
        "adapter quality. They never rank."
    )
    L.append(f"Adapters: {', '.join(A) if A else '(none)'}")
    L.append(f"Common eligible cases: {report.n_cases}")
    L.append("")

    # 1. Flip distribution.
    L.append("Flip distribution (cases flipped by exactly k adapters):")
    d = report.flip_distribution
    L.append(f"  {'k':>3} {'cases':>7} {'share':>7}")
    for k, (c, f) in enumerate(zip(d.counts, d.fractions)):
        L.append(f"  {k:>3} {c:>7} {_pct(f):>7}")
    if d.n_cases:
        # Hard-core indicator: mass at k = N vs uniform expectation.
        hard_core = d.fractions[-1] if d.counts else 0.0
        L.append(
            f"  hard core (flipped by all {d.n_adapters}): {_pct(hard_core)}"
        )
    L.append("")

    # 2. Hardest-decile survival.
    hd = report.hardest_decile
    L.append(
        f"Hardest-decile survival "
        f"(hardest {hd.decile_size} of {hd.n_cases} cases):"
    )
    L.append(f"  {'adapter':<24} {'survived':>8} {'rate':>7}")
    for a in A:
        L.append(
            f"  {a:<24} {hd.survived[a]:>8} {_pct(hd.rates[a]):>7}"
        )
    L.append("")

    # 3. Transfer matrix (overall).
    t = report.transfer_overall
    L.append("Transfer ASR matrix (row flipped -> column also flips):")
    L.append(
        "  (src flips: cases flipped by the row adapter; each cell's rate"
        " divides by the subset of those also eligible for the column adapter)"
    )
    header = "  " + "".join(f"{a[:12]:>13}" for a in A)
    L.append(header)
    for src in A:
        row = f"  {src[:12]:<12}"
        for dst in A:
            row += f"{_pct(t.rate(src, dst)):>13}"
        row += f"   (src flips: {t.flipped_by_source[src]})"
        L.append(row)
    L.append(f"  mean off-diagonal transfer: {_pct(t.mean_off_diagonal)}")
    L.append("")

    # 4. Per-family transfer summaries.
    if report.transfer_by_family:
        L.append("Per-family transfer (mean off-diagonal):")
        L.append(f"  {'family':<28} {'mean xfer':>9} {'cases':>7}")
        for fam, m in report.transfer_by_family.items():
            L.append(
                f"  {fam[:28]:<28} {_pct(m.mean_off_diagonal):>9} "
                f"{m.n_cases:>7}"
            )
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Rust dispatch (D-11).
# ---------------------------------------------------------------------------


def _check_results(results_by_adapter: dict) -> None:
    """D-11 validation shared by the dispatched entry points.

    Rejects lone surrogates in every string the Rust bindings read
    (adapter names and result fields), so both backends raise the same
    ``ValueError``. Duck-typed records missing the full PerCaseResult
    surface are left alone: the PyO3 extraction then fails with
    TypeError and the wrapper falls back to the reference, which only
    needs eligible/case_id/flipped/family.
    """
    for name in results_by_adapter:
        if isinstance(name, str):
            _require_json_str(name)
    for rs in results_by_adapter.values():
        for r in rs:
            try:
                _require_result_strings(r)
            except AttributeError:
                # Duck-typed record: extraction fails -> TypeError ->
                # fallback to the reference.
                pass


def _flip_distribution_from_rust(d: dict) -> FlipDistribution:
    """Rebuild the dataclass from the Rust binding's field dict."""
    return FlipDistribution(
        adapters=tuple(d["adapters"]),
        n_cases=d["n_cases"],
        counts=tuple(d["counts"]),
    )


def _hardest_decile_from_rust(d: dict) -> HardestDecileSurvival:
    """Rebuild the dataclass from the Rust binding's field dict."""
    return HardestDecileSurvival(
        adapters=tuple(d["adapters"]),
        n_cases=d["n_cases"],
        decile_size=d["decile_size"],
        decile_case_ids=tuple(d["decile_case_ids"]),
        survived=dict(d["survived"]),
    )


def _transfer_matrix_from_rust(d: dict) -> TransferMatrix:
    """Rebuild the dataclass from the Rust binding's field dict."""
    return TransferMatrix(
        adapters=tuple(d["adapters"]),
        family=d["family"],
        n_cases=d["n_cases"],
        flipped_by_source=dict(d["flipped_by_source"]),
        rates={(s, t): v for s, t, v in d["rates"]},
    )


def _hardness_report_from_rust(d: dict) -> HardnessReport:
    """Rebuild the report from the Rust binding's nested field dicts."""
    return HardnessReport(
        adapters=tuple(d["adapters"]),
        n_cases=d["n_cases"],
        flip_distribution=_flip_distribution_from_rust(d["flip_distribution"]),
        hardest_decile=_hardest_decile_from_rust(d["hardest_decile"]),
        transfer_overall=_transfer_matrix_from_rust(d["transfer_overall"]),
        transfer_by_family={
            fam: _transfer_matrix_from_rust(m)
            for fam, m in d["transfer_by_family"].items()
        },
    )


def _report_to_plain(report: HardnessReport) -> dict:
    """Deconstruct a report into plain data for the Rust binding.

    Transfer rates cross as ``(src, dst, rate-or-None)`` triples; the
    binding rebuilds the ``{(src, dst): rate}`` dict.
    """
    def plain_transfer(t: TransferMatrix) -> dict:
        return {
            "adapters": list(t.adapters),
            "family": t.family,
            "n_cases": t.n_cases,
            "flipped_by_source": dict(t.flipped_by_source),
            "rates": [(s, d, v) for (s, d), v in t.rates.items()],
        }

    return {
        "adapters": list(report.adapters),
        "n_cases": report.n_cases,
        "flip_distribution": {
            "adapters": list(report.flip_distribution.adapters),
            "n_cases": report.flip_distribution.n_cases,
            "counts": list(report.flip_distribution.counts),
        },
        "hardest_decile": {
            "adapters": list(report.hardest_decile.adapters),
            "n_cases": report.hardest_decile.n_cases,
            "decile_size": report.hardest_decile.decile_size,
            "decile_case_ids": list(report.hardest_decile.decile_case_ids),
            "survived": dict(report.hardest_decile.survived),
        },
        "transfer_overall": plain_transfer(report.transfer_overall),
        "transfer_by_family": {
            fam: plain_transfer(m)
            for fam, m in report.transfer_by_family.items()
        },
    }


def flip_distribution(
    results_by_adapter: dict[str, list[PerCaseResult]],
) -> FlipDistribution:
    """Histogram of per-case flip counts over the common eligible universe.

    Dispatches to the Rust core when available; the pure-Python
    reference (:func:`_flip_distribution_py`) is the fallback.
    """
    if isinstance(results_by_adapter, dict):
        _check_results(results_by_adapter)
        if _rust is not None:
            try:
                return _flip_distribution_from_rust(
                    _rust.hardness_flip_distribution(results_by_adapter)
                )
            except (TypeError, AttributeError):
                # Non-string adapter names or non-PerCaseResult values
                # fail the PyO3 extraction: the reference handles (or
                # raises on) them.
                pass
    return _flip_distribution_py(results_by_adapter)


def hardest_decile_survival(
    results_by_adapter: dict[str, list[PerCaseResult]],
    decile: float = 0.10,
) -> HardestDecileSurvival:
    """Per-adapter survival on the hardest decile of cases.

    Hardness is the flip count across adapters. The decile is the top
    ``ceil(decile * n)`` cases by (flip count desc, case_id asc).
    Dispatches to the Rust core when available; the pure-Python
    reference (:func:`_hardest_decile_survival_py`) is the fallback.
    """
    if not 0 < decile <= 1:
        raise ValueError(f"decile must be in (0, 1], got {decile!r}")
    if isinstance(results_by_adapter, dict):
        _check_results(results_by_adapter)
        if _rust is not None:
            try:
                return _hardest_decile_from_rust(
                    _rust.hardness_hardest_decile_survival(results_by_adapter, decile)
                )
            except (TypeError, AttributeError):
                pass
    return _hardest_decile_survival_py(results_by_adapter, decile)


def transfer_matrix(
    results_by_adapter: dict[str, list[PerCaseResult]],
    family: str | None = None,
) -> TransferMatrix:
    """Cross-adapter transfer ASR, optionally restricted to one family.

    transfer(src -> dst) = P(dst flips | src flipped), over cases eligible
    for both src and dst (and in ``family`` when given). Dispatches to
    the Rust core when available; the pure-Python reference
    (:func:`_transfer_matrix_py`) is the fallback.
    """
    # Reject lone surrogates up front so both backends raise the same
    # ValueError (the Rust Option<String> extraction raises
    # UnicodeEncodeError, a ValueError the dispatch does not catch).
    if isinstance(family, str):
        _require_json_str(family)
    if isinstance(results_by_adapter, dict):
        _check_results(results_by_adapter)
        if _rust is not None:
            try:
                return _transfer_matrix_from_rust(
                    _rust.hardness_transfer_matrix(results_by_adapter, family)
                )
            except (TypeError, AttributeError):
                pass
    return _transfer_matrix_py(results_by_adapter, family)


def analyze_runs(
    results_by_adapter: dict[str, list[PerCaseResult]],
    decile: float = 0.10,
) -> HardnessReport:
    """Full M-4 diagnostic report over N adapter runs.

    Dispatches to the Rust core when available; the pure-Python
    reference (:func:`_analyze_runs_py`) is the fallback.
    """
    if isinstance(results_by_adapter, dict):
        # Decile is checked here (not before the isinstance) so that a
        # non-dict input raises the reference's TypeError first, matching
        # the reference's error precedence.
        if not 0 < decile <= 1:
            raise ValueError(f"decile must be in (0, 1], got {decile!r}")
        _check_results(results_by_adapter)
        if _rust is not None:
            try:
                return _hardness_report_from_rust(
                    _rust.hardness_analyze_runs(results_by_adapter, decile)
                )
            except (TypeError, AttributeError):
                pass
    return _analyze_runs_py(results_by_adapter, decile)


def report_text(report: HardnessReport) -> str:
    """Human-readable M-4 diagnostic tables.

    Labeled diagnostic throughout: these tables describe the shape of
    hardness and transfer; they do not rank adapters. Dispatches to the
    Rust core when available; the pure-Python reference
    (:func:`_report_text_py`) is the fallback.
    """
    if _rust is not None:
        try:
            return _rust.hardness_report_text(_report_to_plain(report))
        except (AttributeError, TypeError):
            # Not a HardnessReport, or an unusual field value: the
            # reference raises the natural exception (or renders it).
            pass
    return _report_text_py(report)
