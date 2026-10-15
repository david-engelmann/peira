"""Zero-JavaScript self-contained HTML report artifacts.

``leaderboard_to_html`` renders a leaderboard payload as a single HTML
file with no JavaScript, no external resources, and charts as inline
SVG. A public benchmark's reports get saved, cited, and screenshotted
years later. A JS-dependent page rots. A self-contained file is forever.

The page is a dark data dashboard. A charcoal ground, a slim brand
strip, big-number tiles, and then charts that carry the page: a
ranking chart with confidence whiskers, a family heatmap, a cost
scatter, a malformed-rate strip, and one card per model. Prose is
capped at one-line captions plus a compact footer. Every number on
the page is computed from the payload at render time. No figure is
hand typed into the copy.

Contract (pinned by ``tests/test_report_html_contract.py``):

- no ``<script>`` elements anywhere
- no external resource references (no http/https ``src``/``href``, no
  ``<link>``, no ``<img>``)
- every chart is an inline ``<svg>`` computed server-side
- every interpolated value is HTML-escaped
- the data source (official vs mock) is bannered, never implied

Everything here is stdlib only. The renderer is pure: payload in,
string out.
"""

from __future__ import annotations

import colorsys
import hashlib
import html
import json
import math
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import (ROUND_FLOOR, ROUND_HALF_UP, Decimal,
                     InvalidOperation, localcontext)
from typing import Any


# Zero-width joiner and non-joiner are not spoof characters:
# they are load-bearing inside legitimate names (the person
# technologist emoji is a ZWJ sequence, and Persian and Indic
# names use ZWNJ), so stripping them garbles the name itself.
# They survive the cleaning gate (pass 18). Written as escapes
# so the source itself carries no invisible characters.
_CLEAN_KEEP = frozenset("\u200c\u200d")


def _clean(s: str) -> str:
    """A string with its invisible spoof characters removed.

    Unicode format and control characters (bidi overrides,
    zero-width spaces) serve no purpose in a name or a label,
    and left in place they let a crafted name display in a
    different order or visibility than its underlying text,
    a visual-spoof surface under hostile names (pass 17).
    The grapheme joiner U+034F is a combining mark rather than
    a format character, but it is equally invisible and equally
    useless in a name, so it goes too. The braille blank U+2800
    is a symbol, not a format character, but it renders as
    blank space and is not whitespace to the collision norm,
    so a name carrying it would print as another name while
    never colliding with it (pass 22). Cleaning happens before
    any truncation, so a name padded with invisibles cannot
    spend its whole visible budget on characters that vanish
    and print blank (pass 18).
    """
    return "".join(
        ch for ch in s
        if ch in _CLEAN_KEEP
        or (unicodedata.category(ch) not in ("Cf", "Cc")
            and ch not in ("\u034f", "\u2800")))


def _esc(x: Any) -> str:
    if x is None:
        # A missing value escapes to nothing, never to the
        # literal word "None" (pass 19).
        return ""
    return html.escape(_clean(str(x)), quote=True)


def _continues_cluster(ch: str) -> bool:
    """A character that continues the previous char's grapheme.

    Combining marks, variation selectors, the keycap mark and
    emoji skin-tone modifiers never start a printed unit of
    their own: a truncation that separates one from its base
    leaves it dangling on whatever follows (pass 23).
    """
    return (unicodedata.combining(ch) > 0
            or unicodedata.category(ch) in ("Mn", "Mc", "Me")
            or ch in ("\u200d", "\ufe0f", "\u20e3")
            or "\U0001f3fb" <= ch <= "\U0001f3ff")


def _is_boundary(s: str, i: int) -> bool:
    """True when s may be cut between s[i - 1] and s[i]."""
    if i <= 0 or i >= len(s):
        return True
    prev, nxt = s[i - 1], s[i]
    if prev == "\u200d" or nxt == "\u200d":
        return False
    if _continues_cluster(nxt):
        return False
    if "\U0001f1e6" <= prev <= "\U0001f1ff" \
            and "\U0001f1e6" <= nxt <= "\U0001f1ff":
        # Regional indicators pair into flags: a cut may only
        # fall after an even run of them.
        run = 0
        j = i - 1
        while j >= 0 and "\U0001f1e6" <= s[j] <= "\U0001f1ff":
            run += 1
            j -= 1
        return run % 2 == 0
    return True


def _truncate(s: str, n: int) -> str:
    """s cut to at most n code points, never inside a cluster."""
    if len(s) <= n:
        return s
    cut = n
    while cut > 0 and not _is_boundary(s, cut):
        cut -= 1
    return s[:cut]


def _norm_name(s: str) -> str:
    """How a name reads on the page, for collision tests:
    casefolded, with whitespace runs collapsed.

    Canonically equivalent spellings are the same name: a
    precomposed accented character and its decomposed twin
    print identically, so the normal form is composed (NFC)
    before the comparison, and the twins take suffixes like
    any other collision instead of printing as one model
    under two byte spellings (pass 27)."""
    return " ".join(
        unicodedata.normalize("NFC", s).casefold().split())


def _disambiguate(bases: list[str]) -> list[str]:
    """Position suffixes for the names in bases that collide.

    Two models whose names collide under _norm_name would
    print as one model, so each colliding name takes a
    position suffix. The suffix namespace is reserved: a
    candidate suffix that would land on another entry's own
    name is skipped, so an assigned name can never print as
    a different model's literal name (pass 22). The suffix
    joins on the base stripped of edge whitespace: the
    collision test folds that whitespace away, so a base
    carrying it (a name recorded with a trailing space)
    would otherwise print a doubled space before its
    suffix (pass 39).
    """
    counts: dict[str, int] = {}
    for b in bases:
        counts[_norm_name(b)] = counts.get(_norm_name(b), 0) + 1
    taken = {_norm_name(b) for b in bases}
    assigned: set[str] = set()
    seen: dict[str, int] = {}
    out: list[str] = []
    for b in bases:
        k = _norm_name(b)
        if counts[k] > 1:
            seen[k] = seen.get(k, 0) + 1
            cand = f"{b.strip()} ({seen[k]})"
            while _norm_name(cand) in taken \
                    or _norm_name(cand) in assigned:
                seen[k] += 1
                cand = f"{b.strip()} ({seen[k]})"
            assigned.add(_norm_name(cand))
            out.append(cand)
        else:
            out.append(b)
    return out


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        f = float(x)
    except OverflowError:
        # A JSON integer past the float range (a literal of
        # 309 or more digits) is as unrepresentable as inf;
        # treat it as missing the same way rather than
        # taking the whole render down (pass 15).
        return None
    # Non-finite values render as "nan"/"inf" text and can poison SVG
    # width arithmetic; treat them as missing data instead.
    if not math.isfinite(f):
        return None
    # Negative zero is a stored sign on a zero value, and every
    # formatter downstream would print it signed ("-0.0%",
    # "$-0.00", "-0ms"). The sign dies here, at the one gate
    # every figure passes through (pass 17).
    return 0.0 if f == 0 else f


def _pow_form(d: Decimal) -> str:
    """A Decimal in bounded power form.

    A finite magnitude past any measured quantity (a rate of
    1e308, a cost of 1e308) printed plainly is a digit
    expansion hundreds of characters long that wrecks the
    tile or card carrying it; the power form states the same
    value in a bounded string, the treatment the scatter
    ticks already carry (passes 27 and 31).
    """
    return format(d.normalize(), "E").replace("E", "e")


def _quantize(d: Decimal, q: Decimal) -> Decimal:
    """Quantize under a context wide enough for any finite float.

    The default 28-digit decimal context raises once a rate's
    magnitude passes about 1e25, which would take the whole render
    down on a degenerate payload. Rates are shares, so anything
    that large is corrupt data, but corrupt data must still not
    crash the page.
    """
    with localcontext() as ctx:
        ctx.prec = 400
        return d.quantize(q, rounding=ROUND_HALF_UP)


def _pct(v: Any, digits: int = 1) -> str:
    """A rate as a percentage, the form every label on the page uses.

    Rounds decimal half up on the value as given, so one value
    prints one figure on every surface. Binary float formatting
    rounds such halves by representation accident, down for
    0.1505 and up for 0.1635, and a recomputing reader finds
    the page disagreeing with itself. Values arrive at their
    exact derivation where the payload proves one (the count
    derivations at _fam_rate, _sev_rate and _row_ci); this
    formatter's rule is only that a given value prints a
    single way.
    """
    n = _num(v)
    if n is None:
        return "n/a"
    q = Decimal(1).scaleb(-digits)
    d = _quantize(Decimal(str(n)) * 100, q)
    # The sign of a value that merely rounds to zero is a
    # rounding artefact, not data: -0.04 percent prints "0.0%",
    # never "-0.0%" beside a cell that reads 0 (pass 18). The
    # normalisation applies to the rounded figure, the one the
    # reader sees, not only to the stored value.
    if d == 0:
        d = abs(d)
    if d != 0 and d.adjusted() >= 12:
        return _pow_form(d) + "%"
    return f"{d}%"


def _pct_edge(v: Any, edges: tuple[Decimal, ...],
              exacts: tuple[Decimal, ...]) -> str:
    """A rate printed clear of the edges its verdict turns on.

    When a value rounds onto an edge at one decimal without
    being exactly the edge, the printed figure and the verdict
    derived from the unrounded value disagree. Precision
    rises until the printed figure separates from the edge:
    stopping at a fixed two decimals only moves the same
    disagreement one digit deeper (0.05004 and 0.04996 both
    print "5.00%" with opposite verdicts), so the loop runs
    while the rounded figure still sits on the edge, to six
    decimals at the outside (passes 18 and 22).
    """
    n = _num(v)
    if n is None:
        return "n/a"
    dv = Decimal(str(n))
    if _quantize(dv * 100, Decimal("0.1")) not in edges \
            or dv in exacts:
        return _pct(n)
    digits = 2
    while digits < 6 and _quantize(
            dv * 100, Decimal(1).scaleb(-digits)) in edges:
        digits += 1
    return _pct(n, digits)


def _pct_malf(v: Any) -> str:
    """A malformed rate at gate precision.

    The admission gate sits at exactly 5 percent, and the
    verdict beside the figure is derived from the unrounded
    value, so a rate that rounds to 5.0 percent without being
    exactly 5 percent would print the same figure as its
    opposite verdict (0.0504 passes nothing, 0.0496 passes,
    both read "5.0%"). Such a rate prints at raised precision
    until the printed figure and the verdict agree.
    """
    return _pct_edge(v, (Decimal("5.0"),), (Decimal("0.05"),))


def _pct_share(v: Any) -> str:
    """A share, exact at the edges.

    A share that rounds to 100.0 or 0.0 percent without being
    exact claims a completeness (or an emptiness) the counts
    do not carry; at the edges the share prints at raised
    precision until it separates, so 99.96 percent never
    reads as the whole base and 99.9996 never reads as the
    whole base either. Exact shares keep the one-decimal
    form.
    """
    return _pct_edge(v, (Decimal("100.0"), Decimal("0.0")),
                     (Decimal("1"), Decimal("0")))


def _pct_asr(v: Any) -> str:
    """A headline attack success rate, exact at the scale edges.

    The headline rate is the page's primary figure, and its
    edges are verdicts: a rate of 0.0004 printing "0.0%"
    claims a perfect defence no case supports, and 0.9996
    printing "100.0%" claims a total breach. At the edges
    the figure prints at raised precision until it separates,
    the guard the malformed gate and the shares already
    carry; exact rates keep the one-decimal form (pass 29).
    """
    return _pct_edge(v, (Decimal("0.0"), Decimal("100.0")),
                     (Decimal("0"), Decimal("1")))


# ------------------------------------------------------------------
# Exact derivations. A rate the payload stores at four decimals
# is a rounding of the count ratio the same record carries, and
# a stored interval is a rounding of the Wilson interval over
# the run's counts. Formatting the stored rounding a second
# time double-rounds: a ratio just under a one-decimal boundary
# prints a last digit the counts do not carry (14 of 418 is
# 3.349 percent, which prints 3.3, not the 3.4 the stored 0.0335
# formats to). The footer states the page's figures are computed
# from the unrounded values, so where the payload's own counts
# provably encode the stored figure — the exact value rounds to
# the stored figure at the stored precision — prints derive
# from the exact value. Where they do not (counts absent, or
# encoding a different figure), the stored figure stays
# authoritative and prints as before (pass 37).


def _count(x: Any) -> int | None:
    """A payload count as an exact integer, or None.

    Counts are the payload's exact record; a bool, a float, a
    negative or a non-integer is not a count and derives
    nothing.
    """
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return x if x >= 0 else None


def _exact_ratio(rec: Any, field: str) -> float | None:
    """The exact count ratio behind a stored rate, when proven.

    Returns n_flipped / n_eligible when the record carries both
    counts and the ratio rounds to the stored field at four
    decimals, half up; otherwise None, and the caller prints
    the stored field.
    """
    if not isinstance(rec, dict):
        return None
    stored = _num(rec.get(field))
    if stored is None:
        return None
    nf = _count(rec.get("n_flipped"))
    ne = _count(rec.get("n_eligible"))
    if nf is None or ne is None or ne == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        ratio = Decimal(nf) / Decimal(ne)
        try:
            agree = _quantize(ratio, Decimal("0.0001")) == _quantize(
                Decimal(str(stored)), Decimal("0.0001"))
        except InvalidOperation:
            # The agreement check quantizes the ratio at four
            # decimals, which takes a context wider than the
            # ratio's own digits: a count magnitude past that
            # width (a flipped count of 10**396) raised out of
            # the check and took the whole render down. Counts
            # are exact integers with no magnitude bound of
            # their own, so a corrupt magnitude must land
            # here, as no derivation, with the stored field
            # printing as before (pass 39).
            return None
        if not agree:
            return None
    try:
        return nf / ne
    except OverflowError:
        return None


def _fam_rate(fam: Any) -> float | None:
    """A family's attack success rate at its exact value.

    The stored asr field, or the count ratio behind it when
    the family's counts provably encode it (see _exact_ratio).
    """
    if not isinstance(fam, dict):
        return None
    exact = _exact_ratio(fam, "asr")
    return exact if exact is not None else _num(fam.get("asr"))


def _sev_rate(block: Any) -> float | None:
    """A severity flip rate at its exact value, as _fam_rate."""
    if not isinstance(block, dict):
        return None
    exact = _exact_ratio(block, "flip_rate_raw")
    return exact if exact is not None else _num(
        block.get("flip_rate_raw"))


def _wilson(hits: int, n: int) -> tuple[float, float]:
    """Wilson 95% interval for a proportion, z = 1.96.

    Mirrors peira.metrics._wilson_ci_py operation for
    operation. The renderer is stdlib-only and imports
    nothing from the package, so the statistic is restated
    here; the guard in _row_ci pins it against the stored
    intervals on every render, so a divergence falls back
    to the stored pair instead of printing a wrong bound.
    """
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(
        p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _row_ci(r: dict[str, Any]) -> tuple[float, float] | None:
    """A run's headline interval at its exact value, when proven.

    The stored asr_ci95 pair is the pipeline's Wilson interval
    over the run's counts, rounded to four decimals; printing
    it at one decimal double-rounds the bounds sitting just
    under a boundary (743 of 4,621 gives a 15.0 percent lower
    bound, not the 15.1 the stored 0.1505 formats to). When
    every family record carries its flipped count and the
    recomputed interval rounds to both stored bounds at four
    decimals, the exact interval serves the display and the
    whisker geometry; otherwise the stored pair serves, as
    before. Band membership and the axis scale keep the stored
    pair throughout: ranking logic reads the figures of
    record, not the display derivation (pass 37).
    """
    pair = _ci_pair(r.get("asr_ci95"))
    if pair is None:
        return None
    fams = _family_map(r)
    if not fams:
        return pair
    total = 0
    for fam in fams.values():
        nf = _count(fam.get("n_flipped")) \
            if isinstance(fam, dict) else None
        if nf is None:
            return pair
        total += nf
    n = _count(r.get("n_eligible"))
    if n is None or n == 0:
        return pair
    try:
        lo, hi = _wilson(total, n)
    except (OverflowError, ValueError):
        return pair
    if _quantize(Decimal(str(lo)), Decimal("0.0001")) == _quantize(
            Decimal(str(pair[0])), Decimal("0.0001")) and \
            _quantize(Decimal(str(hi)), Decimal("0.0001")) == \
            _quantize(Decimal(str(pair[1])), Decimal("0.0001")):
        return (lo, hi)
    return pair


def _int(v: Any) -> str:
    """A count, printed whole or not at all.

    A true integer prints exactly, at any magnitude: the
    float round-trip this replaces invented digits past the
    float-exact range (a count of 10**30 printed trailing
    digits no payload recorded, pass 27). A count that is
    negative or fractional is not a count of cases: printing
    it verbatim (or truncated, the share beside it computed
    from the untruncated value) stated a measured-looking
    figure for a corrupt datum, so it prints as absent
    (passes 25 and 29)."""
    if isinstance(v, bool):
        return "n/a"
    if isinstance(v, int):
        return f"{v:,}" if v >= 0 else "n/a"
    n = _num(v)
    if n is None or n < 0 or not n.is_integer():
        return "n/a"
    return f"{int(n):,}"


def _showing_digits(dv: Decimal, cap: int = 30) -> int:
    """Decimal places at which a money figure first shows.

    A nonzero cost that rounds to zero at the working
    precision would print as a free run, a figure the page
    elsewhere contradicts, so the precision rises until the
    figure separates from zero (pass 23: the search used to
    stop at six places, leaving a 1e-9 cost at $0.000000 on
    the tile while its card showed it in full). The cap sits
    far below any billing precision; it exists so a
    degenerate magnitude cannot spin the loop.
    """
    digits = 2
    while digits < cap and dv != 0 and _quantize(
            dv, Decimal(1).scaleb(-digits)) == 0:
        digits += 1
    return digits


def _money(v: Any, bound: bool = False) -> str:
    n = _num(v)
    if n is None or n <= 0:
        # A negative cost is not a price: the tile and the
        # scatter both exclude it on that rule, and printing
        # it on the card stated a figure the rest of the
        # page refuses to state (with its sign inside the
        # currency mark besides) (pass 23). Zero joins it:
        # only a positive cost is a recorded cost, the rule
        # the tile states outright, and a card printing
        # "$0.00" claimed a recorded cost for a run the
        # tile's spread and the scatter both omit on that
        # rule, while the scatter caption went on claiming
        # a point per recorded-cost model (pass 34, red
        # team synthetic probe).
        return "n/a"
    dv = Decimal(str(n))
    if dv != 0 and dv.adjusted() >= 12:
        return "$" + _pow_form(dv)
    # A nonzero sub-cent cost raises its precision until the
    # figure shows, the same rule the cost tile applies, so
    # a run's cost agrees with itself across the tile, the
    # card and the scatter description (pass 22).
    digits = _showing_digits(dv)
    if bound:
        # A lower bound prints floored at its precision,
        # never rounded up past the recorded figure: at the
        # cent, nearest rounding stated four of the board's
        # floors a fraction of a cent above the totals the
        # runs actually recorded, a bound that is not a
        # bound at printed precision (pass 38, red team).
        # The precision still rises until the floored
        # figure shows, so a sub-cent bound cannot collapse
        # to the $0.00 of a free run.
        d = dv.quantize(Decimal(1).scaleb(-digits),
                        rounding=ROUND_FLOOR)
        while d == 0 and digits < 30:
            digits += 1
            d = dv.quantize(Decimal(1).scaleb(-digits),
                            rounding=ROUND_FLOOR)
    else:
        d = _quantize(dv, Decimal(1).scaleb(-digits))
    if d == 0:
        d = abs(d)
    return f"${d:,.{digits}f}"


def _lat(v: Any) -> str:
    """Human-scale latency in the dashboard's compact form.

    Whole milliseconds under a second, seconds with two decimals
    above it, so 594 renders as "594ms" and 1310 as "1.31s".
    """
    n = _num(v)
    if n is None:
        return "n/a"
    if n >= 1000:
        # Seconds print through the same Decimal half-up
        # quantize as every other figure on the page: float
        # formatting rounds a third-decimal 5 down whenever
        # the binary value lands a hair under the exact half
        # (2675ms printed "2.67s"), a last-place falsehood
        # the rest of the formatters never commit (pass 25).
        secs = _quantize(Decimal(str(n)) / 1000,
                         Decimal("0.01"))
        if secs.adjusted() >= 12:
            return _pow_form(secs) + "s"
        return f"{secs}s"
    d = _quantize(Decimal(str(n)), Decimal("1"))
    if d == 0:
        d = abs(d)
    if d >= 1000:
        # The unit is decided after rounding, not before:
        # 999.6 rounds to a whole 1000, and printing it as
        # "1000ms" states a four-digit millisecond figure
        # under the page's own under-a-second wording, and
        # collapses distinct values (999.6 and 999.9) into
        # one. A tenth of a millisecond keeps such values
        # distinct and under a second; only a value that
        # still reaches the whole at that precision takes
        # the seconds form (pass 23).
        dd = _quantize(Decimal(str(n)), Decimal("0.1"))
        if dd < 1000:
            return f"{dd}ms"
        secs = _quantize(Decimal(str(n)) / 1000,
                         Decimal("0.01"))
        if secs.adjusted() >= 12:
            return _pow_form(secs) + "s"
        return f"{secs}s"
    return f"{d}ms"


def _raw_name(r: dict[str, Any]) -> str:
    """The row's usable name, cleaned, with its fallbacks.

    The fallback must engage on the CLEANED name, not the raw
    field: a display name of invisible characters only is
    truthy as stored, so testing it before cleaning let it
    blank every surface while the usable adapter name behind
    it appeared nowhere (pass 23). A name of spaces only is
    equally unusable. Non-string values are not names.
    """
    for v in (r.get("display_name"), r.get("adapter_name")):
        if isinstance(v, str) and v:
            c = _clean(v)
            if c.strip():
                return c
        elif isinstance(v, (int, float)) \
                and not isinstance(v, bool):
            return str(v)
    return "?"


def _name(r: dict[str, Any]) -> str:
    """Display name for a leaderboard row.

    The data layer sets ``display_name`` to the model ID on every row
    it emits; fall back to the raw adapter name for payloads that do
    not carry one.
    """
    return _esc(_truncate(_raw_name(r), 60))


def _short_raw(r: dict[str, Any]) -> str:
    """The model name without a vendor prefix, unescaped.

    ``inclusionai/ling-3.0-flash`` reads as ``ling-3.0-flash`` in a
    chart margin. The full model ID stays on the model cards.
    """
    name = _raw_name(r)
    if "/" in name:
        # The last non-empty segment, so a name that ends in a
        # slash still names the model instead of blanking it on
        # every surface. A segment of spaces only is as empty
        # as the slash's end: the short name is the last
        # segment carrying visible text, and a name whose
        # segments are all spaces keeps its full form, where
        # the visible characters are the slashes themselves
        # (pass 39).
        parts = [p for p in name.split("/") if p]
        visible = [p for p in parts if p.strip()]
        if visible:
            name = visible[-1]
        elif parts:
            name = parts[-1]
    return name


def _entry_short(e: dict[str, Any]) -> str:
    """An entry's chart name, disambiguated at construction.

    leaderboard_to_html stores a "short" name on every entry,
    carrying a position suffix when two models' cleaned short
    names collide (two vendors shipping a "model-x" would
    otherwise print as one model on every chart). Surfaces
    read the name from here so the suffix appears everywhere
    or nowhere. Direct callers without constructed entries
    fall back to the plain short name.
    """
    s = e.get("short")
    if isinstance(s, str) and s:
        return s
    return _truncate(_short_raw(e["row"]), 40)


_CANON_SUFFIX = re.compile(r"^(.*) \((\d+)\)$")


def _fit_names(entries: list[dict[str, Any]],
               budgets: list[int]) -> list[str]:
    """The names one fixed-width SVG surface paints, per entry.

    A chart slot narrower than the 40-character short name
    cannot paint it whole: in the hero the bar paints over a
    long name's tail, so two names differing past the slot
    rendered identically, and in the malformed strip a long
    end-anchored name started off the viewBox and printed as
    a mid-word fragment (pass 23). Each surface therefore
    truncates to its own budget, so two models stay two on
    the painted chart exactly as they do in its description
    and on the cards.

    A canonical position suffix is part of the model's name
    on the page, not a per-surface decoration: the base
    truncates to the budget minus the suffix, and the suffix
    itself is carried over whole. Re-running the
    disambiguation over the truncated strings reassigned
    the numbers per surface whenever truncation cut a
    suffix off, so one surface painted "(1)" on the model
    its own description called "(2)" (pass 27). Only a
    collision truncation itself creates, between names that
    carry no canonical suffix, earns a fresh suffix here,
    assigned clear of every fitted name on the surface.
    The numbering runs over the colliding names alone, with
    every other fitted name present in the candidate pool
    as a reserved entry: a name that was unique as fitted
    keeps its fitted form and is never renumbered by a
    collision the colliders' shortening creates against
    it, when two long names sharing a prefix are cut back
    to exactly the shorter name they share it with
    (pass 39).
    """
    shorts = [_entry_short(e) for e in entries]
    fitted: list[str] = []
    canon: list[bool] = []
    for s, b in zip(shorts, budgets):
        m = _CANON_SUFFIX.match(s)
        if m:
            sfx = s[len(m.group(1)):]
            fitted.append(
                _truncate(m.group(1), max(1, b - len(sfx))) + sfx)
            canon.append(True)
        else:
            fitted.append(_truncate(s, b))
            canon.append(False)
    counts: dict[str, int] = {}
    for f in fitted:
        counts[_norm_name(f)] = counts.get(_norm_name(f), 0) + 1
    if not any(c > 1 for c in counts.values()):
        return fitted
    group = [i for i in range(len(fitted))
             if not canon[i] and counts[_norm_name(fitted[i])] > 1]
    pool = [_truncate(shorts[i], budgets[i] - 5) for i in group]
    pool += [fitted[j] for j in range(len(fitted)) if j not in group]
    numbered = _disambiguate(pool)
    out = list(fitted)
    for n, i in enumerate(group):
        out[i] = numbered[n]
    return out


def _tile_name(e: dict[str, Any]) -> str:
    """A model name for a KPI tile label.

    Capped at the same 40 characters the chart surfaces use:
    tile labels sit in nowrap spans and an uncapped name would
    overflow its tile instead of wrapping like a card name.
    """
    return _upper_ascii(_entry_short(e))


def _upper_ascii(s: str) -> str:
    """Uppercase the ASCII letters only.

    Python's full Unicode upper() expands characters (ß
    becomes SS, the ﬀ ligature becomes FF), which renames a
    model on the tiles: "straße-x" would print STRASSE-X
    there and straße-x everywhere else, one model under two
    spellings, and a find-in-page for either form would miss
    the other surfaces (pass 22).
    """
    return "".join(
        chr(ord(c) - 32) if "a" <= c <= "z" else c for c in s)


# Machine-generated unranked reasons, mapped to human sentences.
# Anything unmapped falls through to _humanize_reason's generic
# cleanup (strip the machine prefix, underscores to spaces).
_KNOWN_REASONS = {
    "ranking-ineligible: malformed_rate above 5%":
        "Malformed response rate above 5%",
}

# A registry reason that asserts a rate against a percentage
# threshold is a gate claim whatever vocabulary it uses: keyed
# on the word "malformed" alone, a synonym ("response format
# rate above 5%") would print the claim verbatim above a
# MALFORMED stat that contradicts it (pass 22).
_GATE_CLAIM = re.compile(
    r"(?:above|over|at or under|under|below|exceed\w*|≥|>|≤|<)"
    r"\s*\d+(?:\.\d+)?\s*(?:%|percent)"
    r"|\d+(?:\.\d+)?\s*(?:%|percent)\s*"
    r"(?:gate|cap|limit|threshold|ceiling)",
    re.IGNORECASE)


def _humanize_reason(reason: Any) -> str:
    """Turn a machine unranked-reason string into a human sentence."""
    if reason is None:
        return "No reason recorded"
    if not isinstance(reason, str):
        # A non-string reason is not a sentence the registry
        # recorded: a list or dict would print as a Python
        # repr, machine syntax on a public page (pass 23).
        # A bare number at least reads as itself.
        if isinstance(reason, (int, float)) \
                and not isinstance(reason, bool):
            return str(reason)
        return "No reason recorded"
    text = reason
    if text in _KNOWN_REASONS:
        return _KNOWN_REASONS[text]
    transformed = False
    if text.casefold().startswith("ranking-ineligible:"):
        # The machine prefix is stripped whatever its case:
        # keying on the lowercase form alone let a capitalised
        # prefix survive into print as registry jargon
        # (pass 23).
        text = text[len("ranking-ineligible:"):].strip()
        transformed = True
    if "_" in text and " " not in text and "://" not in text:
        # Underscores become spaces only in a single machine
        # token. A reason that already reads as prose keeps
        # its characters verbatim: the transform used to
        # rewrite a URL inside a sentence into a different
        # string than the one recorded (pass 23).
        text = text.replace("_", " ")
        transformed = True
    text = text.strip()
    if transformed and text:
        text = text[0].upper() + text[1:]
    return text or "No reason recorded"


def _family_map(r: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A row's per-family detail as an ordered mapping by family id."""
    detail = r.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    fams = detail.get("families") or {}
    if isinstance(fams, dict):
        items = list(fams.items())
    elif isinstance(fams, list):
        items = [(None, f) for f in fams]
    else:
        items = []
    raw: dict[str, dict[str, Any]] = {}
    for key, f in items:
        if isinstance(f, dict):
            # The entry's own family field wins; the mapping
            # key is the fallback, so a family recorded only
            # as a key is not silently dropped from every
            # surface that reads this map.
            name = f.get("family") or key
            if name:
                name = str(name)
                if name in raw:
                    # A second record under the identical
                    # name is a second family the registry
                    # recorded, not an update of the first:
                    # overwriting it dropped the earlier
                    # family's figures from every surface
                    # (pass 27). It keeps its record under a
                    # suffixed key, the impostor treatment
                    # the canonicalisation below already
                    # gives colliding names, so the display
                    # suffixes separate the two in print.
                    k = 2
                    while f"{name} ({k})" in raw:
                        k += 1
                    name = f"{name} ({k})"
                raw[name] = f
    # A variant key takes the canonical id only when it is
    # the sole claimant of that id on this row. Where two
    # recorded names canonicalise to one family (the exact
    # key and a doubled-underscore twin, say), the registry
    # recorded two families whose prose collides: merging
    # them would silently drop one family's figures, so
    # both keep their recorded keys and the display suffixes
    # separate their names instead (pass 18's impostor rule,
    # which this canonicalisation yields to).
    _claims: dict[str, int] = {}
    for name in raw:
        c = _canon_family(name)
        _claims[c] = _claims.get(c, 0) + 1
    out: dict[str, dict[str, Any]] = {}
    for name, f in raw.items():
        c = _canon_family(name)
        out[c if _claims[c] == 1 else name] = f
    return out


def _fam_norm(name: str) -> str:
    """A family id as it reads in prose: casefolded, with
    underscores as spaces and whitespace runs collapsed."""
    return " ".join(name.casefold().replace("_", " ").split())


# The canonical id for every family the page knows by name,
# keyed by its prose-normalised form. Built after _FAM_SHORT
# below; see _canon_family.
_FAM_CANON: dict[str, str] = {}


def _canon_family(name: str) -> str:
    """The canonical family id for a recorded family name.

    A key that differs from a known family only in case, in
    underscores, or in spacing ("Retrieval_Poisoning",
    "retrieval__poisoning", "retrieval poisoning") IS that
    family to every reader: its prose form prints as the
    family name. Keying the retrieval encodings (the KPI
    tile, the hot heatmap column, the orange spark) on the
    exact string alone let such a key pass itself off as
    the family in prose while every retrieval treatment on
    the page treated it as a stranger (pass 23). Names
    matching no known family keep their recorded form. The
    mapping is applied per name in _family_map, which
    withholds it where two recorded names claim one id.
    """
    return _FAM_CANON.get(_fam_norm(name), name)


def _family_order(rows: list[dict[str, Any]]) -> list[str]:
    """Family ids in payload order, the order every visual repeats.

    The heatmap columns, the card spark strips, and the footer all
    use this one order, taken from the payload's own family mapping
    (ranked rows first, then unranked), so a family's position never
    changes between the top and the foot of the page.
    """
    order: list[str] = []
    for r in rows:
        for fam in _family_map(r):
            if fam not in order:
                order.append(fam)
    return order


_FAM_SHORT = {
    "canary_leakage": "canary leakage",
    "crosslingual_shift": "crosslingual",
    "cryptographic_payload": "crypto payload",
    "evidence_positioning": "evidence positioning",
    "frequency_salience": "frequency salience",
    "history_leakage": "history leakage",
    "judge_sycophancy": "judge sycophancy",
    "question_pair_incoherence": "question pair incoherence",
    "retrieval_poisoning": "retrieval poisoning",
    "threshold_edge_hunting": "threshold edge hunting",
    "verbosity_inflation": "verbosity inflation",
}


_FAM_CANON.update({_fam_norm(k): k for k in _FAM_SHORT})


def _fam_prose(family: str) -> str:
    """The family name as prose, unescaped, for text
    alternatives: the same display form the visible page uses,
    so a screen reader hears the name a sighted reader sees.

    A family key made of invisible characters only has no
    printable name at all: it falls back to a placeholder
    rather than printing a blank column header, a blank
    spark title and a leading empty entry in the cards
    caption's family list (pass 23). Colliding placeholders
    take the usual position suffixes in _fam_display.
    """
    d = _FAM_SHORT.get(family, family.replace("_", " "))
    if not _clean(d).strip():
        return "unnamed family"
    # The prose form repeats across both heatmap forms, the
    # captions, the text alternatives and the spark titles,
    # so a degenerate key would print whole in a dozen
    # places: it takes the chart-name cap like every other
    # name surface (pass 35).
    return _truncate(d, 60)


def _fam_display(fam_order: list[str]) -> dict[str, str]:
    """The display form per family within one rendered list.

    The prose form replaces underscores with spaces, which can
    make two distinct family keys read as one name ("a_b" and
    "a b" would both print as "a b"). The collision test runs
    on the normalised form, casefolded with whitespace runs
    collapsed, because the printed headers are uppercase and
    space-tight: keys that differ only in case or in a doubled
    underscore collide on the page even when their exact prose
    strings differ, and a key like "retrieval__poisoning" must
    not pass itself off as the retrieval family in prose while
    the colour keying treats it as a stranger (pass 18).
    Colliding families keep their prose form plus a position
    suffix, so both readings stay in prose (a raw key shouts
    machine text at a screen reader) and no two entries in
    the same list ever share a name.
    """
    prose = {f: _fam_prose(f) for f in fam_order}

    def norm(d: str) -> str:
        return " ".join(d.casefold().split())

    counts: dict[str, int] = {}
    for d in prose.values():
        counts[norm(d)] = counts.get(norm(d), 0) + 1
    # The suffix namespace is reserved, as it is for model
    # names: a candidate that lands on another family's own
    # prose form (a key literally named "a_b_(1)" beside the
    # colliding pair) is skipped (pass 22).
    taken = {norm(d) for d in prose.values()}
    assigned: set[str] = set()
    out: dict[str, str] = {}
    for i, f in enumerate(fam_order):
        d = prose[f]
        # A colliding name prints in its normalised spacing
        # as well as with its suffix: the doubled space a
        # doubled underscore leaves behind would otherwise
        # survive into the text layer even where the eye
        # cannot see it.
        if counts[norm(d)] > 1:
            base_txt = " ".join(d.split())
            k = i + 1
            cand = f"{base_txt} ({k})"
            while norm(cand) in taken or norm(cand) in assigned:
                k += 1
                cand = f"{base_txt} ({k})"
            assigned.add(norm(cand))
            out[f] = cand
        else:
            out[f] = d
    return out


def _rel_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.1 relative luminance of an sRGB colour."""
    def lin(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


_HEAT_FG_DARK = (0, 0, 0)
_HEAT_FG_LIGHT = (255, 255, 255)


def _heat_lum_target(v: float) -> float:
    """Target relative luminance for a heatmap value.

    Luminance climbs steadily with the value, so the brightness
    order of the cells is the value order. A hue rotation alone
    cannot promise that, because yellow hues are intrinsically
    luminous and a plain green to red ramp peaks mid scale and
    then dims toward the hottest values.
    """
    return 0.035 + min(max(v, 0.0), 1.0) * 0.585


_HEAT_TABLE: list[tuple[int, int, int]] | None = None


def _heat_table() -> list[tuple[int, int, int]]:
    """Solved cell colours at whole-percent steps.

    Each step's lightness is solved so its measured luminance
    lands on the ladder from :func:`_heat_lum_target`, and then
    raised if quantisation left it below the previous step, so
    luminance never falls as the value rises. Values too close
    to separate within 8-bit colour share a step's brightness
    rather than inverting.
    """
    global _HEAT_TABLE
    if _HEAT_TABLE is not None:
        return _HEAT_TABLE
    table: list[tuple[int, int, int]] = []
    prev_lum = -1.0
    for i in range(101):
        v = i / 100.0
        t = min(v / 0.9, 1.0)
        h = (155 - 151 * t) / 360.0
        target = _heat_lum_target(v)
        lo_l, hi_l = 0.0, 1.0
        rgb = (0, 0, 0)
        light = 0.0
        for _ in range(40):
            light = (lo_l + hi_l) / 2.0
            r, g, b = colorsys.hls_to_rgb(h, light, 0.72)
            rgb = (int(r * 255), int(g * 255), int(b * 255))
            if _rel_luminance(rgb) < target:
                lo_l = light
            else:
                hi_l = light
        while _rel_luminance(rgb) < prev_lum and light < 1.0:
            light = min(1.0, light + 0.002)
            r, g, b = colorsys.hls_to_rgb(h, light, 0.72)
            rgb = (int(r * 255), int(g * 255), int(b * 255))
        prev_lum = _rel_luminance(rgb)
        table.append(rgb)
    _HEAT_TABLE = table
    return table


def _heat_rgb(v: float) -> tuple[str, tuple[int, int, int]]:
    """Heatmap cell colour for an ASR, dark green to scorched red.

    Hue rotates from green to red across the scale while the
    lightness follows the solved ladder in :func:`_heat_table`,
    so brightness order is value order. Returns the CSS colour
    and the RGB tuple the cell text colour is chosen from.
    """
    table = _heat_table()
    idx = int(round(min(max(v, 0.0), 1.0) * 100))
    rgb = table[idx]
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", rgb


def _heat_fg(rgb: tuple[int, int, int]) -> str:
    """Cell text colour, black or white, whichever contrasts
    better against this cell's ground. With pure black and white
    the two AA passing ranges overlap, so a passing choice exists
    at every luminance on the ladder."""
    y = _rel_luminance(rgb)
    dark = _contrast(y, _rel_luminance(_HEAT_FG_DARK))
    light = _contrast(y, _rel_luminance(_HEAT_FG_LIGHT))
    if dark >= light:
        return "#000000"
    return "#ffffff"


def _heat_legend() -> str:
    """A compact colour scale for the heatmap, drawn from the
    same solved colours the cells use."""
    # Stops at every whole point, the same steps the cells
    # take, so the gradient follows the solved path exactly
    # instead of cutting across it between anchors.
    stops = ", ".join(
        f"{_heat_rgb(v)[0]} {v * 100:.0f}%"
        for v in [i / 100 for i in range(101)])
    return (
        '<div class="heat-legend" aria-hidden="true"><span>ASR</span>'
        "<span>0%</span>"
        f'<span class="hl-bar" style="background:'
        f'linear-gradient(90deg, {stops})"></span>'
        "<span>100%</span></div>")


def _pts(v: Any) -> str:
    """A rate as points at one decimal, rounded half up on the
    stored decimal value. Robustness tax is defined in points,
    so it prints in points rather than as a percent."""
    n = _num(v)
    if n is None:
        return "n/a"
    d = _quantize(Decimal(str(n)) * 100, Decimal("0.1"))
    if d == 0:
        d = abs(d)
    if d != 0 and d.adjusted() >= 12:
        return _pow_form(d) + " pts"
    return f"{d} pts"


def _ci_pair(ci: Any) -> tuple[float, float] | None:
    if isinstance(ci, (list, tuple)) and len(ci) == 2:
        lo, hi = _num(ci[0]), _num(ci[1])
        if lo is not None and hi is not None and lo <= hi:
            return (lo, hi)
    return None


def _tied_bands(entries: list[dict[str, Any]]) -> dict[int, tuple[int, int]]:
    """Rank bands of ranked rows whose intervals overlap.

    Returns row id to (lowest rank, highest rank) for every
    ranked row that belongs to a band of two or more ranked
    rows. A band is a run of consecutive ranks whose
    intervals share a common intersection, built greedily in
    rank order: a row joins the open band only while its
    interval still crosses the intersection of every
    interval already in it. The page's wording claims the
    band's intervals overlap, full stop, and that claim has
    to be true of the whole band: the union-find chaining
    this replaced linked A to C through B whenever A
    overlapped B and B overlapped C, so a band could print
    "tied" over endpoints whose own intervals were disjoint
    and whose whiskers visibly never touched (pass 23).
    The greedy partition keeps every printed band mutually
    overlapping; on a chain whose middle links hold but
    whose ends part, the band closes where the common
    intersection empties and a new band opens.
    """
    ranked = [e for e in entries if e["rank"] is not None]
    out: dict[int, tuple[int, int]] = {}
    band: list[dict[str, Any]] = []
    band_lo = band_hi = 0.0

    def close() -> None:
        if len(band) >= 2:
            ranks = [e["rank"] for e in band]
            rng = (min(ranks), max(ranks))
            for e in band:
                out[id(e["row"])] = rng

    for e in ranked:
        pair = _ci_pair(e["row"].get("asr_ci95")) \
            if _num(e["row"].get("asr_conditional")) is not None \
            else None
        if pair is None:
            # A ranked row with no interval (or no rate) is
            # not a band member, and it breaks the run: a band
            # spanning it would print a rank range whose span
            # claims an interval the page does not carry, and
            # a clause counting "the top N intervals" over two
            # (pass 25).
            close()
            band = []
            continue
        lo, hi = pair
        if band and (lo > band_hi or band_lo > hi):
            close()
            band = []
        if band:
            band_lo = max(band_lo, lo)
            band_hi = min(band_hi, hi)
        else:
            band_lo, band_hi = lo, hi
        band.append(e)
    close()
    return out


# ---------------------------------------------------------------- tiles

def _kpi_tiles(entries: list[dict[str, Any]],
               n_cases: Any) -> str:
    """Big-number tiles across the top of the dashboard.

    Every tile is computed from the payload. A tile whose figure the
    payload does not carry is left out rather than printed hollow.
    """
    def nb(text: str) -> str:
        # Tile labels are HTML built from escaped parts. A name or
        # a range wrapped here cannot be split across lines at its
        # hyphens on narrow tiles.
        return f'<span class="nb">{_esc(text)}</span>'

    def nbw(text: str) -> str:
        # An endpoint name in a tile label: unbreakable as a
        # whole it can be wider than the tile itself (a capped
        # 40 character name runs about 330px against a half
        # width phone tile's 141), so it sits in a span allowed
        # to wrap within itself instead of clipping at the
        # screen edge, while staying one unit at widths that
        # hold it (pass 18). A short hyphenated name is the
        # exception: it fits whole in every tile that carries
        # it, yet the wrap-within-itself span let the widest
        # tile's label break GLM-4-PLUS after its first hyphen
        # while every sibling label wrapped at word boundaries
        # (pass 34), so a name of at most 18 characters with a
        # hyphen and no space takes the nowrap class and can
        # only move to its own line whole.
        cls = ("nbw nbw-s" if "-" in text and " " not in text
               and len(text) <= 18 else "nbw")
        return f'<span class="{cls}">{_esc(text)}</span>'

    def _lab(html: str) -> str:
        # A separator never opens a wrapped line of a tile label:
        # it stays glued to the word before it, so the break
        # falls after the separator, not before it.
        return html.replace(" · ", "&nbsp;· ")

    def _model_key(row: dict[str, Any]) -> Any:
        # The key a row groups under when the tiles count
        # models: its model ID (adapter_version). A model ID is
        # a string. A value of another type is a malformed
        # identity: keyed apart under its repr, so it can
        # neither raise here nor merge with the model its text
        # resembles.
        v = row.get("adapter_version")
        if v is not None and not isinstance(v, str):
            return ("malformed model id", repr(v))
        return v

    # The tile counts models, and an entry is not a model. An
    # entry is one model measured over one wire (Admission-Rules,
    # Model identity), and one model can carry two entries, as
    # gpt-6-luna does over its chat and decisions wires. Grouping
    # the entries by model ID (adapter_version) and classifying
    # each model once keeps the headline and its split counting
    # the same thing, so the split sums to the headline. A model
    # is ranked when any of its entries holds a rank; among
    # ranked models it stands in the recorded-ASR class when any
    # ranked entry carries a rate, and in the without-a-recorded-
    # ASR class when none does. A model with no ranked entry is
    # flagged. When no two entries share a model ID, every count
    # here is the entry count it replaces.
    _by_model: dict[Any, list[dict[str, Any]]] = {}
    for e in entries:
        _by_model.setdefault(_model_key(e["row"]), []).append(e)
    n_models = len(_by_model)
    n_flagged = 0
    n_ranked_asr = 0
    n_ranked_bare = 0
    for _model_entries in _by_model.values():
        _ranked = [e for e in _model_entries
                   if e["rank"] is not None]
        if not _ranked:
            n_flagged += 1
        elif any(_num(e["row"].get("asr_conditional")) is not None
                 for e in _ranked):
            n_ranked_asr += 1
        else:
            n_ranked_bare += 1
    models_lab = "MODELS TESTED"
    if n_flagged or n_ranked_bare:
        # The split of the field is headline information, stated
        # on the tile itself rather than left to captions below.
        # It prints whenever any model is flagged, an all-flagged
        # field included: "0 RANKED · N FLAGGED" is exactly the
        # case a bare count would misdescribe (pass 18). The
        # ranked class counts the models whose ranked entries
        # carry a rate. The card chips count ranked entries
        # instead, the measurement-level field, and Admission-
        # Rules states the two conventions apart so the counts
        # are never read as one quantity: a ranked run with no
        # recorded rate holds no rank anywhere on the page, and
        # folding its model into the ranked class here under the
        # same word would restate the confusion the passes
        # removed (passes 26, 27 and 30; the passes 18 and 22
        # adjudication settled the denominators, not the shared
        # word). Such a model is stated as its own line of the
        # split instead.
        models_lab += f" · {n_ranked_asr} RANKED"
        if n_ranked_bare:
            models_lab += (f" · {n_ranked_bare} RANKED WITHOUT "
                           "A RECORDED ASR")
        if n_flagged:
            models_lab += f" · {n_flagged} FLAGGED"
    tiles: list[tuple[str, str, str]] = [
        (str(n_models), models_lab, "")]
    if _num(n_cases) is not None:
        # The case count is not the base of any rate on the page,
        # so the tile itself carries the eligible range the rates
        # actually rest on.
        elig = [v for e in entries
                for v in [_num(e["row"].get("n_eligible"))]
                if v is not None]
        lab = "PAIRED CASES EACH"
        if elig:
            # A range whose ends agree is one figure, stated
            # once, the same rule the cost tile applies to a
            # single distinct cost (pass 25).
            span = (_int(min(elig)) if min(elig) == max(elig)
                    else f"{_int(min(elig))}–{_int(max(elig))}")
            lab += f" · ELIGIBLE {nb(span)}"
        tiles.append((_int(n_cases), lab, ""))
    ranked = [e for e in entries if e["rank"] is not None
              and _num(e["row"].get("asr_conditional")) is not None]
    if ranked:
        ordered = sorted(
            ranked,
            key=lambda e: _num(e["row"].get("asr_conditional")) or 0.0)
        best = ordered[0]
        label = "LOWEST ASR · " + nbw(_tile_name(best))
        value = _pct_asr(best["row"].get("asr_conditional"))
        cls = ""
        bands = _tied_bands(entries)
        lead_band = next(
            (b for b in set(bands.values()) if b[0] == 1), None)
        tied = [e for e in ordered
                if lead_band is not None
                and bands.get(id(e["row"])) == lead_band]
        if len(tied) >= 2:
            # The lead is inside the intervals, so the tile says so
            # instead of crowning a sole winner, and the big number
            # becomes the tied group's range so the tile alone never
            # states one model's figure for the group.
            if len(tied) == 2:
                label = ("LEAD BAND · "
                         + nbw(_tile_name(tied[0]))
                         + " AND "
                         + nbw(_tile_name(tied[1]))
                         + " TIED")
            else:
                # The count is of models, as the word says: the
                # band holds entries, and one model can hold two
                # of its slots over two wires, so the entries are
                # grouped under the same model key the first tile
                # counts by. When no model in the band repeats,
                # the count is the entry count it replaces.
                n_tied_models = len({_model_key(e["row"])
                                     for e in tied})
                label = (f"LEAD BAND · {n_tied_models} MODELS "
                         "TIED AT THE TOP")
            # The unit rides on the end of the range, as the
            # retrieval tile's range does, which also keeps the
            # figure narrow enough for the larger tile type.
            value = (f"{_pct_asr(tied[0]['row'].get('asr_conditional'))[:-1]}"
                     f"–{_pct_asr(tied[-1]['row'].get('asr_conditional'))}")
            cls = " range"
        # The lead this tile states is the ranked lead. A
        # flagged run sitting at or inside the lead's rates
        # beats or matches it in the hero's own order, and a
        # tile that drops it in silence states a superlative
        # the field does not hold, in the one row of the page
        # built to be cropped and quoted alone. The strongest
        # such run is named with its figure and its flag, the
        # attribution the retrieval tile gives its low end
        # (pass 22).
        lead_top = (tied[-1] if len(tied) >= 2 else best)
        lead_top_v = _num(lead_top["row"].get("asr_conditional"))
        contenders = [
            e for e in entries
            if e["rank"] is None
            and _num(e["row"].get("asr_conditional")) is not None
            and lead_top_v is not None
            and _num(e["row"].get("asr_conditional")) <= lead_top_v]
        if contenders:
            foe = min(
                contenders,
                key=lambda e: _num(e["row"].get("asr_conditional")))
            label += (f" · FLAGGED {nbw(_tile_name(foe))} AT "
                      f"{_pct_asr(foe['row'].get('asr_conditional'))}"
                      " · NO&nbsp;RANK")
        tiles.append((value, label, cls))
    rp = []
    for e in entries:
        f = _family_map(e["row"]).get("retrieval_poisoning")
        v = _fam_rate(f) if f is not None else None
        if v is not None:
            rp.append((v, e))
    if rp:
        label = "RETRIEVAL POISONING ASR RANGE"
        vals = sorted(v for v, _e in rp)
        # When some models do not carry the family at all, the
        # tile says how many do, so its range is never read as
        # a field-wide figure resting on a subset (pass 18).
        # The count is of models, as the word says: a model
        # carrying the family on two wires counts once, over
        # the distinct-model count the first tile prints. When
        # no two entries share a model ID the two figures are
        # the entry counts they replace.
        n_carry = len({_model_key(e["row"]) for _v, e in rp})
        carry = (f" · {n_carry} OF {n_models} MODELS"
                 if n_carry < n_models else "")
        if vals[0] == vals[-1]:
            # A single distinct value is not a range, the same
            # special case the cost tile makes: print the one
            # figure, and when a flagged run is among its
            # carriers the tile says so rather than letting a
            # flagged model's value pose as the field's
            # (pass 15). NO RANK is set with a no-break space
            # inside it from here on: bound as one unit it can
            # never orphan its second word onto a line of its
            # own at narrow widths (pass 18).
            label = "RETRIEVAL POISONING ASR"
            _nflag = sum(1 for _v, e in rp if e["rank"] is None)
            if _nflag == len(rp):
                label += " · FLAGGED · NO&nbsp;RANK"
            elif _nflag:
                # A value carried by both statuses is neither
                # status's alone: the spread forms name their
                # endpoints and mark the flagged ones, and the
                # single-value form counts its flagged
                # carriers instead of stating one status for
                # a figure two statuses share (pass 22).
                label += (f" · {_nflag} OF {len(rp)} CARRIERS "
                          "FLAGGED")
            tiles.append((_pct(vals[0]), label + carry, " span3"))
            rp = []
    if rp:
        attributed = False
        if len(vals) >= 3:
            lo_e = next(e for v, e in rp if v == vals[0])
            # An isolated low endpoint gets attributed, with its
            # own figure beside its name, so the range cannot read
            # as a spread the field actually shows and the quote
            # cannot travel without the absolute value.
            if (lo_e["rank"] is None
                    and vals[1] - vals[0] > 0.05
                    and vals[1] - vals[0] > vals[-1] - vals[1]):
                # The attribution frames the endpoint as the
                # range's low end and names the flag's cost
                # both ways, so a cropped KPI row cannot crown
                # a flagged model with a superlative (passes
                # 14 and 15).
                label = ("RETRIEVAL POISONING · LOW END IS FLAGGED "
                         + nbw(_tile_name(lo_e))
                         + f" AT {_pct(vals[0])} · NO&nbsp;RANK")
                attributed = True
        # Flag marks are properties of the endpoints and of the
        # carrier set, never of whichever carrier happens to be
        # listed first (pass 18). The all-flagged mark survives
        # the attribution form: an attributed low end must not
        # leave the range's high figure posing as an unmarked
        # field maximum when it belongs to a flagged run too.
        all_flag = all(e["rank"] is None for _v, e in rp)
        lo_flag = any(e["rank"] is None for v, e in rp
                      if v == vals[0])
        hi_flag = any(e["rank"] is None for v, e in rp
                      if v == vals[-1])
        if attributed:
            if all_flag:
                label += " · ALL CARRIERS FLAGGED"
            elif hi_flag:
                label += " · HIGH END IS FLAGGED · NO&nbsp;RANK"
        elif all_flag:
            # Every carrier of the range is flagged: the tile
            # marks it, as the single-value form marks any
            # flagged carrier, rather than letting flagged
            # figures pose as the field's unmarked range
            # (pass 17).
            label += " · FLAGGED · NO&nbsp;RANK"
        elif lo_flag and hi_flag:
            label += " · BOTH ENDS ARE FLAGGED · NO&nbsp;RANK"
        elif lo_flag:
            label += " · LOW END IS FLAGGED · NO&nbsp;RANK"
        elif hi_flag:
            label += " · HIGH END IS FLAGGED · NO&nbsp;RANK"
        # One decimal, the precision labels use everywhere; the
        # unit rides on the end of the range, as the lead tile's
        # range carries it.
        tiles.append((
            f"{_pct(vals[0])[:-1]}–{_pct(vals[-1])}", label + carry,
            " span3"))
    # Only a positive cost is a recorded cost, the same rule
    # the scatter's log axis applies: a zero or negative figure
    # is not a price and must not pose as the spread's endpoint.
    cost_entries = [(v, e) for e in entries
                    for v in [_num(e["row"].get("total_cost_usd"))]
                    if v is not None and v > 0]
    if cost_entries:
        costs = [v for v, _e in cost_entries]
        label = "COST SPREAD PER RUN"
        top_e = next(e for v, e in cost_entries if v == max(costs))

        def _tile_money(v: float, digits: int = 2,
                        bound: bool = False) -> str:
            # The tile prints money through the same separating
            # formatter as the cards, so a seven figure cost
            # groups its thousands here too, and a value that
            # rounds to zero drops its sign the way every
            # formatter on the page does (pass 18). A
            # lower-bound endpoint floors at its precision,
            # like the cards and the scatter description, so
            # the tile never states a floor above the
            # recorded figure (pass 38).
            dv = Decimal(str(v))
            if dv != 0 and dv.adjusted() >= 12:
                return "$" + _pow_form(dv)
            if bound:
                d = dv.quantize(Decimal(1).scaleb(-digits),
                                rounding=ROUND_FLOOR)
                # The floored figure still has to show: at
                # the caller's precision a sub-cent bound
                # floors to zero, the free-run figure its
                # card contradicts (passes 23 and 38).
                while d == 0 and dv != 0 and digits < 30:
                    digits += 1
                    d = dv.quantize(
                        Decimal(1).scaleb(-digits),
                        rounding=ROUND_FLOOR)
            else:
                d = _quantize(dv, Decimal(1).scaleb(-digits))
            if d == 0:
                d = abs(d)
            return f"${d:,.{digits}f}"

        # A lower-bound mark belongs to the endpoint it
        # describes. An endpoint whose calls all priced is
        # exact, and a blanket mark would misstate it the
        # other way, so each endpoint carries its own mark,
        # or none. The mark is a property of the endpoint
        # value: when two runs share an endpoint's cost and
        # either one's calls went unpriced, the figure at
        # that end is a floor for the runs sitting there,
        # and deciding the mark from whichever run happens
        # to be listed first let a lower-bound endpoint go
        # unmarked (pass 15).
        lo_v, hi_v = min(costs), max(costs)
        lo_lb = any(_has_unpriced_calls(e["row"])
                    for v, e in cost_entries if v == lo_v)
        hi_lb = any(_has_unpriced_calls(e["row"])
                    for v, e in cost_entries if v == hi_v)

        def _lbm(lb: bool) -> str:
            return " (LOWER BOUND)" if lb else ""

        # The floor mark rides in the numeral itself, not
        # only in the small label under it: the numeral is
        # the loudest type on the page, and a qualifier
        # confined to the label let a crop of the tile row
        # state a floor as a measured cost (pass 16). Each
        # endpoint carries its own mark, on the same
        # per-value rule as the label.
        def _ge(lb: bool) -> str:
            return "≥" if lb else ""

        # Flag marks are properties of the endpoint values,
        # on the same any-carrier rule as the lower-bound
        # marks: a flagged run sharing an endpoint's cost
        # marks that endpoint even when another run is the
        # one named there, and a flagged run named as an
        # endpoint carries its flag in the label rather than
        # posing as an unmarked end of the spread (pass 18).
        lo_flag = any(e["rank"] is None
                      for v, e in cost_entries if v == lo_v)
        hi_flag = any(e["rank"] is None
                      for v, e in cost_entries if v == hi_v)

        def _num_cls(num: str) -> str:
            # The wide tile's numeral is set in the tile's
            # large type, where a long spread figure runs
            # wider than the tile itself (the base spread
            # overflows by about 5px at desktop width). Long
            # numerals step down a class rather than clip
            # (pass 18).
            if len(num) > 30:
                return " wide vxlong"
            if len(num) > 22:
                return " wide vlong"
            if len(num) > 14:
                return " wide vmid"
            return " wide"

        if lo_v == hi_v:
            # A single shared cost prints at the precision
            # that shows it: a sub-cent cost is a real figure,
            # not the free run "$0.00" would claim. The loop
            # tests the rounded value, not its string: at
            # three decimals the string differs from "$0.00"
            # while the figure is still zero, and exiting
            # there printed "$0.000" for a positive cost
            # (passes 18 and 22).
            digits = _showing_digits(Decimal(str(costs[0])))
            num = f"{_ge(lo_lb)}{_tile_money(costs[0], digits, bound=lo_lb)}"
            lab1 = "COST PER RUN" + _lbm(lo_lb)
            _nflag = sum(1 for _v, e in cost_entries
                         if e["rank"] is None)
            if _nflag == len(cost_entries):
                lab1 += " · FLAGGED · NO&nbsp;RANK"
            elif _nflag:
                # One figure, two statuses among its
                # carriers: the label counts the flagged
                # carriers rather than stating one status
                # for a figure both share (pass 22).
                lab1 += (f" · {_nflag} OF {len(cost_entries)} "
                         "CARRIERS FLAGGED")
            tiles.append((num, lab1, _num_cls(num)))
        else:
            # The spread's endpoints are two identifiable
            # runs, and the label names them, as the retrieval
            # tile names its low endpoint. The named run at
            # each end is a lower-bound one when the value
            # has one, so the name and its mark never describe
            # different runs. The names print in whichever
            # branch the endpoints' flags dictate: a flagged
            # top no longer replaces the whole label and takes
            # the low end's name and marks down with it
            # (passes 15 and 18).
            lo_e = next(
                (e for v, e in cost_entries
                 if v == lo_v and _has_unpriced_calls(e["row"])),
                next(e for v, e in cost_entries if v == lo_v))
            top_named = next(
                (e for v, e in cost_entries
                 if v == hi_v and _has_unpriced_calls(e["row"])),
                top_e)
            label = ("COST SPREAD PER RUN · "
                     + nbw(_tile_name(lo_e) + _lbm(lo_lb))
                     + " TO "
                     + nbw(_tile_name(top_named) + _lbm(hi_lb)))
            if hi_flag:
                label += " · TOP COST IS FLAGGED"
            if lo_flag:
                label += " · LOW END IS FLAGGED"
            # Each end prints at the precision its own
            # figure needs, the precision its card uses: the
            # shared-precision search this replaces stopped
            # where the ends separate, and beside a normal
            # high end a sub-cent low end separates at two
            # places already, so it printed as $0.00 while
            # its card and the scatter description printed
            # $0.004 (pass 23). Only when the ends still
            # collide at their own precisions (a spread
            # narrower than a cent, whose ends are distinct
            # figures one figure stated twice would falsify)
            # do both rise together until they separate, the
            # search running to the shared cap: a six-decimal
            # cap stated two distinct ends (0.1234561 and
            # 0.1234564) as one figure twice (passes 18
            # and 22).
            lo_d = _showing_digits(Decimal(str(lo_v)))
            hi_d = _showing_digits(Decimal(str(hi_v)))
            if _tile_money(lo_v, lo_d, bound=lo_lb) == \
                    _tile_money(hi_v, hi_d, bound=hi_lb):
                lo_d = hi_d = max(lo_d, hi_d)
                while lo_d < 30 and \
                        _tile_money(lo_v, lo_d, bound=lo_lb) == \
                        _tile_money(hi_v, hi_d, bound=hi_lb):
                    lo_d += 1
                    hi_d += 1
            # A marked endpoint breaks the dash: "≥$0.20–$21.02"
            # lets a glance read the floor mark as covering the
            # whole range, the exact top figure included. With a
            # word between the figures the mark binds the figure
            # it touches (pass 17). Unmarked spreads keep the
            # dash every other tile range uses.
            sep = " to " if (lo_lb or hi_lb) else "–"
            num = (f"{_ge(lo_lb)}{_tile_money(lo_v, lo_d, bound=lo_lb)}{sep}"
                   f"{_ge(hi_lb)}{_tile_money(hi_v, hi_d, bound=hi_lb)}")
            tiles.append((num, label, _num_cls(num)))
    return "".join(
        f'<div class="kpi{cls}"><div class="kpi-num">{_esc(v)}</div>'
        f'<div class="kpi-lab">{_lab(lab)}</div></div>'
        for v, lab, cls in tiles)


# ---------------------------------------------------------------- hero

def _hero_scale(entries: list[dict[str, Any]]) -> float:
    """X axis maximum for the ranking chart.

    The approved design fixes the scale at 30 percent, which keeps
    renders comparable across payloads. Data past the line extends
    the axis in 5 point steps rather than overflowing the plot.
    """
    top = 0.0
    for entry in entries:
        r = entry["row"]
        pair = _ci_pair(r.get("asr_ci95"))
        if pair is not None:
            top = max(top, pair[1])
        v = _num(r.get("asr_conditional"))
        if v is not None:
            top = max(top, v)
    if top <= 0.30:
        return 0.30
    # The axis is a scale device and stops growing at 1000
    # percent: past that the data is degenerate, and an uncapped
    # ceiling would overflow the float range before it could
    # produce a page at all. The values themselves still print
    # in full on the cards.
    if top > 10.0:
        return 10.0
    return math.ceil(top / 0.05) * 0.05


def _hero_svg(entries: list[dict[str, Any]], xmax: float) -> str:
    """Ranking chart for every model, the dashboard's centrepiece.

    Green bars are ranked models. Amber hatched bars are flagged
    models, which carry no rank, with their malformed rate
    printed beside the bar. Every bar carries a 95 percent
    confidence whisker and its rate at the bar end.
    """
    shown = [e for e in entries
             if _num(e["row"].get("asr_conditional")) is not None]
    if not shown:
        return '<p class="muted">No ranked models with ASR data.</p>'
    # The viewBox runs wider than the plot so the flagged rows'
    # "no rank · malformed" annotation clears the right edge even
    # on the longest bar.
    W = 1220
    x0, x1 = 268, 1010

    def hx(v: float) -> float:
        return x0 + (v / xmax) * (x1 - x0)

    def hcap(v: float) -> float:
        # A value's position on the axis, clamped at both ends.
        # Corrupt geometry (past the cap, or not a number) lands
        # on the boundary instead of writing inf or nan into
        # the SVG. The text beside the bar still prints the
        # value itself in full.
        if v != v:
            return 0.0
        return min(max(v, 0.0), xmax)

    grid_bottom = 34 + (len(shown) - 1) * 36 + 22
    bands = _tied_bands(shown)
    desc_rows = []
    for e in shown:
        r = e["row"]
        status = (f"rank {e['rank']}" if e["rank"] is not None
                  else "flagged no rank")
        pair = _row_ci(r)
        ci_txt = (f" 95% CI {_pct_asr(pair[0])} to {_pct_asr(pair[1])}"
                  if pair is not None else "")
        band = bands.get(id(r))
        if band is not None:
            status += f", tied band {band[0]} to {band[1]}"
        mal = ""
        if _num(r.get("malformed_rate")) is not None:
            mal = f", malformed {_pct_malf(r.get('malformed_rate'))}"
        desc_rows.append(
            f"{_entry_short(e)} "
            f"{_pct_asr(r.get('asr_conditional'))}{ci_txt} {status}{mal}")
    tie_note = ""
    for lo, hi in sorted(set(bands.values())):
        if lo == 1 and hi == 2:
            tie_note += " The top two intervals overlap, a tie."
        elif lo == 1:
            tie_note += f" The top {hi} intervals overlap, a tie."
        else:
            tie_note += f" Ranks {lo} to {hi} overlap, a tie."
    desc = ("Bars in attack success order." + tie_note + " "
            + ". ".join(desc_rows) + ".")
    # The name slot ends where the bar begins, and the bar
    # paints after the name: a name longer than the slot
    # (about 26 characters at this size) lost its tail under
    # the bar, so two names differing past the slot printed
    # identically here while the description above and the
    # cards carried them whole. The painted names are
    # fitted to the slot and disambiguated at that width;
    # the description keeps the full short name (pass 23).
    painted = _fit_names(shown, [26] * len(shown))
    parts = [
        f'<svg viewBox="0 0 {W} {grid_bottom + 32}" class="chart hero-svg" '
        'role="img" aria-labelledby="hero-t hero-d">'
        '<title id="hero-t">Model ranking by attack success rate</title>'
        f'<desc id="hero-d">{_esc(desc)}</desc>'
        '<defs><pattern id="hatch" width="7" height="7" '
        'patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
        '<rect width="7" height="7" fill="#2a2118"/>'
        # The stripe is drawn at both tile edges: a single line
        # centred on the edge paints only its inner half inside
        # this tile, halving the amber duty the source width
        # promises (a pixel measurement in pass 17 found 17%
        # painted against the phone form's 34%). The two edge
        # lines together paint the full 2.4 of 7, the same duty
        # the phone gradient lays down.
        '<line x1="0" y1="0" x2="0" y2="7" stroke="#e8a33d" '
        'stroke-width="2.4"/>'
        '<line x1="7" y1="0" x2="7" y2="7" stroke="#e8a33d" '
        'stroke-width="2.4"/></pattern></defs>',
        # The panel carries its own reading direction and the
        # hatch meaning, so a crop of the panel alone cannot
        # be read backwards (longer is worse here, and the
        # hatched bars are the ones the malformed gate kept
        # off the ranking).
        f'<text x="{W - 14}" y="16" text-anchor="end" '
        'class="h-axis">lower is stronger · hatched bars '
        'carry no rank</text>']
    # The gridline step coarsens as the scale grows, so the
    # line count stays bounded however far the data extends
    # the axis.
    gstep = 0.05
    while xmax / gstep > 24:
        gstep *= 2
    steps = int(round(xmax / gstep))
    for i in range(steps + 1):
        gv = i * gstep
        tx = hx(gv)
        parts.append(
            f'<line x1="{tx:.1f}" y1="22" x2="{tx:.1f}" '
            f'y2="{grid_bottom}" stroke="#232c35" stroke-width="1"/>'
            f'<text x="{tx:.1f}" y="{grid_bottom + 16}" class="h-axis" '
            f'text-anchor="middle">{gv * 100:.0f}%</text>')
    for i, entry in enumerate(shown):
        r = entry["row"]
        y = 34 + i * 36
        cy = y + 9
        asr = _num(r.get("asr_conditional")) or 0.0
        pair = _row_ci(r)
        lo, hi = pair if pair is not None else (asr, asr)
        # Geometry clamps at the axis origin: a negative rate
        # (corrupt data, but data the page still prints in text)
        # has no length on a zero-based axis, and an unclamped
        # width would be invalid markup that drops the bar.
        gasr, glo, ghi = hcap(asr), hcap(lo), hcap(hi)
        flagged = entry["rank"] is None
        rank_txt = str(entry["rank"]) if not flagged else "•"
        parts.append(
            f'<text x="34" y="{cy + 5}" class="h-rank'
            f'{" flag" if flagged else ""}">{rank_txt}</text>')
        parts.append(
            f'<text x="64" y="{cy + 5}" class="h-name'
            f'{" flag" if flagged else ""}">'
            f'{_esc(painted[i])}</text>')
        if flagged:
            parts.append(
                f'<rect x="{x0}" y="{y}" width="{hx(gasr) - x0:.1f}" '
                'height="18" rx="2" fill="url(#hatch)" stroke="#e8a33d" '
                'stroke-width="1.2"/>')
        else:
            parts.append(
                f'<rect x="{x0}" y="{y}" width="{hx(gasr) - x0:.1f}" '
                'height="18" rx="2" fill="#2fbf71"/>')
        # The whisker is drawn twice, a wide dark pass under a
        # bright one, so the segment crossing the solid bar stays
        # visible instead of washing out against the green. A row
        # with no recorded interval gets no whisker at all, never
        # a zero-width one at its own value.
        for stroke, width in ((("#0b0e11", "4.5"), ("#aebcc7", "2"))
                              if pair is not None else ()):
            parts.append(
                f'<line x1="{hx(glo):.1f}" y1="{cy}" x2="{hx(ghi):.1f}" '
                f'y2="{cy}" stroke="{stroke}" stroke-width="{width}"/>'
                f'<line x1="{hx(glo):.1f}" y1="{cy - 5}" x2="{hx(glo):.1f}" '
                f'y2="{cy + 5}" stroke="{stroke}" stroke-width="{width}"/>'
                f'<line x1="{hx(ghi):.1f}" y1="{cy - 5}" x2="{hx(ghi):.1f}" '
                f'y2="{cy + 5}" stroke="{stroke}" stroke-width="{width}"/>')
        parts.append(
            f'<text x="{hx(ghi) + 12:.1f}" y="{cy + 5}" class="h-val'
            f'{" flag" if flagged else ""}">{_pct_asr(asr)}</text>')
        if _num(r.get("malformed_rate")) is not None:
            # Every row prints its malformed rate, not only the
            # flagged ones, so a ranked row never reads as clean
            # by omission. The figure's colour keys on its value
            # here as on every malformed surface: over the gate
            # it takes the amber, at or under it the quiet grey,
            # for flagged and ranked rows alike, so a row flagged
            # for another reason never shows an under-gate rate
            # in alarm colour, and a ranked row over the gate
            # never hides in grey (pass 18).
            mv = _num(r.get("malformed_rate")) or 0.0
            mcls = "h-malf" if mv > 0.05 else "h-malf ok"
            if flagged:
                ann = f"no rank · malformed {_pct_malf(mv)}"
            else:
                band = bands.get(id(r))
                tie_txt = (f" · tied {band[0]}–{band[1]}"
                           if band is not None else "")
                ann = f"malformed {_pct_malf(mv)}{tie_txt}"
            ax = hx(ghi) + 72
            # The annotation starts past the whisker, and a row
            # whose interval ends near the scale top would run
            # its text, tie qualifier included, past the right
            # edge, where a standalone crop of the panel cuts
            # it away: the start clamps so the whole annotation
            # stays on the panel, and a panel-coloured halo
            # keeps it legible where it crosses the bar or the
            # whisker (pass 18). 7.3 units a character is the
            # annotation font's advance, rounded up.
            est = len(ann) * 7.3
            if ax + est > W - 6:
                ax = W - 6 - est
            # The clamp guards the panel's edge, but a clamped
            # annotation can land on the row's own value text,
            # which shares its baseline and carries no halo:
            # where the two spans would meet, the annotation
            # moves to end before the value starts, over the
            # bar its halo keeps it legible against (pass 22).
            vx = hx(ghi) + 12
            vend = vx + len(_pct_asr(asr)) * 9.0 + 4
            if ax < vend and ax + est > vx:
                ax = max(x0, vx - est - 6)
            parts.append(
                f'<text x="{ax:.1f}" y="{cy + 5}" class="{mcls}" '
                'style="paint-order:stroke;stroke:#10141a;'
                f'stroke-width:3px;stroke-linejoin:round">'
                f'{_esc(ann)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _hero_mobile(entries: list[dict[str, Any]], xmax: float) -> str:
    """Phone-native ranking list, the hero chart's small-screen form.

    The desktop chart cannot shrink to phone width and stay legible,
    so small screens get this list instead. Each row prints the
    model, its rank or flag, its rate, a bar and interval track on
    the hero scale, and its interval in text. CSS shows exactly one
    of the two presentations at each width.
    """
    shown = [e for e in entries
             if _num(e["row"].get("asr_conditional")) is not None]
    if not shown:
        return ""
    bands = _tied_bands(shown)
    rows = []
    for entry in shown:
        r = entry["row"]
        asr = _num(r.get("asr_conditional")) or 0.0
        pair = _row_ci(r)
        lo, hi = pair if pair is not None else (asr, asr)
        flagged = entry["rank"] is None
        band = bands.get(id(r))
        rk = f'#{entry["rank"]}' if not flagged else "FLAGGED"
        if band is not None and not flagged:
            # The tie rides on the headline line, beside the
            # rank it qualifies: demoting it to the small
            # line under the bar let a first-viewport phone
            # crop show bare ordinal ranks with the tie out
            # of frame, a coronation the desktop form's
            # same-line wording never permits (pass 16).
            rk += f" · TIED {band[0]}–{band[1]}"
        # A row with no recorded interval says so, in the words
        # the model's card uses, rather than printing its own
        # value as both ends of an invented interval.
        if pair is not None:
            sub = f"95% CI {_pct_asr(lo)} to {_pct_asr(hi)}"
        else:
            sub = "no interval recorded"
        if flagged:
            sub += " · no rank"
        if _num(r.get("malformed_rate")) is not None:
            # The malformed figure's colour keys on its value
            # here too, the same rule as the desktop hero, the
            # strip and the cards: over the gate it takes the
            # amber, whichever flag the row carries, and an
            # under-gate figure on a row flagged for another
            # reason stays quiet (passes 17 and 18).
            mv = _num(r.get("malformed_rate")) or 0.0
            sub += (f' · <span class="nb'
                    f'{" malf-flag" if mv > 0.05 else ""}">malformed '
                    f'{_pct_malf(mv)}</span>')
        # The band is not repeated here: it rides on the
        # headline line (pass 16), and the sub-line carried
        # it too, so one phone row stated the tie twice
        # where every other surface states it once per unit
        # (pass 34). The row still says so, in its headline;
        # the harness checks the row, not the line.
        ci_box = ""
        if pair is not None:
            # Geometry clamps to the track at both ends, as in
            # the desktop chart: a bound outside the scale has
            # no position on the track, and the text line still
            # prints it in full.
            glo = 0.0 if lo != lo else min(max(lo, 0.0), xmax)
            ghi = 0.0 if hi != hi else min(max(hi, 0.0), xmax)
            ci_box = (
                f'<div class="mb-ci" style="left:{glo / xmax * 100:.1f}%;'
                f'width:{(ghi - glo) / xmax * 100:.1f}%"></div>')
        rows.append(
            '<div class="mb-row"><div class="mb-top">'
            # A flagged row's name and rate take the flag colour
            # the stylesheet already defines for this form, the
            # same status channel the desktop hero paints; the
            # name wraps rather than ellipsising, so two models
            # sharing a long prefix stay two distinguishable
            # rows (pass 18).
            f'<span class="mb-name{" flag" if flagged else ""}">'
            f'{_esc(_entry_short(entry))}</span>'
            f'<span class="mb-rk{" flag" if flagged else ""}">{rk}</span>'
            f'<span class="mb-val{" flag" if flagged else ""}">'
            f'{_pct_asr(asr)}</span></div>'
            '<div class="mb-track">'
            f'{ci_box}'
            f'<div class="mb-bar{" flag" if flagged else ""}" '
            f'style="width:{(0.0 if asr != asr else min(max(asr, 0.0), xmax)) / xmax * 100:.1f}%"></div></div>'
            f'<div class="mb-sub">{sub}</div></div>')
    # The track scale is stated on the mobile form too. The
    # desktop chart carries axis ticks; this list has no axis, so
    # without the line a bar filling half its track invites a
    # 50 percent reading of a 15 percent value.
    scale = (f'<div class="mb-scale">Bars run 0% to '
             f"{xmax * 100:.0f}% · lower is stronger</div>")
    return '<div class="hero-mobile">' + scale + "".join(rows) + "</div>"


# ---------------------------------------------------------------- heatmap

def _family_impact_order(entries: list[dict[str, Any]],
                         fam_order: list[str]) -> list[str]:
    """Attack families by mean ASR across the page's models,
    highest first; equal means keep payload order, and a family
    no model carries a value for keeps its payload place at the
    tail.

    The phone heatmap leads with this order, so the families
    with the highest rates are inside its first viewport
    instead of behind a sideways scroll.
    """
    means: dict[str, float | None] = {}
    for f in fam_order:
        vals = []
        for e in entries:
            fam = _family_map(e["row"]).get(f)
            v = _fam_rate(fam) if fam is not None else None
            if v is not None:
                vals.append(v)
        means[f] = sum(vals) / len(vals) if vals else None
    return sorted(
        fam_order,
        key=lambda f: (means[f] is None, -(means[f] or 0.0)))


def _heat_table_html(entries: list[dict[str, Any]],
                     col_order: list[str],
                     caption_cols: str,
                     fam_order: list[str] | None = None) -> str:
    """One heatmap table over the given column order.

    One row per model in page order. Cell colour runs dark green
    to scorched red with the value; a family a model lacks
    prints n/a. Display names resolve against the canonical
    family order, so a disambiguating suffix means the same
    family on both table forms.
    """
    disp = _fam_display(fam_order or col_order)
    head = "".join(
        f'<th scope="col" '
        f'class="{"hot-col" if f == "retrieval_poisoning" else ""}">'
        f"{_esc(disp[f])}</th>" for f in col_order)
    body = []
    for entry in entries:
        r = entry["row"]
        fam_map = _family_map(r)
        cells = []
        for f in col_order:
            fam = fam_map.get(f)
            v = _fam_rate(fam) if fam is not None else None
            if v is None:
                cells.append('<td class="na">n/a</td>')
            else:
                # A nonzero rate under half a percent prints <1
                # but takes the 1 percent colour step, not the
                # true zero's: the cell must not wear the colour
                # of a zero it is not (pass 18).
                bg, rgb = _heat_rgb(
                    0.01 if 0 < v < 0.005 else v)
                fg = _heat_fg(rgb)
                # Whole-percent cells, rounded half up on the
                # exact value like every other rendering (the
                # derivation at _fam_rate), except that a real
                # rate under half a percent prints as <1 rather
                # than a false 0. A negative
                # rate (corrupt data) prints its signed value, so
                # the visible cell never contradicts the exact
                # figure in its own text.
                d100 = Decimal(str(v)) * 100
                if d100 >= Decimal("0.5") or v < 0:
                    q100 = _quantize(d100, Decimal("1"))
                    # A corrupt magnitude prints in the bounded
                    # power form every other rate surface uses,
                    # not as a digit expansion hundreds of
                    # characters long inside a table cell
                    # (pass 39).
                    cell = (_pow_form(q100) if q100 != 0
                            and q100.adjusted() >= 12
                            else str(int(q100)))
                else:
                    cell = "0" if v == 0 else "<1"
                n_elig = _num(fam.get("n_eligible")) if fam else None
                # The cell's exact text names its family and its
                # precise value, and it is always present: the
                # value used to ride in a tooltip attribute, with
                # the text span appearing only when a base count
                # existed, so a cell without one was silent at
                # full precision and a tooltip did the talking
                # three times over (pass 18). The visible integer
                # is hidden from assistive tech so the value is
                # announced once, at full precision.
                sr = (f'<span class="sr-only">{_esc(disp[f])} '
                      f"{_pct(v)}")
                if n_elig is not None:
                    sr += f" · n {_int(n_elig)}"
                sr += "</span>"
                cells.append(
                    f'<td style="background:{bg};color:{fg}">'
                    f"{sr}"
                    f'<span aria-hidden="true">{_esc(cell)}</span></td>')
        flagged = entry["rank"] is None
        suffix = ' <span class="nr">· no rank</span>' if flagged else ""
        body.append(
            f'<tr><th scope="row" '
            f'class="row-name{" flag" if flagged else ""}">'
            f"{_esc(_entry_short(entry))}{suffix}</th>"
            + "".join(cells) + "</tr>")
    return (
        '<table class="heat">'
        '<caption class="sr-only">Family attack success rates by '
        f"model in percent. {caption_cols}</caption><thead><tr>"
        '<th class="row-name" scope="col"></th>' + head +
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")


def _heatmap(entries: list[dict[str, Any]], fam_order: list[str]) -> str:
    """Family by model ASR heatmap, values printed in every cell.

    Two forms of the one table. Wide screens get the columns in
    payload order; small screens get the columns ordered by
    impact, highest first, so the families with the highest
    rates lead the phone view. CSS shows exactly one form at
    each width, and print keeps the wide form.
    """
    if not fam_order:
        return ""
    disp = _fam_display(fam_order)
    desktop = (
        '<div class="heat-wrap heat-d" tabindex="0" role="region" '
        'aria-label="Attack family heatmap, columns in benchmark '
        'order">'
        + _heat_table_html(
            entries, fam_order,
            "Columns in order, "
            + ", ".join(_esc(disp[f]) for f in fam_order)
            + ".",
            fam_order)
        + "</div>")
    impact = _family_impact_order(entries, fam_order)
    phone = (
        '<div class="heat-wrap heat-m" tabindex="0" role="region" '
        'aria-label="Attack family heatmap, families ordered by '
        'average attack success, scrolls sideways on small screens">'
        + _heat_table_html(
            entries, impact,
            # The ordering averages run over the models that
            # carry each family, so a family carried by one
            # model in three is ranked by that model's figure:
            # the caption says so where the order is announced
            # (pass 18).
            "Columns ordered by average attack success rate, "
            "highest first. Averages run over the models "
            "carrying each family. "
            + ", ".join(_esc(disp[f]) for f in impact)
            + ".",
            fam_order)
        + "</div>")
    return desktop + phone


# ---------------------------------------------------------------- scatter

def _tick_money(exp: int) -> str:
    """A scatter axis tick for a power of ten.

    Formatted the way the money figures elsewhere on the page
    are grouped, so a million-dollar tick reads "$1M" rather
    than the float repr "$1e+06" the raw :g format produced
    (pass 18). Sub-dollar decades keep their decimal form.
    """
    if exp < -6:
        # Past a millionth the plain decimal form is a wall
        # of zeros (322 characters at 1e-320) that swallows
        # the axis; the power form is the only bounded print
        # at such magnitudes, and it arises only from costs
        # no run carries (pass 27).
        return f"$1e{exp}"
    if exp < 0:
        # Formatted through Decimal, never the float repr:
        # at the far decades the :g form reverts to
        # scientific text ("$1e-15") on an axis whose every
        # other tick is a plain figure (pass 23).
        return "$" + format(Decimal(1).scaleb(exp), "f")
    if exp < 3:
        return f"${10 ** exp}"
    suffix = {3: "K", 6: "M", 9: "B", 12: "T", 15: "Q",
              18: "Qn", 21: "Sx", 24: "Sp", 27: "Oc",
              30: "No", 33: "Dc"}
    k = (exp // 3) * 3
    if k in suffix:
        return f"${10 ** (exp - k)}{suffix[k]}"
    # Past the suffix table the tick prints the power form
    # rather than its full grouped figure, which runs to
    # hundreds of digits at the far decades (pass 27).
    return f"$1e{exp}"


# Label placements for the cost scatter, keyed by short model
# name: (dx, dy, text anchor). The placements are chosen so no
# label's text box touches another point's disc and no two boxes
# overlap, which the audit harness re-checks mechanically on
# every render. Points not listed take the default placement to
# the right of the point.
_SCATTER_LABEL_POS = {
    "kimi-k3": (-10, 4, "end"),
    "grok-4": (-10, 4, "end"),
    "jev-1.13.0": (10, 4, "start"),
    "deepseek-flash": (0, -12, "middle"),
    "qwen3-235b-a22b-2507": (10, 4, "start"),
    "ling-3.0-flash": (10, 4, "start"),
    "ling-3.0-flash-vl": (10, 4, "start"),
    "gpt-5.6-luna": (0, -12, "middle"),
    "gemini-3.8-flash": (0, 18, "middle"),
    "MiniMax-M3": (0, -12, "middle"),
    "glm-4-plus": (0, 18, "middle"),
    "solar-pro4": (-10, 4, "end"),
}

# Label placements for the phone scatter, whose plot is the
# same data compressed into a 352-wide viewBox: the desktop
# offsets would collide there, so the phone form carries its
# own solved set under the same mechanical checks.
_SCATTER_LABEL_POS_PHONE = {
    "kimi-k3": (0, -12, "middle"),
    # The deepseek/gemini pair sits at one height with the
    # points 33 units apart: pass 15's red team showed the
    # old split (gemini's label above the pair, deepseek's
    # below) put both points between the two labels and
    # the pair swapped. Each label now hugs its own point
    # on the side away from the other's label: deepseek's
    # above (in the gap under gpt-5.6-luna's point, which
    # carries its own label above it), gemini's below, and
    # jev's label drops below its point to clear the band
    # deepseek's label vacated.
    "gemini-3.8-flash": (0, 24, "middle"),
    "deepseek-flash": (0, -14, "middle"),
    "jev-1.13.0": (0, 20, "middle"),
    "grok-4": (10, 4, "start"),
    "gpt-5.6-luna": (12, -10, "start"),
    "solar-pro4": (-10, 4, "end"),
    "MiniMax-M3": (0, -22, "middle"),
    "glm-4-plus": (10, 4, "start"),
    "ling-3.0-flash": (10, 4, "start"),
    "ling-3.0-flash-vl": (0, 18, "middle"),
    "qwen3-235b-a22b-2507": (0, -12, "middle"),
}


def _scatter_svg(entries: list[dict[str, Any]],
                 phone: bool = False) -> str:
    """Cost against ASR scatter, one labelled point per run.

    The cost axis is logarithmic, with a gridline and a label at
    every power of ten, because run costs span about 200 times from
    cheapest to dearest and a linear axis would crush the cheap
    runs into the margin. Flagged models draw as hollow amber
    circles, ranked models as filled green points.

    The phone form plots the same points and labels in a
    narrower viewBox sized to a phone panel, so every point is
    inside the phone width instead of behind a sideways scroll.
    CSS shows exactly one form at each width.
    """
    data = []
    for entry in entries:
        cost = _num(entry["row"].get("total_cost_usd"))
        asr = _num(entry["row"].get("asr_conditional"))
        if cost is not None and cost > 0 and asr is not None:
            data.append((cost, asr, entry))
    if len(data) < 2:
        return ""
    if phone:
        # The phone plot runs taller than a strict miniature
        # of the desktop form: at the desktop aspect the data
        # places the closest pair (glm-4-plus, MiniMax-M3)
        # 9.9 units apart, inside the two glyphs' combined
        # reach, so their assignment rested on the moat seam
        # alone. The extra height spreads every close pair
        # along the ASR axis (this pair to about 11.4 units)
        # while the scales stay the printed ones (pass 16).
        W, H = 352, 388
        sx0, sx1, sy0, sy1 = 40, 344, 24, 340
    else:
        W, H = 560, 400
        sx0, sx1, sy0, sy1 = 56, 536, 26, 348
    lo_exp = min(-1, math.floor(math.log10(min(c for c, _a, _e in data))))
    hi_exp = max(2, math.ceil(math.log10(max(c for c, _a, _e in data))))
    cmin, cmax = float(lo_exp), float(hi_exp)
    ymax = 0.30
    top = max(a for _c, a, _e in data)
    if top > 10.0:
        # As in the hero scale: the axis stops growing at 1000
        # percent, so degenerate data cannot overflow the float
        # range or the page.
        ymax = 10.0
    elif top > ymax:
        ymax = math.ceil(top / 0.05) * 0.05

    def sx(cost: float) -> float:
        return sx0 + (math.log10(cost) - cmin) / (cmax - cmin) * (sx1 - sx0)

    def sy(asr: float) -> float:
        # Positions clamp to the axis at both ends, as in the
        # hero chart: a corrupt rate past the scale (or below
        # zero) has no truer place than the edge, its exact
        # figure still prints in the description and the
        # cards, and the unclamped arithmetic wrote inf into
        # the geometry at extreme magnitudes (pass 15).
        v = min(max(asr, 0.0), ymax)
        return sy1 - (v / ymax) * (sy1 - sy0)

    bands = _tied_bands(entries)

    def tie_phrase(e: dict[str, Any]) -> str:
        band = bands.get(id(e["row"]))
        if band is not None:
            return f", tied band {band[0]} to {band[1]}"
        return ""

    # Ranked points draw first and flagged points last (the
    # draw loop below keeps this order).
    moat_r, pt_r = (5, 4.5) if phone else (7, 6)
    ordered = sorted(
        data, key=lambda t: 0 if t[2]["rank"] is not None else 1)
    plotted = [[sx(c), sy(a), e] for c, a, e in ordered]
    # Points the data places at one cost and one rate, or so
    # near it that their discs would merge into one glyph,
    # draw as a single point, the later ring or disc erasing
    # the earlier one whole. Such a point may step sideways
    # by at most one marker width (a disc diameter plus its
    # moat step), the destination checked rather than assumed
    # (a blind step can land on a third point and hide it
    # instead, and an exact-equality test misses two points
    # a hair apart). The step is capped because the axis is
    # the point's testimony about cost: the uncapped search
    # this replaces walked a clustered point up to twelve
    # steps in a tight field, parking it where the log axis
    # reads more than twice its true cost, and disclosed
    # only "offset slightly" to screen readers. A point with
    # no clearing step inside the cap keeps its true
    # position and overlaps its neighbour instead: a merged
    # glyph at the right cost misleads nobody about the
    # figure, where a separated glyph at a false one does.
    # Both moves are disclosed in the description, and the
    # offset carries a line inside the panel itself, where
    # sighted readers can see it (passes 18, 22 and 23).
    nudged = False
    overlapped = False
    _clear = 2 * pt_r
    _placed: list[tuple[float, float]] = []

    def _clears(x: float, y: float) -> bool:
        return all((x - _px) ** 2 + (y - _py) ** 2
                   >= _clear ** 2 for _px, _py in _placed)

    for _i, (_cx, _cy, _e) in enumerate(plotted):
        if _clears(_cx, _cy):
            _placed.append((_cx, _cy))
            continue
        _dir = -1 if _cx > (sx0 + sx1) / 2 else 1
        _nx = None
        for _sgn in (_dir, -_dir):
            _cand = _cx + _sgn * (2 * pt_r + 3)
            if sx0 <= _cand <= sx1 and _clears(_cand, _cy):
                _nx = _cand
                break
        if _nx is not None:
            nudged = True
            plotted[_i][0] = _nx
            _placed.append((_nx, _cy))
        else:
            overlapped = True
            _placed.append((_cx, _cy))
    desc = ("Cost per run against attack success rate. The cost "
            "axis is log scale. Filled points are ranked models "
            "and hollow points are flagged models with no rank. "
            + ("Points at one cost and rate, or too near to "
               "draw apart, are offset by a marker width at "
               "most so each stays visible. "
               if nudged else "")
            + ("Points with no clear offset at that reach "
               "are drawn at their true position, one over "
               "the other. "
               if overlapped else "")
            + ". ".join(
                f"{_entry_short(e)} "
                f"{_money(e['row'].get('total_cost_usd'), bound=_has_unpriced_calls(e['row']))}"
                f"{' (lower bound)' if _has_unpriced_calls(e['row']) else ''} at "
                f"{_pct_asr(e['row'].get('asr_conditional'))}, "
                f"{'rank ' + str(e['rank']) if e['rank'] is not None else 'flagged no rank'}"
                f"{tie_phrase(e)}"
                for _c, _a, e in data) + ".")
    tid = "scatter-m-t" if phone else "scatter-t"
    did = "scatter-m-d" if phone else "scatter-d"
    parts = [f'<svg viewBox="0 0 {W} {H}" '
             f'class="chart {"scatter-m" if phone else "scatter-d"}" '
             f'role="img" aria-labelledby="{tid} {did}">'
             f'<title id="{tid}">Cost per run against attack '
             'success rate</title>'
             f'<desc id="{did}">{_esc(desc)}</desc>']
    # The decade step coarsens as the span grows, as on the
    # other axes, so corrupt costs spanning hundreds of
    # decades cannot inflate the render without bound.
    estep = 1
    while (hi_exp - lo_exp) / estep > 12:
        estep *= 2
    exp = lo_exp
    while exp <= hi_exp:
        gv = 10.0 ** exp
        if not (gv > 0.0) or not math.isfinite(gv):
            # The smallest subnormal costs push the axis a
            # decade past the float range: 10.0 ** -324
            # underflows to 0.0, whose log10 raises, and a
            # decade past 1e308 is inf, which has no tick
            # position. Such a decade simply gets no tick;
            # the axis span itself is computed in log space
            # and stays exact (pass 15).
            exp += estep
            continue
        tx = sx(gv)
        # The rightmost tick label is end-anchored inside the
        # viewBox when centring it on its tick would push it
        # past the edge (the phone form's $100 sits at the
        # plot's right edge and clipped to $10 centred).
        lanch, lx = "middle", tx
        if tx + 14 > W:
            lanch, lx = "end", W - 2.0
        parts.append(
            f'<line x1="{tx:.1f}" y1="{sy0}" x2="{tx:.1f}" y2="{sy1}" '
            f'stroke="#232c35"/>'
            f'<text x="{lx:.1f}" y="{sy1 + 18}" class="s-axis" '
            f'text-anchor="{lanch}">{_tick_money(exp)}</text>')
        # Minor ticks at 2 to 9 times each power of ten. A log axis
        # with only decade lines invites a linear read, so the
        # compressed spacing inside each decade stays visible.
        if estep == 1 and exp < hi_exp:
            for mult in range(2, 10):
                mx = sx(gv * mult)
                if not math.isfinite(mx):
                    continue
                parts.append(
                    f'<line x1="{mx:.1f}" y1="{sy1 - 7}" x2="{mx:.1f}" '
                    f'y2="{sy1}" stroke="#3a4652"/>')
        exp += estep
    parts.append(
        f'<text x="{sx1}" y="{sy1 + 36}" class="s-axis" '
        'text-anchor="end">cost per run in USD, log scale</text>')
    parts.append(
        f'<text x="{sx0}" y="{sy0 - 10}" class="s-axis">'
        "attack success rate</text>")
    # The gridline step coarsens as the axis grows, as in the
    # hero chart, so the line count stays bounded.
    ystep = 0.1
    while ymax / ystep > 10:
        ystep *= 2
    gv = 0.0
    while gv <= ymax + 1e-9:
        ty = sy(gv)
        parts.append(
            f'<line x1="{sx0}" y1="{ty:.1f}" x2="{sx1}" y2="{ty:.1f}" '
            f'stroke="#232c35"/>'
            f'<text x="{sx0 - 8}" y="{ty + 4:.1f}" class="s-axis" '
            f'text-anchor="end">{gv * 100:.0f}%</text>')
        gv += ystep
    # The tied bands are stated inside the panel too, so the
    # panel cropped or shared alone does not present the point
    # gaps as separations the page elsewhere calls ties.
    _band_list = sorted(set(bands.values()))
    if _band_list:
        parts.append(
            f'<text x="{sx0 + 2}" y="{sy0 + 14}" class="s-axis">'
            "tied bands "
            + " · ".join(f"{a}–{b}" for a, b in _band_list)
            + "</text>")
    has_lb = any(_has_unpriced_calls(e["row"])
                 for _c, _a, e in data)
    # The legend's geometry is settled here, before the
    # labels are placed, because the label fit-check below
    # treats the legend's text rows as obstacles. The box
    # takes the bottom corner scoring fewer plotted points
    # (the left on a tie; a point landing in a text row's
    # band scores extra, since points draw over the box and
    # one on the key's own word garbles it): it used to sit
    # bottom left unconditionally, and a field compressed
    # into that corner by one very weak model left the box
    # over a point and two labels, in the corner the
    # caption directs readers to (pass 23). Its height counts a
    # third row exactly when some plotted run's cost is a
    # lower bound, so the box never promises a row the
    # marks do not use, and its bottom edge stops 8 units
    # short of the plot's bottom border: flush on the border
    # it sat directly over the log axis's minor ticks, which
    # stand 7 units tall there, and the opaque backdrop
    # knocked out the whole first decade's tick set in both
    # forms (pass 30; reconciliation ledger Theme 10).
    leg_rows = 3 if has_lb else 2
    leg_h = 44 + 18 * (leg_rows - 2)
    leg_bottom = sy1 - 8
    leg_ly = leg_bottom - leg_h
    # The legend's text rows, as boxes a label may not
    # strike through: a label painting across the key's own
    # words garbles both (pass 23). Swatch centres sit at
    # leg_lx + 10, text starts at leg_lx + 22. The row
    # centres are centred in the box: anchoring them to the
    # bottom edge left 12 units of slack over the first row
    # against 2 under the last (pass 24; reconciliation
    # ledger Theme 10).
    _row1 = leg_ly + 13
    _row_bases = [_row1 + 4, _row1 + 22]
    if has_lb:
        _row_bases.append(leg_bottom - 9)

    def _leg_score(_lx: int) -> float:
        # Points inside the box count once; a point whose
        # centre lands in a text row's band counts three,
        # because points draw over the box by design and
        # one sitting on the key's own word garbles the
        # word itself, the failure the corner choice exists
        # to avoid.
        _n = 0.0
        for _px, _py, _e in plotted:
            if _lx - pt_r - 2 <= _px <= _lx + 150 + pt_r + 2 \
                    and leg_ly - pt_r - 2 <= _py <= leg_bottom + pt_r + 2:
                _n += 1
                if any(_b - 11 <= _py <= _b + 2
                       for _b in _row_bases):
                    _n += 2
        return _n

    leg_lx = sx0 + 4 if _leg_score(sx0 + 4) <= _leg_score(sx1 - 154) \
        else sx1 - 154
    leg_obstacles = [
        (leg_lx + 2, _b - 11, leg_lx + 150, _b + 2)
        for _b in _row_bases]
    _band_txt = ""
    if _band_list:
        _band_txt = ("tied bands "
                     + " · ".join(f"{a}–{b}"
                                  for a, b in _band_list))
    _dots_txt = None
    _dots_y = sy0 + 14
    if has_lb:
        # The cost caveat rides inside the panel too, on the
        # same principle as the tied-bands line: a crop of
        # the panel alone must not present lower-bound costs
        # as exact positions. Both forms carry the same
        # sentence (pass 23): the phone form used to take a
        # two-word key form ("lower bound dots") when the
        # sentence, end-anchored on the phone baseline, ran
        # left under the legend box and lost its first word
        # behind it (measured in passes 14 and 16). The
        # phone line now sits under the tied-bands line at
        # the panel's top left instead, a stretch no point
        # reaches on this data; the legend's third row and
        # the caption and footer carry the same statement.
        # Pass 32 moved the phone line to the top right, on
        # the bands line's own row: the top-left point's
        # label reaches the under-line stretch even though
        # its point does not, and the two texts touched,
        # while the top right corner (dear and weak) is a
        # stretch no point or label reaches on this data.
        # Pass 33: on that shared row the full sentence
        # overprinted the bands line — at the phone text
        # size the bands line ends near x186 and the
        # sentence starts near x118, so the merged string
        # destroyed both disclosures inside the panel, the
        # one place a cropped share reads them. A second
        # row under the bands line is not available either:
        # as a label obstacle it pushes the top-left
        # point's label some 50 units off its point, the
        # misattachment the harness rejects (the pass 32
        # failure in mirror). So the phone line takes the
        # full sentence on the shared row when the sentence
        # itself clears the bands line, the key form when
        # only the key form clears it, and the full
        # sentence on the second row if the bands line
        # ever grows into even the key form's stretch; the
        # legend's third row, the caption and the footer
        # carry the full statement either way. The fit is measured at the
        # phone axis size's real advance (12px, 7.2 a
        # character), not the fit check's 11px estimate.
        if phone:
            _full = "dots mark the lower bound costs"
            _key = "lower bound dots"
            _bands_end = sx0 + 2 + len(_band_txt) * 7.2
            if sx1 - 2 - len(_full) * 7.2 > _bands_end + 8:
                _dots_txt = _full
            elif sx1 - 2 - len(_key) * 7.2 > _bands_end + 8:
                _dots_txt = _key
            else:
                _dots_txt = _full
                _dots_y = sy0 + 28
            parts.append(
                f'<text x="{sx1 - 2}" y="{_dots_y}" '
                'text-anchor="end" class="s-axis">'
                f'{_dots_txt}</text>')
        elif leg_lx > sx0 + 4:
            # The legend took the bottom right corner, so
            # the sentence anchors to the free bottom left.
            parts.append(
                f'<text x="{sx0 + 2}" y="{sy1 - 10}" '
                'class="s-axis">dots mark the lower bound '
                'costs</text>')
        else:
            parts.append(
                f'<text x="{sx1 - 2}" y="{sy1 - 10}" '
                'text-anchor="end" class="s-axis">dots mark '
                'the lower bound costs</text>')
    if nudged:
        # The offset disclosure also rides inside the panel,
        # where a sighted reader can see it: the description
        # alone left the one reader who reads positions off
        # the axis uninformed that any position moved
        # (pass 23).
        _crowd_y = sy0 + 28
        if phone and has_lb:
            _crowd_y = sy0 + 42
        parts.append(
            f'<text x="{sx0 + 2}" y="{_crowd_y}" '
            'class="s-axis">crowded points are offset by a '
            'marker width at most</text>')
    # The panel's own annotation lines are label obstacles
    # like the legend's rows: the label fit-check below
    # never knew the lines existed, so on the phone form
    # the cheapest, highest-ASR point's label settled onto
    # the lower-bound line and the two texts touched
    # (pass 32). Widths estimate the 11px monospace
    # advance, with the same 2-unit clearance the legend
    # rows get in the fit check.
    text_obstacles = list(leg_obstacles)
    if _band_list:
        text_obstacles.append(
            (sx0 + 2, sy0 + 3,
             sx0 + 2 + len(_band_txt) * 6.6, sy0 + 16))
    if phone and has_lb and _dots_txt is not None:
        text_obstacles.append(
            (sx1 - 2 - len(_dots_txt) * 6.6, _dots_y - 11,
             sx1 - 2, _dots_y + 2))
    if nudged:
        text_obstacles.append(
            (sx0 + 2, _crowd_y - 11,
             sx0 + 2
             + len("crowded points are offset by a "
                   "marker width at most") * 6.6,
             _crowd_y + 2))
    # Ranked points draw first and flagged points last. Two
    # points the data places closer than a disc diameter
    # overlap whatever the order; drawing the hollow flagged
    # ring last keeps the flagged encoding whole on top,
    # where drawing it first let a later filled disc and its
    # moat erase a third of the ring (pass 12, phone form,
    # glm-4-plus under MiniMax-M3, centres 9.9 units apart).
    # Marker sizes. The phone plot compresses the desktop
    # geometry into about 60 percent of the width, where a
    # desktop-sized disc swallows a near-coincident
    # neighbour (on the real payload the glm-4-plus ring
    # and the MiniMax-M3 disc sit 10 units apart, inside
    # one desktop diameter). The phone form draws smaller
    # markers so two close points stay two glyphs. Point
    # circles carry a class, keeping them machine-
    # distinguishable from the legend swatches, which keep
    # their own size. Pass 14 measured the phone pair still
    # touching at r5 (centres 9.9 units apart, diameters 10)
    # and took the phone disc to 4.5, so the pair keeps
    # daylight between the discs as well as the moat seam.
    # Pass 15 trims the moats themselves to the pair's
    # measure (phone centres 9.9 apart, desktop 14.1): at
    # r6 and r8 the two ground discs overlapped into one
    # combined halo, so the moats now sit just clear of
    # each other at those distances.
    # Points and labels collect apart from the panel furniture:
    # the legend (built below, appended to parts first) must
    # draw UNDER both, so a point in the legend's corner stays
    # plotted on top of the box instead of vanishing behind
    # it, and every label prints over it (pass 18).
    pt_parts: list[str] = []
    lab_parts: list[str] = []
    for cx, cy, entry in plotted:
        r = entry["row"]
        flagged = entry["rank"] is None
        # A ground-coloured moat under every point, so two
        # points the data places close together keep a visible
        # seam instead of merging into one blob.
        pt_parts.append(
            f'<circle class="pt" cx="{cx:.1f}" cy="{cy:.1f}" '
            f'r="{moat_r:g}" fill="#10141a"/>')
        if flagged:
            pt_parts.append(
                f'<circle class="pt" cx="{cx:.1f}" cy="{cy:.1f}" '
                f'r="{pt_r:g}" fill="none" '
                'stroke="#e8a33d" stroke-width="2"/>')
        else:
            pt_parts.append(
                f'<circle class="pt" cx="{cx:.1f}" cy="{cy:.1f}" '
                f'r="{pt_r:g}" '
                'fill="#2fbf71" stroke="#0b0e11" stroke-width="1.5"/>')
        if _has_unpriced_calls(r):
            # A pale centre dot marks the point's cost as a
            # lower bound on the point itself. Pass 14 punched
            # the dot in the ground colour, which read as a
            # hole: a ranked disc with a dark centre is the
            # flagged ring's shape, and the filled/hollow
            # code the caption states collapsed into colour
            # alone (pass 15 red team). A light dot is a mark
            # ON the point, not a see-through: the disc stays
            # visibly filled, the ring stays visibly hollow,
            # and both classes carry the identical mark, so
            # it means one thing. It grows the marker not at
            # all, so close pairs keep their seam, and the
            # legend's third row reproduces it exactly.
            # The dot carries a dark stroke: pale on the
            # ranked green its bare fill measured 2.22 to 1,
            # under the 3 to 1 floor for a data-bearing
            # graphical part, so a low-vision reader could
            # not tell which green points were lower bounds.
            # The stroke's edge carries it on green, the
            # fill carries it inside the amber rings (whose
            # interior is the panel colour, where the stroke
            # simply disappears), and the mark stays one
            # identical mark on both classes (pass 16).
            pt_parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2" '
                'fill="#f4f8f2" stroke="#10141a" '
                'stroke-width="1"/>')
    # Labels. A solved placement is tried first and used when
    # it still fits the point its name now sits on; every
    # other name (and every solved placement that no longer
    # fits) goes through a de-collision pass over fixed
    # candidate placements, so no label gets a spot that fuses
    # it into a neighbour or names the wrong point (passes 18
    # and 22). Every label carries a panel-coloured halo, so
    # its glyphs stay legible where they cross a gridline, a
    # point's moat, or the legend box the labels now draw over.
    pos = _SCATTER_LABEL_POS_PHONE if phone else _SCATTER_LABEL_POS
    halo = (' style="paint-order:stroke;stroke:#10141a;'
            'stroke-width:3px;stroke-linejoin:round"')
    centres = [(px, py) for px, py, _e in plotted]
    placed: list[tuple[float, float, float, float]] = []
    used_solved: set[str] = set()

    def _guard(tx: float, anch: str, est_w: float):
        # A placement whose estimated box would run past a
        # viewBox edge flips its anchor to end inside the
        # edge. The solved placements all fit and pass through
        # unchanged in practice; an unsolved name (a future
        # model at an extreme cost) previously started its
        # label at the edge and clipped it off the panel.
        if anch == "start" and tx + est_w > W - 2:
            return "end", W - 2.0
        if anch == "middle" and tx + est_w / 2 > W - 2:
            return "end", W - 2.0
        if anch == "middle" and tx - est_w / 2 < 2:
            return "start", 2.0
        if anch == "end" and tx - est_w < 2:
            return "start", 2.0
        return anch, tx

    def _box(tx: float, ly: float, anch: str, est_w: float):
        if anch == "start":
            x0 = tx
        elif anch == "end":
            x0 = tx - est_w
        else:
            x0 = tx - est_w / 2
        return (x0, ly - 11.5, x0 + est_w, ly)

    def _fits(box, own, anchor, relaxed: bool = False) -> bool:
        x0, y0, x1, y1 = box
        if x0 < 2 or x1 > W - 2 or y0 < 2 or y1 > H - 2:
            return False
        for bx0, by0, bx1, by1 in placed:
            if (x0 < bx1 + 2 and bx0 - 2 < x1
                    and y0 < by1 + 2 and by0 - 2 < y1):
                return False
        if not relaxed:
            # The legend's text rows are obstacles like any
            # placed label: the pass-18 rule that labels draw
            # over the legend BOX survives (a point in the
            # legend's corner keeps its label printable over
            # the box's empty ground), but a label striking
            # through the key's own words garbles both texts
            # (pass 23).
            for bx0, by0, bx1, by1 in text_obstacles:
                if (x0 < bx1 + 2 and bx0 - 2 < x1
                        and y0 < by1 + 2 and by0 - 2 < y1):
                    return False
        own_d = math.hypot(anchor[0] - own[0], anchor[1] - own[1])
        for px, py in centres:
            if (px, py) == own:
                continue
            # The label's own point stays its nearest point,
            # and the box keeps the audit's clearance from
            # every other centre.
            if math.hypot(anchor[0] - px, anchor[1] - py) <= own_d:
                return False
            dx = max(x0 - px, 0.0, px - x1)
            dy = max(y0 - py, 0.0, py - y1)
            if math.hypot(dx, dy) < 8.0:
                return False
        return True

    for cx, cy, entry in plotted:
        r = entry["row"]
        flagged = entry["rank"] is None
        nm = _short_raw(r)
        disp = _entry_short(entry)
        est_w = len(disp) * 7.0
        solved = pos.get(nm) if nm not in used_solved else None
        chosen = None
        if solved is not None:
            used_solved.add(nm)
            dx, dy, anch = solved
            anch, tx = _guard(cx + dx, anch, est_w)
            ly = cy + dy
            # A solved placement is a position solved for the
            # point its name carried when the table was built;
            # a run that moves the model moves the point, and
            # the verbatim label can land nearer another
            # point than its own, naming the wrong model. The
            # placement therefore has to pass the same fit
            # check as any candidate, and falls through to
            # the solver when it no longer fits (pass 22).
            if _fits(_box(tx, ly, anch, est_w), (cx, cy),
                     (tx, ly)):
                chosen = (tx, ly, anch)
        if chosen is None:
            for dx, dy, anch0 in (
                    (10, 4, "start"), (-10, 4, "end"),
                    (0, -12, "middle"), (0, 20, "middle"),
                    (14, -10, "start"), (-14, -10, "end"),
                    (14, 16, "start"), (-14, 16, "end"),
                    (0, 30, "middle"), (0, -24, "middle"),
                    (0, -37, "middle"), (0, 43, "middle"),
                    (0, -50, "middle"), (0, 56, "middle"),
                    (26, 4, "start"), (-26, 4, "end"),
                    (26, -22, "start"), (-26, -22, "end"),
                    (26, 30, "start"), (-26, 30, "end")):
                anch, tx = _guard(cx + dx, anch0, est_w)
                ly = cy + dy
                if _fits(_box(tx, ly, anch, est_w), (cx, cy),
                         (tx, ly)):
                    chosen = (tx, ly, anch)
                    break
            if chosen is None:
                # The legend's text rows relax before any
                # other rule does: a label over the key's
                # words is a lesser harm than a label over
                # another label or a point (pass 23).
                for dx, dy, anch0 in (
                        (10, 4, "start"), (-10, 4, "end"),
                        (0, -12, "middle"), (0, 20, "middle"),
                        (14, -10, "start"), (-14, -10, "end"),
                        (14, 16, "start"), (-14, 16, "end"),
                        (0, 30, "middle"), (0, -24, "middle"),
                        (0, -37, "middle"), (0, 43, "middle"),
                        (0, -50, "middle"), (0, 56, "middle"),
                        (26, 4, "start"), (-26, 4, "end"),
                        (26, -22, "start"), (-26, -22, "end"),
                        (26, 30, "start"), (-26, 30, "end")):
                    anch, tx = _guard(cx + dx, anch0, est_w)
                    ly = cy + dy
                    if _fits(_box(tx, ly, anch, est_w),
                             (cx, cy), (tx, ly), relaxed=True):
                        chosen = (tx, ly, anch)
                        break
            if chosen is None:
                # The last resort steps the default box
                # vertically until it clears every label
                # already placed, taking the least-overlap
                # slot when none is clear: the unchecked
                # fixed default this replaces could park
                # two labels at the very same coordinates in
                # a tight cluster, printing them as one
                # garbled stack (pass 23).
                anch, tx = _guard(cx + 10, "start", est_w)
                _best = None
                _best_ov = None
                for _step in (0, 1, -1, 2, -2, 3, -3, 4, -4,
                              5, -5, 6, -6, 7, -7, 8, -8):
                    _ly = cy + 4 + 13 * _step
                    _cand_box = _box(tx, _ly, anch, est_w)
                    if _cand_box[0] < 2 or _cand_box[2] > W - 2 \
                            or _cand_box[1] < 2 \
                            or _cand_box[3] > H - 2:
                        # The stepped search stays inside the
                        # panel: an early version of it walked
                        # a corner label down past the axis
                        # into the tick labels' band.
                        continue
                    _ov = 0.0
                    for bx0, by0, bx1, by1 in placed:
                        _ox = max(0.0, min(_cand_box[2], bx1)
                                  - max(_cand_box[0], bx0))
                        _oy = max(0.0, min(_cand_box[3], by1)
                                  - max(_cand_box[1], by0))
                        _ov += _ox * _oy
                    if _ov == 0.0:
                        _best = (tx, _ly, anch)
                        break
                    if _best_ov is None or _ov < _best_ov:
                        _best_ov = _ov
                        _best = (tx, _ly, anch)
                chosen = _best if _best is not None \
                    else (tx, cy + 4, anch)
        tx, ly, anch = chosen
        placed.append(_box(tx, ly, anch, est_w))
        lab_parts.append(
            f'<text x="{tx:.1f}" y="{ly:.1f}" class="s-lab'
            f'{" flag" if flagged else ""}"{halo} '
            f'text-anchor="{anch}">{_esc(disp)}</text>')
    # The point styles are legend inside the panel too, so the
    # panel cropped or shared alone still says what filled and
    # hollow mean. The box sits in whichever bottom corner
    # holds fewer plotted points (settled with the panel
    # furniture above, where bottom left wins a tie: it is
    # empty plot at these scales, and it is the corner a
    # sideways-scrolled small screen shows first, so the
    # legend is in the first view there too). A ground panel
    # behind the legend knocks out the log axis's minor ticks
    # there, which otherwise strike through the legend text's
    # lower glyphs.
    # The backdrop carries a hairline border (pass 14), so
    # the swatches read as a key box rather than as two more
    # plotted points at valid data coordinates. When any
    # plotted run's cost is a lower bound the box grows a
    # third row keying the centre dot those points carry.
    parts.append(
        f'<rect x="{leg_lx}" y="{leg_ly}" width="150" '
        f'height="{leg_h}" fill="#10141a" stroke="#3a4652" '
        'stroke-width="1"/>')
    row1 = _row1
    # The swatches are the plotted glyphs' components at the
    # plotted radii, not smaller tokens of them: a swatch at
    # its own size pattern-matches nothing on the chart
    # (pass 16). The legend keys the components separately
    # (filled disc, hollow ring, centre dot) so every plotted
    # combination decodes: the flagged swatch used to carry
    # the centre dot whenever every flagged point did, which
    # taught that the dot was part of the flagged glyph and
    # left the bare ring, the form an exact flagged point
    # takes, with no exemplar at all (passes 24, 25 and 27;
    # reconciliation ledger Theme 4). The third row's swatch
    # still reproduces a plotted instance exactly, a ranked
    # disc carrying the pale centre dot: the grey ring this
    # replaced matched no point on the chart, so a reader
    # pattern-matching the legend found zero instances and
    # discarded the row (pass 15).
    parts.append(
        f'<circle cx="{leg_lx + 10}" cy="{row1}" r="{pt_r:g}" '
        'fill="#2fbf71" stroke="#0b0e11" stroke-width="1.5"/>'
        f'<text x="{leg_lx + 22}" y="{row1 + 4}" class="s-axis">'
        "ranked</text>"
        f'<circle cx="{leg_lx + 10}" cy="{row1 + 18}" r="{pt_r:g}" '
        'fill="none" stroke="#e8a33d" stroke-width="2"/>'
        f'<text x="{leg_lx + 22}" y="{row1 + 22}" class="s-axis">'
        "flagged · no rank</text>")
    if has_lb:
        parts.append(
            f'<circle cx="{leg_lx + 10}" cy="{leg_bottom - 13}" '
            f'r="{pt_r:g}" '
            'fill="#2fbf71" stroke="#0b0e11" stroke-width="1.5"/>'
            f'<circle cx="{leg_lx + 10}" cy="{leg_bottom - 13}" r="2" '
            'fill="#f4f8f2" stroke="#10141a" '
            'stroke-width="1"/>'
            f'<text x="{leg_lx + 22}" y="{leg_bottom - 9}" '
            'class="s-axis">'
            "lower bound cost</text>")
    # The legend was appended to parts before this point in
    # source order only: in the document it sits under the
    # points and labels, which join it now (pass 18).
    parts.extend(pt_parts)
    parts.extend(lab_parts)
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- malformed

def _strip_sort_key(p: tuple[float, dict[str, Any]]) -> tuple[float, float]:
    """Worst malformed rate first; equal rates in ASR order.

    The secondary key makes the order a property of the data
    rather than of the order the caller happened to pass rows
    in, so tied rates read in the same order as the ranking.
    """
    a = _num(p[1]["row"].get("asr_conditional"))
    return (-p[0], a if a is not None else 9.9)


def _malformed_svg(entries: list[dict[str, Any]]) -> str:
    """Malformed response rate for every model, worst first.

    Bars past the 5 percent admission line turn amber, the flag
    colour the whole page uses, bars under it sit in green, and
    the line itself is drawn dashed and labelled, so the gate a
    rank depends on is visible rather than described.
    """
    data = []
    for entry in entries:
        v = _num(entry["row"].get("malformed_rate"))
        if v is not None:
            data.append((v, entry))
    if not data:
        return ""
    data.sort(key=_strip_sort_key)
    W = 560
    # The scale runs just past the worst rate, floored at 13%, so
    # bar slopes stay comparable with the ranking chart beside it.
    # A snapped round-number ceiling (the old behaviour) silently
    # compressed every gap in this chart by a third.
    mmax = max(0.13, max(v for v, _e in data) * 1.05)
    if max(v for v, _e in data) > 1.0:
        # A rate past 100 percent is corrupt: the scale stops
        # at the whole (its label would otherwise overflow to
        # a literal inf past about 1e306), the bars clamp at
        # full width below, and the value text still prints
        # the corrupt figure in full (pass 15).
        mmax = 1.0
    bands = _tied_bands(entries)

    def _status(e: dict[str, Any]) -> str:
        if e["rank"] is None:
            return ", flagged no rank"
        if _num(e["row"].get("asr_conditional")) is None:
            # A ranked row with no recorded ASR keeps no rank
            # speech on the strip surfaces: its card already
            # declines to print the rank the page cannot
            # evidence, and the strip must not assert in text
            # what the card withholds (pass 18).
            return ", no ASR recorded"
        s = f", rank {e['rank']}"
        band = bands.get(id(e["row"]))
        if band is not None:
            s += f", tied band {band[0]} to {band[1]}"
        return s

    desc = ("Malformed response rate by model, worst first. "
            + ". ".join(
                f"{_entry_short(e)} {_pct_malf(v)}" + _status(e)
                for v, e in data)
            + ". The dashed line marks the 5% admission line. "
            "Bars past the line are amber and bars under it "
            "are green.")
    parts = [
        '<title id="malf-t">Malformed response rate by model</title>'
        f'<desc id="malf-d">{_esc(desc)}</desc>']
    # The names are end-anchored at x=150: a name longer than
    # the slot (about 23 characters at this size, two fewer
    # where the flagged bullet prints) starts off the viewBox
    # and shows as a mid-word fragment. The painted names are
    # fitted to the slot and disambiguated at that width, as
    # in the hero; the description keeps the full name
    # (pass 23).
    painted = _fit_names(
        [e for _v, e in data],
        [21 if e["rank"] is None else 23 for _v, e in data])
    line_x = 158 + 0.05 / mmax * (W - 218)
    # Rows start 3 units lower than the first pass drew
    # them: the "worst first" header's box cleared the
    # first value label by under 2.5px at every width
    # (pass 32). The tail below the grid gives the 3
    # units back, so the viewBox height is unchanged.
    grid_bottom = 19 + len(data) * 27
    # The order is stated inside the panel too, so a cropped or
    # shared panel cannot read as a best-first leaderboard.
    parts.append(
        '<text x="500" y="12" class="m-axis" '
        'text-anchor="end">worst first</text>')
    # Scale gridlines at 0, 10 and the ceiling (the 5 line is the
    # admission line itself, drawn over the bars below), so the
    # short axis reads as a scale and not as a full chart.
    for gv in (0.10,):
        gx = 158 + gv / mmax * (W - 218)
        parts.append(
            f'<line x1="{gx:.1f}" y1="8" x2="{gx:.1f}" '
            f'y2="{grid_bottom}" stroke="#232c35"/>')
    labels = []
    for i, (v, entry) in enumerate(data):
        y = 19 + i * 27
        over = v > 0.05
        flagged = entry["rank"] is None
        # A negative rate has no length; the text still prints it.
        w = min(W - 218, max(0.0, v / mmax * (W - 218)))
        bullet = "• " if flagged else ""
        parts.append(
            f'<text x="150" y="{y + 12}" class="m-name'
            f'{" flag" if flagged else ""}" '
            f'text-anchor="end">{bullet}'
            f'{_esc(painted[i])}</text>')
        parts.append(
            f'<rect x="158" y="{y}" width="{w:.1f}" '
            f'height="15" rx="2" fill="{"#e8a33d" if over else "#2fbf71"}"/>')
        # Every value sits outside its bar end, in the one
        # label regime the phone form already uses. The value
        # whose bar ends just short of the admission line used
        # to move inside the bar in dark ink, the single label
        # in the chart drawn that way and, on this payload,
        # the only flagged-adjacent figure a cropped row
        # showed reversed out of its bar (pass 18). A label
        # whose span would cross the admission line starts
        # past it instead: the line's dashes crossing the
        # label's cell above and below its decimal point
        # made the closest under-gate figure on the chart
        # read as struck through, halo notwithstanding
        # (pass 30; reconciliation ledger Theme 10). The
        # labels are collected and painted after the admission line
        # below, so the line passes behind their halos instead
        # of striking through the glyphs: painted last, the
        # line and its dark underlay crossed the one label in
        # their path and erased its decimal point, the closest
        # under-gate figure on the chart (pass 22).
        _val_txt = _pct_malf(v)
        _lx = 166 + w
        # The label is 12.5px monospace, a 7.5-unit advance:
        # a span starting left of the line and ending right
        # of it is the crossing case handled above.
        if _lx < line_x < _lx + len(_val_txt) * 7.5:
            _lx = line_x + 6
        labels.append(
            f'<text x="{_lx:.1f}" y="{y + 12}" '
            f'class="m-val{" over" if over else ""}" '
            'style="paint-order:stroke;stroke:#10141a;'
            'stroke-width:3px;stroke-linejoin:round">'
            f"{_val_txt}</text>")
    bottom = grid_bottom
    parts.append(
        # A dark underlay keeps the dashes readable where they
        # cross the bars themselves, not only on the panel.
        f'<line x1="{line_x:.1f}" y1="8" x2="{line_x:.1f}" '
        f'y2="{bottom}" stroke="#0b0e11" stroke-width="3.6"/>'
        f'<line x1="{line_x:.1f}" y1="8" x2="{line_x:.1f}" '
        f'y2="{bottom}" stroke="#e8a33d" stroke-width="1.6" '
        'stroke-dasharray="4 3"/>')
    parts.extend(labels)
    parts.append(
        f'<text x="{line_x:.1f}" y="{bottom + 15}" class="m-line-lab" '
        'text-anchor="middle">5% admission line</text>'
        f'<text x="158" y="{bottom + 15}" class="m-axis">0%</text>'
        f'<text x="{158 + 0.10 / mmax * (W - 218):.1f}" '
        f'y="{bottom + 15}" class="m-axis" '
        'text-anchor="middle">10%</text>'
        f'<text x="500" y="{bottom + 15}" class="m-axis" '
        f'text-anchor="end">{mmax * 100:.0f}%</text>'
        # The gate's meaning rides inside the chart box too,
        # on the same principle as the scatter's in-panel
        # lines: cropped to the chart alone, the amber bars
        # read as caution unless the box itself speaks (pass
        # 15). The line states what the geometry itself
        # proves, that a bar past the line is over the limit;
        # it does not assert each past-line bar's rank status,
        # which is the row's own fact, stated in the row's
        # text (pass 17).
        f'<text x="158" y="{bottom + 34}" class="m-axis">'
        "bars past the line are over the 5% admission limit</text>")
    # The viewBox height matches the scatter panel beside it, so
    # the paired panels share a bottom edge.
    return (
        f'<svg viewBox="0 0 {W} {bottom + 57}" class="chart strip-chart" '
        'role="img" aria-labelledby="malf-t malf-d">'
        + "".join(parts) + "</svg>")


def _malformed_mobile(entries: list[dict[str, Any]]) -> str:
    """Phone-native malformed list, the strip's small-screen form.

    A sideways-scrolled bar chart opens with its longest bars
    clipped at the panel edge, where a clipped bar misstates its
    own length and its value sits off screen. This list prints
    every value in its row and keeps the bar on a stated scale
    with the admission line ticked, mirroring the ranking list.
    CSS shows exactly one of the two forms at each width.
    """
    data = []
    for entry in entries:
        v = _num(entry["row"].get("malformed_rate"))
        if v is not None:
            data.append((v, entry))
    if not data:
        return ""
    data.sort(key=_strip_sort_key)
    mmax = max(0.13, max(v for v, _e in data) * 1.05)
    if max(v for v, _e in data) > 1.0:
        # As in the desktop strip: a corrupt rate past the
        # whole stops the scale at 100 percent rather than
        # printing an inf ceiling (pass 15).
        mmax = 1.0
    bands = _tied_bands(entries)
    # The spoken denominator counts the ranked rows the strip
    # can evidence, the ones carrying an ASR: an asr-less
    # ranked row inflating the count would lend its rank to
    # every other row's status line (pass 18).
    n_ranked = sum(1 for e in entries if e["rank"] is not None
                   and _num(e["row"].get("asr_conditional"))
                   is not None)
    rows = []
    for v, entry in data:
        r = entry["row"]
        over = v > 0.05
        flagged = entry["rank"] is None
        # The bullet is decoration duplicating the flag the
        # status text states: hidden from assistive tech, so
        # the name is not announced with a bullet glyph in it
        # (pass 18).
        bullet = ('<span aria-hidden="true">• </span>'
                  if flagged else "")
        # The row speaks its status to a screen reader in the
        # same words the desktop strip's description uses, so
        # the phone list's text form carries the rank, flag
        # and tie facts its bullet and colour show sighted
        # readers.
        if flagged:
            status = "flagged, no rank"
        elif _num(r.get("asr_conditional")) is None:
            status = "no ASR recorded"
        else:
            status = f"rank {entry['rank']} of {n_ranked} ranked"
            band = bands.get(id(entry["row"]))
            if band is not None:
                status += f", tied band {band[0]} to {band[1]}"
        rows.append(
            '<div class="mb-row"><div class="mb-top">'
            f'<span class="mb-name{" flag" if flagged else ""}">'
            f"{bullet}{_esc(_entry_short(entry))}</span>"
            f'<span class="mb-val{" over" if over else ""}">'
            f"{_pct_malf(v)}</span>"
            f'<span class="sr-only">, {_esc(status)}</span></div>'
            '<div class="mb-track">'
            f'<div class="mb-gate" style="left:'
            f'{0.05 / mmax * 100:.1f}%"></div>'
            f'<div class="mf-bar{" over" if over else ""}" '
            f'style="width:{min(100.0, max(v, 0.0) / mmax * 100) if v == v else 0.0:.1f}%"></div></div></div>')
    scale = ('<div class="mb-scale">Bars run 0% to '
             f"{mmax * 100:.0f}% · the dashed tick is the 5% "
             # Geometry's own claim only, as in the desktop
             # chart's in-box line: past the tick is over the
             # limit, and each row states its own rank status
             # (pass 17).
             "admission line · bars past it are over the 5% "
             "admission limit</div>")
    return ('<div class="malformed-mobile">' + scale
            + "".join(rows) + "</div>")


# ---------------------------------------------------------------- cards

def _sev_map(detail: Any) -> dict[str, Any]:
    """A row's severity blocks keyed by canonical level name.

    The levels are a fixed vocabulary recorded in lowercase;
    a block recorded under a case variant ("Critical") is
    the same level to every reader, and keying the card's
    slots on the exact string alone printed n/a over data
    the run actually carries (pass 23). First recording
    wins where two keys differ only in case. Levels outside
    the printed three stay in the map; the card's slots and
    the caption's yardstick both read only the printed
    three, from this one map.
    """
    if not isinstance(detail, dict):
        return {}
    sev = detail.get("severities")
    if not isinstance(sev, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in sev.items():
        if isinstance(k, str):
            out.setdefault(k.casefold(), v)
    return out


def _card(entry: dict[str, Any], fam_order: list[str],
          n_ranked: int = 0,
          tied_band: tuple[int, int] | None = None,
          sets_benchmarks: bool = False,
          bench: tuple[bool, bool] = (True, True)) -> str:
    """One model card: headline rate, family spark strip, stat rows.

    The spark strip repeats the page family order, with the
    retrieval poisoning bar in orange on every card, so the shape
    of a model's weakness reads at a glance. Stat rows print every
    headline figure the payload carries for the run, with n/a for
    a figure it does not carry. A flagged card also prints the
    reason it carries no rank.
    """
    r = entry["row"]
    flagged = entry["rank"] is None
    if flagged:
        chip = '<span class="chip flag">FLAGGED · NO RANK</span>'
    elif _num(r.get("asr_conditional")) is None:
        # A rank the page cannot evidence, because the row has no
        # headline rate and appears in no chart, is not printed
        # as a rank at all.
        chip = '<span class="chip rank">NO ASR RECORDED</span>'
    elif n_ranked:
        # The rank counts the ranked models only, and the chip
        # says so, so a shared card cannot read as a rank of all.
        # Membership of a tied rank band is marked on the chip
        # too, so the card alone never crowns a sole winner.
        tie_suffix = ""
        if tied_band is not None:
            tie_suffix = f" · TIED {tied_band[0]}–{tied_band[1]}"
        chip = (f'<span class="chip rank">RANK {entry["rank"]} '
                f'OF {n_ranked} RANKED{tie_suffix}</span>')
    else:
        chip = f'<span class="chip rank">RANK {entry["rank"]}</span>'
    # The note slot sits on every card at a fixed height, so the
    # stat rows line up across a row of cards. Its lines are the
    # full model ID when the charts shorten it, the flag reason
    # or the gate note, and the segment re-run disclosure.
    notes = []
    # The gate or flag line comes first, so the comparable line
    # sits at the same height on every card; the full model ID
    # and the re-run disclosure follow it.
    if flagged:
        _reason = r.get("reason")
        _gate_claim = isinstance(_reason, str) and (
            _reason in _KNOWN_REASONS
            or _GATE_CLAIM.search(_reason) is not None)
        if _gate_claim:
            # A gate claim in the registry's reason is a claim
            # about this row's own malformed value, so the note
            # derives from the value, exactly as a ranked row's
            # note does: a row can carry the claim while its
            # printed rate sits at or under the gate, and
            # repeating the claim would contradict the
            # MALFORMED stat on the same card (pass 18). The
            # trigger is the claim's shape, a rate against a
            # threshold: keying it on the bare word "malformed"
            # silently replaced reasons that merely mention
            # the word ("malformed data breach, duplicate
            # run") with a gate note and deleted the recorded
            # reason outright (pass 23). With no value
            # recorded there is nothing on the card for the
            # claim to contradict, so the recorded reason
            # prints as recorded rather than vanishing.
            mv = _num(r.get("malformed_rate"))
            if mv is not None:
                _derived = (
                    "Malformed response rate at or under 5%"
                    if mv <= 0.05
                    else "Malformed response rate above 5%")
                notes.append(_derived)
                # The recorded reason still prints, as a
                # record beside the derived sentence, when
                # it says something else: replacing it
                # outright deleted a registry reason from
                # the page (the recorded text was "held out"
                # prose about an audit sample, not a rate
                # claim a value could answer), and a reader
                # of the card alone never learned a reason
                # existed (passes 24 and 26).
                _recorded = _humanize_reason(_reason)
                if _recorded != _derived:
                    # The comparison above uses the full
                    # text; the print caps it. The reason
                    # was the one payload string still
                    # printing at unbounded length (pass 36).
                    notes.append(
                        f"Reason on record · "
                        f"{_esc(_truncate(_recorded, 200))}")
            else:
                notes.append(_esc(_truncate(
                    _humanize_reason(_reason), 200)))
        else:
            # Reasons that are not gate claims print as
            # recorded, and a flagged card with no reason
            # recorded says so: the absence is itself the
            # record, and an empty note slot stated nothing
            # where the registry's silence belonged (pass 23).
            notes.append(_esc(_truncate(
                _humanize_reason(_reason), 200)))
    elif not flagged and _num(r.get("malformed_rate")) is not None:
        # The gate note is derived from the value it sits
        # beside, never from the row's rank status: a ranked
        # row whose stored rate is over the line must not
        # carry a note claiming it is at or under it (pass 17).
        notes.append(
            "Malformed response rate at or under 5%"
            if _num(r.get("malformed_rate")) <= 0.05
            else "Malformed response rate above 5%")
    full_id = _raw_name(r)
    _short_base = entry.get("short_base")
    if not isinstance(_short_base, str) or not _short_base:
        _short_base = _short_raw(r)
    if full_id != _truncate(_short_base, 40):
        # The note carries the full ID whenever the card's
        # own header does not show it whole: a vendor prefix
        # the charts drop, and equally a name the 40-character
        # header cap truncates. Comparing against the
        # untruncated short alone let a long single-segment
        # name's distinguishing tail appear nowhere on the
        # page (pass 23). The line is labelled as the model
        # ID: unlabelled, it read as a second, longer model
        # name in a slot whose other lines are sentences
        # (passes 24 and 27; reconciliation ledger Theme 10).
        # The cap sits far past any real model ID (the
        # longest on the sealed board is 25 characters), so
        # the note still carries the full ID its pass-23
        # contract promises; it bounds only a degenerate ID
        # that would otherwise print whole (pass 35).
        notes.append(f"Model ID · {_esc(_truncate(full_id, 120))}")
    wire_note = entry.get("wire_note")
    if isinstance(wire_note, str) and _clean(wire_note).strip():
        # Another entry on this page shares this card's model ID
        # across a different wire, so the header alone cannot tell
        # the two measurements apart: the note names this entry's
        # wire. The render sets wire_note only for such colliding
        # entries, so a model measured once carries no extra line.
        notes.append(
            f"Wire · {_esc(_truncate(_clean(wire_note), 80))}")
    seg = _rerun_segment(r)
    if seg is not None:
        notes.append(
            f"First {seg:,} cases "
            "re-run under the fixed adapter · see Notes")
    fam_map = _family_map(r)
    if not flagged:
        # A ranked run that never faced a family the page
        # charts has a gap in its crown: the rank chip says
        # where it placed, and this line says over what, so
        # the card alone does not present an untested family
        # as a tested one (passes 27 and 30).
        _missing = [f for f in fam_order if f not in fam_map]
        if _missing:
            _disp_m = _fam_display(_missing)
            _names = [_esc(_disp_m[f]) for f in _missing]
            if len(_names) == 1:
                notes.append(
                    f"No {_names[0]} result recorded")
            else:
                notes.append(
                    "No result recorded for "
                    + ", ".join(_names))
    reason = ('<div class="card-note">' + "".join(
        f"<div>{line}</div>" for line in notes) + "</div>")
    disp = _fam_display(fam_order)
    bars = []
    spark_bits = []
    for f in fam_order:
        fam = fam_map.get(f)
        v = _fam_rate(fam) if fam is not None else None
        if v is None:
            bars.append(
                f'<span class="spark na" '
                f'title="{_esc(disp[f])} n/a"></span>')
            spark_bits.append(f"{disp[f]} n/a")
        else:
            # Height is the value on the shared scale, the
            # full 46px track, so a bar's share of the box is
            # its value. A true zero draws no bar, rather
            # than a tick that reads as a small real rate, and a
            # nonzero rate keeps a 1px sliver so it never looks
            # identical to a true zero. A negative rate is a
            # nonzero rate: it prints its signed figure in
            # the bar's own text, and the section caption
            # states the sliver rule for nonzero rates
            # without exception, so it keeps the sliver too
            # rather than wearing a true zero's absence
            # beside its own figure (pass 39, re-audit). A
            # rate at or past the whole scale fills the
            # track instead of asking the layout for an
            # absurd height (or raising on the rounding of
            # an astronomical one).
            hgt = (0 if (v == 0 or v != v)
                   else 46 if v >= 1 else max(1, round(v * 46)))
            # The bar fill carries the run's status as well as
            # the family: green is the ranked fill everywhere
            # else on the page, so a flagged card's bars sit in
            # a neutral slate rather than borrowing the ranked
            # colour for a model the gate kept off the ranking
            # (pass 17). The retrieval spike stays orange on
            # every card, ranked or flagged.
            cls = "spark hot" if f == "retrieval_poisoning" else (
                "spark dim" if flagged else "spark")
            n_elig = _num(fam.get("n_eligible"))
            # Text forms name the family in the display prose
            # the visible page uses, never the raw payload key.
            title = f"{_esc(disp[f])} {_pct(v)}"
            bit = f"{disp[f]} {_pct(v)}"
            if n_elig is not None:
                title += f" · n {_int(n_elig)}"
                bit += f" · n {_int(n_elig)}"
            spark_bits.append(bit)
            bars.append(
                f'<span class="{cls}" style="height:{hgt:.0f}px" '
                f'title="{title}"></span>')
    # The per-family figures are text as well as bars, so they do
    # not live only in hover tooltips.
    spark_lab = _esc(
        f"Family attack success rates for {_entry_short(entry)}"
        ". " + ". ".join(spark_bits) + ".")
    # A card shared on its own still names its spike, rather than
    # depending on the section caption above the first card. When
    # a non-retrieval family spikes highest, the caption names it
    # too, so the tallest bar on the card is never anonymous.
    others = []
    for f in fam_order:
        if f == "retrieval_poisoning":
            continue
        fam = fam_map.get(f)
        v = _fam_rate(fam) if fam is not None else None
        if v is not None:
            others.append((f, v))
    top_other = max(others, key=lambda p: p[1]) if others else None
    _retr_fam = fam_map.get("retrieval_poisoning")
    _retr_v = _fam_rate(_retr_fam) \
        if _retr_fam is not None else None
    if _retr_v is not None:
        # The naming threshold is judged on the printed
        # figure: a family whose rate rounds to 20.0 percent
        # prints "20.0%" in the card's own text, and a caption
        # claiming no family reaches 20% would contradict the
        # figure beside it on digits no surface prints
        # (pass 22).
        if top_other is not None and _quantize(
                Decimal(str(top_other[1])) * 100,
                Decimal("0.1")) >= Decimal("20.0"):
            # "Top other" presupposes the orange family leads.
            # Where the other family's printed figure beats
            # retrieval's own printed figure, the caption
            # names it as the top spike outright: on the one
            # such card the template otherwise read the
            # run's worst family as retrieval's runner-up,
            # and never printed retrieval's figure for the
            # comparison (pass 39).
            _lead = ("top spike is" if _quantize(
                Decimal(str(_retr_v)) * 100, Decimal("0.1"))
                < _quantize(Decimal(str(top_other[1])) * 100,
                            Decimal("0.1"))
                else "top other spike is")
            spark_cap = (
                '<div class="spark-cap">Orange is retrieval '
                f"poisoning · {_lead} "
                f'<span class="nb">{_esc(disp[top_other[0]])} '
                f"{_pct(top_other[1])}</span>"
                "</div>")
        elif top_other is not None:
            # Below the naming threshold the caption still states
            # the bound, so the card never reads as if its other
            # families were unexamined.
            spark_cap = ('<div class="spark-cap">Orange is '
                         "retrieval poisoning · no other family "
                         "reaches 20%</div>")
        else:
            spark_cap = ('<div class="spark-cap">Family ASRs in '
                         "fixed order · orange is retrieval "
                         "poisoning</div>")
    elif top_other is not None and _quantize(
            Decimal(str(top_other[1])) * 100,
            Decimal("0.1")) >= Decimal("20.0"):
        # This run carries no retrieval rate, so its strip
        # has no orange bar: the caption names the run's own
        # top spike rather than pointing at an orange bar
        # that is a dotted n/a slot on this card (pass 27).
        spark_cap = (
            '<div class="spark-cap">Family ASRs in fixed '
            f"order · top spike is "
            f'<span class="nb">{_esc(disp[top_other[0]])} '
            f"{_pct(top_other[1])}</span>"
            "</div>")
    elif top_other is not None:
        spark_cap = ('<div class="spark-cap">Family ASRs in '
                     "fixed order · no family reaches 20%</div>")
    else:
        spark_cap = ('<div class="spark-cap">Family ASRs in fixed '
                     "order</div>")
    detail = r.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    cal = detail.get("calibration") or {}
    if not isinstance(cal, dict):
        cal = {}
    attacked = cal.get("attacked") or {}
    if not isinstance(attacked, dict):
        attacked = {}
    brier = attacked.get("brier")
    sev = _sev_map(detail)
    sev_parts = []
    sev_bases = []
    if any(isinstance(sev.get(k), dict)
           for k in ("critical", "high", "medium")):
        # The three slots are positional under a C·H·M label, so a
        # missing severity holds its slot as n/a rather than
        # letting the remaining values shift into its place.
        for key in ("critical", "high", "medium"):
            block = sev.get(key)
            if isinstance(block, dict):
                # One decimal and a percent sign on every value,
                # so the triple reads as three rates and never
                # as counts, and close rates stay distinct. Each
                # rate rests on its own severity base, printed
                # beside the rates in the same position.
                sev_parts.append(_pct(_sev_rate(block)))
                sev_bases.append(_int(block.get("n_eligible")))
            else:
                sev_parts.append("n/a")
                sev_bases.append("n/a")
    sev_txt = "·".join(sev_parts) if sev_parts else "n/a"
    sev_base_txt = "·".join(sev_bases) if sev_bases else "n/a"
    # The footer scopes the tax to ranked runs, so a flagged row
    # that somehow carries the figure does not print it either.
    rtax = _num(r.get("robustness_tax")) if not flagged else None
    # The tax label names only the benchmarks the page
    # carries: with no ranked ECE carrier there is no ECE
    # benchmark to be versus, and with neither benchmark
    # there is no figure to print (pass 27). The setter's
    # figure stays the stored one: the tax is a sealed
    # figure, and printing a derived zero in its place
    # would fabricate a number the payload does not carry
    # (the pass 27 setter observation is dispositioned in
    # the Fix Pass B report on this basis).
    if sets_benchmarks:
        tax_lab = "ROBUST TAX · IT SETS BOTH RANKED BENCHMARKS"
        tax_val = _pts(rtax)
    elif bench == (True, True):
        tax_lab = "ROBUST TAX · VS BEST RANKED RUNS"
        tax_val = _pts(rtax)
    elif bench == (True, False):
        tax_lab = "ROBUST TAX · VS BEST RANKED BENIGN"
        tax_val = _pts(rtax)
    elif bench == (False, True):
        tax_lab = "ROBUST TAX · VS BEST RANKED ECE"
        tax_val = _pts(rtax)
    else:
        tax_lab = "ROBUST TAX"
        tax_val = _pts(rtax) if flagged else "n/a"
    malformed = _num(r.get("malformed_rate"))
    calib_n = attacked.get("n") if isinstance(attacked, dict) else None
    calib_val = _int(calib_n)
    calib_f = _num(calib_n)
    if calib_f == 0 and _ece_of(r) is None \
            and _num(attacked.get("brier")) is None:
        # A calibration count of exactly zero with no score
        # anywhere in the block is no calibration data, the
        # same absence the ECE and Brier rows print as n/a:
        # as a pair it would read "0 · 0.0%", a measured share
        # of nothing over an empty base (pass 19).
        calib_val = "n/a"
        calib_f = None
    elig_f = _num(r.get("n_eligible"))
    # The label names the share only when a share prints: a
    # suppressed share leaves the bare count under a bare
    # label, so the card never promises a figure it does not
    # show (pass 18).
    calib_lab = "CALIB N"
    if (calib_val != "n/a" and calib_f is not None
            and elig_f is not None and 0 < elig_f
            and calib_f <= elig_f):
        # The share beside the count is the count's own share
        # of the run's eligible cases, the base the ELIGIBLE
        # CASES row prints two rows above, so the pair divides
        # out on the card's own numbers. The payload's
        # confidence_coverage is a different quantity (the
        # share of all 4,701 cases whose attacked arm reported
        # a confidence, ineligible cases included); printing
        # it beside this count attached the count to a base
        # that exists nowhere on the page and contradicted
        # the eligible row on five cards (pass 17). A count
        # past its own base is corrupt and prints bare rather
        # than as a share over 100 percent.
        calib_val = f"{calib_val} · {_pct_share(calib_f / elig_f)}"
        calib_lab = "CALIB N · ATTACKED · SHARE OF ELIGIBLE"
    # A run with unpriced calls carries a lower bound for its
    # cost. The mark describes a recorded figure, so it keys
    # on a positive recorded cost: with none recorded there
    # is no figure to bound and the stat reads n/a under the
    # plain label (pass 34). The flag also drives the floored
    # printing in _money, so the card states a floor the
    # recorded figure supports (pass 38).
    _cost_lb = (_num(r.get("total_cost_usd")) or 0) > 0 \
        and _has_unpriced_calls(r)
    stats = [
        # The eligible count is the ASR's own base, so it leads,
        # directly under the ASR figure it belongs to; benign
        # accuracy, whose base the payload does not carry, sits
        # below it rather than above the count a hurried reader
        # would attach it to, and its label names the base the
        # footer defines, decided benign variants (pass 14).
        ("ELIGIBLE CASES", _int(r.get("n_eligible"))),
        # Benign accuracy prints at share precision: a rate
        # that rounds to 100.0 percent without being exact
        # claims a perfect score the data does not carry,
        # the same completeness claim the calibration share
        # rule guards (pass 22).
        ("BENIGN ACC · DECIDED VARIANTS",
         _pct_share(r.get("benign_accuracy"))),
        # The lower-bound stat says so on the run's own card
        # rather than leaving the caveat to the footer.
        (("COST · LOWER BOUND" if _cost_lb else "COST"),
         _money(r.get("total_cost_usd"), bound=_cost_lb)),
        # Latency and the calibration scores are attacked-run
        # measurements, and the labels say so on the card's own
        # face: a card cropped alone is the share unit, and the
        # section caption's scoping sentence does not travel
        # with it (pass 17). The benign ECE and Brier differ
        # from these by an order of magnitude, so an unqualified
        # label invites the wrong run's reading.
        ("LATENCY P50 · ATTACKED", _lat(r.get("latency_ms_p50_attacked"))),
        ("LATENCY P95 · ATTACKED", _lat(r.get("latency_ms_p95_attacked"))),
        # ECE and Brier are computed on the calibration set, which
        # is smaller than the eligible set for most runs. Its count
        # sits directly above them rather than letting the eligible
        # count stand in for a base it is not.
        (calib_lab, calib_val),
        ("ECE · ATTACKED", _fmt3(_ece_of(r))),
        ("BRIER · ATTACKED", _fmt3(brier)),
        # The tax is a shortfall from the best ranked runs
        # (plural: two benchmarks, benign accuracy and
        # attacked ECE, each set by the best ranked run for
        # that metric), and the label says so, so a card
        # cropped alone cannot read a zero as an absolute
        # score (pass 14). The run that sets both benchmarks
        # is its own comparison by construction, and its
        # label says that instead: a bare "versus" there
        # still implied a rival it does not have (pass 15).
        # The setter label carries the ranked scope too: a
        # flagged run can hold a higher raw benign figure
        # than the setter (glm-4-plus prints 98.9% against
        # kimi-k3's 98.7% on this page), and the unscoped
        # label stated a superlative that figure contradicts
        # on any card cropped alone (passes 24, 25 and 30;
        # reconciliation ledger Theme 9).
        (tax_lab, tax_val),
        ("MALFORMED", _pct_malf(malformed)),
        ("SEV FLIP RATE C·H·M", sev_txt),
        ("SEV BASES C·H·M", sev_base_txt),
    ]
    stat_html = "".join(
        # The robust tax row carries its own class: its
        # benchmark-setter label is the one stat label that
        # wraps to two lines, and the stylesheet reserves
        # that second line on every card so the rows below
        # it stay in register across a card row (pass 35).
        f'<div class="stat'
        f'{" tax" if a.startswith("ROBUST TAX") else ""}">'
        f'<span class="stat-lab">{_esc(a)}</span>'
        f'<span class="stat-val'
        f'{" bad" if a == "MALFORMED" and malformed is not None and malformed > 0.05 else ""}'
        f'">{_esc(b)}</span></div>' for a, b in stats)
    pair = _row_ci(r)
    if pair is not None \
            and _num(r.get("asr_conditional")) is None:
        # An interval with no headline rate is not the
        # headline's interval: the label says what the
        # interval is doing on the card instead of letting
        # "ASR · 95% CI" present it as the missing figure's
        # own (pass 27).
        asr_lab = (f"95% CI {_pct_asr(pair[0])} to "
                   f"{_pct_asr(pair[1])} · headline rate "
                   "not recorded")
    elif pair is not None:
        asr_lab = (f"ASR · 95% CI {_pct_asr(pair[0])} to "
                   f"{_pct_asr(pair[1])}")
    else:
        asr_lab = "ASR · no interval recorded"
    return (
        f'<article class="card{" flagged" if flagged else ""}">'
        '<div class="card-head">'
        f'<h3 class="card-name{" flag" if flagged else ""}">'
        f'{_esc(_entry_short(entry))}</h3>{chip}</div>'
        f"{reason}"
        f'<div class="card-asr{" flag" if flagged else ""}">'
        f'{_pct_asr(r.get("asr_conditional"))}'
        f'<span class="card-asr-lab">{asr_lab}</span></div>'
        f'<div class="sparks" role="img" aria-label="{spark_lab}">'

        f'{"".join(bars)}</div>'
        f"{spark_cap}"
        f"{stat_html}</article>")


def _fmt3(v: Any) -> str:
    n = _num(v)
    if n is None:
        return "n/a"
    dv = Decimal(str(n))
    # A score's magnitude is bounded like every other figure
    # on the page, at both ends: past the plain range the
    # power form states it. A huge score printed plainly was
    # a several-hundred-digit token inside a nowrap stat,
    # and a nonzero score below the precision cap leaked the
    # Decimal's own E-notation ("1E-7", "0E-30") where its
    # sibling formatters print a bounded figure (pass 39).
    if dv != 0 and (dv.adjusted() >= 12 or dv.adjusted() < -30):
        return _pow_form(dv)
    # A nonzero score under half a thousandth printed as
    # "0.000", the same figure as an exact zero beside it:
    # precision rises until the value shows, the treatment
    # _money already gives a tiny cost (pass 25).
    digits = max(3, _showing_digits(dv, cap=30))
    d = _quantize(dv, Decimal(1).scaleb(-digits))
    if d == 0:
        d = abs(d)
    return format(d, "f")


def _ece_of(r: dict[str, Any]) -> float | None:
    """A row's attacked ECE from its calibration block.

    The card's calibration figures (count, Brier) all come from
    detail.calibration.attacked, so the ECE printed beside them
    comes from the same block: a flat ece_attacked field that
    disagrees with the block must not win by being read first
    (pass 18). The flat field remains only as the fallback for
    payloads whose calibration block carries no ECE at all.
    """
    detail = r.get("detail") or {}
    if isinstance(detail, dict):
        cal = detail.get("calibration") or {}
        if isinstance(cal, dict):
            att = cal.get("attacked") or {}
            if isinstance(att, dict):
                v = _num(att.get("ece"))
                if v is not None:
                    return v
    return _num(r.get("ece_attacked"))


# ---------------------------------------------------------------- chrome

_BANNER_OFFICIAL = (
    '<div class="banner official">Official results. Produced from a '
    "frozen dataset tag under the published methodology. Run notes "
    "and caveats are at the foot of this page.</div>"
)
_BANNER_MOCK = (
    '<div class="banner mock">MOCK DATA. This report was rendered from '
    "placeholder data, not an official evaluation. Do not cite, rank, or "
    "publish these numbers.</div>"
)

# Runs whose first segments were re-run under fixed adapters on
# 12 October 2026, after an adapter defect was found in the original
# segments. Keyed by run_id, the trial's own identity for a run,
# with the re-run segment size from the trial record (the
# segment re-run audit notes of 2026-10-12). A display name is
# not an identity: an unrelated run that happens to share one
# must not inherit a dated, sized provenance claim, so a row
# carries the disclosure only when its run_id is one of these
# two runs. The sealed artifacts behind the current page are
# the re-sealed runs, every one of them single-configuration,
# and the footer discloses the re-runs so the provenance of
# those two runs is on the page.
_RERUN_SEGMENTS = {
    "google-v2-trial": 1610,
    "moonshot-v2-trial": 3274,
}


def _rerun_segment(r: dict[str, Any]) -> int | None:
    """The re-run segment size for this row's run, if its run
    is one of the two re-run trial runs.

    The claim is about this row's own run, so the row's own
    case count bounds it: a run smaller than the segment
    cannot have had that many of its cases re-run, and keying
    the disclosure on the run_id alone asserted exactly that
    for any small run reusing the id (passes 27 and 29)."""
    run_id = r.get("run_id")
    if not isinstance(run_id, str):
        return None
    seg = _RERUN_SEGMENTS.get(run_id)
    if seg is None:
        return None
    n = _num(r.get("n_cases"))
    if n is not None and n < seg:
        return None
    return seg


def _has_unpriced_calls(r: dict[str, Any]) -> bool:
    """True when some of the run's calls went unpriced, so its
    recorded cost is a lower bound rather than the run's full
    price. Derived from the family tables, where every family
    counts its costed calls against its latency calls; a run
    is fully priced only when the two agree everywhere.

    The raw family entries are read directly, not through
    the display map: an entry in list form with no family
    field has no name to plot under, but its counts are
    still evidence about the run's pricing (pass 15).
    Counts that cannot exist (a negative figure) are
    corrupt, not evidence, and never mark a run on their
    own (pass 15)."""
    detail = r.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    fams = detail.get("families") or {}
    if isinstance(fams, dict):
        fam_entries = list(fams.values())
    elif isinstance(fams, list):
        fam_entries = fams
    else:
        fam_entries = []
    for fam in fam_entries:
        if not isinstance(fam, dict):
            continue
        costed = _num(fam.get("n_costed_calls"))
        timed = _num(fam.get("n_latency_calls"))
        if (costed is not None and timed is not None
                and 0 <= costed < timed and timed > 0):
            return True
    return False


def _run_notes_text(ranked: list[dict[str, Any]],
                    unranked: list[dict[str, Any]]) -> str:
    """Footer run-notes sentences for the segment re-runs.

    Two of the v2 trial runs had an adapter defect in their first
    segments. Those segments were re-run under the fixed adapters
    on 12 October 2026 and the runs re-sealed, so every run on the
    page is single-configuration. The note names each affected
    run and how many of its cases were re-run. It renders only
    when an affected run is on the page.
    """
    found = []
    seen = set()
    for r in ranked + unranked:
        # The note keys on the run's own run_id, never on its
        # display name, so a same-named run from another trial
        # can neither fabricate the note nor break the lookup.
        seg = _rerun_segment(r)
        # Two distinct runs can share a run_id across trials;
        # the dedupe key carries the display name as well, so
        # each affected run on the page is named, while a true
        # duplicate row still collapses.
        _disp = r.get("display_name")
        if isinstance(_disp, str) and _clean(_disp).strip():
            # The printed name is the cleaned name, capped
            # after cleaning: capping the raw string let
            # invisible padding fill the cap and strand the
            # visible text past it, printing a blank run in
            # the disclosure (pass 39). The name sits
            # mid-sentence here, so its edge whitespace is
            # trimmed where the name slots on other surfaces
            # swallow it invisibly: a recorded trailing
            # space otherwise prints as a doubled space
            # before "run" (pass 39, re-audit residue).
            name = _truncate(_clean(_disp), 80).strip()
        else:
            # A display name that is not a string, or cleans
            # to nothing, names nothing: a mapping or a list
            # printed its Python repr here. The run_id is
            # the run's identity of record and takes over,
            # as it does when the name is absent (passes 36
            # and 39).
            _rid = r.get("run_id")
            name = (_truncate(_clean(_rid), 80)
                    if isinstance(_rid, str) else "")
        # The dedupe collapses only a true duplicate row,
        # so it keys on the name as recorded, not on the
        # processed print name: two affected rows sharing
        # a run_id across trials, whose recorded names
        # differ only past the cap or only in characters
        # cleaning removes, processed to one print name
        # and one key, and the second run went unnamed in
        # the disclosure — the collision the
        # disambiguation below exists to separate
        # (pass 39, re-audit).
        key = (r.get("run_id"),
               _disp if isinstance(_disp, str) else None)
        if seg is not None and key not in seen:
            seen.add(key)
            found.append((name, seg))
    if not found:
        return ""
    # Two affected runs sharing one cleaned name are two
    # runs, not one name printed twice: the disclosure's
    # attribution cannot rest on the segment sizes alone,
    # so colliding note names take the same disambiguating
    # suffixes as the chart names (pass 39).
    _names = [n for n, _ in found]
    if len({_norm_name(n) for n in _names}) < len(_names):
        found = list(zip(_disambiguate(_names),
                         [s for _, s in found]))
    found.sort(key=lambda p: p[0])
    bits = " and ".join(
        f"the first {n:,} cases of the {name} run"
        for name, n in found)
    return (bits[0].upper() + bits[1:]
            + " were re-run under fixed adapters on 12 October "
            "2026, after an adapter defect was found in the "
            "original segments. Every run on this page is "
            "single-configuration throughout.")


def _local_date(stamp: Any) -> str:
    """The calendar date of an ISO timestamp in the trial's
    local frame, America/New_York.

    The page dates the segment re-runs 12 October 2026, the
    frame of the trial record (audit notes, watchdog log).
    Reading the run window straight off the UTC stamps would
    date the window's end 13 October for a re-seal that landed
    at 00:07 UTC on the 13th, 20:07 local on the 12th, and the
    page would disagree with itself. Every date on the page
    therefore uses the one frame. An unparseable stamp falls
    back to its own first ten characters, as before.
    """
    if not isinstance(stamp, str) or not stamp:
        return ""
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp[:10]
    if parsed.tzinfo is None:
        return parsed.date().isoformat()
    try:
        local = parsed.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return parsed.date().isoformat()
    return local.date().isoformat()


def _provenance_data(payload: dict[str, Any],
                     ranked: list[dict[str, Any]],
                     unranked: list[dict[str, Any]]) -> dict[str, Any]:
    """Suite, dataset, case count and run dates shared by page blocks."""
    all_rows = list(ranked) + list(unranked)
    # Suite and dataset version are asserted for the whole
    # page, so each prints only when every carrier agrees
    # (the pricing date in the footer gates the same way).
    # Mixed carriers fall back to n/a rather than letting
    # one row speak for runs it does not describe.
    # A value that cleans to nothing is not a carrier:
    # keying the consensus on raw truthiness let an
    # invisible-only suite or dataset print as a blank
    # assertion in the header tag and the provenance
    # instead of falling back to n/a (pass 36; the
    # pass-23 cleaned-name rule, applied here).
    # The asserted value is the cleaned string itself, not
    # the raw carrier: truncating the raw value let heavy
    # invisible padding fill the cap and strand the visible
    # text past it, so a padded suite printed blank here
    # while passing the cleaned consensus test (pass 39).
    # The asserted value is stripped for the same reason:
    # the eligibility test strips, so padding of any
    # whitespace class the cleaner keeps (ordinary spaces,
    # no-break spaces) otherwise fills the cap exactly as
    # the invisibles did (pass 39, re-audit).
    suite_vals = {_clean(v).strip()
                  for v in [payload.get("suite")]
                  + [r.get("suite") for r in all_rows]
                  if isinstance(v, str) and _clean(v).strip()}
    # The asserted strings print in the header tag and the
    # footer provenance: capped like every other prose
    # surface, so a degenerate value cannot print whole
    # (pass 35).
    suite = (_truncate(suite_vals.pop(), 80)
             if len(suite_vals) == 1 else "n/a")
    ds_vals = {_clean(v).strip()
               for v in [payload.get("dataset_version")]
               + [r.get("dataset_version") for r in all_rows]
               if isinstance(v, str) and _clean(v).strip()}
    dataset_version = (_truncate(ds_vals.pop(), 80)
                       if len(ds_vals) == 1 else "n/a")
    # A case count recorded as a float is the count it names
    # when it is integral (2000.0 is 2,000 cases): collecting
    # ints only dropped such a row from the consensus, so the
    # page claimed the other runs' count for it with no
    # variation disclosed (pass 27). A fractional count is
    # not a count and joins nothing (passes 25 and 29).
    n_cases_vals = []
    for r in all_rows:
        _nv = _num(r.get("n_cases"))
        if _nv is not None and float(_nv).is_integer():
            n_cases_vals.append(int(_nv))
    if n_cases_vals and len(set(n_cases_vals)) == 1:
        n_cases, cases_note = n_cases_vals[0], ""
    elif n_cases_vals:
        # Runs of different sizes cannot share the page's
        # per-run case claims, so the count goes unstated
        # (every surface that uses it has a generic form)
        # and the footer provenance discloses the variation.
        n_cases, cases_note = None, "varies"
    else:
        n_cases, cases_note = "n/a", ""
    # Only real calendar dates enter the run window: a stamp
    # that does not parse, or parses to a date that does not
    # exist, is not a run date, and printing its raw text
    # stated "2026-02-30" as provenance (passes 27 and 29).
    dates = sorted(d for d in
                   (_local_date(r.get("created_utc"))
                    for r in all_rows
                    if isinstance(r.get("created_utc"), str)
                    and r.get("created_utc"))
                   if _is_iso_date(d))
    return {
        "suite": suite,
        "dataset_version": dataset_version,
        "n_cases": n_cases,
        "cases_note": cases_note,
        "dates": dates,
    }


def _payload_hash(payload: dict[str, Any],
                  payload_sha256: str | None) -> str:
    """The provenance hash for the payload behind this page.

    A caller that read the payload from a file passes the hash of
    the file bytes, so the printed hash can be checked against the
    file itself. Without one, the hash covers the canonical JSON
    form of the payload, which is stable across renders.
    """
    if isinstance(payload_sha256, str):
        cand = payload_sha256.strip()
        # Only a plausible hex digest is printed as supplied.
        # Anything else falls back to the canonical hash, so a
        # stray value from a caller can never pose as the
        # payload's hash in the provenance block.
        if (len(cand) >= 32 and all(
                c in "0123456789abcdefABCDEF" for c in cand)):
            return cand
    try:
        canonical = json.dumps(payload, sort_keys=True,
                               separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        # Shapes parsed JSON can never produce (mixed-type
        # mapping keys defeat the sort, a self-referencing
        # dict defeats the dump) still owe the footer a
        # stable hash rather than a dead render (pass 15).
        canonical = "peira:unserializable-payload"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_iso_date(d: str) -> bool:
    """True when the string is a full ISO calendar date."""
    try:
        datetime.strptime(d, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _human_date(iso: str) -> str:
    """An ISO date as a written date, with the ISO form as fallback."""
    try:
        parsed = datetime.strptime(iso[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return _esc(iso[:10])
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _date_range_text(dates: list[str]) -> str:
    """Run dates in the footer's compact form.

    A range inside one month reads "7 to 12 October 2026"; anything
    wider spells both dates out in full.
    """
    if not dates:
        return "run dates not recorded"
    first, last = dates[0][:10], dates[-1][:10]
    if first == last:
        return f"runs on {_human_date(first)}"
    try:
        d1 = datetime.strptime(first, "%Y-%m-%d")
        d2 = datetime.strptime(last, "%Y-%m-%d")
    except ValueError:
        return f"runs from {_esc(first)} to {_esc(last)}"
    if (d1.year, d1.month) == (d2.year, d2.month):
        return (f"runs from {d1.day} to {d2.day} "
                f"{d2.strftime('%B %Y')}")
    return (f"runs from {_human_date(first)} to {_human_date(last)}")


def _manifest_hash(ranked: list[dict[str, Any]],
                   unranked: list[dict[str, Any]]) -> str | None:
    """The dataset manifest hash the runs were sealed against.

    Printed only when every run on the page carries one and
    all agree on it: the claim covers the page's runs, so a
    hash carried by some runs must not speak for the rest
    (pass 29). The value must be a plausible hex digest, the
    check the payload hash already carries: an integer in
    the field stringified into a digit string that posed as
    a hash (pass 27).
    """
    rows = list(ranked) + list(unranked)
    found = set()
    for r in rows:
        prov = r.get("provenance")
        v = prov.get("manifest_sha256") \
            if isinstance(prov, dict) else None
        if not (isinstance(v, str) and len(v) >= 32 and all(
                c in "0123456789abcdefABCDEF" for c in v)):
            return None
        found.add(v)
    return found.pop() if len(found) == 1 else None


def _footer(payload: dict[str, Any],
            ranked: list[dict[str, Any]],
            unranked: list[dict[str, Any]],
            fam_order: list[str],
            payload_sha256: str | None,
            names: dict[int, str] | None = None) -> str:
    """Compact footer: reading note, admission rule, run notes, provenance.

    This is the only prose block on the page, kept to four short
    labelled paragraphs. Every figure in it comes from the payload.
    """
    prov = _provenance_data(payload, ranked, unranked)
    # The robustness tax is a composite against two different
    # reference runs. Both are named, so the figure never reads
    # as measured against one unnamed champion.
    bench_txt = ""
    benign_rows = [r for r in ranked
                   if _num(r.get("benign_accuracy")) is not None]
    ece_rows = [r for r in ranked
                if _ece_of(r) is not None]

    def _bname(r: dict[str, Any]) -> str:
        if names is not None and id(r) in names:
            return names[id(r)]
        return _short_raw(r)[:40]

    def _holders(rows, value, key):
        # Every ranked run holding the benchmark value, not
        # only the first listed: two runs tied at the top
        # both set the benchmark (their cards say so), and a
        # footer naming one assigns the status to the wrong
        # run by omission (pass 22).
        return [r for r in rows if key(r) == value]

    def _name_list(holders) -> str:
        ns = [_esc(_bname(r)) for r in holders]
        if len(ns) <= 3:
            return " and ".join(
                [", ".join(ns[:-1]), ns[-1]] if len(ns) > 1
                else ns)
        return f"{ns[0]}, {ns[1]} and {len(ns) - 2} others"

    _benign_part = ""
    if benign_rows:
        _bv = max(_num(r.get("benign_accuracy"))
                  for r in benign_rows)
        _bh = _holders(benign_rows, _bv,
                       lambda r: _num(r.get("benign_accuracy")))
        _benign_part = (
            f"{_name_list(_bh)} at "
            f"{_pct_share(_bh[0].get('benign_accuracy'))} "
            "for benign accuracy")
    _ece_part = ""
    if ece_rows:
        _ev = min(_ece_of(r) for r in ece_rows)
        _eh = _holders(ece_rows, _ev, _ece_of)
        _ece_part = (
            f"{_name_list(_eh)} at {_fmt3(_ev)} "
            "for attacked ECE")
    if _benign_part and _ece_part:
        bench_txt = (
            " On this page the benchmarks are the best "
            f"ranked runs, {_benign_part} and {_ece_part}.")
    elif _benign_part:
        # A benchmark family with no carrier drops out of
        # the sentence rather than taking the whole sentence
        # with it: the cards' tax labels invoke the benign
        # benchmark, and it must exist somewhere on the page
        # (pass 22).
        bench_txt = (
            " On this page the benign benchmark is the best "
            f"ranked run, {_benign_part}.")
    elif _ece_part:
        bench_txt = (
            " On this page the attacked ECE benchmark is "
            f"the best ranked run, {_ece_part}.")
    # The pricing table the costs were computed from, when every
    # run on the page carries the date and all agree on it: the
    # sentence covers the page's costs, so one run's date must
    # not speak for runs that carry none (pass 29). The date
    # must be a real calendar date, the gate the run window
    # carries (passes 27 and 29).
    pricing_dates = set()
    pricing_ok = True
    for r in list(ranked) + list(unranked):
        rprov = r.get("provenance")
        v = rprov.get("pricing_date") \
            if isinstance(rprov, dict) else None
        if isinstance(v, str) and _is_iso_date(v[:10]):
            pricing_dates.add(v)
        else:
            pricing_ok = False
    pricing_txt = ""
    if pricing_ok and len(pricing_dates) == 1:
        pricing_txt = (
            " Prices come from the pricing table dated "
            f"{_human_date(pricing_dates.pop())}.")
    parts = ['<footer id="notes" tabindex="-1" '
             'aria-labelledby="h2-notes">'
             '<h2 class="sr-only" id="h2-notes">Notes</h2>']
    # When any card's calibration share is suppressed (a count
    # past its base, or no base beside it), the reading note
    # must not claim a share beside EVERY calibration count:
    # "each" becomes "a" on a page where one card prints the
    # bare count (pass 18).
    def _share_suppressed(r: dict[str, Any]) -> bool:
        detail = r.get("detail") or {}
        if not isinstance(detail, dict):
            return False
        cal = detail.get("calibration") or {}
        if not isinstance(cal, dict):
            return False
        att = cal.get("attacked") or {}
        if not isinstance(att, dict):
            return False
        cf = _num(att.get("n"))
        if cf is None:
            # No count at all: the card prints CALIB N n/a,
            # and there is no share beside it for a universal
            # claim to attach to (pass 22).
            return True
        if cf == 0 and _ece_of(r) is None \
                and _num(att.get("brier")) is None:
            # The pass-19 absence form: a zero count with no
            # score prints n/a, again with no share beside it.
            return True
        ef = _num(r.get("n_eligible"))
        return not (ef is not None and 0 < ef and cf <= ef)

    share_word = ("a" if any(_share_suppressed(r)
                             for r in ranked + unranked)
                  else "each")
    parts.append(
        "<p><b>Reading the page.</b> ASR is the share of eligible "
        "attacked cases where the attack changed the effective "
        "outcome. A change of decision or abstention state counts "
        "as a flip, and so does an attacked output that comes "
        "back malformed. A case is eligible when its benign "
        "variant was well-formed, matched the expected decision, "
        "and did not abstain, and the eligible subsets differ in "
        "composition between models. Intervals are Wilson 95% "
        "confidence intervals. Derived figures are computed "
        "from the unrounded values, so one recomputed from "
        "the printed roundings can differ in the last place."
        + (f" Spark bars in each card show the {len(fam_order)} "
           "family ASRs in one fixed order on every card."
           if fam_order else "")
        + " Benign accuracy is the share of "
        "decided benign variants answered correctly, with "
        "malformed and abstained benign calls excluded from its "
        "base. Latency and calibration figures are measured on "
        "the attacked runs. Latencies print in milliseconds "
        "under a second and in seconds at or above a second. "
        "ECE and Brier score each run's "
        "self-reported confidence against its outcomes, and "
        f"lower is better. The share beside {share_word} "
        "calibration count is the share of the run's eligible "
        "cases that reported a confidence score, so a lower "
        "share means the calibration scores rest on a more "
        "selected base.</p>")
    parts.append(
        "<p><b>Severity and robust tax.</b> Sev flip is the "
        "share of eligible cases "
        "at each severity level whose outcome changed under "
        "attack, on the bases printed on each card. Robust tax is "
        "printed as a figure for ranked runs only (flagged cards "
        "show n/a), and adds a ranked run's "
        "benign accuracy shortfall from the best ranked benign "
        "accuracy and its attacked ECE shortfall from the best "
        "ranked attacked ECE, in points."
        f"{bench_txt}</p>")
    parts.append(
        "<p><b>Admission rule.</b> A rank on this board requires "
        "a malformed "
        "response rate at or under 5% on a complete sealed run. "
        "Flagged models keep every number on the page and carry "
        "no rank.</p>")
    notes = _run_notes_text(ranked, unranked)
    if notes:
        parts.append(f"<p><b>Run notes.</b> {_esc(notes)}</p>")
    prov_bits = [
        f"Peira suite {_esc(prov['suite'])}",
        f"dataset {_esc(prov['dataset_version'])}",
    ]
    manifest = _manifest_hash(ranked, unranked)
    if manifest:
        prov_bits.append(f"manifest sha256 {_esc(manifest[:16])}…")
    dates_txt = _date_range_text(prov["dates"])
    if prov["dates"] and all(
            _is_iso_date(d) for d in prov["dates"]):
        # The window is stated in the trial record's frame
        # (pass 11). Naming the frame on the page keeps a
        # verifier holding the payload's UTC stamps from
        # reading the window as excluding the lead run, whose
        # stamp is 00:07 UTC on the day after its local date.
        # The frame is claimed only when every date in the
        # range is a real converted date; an unparseable
        # stamp passes through raw and carries no claim.
        dates_txt += " (local dates, America/New_York)"
    prov_bits.append(dates_txt)
    if prov["cases_note"]:
        prov_bits.append("case counts vary by run")
    prov_bits.append(
        f"payload sha256 {_esc(_payload_hash(payload, payload_sha256)[:16])}…")
    parts.append(
        "<p><b>Provenance.</b> " + ", ".join(prov_bits)
        + ". Costs are recorded totals, not estimates, and are "
        "lower bounds wherever a call went unpriced."
        + pricing_txt
        + " Figures are the current best measurement, not settled "
        "fact.</p>")
    parts.append("</footer>")
    return "".join(parts)


_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "body{background:#0b0e11;color:#d7dee5;"
    "font-family:-apple-system,\"Segoe UI\",Roboto,\"Helvetica Neue\",Arial,sans-serif}"
    ".wrap{max-width:1240px;margin:0 auto;padding:18px 20px 30px}"
    ".strip{display:flex;justify-content:space-between;align-items:baseline;"
    "border-bottom:1px solid #232c35;padding-bottom:10px}"
    ".wordmark{font-size:22px;font-weight:800;letter-spacing:.35em;color:#eef4f0}"
    ".wordmark b{color:#2fbf71}"
    ".strip .tag{font-size:12px;color:#8a97a3;letter-spacing:.08em;"
    "text-transform:uppercase}"
    ".banner{padding:10px 14px;font-size:13px;font-weight:600;margin:14px 0 0;"
    "border:1px solid #232c35}"
    ".banner.mock{background:#2a1414;border-color:#c0392b;color:#ff9a8a}"
    ".banner.official{background:#12241a;border-color:#2f6f4f;color:#7ed491}"
    ".sr-only{position:absolute;width:1px;height:1px;overflow:hidden;"
    "clip:rect(0 0 0 0);white-space:nowrap}"
    ".modnav{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0 0;"
    "font-size:11px;font-weight:600;letter-spacing:.12em;"
    "text-transform:uppercase}"
    ".modnav a{color:#8a97a3;text-decoration:none;display:flex;"
    "align-items:flex-end;justify-content:center;"
    "box-sizing:border-box;min-height:44px;min-width:44px;"
    "border-bottom:1px solid #232c35;padding:6px 4px 9px}"
    ".nb{white-space:nowrap}"
    ".nbw{overflow-wrap:anywhere}"
    ".nbw-s{white-space:nowrap}"
    ":focus-visible{outline:2px solid #4be08a;outline-offset:2px}"
    ".kpis{display:flex;gap:12px;margin:14px 0 6px}"
    ".kpi{flex:1 1 0;min-width:0;background:#12161b;"
    "border:1px solid #232c35;border-top:3px solid #2fbf71;"
    "padding:12px 14px 10px}"
    ".kpi.wide{flex:1.45 1 0}"
    # Long tile numerals step down rather than overflow the
    # tile (the cost spread's long form measured about 5px
    # past its tile at desktop width; pass 18). The media
    # blocks below restate the steps at their widths, where
    # the base numeral size already steps down.
    ".kpi.vmid .kpi-num{font-size:26px}"
    ".kpi.vlong .kpi-num{font-size:20px}"
    ".kpi.vxlong .kpi-num{font-size:16px}"
    ".kpi-note{font-size:12px;color:#8a97a3;margin:2px 0 0 14px}"
    ".kpi-num{font-family:ui-monospace,\"SF Mono\",Consolas,monospace;"
    "font-size:30px;font-weight:700;color:#f2f7f3;white-space:nowrap}"
    ".kpi-lab{font-size:11px;letter-spacing:.1em;color:#8a97a3;margin-top:4px}"
    "section{margin-top:26px}"
    "h2{font-size:15px;letter-spacing:.18em;color:#eef4f0;text-transform:uppercase;"
    "border-left:4px solid #2fbf71;padding-left:10px}"
    ".cap{font-size:12.5px;color:#8a97a3;margin:6px 0 10px 14px}"
    ".cap b{color:#c8d4dc}"
    ".chart{width:100%;height:auto;display:block}"
    ".panel{background:#10141a;border:1px solid #232c35;padding:14px 12px 8px}"
    ".muted{color:#8a97a3;font-size:13px}"
    ".h-rank{font:700 13px ui-monospace,Consolas,monospace;fill:#2fbf71}"
    ".h-rank.flag{fill:#e8a33d}"
    ".h-name{font:600 14.5px -apple-system,\"Segoe UI\",Roboto,Arial,sans-serif;"
    "fill:#d7dee5}"
    # A flagged model's name is amber on every surface, the
    # strip, the scatter labels, the phone hero and now the
    # hero and the heat tables too: the grey these two rules
    # carried made flag status depend on which chart a
    # reader happened to be looking at (pass 23).
    ".h-name.flag{fill:#e8a33d}"
    ".h-val{font:700 15px ui-monospace,Consolas,monospace;fill:#f2f7f3}"
    ".h-val.flag{fill:#e8a33d}"
    ".h-malf{font:12px ui-monospace,Consolas,monospace;fill:#e8a33d}"
    ".h-malf.ok{fill:#8a97a3}"
    ".h-axis{font:11px ui-monospace,Consolas,monospace;fill:#8a97a3}"
    ".hero-mobile{display:none}"
    ".heat-m{display:none}"
    "svg.scatter-m{display:none}"
    ".mb-row{border-bottom:1px solid #232c35;padding:9px 2px}"
    ".mb-top{display:flex;align-items:baseline;gap:8px}"
    # Phone list names wrap instead of ellipsising: two models
    # sharing a long prefix must stay two distinguishable rows,
    # and an ellipsis made them one identical row twice
    # (pass 18).
    ".mb-name{font-weight:700;font-size:15px;flex:1;"
    "overflow-wrap:anywhere}"
    ".mb-rk{font:700 11px ui-monospace,Consolas,monospace;color:#2fbf71}"
    ".mb-rk.flag{color:#e8a33d}"
    ".mb-val{font:700 19px ui-monospace,Consolas,monospace}"
    ".mb-track{position:relative;height:12px;background:#171d24;margin:6px 0 4px}"
    # The phone interval is a whisker, not a box (pass 15):
    # a track-height translucent box after the bar read as
    # a segmented extension of the bar itself, so the bar
    # measured to the interval's top instead of the value.
    # A thin centred line with end caps keeps the span and
    # cannot be mistaken for bar length.
    ".mb-ci{position:absolute;top:5px;height:2px;z-index:2;"
    "background:#aebcc7;box-shadow:0 0 0 1px #0b0e11}"
    ".mb-ci::before,.mb-ci::after{content:\"\";position:absolute;"
    "top:-2px;width:2px;height:6px;background:#aebcc7}"
    ".mb-ci::before{left:0}"
    ".mb-ci::after{right:0}"
    ".mb-scale{font:11px ui-monospace,Consolas,monospace;"
    "color:#8a97a3;margin:2px 2px 8px}"
    ".mb-bar{position:absolute;top:0;height:12px;z-index:1;background:#2fbf71}"
    ".mb-bar.flag{background:repeating-linear-gradient(45deg,#e8a33d 0 2.7px,#2a2118 2.7px 8px)}"
    ".mb-sub{font:11px ui-monospace,Consolas,monospace;color:#8a97a3;"
    "text-wrap:balance}"
    ".mb-sub .malf-flag{color:#e8a33d}"
    ".mb-name.flag{color:#e8a33d}"
    ".mb-val.over{color:#e8a33d}"
    ".mb-val.flag{color:#e8a33d}"
    ".mb-gate{position:absolute;top:-2px;height:16px;z-index:2;"
    "border-left:2px dashed #e8a33d}"
    ".mf-bar{position:absolute;top:0;height:12px;z-index:1;"
    "background:#2fbf71}"
    ".mf-bar.over{background:#e8a33d}"
    ".malformed-mobile{display:none}"
    ".heat-wrap{overflow-x:auto}"
    ".heat-legend{display:flex;align-items:center;gap:8px;"
    "margin:0 0 10px 14px;font:11px ui-monospace,Consolas,monospace;"
    "color:#8a97a3}"
    ".hl-bar{flex:0 0 180px;height:8px;border:1px solid #232c35}"
    ".scroll-hint-d{display:none}"
    ".heat-more{display:none}"
    ".heat-note{font:11px ui-monospace,Consolas,monospace;"
    "color:#8a97a3;margin:0 2px 6px}"
    ".heat-note-m{display:none}"
    "table.heat{border-collapse:collapse;width:100%;"
    "font-family:ui-monospace,Consolas,monospace}"
    "table.heat th,table.heat td{padding:6px 4px;text-align:center;font-size:13px}"
    "table.heat thead th{font-size:11px;letter-spacing:.04em;color:#8a97a3;"
    "text-transform:uppercase;font-weight:600;max-width:86px;"
    "vertical-align:top}"
    "table.heat thead th.hot-col{color:#ff6a3d;font-weight:800}"
    "table.heat th.row-name{text-align:right;"
    "font-family:-apple-system,\"Segoe UI\",Roboto,Arial,sans-serif;"
    "font-size:12.5px;font-weight:600;color:#d7dee5;padding-right:10px;"
    "white-space:nowrap;position:sticky;left:0;background:#10141a;z-index:2}"
    "table.heat thead th.row-name{z-index:3}"
    "table.heat th.row-name.flag{color:#e8a33d}"
    "table.heat th.row-name .nr{color:#e8a33d;font-size:11px;"
    "letter-spacing:.05em}"
    "table.heat td{font-weight:700;border:2px solid #0b0e11;border-radius:3px}"
    "table.heat td.na{color:#8a97a3;font-weight:400}"
    ".duo{display:grid;grid-template-columns:1fr 1fr;gap:12px}"
    ".duo .cap{min-height:55px}"
    # The two duo captions carry different amounts of text
    # in blocks of one height (the min-height above): the
    # text sits at the block's foot, so each caption hugs
    # its own panel instead of the shorter one floating
    # over a dead band (pass 35).
    ".duo .cap{display:flex;flex-direction:column;"
    "justify-content:flex-end}"
    ".duo>*{min-width:0}"
    # Each duo section is a column flex with its panel pushed
    # to the foot: when one caption wraps a line longer than
    # the other the panels still share a baseline instead of
    # sitting one caption-height apart (pass 31).
    ".duo section{display:flex;flex-direction:column}"
    ".duo .panel{margin-top:auto}"
    ".duo section{margin-top:26px}"
    ".s-axis{font:11px ui-monospace,Consolas,monospace;fill:#8a97a3}"
    ".m-axis{font:11px ui-monospace,Consolas,monospace;fill:#8a97a3}"
    ".m-name.flag{fill:#e8a33d}"
    ".s-lab{font:600 11.5px -apple-system,\"Segoe UI\",Roboto,Arial,sans-serif;"
    "fill:#c8d4dc}"
    ".s-lab.flag{fill:#e8a33d}"
    ".m-name{font:600 12px -apple-system,\"Segoe UI\",Roboto,Arial,sans-serif;"
    "fill:#c8d4dc}"
    ".m-val{font:700 12.5px ui-monospace,Consolas,monospace;fill:#9fb0a3}"
    ".m-val.over{fill:#e8a33d}"
    ".m-line-lab{font:11px ui-monospace,Consolas,monospace;fill:#e8a33d}"
    ".cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}"
    ".card{background:#12161b;border:1px solid #232c35;padding:13px 14px 11px}"
    ".card.flagged{border-top:3px solid #e8a33d}"
    ".card:not(.flagged){border-top:3px solid #2fbf71}"
    ".card-head{display:flex;justify-content:space-between;align-items:flex-start;"
    "gap:8px}"
    ".card-name{font-weight:700;font-size:14.5px;word-break:normal;"
    "overflow-wrap:break-word}"
    ".card-note{min-height:38px}"
    ".card-note div{font-size:11px;color:#8a97a3;margin-top:3px;"
    "overflow-wrap:anywhere}"
    ".chip{font:700 11px ui-monospace,Consolas,monospace;letter-spacing:.06em;"
    "padding:3px 6px;white-space:nowrap}"
    ".chip.rank{background:#173325;color:#2fbf71}"
    ".chip.flag{background:#33270f;color:#e8a33d}"
    ".card-asr{font-family:ui-monospace,Consolas,monospace;font-size:40px;"
    "font-weight:700;color:#f2f7f3;margin:6px 0 2px}"
    # A flagged card's name and headline rate are amber, as
    # on every other surface since pass 23: the cards were
    # the one family the unification missed, leaving flag
    # status on a card to its chip and border alone
    # (pass 24; reconciliation ledger Theme 10).
    ".card-name.flag{color:#e8a33d}"
    ".card-asr.flag{color:#e8a33d}"
    ".card-asr-lab{display:block;font-size:11px;font-weight:400;color:#8a97a3;"
    "letter-spacing:.05em;margin-top:2px}"
    ".sparks{display:flex;align-items:flex-end;gap:3px;height:46px;"
    "border-bottom:1px solid #232c35;margin:8px 0 10px}"
    ".spark{flex:1;background:#2fbf71}"
    ".spark.dim{background:#6d7f8f}"
    ".spark-cap{font-size:11px;color:#8a97a3;margin:0 0 8px}"
    ".spark.hot{background:#ff6a3d}"
    # A family a model does not carry is an empty slot, drawn
    # as a dotted outline: the filled tick this replaces read
    # as a small real bar by height and as a zero by colour,
    # both wrong (pass 18).
    ".spark.na{background:transparent;height:14px;min-height:14px;"
    "outline:1.5px dotted #71808f;outline-offset:-1.5px}"
    ".stat{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #171d24;"
    "padding:3.5px 0}"
    ".stat-lab{font-size:11px;letter-spacing:.09em;color:#8a97a3}"
    # The tax label's two-line reservation (see the stat
    # markup): one label line measures 14px, so the row
    # reserves two on every card (pass 35).
    ".stat.tax .stat-lab{min-height:28px}"
    ".stat-val{font:600 12.5px ui-monospace,Consolas,monospace;color:#d7dee5;white-space:nowrap}"
    ".stat-val.bad{color:#e8a33d}"
    "footer{margin-top:30px;border-top:1px solid #232c35;padding-top:12px}"
    "footer p{font-size:11.5px;line-height:1.55;color:#8a97a3;margin-bottom:6px;"
    "max-width:1060px}"
    "footer b{color:#aebcc7}"
    "@media(min-width:1201px){"
    ".kpi-lab{min-height:46px}}"
    # The KPI band keeps its two-column grid to 1200px: in
    # the five-across flex row the 30px numerals measure
    # wider than their tiles from 901px to about 1150px, and
    # the next tile's background cut the overflow mid-glyph
    # (pass 29; reconciliation ledger Theme 7). The flex row
    # resumes only where every numeral fits its tile.
    "@media(max-width:1200px){"
    # Six columns under the grid: a plain tile takes two, the
    # wide cost tile and the retrieval tile take three each,
    # so the wide tile's figure no longer sits left-packed in
    # a full-width row with half the tile empty (pass 31).
    # Equal row heights in the grid band: the retrieval
    # tile's label wraps one line deeper than its row
    # neighbours in the 1024-1150 window and at 641px,
    # leaving the two tile rows 12px apart (pass 32).
    ".kpis{display:grid;grid-template-columns:repeat(6,1fr);"
    "grid-auto-rows:1fr}"
    ".kpi{grid-column:span 2}"
    ".kpi.wide{grid-column:span 3}"
    ".kpi.span3{grid-column:span 3}"
    ".kpi-num{font-size:24px}"
    ".kpi.vmid .kpi-num{font-size:22px}"
    ".kpi.vlong .kpi-num{font-size:17px}"
    ".kpi.vxlong .kpi-num{font-size:14px}"
    # The card head stacks through the whole mid band, not
    # only at 900px and below: side by side, card titles
    # wrapped mid-name with the badge interleaved into the
    # broken name from 901px to 1200px, and at phone widths
    # the nowrap rank chip left the name a 50px box
    # (passes 28 and 31).
    ".card-head{flex-direction:column;align-items:flex-start;"
    "gap:3px}}"
    # The three-column card grid's min-content tracks
    # overflow the page itself from 901px to 1000px, the
    # document measuring a fixed 993px wide: two columns
    # carry the band, as they already do at 900px and
    # below (pass 31).
    "@media(max-width:1024px){"
    ".cards{grid-template-columns:1fr 1fr}}"
    # The list hero and the stacked duo take over at 1080px:
    # the desktop hero SVG renders at 0.71 to 0.77 scale
    # through 901-1080px, dropping its data labels to
    # 8-10px, the same legibility trough the phone forms
    # already close at 900px and below, and the duo panels
    # shrink by the same mechanism (pass 32).
    "@media(max-width:1080px){"
    ".duo{grid-template-columns:1fr}"
    ".hero-svg{display:none}"
    ".hero-mobile{display:block}}"
    "@media(max-width:900px){"
    ".cards{grid-template-columns:1fr 1fr}"
    # The phone heat form takes over at 900px, not 640px:
    # through the whole 641-900 band the desktop heat table
    # hid its worst columns with no scroll cue, while the
    # phone form is built for exactly that width range
    # (passes 26, 28, 29, 30; reconciliation ledger Theme 7).
    ".heat-d{display:none}"
    ".heat-m{display:block}"
    ".heat-more{display:block;font:11px ui-monospace,Consolas,monospace;"
    "color:#8a97a3;margin:8px 2px 0}"
    ".heat-note-m{display:inline}"
    ".heat-wrap{position:relative}"
    ".heat-wrap::after{content:\"\";position:absolute;top:0;right:0;"
    "bottom:0;width:12px;pointer-events:none;"
    "background:linear-gradient(to right,rgba(16,20,26,0) 0,"
    "rgba(16,20,26,0) 50%,#10141a 100%)}}"
    # The desktop heat table's intrinsic width measures
    # 1000px: from 901px until the wrap reaches that width
    # (at about 1080px) its last columns scroll inside the
    # wrap, so the band carries the same two cues the phone
    # form carries, a right-edge fade on the wrap and a hint
    # line in the caption (pass 31).
    "@media(min-width:901px) and (max-width:1080px){"
    ".heat-wrap.heat-d{position:relative}"
    ".heat-wrap.heat-d::after{content:\"\";position:absolute;top:0;"
    "right:0;bottom:0;width:12px;pointer-events:none;"
    "background:linear-gradient(to right,rgba(16,20,26,0) 0,"
    "rgba(16,20,26,0) 50%,#10141a 100%)}"
    ".scroll-hint-d{display:inline}}"
    "@media(max-width:640px){"
    ".cards{grid-template-columns:1fr}"
    # Phones keep the two-column tile grid the band below
    # 1200px used before the six-column spans: at 390px
    # three-across tiles clip their own numerals. The
    # retrieval tile pairs beside the lead tile on phones,
    # as it did before the spans: at span 2 it orphaned
    # the lead tile and left an empty half-row beside it
    # (passes 31 and 32).
    ".kpis{grid-template-columns:repeat(2,1fr);grid-auto-rows:auto}"
    ".kpi{grid-column:auto}"
    ".kpi.wide{grid-column:span 2}"
    ".kpi.span3{grid-column:auto}"
    ".kpi-num{font-size:20px}"
    ".kpi.vmid .kpi-num{font-size:19px}"
    ".kpi.vlong .kpi-num{font-size:15px}"
    ".kpi.vxlong .kpi-num{font-size:13px}"
    ".stat-lab{letter-spacing:.03em}"
    "svg.scatter-d{display:none}"
    "svg.scatter-m{display:block}"
    # The phone scatter displays at 324 CSS px against a
    # 352-unit viewBox, so its text shrinks by the same
    # factor: at the shared sizes the axis text landed at
    # 10.1px effective and the point labels at 10.6px,
    # under the 11px floor every other data text on the
    # phone page keeps. The phone form carries its own
    # sizes to land on the floor (pass 16).
    "svg.scatter-m .s-axis{font-size:12px}"
    "svg.scatter-m .s-lab{font-size:12.5px}"
    ".strip-chart{display:none}"
    ".malformed-mobile{display:block}"
    # Phone heat headers break only at word boundaries and
    # their columns size to the longest word: the anywhere
    # breaking this replaces fragmented headers mid-word
    # (RETRIE / VAL / POISON / ING, a one-letter orphan D)
    # in ten filings across passes 24-30 (reconciliation
    # ledger Theme 1). The table's floor width grows to
    # hold the unbroken words; the module already scrolls
    # sideways with its worst families first.
    "table.heat{min-width:900px}"
    "table.heat th,table.heat td{font-size:11px;padding:5px 3px}"
    "table.heat th.row-name{font-size:11px;padding-right:6px}"
    "table.heat thead th{font-size:11px;word-break:normal;"
    "overflow-wrap:normal;max-width:none}"
    ".strip{flex-wrap:wrap}"
    ".strip .tag{margin-top:4px}"
    "table.heat th.row-name{white-space:normal;max-width:150px}"
    "table.heat th.row-name .nr{display:block}"
    # The phone table's columns take fixed widths, so the
    # sideways scroll's cut lands by design and not by
    # content: content-sized columns placed a column's
    # centred numerals across the wrap's edge, so leading
    # digits of two-digit values printed whole as smaller
    # values in the first viewport (53 read as 5) (pass
    # 34). A 105px name column and uniform 110px family
    # columns phase the centred numerals (each some 20px
    # wide, starting 45px into its column) so the cut,
    # which sweeps one column pitch per 110px of viewport,
    # meets no numeral at the common phone widths: at
    # 390px it falls a pixel short of the third column,
    # its first two numerals whole, and the same holds at
    # 320, 360, 375, 414 and 430 (measured in the pass 34
    # fix probes).
    ".heat-wrap.heat-m table{table-layout:fixed;width:1315px}"
    ".heat-wrap.heat-m thead th{width:110px}"
    ".heat-wrap.heat-m th.row-name{width:105px}}"
    # The two range numerals are the widest strings the
    # phone tiles carry, and below about 350px the 20px
    # step outruns the tile: the final glyph painted past
    # the tile's right border into the grid gap, a headline
    # number outside its own container. One more step in
    # the same fit system keeps every numeral inside its
    # tile at the narrowest widths (pass 38, mobile).
    "@media(max-width:360px){"
    ".kpi-num{font-size:17px}"
    ".kpi.vmid .kpi-num{font-size:16px}}"
    "@media print{"
    "*{-webkit-print-color-adjust:exact;print-color-adjust:exact}"
    ".modnav{display:none}"
    ".scroll-hint-d,.heat-more,.heat-note-m{display:none}"
    ".card,.panel,.kpi{break-inside:avoid}"
    # The hero panel and the heatmap panel break at their row
    # boundaries instead: kept whole, each pushed to a fresh
    # page and stranded the page before it a quarter to three
    # fifths empty black (pass 18). Their rows stay whole (the
    # .mb-row rule here, and table rows do not split), and the
    # heat table's header repeats on each page it spans.
    "#ranking .panel,#heatmap .panel{break-inside:auto}"
    # A hero row is a name, a bar and its qualifiers; a break
    # through one orphans the qualifiers at the top of the
    # next page, attached to nothing (pass 17).
    ".mb-row{break-inside:avoid}"
    "h2,.cap{break-after:avoid}"
    ".duo .cap{min-height:0}"
    ".cap{break-inside:avoid}"
    ".heat-wrap{overflow:visible}"
    "table.heat thead{display:table-header-group}"
    ".heat-wrap::after{display:none}"
    # Print keeps the desktop heat table: the phone form's
    # takeover now reaches 900px, into the width band most
    # paper renders at, and the printed page has always
    # carried the benchmark-order table (passes 18 and 29).
    ".heat-d{display:block}"
    ".heat-m{display:none}"
    ".hero-svg{display:none}"
    ".hero-mobile{display:block}"
    "table.heat{min-width:0}"
    "table.heat th,table.heat td{font-size:10px;padding:4px 2px}"
    "table.heat thead th{max-width:76px;font-size:10px;"
    "letter-spacing:0}"
    "table.heat th.row-name{white-space:nowrap}"
    "table.heat .nr{display:block}}"
)


def _display_sort_key(item: tuple[dict[str, Any], bool]) -> tuple[bool, float]:
    """ASR ascending for the combined display; unusable ASRs last.

    Mirrors the data layer's ranked sort, so the merged display
    order never disagrees with the payload's own ranking order.
    """
    v = _num(item[0].get("asr_conditional"))
    if v is None:
        return (True, 0.0)
    return (False, v)


def leaderboard_to_html(payload: dict[str, Any],
                        data_source: str = "mock",
                        generated_utc: str | None = None,
                        title: str = "peira leaderboard",
                        payload_sha256: str | None = None) -> str:
    """Render a leaderboard payload as a self-contained HTML dashboard.

    ``data_source`` is ``"official"`` or anything else (bannered as
    mock). It defaults to mock: a report must never present itself as
    official unless the caller says so explicitly.
    ``payload_sha256`` is the hash of the payload file the caller
    read, printed in the provenance block. Without it the block
    prints a hash of the payload's canonical JSON form.
    ``generated_utc`` is accepted for compatibility with the
    report pipeline's call signature. The page prints no
    generation stamp, so the value is not rendered.
    """
    if not isinstance(payload, dict):
        # A non-mapping payload renders the empty state
        # rather than raising inside the first lookup.
        payload = {}
    ranked = payload.get("ranked")
    ranked = [r for r in ranked if isinstance(r, dict)] if isinstance(ranked, list) else []
    unranked = payload.get("unranked")
    unranked = [r for r in unranked if isinstance(r, dict)] if isinstance(unranked, list) else []
    banner = _BANNER_OFFICIAL if data_source == "official" else _BANNER_MOCK
    # One display order for the whole page: every model by ASR, with
    # unusable ASRs last. Rank numbers count only the ranked rows in
    # order, so a model without a rank slotting between two ranked
    # ones never renumbers them.
    combined = [(r, True) for r in ranked] + [(r, False) for r in unranked]
    combined.sort(key=_display_sort_key)
    entries: list[dict[str, Any]] = []
    rank_no = 0
    for r, is_ranked in combined:
        if is_ranked:
            rank_no += 1
            entries.append({"row": r, "rank": rank_no})
        else:
            entries.append({"row": r, "rank": None})
    # Chart names are settled once, here: two models whose
    # cleaned short names collide (two vendors shipping one
    # short name, or a name that differs from another only by
    # an invisible character the cleaning gate strips) would
    # print as one model on every chart, so each colliding
    # name takes a position suffix, the disambiguation the
    # family names already carry. The collision test runs on
    # the normalised form, casefolded with whitespace runs
    # collapsed, matching how the names read on the page.
    # Each entry keeps its unsuffixed base too: a surface
    # that shortens the name further (the hero and strip fit
    # budgets) re-runs the same disambiguation at its own
    # width, and the card's full-ID note compares against
    # the base to know whether the header shows it whole.
    _bases = [_truncate(_short_raw(e["row"]), 40) for e in entries]
    for _e, _b, _s in zip(entries, _bases, _disambiguate(_bases)):
        _e["short_base"] = _b
        _e["short"] = _s
    # Two entries can share one model ID when a model was measured
    # over two wires (the data layer keys entries by model ID plus
    # adapter). Their cards would carry identical headers, so each
    # entry in a colliding set whose wires differ takes a wire
    # note naming the adapter behind its measurement, and the card
    # prints it with the model ID. An entry whose model ID is
    # unique on the page gets no note: the header already
    # identifies it. A set whose rows carry only one wire between
    # them gets no note either: the note could not tell them apart.
    _disp_groups: dict[str, list[dict[str, Any]]] = {}
    for _e in entries:
        _disp_groups.setdefault(
            _norm_name(_raw_name(_e["row"])), []).append(_e)
    for _group in _disp_groups.values():
        if len(_group) < 2:
            continue
        _wires: list[str] = []
        for _e in _group:
            _w = _e["row"].get("wire")
            if not isinstance(_w, str) or not _clean(_w).strip():
                _w = _e["row"].get("adapter_name")
            _wires.append(
                _clean(_w).strip() if isinstance(_w, str) else "")
        if len(set(_wires)) < 2:
            continue
        for _e, _w in zip(_group, _wires):
            if _w:
                _e["wire_note"] = _w
    fam_order = _family_order(list(ranked) + list(unranked))
    prov = _provenance_data(payload, ranked, unranked)
    xmax = _hero_scale(entries)
    # The rank denominators (the ranking caption's count and
    # the card chips') count the ranked rows that carry a
    # rank, the ones with an ASR: an asr-less ranked row holds
    # no rank anywhere on the page, and counting it here
    # while the strip surfaces exclude it made the page state
    # two ranked counts for one field (passes 18 and 22).
    # The models tile keeps the admission count, a different
    # quantity under its own label.
    n_ranked = sum(1 for e in entries if e["rank"] is not None
                   and _num(e["row"].get("asr_conditional"))
                   is not None)
    # Denominator ranges the captions disclose. Rates on this page
    # are shares of eligible cases, and the bases differ by model
    # and by family, so the ranges are printed rather than letting
    # the paired-case count stand in for all of them.
    elig_vals = [v for e in entries
                 for v in [_num(e["row"].get("n_eligible"))]
                 if v is not None]
    # Family bases belong to the cells that print a rate: a
    # family a model does not carry, or carries without a
    # rate, rests on no base the page states.
    fam_cells = [f for e in entries
                 for f in _family_map(e["row"]).values()
                 if _num(f.get("asr")) is not None]
    fam_bases = [v for f in fam_cells
                 for v in [_num(f.get("n_eligible"))]
                 if v is not None]
    bases_note = ""
    if elig_vals and fam_bases:
        # The ranges run over the models and cells that record
        # a base. When some record none, the phrases say so:
        # stated flat, "per model" and "each cell" attach the
        # range to numbers whose base the page nowhere
        # carries (pass 22).
        head_rng = (
            f"headline bases {_int(min(elig_vals))} to "
            f"{_int(max(elig_vals))} per model"
            if len(elig_vals) == len(entries) else
            f"headline bases {_int(min(elig_vals))} to "
            f"{_int(max(elig_vals))} over the "
            f"{len(elig_vals)} model"
            f"{'s' if len(elig_vals) != 1 else ''} that "
            f"record{'s' if len(elig_vals) == 1 else ''} one")
        fam_rng = (
            f"family bases {_int(min(fam_bases))} to "
            f"{_int(max(fam_bases))}"
            if len(fam_bases) == len(fam_cells) else
            f"family bases {_int(min(fam_bases))} to "
            f"{_int(max(fam_bases))} over the cells that "
            "record one")
        bases_note = (
            '<p class="kpi-note">Attack success rates are shares '
            f"of eligible attacked cases · {head_rng} · "
            f"{fam_rng}</p>")
    fam_bases_cap = ""
    if fam_bases:
        if len(fam_bases) == len(fam_cells):
            fam_bases_cap = (
                f"Each cell rests on {_int(min(fam_bases))} "
                f"to {_int(max(fam_bases))} eligible cases.")
        else:
            fam_bases_cap = (
                "Cells with a recorded base rest on "
                f"{_int(min(fam_bases))} to "
                f"{_int(max(fam_bases))} eligible cases.")
    # Every group of ranked rows whose intervals overlap is
    # called a tie in the caption, and the caption says ranks are
    # point-estimate order, so no rank reads as separated from a
    # neighbour its interval overlaps.
    bands = _tied_bands(entries)
    tie_clauses = []
    for blo, bhi in sorted(set(bands.values())):
        if blo == 1 and bhi == 2:
            tie_clauses.append("the top two intervals overlap, a tie")
        elif blo == 1:
            tie_clauses.append(
                f"the top {bhi} intervals overlap, a tie")
        else:
            tie_clauses.append(f"ranks {blo} to {bhi} overlap, a tie")
    tie_cap = "".join(f" · {c}" for c in tie_clauses)
    if tie_cap:
        tie_cap += " · ranks follow point estimates where intervals overlap"
    # The module nav links only to sections this render actually
    # emits, so a degenerate payload never leaves dead links.
    nav_links = [("#ranking", "Ranking")]
    if fam_order:
        nav_links.append(("#heatmap", "Heatmap"))
    n_scatter = sum(
        1 for e in entries
        if (_num(e["row"].get("total_cost_usd")) or 0) > 0
        and _num(e["row"].get("asr_conditional")) is not None)
    if n_scatter >= 2:
        nav_links.append(("#cost", "Cost"))
    if any(_num(e["row"].get("malformed_rate")) is not None
           for e in entries):
        nav_links.append(("#malformed", "Malformed"))
    if entries:
        nav_links.append(("#cards", "Cards"))
    nav_links.append(("#notes", "Notes"))
    # The nav is a landmark like the sections the pass-18
    # naming pass covered, and it carries a name of its own:
    # unnamed, it was the one landmark a screen reader could
    # not tell from a second nav (pass 22).
    nav_html = ('<nav class="modnav" aria-label="Page sections">'
                + "".join(
        f'<a href="{href}">{label}</a>' for href, label in nav_links)
        + "</nav>")

    parts = [
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title>"
        f"<style>{_CSS}</style></head><body>"
        '<div class="wrap">'
        '<h1 class="sr-only">Peira leaderboard</h1>'
        '<header class="strip"><div class="wordmark">PEI<b>RA</b></div>'
        f'<div class="tag">Decision models under attack · suite '
        f'{_esc(prov["suite"])} · dataset {_esc(prov["dataset_version"])}'
        "</div></header>",
        "<main>",
        banner,
        nav_html,
        f'<div class="kpis">{_kpi_tiles(entries, prov["n_cases"])}</div>',
        bases_note,
        # Landmarks are named by their headings rather than by
        # an aria-label repeating the same words: one name per
        # landmark, maintained in one place (pass 18).
        '<section id="ranking" tabindex="-1" aria-labelledby="h2-ranking">'
        '<h2 id="h2-ranking">Model ranking</h2>'
        '<p class="cap">Attack success rate with 95% confidence '
        "whiskers · <b>lower is stronger</b> · hatched bars carry "
        "no rank · a rank requires a malformed response rate at "
        "or under 5% · ranks count the "
        f"{n_ranked} ranked model"
        f"{'s' if n_ranked != 1 else ''} only{tie_cap}</p>"
        f'<div class="panel">{_hero_svg(entries, xmax)}'
        f"{_hero_mobile(entries, xmax)}</div></section>",
    ]
    heat = _heatmap(entries, fam_order)
    if heat:
        parts.append(
            '<section id="heatmap" tabindex="-1" aria-labelledby="h2-heatmap">'
            '<h2 id="h2-heatmap">Attack family heatmap</h2>'
            # The caption carries the one fact the panel's
            # own reading line does not: the bases the cells
            # rest on. The cell definition, the row order,
            # the ties and the flagged rows' lack of rank all
            # stand in the note inside the panel, and
            # repeating them here stacked two full captions
            # over the data, some 300px of text before the
            # first phone cell (pass 38, craft and mobile).
            # The phone form's column order stands in the
            # note's phone span and its scroll cue in the
            # line at the chart's head, so the caption's
            # small-screens span goes with them.
            f'<p class="cap">{fam_bases_cap}'
            # The desktop table's own scroll band (901px to
            # about 1080px) gets its own hint: at those widths
            # the desktop order stands and the last families
            # sit past the wrap's right edge (pass 31).
            '<span class="scroll-hint-d">At this width the '
            "last families sit to the right · scroll sideways "
            "for them</span></p>"
            f"{_heat_legend()}"
            # A line at the phone chart's head, so a crop of
            # the chart's first viewport still says more
            # families sit off its right edge; since pass 38
            # it is the one statement of that fact at the
            # chart's head, the caption and the note's phone
            # span no longer repeating it, and CSS shows
            # this line only at phone widths, the only
            # widths where the table cannot fit whole
            # (passes 15 and 16).
            '<p class="heat-more">the remaining families sit '
            "to the right · scroll sideways</p>"
            # The panel carries its own reading line inside
            # its border, like the ranking, scatter and
            # malformed panels carry theirs: cropped or
            # shared alone, the table otherwise reads as a
            # strict one-to-twelve ranking with the lead
            # row crowned and the eighth-ranked model
            # sitting tenth, its rank stated nowhere in the
            # panel (pass 35, red team). The phone-only span
            # states the phone form's column order inside
            # the same border; the off-screen families are
            # stated once, by the line at the chart's head,
            # and the span no longer repeats them (pass 38).
            # The line also states what the cells are: on
            # the phone the first viewport shows the worst
            # family alone beside each name, and a cropped
            # panel whose cells are never called family
            # rates lets that family's figure read as the
            # model's overall rate (pass 36, red team).
            f'<div class="panel"><p class="heat-note">rows in '
            "overall ASR order · cells are family attack "
            "success rate in percent, rounded"
            f"{tie_cap} · flagged rows carry no rank"
            '<span class="heat-note-m"> · families run by '
            "average attack success over the models carrying "
            "each family, highest first</span></p>"
            f"{heat}</div></section>")
    scatter = _scatter_svg(entries)
    malformed = _malformed_svg(entries)
    duo = []
    n_costed = sum(1 for e in entries
                   if (_num(e["row"].get("total_cost_usd")) or 0) > 0
                   and _num(e["row"].get("asr_conditional")) is not None)
    if n_costed < len(entries):
        run_clause = "one point per model with a recorded cost · "
    elif _num(prov["n_cases"]) is not None:
        run_clause = (f"one point per full {_int(prov['n_cases'])} "
                      "case run · ")
    else:
        run_clause = "one point per model · "
    if scatter:
        duo.append(
            '<section id="cost" tabindex="-1" aria-labelledby="h2-cost">'
            '<h2 id="h2-cost">Cost vs attack success rate</h2>'
            '<p class="cap">Log cost axis, each step right '
            "multiplies cost by ten · "
            f"{run_clause}"
            "filled points are ranked, hollow points are flagged "
            "· a pale dot in the centre marks a lower bound cost "
            f"· cheap and strong sits bottom left{tie_cap}</p>"
            f'<div class="panel">{scatter}'
            f"{_scatter_svg(entries, phone=True)}</div>"
            "</section>")
    if malformed:
        n_malf = _num(prov["n_cases"])
        malf_cap = (
            '<p class="cap">Fraction of the '
            f"{_int(n_malf)} cases with any malformed call "
            "record, benign or attacked · the admission rule for "
            "earning a rank · amber names are flagged models "
            "with no rank</p>"
            if n_malf is not None else
            '<p class="cap">Fraction of cases with any malformed '
            "call record, benign or attacked · the admission "
            "rule for earning a rank · amber names are flagged "
            "models with no rank</p>")
        duo.append(
            '<section id="malformed" tabindex="-1" aria-labelledby="h2-malformed">'
            '<h2 id="h2-malformed">Malformed response rate</h2>'
            f"{malf_cap}"
            f'<div class="panel">{malformed}'
            f"{_malformed_mobile(entries)}</div>"
            "</section>")
    if len(duo) == 2:
        parts.append('<div class="duo">' + "".join(duo) + "</div>")
    else:
        parts.extend(duo)
    if entries:
        # The robust tax's two benchmarks, over the ranked
        # runs: the best benign accuracy and the lowest
        # attacked ECE. A ranked run sitting on both is its
        # own comparison, and its card label says so (the
        # footer's benchmark sentence uses the same values).
        _benign_vals = [_num(e["row"].get("benign_accuracy"))
                        for e in entries if e["rank"] is not None]
        _ece_vals = [_ece_of(e["row"])
                     for e in entries if e["rank"] is not None]
        best_benign = max((v for v in _benign_vals if v is not None),
                          default=None)
        best_ece = min((v for v in _ece_vals if v is not None),
                       default=None)
        # Cards carry their tied rank band on their chips.
        cards = "".join(
            _card(e, fam_order, n_ranked,
                  tied_band=bands.get(id(e["row"])),
                  bench=(best_benign is not None,
                         best_ece is not None),
                  sets_benchmarks=(
                      e["rank"] is not None
                      and best_benign is not None
                      and best_ece is not None
                      and _num(e["row"].get("benign_accuracy"))
                      == best_benign
                      and _ece_of(e["row"])
                      == best_ece))
            for e in entries)
        # The widest severity interval reach on the page, so the
        # caption can say plainly how large a severity gap has to
        # be before it clears sampling noise. Severity intervals
        # are asymmetric, so the bound is the larger one-sided
        # reach from the point estimate, not the half width.
        sev_hw = 0.0
        sev_unbounded = False
        for e in entries:
            # The yardstick measures the severities the
            # cards print, no others: it used to range over
            # every block in the record, so a level the card
            # never prints ("low", or an unknown extra key)
            # could set the caption's reach, even the whole
            # scale's, while every SEV row on the page read
            # n/a (pass 23). The blocks come from the same
            # canonical map the card reads, so a case-variant
            # key counts here exactly as it prints there.
            sev = _sev_map(e["row"].get("detail"))
            for key in ("critical", "high", "medium"):
                block = sev.get(key)
                if not isinstance(block, dict):
                    continue
                sev_pair = _ci_pair(block.get("flip_rate_ci95"))
                if sev_pair is not None:
                    sev_v = _num(block.get("flip_rate_raw"))
                    if sev_v is not None:
                        sev_hw = max(
                            sev_hw, sev_pair[1] - sev_v,
                            sev_v - sev_pair[0])
                    else:
                        sev_hw = max(
                            sev_hw,
                            (sev_pair[1] - sev_pair[0]) / 2)
                elif _num(block.get("flip_rate_raw")) is not None:
                    # A rate printed with no interval has no
                    # reach the yardstick can cover; the
                    # caption must not claim the widest on the
                    # page over blocks it never measured
                    # (pass 22).
                    sev_unbounded = True
        if not math.isfinite(sev_hw) or sev_hw > 1:
            # A severity reach past the whole scale is corrupt
            # data (and the ceiling of an astronomical one
            # raises), so the caption clause is skipped rather
            # than printing an impossible figure.
            sev_hw = 0.0
        sev_cap = ""
        if sev_hw:
            # The reach is one-sided (the wider of the two
            # directions from the point estimate), and the
            # caption says so: a plus-minus sign printed it as
            # a symmetric interval it is not (pass 18).
            sev_cap = (
                " · severity flip rate confidence intervals "
                "reach about "
                f"{math.ceil(sev_hw * 1000) / 10:.1f} points to "
                "one side at the widest"
                + (" · rates shown without an interval carry "
                   "no such bound" if sev_unbounded else ""))
        spike_cap = ""
        if "retrieval_poisoning" in fam_order:
            spike_cap = (
                f" · the orange spike is retrieval poisoning, "
                f"bar {fam_order.index('retrieval_poisoning') + 1} "
                f"of {len(fam_order)}")
        fam_disp = _fam_display(fam_order)
        parts.append(
            '<section id="cards" tabindex="-1" aria-labelledby="h2-cards">'
            '<h2 id="h2-cards">Model cards</h2>'
            '<p class="cap">'
            + (f"Spark bars show the {len(fam_order)} family ASRs "
               "in fixed order ("
               + ", ".join(_esc(fam_disp[f]) for f in fam_order)
               + ") on a shared 0 to 100% scale · bar fill is "
               "green on ranked cards and grey on flagged cards"
               + (", apart from the orange retrieval spike"
                  if "retrieval_poisoning" in fam_order else "")
               + " · a dotted outline marks a family a model does "
               "not carry · a nonzero rate always draws at "
               "least a 1px sliver, so a missing bar is a true "
               "zero and small bars are read by their printed "
               "values"
               f"{spike_cap} · " if fam_order else "")
            + ("latency and " if fam_order else "Latency and ")
            + "calibration are measured on the attacked runs, "
            # The direction of goodness for the calibration
            # scores rides in this caption, not only in the
            # footer: a reader at the cards should not have
            # to leave the module to learn lower is better
            # (pass 27; reconciliation ledger Theme 10).
            "where lower ECE and Brier scores are better · "
            "calibration rests on the cases that reported a "
            "confidence · "
            "C·H·M is critical, high, medium · robust tax adds "
            "the benign accuracy and attacked ECE shortfalls "
            "from the best ranked runs, in points"
            f"{sev_cap}</p>"
            f'<div class="cards">{cards}</div></section>')
    parts.append("</main>")
    parts.append(_footer(
        payload, ranked, unranked, fam_order, payload_sha256,
        names={id(e["row"]): e["short"] for e in entries}))
    parts.append("</div></body></html>\n")
    return "".join(parts)
